"""Score published W1AW practice audio or locally supplied Utah WebSDR recordings."""

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
# End times are in the first word space after the labeled reference prefix.
RECORDINGS = [(15, "260204", 94.358, 27), (20, "260217", 90.982, 31)]


def utah_labels():
    return json.loads((ROOT / "tests/fixtures/utah-cw.json").read_text(encoding="utf-8"))


def measure_utah(path, recording, fixture, versions=(), gain_fade=False):
    if hashlib.sha256(path.read_bytes()).hexdigest() != recording["sha256"]:
        raise ValueError(f"Recording differs from the labeled audio: {path}")
    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"Expected mono 16-bit PCM: {path}")
        for excerpt in recording["excerpts"]:
            first = round(excerpt["start"] * rate)
            wav.setpos(first)
            pcm = wav.readframes(round(excerpt["end"] * rate) - first)
            if gain_fade:
                samples = np.frombuffer(pcm, dtype="<i2")
                t = (first + np.arange(len(samples))) / rate
                gain = 0.7 * (0.23 + 0.77 * (1 + np.cos(2 * np.pi * 0.23 * t)) / 2)
                pcm = np.rint(samples * gain).astype("<i2").tobytes()
            fixture.write_text(json.dumps({"rate": rate, "reference": excerpt["text"],
                                           "pcm": base64.b64encode(pcm).decode("ascii")}), encoding="utf-8")
            result = subprocess.run(["node", "tests/accuracy.mjs", f"--fixture={fixture}", "--json", *versions],
                                    cwd=ROOT, capture_output=True, text=True, check=True)
            yield excerpt, dict(json.loads(result.stdout))


def score_utah(directory, versions, verbose, gain_fade=False):
    totals = {}
    with tempfile.TemporaryDirectory() as scratch:
        fixture = Path(scratch) / "utah.json"
        for recording in utah_labels():
            path = directory / recording["file"]
            if not path.is_file():
                raise SystemExit(f"Missing recording: {path}")
            print(path.name, flush=True)
            for excerpt, results in measure_utah(path, recording, fixture, versions, gain_fade):
                chars = len(excerpt["text"])
                if verbose:
                    print(f"  reference  {excerpt['text']}")
                for version, measurement in results.items():
                    errors = measurement["edits"]
                    print(f"  {excerpt['start']:.2f}-{excerpt['end']:.2f}s  {version}  {errors}/{chars} edits")
                    if verbose:
                        print(f"    {measurement['text']}")
                    tally = totals.setdefault(version, [0, 0])
                    tally[0] += errors
                    tally[1] += chars
    for version, (errors, chars) in totals.items():
        print(f"{version} total: {errors}/{chars} edits ({100 * errors / chars:.2f}% CER)")


def download(url, path):
    if not path.exists():
        with urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
    return path


def score_recordings(cache, versions):
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        for wpm, code, seconds, words in RECORDINGS:
            archive = f"https://www.arrl.org/files/file/Morse/Archive/{wpm}%20WPM/"
            audio = download(f"{archive}{code}_{wpm}WPM.mp3", cache / f"{code}.mp3")
            text = download(f"{archive}{code}_{wpm}.txt", cache / f"{code}.txt")
            ref = " ".join(text.read_text(encoding="utf-8").upper().split()[:words]).replace("=", "<BT>")
            with sf.SoundFile(audio) as stream:
                rate = stream.samplerate
                pcm = stream.read(round(seconds * rate), dtype="float32")
            for degrade in (False, True):
                samples = pcm
                if degrade:
                    t = np.arange(len(pcm)) / rate
                    gain = 1 - 0.91 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.47 * t)) ** 3
                    samples = 0.45 * pcm * gain + 0.11 * np.random.default_rng(wpm).normal(size=len(pcm))
                encoded = np.round(np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2")
                fixture = Path(scratch) / "input.json"
                fixture.write_text(json.dumps({"rate": rate, "reference": ref,
                                               "pcm": base64.b64encode(encoded.tobytes()).decode("ascii")}),
                                   encoding="utf-8")
                print(f"W1AW {wpm} WPM | {'added fade and noise' if degrade else 'original audio'}", flush=True)
                subprocess.run(["node", "tests/accuracy.mjs", f"--fixture={fixture}", *versions], cwd=ROOT, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", help="Git revision of the reference JavaScript decoder")
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "morsedecode-w1aw")
    parser.add_argument("--utah", action="store_true", help="Score time-labeled Northern Utah WebSDR excerpts")
    parser.add_argument("--gain-fade", action="store_true", help="Vary receiver output gain on the Utah benchmark")
    parser.add_argument("--directory", type=Path, default=ROOT / "recordings", help="Directory of Utah WAVs")
    parser.add_argument("--verbose", action="store_true", help="Print the reference and decoded text")
    args = parser.parse_args()
    if args.gain_fade and not args.utah:
        parser.error("--gain-fade requires --utah")
    versions = [f"--baseline={args.baseline}"] if args.baseline else []
    if args.utah:
        score_utah(args.directory, versions, args.verbose, args.gain_fade)
    else:
        score_recordings(args.cache, versions + (["--verbose"] if args.verbose else []))
