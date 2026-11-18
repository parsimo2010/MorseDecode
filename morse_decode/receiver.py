"""Send terminal input to the same decoder module bundled into the browser."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .config import Config


class DecoderError(RuntimeError):
    """The terminal could not start or communicate with the decoder."""


class Receiver:
    def __init__(self, rate: int, cfg: Config) -> None:
        node = shutil.which("node")
        if node is None:
            raise DecoderError("Install Node.js and make sure 'node' is on PATH.")
        self.passbands = [
            {"low": low, "high": min(low + cfg.input.channel_width_hz, cfg.input.freq_max)}
            for low in range(cfg.input.freq_min, cfg.input.freq_max, cfg.input.channel_width_hz)
        ]
        driver = Path(__file__).resolve().parent / "core" / "stdio.mjs"
        self._process = subprocess.Popen(
            [node, str(driver)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        try:
            overrides = {
                "binWidth": cfg.input.bin_width,
                "windowMs": cfg.audio.window_ms,
                "hopMs": cfg.audio.hop_ms,
                "debounceMs": cfg.audio.debounce_ms,
                "onDb": cfg.audio.on_db,
                "offDb": cfg.audio.off_db,
                "agcEnabled": cfg.audio.agc_enabled,
                "agcWindowS": cfg.audio.agc_window_s,
                "agcTargetRms": cfg.audio.agc_target_rms,
                "minWpm": cfg.decoder.speed_min_wpm,
                "maxWpm": cfg.decoder.speed_max_wpm,
            }
            self._request({
                "type": "start", "rate": rate, "passbands": self.passbands,
                "options": {key: value for key, value in overrides.items() if value is not None},
            })
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Receiver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, request: dict) -> dict:
        writer, reader = self._process.stdin, self._process.stdout
        assert writer is not None and reader is not None
        try:
            writer.write(json.dumps(request, allow_nan=False) + "\n")
            writer.flush()
            line = reader.readline()
        except (OSError, ValueError) as exc:
            raise DecoderError(f"Could not send audio to the decoder: {exc}") from exc
        if not line:
            raise DecoderError("The decoder process exited before replying.")
        reply = json.loads(line)
        if "error" in reply:
            raise DecoderError(reply["error"])
        return reply

    def push(self, samples: np.ndarray) -> list[dict]:
        pcm = base64.b64encode(samples.astype("<f4", copy=False).tobytes()).decode("ascii")
        return self._request({"type": "audio", "pcm": pcm})["channels"]

    def finish(self) -> list[dict]:
        return self._request({"type": "finish"})["channels"]

    def close(self) -> None:
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except BrokenPipeError:
                    pass
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
