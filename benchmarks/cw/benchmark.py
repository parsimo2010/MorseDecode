"""Build, export and score the public CW recording corpus using Python's standard library."""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import wave
from pathlib import Path


HERE = Path(__file__).resolve().parent
CATALOG = HERE / "corpus.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def corpus(path=CATALOG):
    data = json.loads(path.read_text(encoding="utf-8"))
    validate(data)
    return data


def validate(data):
    if data["version"] != 1:
        raise ValueError("Unsupported corpus format")
    seen = set()
    for recording in data["recordings"]:
        filename = recording["file"]
        if Path(filename).name != filename or recording["sample_rate"] <= 0:
            raise ValueError(f"Invalid recording: {filename}")
        if not recording["clips"] or not recording["source"] or recording["usage"] not in {"development", "holdout"}:
            raise ValueError(f"Missing clips, source or dataset split: {filename}")
        channel = recording.get("channel")
        if channel is not None:
            capture_file = channel["capture_file"]
            if (Path(capture_file).name != capture_file
                    or not re.fullmatch(r"[a-f0-9]{64}", channel["capture_sha256"])
                    or not 0 < channel["tone_hz"] < recording["sample_rate"] / 2
                    or channel["filter_hz"] <= 0):
                raise ValueError(f"Invalid channel provenance: {filename}")
        end = 0
        for entry in [recording, *recording["clips"]]:
            key = entry["id"]
            if not re.fullmatch(r"[a-z0-9-]+", key) or key in seen:
                raise ValueError(f"Invalid or duplicate ID: {key}")
            seen.add(key)
        for clip in recording["clips"]:
            if not all(type(clip[key]) is int for key in ("start_frame", "end_frame")):
                raise ValueError(f"Clip bounds must be integer sample frames: {clip['id']}")
            if not (end <= clip["start_frame"] < clip["end_frame"] <= recording["frames"]):
                raise ValueError(f"Overlapping or invalid clip: {clip['id']}")
            if not clip["text"].strip() or not re.fullmatch(r"[a-f0-9]{64}", clip["pcm_sha256"]):
                raise ValueError(f"Missing transcript or PCM hash: {clip['id']}")
            end = clip["end_frame"]


def pcm(path, rate, frames, first=0, end=None):
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) != (rate, 1, 2, frames):
            raise ValueError(f"Unexpected WAV format or length: {path}")
        wav.setpos(first)
        return wav.readframes((frames if end is None else end) - first)


def audio_path(clip):
    return Path("audio") / (clip["id"] + ".wav")


def checked(data, expected, path):
    if digest(data) != expected:
        raise ValueError(f"SHA-256 mismatch: {path}")
    return data


def clip_audio(directory, recording, clip):
    path = directory / audio_path(clip)
    samples = pcm(path, recording["sample_rate"], clip["end_frame"] - clip["start_frame"])
    return checked(samples, clip["pcm_sha256"], path)


def build(data, originals, directory):
    for r in data["recordings"]:
        path = originals / r["file"]
        checked(path.read_bytes(), r["sha256"], path)
        for c in r["clips"]:
            output = directory / audio_path(c)
            samples = pcm(path, r["sample_rate"], r["frames"], c["start_frame"], c["end_frame"])
            checked(samples, c["pcm_sha256"], c["id"])
            if output.exists():
                clip_audio(directory, r, c)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
                staged = Path(tmp) / "clip.wav"
                with wave.open(str(staged), "wb") as wav:
                    wav.setparams((1, 2, r["sample_rate"], 0, "NONE", "not compressed"))
                    wav.writeframes(samples)
                staged.replace(output)


def add(catalog, original, review):
    """Add one reviewed recording, publishing its catalog entry after verifying the clips."""
    with wave.open(str(original)) as wav:
        rate, frames = wav.getframerate(), wav.getnframes()
    r = {key: review[key] for key in ("id", "source", "recorded_utc", "frequency_khz", "usage")}
    if "channel" in review:
        r["channel"] = review["channel"]
    r.update(file=original.name, sha256=digest(original.read_bytes()), sample_rate=rate, frames=frames, clips=[])
    for label in review["clips"]:
        first, end = label["start_frame"], label["end_frame"]
        if type(first) is not int or type(end) is not int or not 0 <= first < end <= frames:
            raise ValueError(f"Invalid sample bounds: {first}, {end}")
        samples = pcm(original, rate, frames, first, end)
        r["clips"].append(dict(id=f"{r['id']}-{first}", start_frame=first, end_frame=end,
                               pcm_sha256=digest(samples), text=label["text"]))

    lock = catalog.with_suffix(".lock")
    lock.mkdir()
    try:
        data = corpus(catalog)
        if any(old["file"] == r["file"] or old["sha256"] == r["sha256"] for old in data["recordings"]):
            raise ValueError("This source recording is already in the catalog")
        data["recordings"].append(r)
        validate(data)
        build({"recordings": [r]}, original.parent, catalog.parent)
        with tempfile.TemporaryDirectory(dir=catalog.parent) as tmp:
            staged = Path(tmp) / "catalog"
            staged.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            staged.replace(catalog)
    finally:
        lock.rmdir()


def export(catalog, data, target):
    if target.exists():
        raise ValueError(f"Choose a new directory for the benchmark bundle: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        stage = Path(tmp) / "bundle"
        (stage / "audio").mkdir(parents=True)
        db = sqlite3.connect(stage / "corpus.sqlite3")
        try:
            db.executescript("""
                CREATE TABLE recordings(id TEXT PRIMARY KEY, file TEXT, sha256 TEXT, recorded_utc TEXT,
                                        frequency_khz REAL, sample_rate INTEGER, frames INTEGER, source TEXT,
                                        usage TEXT, channel_json TEXT);
                CREATE TABLE clips(id TEXT PRIMARY KEY, recording_id TEXT REFERENCES recordings(id),
                                   start_frame INTEGER, end_frame INTEGER, pcm_sha256 TEXT, audio TEXT, text TEXT);
            """)
            with (stage / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as inputs:
                for r in data["recordings"]:
                    db.execute("INSERT INTO recordings VALUES (:id,:file,:sha256,:recorded_utc,"
                               ":frequency_khz,:sample_rate,:frames,:source,:usage,:channel_json)",
                               dict(r, channel_json=json.dumps(r["channel"]) if "channel" in r else None))
                    for c in r["clips"]:
                        clip_audio(catalog.parent, r, c)
                        audio = audio_path(c).as_posix()
                        shutil.copyfile(catalog.parent / audio, stage / audio)
                        inputs.write(json.dumps({"id": c["id"], "audio": audio}) + "\n")
                        db.execute("INSERT INTO clips VALUES (:id,:recording_id,:start_frame,:end_frame,"
                                   ":pcm_sha256,:audio,:text)", dict(c, recording_id=r["id"], audio=audio))
            db.commit()
        finally:
            db.close()
        shutil.copyfile(catalog, stage / "corpus.json")
        shutil.copyfile(__file__, stage / "benchmark.py")
        stage.rename(target)


def run_decoder(catalog, data, command, output):
    if not command or not any("{wav}" in arg for arg in command):
        raise ValueError("Include {wav} in the external command")
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staged = Path(tmp) / "output.jsonl"
        with staged.open("w", encoding="utf-8", newline="\n") as stream:
            for r in data["recordings"]:
                for c in r["clips"]:
                    clip_audio(catalog.parent, r, c)
                    path = (catalog.parent / audio_path(c)).resolve()
                    args = [arg.replace("{wav}", str(path)) for arg in command]
                    run = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
                    if run.returncode:
                        raise ValueError(f"Decoder failed on {c['id']} (exit {run.returncode}): {run.stderr.strip()}")
                    stream.write(json.dumps({"id": c["id"], "text": run.stdout.strip()}) + "\n")
        staged.replace(output)


def predictions(path):
    result = {}
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        row = json.loads(line)
        if row["id"] in result or not isinstance(row["text"], str):
            raise ValueError(f"Duplicate ID or invalid transcript on prediction line {n}")
        result[row["id"]] = row["text"]
    return result


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        nxt = [i]
        for j, other in enumerate(b, 1):
            nxt.append(min(row[j] + 1, nxt[-1] + 1, row[j - 1] + (char != other)))
        row = nxt
    return row[-1]


def normalize(text):
    return " ".join(text.upper().split()).replace("=", "<BT>").replace("+", "<AR>")


def symbols(text):
    return re.findall(r"<[A-Z]+>|[^ ]", text)


def score(data, guesses):
    expected = {c["id"] for r in data["recordings"] for c in r["clips"]}
    if guesses.keys() != expected:
        missing = sorted(expected - guesses.keys())
        extra = sorted(guesses.keys() - expected)
        raise ValueError(f"Prediction IDs differ. Missing {missing}. Unexpected {extra}")
    totals = [0, 0, 0, 0]
    rows = []
    for r in data["recordings"]:
        for c in r["clips"]:
            ref, hyp = normalize(c["text"]), normalize(guesses[c["id"]])
            keys, decoded = symbols(ref), symbols(hyp)
            counts = [distance(ref, hyp), len(ref), distance(keys, decoded), len(keys)]
            totals = [a + b for a, b in zip(totals, counts)]
            rows.append(dict(id=c["id"], edits=counts[0], characters=counts[1],
                             symbol_edits=counts[2], symbols=counts[3]))
    if not rows:
        raise ValueError("The corpus contains no scored clips")
    edits, chars, key_edits, keys = totals
    fingerprint = digest(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    return dict(corpus_sha256=fingerprint, clips=rows, edits=edits, characters=chars,
                cer=edits / chars, symbol_edits=key_edits, symbols=keys, symbol_error_rate=key_edits / keys)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    commands = parser.add_subparsers(dest="command", required=True)
    adding = commands.add_parser("add", help="Append a reviewed recording and extract its WAV clips")
    adding.add_argument("original", type=Path)
    adding.add_argument("review", type=Path, help="Recording metadata and frame-aligned transcripts in JSON")
    commands.add_parser("build", help="Extract labeled WAVs from verified originals").add_argument("originals", type=Path)
    commands.add_parser("export", help="Create a portable benchmark bundle").add_argument("directory", type=Path)
    runner = commands.add_parser("run", help="Run a WAV-to-text command once per clip")
    runner.add_argument("output", type=Path)
    runner.add_argument("decoder", nargs=argparse.REMAINDER, help="Command arguments including {wav}")
    scoring = commands.add_parser("score", help="Evaluate a decoder's JSONL transcripts")
    scoring.add_argument("predictions", type=Path)
    scoring.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = corpus(args.catalog)
        if args.command == "add":
            add(args.catalog, args.original, json.loads(args.review.read_text(encoding="utf-8-sig")))
        elif args.command == "build":
            build(data, args.originals, args.catalog.parent)
        elif args.command == "run":
            run_decoder(args.catalog, data, args.decoder, args.output)
        elif args.command == "export":
            export(args.catalog, data, args.directory)
        else:
            report = score(data, predictions(args.predictions))
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(f"{len(report['clips'])} clips, corpus {report['corpus_sha256']}")
                print(f"{report['edits']}/{report['characters']} character edits ({report['cer']:.2%} CER)")
                print(f"{report['symbol_edits']}/{report['symbols']} keyed symbol edits "
                      f"({report['symbol_error_rate']:.2%})")
    except (ValueError, OSError, KeyError, wave.Error) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
