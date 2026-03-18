#!/usr/bin/env python3
"""
Decoder diagnostic: runs the exact production pipeline on synthetic Morse and
optionally on web1.wav, printing timing estimates, histogram fit quality, and
decoded text at each step so problems can be isolated.

Usage:
    python test_decoder.py            # synthetic tests only
    python test_decoder.py web1.wav   # also test on real recording
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from morse_decode.audio.normalizer import AGCNormalizer
from morse_decode.signal.fft import STFTProcessor
from morse_decode.signal.detector import GatedNoiseDetector
from morse_decode.timing.segmenter import RunLengthSegmenter
from morse_decode.timing.estimator import TimingEstimator
from morse_decode.decoder.buffer import RewindBuffer
from morse_decode.decoder.beam_search import BeamDecoder


# ---------------------------------------------------------------------------
# Morse code table
# ---------------------------------------------------------------------------

MORSE_TABLE: dict[str, str] = {
    "A": ".-",   "B": "-...", "C": "-.-.", "D": "-..",  "E": ".",
    "F": "..-.", "G": "--.",  "H": "....", "I": "..",   "J": ".---",
    "K": "-.-",  "L": ".-..", "M": "--",   "N": "-.",   "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.",  "S": "...",  "T": "-",
    "U": "..-",  "V": "...-", "W": ".--",  "X": "-..-", "Y": "-.--",
    "Z": "--..", "0": "-----","1": ".----","2": "..---","3": "...--",
    "4": "....-","5": ".....","6": "-....","7": "--...","8": "---..",
    "9": "----.", "/": "-..-.","?": "..--..","=": "-...-","AR": ".-.-.",
    "SK": "...-.-","BT": "-...-",
}


# ---------------------------------------------------------------------------
# Synthetic Morse audio generator
# ---------------------------------------------------------------------------

def generate_morse(
    text: str,
    freq_hz: float = 700.0,
    wpm: float = 25.0,
    sample_rate: int = 44100,
    noise_rms: float = 0.05,
    timing_jitter: float = 0.0,
) -> tuple[np.ndarray, int]:
    """
    Generate clean synthetic Morse code audio.

    Parameters
    ----------
    text        : message to encode (upper-case letters, digits, spaces)
    freq_hz     : carrier frequency in Hz
    wpm         : CW speed in words per minute (PARIS standard)
    sample_rate : audio sample rate
    noise_rms   : white noise amplitude (relative to tone amplitude = 1.0)
    timing_jitter : fractional random timing variation (0 = perfect, 0.1 = ±10%)
    """
    dit_ms = 1200.0 / wpm

    def dur_s(ms: float) -> float:
        jitter = 1.0 + timing_jitter * (np.random.rand() * 2 - 1) if timing_jitter else 1.0
        return ms * jitter / 1000.0

    def tone(duration_s: float) -> np.ndarray:
        n = int(duration_s * sample_rate)
        t = np.arange(n, dtype=np.float32) / sample_rate
        sig = np.sin(2 * np.pi * freq_hz * t)
        # 5ms raise/fall to avoid clicks
        fade = min(int(0.005 * sample_rate), n // 4)
        if fade > 0:
            sig[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            sig[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        return sig

    def silence(ms: float) -> np.ndarray:
        return np.zeros(int(dur_s(ms) * sample_rate), dtype=np.float32)

    segments: list[np.ndarray] = []
    # Lead-in silence so AGC doesn't see signal at time=0
    segments.append(np.zeros(int(0.5 * sample_rate), dtype=np.float32))

    first_word = True
    for word in text.upper().split():
        if not first_word:
            segments.append(silence(dit_ms * 7))   # word gap
        first_word = False
        first_char = True
        for ch in word:
            if not first_char:
                segments.append(silence(dit_ms * 3))  # letter gap
            first_char = False
            code = MORSE_TABLE.get(ch, "")
            first_elem = True
            for element in code:
                if not first_elem:
                    segments.append(silence(dit_ms))   # element gap
                first_elem = False
                d = dur_s(dit_ms if element == "." else dit_ms * 3)
                segments.append(tone(d))

    # Trailing silence
    segments.append(np.zeros(int(0.5 * sample_rate), dtype=np.float32))

    audio = np.concatenate(segments)
    if noise_rms > 0:
        audio += (np.random.randn(len(audio)) * noise_rms).astype(np.float32)
    return audio, sample_rate


# ---------------------------------------------------------------------------
# Full pipeline (mirrors cli.py ChannelState exactly)
# ---------------------------------------------------------------------------

class ChannelPipeline:
    """Runs the exact same pipeline as ChannelState in cli.py."""

    def __init__(self, hop_ms: float = 5.0, on_db: float = 24.0,
                 off_db: float = 20.0, debounce_ms: float = 2.0,
                 window_ms: float = 40.0) -> None:
        self.detector = GatedNoiseDetector(
            hop_ms=hop_ms, debounce_ms=debounce_ms,
            on_db=on_db, off_db=off_db,
        )
        self._min_mark_ms = debounce_ms * 2
        self._window_correction_ms = window_ms / 2.0
        self.segmenter = RunLengthSegmenter(silence_reset_s=5.0, on_db=on_db)
        self.estimator = TimingEstimator(
            speed_min_wpm=5.0, speed_max_wpm=50.0,
            histogram_bins=60, estimator_decay=0.97, outlier_pct=10.0,
        )
        self.buffer = RewindBuffer(max_seconds=10.0)
        self.decoder = BeamDecoder(beam_width=16, ambiguity_factor=1.5)
        self._hop_ms = hop_ms

    def feed(self, frames: np.ndarray) -> None:
        """Process one batch of (n_frames, n_bins) energy frames."""
        if frames.ndim == 1:
            frames = frames[:, np.newaxis]

        det_events = self.detector.process_frames(frames)

        # Apply Hann-window timing correction and filter micro-marks.
        filtered = []
        for ev in det_events:
            if not ev.is_mark:          # mark just ended: add correction
                ev.duration_ms += self._window_correction_ms
                if ev.duration_ms < self._min_mark_ms:
                    continue
            else:                       # space just ended: subtract correction
                ev.duration_ms = max(0.0, ev.duration_ms - self._window_correction_ms)
            filtered.append(ev)
        det_events = filtered

        if not det_events:
            return

        timing_events = self.segmenter.process(det_events)

        if self.segmenter.reset_needed:
            self.estimator.reset()
            self.decoder.reset()
            self.buffer.clear()
            self.segmenter.reset()

        for ev in timing_events:
            self.buffer.push(ev)

        estimate_changed = self.estimator.update(timing_events)
        estimate = self.estimator.estimate

        if estimate_changed and estimate.confident:
            self.decoder.rewind_and_replay(self.buffer.events(), estimate)
        elif estimate.confident:
            for ev in timing_events:
                self.decoder.process_event(ev, estimate)
        # else: no confident estimate yet — buffer for rewind

    def flush(self) -> None:
        """Commit any pending character by sending a virtual word-space event."""
        from morse_decode.decoder.buffer import TimingEvent
        est = self.estimator.estimate
        if not est.confident:
            return
        fake = TimingEvent(duration_ms=99999.0, is_mark=False, timestamp_s=0.0)
        self.decoder.process_event(fake, est)

    @property
    def text(self) -> str:
        return self.decoder.text

    @property
    def estimate(self):
        return self.estimator.estimate


def run_pipeline(
    audio: np.ndarray,
    sample_rate: int,
    freq_min: int = 400,
    freq_max: int = 1000,
    use_agc: bool = True,
    verbose: bool = True,
) -> tuple[str, object]:
    """Run full pipeline and return (decoded_text, final_estimate)."""

    agc = AGCNormalizer(sample_rate=sample_rate, window_s=10.0, target_rms=0.1)
    fft = STFTProcessor(
        sample_rate=sample_rate, window_ms=40.0, hop_ms=5.0,
        freq_min=freq_min, freq_max=freq_max, bin_width=25,
    )
    bins_per_ch = max(1, 200 // 25)   # 8 bins per 200 Hz channel
    all_centers = fft.bin_centers
    n_channels = len(all_centers) // bins_per_ch

    channels = [ChannelPipeline() for _ in range(n_channels)]

    chunk_size = int(0.05 * sample_rate)  # 50 ms chunks
    for start in range(0, len(audio), chunk_size):
        chunk = audio[start : start + chunk_size].astype(np.float32)
        if use_agc:
            chunk = agc.process(chunk)
        frames = fft.process_chunk(chunk)
        if frames.shape[0] == 0:
            continue
        for i, ch in enumerate(channels):
            ch.feed(frames[:, i * bins_per_ch : (i + 1) * bins_per_ch])

    # Flush pending characters in each channel
    for ch in channels:
        ch.flush()

    # Pick the channel with the most decoded text
    best = max(channels, key=lambda c: len(c.text))
    est = best.estimate

    if verbose:
        ch_centers = [
            int(np.mean(all_centers[i * bins_per_ch : (i + 1) * bins_per_ch]))
            for i in range(n_channels)
        ]
        print("  Channel estimates:")
        for i, ch in enumerate(channels):
            e = ch.estimate
            print(
                f"    {ch_centers[i]:4d} Hz | "
                f"dit={e.dit_ms:5.1f}ms dah={e.dah_ms:5.1f}ms "
                f"spd={e.speed_wpm:4.1f}wpm | "
                f"el_gap={e.element_gap_ms:5.1f}ms (s={e.element_gap_sigma_ms:4.1f}) "
                f"lt_gap={e.letter_gap_ms:5.1f}ms (s={e.letter_gap_sigma_ms:4.1f}) | "
                f"text='{ch.text[:60]}'"
            )

    return best.text, est


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_synthetic() -> None:
    np.random.seed(42)
    print("\n" + "=" * 70)
    print("SYNTHETIC MORSE TESTS")
    print("=" * 70)

    cases = [
        # (text, wpm, noise_rms, jitter)
        ("CQ DE W1AW",        25, 0.01, 0.0),   # clean reference
        ("RIG HERE IS",       25, 0.05, 0.0),   # the problem phrase
        ("RIG HERE IS",       25, 0.05, 0.15),  # same with bad fist (15% jitter)
        ("CQ CQ DE W1AW K",   20, 0.05, 0.0),   # longer message
        ("PARIS PARIS PARIS", 30, 0.05, 0.0),   # speed calibration word
    ]

    for text, wpm, noise, jitter in cases:
        dit_ms = 1200.0 / wpm
        print(f"\nInput: '{text}'  WPM={wpm}  noise={noise}  jitter={jitter}")
        print(f"  Expected timing: dit={dit_ms:.0f}ms  el_gap={dit_ms:.0f}ms  "
              f"lt_gap={dit_ms*3:.0f}ms  wd_gap={dit_ms*7:.0f}ms")

        audio, sr = generate_morse(text, wpm=wpm, noise_rms=noise,
                                   timing_jitter=jitter)
        decoded, est = run_pipeline(audio, sr, verbose=True)

        print(f"  Decoded: '{decoded.strip()}'")

        # Simple character error rate
        ref = text.upper().replace(" ", "")
        hyp = decoded.upper().replace(" ", "")
        hits = sum(a == b for a, b in zip(ref, hyp))
        cer = 1.0 - hits / max(len(ref), 1)
        print(f"  CER ~{cer:.0%}  (ref_len={len(ref)} hyp_len={len(hyp)})")


def test_web1(path: str) -> None:
    try:
        import soundfile as sf
    except ImportError:
        print("soundfile not installed — skipping web1.wav test")
        return

    if not Path(path).exists():
        print(f"  {path} not found — skipping")
        return

    print(f"\n{'='*70}")
    print(f"WEB1.WAV TEST: {path}")
    print("=" * 70)

    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio[:, 0]
    print(f"  Duration: {len(audio)/sr:.1f}s  SR={sr}")

    decoded, est = run_pipeline(audio, sr, verbose=True)
    print(f"\n  Final decoded: '{decoded.strip()}'")


# ---------------------------------------------------------------------------
# Space histogram diagnostic: print what the estimator sees
# ---------------------------------------------------------------------------

def diagnose_space_histogram(audio: np.ndarray, sample_rate: int) -> None:
    """Show exactly what the space histogram looks like mid-decode."""
    from morse_decode.timing.estimator import _gaussian_smooth, _find_peaks

    agc = AGCNormalizer(sample_rate=sample_rate, window_s=10.0, target_rms=0.1)
    fft = STFTProcessor(
        sample_rate=sample_rate, window_ms=40.0, hop_ms=5.0,
        freq_min=400, freq_max=1000, bin_width=25,
    )
    bins_per_ch = 8
    all_centers = fft.bin_centers
    n_channels = len(all_centers) // bins_per_ch

    channels = [ChannelPipeline() for _ in range(n_channels)]

    chunk_size = int(0.05 * sample_rate)
    for start in range(0, len(audio), chunk_size):
        chunk = agc.process(audio[start : start + chunk_size].astype(np.float32))
        frames = fft.process_chunk(chunk)
        if frames.shape[0] == 0:
            continue
        for i, ch in enumerate(channels):
            ch.feed(frames[:, i * bins_per_ch : (i + 1) * bins_per_ch])

    best = max(channels, key=lambda c: len(c.text))
    est_obj = best.estimator

    print("\n  Space histogram peak analysis:")
    hist = est_obj._space_hist.copy()
    centers = est_obj._bin_centers
    dit = est_obj.estimate.dit_ms

    print(f"    dit_ms={dit:.1f}  total space events: {hist.sum():.0f}")

    if dit > 0:
        min_gap = dit * 0.3
        max_gap = dit * 15.0
        min_idx = int(np.searchsorted(est_obj._bin_edges[1:], min_gap))
        max_idx = int(np.searchsorted(est_obj._bin_edges[1:], max_gap))
        # Show histogram before and after filter
        valid = centers[(centers >= min_gap) & (centers <= max_gap)]
        print(f"    valid range: {min_gap:.0f}ms – {max_gap:.0f}ms  "
              f"(bins {min_idx}–{max_idx})")
        h_filt = hist.copy()
        h_filt[:min_idx] = 0
        h_filt[max_idx:] = 0
        h_smooth = _gaussian_smooth(h_filt, sigma=1.5)
        peaks = _find_peaks(h_smooth)
        print(f"    peaks found: {len(peaks)}")
        for rank, pi in enumerate(peaks[:5]):
            print(f"      #{rank+1}: {centers[pi]:.1f}ms  count={h_smooth[pi]:.1f}")

        e = est_obj.estimate
        print(f"    fitted: el_gap={e.element_gap_ms:.1f}ms s={e.element_gap_sigma_ms:.1f}ms  "
              f"lt_gap={e.letter_gap_ms:.1f}ms s={e.letter_gap_sigma_ms:.1f}ms")
        print(f"    thresholds: el/lt={e.element_letter_threshold_ms:.1f}ms  "
              f"lt/wd={e.letter_word_threshold_ms:.1f}ms")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_synthetic()

    wav = sys.argv[1] if len(sys.argv) > 1 else "web1.wav"
    test_web1(wav)

    # Also run space histogram diagnostic on synthetic "RIG HERE IS"
    np.random.seed(42)
    print("\n" + "=" * 70)
    print("SPACE HISTOGRAM DIAGNOSTIC (RIG HERE IS @ 25 WPM)")
    print("=" * 70)
    audio, sr = generate_morse("RIG HERE IS", wpm=25, noise_rms=0.05)
    diagnose_space_histogram(audio, sr)
