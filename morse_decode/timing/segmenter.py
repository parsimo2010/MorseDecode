"""
Run-length segmenter.

Converts a stream of DetectorEvents (ON/OFF transitions) into TimingEvents
(duration, is_mark, timestamp) suitable for the timing estimator and beam
search decoder.

The segmenter also tracks long silence periods and signals when the speed
estimator should be reset.
"""

from __future__ import annotations

from ..signal.detector import DetectorEvent
from ..decoder.buffer import TimingEvent


class RunLengthSegmenter:
    """
    Converts detector ON/OFF events into timing events.

    The detector produces an event each time the signal state changes, with
    `duration_ms` being the duration of the state that just *ended*.  This
    class simply repackages those events as TimingEvent objects.

    It also tracks silence duration to detect when transmission has ended and
    the speed estimator should reset.

    Parameters
    ----------
    silence_reset_s : float
        If signal is OFF for longer than this, `reset_needed` becomes True.
    """

    def __init__(self, silence_reset_s: float = 5.0) -> None:
        self._silence_reset_s = silence_reset_s
        self._silence_ms: float = 0.0
        self.reset_needed: bool = False

    def process(self, events: list[DetectorEvent]) -> list[TimingEvent]:
        """
        Convert detector events to timing events.

        Returns a (possibly empty) list of TimingEvent objects in order.
        """
        timing_events: list[TimingEvent] = []

        for ev in events:
            if ev.duration_ms <= 0:
                continue

            if not ev.is_mark:
                # This event signals a transition TO mark, meaning an OFF period just ended
                self._silence_ms += ev.duration_ms
                if self._silence_ms >= self._silence_reset_s * 1000.0:
                    if not self.reset_needed:
                        self.reset_needed = True
            else:
                # Transition TO off, meaning a mark (ON) period just ended.
                # Reset silence accumulator since we have activity.
                self._silence_ms = 0.0
                self.reset_needed = False

            timing_events.append(
                TimingEvent(
                    duration_ms=ev.duration_ms,
                    is_mark=not ev.is_mark,  # flip: event.is_mark = new state, timing wants old state
                    timestamp_s=ev.timestamp_s,
                )
            )

        return timing_events

    def reset(self) -> None:
        self._silence_ms = 0.0
        self.reset_needed = False
