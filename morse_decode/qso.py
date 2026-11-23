"""Reconstruct a QSO from receive logs and timestamped transmit events."""

import json
from datetime import datetime, timezone
from pathlib import Path


def read_events(path: Path, default_direction: str):
    """Yield UTC-timestamped events, accepting older receive logs."""
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event["text"], str):
                    raise ValueError("expected an event with a text string")
                timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                direction = event.setdefault("direction", default_direction)
                if direction not in ("rx", "tx") or (default_direction == "tx" and direction != "tx"):
                    raise ValueError("invalid event direction")
                if direction == "tx" and timestamp.tzinfo is None:
                    raise ValueError("transmit timestamps require a UTC offset")
                event["timestamp"] = timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            yield event


def qso_timeline(receive: Path, transmit: Path | None = None):
    events = list(read_events(receive, "rx"))
    if transmit is not None:
        events.extend(read_events(transmit, "tx"))
    return sorted(events, key=lambda event: event["timestamp"])
