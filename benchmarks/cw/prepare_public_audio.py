"""Prepare the CC0 benchmark source WAVs from the documented media files."""

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import hilbert


def prepare(output, hand, paddle, offair, ffmpeg):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        for source, filename, offset in [
            (hand, "dod-23735-audio.wav", 0),
            (paddle, "freesound-347147-paddle.wav", -1400),
            (offair, "freesound-165450-offair.wav", 250),
        ]:
            mono = Path(scratch) / filename
            target = mono if offset else output / filename
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source),
                            "-vn", "-ac", "1", "-ar", "8000", "-acodec", "pcm_s16le", str(target)],
                           check=True)
            if offset:
                samples, rate = sf.read(mono)
                samples = (hilbert(samples) * np.exp(2j * np.pi * offset * np.arange(len(samples)) / rate)).real
                sf.write(output / filename, samples, rate, subtype="PCM_16")
    samples, rate = sf.read(output / "freesound-165450-offair.wav")
    # Seeded broadband bursts with an 18 ms decay model short static crashes.
    rng = np.random.default_rng(20261123)
    decay = np.exp(-np.arange(round(0.12 * rate)) / (0.018 * rate))
    peak = np.max(np.abs(samples[round(50.3 * rate):round(59.35 * rate)]))
    for seconds in (50.35, 52.34, 54.85, 56.42, 57.7, 58.72):
        first = round(seconds * rate)
        samples[first:first + len(decay)] += 0.75 * peak * decay * rng.standard_normal(len(decay))
    sf.write(output / "freesound-165450-offair-qrn.wav", samples, rate, subtype="PCM_16")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hand", type=Path, required=True)
    parser.add_argument("--paddle", type=Path, required=True)
    parser.add_argument("--offair", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    prepare(args.output, args.hand, args.paddle, args.offair, args.ffmpeg)
