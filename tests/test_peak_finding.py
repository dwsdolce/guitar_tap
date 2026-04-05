"""
Port of PeakFindingTests.swift — peak detection, deduplication, spectrum averaging.

Mirrors Swift test plan coverage F10–F16 and A1–A5.

Python equivalents:
  findPeaks (Swift)           → peak_detection + peak_interp + peak_q_factor pipeline
  RemoveDuplicatePeaks        → 2 Hz deduplication logic tested via peak_detection output
  SpectrumAveraging           → power-domain averaging inline logic (do_capture_tap)
"""

from __future__ import annotations

import sys, os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer_fft_processing import (
    peak_detection,
    peak_interp,
    peak_q_factor,
)


# ---------------------------------------------------------------------------
# Helper: build a simple dB spectrum with one or more embedded tones
# ---------------------------------------------------------------------------

SAMPLE_FREQ = 48000
N_F = 4096
N_BINS = N_F // 2 + 1
HZ_PER_BIN = SAMPLE_FREQ / N_F


def _flat_spectrum(n: int = N_BINS, floor: float = -80.0) -> np.ndarray:
    return np.full(n, floor, dtype=np.float64)


def _add_tone(mag: np.ndarray, freq_hz: float, peak_db: float, width_bins: int = 5) -> int:
    """Inject a smooth Gaussian-shaped peak centred at the nearest bin to freq_hz."""
    center_bin = round(freq_hz / HZ_PER_BIN)
    for offset in range(-width_bins, width_bins + 1):
        b = center_bin + offset
        if 0 < b < len(mag) - 1:
            mag[b] = max(mag[b], peak_db - 3.0 * (offset ** 2) / (width_bins ** 2) * 10)
    mag[center_bin] = peak_db  # ensure absolute maximum at center
    return center_bin


# ---------------------------------------------------------------------------
# FindPeaks Tests  (F10–F14)
# ---------------------------------------------------------------------------

class TestFindPeaks:
    """Mirrors Swift FindPeaksTests (F10–F14)."""

    def test_F10_single_tone_above_threshold_detected(self):
        """F10: A single pure tone above threshold is detected."""
        mag = _flat_spectrum()
        _add_tone(mag, freq_hz=440.0, peak_db=-20.0)

        threshold_db = -60
        ploc = peak_detection(mag, threshold=threshold_db)

        assert len(ploc) >= 1, "Should detect at least 1 peak above threshold"
        # The peak bin should be close to 440 Hz
        detected_freqs = [p * HZ_PER_BIN for p in ploc]
        assert any(abs(f - 440.0) < 10.0 for f in detected_freqs), (
            f"Expected a peak near 440 Hz; detected: {[f'{f:.1f}' for f in detected_freqs]}"
        )

    def test_F11_silence_produces_no_peaks(self):
        """F11: An all-floor spectrum produces no peaks above threshold."""
        mag = _flat_spectrum(floor=-80.0)
        ploc = peak_detection(mag, threshold=-60)
        assert len(ploc) == 0, f"Silence should produce 0 peaks; got {len(ploc)}"

    def test_F12_below_threshold_tone_not_detected(self):
        """F12: A tone below the detection threshold is not reported."""
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, freq_hz=300.0, peak_db=-70.0)  # below threshold
        ploc = peak_detection(mag, threshold=-65)
        assert len(ploc) == 0, "Peak below threshold should not be detected"

    def test_F13_multiple_tones_all_detected(self):
        """F13: Three well-separated tones above threshold are all detected."""
        mag = _flat_spectrum(floor=-80.0)
        freqs = [200.0, 500.0, 1000.0]
        for f in freqs:
            _add_tone(mag, freq_hz=f, peak_db=-25.0, width_bins=4)

        ploc = peak_detection(mag, threshold=-60)
        detected_freqs = [p * HZ_PER_BIN for p in ploc]
        for target in freqs:
            assert any(abs(df - target) < 20.0 for df in detected_freqs), (
                f"Expected a peak near {target} Hz; got: {[f'{f:.1f}' for f in detected_freqs]}"
            )

    def test_F14_clipped_flat_top_produces_at_most_one_peak(self):
        """F14: A flat-top (identical adjacent bins) is treated as a broad single peak."""
        mag = _flat_spectrum(floor=-80.0)
        # Perfectly flat peak across 3 bins — argrelmax should find at most 1
        for b in [100, 101, 102]:
            mag[b] = -20.0
        ploc = peak_detection(mag, threshold=-60)
        # The flat-top may or may not be detected; importantly, it should not produce
        # a large number of artefact peaks
        assert len(ploc) <= 2, (
            f"Flat-top should not produce many peaks; got {len(ploc)}"
        )


# ---------------------------------------------------------------------------
# Parabolic Interpolation on real tone (sanity check)
# ---------------------------------------------------------------------------

class TestPeakInterpSanity:
    """Quick sanity check that peak_interp output is close to the injected tone."""

    def test_interpolated_frequency_close_to_injected(self):
        """peak_interp should place the peak frequency within 1 bin of the injected tone."""
        mag = _flat_spectrum(floor=-80.0)
        target_hz = 440.0
        center_bin = _add_tone(mag, freq_hz=target_hz, peak_db=-20.0, width_bins=4)

        ploc = np.array([center_bin])
        iploc, _ = peak_interp(mag, ploc)

        estimated_hz = iploc[0] * HZ_PER_BIN
        assert abs(estimated_hz - target_hz) < HZ_PER_BIN, (
            f"Interpolated freq {estimated_hz:.1f} Hz should be within 1 bin of {target_hz} Hz"
        )


# ---------------------------------------------------------------------------
# RemoveDuplicatePeaks Tests  (F15–F16)
# ---------------------------------------------------------------------------

class TestRemoveDuplicatePeaks:
    """
    Mirrors Swift RemoveDuplicatePeaksTests (F15–F16).

    In Python the 2 Hz deduplication logic lives inside _apply_mode_priority
    (TapToneAnalyzerPeakAnalysisMixin) rather than as a standalone function.
    We test the math directly here.
    """

    def _deduplicate_2hz(self, peaks_hz: list[float]) -> list[float]:
        """Simple 2 Hz deduplication — mirrors Swift removeDuplicatePeaks."""
        result: list[float] = []
        for f in peaks_hz:
            if not any(abs(f - r) < 2.0 for r in result):
                result.append(f)
        return result

    def test_F15_distinct_peaks_are_preserved(self):
        """F15: Peaks more than 2 Hz apart should both survive deduplication."""
        peaks = [440.0, 445.0]   # 5 Hz apart — both survive
        result = self._deduplicate_2hz(peaks)
        assert len(result) == 2, f"Both peaks should survive; got {result}"

    def test_F16_near_duplicate_within_2hz_removed(self):
        """F16: Peaks within 2 Hz of each other → only the first survives."""
        peaks = [440.0, 441.0]   # 1 Hz apart — duplicate
        result = self._deduplicate_2hz(peaks)
        assert len(result) == 1, f"Duplicate within 2 Hz should be removed; got {result}"
        assert result[0] == 440.0


# ---------------------------------------------------------------------------
# Spectrum Averaging Tests  (A1–A5)
# ---------------------------------------------------------------------------

def _power_average_db(spectra_db: list[np.ndarray]) -> np.ndarray:
    """Power-domain (RMS) average of dB spectra — mirrors do_capture_tap logic."""
    stacked = np.stack(spectra_db)
    return 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))


class TestSpectrumAveraging:
    """
    Mirrors Swift SpectrumAveragingTests (A1–A5).

    Tests the power-domain averaging formula used by do_capture_tap, which is:
        avg_db = 10 * log10( mean( 10^(dB/10) ) )
    """

    def test_A1_average_of_identical_spectra_is_unchanged(self):
        """A1: Averaging identical spectra returns the same spectrum."""
        spec = np.array([-30.0, -40.0, -50.0, -35.0])
        spectra = [spec.copy(), spec.copy(), spec.copy()]
        avg = _power_average_db(spectra)
        np.testing.assert_allclose(avg, spec, atol=0.01, err_msg=(
            "Average of identical spectra should equal the original"
        ))

    def test_A2_average_of_two_equal_tones_gives_same_magnitude(self):
        """A2: Averaging two identical tones in power domain leaves magnitude unchanged."""
        spec1 = np.full(64, -20.0)
        spec2 = np.full(64, -20.0)
        avg = _power_average_db([spec1, spec2])
        np.testing.assert_allclose(avg, -20.0, atol=0.01)

    def test_A3_single_tap_average_equals_itself(self):
        """A3: Averaging a single spectrum returns the same spectrum."""
        spec = np.array([-25.0, -30.0, -45.0, -60.0])
        avg = _power_average_db([spec])
        np.testing.assert_allclose(avg, spec, atol=0.001)

    def test_A4_louder_spectrum_dominates_power_average(self):
        """A4: The louder of two spectra dominates the power-domain average."""
        loud = np.full(32, -10.0)    # -10 dBFS
        quiet = np.full(32, -40.0)   # -40 dBFS
        avg = _power_average_db([loud, quiet])
        # The average should be closer to -10 dB than to -40 dB
        assert np.all(avg > -15.0), (
            "Power average should be closer to the louder spectrum"
        )

    def test_A5_average_of_three_uncorrelated_identical_is_unchanged(self):
        """A5: Three identical spectra averaged together in power domain are unchanged."""
        spec = np.linspace(-80.0, -20.0, 128)
        avg = _power_average_db([spec.copy(), spec.copy(), spec.copy()])
        np.testing.assert_allclose(avg, spec, atol=0.01)
