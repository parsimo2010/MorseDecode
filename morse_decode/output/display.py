"""
Rich-based multi-line live terminal display.

One row per passband. The readout shows the acquired carrier frequency
or the passband center before acquisition.
┌─────────┬─────────────┬────────┬───────────┬──────────────────────────────────────────────┐
│  425 Hz │ ###..  18dB │ 15 wpm │ W1AW      │ CQ CQ DE W1AW W1AW K                        │
│  700 Hz │ .....  --dB │ -- wpm │           │                                              │
...
└─────────┴─────────────┴────────┴───────────┴──────────────────────────────────────────────┘

Inactive rows can be dimmed. Their text scrolls off over the configured time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

# Signal contrast bar characters (ASCII-safe)
_BAR_FULL = "#"
_BAR_EMPTY = "."

# Style constants
_STYLE_ACTIVE = "bright_white"
_STYLE_INACTIVE = "dim"
_STYLE_FREQ = "cyan"
_STYLE_CALLSIGN = "bright_yellow bold"
_STYLE_SPEED = "green"


# ---------------------------------------------------------------------------
# Per-bin state
# ---------------------------------------------------------------------------

@dataclass
class BinDisplayState:
    """Display state for one receiver passband."""
    freq_hz: int
    snr_db: float = -20.0
    speed_wpm: float = 0.0
    last_callsign: str = ""
    text: str = ""              # full decoded text (grows over time)
    active: bool = False
    last_active_time: float = field(default_factory=time.monotonic)
    # Scroll offset: how many chars have scrolled off the left for inactive bins
    _scroll_offset: int = 0

    def mark_active(self) -> None:
        self.active = True
        self.last_active_time = time.monotonic()
        self._scroll_offset = 0

    def mark_inactive(self) -> None:
        self.active = False

    def update_scroll(self, text_width: int, scroll_s: float) -> None:
        """Advance scroll offset for inactive bins so text drifts off over time."""
        if self.active:
            return
        elapsed = time.monotonic() - self.last_active_time
        if scroll_s <= 0:
            self._scroll_offset = len(self.text)
            return
        chars_per_s = text_width / scroll_s
        self._scroll_offset = min(int(elapsed * chars_per_s), text_width)

    def visible_text(self, text_width: int) -> str:
        """Return the text slice to display, scrolling oldest chars off the left when inactive."""
        full = self.text
        if not full:
            return ""
        # Viewport start shifts rightward as scroll_offset increases,
        # so the oldest (leftmost) characters exit the left side first.
        start = max(0, len(full) - text_width + self._scroll_offset)
        end = min(len(full), start + text_width)
        return full[start:end]


# ---------------------------------------------------------------------------
# SNR bar renderer
# ---------------------------------------------------------------------------

def _snr_bar(snr_db: float, width: int = 5, max_db: float = 30.0) -> str:
    filled = int(round(max(0.0, min(snr_db, max_db)) / max_db * width))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def _snr_label(snr_db: float) -> str:
    if snr_db < 0:
        return "--dB"
    return f"{int(snr_db):2d}dB"


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class Display:
    """
    Manages the Rich Live display showing all receiver passbands.
    """

    def __init__(
        self,
        bin_states: list[BinDisplayState],
        snr_bar_width: int = 5,
        callsign_width: int = 9,
        text_width: int = 60,
        refresh_hz: float = 8.0,
        inactive_dim: bool = True,
        inactive_scroll_s: float = 30.0,
    ) -> None:
        self._bins = bin_states
        self._snr_bar_width = snr_bar_width
        self._callsign_width = callsign_width
        self._text_width = text_width
        self._inactive_dim = inactive_dim
        self._inactive_scroll_s = inactive_scroll_s
        self._console = Console()
        self._live = Live(
            self._build_table(),
            console=self._console,
            refresh_per_second=refresh_hz,
            transient=False,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Display":
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        self._live.__exit__(*args)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the table and push it to the Live display."""
        for bs in self._bins:
            bs.update_scroll(self._text_width, self._inactive_scroll_s)
        self._live.update(self._build_table())

    # ------------------------------------------------------------------
    # Table builder
    # ------------------------------------------------------------------

    def _build_table(self) -> Table:
        table = Table(
            show_header=True,
            show_edge=True,
            show_lines=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("Freq", style=_STYLE_FREQ, width=7, no_wrap=True)
        table.add_column(
            f"{'Signal':^{self._snr_bar_width + 5}}",
            width=self._snr_bar_width + 5,
            no_wrap=True,
        )
        table.add_column("Speed", width=7, no_wrap=True)
        table.add_column("Callsign", width=self._callsign_width, no_wrap=True)
        table.add_column("Decoded", no_wrap=True)

        for bs in self._bins:
            row_style = _STYLE_ACTIVE if bs.active else (_STYLE_INACTIVE if self._inactive_dim else "")

            # Frequency
            freq_text = Text(f"{bs.freq_hz} Hz", style=_STYLE_FREQ if bs.active else "dim cyan")

            # SNR bar + level
            bar = _snr_bar(bs.snr_db, self._snr_bar_width)
            label = _snr_label(bs.snr_db) if bs.active else "--dB"
            snr_text = Text(f"{bar} {label}", style=row_style)

            # Speed
            if bs.speed_wpm > 0 and bs.active:
                spd_text = Text(f"{bs.speed_wpm:.0f} wpm", style=_STYLE_SPEED)
            else:
                spd_text = Text("-- wpm", style="dim")

            # Callsign
            cs = bs.last_callsign or ""
            cs_text = Text(cs.ljust(self._callsign_width - 1), style=_STYLE_CALLSIGN if cs else row_style)

            # Decoded text (scrolling window)
            visible = bs.visible_text(self._text_width)
            decoded_text = Text(visible.ljust(self._text_width), style=row_style)

            table.add_row(freq_text, snr_text, spd_text, cs_text, decoded_text)

        return table

    # ------------------------------------------------------------------
    # Utility: print a message above the live display
    # ------------------------------------------------------------------

    def print_status(self, msg: str) -> None:
        self._console.print(msg)
