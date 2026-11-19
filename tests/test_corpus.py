"""Check that a decoder outside the repository can replay and score the corpus."""

import json
import sqlite3
import subprocess
import sys

import pytest

from benchmarks.cw import benchmark


def test_portable_export_and_external_predictions(tmp_path):
    data = benchmark.corpus()
    bundle = tmp_path / "external"
    benchmark.export(benchmark.CATALOG, data, bundle)
    with sqlite3.connect(bundle / "corpus.sqlite3") as db:
        labels = dict(db.execute("SELECT id, text FROM clips"))
    inputs = [json.loads(line) for line in (bundle / "inputs.jsonl").read_text().splitlines()]
    assert {row["id"] for row in inputs} == labels.keys()
    assert all(set(row) == {"id", "audio"} and (bundle / row["audio"]).is_file() for row in inputs)
    guesses = tmp_path / "output.jsonl"
    guesses.write_text("".join(json.dumps({"id": key, "text": value.lower().replace("<bt>", "=")}) + "\n"
                               for key, value in reversed(labels.items())))
    result = subprocess.run([sys.executable, "benchmark.py", "score", str(guesses), "--json"],
                            cwd=bundle, check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["edits"] == report["symbol_edits"] == 0
    assert len(report["clips"]) == len(labels)
    with pytest.raises(ValueError, match="Missing"):
        benchmark.score(data, {})
    with guesses.open("a") as output:
        output.write(json.dumps({"id": inputs[0]["id"], "text": ""}) + "\n")
    with pytest.raises(ValueError, match="Duplicate"):
        benchmark.predictions(guesses)


def test_empty_copy_and_spacing_metrics():
    data = {"recordings": [{"clips": [{"id": "a", "text": "I <BT>"}, {"id": "b", "text": "ES"}]}]}
    result = benchmark.score(data, {"a": "i=", "b": ""})
    assert (result["edits"], result["characters"]) == (3, 8)
    assert (result["symbol_edits"], result["symbols"]) == (2, 4)

def test_add_extract_and_run_external_command(tmp_path):
    catalog = tmp_path / "corpus.json"
    catalog.write_text('{"version":1,"recordings":[]}')
    recording = benchmark.corpus()["recordings"][0]
    original = benchmark.HERE / benchmark.audio_path(recording["clips"][0])
    review = dict(id="test-source", source="Test receiver", recorded_utc=recording["recorded_utc"],
                  frequency_khz=7000, usage="holdout",
                  clips=[dict(start_frame=100, end_frame=201, text="I")])
    benchmark.add(catalog, original, review)
    data = benchmark.corpus(catalog)
    entry = data["recordings"][0]
    assert benchmark.clip_audio(tmp_path, entry, entry["clips"][0]) == benchmark.pcm(
        original, entry["sample_rate"], entry["frames"], 100, 201)
    with pytest.raises(ValueError, match="already"):
        benchmark.add(catalog, original, review)
    command = [sys.executable, "-c", "import wave,sys; print(wave.open(sys.argv[1]).getnframes())", "{wav}"]
    output = tmp_path / "predictions.jsonl"
    benchmark.run_decoder(catalog, data, command, output)
    assert benchmark.predictions(output) == {"test-source-100": "101"}
    with pytest.raises(ValueError, match="Decoder failed"):
        benchmark.run_decoder(catalog, data, [sys.executable, "-c", "raise SystemExit(1)", "{wav}"], output)
    assert benchmark.predictions(output) == {"test-source-100": "101"}
