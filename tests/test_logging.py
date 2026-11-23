import datetime
import json
from types import SimpleNamespace

import pytest

from morse_decode import cli


@pytest.fixture
def fixed_timestamp(monkeypatch):
    now = datetime.datetime(2026, 11, 23, 12, 0)
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(datetime=SimpleNamespace(now=lambda: now)))


@pytest.mark.parametrize("name", ["receive.jsonl", "receive.log", "receive"])
def test_rotation_preserves_paths_and_same_second_archives(tmp_path, fixed_timestamp, name):
    directory = tmp_path / "station.log"
    directory.mkdir()
    path = directory / name
    logger = cli.ChannelLogger(str(path), fmt="jsonl", rotate_mb=1)
    payload = "CQ" * (512 * 1024)
    try:
        logger.log(650, payload + " FIRST", 10, 20)
        logger.log(650, payload + " SECOND", 10, 20)
        logger.log(650, "THIRD", 10, 20)
    finally:
        logger.close()
    first = path.with_name(f"{path.stem}_20261123_120000{path.suffix}")
    second = path.with_name(f"{path.stem}_20261123_120000_1{path.suffix}")
    assert json.loads(first.read_text())["text"] == payload + " FIRST"
    assert json.loads(second.read_text())["text"] == payload + " SECOND"
    assert json.loads(path.read_text())["text"] == "THIRD"


def test_failed_rotation_keeps_logger_writable(tmp_path, monkeypatch, fixed_timestamp):
    path = tmp_path / "receive.log"
    logger = cli.ChannelLogger(str(path), rotate_mb=1)
    payload = "CQ" * (512 * 1024)

    def blocked(*args):
        raise PermissionError("Archive temporarily unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(cli.os, "rename", blocked)
            logger.log(650, payload, 10, 20)
        logger.log(650, "SECOND", 10, 20)
        logger.log(650, "THIRD", 10, 20)
    finally:
        logger.close()
    archive = tmp_path / "receive_20261123_120000.log"
    assert archive.read_text().splitlines()[-1].endswith(" SECOND")
    assert path.read_text().rstrip().endswith(" THIRD")
