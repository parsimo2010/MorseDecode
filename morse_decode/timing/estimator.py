"""
Timing estimator for CW speed and spacing.

Uses histogram analysis to separate dits from dahs (marks) and inter-element
gaps from inter-letter and word gaps (spaces).

Robustness for bad fists
------------------------
The histogram uses exponential decay so recent observations gradually replace
old ones, but the decay is slow enough that a few outlier timings don't
immediately corrupt the estimate.  Peak-finding uses the histogram mode
(most frequent bin) rather than the mean, which is robust to outliers and to
the asymmetric distributions produced by inconsistent sending.

Speed range constraints
-----------------------
CW speed in WPM determines the standard dit duration:
    dit_ms = 1200 / wpm

The estimator uses this to validate histogram peaks: a peak that would imply
a speed outside [speed_min_wpm, speed_max_wpm] is rejected or clamped.

Thresholds
----------
After estimating dit_ms and dah_ms:
  - dit/dah threshold      ≈ (dit_ms + dah_ms) / 2   (midpoint)
  - element/letter threshold ≈ dit_ms * 2.5            (standard: 3 dit)
  - letter/word threshold    ≈ dit_ms * 5.0            (standard: 7 dit)

A small margin is applied around each threshold; combined with the beam
search's ambiguity_factor, this handles bad-fist spacing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..decoder.buffer import TimingEvent


# ---------------------------------------------------------------------------
# Output dataclass (consumed by BeamDecoder)
# ---------------------------------------------------------------------------

@dataclass
class TimingEstimate:
    """Current best estimate of CW timing parameters."""

    dit_ms: float = 0.0          # estimated dit duration
    dah_ms: float = 0.0          # estimated dah duration (ideally 3 × dit_ms)
    speed_wpm: float = 0.0       # derived speed in WPM
    n_samples: int = 0           # number of mark events seen so far
    confident: bool = False      # True once enough samples collected

    @property
    def dit_dah_threshold_ms(self) -> float:
        """Midpoint threshold between dit and dah durations."""
        if self.dit_ms <= 0 or self.dah_ms <= 0:
            return 0.0
        return (self.dit_ms + self.dah_ms) / 2.0

    @property
    def element_letter_threshold_ms(self) -> float:
        """Threshold between intra-character gap and inter-letter gap."""
        if self.dit_ms <= 0:
            return 0.0
        return self.dit_ms * 2.5

    @property
    def letter_word_threshold_ms(self) -> float:
        """Threshold between inter-letter gap and inter-word gap."""
        if self.dit_ms <= 0:
            return 0.0
        return self.dit_ms * 5.0


# ---------------------------------------------------------------------------
# Histogram estimator
# ---------------------------------------------------------------------------

class TimingEstimator:
    """
    Online histogram-based estimator for CW timing.

    Parameters
    ----------
    speed_min_wpm, speed_max_wpm : float
        Allowed speed range; constrains histogram peak search.
    histogram_bins : int
        Resolution of the duration histograms.
    estimator_decay : float
        Per-event exponential decay applied to all histogram bins (keeps
        the histogram responsive to speed changes mid-transmission).
    outlier_pct : float
        Percentage of the extreme tails to ignore when finding peaks.
        Handles wildly out-of-range timings from bad fists.
    min_samples : int
        Minimum number of mark events before reporting a confident estimate.
    """

    # Duration range for histograms (ms)
    _HIST_MIN_MS: float = 5.0
    _HIST_MAX_MS: float = 2000.0

    def __init__(
        self,
        speed_min_wpm: float = 5.0,
        speed_max_wpm: float = 50.0,
        histogram_bins: int = 60,
        estimator_decay: float = 0.97,
        outlier_pct: float = 10.0,
        min_samples: int = 10,
    ) -> None:
        self._speed_min_wpm = speed_min_wpm
        self._speed_max_wpm = speed_max_wpm
        self._n_bins = histogram_bins
        self._decay = estimator_decay
        self._outlier_pct = outlier_pct
        self._min_samples = min_samples

        # Duration limits derived from speed range
        self._dit_min_ms = 1200.0 / speed_max_wpm   # fastest dit
        self._dit_max_ms = 1200.0 / speed_min_wpm   # slowest dit
        self._dah_max_ms = self._dit_max_ms * 4.0   # slowest dah (generous)

        # Log-spaced bins cover the full range; log scale better handles
        # the wide dynamic range (5 ms to 2 s)
        log_min = math.log(self._HIST_MIN_MS)
        log_max = math.log(self._HIST_MAX_MS)
        self._bin_edges = np.exp(np.linspace(log_min, log_max, histogram_bins + 1))
        self._bin_centers = np.sqrt(self._bin_edges[:-1] * self._bin_edges[1:])  # geometric mean

        # Mark histogram (dits and dahs)
        self._mark_hist = np.zeros(histogram_bins, dtype=np.float64)
        # Space histogram (gaps)
        self._space_hist = np.zeros(histogram_bins, dtype=np.float64)

        self._n_marks: int = 0
        self._estimate = TimingEstimate()

    # ------------------------------------------------------------------
    # Feed data
    # ------------------------------------------------------------------

    def update(self, events: list[TimingEvent]) -> bool:
        """
        Feed new timing events.

        Returns True if the estimate changed significantly (caller may want
        to trigger a rewind-and-replay).
        """
        old_speed = self._estimate.speed_wpm

        for ev in events:
            if ev.duration_ms < self._HIST_MIN_MS or ev.duration_ms > self._HIST_MAX_MS:
                continue  # ignore extreme outliers
            idx = int(np.searchsorted(self._bin_edges[1:], ev.duration_ms))
            idx = min(idx, self._n_bins - 1)

            # Decay before adding (keeps histogram fresh)
            if ev.is_mark:
                self._mark_hist *= self._decay
                self._mark_hist[idx] += 1.0
                self._n_marks += 1
            else:
                self._space_hist *= self._decay
                self._space_hist[idx] += 1.0

        self._refit()

        # Significant change: > 15% speed shift
        new_speed = self._estimate.speed_wpm
        if old_speed > 0 and new_speed > 0:
            return abs(new_speed - old_speed) / old_speed > 0.15
        return False

    def reset(self) -> None:
        """Reset after long silence / new transmission."""
        self._mark_hist[:] = 0.0
        self._space_hist[:] = 0.0
        self._n_marks = 0
        self._estimate = TimingEstimate()

    @property
    def estimate(self) -> TimingEstimate:
        return self._estimate

    # ------------------------------------------------------------------
    # Internal — histogram peak finding
    # ------------------------------------------------------------------

    def _refit(self) -> None:
        """Recompute timing estimate from current histograms."""
        if self._n_marks < self._min_samples:
            return

        dit_ms, dah_ms = self._fit_mark_histogram()
        if dit_ms <= 0:
            return

        speed_wpm = 1200.0 / dit_ms
        # Clamp to valid range
        speed_wpm = max(self._speed_min_wpm, min(self._speed_max_wpm, speed_wpm))
        dit_ms = 1200.0 / speed_wpm

        self._estimate = TimingEstimate(
            dit_ms=dit_ms,
            dah_ms=dah_ms if dah_ms > 0 else dit_ms * 3.0,
            speed_wpm=speed_wpm,
            n_samples=self._n_marks,
            confident=self._n_marks >= self._min_samples * 2,
        )

    def _fit_mark_histogram(self) -> tuple[float, float]:
        """
        Find two peaks in the mark histogram corresponding to dits and dahs.

        Returns (dit_ms, dah_ms).  Returns (0, 0) if the histogram is
        insufficient or ambiguous.
        """
        hist = self._mark_hist.copy()
        total = hist.sum()
        if total < 1:
            return 0.0, 0.0

        # Trim outlier tails by zero-ing extreme bins
        trim_count = self._outlier_pct / 100.0 * total
        cumsum = np.cumsum(hist)
        lo_mask = cumsum < trim_count
        hi_mask = cumsum > total - trim_count
        hist[lo_mask] = 0.0
        hist[hi_mask] = 0.0

        if hist.sum() < 1:
            return 0.0, 0.0

        # Smooth with a Gaussian kernel (width 1.5 bins) for stability
        hist = _gaussian_smooth(hist, sigma=1.5)

        # Find the global maximum — this is most likely the dit peak
        # (dits outnumber dahs by ~3:1 in typical CW)
        peak1_idx = int(np.argmax(hist))
        peak1_ms = self._bin_centers[peak1_idx]

        # The expected dah duration is ~3× dit
        expected_dah_ms = peak1_ms * 3.0
        expected_dah_min = peak1_ms * 2.0
        expected_dah_max = peak1_ms * 5.0

        # Check that peak1 is in valid dit range
        if not (self._dit_min_ms <= peak1_ms <= self._dit_max_ms):
            # Maybe the histogram is dominated by dahs; try the shorter tail
            short_mask = self._bin_centers <= self._dit_max_ms
            if short_mask.any():
                sub = hist.copy()
                sub[~short_mask] = 0.0
                if sub.sum() > 0:
                    peak1_idx = int(np.argmax(sub))
                    peak1_ms = self._bin_centers[peak1_idx]
                    if not (self._dit_min_ms <= peak1_ms <= self._dit_max_ms):
                        return 0.0, 0.0
                else:
                    return 0.0, 0.0
            else:
                return 0.0, 0.0

        # Find the dah peak: search in the expected range, away from the dit peak
        mask = (self._bin_centers >= expected_dah_min) & (self._bin_centers <= expected_dah_max)
        if mask.any() and hist[mask].sum() > 0:
            sub = hist.copy()
            sub[~mask] = 0.0
            peak2_idx = int(np.argmax(sub))
            peak2_ms = self._bin_centers[peak2_idx]
        else:
            # No clear dah peak — use the theoretical 3:1 ratio
            peak2_ms = peak1_ms * 3.0

        return peak1_ms, peak2_ms


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _gaussian_smooth(arr: np.ndarray, sigma: float = 1.5) -> np.ndarray:
    """Apply a simple Gaussian blur to a 1D array using a truncated kernel."""
    radius = max(1, int(sigma * 3))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    return np.convolve(arr, kernel, mode="same")
