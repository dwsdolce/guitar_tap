# @parity test/dsp
"""
Port of DSPTests.swift — parabolic interpolation and Q-factor calculation (F1–F9).

REWRITTEN 2026-09-20 (#17) — this file previously did not test the code the app runs.

It exercised ``peak_interp`` and ``peak_q_factor`` from
``realtime_fft_analyzer_fft_processing``: NumPy ports of the peak-finding section of Swift's
findPeaks that **nothing in the application ever called**. The app uses the scalar pair on
TapToneAnalyzer — ``_parabolic_interpolate`` and ``_calculate_q_factor`` — which are the direct
counterparts of Swift's ``parabolicInterpolate`` / ``calculateQFactor`` and are what the capture
and peak-analysis paths run. Those had no test at all.

So test/dsp paired Swift's tests of the live code with this edition's tests of a second,
unused implementation. Swift and the web each have exactly one; the duplicate was Python-only.
The dead trio (peak_detection, peak_interp, peak_q_factor) has been removed, and these tests now
call what the app calls.

This is the same defect test_peak_finding.py records finding on 2026-07-19 in test/peaks. It was
fixed there by relocating the FFT-layer tests rather than repointing them, which left this copy
alive and the sibling slug untouched. See SLUG-SWEEP.md F14.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402


def _sut() -> TapToneAnalyzer:
    """The analyzer, which owns both functions under test. Mirrors Swift's makeSUT()."""
    return TapToneAnalyzer()


def _spectrum(
    peak_hz: float,
    peak_db: float,
    half_width: float,
    bin_count: int = 2048,
    sample_rate: int = 48000,
    noise_floor: float = -100.0,
) -> tuple[list[float], list[float]]:
    """A Gaussian peak on a noise floor — the same synthetic spectrum Swift's makeSpectrum
    builds, with the same defaults, so the Q cases compare like with like."""
    bin_width = (sample_rate / 2) / (bin_count - 1)
    sigma = half_width / 2.355
    mags: list[float] = []
    freqs: list[float] = []
    for i in range(bin_count):
        f = i * bin_width
        freqs.append(f)
        dist = f - peak_hz
        gauss = peak_db + (-dist * dist / (2 * sigma * sigma))
        mags.append(max(gauss, noise_floor))
    return mags, freqs


def _index_of_max(values: list[float]) -> int:
    return max(range(len(values)), key=lambda i: values[i])


# ---------------------------------------------------------------------------
# Parabolic interpolation (F1–F6). Mirrors Swift ParabolicInterpolationTests.
# ---------------------------------------------------------------------------

class TestParabolicInterpolation:
    """Mirrors Swift ParabolicInterpolationTests."""

    def test_F1_equal_neighbours_give_the_exact_centre_bin(self):
        """Both neighbours equal → the numerator (lval - rval) is 0, so δ = 0."""
        sut = _sut()
        mags = [-80.0, -80.0, -30.0, -30.0, -30.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert abs(freq - 30) < 0.01, f"expected ≈30 Hz, got {freq}"

    def test_F2_higher_left_neighbour_shifts_the_peak_left(self):
        sut = _sut()
        mags = [-80.0, -80.0, -25.0, -20.0, -35.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert freq < 30, f"expected a left shift, got {freq}"

    def test_F3_higher_right_neighbour_shifts_the_peak_right(self):
        sut = _sut()
        mags = [-80.0, -80.0, -35.0, -20.0, -25.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert freq > 30, f"expected a right shift, got {freq}"

    def test_F4_bin_zero_falls_back_to_the_raw_bin(self):
        """Rather than reading index -1."""
        sut = _sut()
        mags = [-20.0, -30.0, -40.0, -50.0]
        freqs = [0.0, 10.0, 20.0, 30.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, 0)
        assert freq == 0.0
        assert mag == -20.0

    def test_F4b_last_bin_falls_back_to_the_raw_bin(self):
        """Rather than reading past the end."""
        sut = _sut()
        mags = [-50.0, -40.0, -30.0, -20.0]
        freqs = [0.0, 10.0, 20.0, 30.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, len(mags) - 1)
        assert freq == 30.0
        assert mag == -20.0

    def test_F5_flat_top_gives_neither_nan_nor_inf(self):
        """lval = val = rval, so the denominator is exactly 0.

        Without the guard this is 0/0 → NaN, and a NaN frequency travels into the saved
        measurement.
        """
        sut = _sut()
        mags = [-80.0, -80.0, -20.0, -20.0, -20.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, 3)
        assert not math.isnan(freq) and math.isfinite(freq)
        assert not math.isnan(mag) and math.isfinite(mag)
        # And it returns the raw bin, not something invented.
        assert freq == 30.0
        assert mag == -20.0

    def test_F6_interpolated_magnitude_is_at_least_the_bin_magnitude(self):
        """The parabola's apex sits at or above the sampled bins when the centre is a local max."""
        sut = _sut()
        mags, freqs = _spectrum(peak_hz=200, peak_db=-15, half_width=8)
        i = _index_of_max(mags)
        _, interp_mag = sut._parabolic_interpolate(mags, freqs, i)
        assert interp_mag >= mags[i] - 0.5, f"{interp_mag} should be ≥ {mags[i]}"


# ---------------------------------------------------------------------------
# Q factor and −3 dB bandwidth (F7–F9). Mirrors Swift QFactorTests.
# ---------------------------------------------------------------------------

class TestQFactor:
    """Mirrors Swift QFactorTests."""

    def test_F7_sharp_peak_has_a_higher_q_than_a_broad_one(self):
        sut = _sut()
        sharp_mags, sharp_freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=20)
        broad_mags, broad_freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=80)
        si = _index_of_max(sharp_mags)
        bi = _index_of_max(broad_mags)
        sharp_q, sharp_bw = sut._calculate_q_factor(sharp_mags, sharp_freqs, si, sharp_mags[si])
        broad_q, _ = sut._calculate_q_factor(broad_mags, broad_freqs, bi, broad_mags[bi])
        assert sharp_q > broad_q, f"sharp {sharp_q} should exceed broad {broad_q}"
        assert sharp_bw > 0
        assert sharp_q > 0

    def test_F8_broad_peak_gives_a_plausible_low_q(self):
        """80 Hz half-width at 200 Hz → Q ≈ 200/160 ≈ 1.25."""
        sut = _sut()
        mags, freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=80)
        i = _index_of_max(mags)
        q, _ = sut._calculate_q_factor(mags, freqs, i, mags[i])
        assert 0 < q < 15, f"expected 0 < Q < 15 for a broad peak, got {q}"

    def test_F9_no_bin_below_threshold_means_bandwidth_spans_the_spectrum(self):
        """When nothing drops 3 dB below the peak, the walk runs to both edges.

        This was called ``test_F9_peak_with_all_bins_above_threshold_returns_zero`` and asserted
        only ``q >= 0``. Q is centre/span here, not 0 — the name promised a behaviour the body
        never checked and that does not hold. A test name is a comment. See SLUG-SWEEP.md F14.
        """
        sut = _sut()
        n = 100
        mags = [-20.0] * n
        freqs = [i * 10.0 for i in range(n)]
        q, bw = sut._calculate_q_factor(mags, freqs, 50, -20.0)
        # The walk reaches bin 0 and bin 99, so the bandwidth is the full span: 990 - 0.
        assert abs(bw - 990.0) < 1e-3, f"bandwidth should span the spectrum, got {bw}"
        # Q = centre / span = 500 / 990.
        assert abs(q - 0.50505) < 1e-4, f"Q should be centre/span ≈ 0.505, got {q}"
        assert math.isfinite(q) and not math.isnan(q)
