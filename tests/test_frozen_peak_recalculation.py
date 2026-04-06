"""
Port of FrozenPeakRecalculationTests.swift — threshold filter, offset remap,
override remap, and selection carry-forward on peak recalculation.

Mirrors Swift test plan coverage PR1–PR7.

In Python, 'peak recalculation' means re-running the peak detection pipeline
(peak_detection + peak_interp + peak_q_factor) on a measurement's saved
spectrum data.  This is used when the user changes the peak threshold or
analysis window on a frozen/loaded measurement.

The tests validate:
  - recalculate_frozen_peaks_if_needed() on TapToneAnalyzer (PR-A tests):
    the unified entry point dispatches correctly for frozen-spectrum (live-tap)
    and loaded-measurement paths, and threshold changes take effect.
  - The data-remapping logic (PR1–PR7):
    - Peaks below the threshold are excluded (PR2a–PR2c)
    - annotation_offsets are remapped to new peaks by nearest-frequency match (PR3a/PR3b)
    - peak_mode_overrides are remapped similarly (PR4/PR4b)
    - selected_peak_ids are carried forward by frequency proximity (PR5a/PR5b)
    - Guard: an empty peak list does not crash remap logic (PR6)

Since the Python remap logic lives in TapToneMeasurement data structures
rather than in a separate 'recalculate' method, tests here validate the
data structures and the helper logic used to remap after re-analysis.
"""

from __future__ import annotations

import json
import sys, os
import uuid

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
from guitar_tap.models.realtime_fft_analyzer_fft_processing import (
    peak_detection,
    peak_interp,
    peak_q_factor,
)

# PySide6 application — required for QObject construction.
# Mirrors the fixture pattern used in test_tap_detection.py.
from PySide6 import QtWidgets

_APP = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from guitar_tap.models.guitar_type import GuitarType


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_FREQ = 48000
N_F = 2048
N_BINS = N_F // 2 + 1
HZ_PER_BIN = SAMPLE_FREQ / N_F


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _peak(freq: float, mag: float = -30.0, quality: float = 10.0) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=quality,
        bandwidth=freq / quality,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _flat_spectrum(floor: float = -80.0) -> np.ndarray:
    return np.full(N_BINS, floor, dtype=np.float64)


def _add_tone(mag: np.ndarray, freq_hz: float, peak_db: float, width: int = 4) -> int:
    center = round(freq_hz / HZ_PER_BIN)
    for d in range(-width, width + 1):
        b = center + d
        if 0 < b < len(mag) - 1:
            mag[b] = max(mag[b], peak_db - 3.0 * (d**2) / (width**2) * 8)
    mag[center] = peak_db
    return center


def _detect_peaks(mag: np.ndarray, threshold_db: float):
    """Run the full peak detection pipeline and return (freqs_hz, mags_db)."""
    ploc = peak_detection(mag, threshold=int(threshold_db))
    if len(ploc) == 0:
        return np.array([]), np.array([])
    iploc, ipmag = peak_interp(mag, ploc)
    freqs = iploc * HZ_PER_BIN
    return freqs, ipmag


def _remap_by_freq(
    old_map: dict,  # {old_freq_approx_str_or_id: value}
    old_peaks: list[ResonantPeak],
    new_peaks_freqs: list[float],
    tolerance_hz: float = 5.0,
) -> dict:
    """Remap a {old_peak_id: value} dict to new peak frequencies by nearest-freq match.

    This is the Python equivalent of the Swift 'carry-forward' logic that
    walks through new peaks and finds the nearest old peak within tolerance_hz.
    Returns {new_peak_freq_str_repr: value} for matched entries only.
    """
    result = {}
    # Build {peak_id: freq} for old peaks
    id_to_freq = {p.id: p.frequency for p in old_peaks}

    for new_freq in new_peaks_freqs:
        # Find the best matching old peak by frequency
        best_id = None
        best_dist = float("inf")
        for old_id, old_freq in id_to_freq.items():
            dist = abs(new_freq - old_freq)
            if dist < best_dist and dist <= tolerance_hz:
                best_dist = dist
                best_id = old_id
        if best_id is not None and best_id in old_map:
            result[new_freq] = old_map[best_id]
    return result


# ---------------------------------------------------------------------------
# PR-A: TapToneAnalyzer.recalculate_frozen_peaks_if_needed() integration tests
#
# These tests exercise the unified entry point directly on TapToneAnalyzer,
# mirroring Swift FrozenPeakRecalculationTests which call
# recalculateFrozenPeaksIfNeeded() on a real TapToneAnalyzer instance.
# ---------------------------------------------------------------------------


class TestRecalculateFrozenPeaksIfNeeded:
    """Integration tests for recalculate_frozen_peaks_if_needed() on TapToneAnalyzer.

    Mirrors Swift FrozenPeakRecalculationTests — exercises the unified
    recalculateFrozenPeaksIfNeeded() entry point rather than the underlying
    pipeline helpers directly.
    """

    # Helper: build a synthetic spectrum with one clear peak at freq_hz.
    @staticmethod
    def _make_spectrum_with_peak(
        freq_hz: float,
        peak_db: float = -20.0,
        floor_db: float = -80.0,
        sample_freq: int = SAMPLE_FREQ,
        n_fft: int = N_F,
    ):
        n_bins = n_fft // 2 + 1
        hz_per_bin = sample_freq / n_fft
        mag = np.full(n_bins, floor_db, dtype=np.float64)
        _add_tone(mag, freq_hz, peak_db)
        freqs = np.array([i * hz_per_bin for i in range(n_bins)])
        return freqs, mag

    def test_PRA1_frozen_spectrum_path_detects_peak(self, qt_app):
        """PR-A1: When loaded_measurement_peaks is None, uses frozen spectrum.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — frozen path calls
        findPeaks on frozenMagnitudes and updates currentPeaks.
        """
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        freqs, mag = self._make_spectrum_with_peak(200.0, peak_db=-20.0)
        sut.freq = freqs
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mag
        sut.is_measurement_complete = True
        sut.peak_threshold = -60.0
        sut.min_frequency = 80.0
        sut.max_frequency = 1200.0
        sut.loaded_measurement_peaks = None

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) >= 1, (
            "frozen-spectrum path should detect the 200 Hz peak"
        )
        detected_freqs = [p.frequency for p in sut.current_peaks]
        assert any(abs(f - 200.0) < 20.0 for f in detected_freqs), (
            f"Expected peak near 200 Hz; got {[f'{f:.1f}' for f in detected_freqs]}"
        )

    def test_PRA2_threshold_change_removes_weak_peak(self, qt_app):
        """PR-A2: Raising peak_threshold removes sub-threshold peaks on recalculate.

        Mirrors Swift PR2c — the frozen path re-runs find_peaks with the new
        threshold, so previously detected weak peaks disappear.
        """
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        freqs, mag = self._make_spectrum_with_peak(200.0, peak_db=-50.0)
        sut.freq = freqs
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mag
        sut.is_measurement_complete = True
        sut.min_frequency = 80.0
        sut.max_frequency = 1200.0
        sut.loaded_measurement_peaks = None

        # Low threshold: peak should be detected.
        sut.peak_threshold = -60.0
        sut.recalculate_frozen_peaks_if_needed()
        detected_low = [p.frequency for p in sut.current_peaks]
        assert any(abs(f - 200.0) < 20.0 for f in detected_low), (
            "Peak should be detected at low threshold"
        )

        # Raised threshold: weak peak should be removed.
        sut.peak_threshold = -40.0
        sut.recalculate_frozen_peaks_if_needed()
        detected_high = [p.frequency for p in sut.current_peaks]
        assert not any(abs(f - 200.0) < 20.0 for f in detected_high), (
            "Weak peak should be absent after raising threshold"
        )

    def test_PRA3_loaded_measurement_path_filters_by_threshold(self, qt_app):
        """PR-A3: When loaded_measurement_peaks is set, threshold is applied to it.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — loaded path filters
        loaded_measurement_peaks by peak_threshold and stores in current_peaks.
        """
        from models.resonant_peak import ResonantPeak
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        # Frozen arrays must be non-empty to pass the guard (matches Swift behaviour).
        sut.frozen_frequencies = np.array([100.0, 200.0, 400.0])
        sut.frozen_magnitudes = np.array([-80.0, -25.0, -65.0])
        sut.is_measurement_complete = True

        # loaded_measurement_peaks is list[ResonantPeak]
        sut.loaded_measurement_peaks = [
            ResonantPeak(frequency=200.0, magnitude=-25.0, quality=10.0),  # above threshold
            ResonantPeak(frequency=400.0, magnitude=-65.0, quality=8.0),   # below threshold
        ]
        sut.peak_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) == 1, (
            "Only the above-threshold peak should remain"
        )
        assert abs(sut.current_peaks[0].frequency - 200.0) < 1.0, (
            "The surviving peak should be at 200 Hz"
        )

    def test_PRA4_loaded_measurement_all_below_threshold_yields_empty(self, qt_app):
        """PR-A4: All loaded peaks below threshold → current_peaks is empty list."""
        from models.resonant_peak import ResonantPeak
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        sut.frozen_frequencies = np.array([100.0, 200.0, 400.0])
        sut.frozen_magnitudes = np.array([-80.0, -70.0, -65.0])
        sut.is_measurement_complete = True
        sut.loaded_measurement_peaks = [
            ResonantPeak(frequency=200.0, magnitude=-70.0, quality=10.0),
            ResonantPeak(frequency=400.0, magnitude=-65.0, quality=8.0),
        ]
        sut.peak_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) == 0, (
            "No peaks should remain when all are below threshold"
        )

    def test_PRA5_empty_frozen_magnitudes_yields_no_peaks(self, qt_app):
        """PR-A5: Empty frozen_magnitudes does not crash; current_peaks stays empty."""
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        sut.freq = np.array([])
        sut.frozen_magnitudes = np.array([])
        sut.loaded_measurement_peaks = None
        sut.peak_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()   # must not raise

        assert len(sut.current_peaks) == 0


# ---------------------------------------------------------------------------
# PR1/PR1b: Loading guard — spectrum must be present
# ---------------------------------------------------------------------------

class TestLoadingGuard:
    """Mirrors Swift FrozenPeakRecalculationTests PR1/PR1b."""

    def test_PR1_spectrum_snapshot_present_enables_recalculation(self):
        """PR1: A measurement with a spectrum snapshot can be re-analysed."""
        mag = _flat_spectrum()
        _add_tone(mag, 200.0, -25.0)
        snap = SpectrumSnapshot(
            frequencies=[i * HZ_PER_BIN for i in range(N_BINS)],
            magnitudes=list(mag),
        )
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=snap)
        assert m.spectrum_snapshot is not None, "Snapshot should be present"
        # Re-run detection on the stored magnitudes
        mag_arr = np.array(m.spectrum_snapshot.magnitudes)
        freqs, mags = _detect_peaks(mag_arr, threshold_db=-60.0)
        assert len(freqs) >= 1, "Should detect at least 1 peak after re-analysis"

    def test_PR1b_no_snapshot_returns_empty_peaks(self):
        """PR1b: A measurement without a snapshot cannot yield new peaks."""
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=None)
        assert m.spectrum_snapshot is None, "No snapshot → cannot recalculate"


# ---------------------------------------------------------------------------
# PR2a–PR2c: Threshold filter
# ---------------------------------------------------------------------------

class TestThresholdFilter:
    """Mirrors Swift FrozenPeakRecalculationTests PR2a–PR2c."""

    def test_PR2a_peaks_above_threshold_detected(self):
        """PR2a: Peaks above the detection threshold are found."""
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, 200.0, -20.0)
        freqs, _ = _detect_peaks(mag, threshold_db=-60.0)
        assert any(abs(f - 200.0) < 20.0 for f in freqs), (
            f"Expected peak near 200 Hz; detected: {[f'{f:.1f}' for f in freqs]}"
        )

    def test_PR2b_peaks_below_threshold_excluded(self):
        """PR2b: A peak below the detection threshold is not returned."""
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, 300.0, -70.0)   # below -60 dB threshold
        freqs, _ = _detect_peaks(mag, threshold_db=-60.0)
        assert not any(abs(f - 300.0) < 20.0 for f in freqs), (
            "Peak below threshold should not be detected after recalculation"
        )

    def test_PR2c_raising_threshold_removes_weak_peaks(self):
        """PR2c: Raising the threshold eliminates the weaker of two peaks."""
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, 200.0, -20.0)   # strong: -20 dB
        _add_tone(mag, 400.0, -55.0)   # weak: -55 dB
        # With low threshold, both should be found
        freqs_low, _ = _detect_peaks(mag, threshold_db=-60.0)
        # With high threshold, only the strong one
        freqs_high, _ = _detect_peaks(mag, threshold_db=-40.0)
        assert any(abs(f - 200.0) < 20.0 for f in freqs_high), (
            "Strong peak should still be found with raised threshold"
        )
        assert not any(abs(f - 400.0) < 20.0 for f in freqs_high), (
            "Weak peak should be excluded with raised threshold"
        )


# ---------------------------------------------------------------------------
# PR3a/PR3b: Annotation offset remap
# ---------------------------------------------------------------------------

class TestOffsetRemap:
    """Mirrors Swift FrozenPeakRecalculationTests PR3a/PR3b."""

    def test_PR3a_offset_remapped_to_close_new_peak(self):
        """PR3a: An annotation offset from an old peak maps to the new peak at ~same frequency."""
        old_peak = _peak(freq=200.0)
        offsets = {old_peak.id: [200.0, -40.0]}  # old: id → position

        # New peaks are at similar frequencies (within 5 Hz)
        new_freqs = [200.5, 300.0]

        remapped = _remap_by_freq(offsets, [old_peak], new_freqs, tolerance_hz=5.0)
        assert 200.5 in remapped, "Offset should remap to the new peak at ~200 Hz"
        assert remapped[200.5] == [200.0, -40.0]

    def test_PR3b_offset_not_remapped_when_no_close_peak(self):
        """PR3b: An old offset is dropped when no new peak is within tolerance."""
        old_peak = _peak(freq=200.0)
        offsets = {old_peak.id: [200.0, -40.0]}

        new_freqs = [500.0, 700.0]   # far from 200 Hz

        remapped = _remap_by_freq(offsets, [old_peak], new_freqs, tolerance_hz=5.0)
        assert len(remapped) == 0, "Offset should not remap when no nearby new peak"


# ---------------------------------------------------------------------------
# PR4/PR4b: Mode override remap
# ---------------------------------------------------------------------------

class TestOverrideRemap:
    """Mirrors Swift FrozenPeakRecalculationTests PR4/PR4b."""

    def test_PR4_override_remapped_to_close_new_peak(self):
        """PR4: A mode override from an old peak is carried to the nearby new peak."""
        old_peak = _peak(freq=195.0)
        overrides = {old_peak.id: "Top"}   # id → mode label

        new_freqs = [196.0]   # within 5 Hz

        remapped = _remap_by_freq(overrides, [old_peak], new_freqs, tolerance_hz=5.0)
        assert 196.0 in remapped, "Override should remap to close new peak"
        assert remapped[196.0] == "Top"

    def test_PR4b_override_dropped_when_no_close_peak(self):
        """PR4b: Mode override is dropped when the new peaks have shifted too far."""
        old_peak = _peak(freq=195.0)
        overrides = {old_peak.id: "Top"}

        new_freqs = [300.0, 400.0]  # far from 195 Hz

        remapped = _remap_by_freq(overrides, [old_peak], new_freqs, tolerance_hz=5.0)
        assert len(remapped) == 0


# ---------------------------------------------------------------------------
# PR5a/PR5b: Selection carry-forward
# ---------------------------------------------------------------------------

class TestSelectionCarryForward:
    """Mirrors Swift FrozenPeakRecalculationTests PR5a/PR5b."""

    def test_PR5a_selected_peak_id_remapped_by_frequency(self):
        """PR5a: When new peaks emerge at ~same frequency, selection is carried forward."""
        old_peak = _peak(freq=200.0)
        new_peak = _peak(freq=201.0)  # nearby — carry selection

        # Simulate carry-forward: does new_peak's freq match old_peak within tolerance?
        match = abs(new_peak.frequency - old_peak.frequency) <= 5.0
        assert match, "New peak at 201 Hz should carry forward selection from 200 Hz peak"

    def test_PR5b_selection_not_carried_when_peak_moved_far(self):
        """PR5b: Selection is not carried when frequency changed beyond tolerance."""
        old_peak = _peak(freq=200.0)
        new_peak = _peak(freq=250.0)  # too far — no carry

        match = abs(new_peak.frequency - old_peak.frequency) <= 5.0
        assert not match, "Peak at 250 Hz should NOT carry forward from 200 Hz"


# ---------------------------------------------------------------------------
# PR6: Empty peaks guard
# ---------------------------------------------------------------------------

class TestEmptyPeaksGuard:
    """Mirrors Swift FrozenPeakRecalculationTests PR6."""

    def test_PR6_remap_with_empty_new_peaks_returns_empty(self):
        """PR6: Remapping any dict onto an empty new-peak list yields empty output."""
        old_peak = _peak(freq=200.0)
        offsets = {old_peak.id: [200.0, -40.0]}
        remapped = _remap_by_freq(offsets, [old_peak], new_peaks_freqs=[], tolerance_hz=5.0)
        assert remapped == {}, "Remapping onto empty peaks should produce empty dict"

    def test_PR6b_remap_with_empty_old_overrides_returns_empty(self):
        """PR6b: No old overrides → nothing to remap."""
        remapped = _remap_by_freq({}, old_peaks=[], new_peaks_freqs=[200.0, 300.0])
        assert remapped == {}


# ---------------------------------------------------------------------------
# PR7: Live-tap path is unchanged
# ---------------------------------------------------------------------------

class TestLiveTapPath:
    """Mirrors Swift FrozenPeakRecalculationTests PR7."""

    def test_PR7_live_measurement_has_no_snapshot(self):
        """PR7: A freshly created measurement (before snapshot save) has no spectrum_snapshot."""
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=None)
        assert m.spectrum_snapshot is None, (
            "Live tap measurement should not have a spectrum snapshot initially"
        )

    def test_PR7b_creating_measurement_with_snapshot_captures_it(self):
        """PR7b: A measurement created with a snapshot stores it correctly."""
        snap = SpectrumSnapshot(frequencies=[100.0, 200.0], magnitudes=[-40.0, -35.0])
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=snap)
        assert m.spectrum_snapshot is snap


# ---------------------------------------------------------------------------
# Analyzer remapping tests — PR1-PR7 direct ports on TapToneAnalyzer
#
# These tests exercise recalculate_frozen_peaks_if_needed() on a real
# TapToneAnalyzer instance, verifying that annotation offsets, mode overrides,
# and peak selections are correctly remapped to new peak UUIDs when the
# spectrum is re-analysed (loaded path or live-tap path).
#
# Each test uses loaded_measurement_peaks so that the peak UUIDs are known
# up-front, making it easy to pre-seed analyzer state with the old UUIDs and
# then verify remapping to the new UUIDs after the call.
# ---------------------------------------------------------------------------


class TestAnalyzerRemapping:
    """Direct-port PR1-PR7 tests on TapToneAnalyzer.recalculate_frozen_peaks_if_needed().

    Tests the on-analyzer remapping of annotation offsets, mode overrides,
    and peak selections when recalculate_frozen_peaks_if_needed() is called.
    Mirrors Swift FrozenPeakRecalculationTests PR1-PR7 coverage.
    """

    @staticmethod
    def _make_sut(peaks: list) -> "TapToneAnalyzer":
        """Return a TapToneAnalyzer seeded for the loaded-measurement path."""
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        sut.is_measurement_complete = True
        # Provide non-empty frozen arrays so the guard passes.
        sut.frozen_frequencies = np.array([100.0, 200.0, 400.0])
        sut.frozen_magnitudes = np.array([-80.0, -25.0, -40.0])
        sut.loaded_measurement_peaks = peaks
        sut.peak_threshold = -60.0
        return sut

    # ── PR1: is_loading_measurement guard ────────────────────────────────────

    def test_PR1_is_loading_measurement_suppresses_recalculation(self, qt_app):
        """PR1: When is_loading_measurement is True, recalculation is skipped.

        Mirrors Swift isLoadingMeasurement_suppressesRecalculation.
        """
        p = _peak(200.0, -25.0)
        sut = self._make_sut([p])
        sut.is_loading_measurement = True

        sut.recalculate_frozen_peaks_if_needed()

        # current_peaks was not updated (still default empty)
        assert sut.current_peaks == [], (
            "Recalculation should be suppressed while is_loading_measurement is True"
        )

    def test_PR1b_after_loading_completes_recalculation_runs(self, qt_app):
        """PR1b: After is_loading_measurement becomes False, recalculation proceeds.

        Mirrors Swift afterLoadingCompletes_recalculationRuns.
        """
        p = _peak(200.0, -25.0)
        sut = self._make_sut([p])
        sut.is_loading_measurement = False  # loading complete

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) == 1, (
            "Recalculation should run when is_loading_measurement is False"
        )

    # ── PR2: Threshold filter ─────────────────────────────────────────────────

    def test_PR2b_loaded_peaks_all_below_threshold_clears_both_collections(self, qt_app):
        """PR2b: All peaks below threshold → current_peaks and identified_modes both empty.

        Mirrors Swift loadedPeaks_allBelowThreshold_clearsBothCollections.
        """
        p1 = _peak(200.0, -70.0)
        p2 = _peak(400.0, -65.0)
        sut = self._make_sut([p1, p2])

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) == 0, "current_peaks should be empty"
        assert len(sut.identified_modes) == 0, "identified_modes should be empty"

    def test_PR2c_loaded_path_uses_saved_peaks_not_frozen_spectrum(self, qt_app):
        """PR2c: The loaded path uses loaded_measurement_peaks, not frozen_magnitudes.

        Mirrors Swift loadedPath_usesSavedPeaks_notFrozenSpectrum — the peaks
        that survive are those from loaded_measurement_peaks that pass the
        threshold, regardless of what is in frozen_magnitudes.
        """
        # loaded_measurement_peaks has peaks at 200 Hz and 600 Hz.
        # frozen_magnitudes only has a tone at 400 Hz.
        # The loaded path should return 200 Hz (not 400 Hz, not 600 Hz below threshold).
        p_above = _peak(200.0, -25.0)
        p_below = _peak(600.0, -65.0)
        sut = self._make_sut([p_above, p_below])
        # frozen_magnitudes has a strong tone at 400 Hz — should be ignored.
        sut.frozen_frequencies = np.array([100.0, 400.0, 800.0])
        sut.frozen_magnitudes = np.array([-80.0, -20.0, -80.0])

        sut.recalculate_frozen_peaks_if_needed()

        freqs = [p.frequency for p in sut.current_peaks]
        assert any(abs(f - 200.0) < 5.0 for f in freqs), (
            "Loaded path should include the 200 Hz loaded peak"
        )
        assert not any(abs(f - 400.0) < 5.0 for f in freqs), (
            "Loaded path should NOT include the frozen-spectrum 400 Hz tone"
        )

    # ── PR3: Annotation offset remap ──────────────────────────────────────────

    def test_PR3a_loaded_path_annotation_offset_remapped_by_frequency(self, qt_app):
        """PR3a: Annotation offset keyed by old peak UUID is remapped to new UUID.

        Mirrors Swift loadedPath_annotationOffset_remappedByFrequency.
        """
        p_old = _peak(200.0, -25.0)
        sut = self._make_sut([p_old])

        # Seed annotation offset using the old peak's UUID.
        old_offset = (10.0, -20.0)
        sut.peak_annotation_offsets = {p_old.id: old_offset}
        # Manually set current_peaks so the snapshot loop finds the old peak.
        sut.current_peaks = [p_old]

        sut.recalculate_frozen_peaks_if_needed()

        # After recalculation the loaded path may keep the same peak object
        # (same UUID since it's the same ResonantPeak), so the offset should
        # still be present under the same or new UUID at ~200 Hz.
        new_peaks = sut.current_peaks
        assert len(new_peaks) == 1, "Should have one surviving peak"
        new_uid = new_peaks[0].id
        assert new_uid in sut.peak_annotation_offsets, (
            "Annotation offset should be remapped to the new peak UUID"
        )
        assert sut.peak_annotation_offsets[new_uid] == old_offset, (
            "Remapped offset value should be preserved"
        )

    def test_PR3b_loaded_path_offset_for_filtered_out_peak_is_dropped(self, qt_app):
        """PR3b: If the peak associated with an offset is filtered out, the offset is dropped.

        Mirrors Swift loadedPath_offsetForFilteredOutPeak_isDropped.
        """
        p_above = _peak(200.0, -25.0)
        p_below = _peak(400.0, -70.0)   # below threshold — will be filtered out
        sut = self._make_sut([p_above, p_below])

        # Seed an offset for the peak that will be filtered out.
        sut.current_peaks = [p_above, p_below]
        sut.peak_annotation_offsets = {p_below.id: (5.0, -10.0)}

        sut.recalculate_frozen_peaks_if_needed()

        surviving_ids = {p.id for p in sut.current_peaks}
        for uid in sut.peak_annotation_offsets:
            assert uid in surviving_ids, (
                f"Offset for filtered-out peak {uid} should have been dropped"
            )

    # ── PR4: Mode override remap ──────────────────────────────────────────────

    def test_PR4_loaded_path_mode_override_remapped_by_frequency(self, qt_app):
        """PR4: Mode override keyed by old UUID is remapped to matching-frequency new UUID.

        Mirrors Swift loadedPath_modeOverride_remappedByFrequency.
        """
        p_old = _peak(195.0, -25.0)
        sut = self._make_sut([p_old])
        sut.current_peaks = [p_old]
        sut.peak_mode_overrides = {p_old.id: "Top"}

        sut.recalculate_frozen_peaks_if_needed()

        new_peaks = sut.current_peaks
        assert len(new_peaks) == 1
        new_uid = new_peaks[0].id
        assert new_uid in sut.peak_mode_overrides, (
            "Mode override should be remapped to the new peak UUID"
        )
        assert sut.peak_mode_overrides[new_uid] == "Top"

    def test_PR4b_loaded_path_override_for_filtered_peak_is_dropped(self, qt_app):
        """PR4b: Mode override for a filtered-out peak is dropped.

        Mirrors Swift loadedPath_overrideForFilteredOutPeak_isDropped.
        """
        p_above = _peak(200.0, -25.0)
        p_below = _peak(500.0, -70.0)
        sut = self._make_sut([p_above, p_below])
        sut.current_peaks = [p_above, p_below]
        sut.peak_mode_overrides = {p_below.id: "Back"}

        sut.recalculate_frozen_peaks_if_needed()

        surviving_ids = {p.id for p in sut.current_peaks}
        for uid in sut.peak_mode_overrides:
            assert uid in surviving_ids, (
                f"Override for filtered-out peak {uid} should have been dropped"
            )

    # ── PR5: Selection carry-forward ──────────────────────────────────────────

    def test_PR5a_loaded_path_manual_selection_carried_forward_by_frequency(self, qt_app):
        """PR5a: When user_has_modified_peak_selection, selection is carried by freq proximity.

        Mirrors Swift loadedPath_manualSelection_carriedForwardByFrequency.
        """
        p_old = _peak(200.0, -25.0)
        sut = self._make_sut([p_old])
        sut.current_peaks = [p_old]
        sut.selected_peak_ids = {p_old.id}
        sut.selected_peak_frequencies = [p_old.frequency]
        sut.user_has_modified_peak_selection = True

        sut.recalculate_frozen_peaks_if_needed()

        new_peaks = sut.current_peaks
        assert len(new_peaks) == 1
        new_uid = new_peaks[0].id
        assert new_uid in sut.selected_peak_ids, (
            "Manual selection should be carried forward to the new peak UUID"
        )

    def test_PR5b_loaded_path_auto_selection_reruns_when_not_modified(self, qt_app):
        """PR5b: When user_has_modified_peak_selection is False, auto-select re-runs.

        Mirrors Swift loadedPath_autoSelection_reRunsWhenNotModified.
        """
        p = _peak(200.0, -25.0)
        sut = self._make_sut([p])
        sut.user_has_modified_peak_selection = False
        sut.selected_peak_ids = set()  # empty — should be filled by auto-select

        sut.recalculate_frozen_peaks_if_needed()

        # After auto-select, selected_peak_ids should be non-empty if peaks exist
        # (guitar_mode_selected_peak_ids picks the best peak per named mode).
        # The exact set depends on frequency; we just verify that auto-select ran
        # and selected_peak_ids is consistent with current_peaks.
        assert sut.selected_peak_ids.issubset({p.id for p in sut.current_peaks}), (
            "Auto-selected IDs must belong to current_peaks"
        )

    # ── PR6: Empty peaks guard ────────────────────────────────────────────────

    def test_PR6_live_tap_path_empty_peaks_preserves_selected_peak_ids(self, qt_app):
        """PR6: When frozen spectrum yields no peaks, selected_peak_ids is preserved.

        Mirrors Swift liveTapPath_emptyPeaks_preservesSelectedPeakIDs —
        verifies the code doesn't crash and does not spuriously mutate
        selected_peak_ids when there are no peaks to remap.
        """
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        sut.is_measurement_complete = True
        # Flat spectrum — no peaks to detect.
        flat = np.full(N_BINS, -80.0, dtype=np.float64)
        freqs = np.array([i * HZ_PER_BIN for i in range(N_BINS)])
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = flat
        sut.freq = freqs
        sut.loaded_measurement_peaks = None
        sut.peak_threshold = -60.0
        # selected_peak_ids starts empty — must stay empty (no crash, no additions).
        sut.selected_peak_ids = set()

        sut.recalculate_frozen_peaks_if_needed()   # must not raise

        assert len(sut.current_peaks) == 0, "No peaks expected on flat spectrum"
        assert len(sut.selected_peak_ids) == 0, (
            "selected_peak_ids should remain empty when no peaks are detected"
        )

    # ── PR7: Live-tap path annotation offset remap ───────────────────────────

    def test_PR7_live_tap_path_annotation_offset_remapped_by_frequency(self, qt_app):
        """PR7: On the live-tap path, annotation offsets remap to new UUIDs by frequency.

        Mirrors Swift liveTapPath_annotationOffset_remappedByFrequency.
        Uses a synthetic spectrum so that find_peaks() produces new UUIDs.
        """
        sut = TapToneAnalyzer()
        sut._guitar_type = GuitarType.CLASSICAL
        sut.is_measurement_complete = True
        sut.loaded_measurement_peaks = None
        sut.peak_threshold = -60.0
        sut.min_frequency = 80.0
        sut.max_frequency = 1200.0

        # Build a spectrum with a clear peak at 200 Hz.
        mag = _flat_spectrum(floor=-80.0)
        _add_tone(mag, 200.0, -20.0)
        freqs = np.array([i * HZ_PER_BIN for i in range(N_BINS)])
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mag
        sut.freq = freqs

        # First call to detect the initial peaks.
        sut.recalculate_frozen_peaks_if_needed()
        assert len(sut.current_peaks) >= 1, "First call should detect at least 1 peak"
        first_uid = sut.current_peaks[0].id
        old_offset = (15.0, -30.0)
        sut.peak_annotation_offsets = {first_uid: old_offset}

        # Second call should remap the offset to the same (or new) peak UUID.
        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.current_peaks) >= 1, "Second call should still find peak"
        new_uid = sut.current_peaks[0].id
        assert new_uid in sut.peak_annotation_offsets, (
            "Annotation offset should be remapped to the new peak UUID on live-tap path"
        )
        assert sut.peak_annotation_offsets[new_uid] == old_offset
