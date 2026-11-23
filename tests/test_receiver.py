"""Exercise the shared decoder through the terminal and bundled web worker."""

import json
import socket
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from morse_decode.cli import main
from morse_decode.config import Config
from morse_decode.receiver import DecoderError, Receiver
from tests.recordings import measure_utah, utah_labels


ROOT = Path(__file__).resolve().parents[1]
RATE = 8000
MESSAGE = "CQ CQ DE W1AW"
CODES = {"A": ".-", "C": "-.-.", "D": "-..", "E": ".", "Q": "--.-",
         "T": "-", "S": "...", "W": ".--", "1": ".----"}


def synth(text, hz, wpm=22):
    dit = round(RATE * 1.2 / wpm)
    words = []
    for word in text.split():
        chars = ["0".join("1" if mark == "." else "111" for mark in CODES[char]) for char in word]
        words.append("000".join(chars))
    keying = np.repeat([int(bit) for bit in "0000000".join(words)], dit)
    keying = np.pad(keying, (RATE // 4, RATE))
    return np.asarray(0.48 * keying * np.sin(2 * np.pi * hz * np.arange(len(keying)) / RATE), dtype="<f4")


def receive(samples, cfg):
    with Receiver(RATE, cfg) as receiver:
        text = ["" for _ in receiver.passbands]
        for start in range(0, len(samples), 400):
            for i, channel in enumerate(receiver.push(samples[start:start + 400])):
                text[i] += channel["delta"]
        final = receiver.finish()
        for i, channel in enumerate(final):
            text[i] += channel.pop("delta")
            channel["text"] = text[i]
        return final


@pytest.mark.parametrize("agc", [None, True])
def test_browser_worker_and_terminal_decode_identically(agc):
    subprocess.run(["node", "web/build.mjs"], cwd=ROOT, check=True, capture_output=True)
    samples = synth(MESSAGE, 673)
    cfg = Config()
    cfg.input.channel_width_hz = 600
    cfg.audio.agc_enabled = agc
    terminal, = receive(samples, cfg)

    worker = subprocess.run(
        ["node", "--input-type=module", "-e", r"""
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const html = readFileSync('dist/index.html', 'utf8');
const source = JSON.parse(html.match(/^const workerSource = (.+);$/m)[1]);
const self = {postMessage: message => {
  if (message.type === 'error') throw new Error(message.message);
  if (message.type === 'finished') console.log(JSON.stringify(message));
}};
runInNewContext(source, {self, performance});
const send = data => self.onmessage({data});
const agcEnabled = JSON.parse(process.argv[1]) ?? undefined;
send({type: 'start', rate: 8000, passband: {low: 400, high: 1000, agcEnabled}});
const pcm = readFileSync(0);
for (let i = 0; i < pcm.length; i += 731 * 4) {
  const length = Math.min(731, (pcm.length - i) / 4);
  send({type: 'audio', samples: Float32Array.from({length}, (_, j) => pcm.readFloatLE(i + 4 * j))});
}
send({type: 'stop'});
""", json.dumps(agc)], cwd=ROOT, input=samples.tobytes(), capture_output=True, check=True,
    )
    browser = json.loads(worker.stdout)
    assert terminal["text"] == MESSAGE
    assert terminal["callsign"] == "W1AW"
    assert terminal == {key: browser[key] for key in terminal}


@pytest.mark.parametrize("frequency", [600, 673])
def test_adjacent_channels_do_not_decode_the_same_carrier(frequency):
    assert [channel["text"] for channel in receive(synth(MESSAGE, frequency), Config())] == ["", MESSAGE, ""]


def test_two_simultaneous_carriers_decode_independently():
    low = synth(MESSAGE, 563)
    high = synth("TEST TEST", 867, wpm=27) * 0.65
    low[:len(high)] += high
    assert [channel["text"] for channel in receive(low, Config())] == [MESSAGE, "", "TEST TEST"]


@pytest.mark.parametrize("use_stdin", [False, True])
def test_cli_audio_and_final_transcript_log(tmp_path, monkeypatch, use_stdin):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    pcm = (synth(MESSAGE, 673) * 32767).astype("<i2").tobytes()
    log = tmp_path / "receive.jsonl"
    if use_stdin:
        source = ["--stdin", "--sample-rate", str(RATE)]
    else:
        recording = tmp_path / "input.wav"
        with wave.open(str(recording), "wb") as wav:
            wav.setparams((1, 2, RATE, 0, "NONE", ""))
            wav.writeframes(pcm)
        source = ["--file", str(recording)]
    result = CliRunner().invoke(main, [*source, "--channel-width", "600", "--log", str(log),
                                       "--log-format", "jsonl"], input=pcm if use_stdin else None)
    assert result.exit_code == 0, result.output
    assert MESSAGE in result.output
    assert "".join(json.loads(line)["text"] for line in log.read_text().splitlines()) == MESSAGE


def test_invalid_passband_returns_a_clear_error():
    cfg = Config()
    cfg.input.freq_max = RATE // 2 + 100
    with pytest.raises(DecoderError, match="below half the sample rate"):
        Receiver(RATE, cfg)


def test_cli_flushes_pending_word_once_when_capture_is_interrupted(tmp_path, monkeypatch):
    from morse_decode import cli

    class InterruptedSource:
        sample_rate = RATE

        def stream(self):
            samples = synth("CQ", 673)[:-RATE]
            for start in range(0, len(samples), 400):
                yield samples[start:start + 400]
            raise KeyboardInterrupt

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "create_source", lambda **options: InterruptedSource())
    log = tmp_path / "interrupted.jsonl"
    result = CliRunner().invoke(main, ["--channel-width", "600", "--log", str(log),
                                       "--log-format", "jsonl"])
    assert result.exit_code == 0, result.output
    assert "CQ" in result.output
    assert [json.loads(line)["text"] for line in log.read_text().splitlines()] == ["CQ"]


def test_cli_decodes_tcp_pcm_to_eof(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    pcm = (synth("CQ", 673)[:-RATE] * 32767).astype("<i2").tobytes()
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(3)
        port = server.getsockname()[1]

        def send():
            connection, _ = server.accept()
            with connection:
                connection.sendall(pcm[:401])
                connection.sendall(pcm[401:] + b"\xff")

        producer = threading.Thread(target=send, daemon=True)
        producer.start()
        result = CliRunner().invoke(main, ["--network", f"tcp://127.0.0.1:{port}",
                                           "--sample-rate", str(RATE), "--channel-width", "600"])
        producer.join(timeout=4)
    assert result.exit_code == 0, result.output
    assert "CQ" in result.output
    assert "partial PCM sample" in result.output


@pytest.mark.parametrize(("options", "message"), [
    ({"minWpm": 8e-309}, "WPM range"),
    ({"hopMs": 0.1}, "hop"),
    ({"windowMs": 1e9}, "window"),
    ({"low": 100, "high": 3000, "binWidth": 1}, "Too many search tones"),
    ({"low": 100, "high": 3000, "windowMs": 150}, "real-time work limit"),
])
def test_pathological_core_options_fail_promptly(options, message):
    result = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import {CWDecoder} from './morse_decode/core/decoder.mjs';"
         "new CWDecoder(48000, JSON.parse(process.argv[1]));", json.dumps(options)],
        cwd=ROOT, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode != 0
    assert message in result.stderr


def test_core_still_accepts_wide_passband():
    subprocess.run(
        ["node", "--input-type=module", "-e",
         "import {CWDecoder} from './morse_decode/core/decoder.mjs';"
         "new CWDecoder(48000, {low: 100, high: 3000});"],
        cwd=ROOT, check=True, timeout=5,
    )


@pytest.mark.parametrize("rate", [8000, 48000])
@pytest.mark.parametrize("agc", [False, True])
def test_invalid_pcm_is_silence_and_does_not_poison_following_copy(rate, agc):
    cfg = Config()
    cfg.input.channel_width_hz = 600
    cfg.audio.agc_enabled = agc
    samples = np.repeat(synth(MESSAGE, 673), rate // RATE)
    with Receiver(rate, cfg) as receiver:
        receiver.push(np.array([float("nan"), float("inf"), -float("inf")], dtype=np.float32))
        chunks = []
        for start in range(0, len(samples), rate // 20):
            chunks.append(receiver.push(samples[start:start + rate // 20])[0]["delta"])
        chunks.append(receiver.finish()[0]["delta"])
    assert "".join(chunks) == MESSAGE


def test_filtered_receiver_noise_and_replies():
    subprocess.run(["node", "tests/accuracy.mjs", "--match=receiver", "--holdout", "--check"],
                   cwd=ROOT, check=True)


def test_noisy_carrier_phase_resets():
    subprocess.run(["node", "tests/accuracy.mjs", "--match=each mark", "--holdout", "--seed=405731", "--check"],
                   cwd=ROOT, check=True)


@pytest.mark.parametrize("recording", utah_labels(), ids=lambda recording: recording["file"])
def test_utah_recording(recording, tmp_path):
    limits = json.loads((ROOT / "tests/fixtures/field-limits.json").read_text(encoding="utf-8"))
    missing = {clip["id"] for clip in recording["clips"]} - limits.keys()
    assert not missing, f"Missing field regression budgets: {sorted(missing)}"
    for clip, results in measure_utah(None, recording, tmp_path / "field.json"):
        measured = results["current"]
        assert measured["edits"] <= limits[clip["id"]], measured["text"]
