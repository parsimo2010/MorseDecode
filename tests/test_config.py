import pytest
from click.testing import CliRunner

from morse_decode import cli, config


@pytest.fixture
def default_file(tmp_path, monkeypatch):
    path = tmp_path / "default.toml"
    monkeypatch.setattr(config, "_default_config_path", lambda: path)
    return path


def test_device_type_is_preserved_across_config_layers(tmp_path, default_file):
    default_file.write_text('[input]\ndevice = "USB Audio"\n', encoding="utf-8")
    explicit = tmp_path / "station.toml"
    explicit.write_text("[input]\ndevice = 3\n", encoding="utf-8")

    assert config.load_config().input.device == "USB Audio"
    assert config.load_config(explicit).input.device == 3
    assert config.load_config(explicit, input__device="3").input.device == "3"


@pytest.mark.parametrize("contents", [None, "[input"])
def test_cli_reports_bad_explicit_config(tmp_path, monkeypatch, default_file, contents):
    path = tmp_path / "explicit.toml"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "run_decoder", lambda *args, **kwargs: calls.append(args))
    runner = CliRunner()

    result = runner.invoke(cli.main, ["--config", str(path)])
    assert result.exit_code == 1
    assert str(path) in result.output
    assert not calls
    assert runner.invoke(cli.main).exit_code == 0
    assert len(calls) == 1
