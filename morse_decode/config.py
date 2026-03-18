"""
Configuration system for MorseDecode.

Priority (highest to lowest):
  1. CLI flag overrides
  2. Config file specified via --config
  3. Default config file (~/.morsedecode.toml or %APPDATA%/morsedecode/config.toml)
  4. Hard-coded defaults (dataclass field defaults below)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any

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
    bin_width: int = 25              # Hz — FFT frequency resolution per bin
    channel_width_hz: int = 200      # Hz — decoding channel width (must be >= bin_width)


@dataclass
class AudioConfig:
    sample_rate: int = 0             # 0 = auto-detect
    window_ms: float = 40.0          # FFT window length in ms (40 ms → 25 Hz bins)
    hop_ms: float = 5.0              # FFT hop size in ms
    agc_enabled: bool = False
    agc_window_s: float = 10.0       # RMS averaging window
    agc_target_rms: float = 0.1      # target normalized RMS
    debounce_ms: float = 2.0         # min signal state duration (ms)
    on_db: float = 24.0              # ON  when 10*log10(bin1/bin3) >= on_db
    off_db: float = 20.0              # OFF when 10*log10(bin1/bin3) <  off_db


@dataclass
class DecoderConfig:
    beam_width: int = 16             # beam search width (larger = more bad-fist tolerance)
    speed_min_wpm: float = 5.0
    speed_max_wpm: float = 50.0
    histogram_bins: int = 60
    estimator_decay: float = 0.97    # histogram exponential decay per dit/dah event
    outlier_pct: float = 10.0        # % of extreme values to trim when fitting peaks
    silence_reset_s: float = 5.0     # silence seconds before speed estimator resets
    rewind_buffer_s: float = 10.0    # seconds of timing events to buffer for re-decode
    ambiguity_factor: float = 1.5    # widens dit/dah decision boundary (>1 = more branching)


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


def _merge_dict(base: dict, override: dict) -> dict:
    """Recursively merge override into base (modifies base in-place, returns it)."""
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _merge_dict(base[key], val)
        else:
            base[key] = val
    return base


def _apply_dict_to_dataclass(dc: Any, data: dict) -> None:
    """Apply a flat or nested dict onto a dataclass, ignoring unknown keys."""
    dc_fields = {f.name for f in fields(dc)}
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
                if field_type is bool:
                    # bool("false") == True so handle explicitly
                    if isinstance(val, str):
                        val = val.lower() not in ("false", "0", "no", "off")
                    else:
                        val = bool(val)
                elif current is None:
                    val = val  # keep as-is when default is None
                else:
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
                      e.g.  input__device=3, decoder__beam_width=32
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


def compute_bin_centers(cfg: InputConfig) -> list[int]:
    """Return list of bin center frequencies in Hz."""
    half = cfg.bin_width // 2
    centers = []
    f = cfg.freq_min + half
    while f <= cfg.freq_max - half:
        centers.append(f)
        f += cfg.bin_width
    return centers
