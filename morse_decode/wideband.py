"""Find and decode CW carriers in Gqrx IQ, USB and receiver-audio recordings."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import fft, ndimage, signal

from .config import Config, InputConfig
from .receiver import DecoderError, Receiver

AUDIO_RATE = 8000
TONE_HZ = 700
FILTER_HZ = 220
SCAN_SECONDS = 4
EXTRACT_SECONDS = 8
GQRX_NAME = re.compile(
    r"gqrx_(?P<date>\d{8})_(?P<time>\d{6})_(?P<tuned>\d+)"
    r"(?:_(?P<rate>\d+)_fc|-(?P<mode>IQ|USB)-(?P<width>\d+(?:_\d+)?)k(?P<noagc>-noagc)?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Capture:
    path: Path
    mode: str
    sample_rate: int
    frames: int
    tuned_hz: int | None
    recorded_utc: str | None
    filter_hz: int | None
    gqrx_agc: bool | None

    @classmethod
    def open(cls, path: Path, mode: str | None = None, tuned_hz: int | None = None) -> Capture:
        name = GQRX_NAME.fullmatch(path.stem)
        fields = name.groupdict() if name else {}
        stamp = None
        if name:
            stamp = datetime.strptime(name["date"] + name["time"], "%Y%m%d%H%M%S")
            stamp = stamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            if tuned_hz is None:
                tuned_hz = int(name["tuned"])
        if path.suffix.lower() == ".raw":
            if not fields.get("rate") or mode not in (None, "iq"):
                raise ValueError("Raw IQ requires a Gqrx gqrx_YYYYMMDD_HHMMSS_HZ_RATE_fc.raw filename")
            size = path.stat().st_size
            if size % 8 or not size or int(fields["rate"]) < 1000:
                raise ValueError("Expected complete complex float32 samples in the raw IQ file")
            return cls(path, "iq", int(fields["rate"]), size // 8, tuned_hz, stamp, None, None)
        info = sf.info(path)
        if not info.frames or info.samplerate < 1000:
            raise ValueError("Expected a nonempty recording sampled at 1 kHz or higher")
        mode = mode or (fields.get("mode") or "audio").lower()
        if mode == "iq" and info.channels != 2:
            raise ValueError("IQ audio requires two channels, I followed by Q")
        width = fields.get("width")
        return cls(path, mode, info.samplerate, info.frames, tuned_hz, stamp,
                   round(float(width.replace("_", ".")) * 1000) if width else None,
                   not bool(fields["noagc"]) if width else None)

    def read(self, first: int, end: int) -> np.ndarray:
        if self.path.suffix.lower() == ".raw":
            raw = np.memmap(self.path, dtype="<c8", mode="r", offset=first * 8, shape=(end - first,))
            return np.asarray(raw)
        samples, _ = sf.read(self.path, start=first, stop=end, dtype="float32", always_2d=True)
        if self.mode == "iq":
            return samples[:, 0] + 1j * samples[:, 1]
        return samples[:, 0]

    def search_range(self) -> tuple[float, float]:
        edge = self.sample_rate / 2
        if self.mode == "iq":
            edge = min(edge, self.filter_hz / 2) if self.filter_hz else edge
            return -edge, edge
        if self.mode == "usb":
            return 0, min(edge, self.filter_hz or edge)
        return 100, min(3000, edge)

    def rf_hz(self, offset: float) -> float | None:
        if self.mode != "audio" and self.tuned_hz is not None:
            return round(self.tuned_hz + offset, 1)
        return None


@dataclass(frozen=True)
class Candidate:
    offset_hz: float
    evidence_db: float | None


def scan_block(capture: Capture, first: int, nfft: int, hop: int,
               bins: np.ndarray, workers: int) -> np.ndarray:
    samples = capture.read(first, min(first + SCAN_SECONDS * capture.sample_rate + nfft - hop, capture.frames))
    if len(samples) < nfft:
        return np.zeros(len(bins))
    frames = np.lib.stride_tricks.sliding_window_view(samples, nfft)[::hop]
    taper = signal.windows.hann(nfft, sym=False).astype(np.float32)
    transformed = fft.fft if capture.mode == "iq" else fft.rfft
    # Bound the FFT scratch space even for native captures at the SDR sample rate.
    batch = max(1, 2**20 // nfft)
    spectrum = np.empty((len(frames), len(bins)), dtype=np.float32)
    for start in range(0, len(frames), batch):
        windowed = frames[start:start + batch] * taper
        spectrum[start:start + batch] = np.abs(transformed(windowed, axis=1, workers=workers)[:, bins]) ** 2
    # Compare a carrier to the noise on both sides at the same time.
    noise = ndimage.median_filter(spectrum, size=(1, 17), mode="nearest")
    contrast = 10 * np.log10((spectrum + 1e-15) / (noise + 1e-15))
    # A short burst can survive even in an otherwise idle recording.
    return np.percentile(contrast, 84, axis=0)


def find_carriers(capture: Capture, limits: tuple[float, float], min_db: float = 10,
                  workers: int = 1) -> list[Candidate]:
    rate = capture.sample_rate
    nfft = 2 ** round(math.log2(rate / 10))
    hop = max(nfft // 2, round(rate * 0.04))
    nfft = max(nfft, hop)
    iq = capture.mode == "iq"
    frequencies = fft.fftfreq(nfft, 1 / rate) if iq else fft.rfftfreq(nfft, 1 / rate)
    order = np.argsort(frequencies)
    hz = frequencies[order]
    low, high = limits
    order = order[(hz >= low - 150) & (hz <= high + 150)]
    hz = frequencies[order]
    evidence = np.zeros(len(hz))
    for first in range(0, capture.frames, SCAN_SECONDS * rate):
        evidence = np.maximum(evidence, scan_block(capture, first, nfft, hop, order, workers))
    peaks, _ = signal.find_peaks(evidence, height=min_db, prominence=2.5,
                                 distance=max(1, round(55 * nfft / rate)))
    results = []
    for index in peaks:
        left, middle, right = evidence[index - 1:index + 2]
        offset = hz[index] + 0.5 * (left - right) / (left - 2 * middle + right) * rate / nfft
        if low <= offset <= high and abs(offset) >= 45:
            results.append(Candidate(round(float(offset), 1), round(float(middle), 1)))
    return results


def render(capture: Capture, offset_hz: float, filter_hz: int = FILTER_HZ,
           tone_hz: int = TONE_HZ) -> tuple[np.ndarray, float]:
    """Mix to baseband, filter, and remodulate to a standard mono CW pitch."""
    rate = capture.sample_rate
    # Use a common sample grid so overlap removal retains the same phase and frame count.
    divisor = math.gcd(rate, AUDIO_RATE)
    up, down = AUDIO_RATE // divisor, rate // divisor
    taps = signal.firwin(401, filter_hz / 2, fs=AUDIO_RATE).astype(np.float32)
    result = np.empty(math.ceil(capture.frames * up / down), dtype=np.float32)
    pad = math.ceil(rate / (8 * down)) * down
    chunk = math.ceil(rate * EXTRACT_SECONDS / down) * down
    for first in range(0, capture.frames, chunk):
        end = min(first + chunk, capture.frames)
        left = max(0, first - pad)
        right = min(capture.frames, end + pad)
        t = np.arange(left, right, dtype=np.float64) / rate
        mixed = capture.read(left, right) * np.exp(-2j * np.pi * offset_hz * t).astype(np.complex64)
        baseband = signal.resample_poly(mixed, up, down)
        baseband = signal.fftconvolve(baseband, taps, mode="same")
        start_frame = first * up // down
        end_frame = (end * up + down - 1) // down
        skip = (first - left) * up // down
        t = np.arange(start_frame, end_frame, dtype=np.float64) / AUDIO_RATE
        result[start_frame:end_frame] = (
            baseband[skip:skip + len(t)] * np.exp(2j * np.pi * tone_hz * t)).real
    peak = float(np.max(np.abs(result), initial=0.0))
    gain = 0.8 / peak if peak > 0 else 1.0
    return result * gain, gain


def write_audio(path: Path, samples: np.ndarray) -> None:
    pcm = np.rint(np.clip(samples, -1, 32767 / 32768) * 32768).astype(np.int16)
    sf.write(path, pcm, AUDIO_RATE, subtype="PCM_16")


def decode(samples: np.ndarray, tone_hz: int = TONE_HZ) -> str:
    cfg = Config(input=InputConfig(freq_min=tone_hz - 100, freq_max=tone_hz + 100))
    with Receiver(AUDIO_RATE, cfg) as receiver:
        pieces = [receiver.push(samples[i:i + AUDIO_RATE])[0]["delta"]
                  for i in range(0, len(samples), AUDIO_RATE)]
        pieces.append(receiver.finish()[0]["delta"])
    return "".join(pieces).strip()


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest(capture: Capture, output: Path, limits: tuple[float, float], offsets: list[float],
           min_db: float, filter_hz: int, tone_hz: int, workers: int) -> dict:
    if offsets:
        candidates = [Candidate(offset, None) for offset in sorted({round(hz, 1) for hz in offsets})]
    else:
        candidates = find_carriers(capture, limits, min_db, workers)
    output_path = output / capture.path.stem
    if output_path.exists():
        raise ValueError(f"Choose a new output directory for {capture.path.name}")

    def process(candidate: Candidate) -> dict:
        offset = candidate.offset_hz
        samples, gain = render(capture, offset, filter_hz, tone_hz)
        filename = f"{capture.path.stem}_{offset:+.1f}Hz.wav"
        write_audio(stage / filename, samples)
        return dict(**asdict(candidate), rf_hz=capture.rf_hz(offset), audio=filename,
                    sample_rate=AUDIO_RATE, filter_hz=filter_hz, tone_hz=tone_hz,
                    peak_gain=gain, text=decode(samples, tone_hz))

    with tempfile.TemporaryDirectory(dir=output) as temporary:
        stage = Path(temporary) / "capture"
        stage.mkdir()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            signals = list(pool.map(process, candidates))
        report = dict(asdict(capture), path=capture.path.name, sha256=sha256(capture.path),
                      search_hz=list(limits), candidate_count=len(signals), signals=signals)
        (stage / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        stage.rename(output_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Gqrx WAV or native float32 IQ files")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("iq", "usb", "audio"), help="Override filename mode")
    parser.add_argument("--tuned-hz", type=int, help="Override the filename's tuned frequency")
    parser.add_argument("--search-hz", nargs=2, type=float, metavar=("LOW", "HIGH"),
                        help="Restrict search to signed offsets from tuning, or audio Hz for USB/audio")
    parser.add_argument("--offset-hz", action="append", default=[], type=float,
                        help="Manually extract a carrier at this offset, repeatable")
    parser.add_argument("--min-db", type=float, default=10, help="Local spectral contrast threshold")
    parser.add_argument("--filter-hz", type=int, default=FILTER_HZ, help="Full extraction bandwidth")
    parser.add_argument("--tone-hz", type=int, default=TONE_HZ, help="Output audio tone")
    parser.add_argument("--workers", type=int, default=1, help="Parallel FFTs or channel extractions")
    args = parser.parse_args()
    guard = max(100, args.filter_hz / 2)
    if (args.workers < 1 or not math.isfinite(args.min_db) or not 40 <= args.filter_hz <= 1000
            or not guard < args.tone_hz < AUDIO_RATE / 2 - guard):
        parser.error("Require positive workers, a finite threshold, a 40–1000 Hz filter and an in-band tone")
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        inputs = chain.from_iterable(sorted(path.parent.glob(path.name)) if "*" in path.name or "?" in path.name
                                     else (path,) for path in args.inputs)
        paths = dict.fromkeys(inputs)
        if not paths:
            raise ValueError("No recordings matched the input paths")
        for path in paths:
            capture = Capture.open(path, args.mode, args.tuned_hz)
            low, high = capture.search_range()
            limits = tuple(args.search_hz) if args.search_hz else (low, high)
            if not low <= limits[0] < limits[1] <= high or any(not low < hz < high for hz in args.offset_hz):
                raise ValueError(f"Search limits and offsets must lie within {low:g} to {high:g} Hz")
            report = ingest(capture, args.output, limits, args.offset_hz, args.min_db,
                            args.filter_hz, args.tone_hz, args.workers)
            print(f"{path.name}: {report['candidate_count']} candidates", flush=True)
    except (OSError, ValueError, sf.LibsndfileError, DecoderError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
