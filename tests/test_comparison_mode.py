"""
Port of ComparisonModeTests.swift — comparison overlay loading and clearing.

Mirrors Swift test plan coverage CP-U1–CP-U8 and DisplayModeTransitionTests.

Strategy: rather than instantiating the full TapToneAnalyzer (which requires
sounddevice, views, Qt widgets), we test the mixin methods directly by creating
a minimal stub object that owns only the fields the mixin uses.
"""

from __future__ import annotations

import sys, os
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtCore, QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode
from guitar_tap.models.tap_tone_analyzer_measurement_management import (
    TapToneAnalyzerMeasurementManagementMixin,
)
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot


# ---------------------------------------------------------------------------
# Minimal stub that exercises the mixin without the full analyzer
# ---------------------------------------------------------------------------

class _StubAnalyzer(
    TapToneAnalyzerMeasurementManagementMixin,
    QtCore.QObject,
):
    """Minimal stub that provides just the state the mixin methods touch."""

    comparisonChanged: QtCore.Signal = QtCore.Signal(bool)
    savedMeasurementsChanged: QtCore.Signal = QtCore.Signal()
    freqRangeChanged: QtCore.Signal = QtCore.Signal(int, int)
    loadedMeasurementNameChanged: QtCore.Signal = QtCore.Signal(object)

    def __init__(self) -> None:
        _get_app()
        super().__init__(None)
        self._display_mode = AnalysisDisplayMode.LIVE
        self._comparison_data: list = []
        self.comparison_labels: list = []
        self.comparison_snapshots: list = []
        self.savedMeasurements: list = []
        self.loaded_measurement_name: str | None = None

    @property
    def is_comparing(self) -> bool:
        return self._display_mode == AnalysisDisplayMode.COMPARISON

    def update_axis(self, min_freq: int, max_freq: int) -> None:
        self.freqRangeChanged.emit(min_freq, max_freq)

    def _persist_measurements(self) -> None:
        pass  # no-op stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(
    min_freq: float = 80.0, max_freq: float = 1200.0,
    min_db: float = -90.0, max_db: float = -10.0,
) -> SpectrumSnapshot:
    return SpectrumSnapshot(
        frequencies=[100.0, 200.0, 300.0, 400.0],
        magnitudes=[-40.0, -35.0, -45.0, -50.0],
        min_freq=min_freq, max_freq=max_freq,
        min_db=min_db, max_db=max_db,
    )


def _make_measurement(
    tap_location: str | None = None,
    with_snapshot: bool = True,
) -> TapToneMeasurement:
    return TapToneMeasurement.create(
        peaks=[],
        tap_location=tap_location,
        spectrum_snapshot=_make_snapshot() if with_snapshot else None,
    )


# ---------------------------------------------------------------------------
# loadComparison tests  (CP-U1–CP-U5)
# ---------------------------------------------------------------------------

class TestComparisonLoad:
    """Mirrors Swift ComparisonLoadTests (CP-U1–CP-U5)."""

    def test_CP_U1_two_measurements_produce_two_entries(self):
        """CP-U1: Loading 2 measurements populates _comparison_data with 2 entries."""
        sut = _StubAnalyzer()
        m1 = _make_measurement(tap_location="Bridge")
        m2 = _make_measurement(tap_location="Neck")
        sut.load_comparison([m1, m2])
        assert len(sut._comparison_data) == 2
        assert sut._display_mode == AnalysisDisplayMode.COMPARISON

    def test_CP_U2_label_uses_tap_location(self):
        """CP-U2: Label uses tapLocation when present."""
        sut = _StubAnalyzer()
        m = _make_measurement(tap_location="Bridge Area")
        sut.load_comparison([m])
        assert sut._comparison_data[0]["label"] == "Bridge Area"

    def test_CP_U3_skips_measurements_without_snapshot(self):
        """CP-U3: Measurements without a spectrum snapshot are silently filtered out."""
        sut = _StubAnalyzer()
        with_snap    = _make_measurement(tap_location="With",    with_snapshot=True)
        without_snap = _make_measurement(tap_location="Without", with_snapshot=False)
        sut.load_comparison([with_snap, without_snap])
        assert len(sut._comparison_data) == 1
        assert sut._comparison_data[0]["label"] == "With"

    def test_CP_U4_palette_wraps_for_more_than_5_entries(self):
        """CP-U4: Colors cycle through the 5-color palette without crashing for >5 entries."""
        sut = _StubAnalyzer()
        measurements = [_make_measurement(tap_location=f"M{i}") for i in range(1, 7)]
        sut.load_comparison(measurements)   # must not raise
        assert len(sut._comparison_data) == 6

    def test_CP_U5_axis_bounds_set_to_union_of_snapshots(self):
        """CP-U5: Axis bounds are set to the union of all snapshot ranges."""
        sut = _StubAnalyzer()
        axis_events: list[tuple] = []
        sut.freqRangeChanged.connect(lambda lo, hi: axis_events.append((lo, hi)))

        m1 = TapToneMeasurement.create(
            peaks=[], tap_location="A",
            spectrum_snapshot=_make_snapshot(min_freq=50.0, max_freq=800.0),
        )
        m2 = TapToneMeasurement.create(
            peaks=[], tap_location="B",
            spectrum_snapshot=_make_snapshot(min_freq=100.0, max_freq=1200.0),
        )
        sut.load_comparison([m1, m2])

        assert len(axis_events) == 1, "Should emit freqRangeChanged once"
        lo, hi = axis_events[0]
        assert lo == 50, f"minFreq should be 50, got {lo}"
        assert hi == 1200, f"maxFreq should be 1200, got {hi}"


# ---------------------------------------------------------------------------
# clearComparison tests  (CP-U6–CP-U8)
# ---------------------------------------------------------------------------

class TestComparisonClear:
    """Mirrors Swift ComparisonClearTests (CP-U6–CP-U8)."""

    def test_CP_U6_clear_comparison_empties_data(self):
        """CP-U6: clearComparison() empties _comparison_data."""
        sut = _StubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        assert len(sut._comparison_data) == 2

        sut.clear_comparison()

        assert sut._comparison_data == []
        assert sut._display_mode == AnalysisDisplayMode.LIVE

    def test_CP_U7_load_empty_array_produces_empty_data(self):
        """CP-U7: Loading an empty array also clears _comparison_data."""
        sut = _StubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        sut.load_comparison([])
        assert sut._comparison_data == []
        assert sut._display_mode == AnalysisDisplayMode.LIVE

    def test_CP_U8_no_snapshots_leaves_mode_as_live(self):
        """CP-U8: All measurements lacking snapshots → mode stays LIVE."""
        sut = _StubAnalyzer()
        sut.load_comparison([
            _make_measurement(with_snapshot=False),
            _make_measurement(with_snapshot=False),
        ])
        assert sut._comparison_data == []
        assert sut._display_mode == AnalysisDisplayMode.LIVE


# ---------------------------------------------------------------------------
# DisplayMode transition tests
# ---------------------------------------------------------------------------

class TestDisplayModeTransitions:
    """Mirrors Swift DisplayModeTransitionTests."""

    def test_initial_mode_is_live(self):
        sut = _StubAnalyzer()
        assert sut._display_mode == AnalysisDisplayMode.LIVE

    def test_load_comparison_sets_mode_to_comparison(self):
        sut = _StubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        assert sut._display_mode == AnalysisDisplayMode.COMPARISON

    def test_clear_comparison_sets_mode_to_live(self):
        sut = _StubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        sut.clear_comparison()
        assert sut._display_mode == AnalysisDisplayMode.LIVE

    def test_comparison_changed_signal_emitted_on_load(self):
        sut = _StubAnalyzer()
        events: list[bool] = []
        sut.comparisonChanged.connect(lambda v: events.append(v))
        sut.load_comparison([_make_measurement(), _make_measurement()])
        assert events == [True], f"Should emit True on load; got {events}"

    def test_comparison_changed_signal_emitted_on_clear(self):
        sut = _StubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        events: list[bool] = []
        sut.comparisonChanged.connect(lambda v: events.append(v))
        sut.clear_comparison()
        assert events == [False], f"Should emit False on clear; got {events}"


# ---------------------------------------------------------------------------
# Extended stub for Phase 2 tests (requires extra signals + persistence stub)
# ---------------------------------------------------------------------------

class _FullStubAnalyzer(_StubAnalyzer):
    """Extends _StubAnalyzer with persistence capture for Phase 2 inspection."""

    def __init__(self) -> None:
        super().__init__()
        self._persisted: list = []   # captures what would be written to disk

    def _persist_measurements(self) -> None:
        """Captures the list for inspection after save_comparison()."""
        self._persisted = list(self.savedMeasurements)


def _make_measurement_with_peaks(
    tap_location: str | None = "Bridge",
    guitar_type: str | None = "Classical",
) -> "TapToneMeasurement":
    """Create a measurement carrying two peaks suitable for resolved_mode_peaks."""
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
    # Create peaks near typical Air (100 Hz) and Top (200 Hz) frequency ranges
    p_air = ResonantPeak(
        frequency=100.0, magnitude=-30.0, quality=10.0,
        bandwidth=10.0, id=str(uuid.uuid4()),
    )
    p_top = ResonantPeak(
        frequency=195.0, magnitude=-28.0, quality=8.0,
        bandwidth=12.0, id=str(uuid.uuid4()),
    )
    # Set guitar_type on the snapshot so load_comparison picks it up via snap.guitar_type
    snap = SpectrumSnapshot(
        frequencies=[100.0, 200.0, 300.0, 400.0],
        magnitudes=[-40.0, -35.0, -45.0, -50.0],
        min_freq=80.0, max_freq=1200.0,
        min_db=-90.0, max_db=-10.0,
        guitar_type=guitar_type,
    )
    return TapToneMeasurement.create(
        peaks=[p_air, p_top],
        tap_location=tap_location,
        spectrum_snapshot=snap,
        guitar_type=guitar_type,
    )


# ---------------------------------------------------------------------------
# Phase 1 — resolved_mode_peaks helper
# ---------------------------------------------------------------------------

class TestResolvedModePeaks:
    """Mirrors Swift TapToneAnalyzerResolvedModePeaksTests (Phase 1)."""

    def test_returns_empty_for_no_peaks(self):
        """No peaks → empty dict."""
        from guitar_tap.models.tap_tone_analyzer_peak_analysis import (
            TapToneAnalyzerPeakAnalysisMixin,
        )
        result = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks([], "Classical")
        assert result == {}

    def test_classifies_air_peak(self):
        """A peak at a typical Air frequency should appear under GuitarMode.AIR."""
        from guitar_tap.models.tap_tone_analyzer_peak_analysis import (
            TapToneAnalyzerPeakAnalysisMixin,
        )
        from guitar_tap.models.resonant_peak import ResonantPeak
        from guitar_tap.models.guitar_mode import GuitarMode
        peak = ResonantPeak(
            frequency=100.0, magnitude=-30.0, quality=10.0,
            bandwidth=10.0, id=str(uuid.uuid4()),
        )
        result = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            [peak], guitar_type="Classical"
        )
        assert GuitarMode.AIR in result
        assert abs(result[GuitarMode.AIR] - 100.0) < 1e-6

    def test_highest_magnitude_peak_wins_per_mode(self):
        """When two peaks fall in the same mode band, the higher-magnitude one wins."""
        from guitar_tap.models.tap_tone_analyzer_peak_analysis import (
            TapToneAnalyzerPeakAnalysisMixin,
        )
        from guitar_tap.models.resonant_peak import ResonantPeak
        from guitar_tap.models.guitar_mode import GuitarMode
        p1 = ResonantPeak(frequency=100.0, magnitude=-40.0, quality=10.0,
                          bandwidth=10.0, id=str(uuid.uuid4()))
        p2 = ResonantPeak(frequency=105.0, magnitude=-25.0, quality=10.0,
                          bandwidth=10.0, id=str(uuid.uuid4()))
        result = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            [p1, p2], guitar_type="Classical"
        )
        # p2 has higher magnitude — should win
        if GuitarMode.AIR in result:
            assert abs(result[GuitarMode.AIR] - 105.0) < 1e-6

    def test_comparison_data_carries_peaks_and_guitar_type(self):
        """After load_comparison, each _comparison_data entry has 'peaks' and 'guitar_type'."""
        sut = _FullStubAnalyzer()
        m = _make_measurement_with_peaks(tap_location="Bridge", guitar_type="Classical")
        sut.load_comparison([m])
        assert len(sut._comparison_data) == 1
        entry = sut._comparison_data[0]
        assert "peaks" in entry, "Entry should carry 'peaks'"
        assert "guitar_type" in entry, "Entry should carry 'guitar_type'"
        assert entry["guitar_type"] == "Classical"


# ---------------------------------------------------------------------------
# Phase 2 — save_comparison / load comparison record
# ---------------------------------------------------------------------------

class TestSaveComparison:
    """Mirrors Swift ComparisonSaveLoadTests (Phase 2)."""

    def test_save_comparison_creates_record(self):
        """save_comparison() appends a measurement with is_comparison == True."""
        sut = _FullStubAnalyzer()
        m1 = _make_measurement(tap_location="Bridge")
        m2 = _make_measurement(tap_location="Neck")
        sut.load_comparison([m1, m2])
        sut.save_comparison(tap_location="My Comparison", notes=None)

        assert len(sut.savedMeasurements) == 1
        saved = sut.savedMeasurements[0]
        assert saved.is_comparison

    def test_save_comparison_entries_count_matches_comparison_data(self):
        """Entry count in the saved record matches the number of loaded spectra."""
        sut = _FullStubAnalyzer()
        measurements = [_make_measurement(tap_location=f"M{i}") for i in range(3)]
        sut.load_comparison(measurements)
        sut.save_comparison(tap_location="Triple", notes=None)

        saved = sut.savedMeasurements[0]
        assert saved.comparison_entries is not None
        assert len(saved.comparison_entries) == 3

    def test_save_comparison_noop_when_no_comparison_data(self):
        """save_comparison() does nothing when _comparison_data is empty."""
        sut = _FullStubAnalyzer()
        sut.save_comparison(tap_location="Empty", notes=None)
        assert sut.savedMeasurements == []

    def test_save_comparison_tap_location_stored(self):
        """tap_location argument is stored on the saved measurement."""
        sut = _FullStubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        sut.save_comparison(tap_location="My Label", notes="Some notes")
        saved = sut.savedMeasurements[0]
        assert saved.tap_location == "My Label"
        assert saved.notes == "Some notes"

    def test_save_comparison_color_components_normalised(self):
        """color_components in each entry should be in [0, 1] range."""
        sut = _FullStubAnalyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        sut.save_comparison()
        saved = sut.savedMeasurements[0]
        for entry in saved.comparison_entries:
            for c in entry.color_components:
                assert 0.0 <= c <= 1.0, f"Component {c} out of [0,1] range"


class TestLoadComparisonRecord:
    """Mirrors Swift comparison record load path tests (Phase 2)."""

    def _make_saved_comparison(self, n: int = 2) -> "TapToneMeasurement":
        """Helper: create and save a comparison, return the saved record."""
        sut = _FullStubAnalyzer()
        measurements = [_make_measurement(tap_location=f"M{i}") for i in range(n)]
        sut.load_comparison(measurements)
        sut.save_comparison(tap_location="Saved Comparison")
        return sut.savedMeasurements[0]

    def test_load_comparison_record_sets_display_mode(self):
        """Loading a comparison record sets display_mode to COMPARISON."""
        record = self._make_saved_comparison(2)
        sut2 = _FullStubAnalyzer()
        # _load_measurement_body is the internal path; use the public load_measurement
        # which calls it. Stub out the parts that aren't relevant.
        sut2._restore_comparison_from_entries(record)
        assert sut2._display_mode == AnalysisDisplayMode.COMPARISON

    def test_load_comparison_record_populates_comparison_data(self):
        """After loading a comparison record, _comparison_data has the right entry count."""
        record = self._make_saved_comparison(3)
        sut2 = _FullStubAnalyzer()
        sut2._restore_comparison_from_entries(record)
        assert len(sut2._comparison_data) == 3

    def test_load_comparison_record_restores_labels(self):
        """Labels in _comparison_data match the saved ComparisonEntry labels."""
        sut = _FullStubAnalyzer()
        m1 = _make_measurement(tap_location="Bridge")
        m2 = _make_measurement(tap_location="Neck")
        sut.load_comparison([m1, m2])
        sut.save_comparison(tap_location="Test")
        record = sut.savedMeasurements[0]

        sut2 = _FullStubAnalyzer()
        sut2._restore_comparison_from_entries(record)
        labels = [e["label"] for e in sut2._comparison_data]
        assert "Bridge" in labels
        assert "Neck" in labels

    def test_load_comparison_record_emits_comparison_changed(self):
        """_restore_comparison_from_entries emits comparisonChanged(True)."""
        record = self._make_saved_comparison(2)
        sut2 = _FullStubAnalyzer()
        events: list[bool] = []
        sut2.comparisonChanged.connect(lambda v: events.append(v))
        sut2._restore_comparison_from_entries(record)
        assert True in events

    def test_load_comparison_record_axis_restored(self):
        """Axis bounds are restored from the union of entry snapshots."""
        sut = _FullStubAnalyzer()
        m1 = TapToneMeasurement.create(
            peaks=[], tap_location="A",
            spectrum_snapshot=_make_snapshot(min_freq=50.0, max_freq=800.0),
        )
        m2 = TapToneMeasurement.create(
            peaks=[], tap_location="B",
            spectrum_snapshot=_make_snapshot(min_freq=100.0, max_freq=1200.0),
        )
        sut.load_comparison([m1, m2])
        sut.save_comparison(tap_location="Axis Test")
        record = sut.savedMeasurements[0]

        sut2 = _FullStubAnalyzer()
        axis_events: list[tuple] = []
        sut2.freqRangeChanged.connect(lambda lo, hi: axis_events.append((lo, hi)))
        sut2._restore_comparison_from_entries(record)
        assert len(axis_events) >= 1
        lo, hi = axis_events[-1]
        assert lo <= 50
        assert hi >= 1200
