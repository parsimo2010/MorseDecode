"""
Configuration system for MorseDecode.

Priority (highest to lowest):
  1. CLI flag overrides
  2. Config file specified via --config
  3. Platform defaults file (resolved by _default_config_path)
  4. Built-in terminal defaults and shared JavaScript decoder defaults
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_type_hints

# tomllib is stdlib in Python 3.11+; fall back to third-party tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError as exc:
        raise ImportError(
            "Install 'tomli' package for Python < 3.11: pip install tomli"
        ) from exc


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InputConfig:
    device: str | int = "default"   # device name/index, or "default"
    file: str | None = None          # path to audio file
    stdin: bool = False              # read raw audio from stdin
    freq_min: int = 400              # Hz
    freq_max: int = 1000             # Hz
    bin_width: int | None = None
    channel_width_hz: int = 200      # Hz — receiver passband width


@dataclass
class AudioConfig:
    sample_rate: int = 0             # 0 uses the live device rate or 44100 Hz for stdin
    window_ms: float | None = None
    hop_ms: float | None = None
    agc_enabled: bool | None = None
    agc_window_s: float | None = None
    agc_target_rms: float | None = None
    debounce_ms: float | None = None
    on_db: float | None = None
    off_db: float | None = None


@dataclass
class DecoderConfig:
    speed_min_wpm: float | None = None
    speed_max_wpm: float | None = None


@dataclass
class DisplayConfig:
    refresh_hz: float = 8.0
    snr_bar_width: int = 5
    callsign_width: int = 9
    text_width: int = 60
    inactive_dim: bool = True
    inactive_scroll_s: float = 30.0


@dataclass
class LogConfig:
    enabled: bool = False
    path: str = "morsedecode.log"
    format: str = "text"             # "text" or "jsonl"
    rotate_mb: int = 10


@dataclass
class Config:
    input: InputConfig = field(default_factory=InputConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    decoder: DecoderConfig = field(default_factory=DecoderConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    log: LogConfig = field(default_factory=LogConfig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config_path() -> Path:
    """Return the platform-appropriate default config file path."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "morsedecode" / "config.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / "morsedecode" / "config.toml"
    return Path.home() / ".morsedecode.toml"


def _apply_dict_to_dataclass(dc: Any, data: dict) -> None:
    """Apply a flat or nested dict onto a dataclass, ignoring unknown keys."""
    dc_fields = {f.name for f in fields(dc)}
    field_types = get_type_hints(type(dc))
    for key, val in data.items():
        if key not in dc_fields:
            continue
        current = getattr(dc, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(val, dict):
            _apply_dict_to_dataclass(current, val)
        else:
            # Coerce type to match the dataclass field default type
            try:
                field_type = type(current)
                if current is None:
                    options = [option for option in get_args(field_types[key]) if option is not type(None)]
                    if len(options) == 1:
                        field_type = options[0]
                if field_type is bool:
                    # bool("false") == True so handle explicitly
                    if isinstance(val, str):
                        val = val.lower() not in ("false", "0", "no", "off")
                    else:
                        val = bool(val)
                elif field_type is not type(None):
                    val = field_type(val)
            except (ValueError, TypeError):
                pass
            setattr(dc, key, val)


def _load_toml_file(path: Path) -> dict:
    """Load a TOML file; return empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(
    config_file: str | Path | None = None,
    **cli_overrides: Any,
) -> Config:
    """
    Build a Config object from layered sources.

    Parameters
    ----------
    config_file : path to an explicit TOML config file (--config CLI flag)
    **cli_overrides : flat keyword arguments mapping section__key to value,
                      e.g.  input__device=3, decoder__speed_max_wpm=45
                      Section separator is double-underscore.
    """
    cfg = Config()

    # Layer 1: default config file
    default_path = _default_config_path()
    default_data = _load_toml_file(default_path)
    for section, values in default_data.items():
        if isinstance(values, dict):
            sub = getattr(cfg, section, None)
            if sub is not None:
                _apply_dict_to_dataclass(sub, values)

    # Layer 2: explicit config file
    if config_file is not None:
        explicit_data = _load_toml_file(Path(config_file))
        for section, values in explicit_data.items():
            if isinstance(values, dict):
                sub = getattr(cfg, section, None)
                if sub is not None:
                    _apply_dict_to_dataclass(sub, values)

    # Layer 3: CLI overrides (section__key = value)
    for compound_key, val in cli_overrides.items():
        if val is None:
            continue
        parts = compound_key.split("__", 1)
        if len(parts) == 2:
            section, key = parts
            sub = getattr(cfg, section, None)
            if sub is not None:
                _apply_dict_to_dataclass(sub, {key: val})
        else:
            # Top-level key (not common but handle gracefully)
            _apply_dict_to_dataclass(cfg, {compound_key: val})

    return cfg
