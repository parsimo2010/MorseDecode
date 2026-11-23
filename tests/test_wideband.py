"""Exercise signed IQ channelization and one-sided USB at the command line."""

import json
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from tests.test_receiver import MESSAGE, RATE, synth


@pytest.mark.parametrize("mode", ["raw", "iq-wav", "usb"])
def test_wideband_ingest(tmp_path, mode):
    rate = 96_000 if mode == "raw" else 48_000
    is_iq = mode != "usb"
    offsets = [-12_063, 14_291] if is_iq else [12_063, 14_291]
    messages = [MESSAGE, "TEST TEST"]
    tracks = []
    for offset, message in zip(offsets, messages):
        x = synth(message, 700)
        t = np.arange(len(x)) / RATE
        baseband = signal.hilbert(x) * np.exp(-2j * np.pi * 700 * t)
        resampled = signal.resample_poly(baseband, rate // RATE, 1)
        tracks.append(resampled * np.exp(2j * np.pi * offset * np.arange(len(resampled)) / rate))
    frames = max(map(len, tracks))
    rng = np.random.default_rng(153)
    iq = 0.012 * (rng.normal(size=frames) + 1j * rng.normal(size=frames))
    for track in tracks:
        iq[:len(track)] += track

    if mode == "raw":
        path = tmp_path / "gqrx_20261123_000841_14033600_96000_fc.raw"
        iq.astype("<c8").tofile(path)
    else:
        tag = "IQ-80k" if is_iq else "USB-39_9k-noagc"
        path = tmp_path / f"gqrx_20261123_000841_14033600-{tag}.wav"
        sf.write(path, np.column_stack((iq.real, iq.imag if is_iq else iq.real)), rate, subtype="PCM_16")

    output = tmp_path / "decoded"
    subprocess.run([sys.executable, "-m", "morse_decode.wideband", str(path),
                    "--output", str(output), "--workers", "2"], check=True)
    folder = output / path.stem
    result = json.loads((folder / "report.json").read_text())
    assert result["recorded_utc"] == "2026-11-23T00:08:41Z"
    assert result["candidate_count"] == 2
    for row, offset, message in zip(result["signals"], offsets, messages):
        assert row["offset_hz"] == pytest.approx(offset, abs=5)
        assert row["rf_hz"] == pytest.approx(14_033_600 + offset, abs=5)
        assert row["text"].startswith(message)
        audio = sf.info(folder / row["audio"])
        assert (audio.samplerate, audio.channels, audio.subtype) == (8_000, 1, "PCM_16")
        assert audio.frames == int(np.ceil(frames * 8_000 / rate))
