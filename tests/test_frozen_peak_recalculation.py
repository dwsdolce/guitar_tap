# @parity test/frozen-peak-recalc
"""Port of FrozenPeakRecalculationTests.swift — the frozen/loaded peak recalculation path.

Mirrors Swift ``FrozenPeakRecalculationTests``; the shared behaviour list is
``docs/FROZEN-RECALC-TEST-PARITY.md`` in the hub (one id per behaviour; the range moves as the
table grows, so do not cite a bound here).

`recalculate_frozen_peaks_if_needed()` is the single entry point that refreshes the peak
display after a threshold or analysis-range change. It has two branches:

  - **loaded** — `loaded_measurement_peaks` is set. The saved peaks are authoritative and
    are NEVER re-derived from the frozen spectrum; Peak Min only projects them for display.
  - **live/frozen** — detection re-runs over the frozen spectrum at the -100 dB floor.

Either way `_apply_frozen_peak_state()` carries per-peak state (annotation offsets, mode
overrides, selection) onto the new peak ids by ±5 Hz frequency proximity.

Every test here must reach that production code. An earlier version of this file carried
`_remap_by_freq`, a test-local reimplementation of the carry-forward logic, and this
docstring claimed the remap "lives in TapToneMeasurement data structures rather than in a
separate recalculate method" — which is false, and which let eight tests pass while
measuring nothing. Both are gone. A helper that reimplements the behaviour under test is
not a fixture; it is a second implementation, and a test against it proves nothing.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# PySide6 application — required for QObject construction.
# Mirrors the fixture pattern used in test_tap_detection.py.
from PySide6 import QtWidgets

from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

_APP = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

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


def _gaussian_spectrum(bumps, lo: float = 50.0, hi: float = 500.0, floor: float = -100.0):
    """A synthetic spectrum with a Gaussian bump at each requested frequency, on a -100 dB floor.

    The flat spectrum installed by the minimal freeze helpers makes find_peaks detect nothing, so any
    test that drives the live/frozen recalc through it passes vacuously -- a trap this suite has
    fallen into before. This fixture gives real detection something to work on.

    Mirrors Swift ``gaussianSpectrum``.
    """
    sigma = 3.0
    freqs: list = []
    mags: list = []
    f = lo
    while f <= hi:
        m = floor
        for bf, bmag in bumps:
            d = f - bf
            m = max(m, floor + (bmag - floor) * float(np.exp(-(d * d) / (2 * sigma * sigma))))
        freqs.append(f)
        mags.append(m)
        f += 1.0
    return np.array(freqs), np.array(mags)


def _freeze_on_real_spectrum(sut, bumps) -> None:
    """Freeze the SUT on a real (Gaussian) spectrum so the live/frozen recalc branch actually
    detects. Mirrors Swift ``freezeOnRealSpectrum``.
    """
    freqs, mags = _gaussian_spectrum(bumps)
    sut.min_frequency = 50.0
    sut.max_frequency = 500.0
    sut.is_measurement_complete = True
    sut.frozen_frequencies = freqs
    sut.frozen_magnitudes = mags
    sut.all_peaks = sut.find_peaks(mags, freqs, peak_min_override=sut.PEAK_DETECTION_FLOOR)




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

    def test_PR01_frozen_spectrum_path_detects_peak(self, qt_app):
        """PR-A1: When loaded_measurement_peaks is None, uses frozen spectrum.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — frozen path calls
        findPeaks on frozenMagnitudes and updates currentPeaks.
        """
        sut = TapToneAnalyzer()
        freqs, mag = self._make_spectrum_with_peak(200.0, peak_db=-20.0)
        sut.freq = freqs
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mag
        sut.is_measurement_complete = True
        sut.peak_min_threshold = -60.0
        sut.min_frequency = 80.0
        sut.max_frequency = 1200.0
        sut.loaded_measurement_peaks = None

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.peaks_above_peak_min) >= 1, (
            "frozen-spectrum path should detect the 200 Hz peak"
        )
        detected_freqs = [p.frequency for p in sut.peaks_above_peak_min]
        assert any(abs(f - 200.0) < 20.0 for f in detected_freqs), (
            f"Expected peak near 200 Hz; got {[f'{f:.1f}' for f in detected_freqs]}"
        )

    def test_PR02_threshold_change_removes_weak_peak(self, qt_app):
        """PR-A2: Raising peak_threshold removes sub-threshold peaks on recalculate.

        Mirrors Swift PR2c — the frozen path re-runs find_peaks with the new
        threshold, so previously detected weak peaks disappear.
        """
        sut = TapToneAnalyzer()
        freqs, mag = self._make_spectrum_with_peak(200.0, peak_db=-50.0)
        sut.freq = freqs
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mag
        sut.is_measurement_complete = True
        sut.min_frequency = 80.0
        sut.max_frequency = 1200.0
        sut.loaded_measurement_peaks = None

        # Low threshold: peak should be detected.
        sut.peak_min_threshold = -60.0
        sut.recalculate_frozen_peaks_if_needed()
        detected_low = [p.frequency for p in sut.peaks_above_peak_min]
        assert any(abs(f - 200.0) < 20.0 for f in detected_low), (
            "Peak should be detected at low threshold"
        )

        # Raised threshold: weak peak should be removed.
        sut.peak_min_threshold = -40.0
        sut.recalculate_frozen_peaks_if_needed()
        detected_high = [p.frequency for p in sut.peaks_above_peak_min]
        assert not any(abs(f - 200.0) < 20.0 for f in detected_high), (
            "Weak peak should be absent after raising threshold"
        )

    def test_PR03_loaded_path_peak_min_projects_and_never_shrinks_the_durable_set(self, qt_app):
        """PR03: the loaded path applies Peak Min to the PROJECTION and never to the durable set.

        Asserts BOTH surfaces deliberately. This test asserted only `peaks_above_peak_min` and was
        named "filters by threshold", which read as contradicting web's PR-A3 ("keeps the FULL
        authoritative set"); both were correct and the name was the whole disagreement. The durable
        half is the assertion with teeth: assigning `all_peaks` a filtered view would shrink it as
        Peak Min rises, and the save path writes `all_peaks` — so the shrunken set gets persisted.

        Mirrors Swift loadedMeasurement_peakMinProjects_andNeverShrinksTheDurableSet.
        """
        from guitar_tap.models.resonant_peak import ResonantPeak
        sut = TapToneAnalyzer()
        # Frozen arrays must be non-empty to pass the guard (matches Swift behaviour).
        sut.frozen_frequencies = np.array([100.0, 200.0, 400.0])
        sut.frozen_magnitudes = np.array([-80.0, -25.0, -65.0])
        sut.is_measurement_complete = True

        # loaded_measurement_peaks is list[ResonantPeak]
        sut.loaded_measurement_peaks = [
            ResonantPeak(frequency=200.0, magnitude=-25.0, quality=10.0),  # above threshold
            ResonantPeak(frequency=400.0, magnitude=-65.0, quality=8.0),   # below threshold
        ]
        sut.peak_min_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()

        assert sorted(round(p.frequency) for p in sut.all_peaks) == [200, 400], (
            "the durable set keeps every saved peak — it is what gets saved again"
        )
        assert len(sut.peaks_above_peak_min) == 1, (
            "the projection shows only the above-Peak-Min peak"
        )
        assert abs(sut.peaks_above_peak_min[0].frequency - 200.0) < 1.0, (
            "The surviving peak should be at 200 Hz"
        )

    def test_PR04_loaded_all_below_threshold_clears_display_keeps_durable_set(self, qt_app):
        """PR-A4 (Phase 1/2 model): all loaded peaks below Peak Min → the DISPLAY projection
        (peaks_above_peak_min) empties, but the DURABLE set (all_peaks) and classification survive.
        A display filter must never shrink the durable set. Mirrors Swift
        loadedPeaks_allBelowThreshold_clearsDisplayButKeepsClassification.
        """
        from guitar_tap.models.resonant_peak import ResonantPeak
        sut = TapToneAnalyzer()
        sut.frozen_frequencies = np.array([100.0, 200.0, 400.0])
        sut.frozen_magnitudes = np.array([-80.0, -70.0, -65.0])
        sut.is_measurement_complete = True
        sut.loaded_measurement_peaks = [
            ResonantPeak(frequency=200.0, magnitude=-70.0, quality=10.0),
            ResonantPeak(frequency=400.0, magnitude=-65.0, quality=8.0),
        ]
        sut.peak_min_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.peaks_above_peak_min) == 0, (
            "the display projection empties when all peaks are below Peak Min"
        )
        assert len(sut.all_peaks) == 2, (
            "the durable set survives — a display filter must never shrink all_peaks"
        )

    def test_PR05_empty_frozen_magnitudes_yields_no_peaks(self, qt_app):
        """PR-A5: Empty frozen_magnitudes does not crash; peaks_above_peak_min stays empty."""
        sut = TapToneAnalyzer()
        sut.freq = np.array([])
        sut.frozen_magnitudes = np.array([])
        sut.loaded_measurement_peaks = None
        sut.peak_min_threshold = -60.0

        sut.recalculate_frozen_peaks_if_needed()   # must not raise

        assert len(sut.peaks_above_peak_min) == 0


# ---------------------------------------------------------------------------
# PR8: can_reanalyze — when the Re-analyze button is offered
# ---------------------------------------------------------------------------
#
# Re-analyze is a RESET, not a dirty-flag indicator: it is offered whenever it COULD do
# something, not only when we can prove it WILL. What can leave the displayed analysis
# differing from a clean re-derivation is open-ended (peaks came from a file; mode
# assignments carried forward across Peak Min moves instead of being re-claimed; the
# analysis range moved; selections were hand-edited), and the two failure modes are not
# symmetric — a wrongly-DISABLED button is a dead end, a wrongly-ENABLED one costs a
# pointless click. So: any complete guitar measurement with a frozen spectrum; never
# material.
#
# This replaces `loaded_measurement_peaks is not None`, a proxy for "the peaks are stale"
# that was wrong in both directions — it disabled itself after one press, and never lit up
# for a live capture whose mode assignments had drifted.
#
# Mirrors Swift FrozenPeakRecalculation_CanReanalyzeTests.

class TestPR8CanReanalyze:
    """PR8: can_reanalyze — the Re-analyze button's enabled state."""

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        """The measurement type is global app state — put it back after each test."""
        saved = TapDisplaySettings.measurement_type()
        yield
        TapDisplaySettings.set_measurement_type(saved)

    def _frozen(self, mtype: MeasurementType) -> TapToneAnalyzer:
        TapDisplaySettings.set_measurement_type(mtype)
        sut = TapToneAnalyzer()
        sut.frozen_frequencies = np.array([i * HZ_PER_BIN for i in range(N_BINS)])
        sut.frozen_magnitudes = _flat_spectrum()
        sut.is_measurement_complete = True
        return sut

    def test_PR33_live_frozen_capture_can_reanalyze(self, qt_app):
        """A never-loaded frozen capture CAN be re-analyzed.

        It is the only route back to a clean mode classification once the assignments
        have drifted across Peak Min moves.
        """
        sut = self._frozen(MeasurementType.CLASSICAL)
        sut.peaks_above_peak_min = [_peak(200.0)]
        sut.loaded_measurement_peaks = None      # never loaded — a fresh capture

        assert sut.can_reanalyze is True

    def test_PR34_loaded_measurement_can_reanalyze(self, qt_app):
        """A loaded measurement can be re-analyzed — its saved peaks were never derived here."""
        sut = self._frozen(MeasurementType.CLASSICAL)
        saved_peaks = [_peak(200.0)]
        sut.peaks_above_peak_min = saved_peaks
        sut.loaded_measurement_peaks = saved_peaks

        assert sut.can_reanalyze is True

    def test_PR35_reanalyze_is_not_a_one_shot(self, qt_app):
        """THE ONE-SHOT REGRESSION.

        reanalyze_peaks() clears loaded_measurement_peaks, which used to be the button's
        ONLY enabling condition — so a single press disabled it forever.
        """
        sut = self._frozen(MeasurementType.CLASSICAL)
        saved_peaks = [_peak(200.0)]
        sut.peaks_above_peak_min = saved_peaks
        sut.loaded_measurement_peaks = saved_peaks
        assert sut.can_reanalyze is True

        sut.reanalyze_peaks()

        assert sut.loaded_measurement_peaks is None, "Re-analyze drops the saved peaks"
        assert sut.can_reanalyze is True, (
            "Re-analyze must remain available after a press — it is a reset, not a one-shot"
        )

    def test_PR36_material_can_never_reanalyze(self, qt_app):
        """Material peaks come from the per-phase captures; find_peaks would destroy them.

        This previously held only by accident (a loaded material measurement leaves the
        frozen spectrum empty), so it is pinned explicitly.
        """
        for mtype in (MeasurementType.PLATE, MeasurementType.BRACE):
            sut = self._frozen(mtype)                      # even WITH a frozen spectrum…
            sut.loaded_measurement_peaks = [_peak(200.0)]  # …and loaded peaks
            assert sut.can_reanalyze is False, (
                f"Re-analyze is meaningless for {mtype} and must never be offered"
            )

    def test_PR37_incomplete_or_no_frozen_spectrum_cannot_reanalyze(self, qt_app):
        """Nothing to re-analyze without a completed measurement and a frozen spectrum."""
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)

        no_spectrum = TapToneAnalyzer()
        no_spectrum.is_measurement_complete = True
        assert no_spectrum.can_reanalyze is False, "No frozen spectrum — nothing to re-analyze from"

        incomplete = self._frozen(MeasurementType.CLASSICAL)
        incomplete.is_measurement_complete = False
        assert incomplete.can_reanalyze is False, "Measurement still in progress"


# ---------------------------------------------------------------------------
# The LOADED branch, the loading guard, and auto-selection
# ---------------------------------------------------------------------------
#
# recalculate_frozen_peaks_if_needed has two branches. This covers the LOADED one — the saved
# peaks are authoritative and are never re-derived from the frozen spectrum — plus the
# is_loading_measurement guard that gates both branches.
#
# Mirrors Swift FrozenPeakRecalculationTests (the loaded-peaks suite).

class TestLoadedPath:
    """The loaded branch of recalculate_frozen_peaks_if_needed."""

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        """The measurement type is global app state — put it back after each test."""
        saved = TapDisplaySettings.measurement_type()
        yield
        TapDisplaySettings.set_measurement_type(saved)

    def _frozen(self, mtype: MeasurementType) -> TapToneAnalyzer:
        """A complete measurement on a FLAT frozen spectrum, so detection would find nothing.

        Two stores must agree: the analyzer keeps its own `_measurement_type` (read by the recalc)
        while the display projection reads TapDisplaySettings. The view sets both — see
        `_apply_measurement_type_to_ui` — so the tests do too, through the production setters.
        """
        TapDisplaySettings.set_measurement_type(mtype)
        sut = TapToneAnalyzer()
        sut.set_measurement_type(mtype)
        sut.frozen_frequencies = np.array([i * HZ_PER_BIN for i in range(N_BINS)])
        sut.frozen_magnitudes = _flat_spectrum()
        sut.is_measurement_complete = True
        return sut
    def test_PR06_loaded_path_uses_saved_peaks_not_the_frozen_spectrum(self, qt_app):
        """PR06: loaded peaks are authoritative — the frozen spectrum is NOT re-analysed.

        Saved peaks may not be reproducible by re-running detection: spectrum averaging, FFT
        windowing and analysis settings can all differ between sessions. The frozen spectrum here
        is flat, so detection would find nothing — the saved peak surviving proves it was used.
        Gap filled 2026-09-19 (issue #8); Swift and web already covered this.
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = self._frozen(MeasurementType.GENERIC)   # flat spectrum: detection finds nothing
        sut.loaded_measurement_peaks = [_peak(300.0, -25.0)]
        sut.peak_min_threshold = -80.0

        sut.recalculate_frozen_peaks_if_needed()

        assert any(abs(p.frequency - 300.0) < 1.0 for p in sut.all_peaks), (
            "the saved peak must survive — a flat spectrum would yield nothing if re-analysed"
        )

    def test_PR07_loaded_peaks_above_threshold_are_kept(self, qt_app):
        """PR07: the durable set holds every saved peak; Peak Min only projects it.

        Asserts BOTH surfaces deliberately. all_peaks must stay whole — assigning it a filtered
        view would shrink it as Peak Min rises, and the save path would then write the shrunken
        set (silent data loss). peaks_above_peak_min is where the filtering shows.
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = self._frozen(MeasurementType.GENERIC)
        strong, weak = _peak(200.0, -20.0), _peak(400.0, -60.0)
        sut.loaded_measurement_peaks = [strong, weak]
        sut.peak_min_threshold = -40.0          # drops the weak one from the DISPLAY only

        sut.recalculate_frozen_peaks_if_needed()

        assert {round(p.frequency) for p in sut.all_peaks} == {200, 400}, (
            "the durable set must keep both saved peaks regardless of Peak Min"
        )
        assert {round(p.frequency) for p in sut.peaks_above_peak_min} == {200}, (
            "the projection must drop the peak below Peak Min"
        )

    def test_PR10_loading_measurement_suppresses_recalculation(self, qt_app):
        """PR10: while is_loading_measurement is set, recalculation is a no-op.

        Swift guards the same way (recalculateFrozenPeaksIfNeeded, first line). Both editions
        trigger recalculation from property observers that can fire part-way through a load, so
        without the guard a half-applied measurement would be re-analysed and clobber what is
        being loaded. Gap filled 2026-09-19 (issue #8): the guard existed here, untested.

        The web needs no equivalent — it drives recalculatePeaks from one layout effect keyed on
        the loaded peaks themselves, so the effect only runs once they are in place.
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = self._frozen(MeasurementType.GENERIC)
        sut.loaded_measurement_peaks = [_peak(200.0, -20.0)]
        sut.all_peaks = []

        sut.is_loading_measurement = True
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.all_peaks == [], (
            "recalculation must not run while a measurement is loading"
        )

    def test_PR11_recalculation_runs_once_loading_completes(self, qt_app):
        """PR11: clearing is_loading_measurement lets the next recalculation through.

        The other half of PR10 — the guard must suppress, not permanently disable.
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = self._frozen(MeasurementType.GENERIC)
        saved = _peak(200.0, -20.0)
        sut.loaded_measurement_peaks = [saved]
        sut.all_peaks = []

        sut.is_loading_measurement = True
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.all_peaks == [], "precondition: suppressed while loading"

        sut.is_loading_measurement = False
        sut.recalculate_frozen_peaks_if_needed()
        assert [p.frequency for p in sut.all_peaks] == [saved.frequency], (
            "once loading completes the saved peaks must be adopted"
        )


    def test_PR08_loaded_all_below_peak_min_clears_display_but_keeps_classification(self, qt_app):
        """PR08: with every loaded peak below Peak Min the DISPLAY empties — the durable set and
        the classification both survive.

        Classification is a fact about the measurement, not about what is on screen. Distinct
        from PR04/PRA4, which pins the projection emptying; this pins what must NOT empty with it.
        Mirrors Swift loadedPeaks_allBelowThreshold_clearsDisplayButKeepsClassification.
        Gap filled 2026-09-19 (issue #8).
        """
        from guitar_tap.models.guitar_mode import GuitarMode

        sut = self._frozen(MeasurementType.GENERIC)
        peak = _peak(200.0, -60.0)
        sut.loaded_measurement_peaks = [peak]
        sut.identified_modes = [{"peak": peak, "mode": GuitarMode.AIR}]
        sut.peak_min_threshold = -10.0          # above every peak

        sut.recalculate_frozen_peaks_if_needed()

        assert sut.peaks_above_peak_min == [], (
            "the projection is what Peak Min empties"
        )
        assert [round(p.frequency) for p in sut.all_peaks] == [200], (
            "a display filter must never shrink the durable set"
        )
        assert [e["mode"] for e in sut.identified_modes] == [GuitarMode.AIR], (
            "classification describes the measurement, not the display"
        )

    def test_PR09_loaded_material_peaks_are_never_filtered_by_peak_min(self, qt_app):
        """PR09: Peak Min is a GUITAR-only control — a loaded plate/brace keeps every peak.

        A loaded material measurement's identified L / C / FLC peaks ARE the result; filtering
        them by a guitar display control would take the answer off the screen. Regression found
        2026-07-21: a loaded plate whose fL sat at -62.41 dB with Peak Min -60 lost that peak
        from both the table and the annotations. Mirrors Swift
        loadedPeaks_material_areNeverFilteredByPeakMin. Gap filled 2026-09-19 (issue #8).
        """
        for mtype in (MeasurementType.PLATE, MeasurementType.BRACE):
            sut = self._frozen(mtype)
            f_l = _peak(66.88, -62.41)          # BELOW Peak Min — the victim
            f_c = _peak(116.75, -57.62)
            sut.loaded_measurement_peaks = [f_l, f_c]
            sut.peak_min_threshold = -60.0      # would drop f_l if the guitar filter applied

            sut.recalculate_frozen_peaks_if_needed()

            freqs = [p.frequency for p in sut.peaks_above_peak_min]
            assert any(abs(f - 66.88) < 0.01 for f in freqs), (
                f"{mtype.short_name}: fL below Peak Min must survive — Peak Min is guitar-only"
            )
            assert any(abs(f - 116.75) < 0.01 for f in freqs), (
                f"{mtype.short_name}: fC must survive"
            )

    def test_PR28_unmodified_selection_re_runs_auto_over_the_durable_set(self, qt_app):
        """PR28: an untouched selection is re-derived, not carried — the loudest peak in each
        claimed mode band wins.

        The counterpart to PR26: once the user has touched the selection it carries forward by
        frequency; until then every recalculation re-runs auto-selection. Acoustic Air is
        90–120 Hz (GuitarType.ACOUSTIC.mode_ranges), so both peaks are Air candidates and only
        magnitude separates them. Mirrors Swift loadedPath_autoSelection_reRunsWhenNotModified.
        Gap filled 2026-09-19 (issue #8).
        """
        sut = self._frozen(MeasurementType.ACOUSTIC)
        quiet_air = _peak(98.0, -50.0)
        loud_air = _peak(105.0, -25.0)
        sut.loaded_measurement_peaks = [quiet_air, loud_air]
        sut.user_has_modified_peak_selection = False
        sut.peak_min_threshold = -80.0

        sut.recalculate_frozen_peaks_if_needed()

        assert loud_air.id in sut.selected_peak_ids, (
            "auto-selection takes the loudest peak in the Air band"
        )
        assert quiet_air.id not in sut.selected_peak_ids, (
            "the quieter Air candidate loses — one winner per mode"
        )
    def test_PR31_loaded_branch_keeps_stable_ids_so_overrides_are_not_remapped_away(self, qt_app):
        """PR31: on the LOADED branch the peak ids do not change, so a restored override must stay
        on its own peak's id — the ±5 Hz remap must not re-home it onto a different peak.

        The carry-forward exists for the RE-MINT case, where detection produces fresh ids and state
        keyed to the old ones has to be moved across by frequency. The loaded branch runs the same
        `_apply_frozen_peak_state` code but sets `all_peaks = loaded_measurement_peaks` — the same
        objects, the same ids — so the remap has nothing to move and must leave every override
        exactly where it was. A remap that ignored the tolerance, or took the first candidate
        regardless of distance, would relabel a peak the user never touched, and that label then
        travels into the saved measurement.

        Mirrors Swift `loadedPath_stableIDs_leaveRestoredOverridesInPlace`; web covers it as
        "the loaded branch keeps stable ids". Gap filled 2026-09-20 (issue #8) — it had been open
        since 2026-09-19 but was invisible, because the parity table showed a dash for BOTH Swift
        and Python after only Swift's half was written.
        """
        sut = self._frozen(MeasurementType.GENERIC)
        low, high = _peak(200.0, -20.0), _peak(400.0, -25.0)
        sut.all_peaks = [low, high]          # the durable set the snapshot resolves against
        sut.loaded_measurement_peaks = [low, high]
        sut.peak_mode_overrides = {low.id: "Air", high.id: "Top"}
        sut.peak_min_threshold = -80.0       # nothing hidden — isolate the id question

        sut.recalculate_frozen_peaks_if_needed()

        assert len(sut.peak_mode_overrides) == 2, (
            "both overrides survive the loaded branch"
        )
        assert sut.peak_mode_overrides.get(low.id) == "Air", (
            "the 200 Hz override stays on the 200 Hz peak's OWN id"
        )
        assert sut.peak_mode_overrides.get(high.id) == "Top", (
            "the 400 Hz override stays on the 400 Hz peak's OWN id"
        )

class TestRemappingThroughProduction:
    """Carry-forward of per-peak state across a re-mint — driven through the REAL path.

    Replaces eight tests purged 2026-09-19 (issue #8) that exercised `_remap_by_freq`, a
    reimplementation of this logic living in the test file, or asserted arithmetic on literals.
    Production remapping could have been broken in every one and all eight would have passed.

    Each test here re-freezes the analyzer on a SHIFTED spectrum so detection mints genuinely new
    peak ids, then asserts what `recalculate_frozen_peaks_if_needed` did with the state keyed to
    the old ones.
    """

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        saved = TapDisplaySettings.measurement_type()
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        yield
        TapDisplaySettings.set_measurement_type(saved)

    @staticmethod
    def _remint(sut, bumps):
        """Re-detect on a new spectrum, as a re-analyze would: fresh ids, same analyzer."""
        freqs, mags = _gaussian_spectrum(bumps)
        sut.frozen_frequencies = freqs
        sut.frozen_magnitudes = mags
        sut.recalculate_frozen_peaks_if_needed()

    @staticmethod
    def _peak_near(sut, hz, tol=5.0):
        return next((p for p in sut.all_peaks if abs(p.frequency - hz) < tol), None)

    def test_PR20_offset_is_remapped_onto_the_nearby_new_peak(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        old = self._peak_near(sut, 200.0)
        assert old is not None, "precondition: a peak was detected at 200 Hz"
        sut.peak_annotation_offsets = {old.id: (12.0, -8.0)}

        self._remint(sut, [(203.0, -20.0)])          # within the 5 Hz tolerance

        new = self._peak_near(sut, 203.0)
        assert new is not None and new.id != old.id, "precondition: the re-mint minted a new id"
        assert sut.peak_annotation_offsets.get(new.id) == (12.0, -8.0), (
            "the dragged label must follow the peak across a re-mint"
        )

    def test_PR22_offset_is_dropped_when_no_new_peak_is_near(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        old = self._peak_near(sut, 200.0)
        sut.peak_annotation_offsets = {old.id: (12.0, -8.0)}

        self._remint(sut, [(300.0, -20.0)])          # far outside the tolerance

        assert old.id not in sut.peak_annotation_offsets, (
            "an offset whose peak vanished must not be carried onto an unrelated peak"
        )

    def test_PR23_override_is_remapped_onto_the_nearby_new_peak(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        old = self._peak_near(sut, 200.0)
        sut.peak_mode_overrides = {old.id: "Air"}

        self._remint(sut, [(203.0, -20.0)])

        new = self._peak_near(sut, 203.0)
        assert new is not None and new.id != old.id
        assert sut.peak_mode_overrides.get(new.id) == "Air", (
            "a custom mode name must follow the peak across a re-mint"
        )

    def test_PR25_override_is_orphaned_when_no_new_peak_is_near(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        old = self._peak_near(sut, 200.0)
        sut.peak_mode_overrides = {old.id: "Air"}

        self._remint(sut, [(300.0, -20.0)])

        new = self._peak_near(sut, 300.0)
        assert new is not None, "precondition: the re-mint produced a peak at 300 Hz"
        # Negative-only assertions pass vacuously on an empty dict, so assert the value is gone
        # ENTIRELY — not merely absent from the new id, which a leak under the old id would satisfy.
        assert "Air" not in sut.peak_mode_overrides.values(), (
            "an orphaned override must be dropped, not re-homed or left under a stale id"
        )

    def test_PR26_manual_selection_is_carried_forward_by_frequency(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0), (400.0, -22.0)])
        keep = self._peak_near(sut, 200.0)
        sut.selected_peak_ids = {keep.id}
        sut.user_has_modified_peak_selection = True

        self._remint(sut, [(203.0, -20.0), (400.0, -22.0)])

        new = self._peak_near(sut, 203.0)
        assert new is not None
        assert new.id in sut.selected_peak_ids, (
            "a deliberate selection must survive a re-mint that shifts the id"
        )

    def test_PR27_selection_is_not_carried_when_the_peak_moved_far(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        keep = self._peak_near(sut, 200.0)
        sut.selected_peak_ids = {keep.id}
        sut.user_has_modified_peak_selection = True

        self._remint(sut, [(300.0, -20.0)])

        moved = self._peak_near(sut, 300.0)
        assert moved is not None, "precondition: the re-mint produced a peak at 300 Hz"
        assert keep.id not in {p.id for p in sut.all_peaks}, "precondition: the old peak is gone"
        assert moved.id not in sut.selected_peak_ids, (
            "selection must not jump to a peak the user never chose"
        )

    def test_PR29_empty_new_peaks_preserve_the_selection_for_re_selection(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        keep = self._peak_near(sut, 200.0)
        sut.selected_peak_ids = {keep.id}
        sut.user_has_modified_peak_selection = True
        before = set(sut.selected_peak_ids)

        sut.frozen_magnitudes = _flat_spectrum(floor=-100.0)   # nothing to detect
        sut.recalculate_frozen_peaks_if_needed()

        assert sut.selected_peak_ids == before, (
            "an empty detection must not erase the selection — lowering the threshold restores it"
        )

    def test_PR30_remap_with_no_prior_overrides_is_a_no_op(self, qt_app):
        sut = TapToneAnalyzer()
        _freeze_on_real_spectrum(sut, [(200.0, -20.0)])
        sut.peak_mode_overrides = {}

        self._remint(sut, [(203.0, -20.0)])       # must not raise

        assert sut.peak_mode_overrides == {}, "no overrides in, none out"


class TestPeakMinDurability:
    """Mirrors Swift PeakMinDurabilityTests — THE point of the peak-lifecycle work.

    Drive the REAL user path (assign peak_min_threshold, which the property setter re-projects,
    exactly as the slider does) and sweep a peak out of view and back: its identity, selection,
    mode override and dragged annotation position must all survive.
    """

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        saved = TapDisplaySettings.measurement_type()
        yield
        TapDisplaySettings.set_measurement_type(saved)

    def _frozen_guitar(self) -> TapToneAnalyzer:
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = TapToneAnalyzer()
        sut.is_measurement_complete = True
        sut.frozen_frequencies = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0])
        sut.frozen_magnitudes = np.array([-100.0] * 6)
        return sut

    def test_PR19_reanalyze_preserves_state_of_peaks_hidden_by_peak_min(self, qt_app):
        """Re-analyze re-detects from the frozen spectrum, and a peak HIDDEN by Peak Min keeps its
        dragged annotation offset and its custom mode name — the carry-forward snapshot resolves
        UUIDs over the durable ``all_peaks``, not the Peak-Min projection (Phase 4a). Mirrors Swift
        ``reanalyzePreservesStateOfPeaksHiddenByPeakMin``. Asserts its own preconditions so it cannot
        rot into a vacuous pass through the flat-spectrum trap.
        """
        sut = TapToneAnalyzer()
        # A loud 200 Hz peak and a quiet 400 Hz peak, detected on a real spectrum.
        _freeze_on_real_spectrum(sut, [(200.0, -20.0), (400.0, -55.0)])
        # Peak Min hides the quiet 400 Hz peak; the durable set keeps it.
        sut.peak_min_threshold = -40.0
        sut.refresh_displayed_peaks()

        hidden = next(p for p in sut.all_peaks if abs(p.frequency - 400.0) < 5.0)
        # Preconditions — so the test cannot pass vacuously:
        assert hidden.id not in {p.id for p in sut.peaks_above_peak_min}, \
            "precondition: 400 Hz peak must be hidden by Peak Min"
        assert any(abs(p.frequency - 200.0) < 5.0 for p in sut.peaks_above_peak_min), \
            "precondition: 200 Hz peak must be visible"

        # Drag a label and assign a custom mode on the HIDDEN peak.
        sut.peak_annotation_offsets[hidden.id] = [400.0, -60.0]
        sut.peak_mode_overrides[hidden.id] = "Wolf note"

        sut.reanalyze_peaks()

        # After re-detection (fresh UUIDs) the 400 Hz peak still exists in the durable set...
        new_hidden = next(p for p in sut.all_peaks if abs(p.frequency - 400.0) < 5.0)
        # ...and both its dragged offset and its custom name carried forward to the new id.
        assert new_hidden.id in sut.peak_annotation_offsets, \
            "dragged annotation offset must survive Re-analyze on a Peak-Min-hidden peak"
        assert sut.peak_mode_overrides.get(new_hidden.id) == "Wolf note", \
            "custom mode name must survive Re-analyze on a Peak-Min-hidden peak"

    def test_PR13_peak_min_sweep_preserves_identity_selection_override_and_offset(self, qt_app):
        sut = self._frozen_guitar()
        loud = _peak(200.0, -20.0)
        quiet = _peak(300.0, -50.0)   # the one we will hide
        sut.all_peaks = [loud, quiet]
        sut.peak_min_threshold = -60.0   # both displayed

        # User state, all on the peak that is about to be hidden.
        sut.selected_peak_ids = {quiet.id}
        sut.set_mode_override("Wolf note", quiet.id)
        sut.update_annotation_offset(quiet.id, (12.0, 34.0))

        # Raise Peak Min above the quiet peak — it vanishes from the DISPLAY only.
        sut.peak_min_threshold = -40.0
        assert not any(p.id == quiet.id for p in sut.peaks_above_peak_min), "quiet peak should be hidden"
        assert any(p.id == quiet.id for p in sut.all_peaks), (
            "...but it must remain in the durable set — hidden, not destroyed"
        )

        # Lower it again.
        sut.peak_min_threshold = -60.0
        assert any(p.id == quiet.id for p in sut.peaks_above_peak_min), (
            "the SAME peak identity must come back, not a new one"
        )
        assert quiet.id in sut.selected_peak_ids, "selection must survive a Peak Min sweep"
        assert sut.has_manual_override(quiet.id), "custom mode label must survive a Peak Min sweep"
        assert sut.peak_annotation_offsets.get(quiet.id) == (12.0, 34.0), (
            "dragged annotation position must survive a Peak Min sweep"
        )

    def test_PR14_deselect_survives_peak_min_sweep(self, qt_app):
        """PEAK-SELECTION-SURVIVES-SLIDER.md: deselect a peak, sweep Peak Min — it stays
        deselected. The decoupling means the slider never re-runs the carry-forward.
        """
        sut = self._frozen_guitar()
        a = _peak(200.0, -20.0)
        b = _peak(300.0, -25.0)
        sut.all_peaks = [a, b]
        sut.peak_min_threshold = -60.0
        sut.selected_peak_ids = {a.id, b.id}

        sut.toggle_peak_selection(b.id)
        assert b.id not in sut.selected_peak_ids, "b just deselected"

        sut.peak_min_threshold = -30.0
        sut.peak_min_threshold = -60.0

        assert b.id not in sut.selected_peak_ids, (
            "a deselected peak must NOT re-select on a Peak Min sweep"
        )
        assert a.id in sut.selected_peak_ids, "the still-selected peak stays selected"

    # ── Phase 3: per-tap entries computed once, at capture (mirrors Swift 11689b6) ──────────

    def _tap_entry(self, tap_index, peaks, selected):
        from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
        from guitar_tap.models.tap_tone_measurement import TapEntry
        snap = SpectrumSnapshot(
            frequencies=[100.0, 200.0, 300.0, 400.0],
            magnitudes=[-40.0, -20.0, -50.0, -60.0],
        )
        return TapEntry(
            id=str(uuid.uuid4()),
            tap_index=tap_index,
            snapshot=snap,
            peaks=list(peaks),
            selected_peak_ids=list(selected),
        )

    def test_PR15_peak_min_sweep_leaves_tap_entries_untouched(self, qt_app):
        """Mirrors Swift peakMinSweep_leavesTapEntriesUntouched — drive the real slider path."""
        sut = self._frozen_guitar()
        loud = _peak(200.0, -20.0)
        quiet = _peak(300.0, -50.0)
        sut.all_peaks = [loud, quiet]
        sut.peak_min_threshold = -60.0
        sut.tap_entries = [self._tap_entry(1, [loud, quiet], [quiet.id])]
        before_ids = [[p.id for p in e.peaks] for e in sut.tap_entries]
        before_sel = [list(e.selected_peak_ids) for e in sut.tap_entries]

        sut.peak_min_threshold = -40.0   # hides `quiet` from the DISPLAY
        sut.peak_min_threshold = -60.0   # and back

        assert [[p.id for p in e.peaks] for e in sut.tap_entries] == before_ids, (
            "per-tap peak identities must not change when Peak Min moves"
        )
        assert [list(e.selected_peak_ids) for e in sut.tap_entries] == before_sel, (
            "per-tap selection must not be rebuilt when Peak Min moves"
        )
        assert len(sut.tap_entries[0].peaks) == 2, (
            "the sub-Peak-Min peak stays in the durable per-tap set — hidden, not destroyed"
        )

    def test_PR16_recalculate_frozen_peaks_leaves_tap_entries_untouched(self, qt_app):
        """Mirrors Swift recalculateFrozenPeaks_leavesTapEntriesUntouched — the direct guard
        against the deleted per-tap recompute being reintroduced, on BOTH recalc branches."""
        loud = _peak(200.0, -20.0)
        quiet = _peak(300.0, -50.0)
        for loaded in (True, False):
            sut = self._frozen_guitar()
            sut.all_peaks = [loud, quiet]
            if loaded:
                sut.loaded_measurement_peaks = [loud, quiet]
            sut.peak_min_threshold = -40.0   # above `quiet`, so a re-detect would drop it
            sut.tap_entries = [self._tap_entry(1, [loud, quiet], [quiet.id])]
            before_ids = [[p.id for p in e.peaks] for e in sut.tap_entries]
            before_sel = [list(e.selected_peak_ids) for e in sut.tap_entries]

            sut.recalculate_frozen_peaks_if_needed()

            assert [[p.id for p in e.peaks] for e in sut.tap_entries] == before_ids, (
                f"recalc must not re-detect per-tap peaks (loaded={loaded})"
            )
            assert [list(e.selected_peak_ids) for e in sut.tap_entries] == before_sel, (
                f"recalc must not rebuild per-tap selection (loaded={loaded})"
            )

    def test_PR17_loading_restores_saved_per_tap_peaks_and_never_re_detects(self, qt_app):
        """PR17: per-tap peaks are found ONCE, at capture, and persisted — loading restores them
        verbatim.

        The companion to PR15/PR16, which pin the same rule against a *display* recalc. This pins
        it against the LOAD. The saved entry carries a peak at 777 Hz, a frequency absent from
        its own snapshot, so re-detection could not mint it: if it comes back, it was restored.
        tap_entries is persisted, so re-deriving here would truncate the saved per-tap set —
        load with Peak Min raised, save, and the difference is permanent. Mirrors web's
        `loaded per-tap entries are found once`. Gap filled 2026-09-19 (issue #8).
        """
        sut = self._frozen_guitar()
        undetectable = _peak(777.0, -30.0)   # not a local max of the entry's snapshot
        entry = self._tap_entry(1, [undetectable], [undetectable.id])
        saved = TapToneMeasurement.create(
            peaks=[undetectable],
            spectrum_snapshot=entry.snapshot,
            tap_entries=[entry],
            measurement_type=MeasurementType.GENERIC.value,
        )

        sut.load_measurement(saved)

        assert len(sut.tap_entries) == 1, "the saved per-tap entry must be restored"
        assert [p.id for p in sut.tap_entries[0].peaks] == [undetectable.id], (
            "per-tap peaks are restored by identity, never re-detected from the saved spectrum"
        )
        assert [round(p.frequency) for p in sut.tap_entries[0].peaks] == [777], (
            "a peak absent from the snapshot proves the saved set was used"
        )

    def test_PR18_selected_peaks_resolve_over_durable_set(self, qt_app):
        """Mirrors Swift selectedPeaks_resolveOverDurableSet_notTheDisplayProjection — the
        averaged-row source. A selected peak below Peak Min must stay in `selected_peaks`."""
        sut = self._frozen_guitar()
        loud = _peak(200.0, -20.0)
        quiet = _peak(300.0, -50.0)
        sut.all_peaks = [loud, quiet]
        sut.peak_min_threshold = -60.0
        sut.selected_peak_ids = {loud.id, quiet.id}

        sut.peak_min_threshold = -40.0   # hides `quiet` from the display

        assert not any(p.id == quiet.id for p in sut.peaks_above_peak_min), (
            "precondition: the quiet peak is hidden from the display"
        )
        resolved = {p.id for p in sut.selected_peaks}
        assert resolved == {loud.id, quiet.id}, (
            "a selected peak below Peak Min is still selected — derived values must include it"
        )

# ---------------------------------------------------------------------------
# The LIVE branch — peaks follow the incoming spectrum until the measurement completes
# ---------------------------------------------------------------------------

class TestLivePath:
    """analyze_magnitudes: the live display, and where it stops."""

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        saved = TapDisplaySettings.measurement_type()
        yield
        TapDisplaySettings.set_measurement_type(saved)

    def test_PR12_live_peaks_track_the_spectrum_until_the_measurement_completes(self, qt_app):
        """PR12: while detection is running the durable set follows each FFT frame; once the
        measurement is complete analyze_magnitudes stops touching it.

        The second half is the load-bearing one. After completion the frozen/loaded path owns
        the display, and a late audio frame arriving from the still-draining engine must not
        overwrite the captured result. Mirrors web's `live-spectrum path`; Swift covers the
        same guard in `analyzeMagnitudes`. Gap filled 2026-09-19 (issue #8).
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut = TapToneAnalyzer()
        sut.set_measurement_type(MeasurementType.GENERIC)
        sut.min_frequency = 50.0
        sut.max_frequency = 500.0
        sut.peak_min_threshold = -80.0
        sut.detection_state = DetectionState.LISTENING
        sut.is_measurement_complete = False

        freqs, mags = _gaussian_spectrum([(200.0, -20.0)])
        sut.analyze_magnitudes(list(mags), list(freqs), float(np.max(mags)))

        assert any(abs(p.frequency - 200.0) < 2.0 for p in sut.all_peaks), (
            "the live frame's peak must reach the durable set"
        )

        sut.is_measurement_complete = True
        late_freqs, late_mags = _gaussian_spectrum([(300.0, -20.0)])
        sut.analyze_magnitudes(list(late_mags), list(late_freqs), float(np.max(late_mags)))

        assert any(abs(p.frequency - 200.0) < 2.0 for p in sut.all_peaks), (
            "the captured result must survive a late frame"
        )
        assert not any(abs(p.frequency - 300.0) < 2.0 for p in sut.all_peaks), (
            "a frame arriving after completion must not re-analyse the display"
        )


# ---------------------------------------------------------------------------
# Material peaks carry ordinary peak identity
# ---------------------------------------------------------------------------

class TestMaterialPeakIdentity:
    """A captured material peak is a ResonantPeak like any other — same id, same state stores."""

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        saved = TapDisplaySettings.measurement_type()
        yield
        TapDisplaySettings.set_measurement_type(saved)

    def test_PR32_a_captured_material_peak_owns_its_annotation_offset(self, qt_app):
        """PR32: a brace capture mints a real peak id, and its dragged label lives in the ONE
        annotation store — there is no separate material store.

        Material peaks reach the chart through a different capture path (the gated per-phase
        handlers, not find_peaks on a frozen spectrum), so the risk is that they arrive as
        second-class objects the per-peak state cannot key on. Driven through
        _handle_longitudinal_gated_progress, the real brace completion path. Mirrors web's
        `a captured MATERIAL peak gets a stored id`. Gap filled 2026-09-19 (issue #8).
        """
        TapDisplaySettings.set_measurement_type(MeasurementType.BRACE)
        sut = TapToneAnalyzer()
        sut.set_measurement_type(MeasurementType.BRACE)
        sut.min_frequency = 100.0
        sut.max_frequency = 1200.0
        sut.number_of_taps = 1

        freqs, mags = _gaussian_spectrum([(300.0, -30.0)], lo=100.0, hi=1200.0)
        dominant = sut.find_dominant_peak(
            magnitudes=list(mags), frequencies=list(freqs), min_hz=100.0, max_hz=1200.0,
        )
        assert dominant is not None, "precondition: the synthetic brace tap has a dominant peak"
        sut.captured_taps = [(list(mags), list(freqs), 0.0)]

        sut._handle_longitudinal_gated_progress(
            list(mags), list(freqs), dominant, min_hz=100.0, max_hz=1200.0,
        )

        captured = sut.selected_longitudinal_peak
        assert captured is not None, "the brace capture must produce an fL peak"
        assert captured.id, "a captured material peak carries a real id"
        # Precondition, not a claim: the brace branch assigns all_peaks = [selected fL], so this
        # holds by construction. The assertions with teeth are the round trip below.
        assert [p.id for p in sut.all_peaks] == [captured.id]

        sut.update_annotation_offset(captured.id, (12.0, -3.0))

        assert sut.peak_annotation_offsets.get(captured.id) == (12.0, -3.0), (
            "a material peak's offset lives in peak_annotation_offsets — the same one store"
        )

        # The claim with teeth: that identity survives a save/load round trip. The save path
        # persists guitar_full_save_peaks() (= all_peaks) and the load path restores an offset
        # only for an id it finds in measurement.peaks — so a material peak missing from the
        # saved set would silently drop its label position.
        saved = TapToneMeasurement.create(
            peaks=sut.guitar_full_save_peaks(),
            annotation_offsets=dict(sut.peak_annotation_offsets),
            measurement_type=MeasurementType.BRACE.value,
        )
        reloaded = TapToneAnalyzer()
        reloaded.set_measurement_type(MeasurementType.BRACE)
        reloaded.load_measurement(saved)

        assert reloaded.get_annotation_offset(captured.id) == (12.0, -3.0), (
            "the offset must come back keyed to the same material peak id"
        )
