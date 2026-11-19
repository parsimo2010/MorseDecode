"""Score published W1AW practice audio or public Utah WebSDR clips."""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from benchmarks.cw import benchmark

# End times are in the first word space after the labeled reference prefix.
RECORDINGS = [(15, "260204", 94.358, 27), (20, "260217", 90.982, 31)]


def utah_labels():
    return benchmark.corpus()["recordings"]


def measure_utah(path, recording, fixture, versions=(), gain_fade=False):
    rate = recording["sample_rate"]
    if path is not None:
        benchmark.checked(path.read_bytes(), recording["sha256"], path)
    for clip in recording["clips"]:
        first = clip["start_frame"]
        if path is None:
            pcm = benchmark.clip_audio(benchmark.HERE, recording, clip)
        else:
            pcm = benchmark.pcm(path, rate, recording["frames"], first, clip["end_frame"])
            benchmark.checked(pcm, clip["pcm_sha256"], clip["id"])
        if gain_fade:
            samples = np.frombuffer(pcm, dtype="<i2")
            t = (first + np.arange(len(samples))) / rate
            gain = 0.7 * (0.23 + 0.77 * (1 + np.cos(2 * np.pi * 0.23 * t)) / 2)
            pcm = np.rint(samples * gain).astype("<i2").tobytes()
        fixture.write_text(json.dumps({"rate": rate, "reference": clip["text"],
                                       "pcm": base64.b64encode(pcm).decode("ascii")}), encoding="utf-8")
        result = subprocess.run(["node", "tests/accuracy.mjs", f"--fixture={fixture}", "--json", *versions],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        yield clip, dict(json.loads(result.stdout))


def score_utah(directory, versions, verbose, gain_fade=False, predictions=None):
    totals = {}
    outputs = []
    with tempfile.TemporaryDirectory() as scratch:
        fixture = Path(scratch) / "utah.json"
        for recording in utah_labels():
            path = directory / recording["file"] if directory else None
            print(recording["file"], flush=True)
            for clip, results in measure_utah(path, recording, fixture, versions, gain_fade):
                outputs.append({"id": clip["id"], "text": results["current"]["text"]})
                if verbose:
                    print(f"  reference  {clip['text']}")
                for version, measurement in results.items():
                    errors = measurement["edits"]
                    chars = len(clip["text"])
                    print(f"  {clip['id']}  {version}  {errors}/{chars} edits")
                    if verbose:
                        print(f"    {measurement['text']}")
                    tally = totals.setdefault(version, [0, 0])
                    tally[0] += errors
                    tally[1] += chars
    for version, (errors, chars) in totals.items():
        print(f"{version} total: {errors}/{chars} edits ({100 * errors / chars:.2f}% CER)")
    if predictions:
        predictions.write_text("".join(json.dumps(row) + "\n" for row in outputs), encoding="utf-8")


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
    parser.add_argument("--directory", type=Path, help="Use the original full WAVs in this directory instead of the bundled clips")
    parser.add_argument("--predictions", type=Path, help="Write current decoder JSONL for the public corpus scorer")
    parser.add_argument("--verbose", action="store_true", help="Print the reference and decoded text")
    args = parser.parse_args()
    if (args.gain_fade or args.predictions or args.directory) and not args.utah:
        parser.error("--directory, --predictions and --gain-fade require --utah")
    versions = [f"--baseline={args.baseline}"] if args.baseline else []
    if args.utah:
        score_utah(args.directory, versions, args.verbose, args.gain_fade, args.predictions)
    else:
        score_recordings(args.cache, versions + (["--verbose"] if args.verbose else []))
