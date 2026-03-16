"""Tests for timing estimator and segmenter."""

import pytest
import numpy as np
from morse_decode.decoder.buffer import TimingEvent
from morse_decode.timing.estimator import TimingEstimator, TimingEstimate


def _make_events(pattern: list[tuple[float, bool]], base_time: float = 0.0) -> list[TimingEvent]:
    """Helper: build TimingEvent list from (duration_ms, is_mark) pairs."""
    events = []
    t = base_time
    for dur, is_mark in pattern:
        t += dur / 1000.0
        events.append(TimingEvent(duration_ms=dur, is_mark=is_mark, timestamp_s=t))
    return events


class TestTimingEstimator:
    def _make_cw_events(self, dit_ms: float, n_chars: int = 20) -> list[TimingEvent]:
        """Generate synthetic clean CW events for a given dit duration."""
        dah_ms = dit_ms * 3.0
        gap_ms = dit_ms        # intra-char gap
        letter_ms = dit_ms * 3.0
        pattern = []
        # Alternate simple characters: E (.) and T (-) separated by letter gaps
        for i in range(n_chars):
            if i % 2 == 0:
                pattern.append((dit_ms, True))   # E = .
            else:
                pattern.append((dah_ms, True))   # T = -
            pattern.append((letter_ms, False))   # letter gap
        return _make_events(pattern)

    def test_speed_15wpm(self):
        dit_ms = 1200.0 / 15.0  # 80 ms
        events = self._make_cw_events(dit_ms, n_chars=30)
        est = TimingEstimator(speed_min_wpm=5, speed_max_wpm=50)
        est.update(events)
        result = est.estimate
        if result.speed_wpm > 0:
            assert abs(result.speed_wpm - 15.0) < 5.0, \
                f"expected ~15 wpm, got {result.speed_wpm:.1f}"

    def test_speed_25wpm(self):
        dit_ms = 1200.0 / 25.0  # 48 ms
        events = self._make_cw_events(dit_ms, n_chars=30)
        est = TimingEstimator(speed_min_wpm=5, speed_max_wpm=50)
        est.update(events)
        result = est.estimate
        if result.speed_wpm > 0:
            assert abs(result.speed_wpm - 25.0) < 8.0, \
                f"expected ~25 wpm, got {result.speed_wpm:.1f}"

    def test_speed_clamp(self):
        # Send impossibly fast events (1 ms dits → 1200 wpm)
        events = self._make_cw_events(1.0, n_chars=30)
        est = TimingEstimator(speed_min_wpm=5, speed_max_wpm=50)
        est.update(events)
        result = est.estimate
        if result.speed_wpm > 0:
            assert result.speed_wpm <= 50.0

    def test_reset_clears_estimate(self):
        dit_ms = 1200.0 / 20.0
        events = self._make_cw_events(dit_ms, n_chars=30)
        est = TimingEstimator()
        est.update(events)
        est.reset()
        assert est.estimate.dit_ms == 0.0
        assert est.estimate.speed_wpm == 0.0

    def test_thresholds_sensible(self):
        est = TimingEstimator()
        estimate = TimingEstimate(dit_ms=80.0, dah_ms=240.0, speed_wpm=15.0, n_samples=30)
        assert estimate.dit_dah_threshold_ms == pytest.approx(160.0)
        assert estimate.element_letter_threshold_ms == pytest.approx(200.0)
        assert estimate.letter_word_threshold_ms == pytest.approx(400.0)

    def test_no_estimate_before_min_samples(self):
        est = TimingEstimator(speed_min_wpm=5, speed_max_wpm=50)
        events = self._make_cw_events(80.0, n_chars=3)  # too few
        est.update(events)
        assert est.estimate.speed_wpm == 0.0


class TestTimingEstimate:
    def test_zero_dit_thresholds(self):
        e = TimingEstimate()
        assert e.dit_dah_threshold_ms == 0.0
        assert e.element_letter_threshold_ms == 0.0
        assert e.letter_word_threshold_ms == 0.0

    def test_confident_flag(self):
        e = TimingEstimate(n_samples=5, confident=False)
        assert not e.confident
        e2 = TimingEstimate(n_samples=25, confident=True)
        assert e2.confident
