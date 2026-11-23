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
