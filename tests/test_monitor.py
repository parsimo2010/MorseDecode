import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from morse_decode.output.monitor import Monitor


def test_monitor_only_returns_transcripts_with_its_viewer_token():
    with Monitor(0) as monitor:
        base = monitor.url.split("#")[0]
        with urlopen(base, timeout=2) as response:
            assert b"MorseDecode receiver" in response.read()
        endpoint = base + "snapshot"
        for auth in ({}, {"Authorization": "Bearer bad"}):
            with pytest.raises(HTTPError) as exc:
                urlopen(Request(endpoint, headers=auth), timeout=2)
            assert exc.value.code == 401
        request = Request(endpoint, headers={"Authorization": f"Bearer {monitor.token}"})
        snapshot = [{"freq_hz": 672, "signal_db": 11, "speed_wpm": 18, "text": "CQ"}]
        monitor.publish(snapshot)
        with urlopen(request, timeout=2) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response) == snapshot
