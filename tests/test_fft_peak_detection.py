# @parity none
"""
FFT-layer peak detection — ``peak_detection`` in realtime_fft_analyzer_fft_processing.

Python-only. Swift and the web have no standalone equivalent: their bin-level local
maximum search is inlined in ``findPeaks``, so there is nothing to mirror and this
file is deliberately outside the ``test/peaks`` parity group.

MOVED HERE 2026-07-19 from test_peak_finding.py. Those cases were tagged
``@parity test/peaks`` and named F10–F14, implying they mirrored Swift's
``findPeaks`` tests — but they exercise a different function at a different layer,
so ``TapToneAnalyzer.find_peaks`` had no direct coverage on Python at all. That is
one of the two reasons the duplicate-peak defect survived here
(Development/PEAK-FINDING-DUPLICATE-PEAKS.md, section 5). The tests themselves are
sound and worth keeping; only their parity claim was wrong.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer_fft_processing import (  # noqa: E402
    peak_detection,
)

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


class TestFFTPeakDetection:
    """Bin-level local-maximum search used by the realtime FFT analyzer."""

    def test_single_tone_above_threshold_detected(self):
        mag = _flat_spectrum()
        _add_tone(mag, freq_hz=440.0, peak_db=-20.0)

        ploc = peak_detection(mag, threshold=-60)

        assert len(ploc) >= 1, "Should detect at least 1 peak above threshold"
        detected_freqs = [p * HZ_PER_BIN for p in ploc]
        assert any(abs(f - 440.0) < 10.0 for f in detected_freqs), (
            f"Expected a peak near 440 Hz; detected: {[f'{f:.1f}' for f in detected_freqs]}"
        )

    def test_silence_produces_no_peaks(self):
        mag = _flat_spectrum(floor=-80.0)
        ploc = peak_detection(mag, threshold=-60)
        assert len(ploc) == 0, f"Silence should produce 0 peaks; got {len(ploc)}"

    def test_below_threshold_tone_not_detected(self):
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, freq_hz=300.0, peak_db=-70.0)
        ploc = peak_detection(mag, threshold=-65)
        assert len(ploc) == 0, "Peak below threshold should not be detected"

    def test_multiple_tones_all_detected(self):
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

    def test_clipped_flat_top_produces_at_most_one_peak(self):
        mag = _flat_spectrum(floor=-80.0)
        for b in [100, 101, 102]:
            mag[b] = -20.0
        ploc = peak_detection(mag, threshold=-60)
        assert len(ploc) <= 2, f"Flat-top should not produce many peaks; got {len(ploc)}"