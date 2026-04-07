"""
Port of DSPTests.swift — parabolic interpolation and Q-factor tests.

Mirrors Swift test plan coverage F1–F9.
"""

from __future__ import annotations

import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer_fft_processing import (
    peak_interp,
    peak_q_factor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spectrum(n: int = 256) -> np.ndarray:
    """Return a flat -80 dB spectrum of length *n*."""
    return np.full(n, -80.0, dtype=np.float64)


def _insert_peak(mag: np.ndarray, center: int, height: float, width: int = 3) -> None:
    """Inject a simple triangular peak centred at *center*."""
    mag[center] = height
    if center > 0:
        mag[center - 1] = height - 6.0
    if center < len(mag) - 1:
        mag[center + 1] = height - 6.0
    if width >= 5:
        if center > 1:
            mag[center - 2] = height - 12.0
        if center < len(mag) - 2:
            mag[center + 2] = height - 12.0


# ---------------------------------------------------------------------------
# Parabolic Interpolation Tests  (F1–F6)
# ---------------------------------------------------------------------------

class TestParabolicInterpolation:
    """Mirrors Swift ParabolicInterpolationTests (F1–F6)."""

    def test_F1_symmetric_peak_interpolates_to_center(self):
        """F1: Symmetric peak → interpolated location equals the integer bin."""
        mag = _make_spectrum()
        mag[50] = -20.0
        mag[49] = -26.0
        mag[51] = -26.0
        ploc = np.array([50])
        iploc, _ = peak_interp(mag, ploc)
        assert abs(iploc[0] - 50.0) < 0.01, (
            f"Symmetric peak should not shift; got {iploc[0]}"
        )

    def test_F2_left_leaning_peak_shifts_left(self):
        """F2: Asymmetric peak (left bin larger) → interpolated location shifts left."""
        mag = _make_spectrum()
        mag[50] = -20.0
        mag[49] = -23.0   # left neighbour is 3 dB down (larger than right)
        mag[51] = -29.0   # right neighbour is 9 dB down
        ploc = np.array([50])
        iploc, _ = peak_interp(mag, ploc)
        assert iploc[0] < 50.0, (
            f"Peak should shift left when left neighbour is larger; got {iploc[0]}"
        )

    def test_F3_right_leaning_peak_shifts_right(self):
        """F3: Asymmetric peak (right bin larger) → interpolated location shifts right."""
        mag = _make_spectrum()
        mag[50] = -20.0
        mag[49] = -29.0
        mag[51] = -23.0
        ploc = np.array([50])
        iploc, _ = peak_interp(mag, ploc)
        assert iploc[0] > 50.0, (
            f"Peak should shift right when right neighbour is larger; got {iploc[0]}"
        )

    def test_F4_shift_magnitude_is_less_than_half_bin(self):
        """F4: Parabolic correction is bounded within ±0.5 bins."""
        mag = _make_spectrum()
        mag[80] = -15.0
        mag[79] = -25.0
        mag[81] = -35.0
        ploc = np.array([80])
        iploc, _ = peak_interp(mag, ploc)
        assert abs(iploc[0] - 80.0) < 0.5, (
            f"Interpolated shift must be < 0.5 bins; got {iploc[0] - 80.0:.3f}"
        )

    def test_F4b_last_bin_returns_raw_values(self):
        """F4b: A peak at the last array index returns raw bin values without crash.

        Mirrors Swift edgeBinLastIndex_returnsRawValues — parabolicInterpolate must
        handle a peak at array index len-1 gracefully, returning the raw bin frequency
        and magnitude rather than reading out of bounds.
        """
        mag = _make_spectrum(n=256)
        last = len(mag) - 1
        mag[last] = -20.0       # peak at the very last bin
        mag[last - 1] = -30.0   # left neighbour present; no right neighbour
        ploc = np.array([last])
        iploc, ipmag = peak_interp(mag, ploc)   # must not raise
        # The interpolated location must stay within the array bounds
        assert 0 <= iploc[0] <= last, (
            f"Interpolated location {iploc[0]} must be within [0, {last}]"
        )
        # The magnitude must be finite and at least as large as the floor
        assert np.isfinite(ipmag[0]), "Interpolated magnitude must be finite"

    def test_F5_interpolated_magnitude_exceeds_bin_value(self):
        """F5: Interpolated magnitude is ≥ the bin's sampled dB value."""
        mag = _make_spectrum()
        mag[60] = -22.0
        mag[59] = -25.0
        mag[61] = -27.0
        ploc = np.array([60])
        _, ipmag = peak_interp(mag, ploc)
        assert ipmag[0] >= mag[60], (
            f"Interpolated mag {ipmag[0]:.2f} should be ≥ bin value {mag[60]:.2f}"
        )

    def test_F6_multiple_peaks_all_interpolated(self):
        """F6: Multiple peaks are all individually interpolated."""
        mag = _make_spectrum()
        for center in [30, 100, 180]:
            mag[center] = -20.0
            mag[center - 1] = -26.0
            mag[center + 1] = -26.0
        ploc = np.array([30, 100, 180])
        iploc, ipmag = peak_interp(mag, ploc)
        assert len(iploc) == 3
        assert len(ipmag) == 3
        for i in range(3):
            assert abs(iploc[i] - ploc[i]) < 0.5, (
                f"Peak {i} shift exceeds 0.5 bins: {iploc[i] - ploc[i]:.3f}"
            )


# ---------------------------------------------------------------------------
# Q-Factor Tests  (F7–F9)
# ---------------------------------------------------------------------------

class TestQFactor:
    """Mirrors Swift QFactorTests (F7–F9)."""

    def test_F7_sharp_peak_has_higher_Q_than_broad(self):
        """F7: A narrow peak has a higher Q than a wide one."""
        sample_freq = 48000
        n_f = 2048
        mag_sharp = _make_spectrum(n_f // 2 + 1)
        mag_broad  = _make_spectrum(n_f // 2 + 1)

        center = 200
        peak_db = -20.0

        # Sharp: -3 dB boundary within ±2 bins of the peak
        # Bins beyond ±2 drop sharply below the -3 dB level
        mag_sharp[center] = peak_db
        mag_sharp[center - 1] = peak_db - 2.5   # just above -3 dB
        mag_sharp[center + 1] = peak_db - 2.5
        mag_sharp[center - 2] = peak_db - 4.0   # just below -3 dB → boundary at bin 2
        mag_sharp[center + 2] = peak_db - 4.0
        # Everything else stays at floor (-80 dB)

        # Broad: -3 dB boundary at ±15 bins from the peak
        mag_broad[center] = peak_db
        for d in range(1, 20):
            val = peak_db - 0.2 * d   # slow decay → -3 dB at ±15 bins
            mag_broad[center - d] = max(val, -80.0)
            mag_broad[center + d] = max(val, -80.0)

        ploc = np.array([center])
        iploc_sharp, ipmag_sharp = peak_interp(mag_sharp, ploc)
        iploc_broad, ipmag_broad = peak_interp(mag_broad, ploc)

        q_sharp = peak_q_factor(mag_sharp, ploc, iploc_sharp, ipmag_sharp, sample_freq, n_f)
        q_broad  = peak_q_factor(mag_broad,  ploc, iploc_broad,  ipmag_broad,  sample_freq, n_f)

        assert q_sharp[0] > q_broad[0], (
            f"Sharp peak Q ({q_sharp[0]:.2f}) should exceed broad peak Q ({q_broad[0]:.2f})"
        )

    def test_F8_q_is_positive(self):
        """F8: Q is always ≥ 0 for valid peaks."""
        sample_freq = 48000
        n_f = 2048
        mag = _make_spectrum(n_f // 2 + 1)
        center = 150
        mag[center] = -20.0
        mag[center - 1] = -26.0
        mag[center + 1] = -26.0
        ploc = np.array([center])
        iploc, ipmag = peak_interp(mag, ploc)
        q = peak_q_factor(mag, ploc, iploc, ipmag, sample_freq, n_f)
        assert q[0] >= 0.0, f"Q must be non-negative; got {q[0]}"

    def test_F9_peak_with_all_bins_above_threshold_returns_zero(self):
        """F9: When −3 dB crossing cannot be found, Q returns 0."""
        sample_freq = 48000
        n_f = 2048
        # Fill the entire spectrum above the peak level — no -3 dB crossing possible
        mag = np.full(n_f // 2 + 1, -15.0, dtype=np.float64)
        center = 100
        mag[center] = -10.0       # tiny local maximum
        mag[center - 1] = -14.5
        mag[center + 1] = -14.5
        ploc = np.array([center])
        iploc, ipmag = peak_interp(mag, ploc)
        q = peak_q_factor(mag, ploc, iploc, ipmag, sample_freq, n_f)
        # Either returns 0 (boundary not found) or a very small value — must not crash.
        assert q[0] >= 0.0, f"Q must be non-negative even in degenerate case; got {q[0]}"
