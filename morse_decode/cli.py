"""
MorseDecode command-line interface and main processing loop.

Entry point: `morsedecode` (defined in pyproject.toml).

Usage examples
--------------
    morsedecode --list-devices
    morsedecode                          # default device, default settings
    morsedecode --device 3
    morsedecode --file recording.wav
    morsedecode --stdin                  # pipe from rtl_fm, gqrx, etc.
    morsedecode --config my.toml
    morsedecode --freq-min 600 --freq-max 900 --bin-width 50
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import TextIO

import click
import numpy as np

from .config import Config, InputConfig, load_config, compute_bin_centers
from .audio.source import create_source, list_devices, AudioSource
from .audio.normalizer import AGCNormalizer
from .signal.fft import STFTProcessor
from .signal.detector import GatedNoiseDetector
from .timing.segmenter import RunLengthSegmenter
from .timing.estimator import TimingEstimator
from .decoder.buffer import RewindBuffer, TimingEvent
from .decoder.beam_search import BeamDecoder
from .output.display import Display, BinDisplayState


# ---------------------------------------------------------------------------
# Logger (file logging)
# ---------------------------------------------------------------------------

class ChannelLogger:
    """Append decoded output to a log file in text or jsonl format."""

    def __init__(self, path: str, fmt: str = "text", rotate_mb: int = 10) -> None:
        self._path = path
        self._fmt = fmt
        self._rotate_mb = rotate_mb * 1024 * 1024
        self._fh: TextIO | None = None
        self._open()

    def _open(self) -> None:
        self._fh = open(self._path, "a", encoding="utf-8")

    def log(self, freq_hz: int, text: str, snr_db: float, speed_wpm: float) -> None:
        if not text.strip() or self._fh is None:
            return
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        if self._fmt == "jsonl":
            line = json.dumps({
                "timestamp": ts,
                "freq_hz": freq_hz,
                "text": text,
                "snr_db": round(snr_db, 1),
                "speed_wpm": round(speed_wpm, 1),
            })
        else:
            line = f"{ts}  {freq_hz:5d}Hz  {speed_wpm:5.1f}wpm  {text}"
        self._fh.write(line + "\n")
        self._fh.flush()
        # Rotate if needed
        if self._rotate_mb > 0:
            try:
                if os.path.getsize(self._path) > self._rotate_mb:
                    self._rotate()
            except OSError:
                pass

    def _rotate(self) -> None:
        if self._fh:
            self._fh.close()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated = self._path.replace(".log", f"_{ts}.log")
        os.rename(self._path, rotated)
        self._open()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# ---------------------------------------------------------------------------
# Per-channel processing state
# ---------------------------------------------------------------------------

class ChannelState:
    """Holds all processing state for one frequency bin."""

    def __init__(
        self,
        freq_hz: int,
        hop_ms: float,
        cfg: Config,
    ) -> None:
        self.freq_hz = freq_hz
        self.detector = GatedNoiseDetector(
            hop_ms=hop_ms,
            debounce_ms=cfg.audio.debounce_ms,
            on_db=cfg.audio.on_db,
            off_db=cfg.audio.off_db,
        )
        self._min_mark_ms = cfg.audio.debounce_ms * 2  # discard sub-noise marks
        self.segmenter = RunLengthSegmenter(
            silence_reset_s=cfg.decoder.silence_reset_s,
            on_db=cfg.audio.on_db,
        )
        self.estimator = TimingEstimator(
            speed_min_wpm=cfg.decoder.speed_min_wpm,
            speed_max_wpm=cfg.decoder.speed_max_wpm,
            histogram_bins=cfg.decoder.histogram_bins,
            estimator_decay=cfg.decoder.estimator_decay,
            outlier_pct=cfg.decoder.outlier_pct,
        )
        self.rewind_buffer = RewindBuffer(
            max_seconds=cfg.decoder.rewind_buffer_s,
        )
        self.decoder = BeamDecoder(
            beam_width=cfg.decoder.beam_width,
            ambiguity_factor=cfg.decoder.ambiguity_factor,
        )
        self.display_state = BinDisplayState(freq_hz=freq_hz)
        self._prev_text_len: int = 0
        # The Hann-window STFT introduces a systematic timing bias: ON detection
        # fires on time but OFF detection fires window_ms/2 early (the carrier
        # fades out of the high-weight centre of the window before it actually
        # ends).  Correct by adding window_ms/2 to each measured mark duration
        # and subtracting window_ms/2 from each measured space duration.
        self._window_correction_ms: float = cfg.audio.window_ms / 2.0

    def _flush(self) -> None:
        """Commit any pending character by sending a virtual word-space event."""
        est = self.estimator.estimate
        if not est.confident:
            return
        fake = TimingEvent(duration_ms=99999.0, is_mark=False, timestamp_s=0.0)
        self.decoder.process_event(fake, est)

    def process_energy_frames(self, frames: np.ndarray) -> None:
        """Drive the full pipeline for new energy frames from this channel.

        frames : shape (n_time_frames,) or (n_time_frames, n_bins_per_channel)
            When multiple bins are provided the detector uses the max bin as
            the signal estimate and the min bin for noise tracking.
        """
        if frames.ndim == 1:
            frames = frames[:, np.newaxis]
        det_events = self.detector.process_frames(frames)

        # Apply Hann-window timing correction and filter micro-marks.
        # DetectorEvent.is_mark=False → signal just went OFF → duration is a mark.
        # DetectorEvent.is_mark=True  → signal just went ON  → duration is a space.
        filtered: list = []
        for ev in det_events:
            if not ev.is_mark:
                # Mark just ended: OFF fires window_ms/2 early → add correction
                ev.duration_ms += self._window_correction_ms
                if ev.duration_ms < self._min_mark_ms:
                    continue   # drop spurious micro-marks
            else:
                # Space just ended: started window_ms/2 early → subtract correction
                ev.duration_ms = max(0.0, ev.duration_ms - self._window_correction_ms)
            filtered.append(ev)
        det_events = filtered

        if not det_events:
            # No state transitions — update display state from current detector
            self.display_state.active = self.detector.is_active
            self.display_state.snr_db = self.detector.snr_db
            return

        # Convert detector events → timing events
        timing_events = self.segmenter.process(det_events)

        # Handle silence reset — flush pending char before wiping decoder state
        if self.segmenter.reset_needed:
            self._flush()
            self.estimator.reset()
            self.decoder.reset()
            self.rewind_buffer.clear()
            self.segmenter.reset()
            self.display_state.mark_inactive()
            self._prev_text_len = 0  # decoder text reset; compare against 0 for new text

        # Buffer all timing events for potential rewind
        for ev in timing_events:
            self.rewind_buffer.push(ev)

        # Feed estimator; check if speed changed significantly
        estimate_changed = self.estimator.update(timing_events)

        estimate = self.estimator.estimate

        if estimate_changed and estimate.confident:
            # Replay buffered events with the updated estimate.
            # Starting from decoder.text (empty until first confidence) ensures
            # the rewind always replays from a clean state on first confidence.
            buffered = self.rewind_buffer.events()
            self.decoder.rewind_and_replay(buffered, estimate)
        elif estimate.confident:
            # Incremental decode once we have a confident estimate
            for ev in timing_events:
                self.decoder.process_event(ev, estimate)
        # else: no confident estimate yet — events stay buffered for the rewind

        # Update display state
        ds = self.display_state
        ds.snr_db = self.detector.snr_db
        ds.speed_wpm = estimate.speed_wpm
        ds.last_callsign = self.decoder.last_callsign

        new_text = self.decoder.text
        if new_text and len(new_text) > self._prev_text_len:
            ds.text = new_text
            self._prev_text_len = len(new_text)
            ds.mark_active()
        elif not self.detector.is_active:
            ds.mark_inactive()


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def run_decoder(cfg: Config, logger: ChannelLogger | None = None) -> None:
    """Main decode loop — runs until interrupted."""

    # --- Audio source ---
    source = create_source(
        device=cfg.input.device if cfg.input.device != "default" else None,
        file=cfg.input.file,
        stdin=cfg.input.stdin,
        sample_rate=cfg.audio.sample_rate,
        chunk_ms=50.0,
    )
    sample_rate = source.sample_rate

    # --- AGC ---
    normalizer: AGCNormalizer | None = None
    if cfg.audio.agc_enabled:
        normalizer = AGCNormalizer(
            sample_rate=sample_rate,
            window_s=cfg.audio.agc_window_s,
            target_rms=cfg.audio.agc_target_rms,
        )

    # --- FFT ---
    fft = STFTProcessor(
        sample_rate=sample_rate,
        window_ms=cfg.audio.window_ms,
        hop_ms=cfg.audio.hop_ms,
        freq_min=cfg.input.freq_min,
        freq_max=cfg.input.freq_max,
        bin_width=cfg.input.bin_width,
    )

    # --- Group fine FFT bins into wider decoding channels ---
    # Each channel uses channel_width_hz / bin_width consecutive FFT bins.
    # The detector takes all bins in the channel: max = signal, min = noise.
    bins_per_ch = max(1, cfg.input.channel_width_hz // cfg.input.bin_width)
    all_centers = fft.bin_centers
    n_channels = len(all_centers) // bins_per_ch
    channel_centers = [
        int(np.mean(all_centers[i * bins_per_ch:(i + 1) * bins_per_ch]))
        for i in range(n_channels)
    ]

    # --- Per-channel state ---
    channels: list[ChannelState] = [
        ChannelState(freq_hz, fft.hop_ms, cfg)
        for freq_hz in channel_centers
    ]
    bin_display_states = [ch.display_state for ch in channels]

    # --- Display ---
    display = Display(
        bin_states=bin_display_states,
        snr_bar_width=cfg.display.snr_bar_width,
        callsign_width=cfg.display.callsign_width,
        text_width=cfg.display.text_width,
        refresh_hz=cfg.display.refresh_hz,
        inactive_dim=cfg.display.inactive_dim,
        inactive_scroll_s=cfg.display.inactive_scroll_s,
    )

    # --- Log tracking (only log newly decoded chars) ---
    logged_text_lens: dict[int, int] = {ch.freq_hz: 0 for ch in channels}

    with display:
        display.print_status(
            f"[cyan]MorseDecode[/cyan] | "
            f"{n_channels} channels ({cfg.input.channel_width_hz}Hz wide), "
            f"{cfg.input.freq_min}-{cfg.input.freq_max} Hz, "
            f"SR {sample_rate} Hz | Ctrl-C to quit"
        )
        try:
            for chunk in source.stream():
                # AGC
                if normalizer is not None:
                    chunk = normalizer.process(chunk)

                # FFT: shape (n_frames, n_bins)
                energy_frames = fft.process_chunk(chunk)
                if energy_frames.shape[0] == 0:
                    continue

                # Per-channel processing (multi-bin slice per channel)
                for i, ch in enumerate(channels):
                    start = i * bins_per_ch
                    ch.process_energy_frames(energy_frames[:, start:start + bins_per_ch])

                    # File logging of newly decoded text
                    if logger is not None:
                        prev_len = logged_text_lens[ch.freq_hz]
                        new_text = ch.display_state.text
                        if len(new_text) > prev_len:
                            delta = new_text[prev_len:]
                            if delta.strip():
                                logger.log(
                                    ch.freq_hz,
                                    delta,
                                    ch.display_state.snr_db,
                                    ch.display_state.speed_wpm,
                                )
                            logged_text_lens[ch.freq_hz] = len(new_text)

                display.refresh()

        except KeyboardInterrupt:
            pass
        else:
            # End of file — flush any pending character in each channel
            for ch in channels:
                ch._flush()

    if logger:
        logger.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "config_file", default=None, metavar="FILE",
              help="Path to a TOML config file.")
@click.option("--list-devices", "list_devs", is_flag=True,
              help="List available audio input devices and exit.")
# Input
@click.option("--device", default=None, metavar="DEVICE",
              help="Audio device name or index (default: system default).")
@click.option("--file", "audio_file", default=None, metavar="FILE",
              help="Decode an audio file instead of live input.")
@click.option("--stdin", is_flag=True,
              help="Read raw PCM audio from stdin.")
@click.option("--freq-min", default=None, type=int, metavar="HZ",
              help="Lower frequency edge in Hz (default: 400).")
@click.option("--freq-max", default=None, type=int, metavar="HZ",
              help="Upper frequency edge in Hz (default: 1000).")
@click.option("--bin-width", default=None, type=int, metavar="HZ",
              help="FFT bin width in Hz (default: 25).")
@click.option("--channel-width", default=None, type=int, metavar="HZ",
              help="Decoding channel width in Hz; groups multiple FFT bins (default: 200).")
# Audio / detection
@click.option("--sample-rate", default=None, type=int, metavar="HZ",
              help="Sample rate for stdin input (default: auto).")
@click.option("--on-db", default=None, type=float, metavar="DB",
              help="Signal ON threshold: 10*log10(bin1/noise_ref) in dB (default: 24).")
@click.option("--off-db", default=None, type=float, metavar="DB",
              help="Signal OFF threshold in dB; must be < --on-db (default: 20).")
# Decoder
@click.option("--beam-width", default=None, type=int, metavar="N",
              help="Beam search width (default: 16).")
@click.option("--speed-min", default=None, type=float, metavar="WPM",
              help="Minimum CW speed in WPM (default: 5).")
@click.option("--speed-max", default=None, type=float, metavar="WPM",
              help="Maximum CW speed in WPM (default: 50).")
# Log
@click.option("--log", "log_path", default=None, metavar="FILE",
              help="Enable file logging to FILE.")
@click.option("--log-format", default=None, type=click.Choice(["text", "jsonl"]),
              help="Log format: text (default) or jsonl.")
@click.version_option(package_name="morsedecode")
def main(
    config_file: str | None,
    list_devs: bool,
    device: str | None,
    audio_file: str | None,
    stdin: bool,
    freq_min: int | None,
    freq_max: int | None,
    bin_width: int | None,
    channel_width: int | None,
    sample_rate: int | None,
    on_db: float | None,
    off_db: float | None,
    beam_width: int | None,
    speed_min: float | None,
    speed_max: float | None,
    log_path: str | None,
    log_format: str | None,
) -> None:
    """Multi-channel CW (Morse code) decoder with FFT frequency-bin analysis.

    Decodes simultaneous CW signals across a configurable frequency range
    from a live audio device, audio file, or stdin pipe.
    """
    if list_devs:
        click.echo(list_devices())
        return

    # Build config with CLI overrides
    cfg = load_config(
        config_file=config_file,
        **{k: v for k, v in {
            "input__device": device,
            "input__file": audio_file,
            "input__stdin": stdin or None,
            "input__freq_min": freq_min,
            "input__freq_max": freq_max,
            "input__bin_width": bin_width,
            "input__channel_width_hz": channel_width,
            "audio__sample_rate": sample_rate,
            "audio__on_db": on_db,
            "audio__off_db": off_db,
            "decoder__beam_width": beam_width,
            "decoder__speed_min_wpm": speed_min,
            "decoder__speed_max_wpm": speed_max,
            "log__path": log_path,
            "log__format": log_format,
        }.items() if v is not None},
    )

    # If --log flag given, enable logging
    if log_path:
        cfg.log.enabled = True

    # Validate
    if cfg.input.freq_min >= cfg.input.freq_max:
        raise click.UsageError("--freq-min must be less than --freq-max")
    if cfg.input.bin_width <= 0:
        raise click.UsageError("--bin-width must be positive")

    # Set up file logger
    logger: ChannelLogger | None = None
    if cfg.log.enabled:
        logger = ChannelLogger(
            cfg.log.path,
            fmt=cfg.log.format,
            rotate_mb=cfg.log.rotate_mb,
        )

    run_decoder(cfg, logger=logger)


if __name__ == "__main__":
    main()
