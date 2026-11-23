import socket
from types import SimpleNamespace

import numpy as np

from morse_decode.audio import source


def test_device_reports_callbacks_and_queue_overrun_from_consumer(monkeypatch):
    reports = []

    class InputStream:
        def __init__(self, *, callback, **options):
            self.callback = callback

        def __enter__(self):
            samples = np.zeros((16, 1), dtype=np.float32)
            for index in range(65):
                self.callback(samples, 16, None, "input overflow" if index == 0 else "")
            assert not reports

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr(source, "_HAS_SOUNDDEVICE", True)
    monkeypatch.setattr(source, "sd", SimpleNamespace(InputStream=InputStream), raising=False)
    stream = source.DeviceSource(sample_rate=8000, on_status=reports.append).stream()
    try:
        assert next(stream).shape == (16,)
        assert any("input overflow" in message for message in reports)
        assert any("queue full" in message for message in reports)
    finally:
        stream.close()


def test_udp_preserves_datagram_alignment_and_closes_on_interrupt(monkeypatch):
    received = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    received.bind(("127.0.0.1", 0))
    reports = []
    audio = source.NetworkSource("udp://127.0.0.1:1234", 8000, on_status=reports.append)
    monkeypatch.setattr(audio, "_open", lambda: received)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(b"x", received.getsockname())
        sender.sendto(b"\x00\x80\x00\x40", received.getsockname())
    stream = audio.stream()
    try:
        np.testing.assert_array_equal(next(stream), [-1, 0.5])
        assert "partial PCM sample" in reports[0]
    finally:
        stream.close()
    assert received.fileno() == -1
