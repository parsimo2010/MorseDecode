"""
Per-channel signal detector.

Converts a stream of per-bin energy values into binary ON/OFF events with
timestamps, using an adaptive threshold derived from noise floor estimation.

Adaptive threshold
------------------
The noise floor is estimated as an exponentially-weighted running minimum of
the energy.  The threshold is set at `snr_factor` × noise_floor.  This
approach is robust to slowly drifting band noise.

Debounce
--------
Short state transitions (e.g. key bounce, brief AGC overshoot) are suppressed:
a state change is only committed after it has persisted for at least
`debounce_ms` milliseconds.

SNR estimation
--------------
SNR (dB) is continuously updated: 10 * log10(signal_energy / noise_floor).
This feeds the display and can be used for channel activity detection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class DetectorEvent:
    """A committed ON or OFF state transition."""
    is_mark: bool        # True = signal ON, False = signal OFF
    duration_ms: float   # duration of the *previous* state (the one that just ended)
    timestamp_s: float   # wall-clock time at end of this state


class AdaptiveDetector:
    """
    Adaptive threshold detector with noise-floor estimation and debounce.

    Parameters
    ----------
    hop_ms : float
        Duration of each energy frame in ms (= FFT hop size).
    debounce_ms : float
        Minimum duration for a state change to be committed.
    noise_alpha : float
        EMA decay for noise floor estimate (smaller = slower adaptation).
    snr_factor : float
        Threshold = snr_factor × noise_floor (linear, not dB).
    snr_factor_hysteresis : float
        Lower factor for turning OFF (hysteresis prevents chatter near threshold).
    """

    def __init__(
        self,
        hop_ms: float = 5.0,
        debounce_ms: float = 3.0,
        noise_alpha: float = 0.001,
        snr_factor: float = 4.0,
        snr_factor_hysteresis: float = 2.5,
    ) -> None:
        self._hop_ms = hop_ms
        self._debounce_frames = max(1, round(debounce_ms / hop_ms))
        self._noise_alpha = noise_alpha
        self._snr_factor = snr_factor
        self._snr_factor_hyst = snr_factor_hysteresis

        # State
        self._noise_floor: float = 1e-8     # running noise estimate (linear energy)
        self._committed_state: bool = False  # current committed ON/OFF
        self._pending_state: bool = False    # candidate new state
        self._pending_frames: int = 0        # frames in pending state
        self._state_frames: int = 0          # frames in committed state
        self._timestamp_s: float = 0.0       # wall clock (accumulated from frames)

        # SNR
        self._signal_energy: float = 0.0
        self.snr_db: float = -20.0

        # Pending events to be consumed by caller
        self._events: list[DetectorEvent] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def process_frames(self, energies: "list[float] | any") -> list[DetectorEvent]:
        """
        Process a sequence of energy values (one per FFT frame).

        Returns a list of DetectorEvents committed during this call.
        """
        import numpy as np
        energies = np.asarray(energies, dtype=np.float64).ravel()
        events: list[DetectorEvent] = []

        for energy in energies:
            self._timestamp_s += self._hop_ms / 1000.0

            # Update noise floor: slow minimum tracker
            # Only update when likely silent (energy below 2× current noise)
            if energy < 2.0 * self._noise_floor or self._noise_floor < 1e-10:
                self._noise_floor += self._noise_alpha * (energy - self._noise_floor)
                self._noise_floor = max(self._noise_floor, 1e-10)

            # Update signal energy estimate (fast EMA for responsive SNR display)
            self._signal_energy += 0.1 * (energy - self._signal_energy)

            # SNR in dB
            if self._noise_floor > 0 and self._signal_energy > 0:
                self.snr_db = 10.0 * math.log10(
                    max(self._signal_energy, self._noise_floor) / self._noise_floor
                )

            # Threshold with hysteresis
            if self._committed_state:
                threshold = self._snr_factor_hyst * self._noise_floor
            else:
                threshold = self._snr_factor * self._noise_floor

            raw_state = energy >= threshold

            # Debounce
            if raw_state == self._pending_state:
                self._pending_frames += 1
            else:
                self._pending_state = raw_state
                self._pending_frames = 1

            if self._pending_frames >= self._debounce_frames and raw_state != self._committed_state:
                # State transition committed
                committed_duration_ms = self._state_frames * self._hop_ms
                ev = DetectorEvent(
                    is_mark=raw_state,
                    duration_ms=committed_duration_ms,
                    timestamp_s=self._timestamp_s,
                )
                events.append(ev)
                self._committed_state = raw_state
                self._state_frames = self._pending_frames
            else:
                self._state_frames += 1

        return events

    def reset(self) -> None:
        """Reset transient state (called after long silence)."""
        self._committed_state = False
        self._pending_state = False
        self._pending_frames = 0
        self._state_frames = 0

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def threshold(self) -> float:
        return self._snr_factor * self._noise_floor

    @property
    def is_active(self) -> bool:
        """True if the channel is currently in the ON state."""
        return self._committed_state
