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


def score_utah(directory, versions, verbose):
    labels = json.loads((ROOT / "tests/fixtures/utah-cw.json").read_text(encoding="utf-8"))
    totals = {}
    with tempfile.TemporaryDirectory() as scratch:
        fixture = Path(scratch) / "utah.json"
        for recording in labels:
            path = directory / recording["file"]
            if not path.is_file():
                raise SystemExit(f"Missing recording: {path}")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != recording["sha256"]:
                    raise SystemExit(f"Recording differs from the labeled audio: {path}")
            print(path.name, flush=True)
            with wave.open(str(path)) as wav:
                rate = wav.getframerate()
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                    raise ValueError(f"Expected mono 16-bit PCM: {path}")
                for start, end, reference in recording["excerpts"]:
                    wav.setpos(round(start * rate))
                    pcm = wav.readframes(round(end * rate) - wav.tell())
                    fixture.write_text(json.dumps({"rate": rate, "reference": reference,
                                                   "pcm": base64.b64encode(pcm).decode("ascii")}),
                                       encoding="utf-8")
                    result = subprocess.run(["node", "tests/accuracy.mjs", f"--fixture={fixture}",
                                             "--json", *versions], cwd=ROOT, capture_output=True,
                                            text=True, check=True)
                    if verbose:
                        print(f"  reference  {reference}")
                    for version, measurement in json.loads(result.stdout):
                        errors = measurement["edits"]
                        print(f"  {start:.2f}-{end:.2f}s  {version}  {errors}/{len(reference)} edits")
                        if verbose:
                            print(f"    {measurement['text']}")
                        tally = totals.setdefault(version, [0, 0])
                        tally[0] += errors
                        tally[1] += len(reference)
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
    parser.add_argument("--directory", type=Path, default=ROOT / "recordings", help="Directory of Utah WAVs")
    parser.add_argument("--verbose", action="store_true", help="Print the reference and decoded text")
    args = parser.parse_args()
    versions = [f"--baseline={args.baseline}"] if args.baseline else []
    if args.utah:
        score_utah(args.directory, versions, args.verbose)
    else:
        score_recordings(args.cache, versions + (["--verbose"] if args.verbose else []))
