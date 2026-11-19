"""Score the decoder against published W1AW audio and transcripts."""

import argparse
import base64
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
# End times are in the first word space after the labeled reference prefix.
RECORDINGS = [(15, "260204", 94.358, 27), (20, "260217", 90.982, 31)]


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
    args = parser.parse_args()
    score_recordings(args.cache, [f"--baseline={args.baseline}"] if args.baseline else [])
