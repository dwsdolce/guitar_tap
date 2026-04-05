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

    def __init__(self) -> None:
        _get_app()
        super().__init__(None)
        self._display_mode = AnalysisDisplayMode.LIVE
        self._comparison_data: list = []
        self.comparison_labels: list = []
        self.savedMeasurements: list = []

    @property
    def is_comparing(self) -> bool:
        return self._display_mode == AnalysisDisplayMode.COMPARISON

    def update_axis(self, min_freq: int, max_freq: int) -> None:
        self.freqRangeChanged.emit(min_freq, max_freq)


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
