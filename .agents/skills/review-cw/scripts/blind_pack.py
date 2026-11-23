"""Create an anonymous WAV-only reviewer directory and a separate coordinator key."""

import argparse
import hashlib
import json
import tempfile
import wave
from pathlib import Path


def pack(source, destination):
    files = sorted(source.glob("*.wav"))
    if not files:
        raise ValueError(f"No WAV files in {source}")
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage = Path(tmp) / "pack"
        (stage / "audio").mkdir(parents=True)
        write_pack(files, stage)
        stage.rename(destination)


def write_pack(files, directory):
    mapping = {}
    for path in files:
        with wave.open(str(path)) as wav:
            params = wav.getparams()
            pcm = wav.readframes(params.nframes)
        if params.nchannels != 1 or len(pcm) != params.nframes * params.sampwidth:
            raise ValueError(f"Expected a complete mono channel: {path}")
        digest = hashlib.sha256(f"{params.framerate}/{params.sampwidth}/".encode("ascii"))
        digest.update(pcm)
        key = digest.hexdigest()
        mapping.setdefault(key, []).append(path.name)
        output = directory / "audio" / (key + ".wav")
        if output.exists():
            with wave.open(str(output)) as wav:
                if wav.getparams() == params and wav.readframes(params.nframes) == pcm:
                    continue
            raise ValueError(f"Audio key collision for {path}")
        with wave.open(str(output), "wb") as wav:
            wav.setparams(params)
            wav.writeframes(pcm)
    (directory / "coordinator.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    pack(args.source, args.destination)
