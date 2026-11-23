"""
MorseDecode command-line interface and main processing loop.

Entry point: `morsedecode` (defined in pyproject.toml).

Usage examples
--------------
    morsedecode --list-devices
    morsedecode                          # default device, default settings
    morsedecode --device "Microphone (Senary Audio), MME"
    morsedecode --file recording.wav
    morsedecode --stdin --sample-rate 44100 < recording.pcm
    morsedecode --config my.toml
    morsedecode --freq-min 600 --freq-max 900 --bin-width 50
"""

from __future__ import annotations

import datetime
import json
import os
from contextlib import closing
from pathlib import Path
from typing import TextIO

import click

from .config import Config, ConfigError, load_config
from .audio.source import create_source, list_devices
from .receiver import DecoderError, Receiver
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
        path = Path(self._path)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated = path.with_name(f"{path.stem}_{ts}{path.suffix}")
        index = 1
        while rotated.exists():
            rotated = path.with_name(f"{path.stem}_{ts}_{index}{path.suffix}")
            index += 1
        self.close()
        try:
            os.rename(path, rotated)
        finally:
            # A failed rename must not leave the active logger closed.
            self._open()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def run_decoder(cfg: Config, logger: ChannelLogger | None = None) -> None:
    source = create_source(
        device=cfg.input.device if cfg.input.device != "default" else None,
        file=cfg.input.file,
        stdin=cfg.input.stdin,
        sample_rate=cfg.audio.sample_rate,
        chunk_ms=50.0,
    )
    sample_rate = source.sample_rate
    with Receiver(sample_rate, cfg) as receiver:
        rows = [
            BinDisplayState(freq_hz=(band["low"] + band["high"]) // 2)
            for band in receiver.passbands
        ]
        display = Display(
            bin_states=rows,
            snr_bar_width=cfg.display.snr_bar_width,
            callsign_width=cfg.display.callsign_width,
            text_width=cfg.display.text_width,
            refresh_hz=cfg.display.refresh_hz,
            inactive_dim=cfg.display.inactive_dim,
            inactive_scroll_s=cfg.display.inactive_scroll_s,
        )

        def update(results: list[dict], final: bool = False) -> None:
            for row, result in zip(rows, results, strict=True):
                if result["frequency"] is not None:
                    row.freq_hz = round(result["frequency"])
                row.snr_db = result["signalDb"] if result["signalDb"] is not None else -20.0
                row.speed_wpm = result["wpm"] or 0.0
                row.last_callsign = result["callsign"]
                delta = result["delta"]
                row.text += delta
                if result["active"] or delta or (final and row.text):
                    row.mark_active()
                else:
                    row.mark_inactive()
                if logger is not None and delta:
                    logger.log(row.freq_hz, delta, row.snr_db, row.speed_wpm)
            display.refresh()

        with display, closing(source.stream()) as chunks:
            display.print_status(
                f"[cyan]MorseDecode[/cyan] | {len(rows)} channels | "
                f"{cfg.input.freq_min}-{cfg.input.freq_max} Hz | "
                f"SR {sample_rate} Hz | Ctrl-C to quit"
            )
            try:
                for chunk in chunks:
                    update(receiver.push(chunk))
            except KeyboardInterrupt:
                return
            update(receiver.finish(), final=True)


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
              help="Live audio input name from --list-devices (default: system default).")
@click.option("--file", "audio_file", default=None, metavar="FILE",
              help="Decode an audio file instead of live input.")
@click.option("--stdin", is_flag=True,
              help="Read signed 16-bit mono PCM from stdin.")
@click.option("--freq-min", default=None, type=int, metavar="HZ",
              help="Lower frequency edge in Hz (default: 400).")
@click.option("--freq-max", default=None, type=int, metavar="HZ",
              help="Upper frequency edge in Hz (default: 1000).")
@click.option("--bin-width", default=None, type=int, metavar="HZ",
              help="Override the core's maximum spacing between search tones.")
@click.option("--channel-width", default=None, type=int, metavar="HZ",
              help="Receiver passband width in Hz (default: 200).")
# Audio / detection
@click.option("--sample-rate", default=None, type=int, metavar="HZ",
              help="Sample rate for live or stdin input (defaults: device rate or 44100 Hz).")
@click.option("--on-db", default=None, type=float, metavar="DB",
              help="Override the core's signal-on threshold. Lower is more sensitive.")
@click.option("--off-db", default=None, type=float, metavar="DB",
              help="Override the core's signal-off threshold. Keep it below the signal-on threshold.")
# Decoder
@click.option("--beam-width", default=None, type=int, hidden=True)
@click.option("--speed-min", default=None, type=float, metavar="WPM",
              help="Override the core's minimum keying speed.")
@click.option("--speed-max", default=None, type=float, metavar="WPM",
              help="Override the core's maximum keying speed.")
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
    """Terminal interface for the shared CW (Morse code) decoder.

    Decodes simultaneous CW signals across a configurable frequency range
    from a live audio device, audio file, or stdin pipe.
    """
    if list_devs:
        click.echo(list_devices())
        return

    if beam_width is not None:
        click.echo("Warning: --beam-width is retired. The shared decoder searches each word without beam pruning.", err=True)

    # Build config with CLI overrides
    overrides = {
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
        "decoder__speed_min_wpm": speed_min,
        "decoder__speed_max_wpm": speed_max,
        "log__path": log_path,
        "log__format": log_format,
    }
    try:
        cfg = load_config(config_file=config_file, **overrides)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    # If --log flag given, enable logging
    if log_path:
        cfg.log.enabled = True

    # Validate
    if cfg.input.freq_min >= cfg.input.freq_max:
        raise click.UsageError("--freq-min must be less than --freq-max")
    if cfg.input.bin_width is not None and cfg.input.bin_width <= 0:
        raise click.UsageError("--bin-width must be positive")

    if cfg.input.channel_width_hz <= 0:
        raise click.UsageError("--channel-width must be positive")

    # Set up file logger
    logger: ChannelLogger | None = None
    if cfg.log.enabled:
        logger = ChannelLogger(
            cfg.log.path,
            fmt=cfg.log.format,
            rotate_mb=cfg.log.rotate_mb,
        )

    try:
        run_decoder(cfg, logger=logger)
    except DecoderError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if logger:
            logger.close()


if __name__ == "__main__":
    main()
