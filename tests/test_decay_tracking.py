"""
Port of DecayTrackingTests.swift — ring-out measurement after a tap.

Mirrors Swift DecayTrackingTests test suite.
"""

from __future__ import annotations

import sys, os
import time

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


from guitar_tap.models.tap_tone_analyzer_decay_tracking import DecayTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(decay_threshold_db: float = 15.0) -> tuple["DecayTracker", list]:
    _get_app()
    tracker = DecayTracker(decay_threshold_db=decay_threshold_db)
    results: list[float] = []
    tracker.ringOutMeasured.connect(lambda v: results.append(v))
    return tracker, results


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestDecayTracking:
    """Mirrors Swift DecayTrackingTests."""

    def test_not_tracking_update_ignored(self):
        """update() before start() is a no-op — no emission."""
        tracker, results = _make_tracker()
        tracker.update(50)
        assert results == [], "update() without start() should not emit"

    def test_level_never_decays_no_emission(self):
        """If the level never drops below the threshold, ringOutMeasured is never emitted."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        # Feed 20 updates that never drop below peak-15 = 65
        for _ in range(20):
            tracker.update(70)   # 70 > 80-15=65 → not decayed
        assert results == [], "Signal that never decays should not emit"

    def test_normal_decay_emits_with_positive_elapsed(self):
        """A level that drops below the threshold emits a positive elapsed time."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        time.sleep(0.01)   # tiny sleep so elapsed > 0
        tracker.update(64)   # 64 <= 80-15=65 → triggers
        assert len(results) == 1, "Should emit exactly once on decay threshold crossing"
        assert results[0] >= 0.0, f"Elapsed time must be non-negative; got {results[0]}"

    def test_immediate_decay_on_first_update(self):
        """If the very first update is already below threshold, emit immediately."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        tracker.update(60)   # well below 80-15=65
        assert len(results) == 1, "Should emit on first update if already decayed"

    def test_emits_only_once_not_multiple_times(self):
        """ringOutMeasured should be emitted exactly once, not on subsequent low updates."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        # First update crosses threshold — fires
        tracker.update(60)
        assert len(results) == 1
        # Subsequent low updates should not fire again
        for _ in range(5):
            tracker.update(50)
        assert len(results) == 1, "Should emit only once; emitted multiple times"

    def test_reset_stops_tracking(self):
        """After reset(), further updates do nothing."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        tracker.reset()
        tracker.update(50)   # would cross threshold, but tracking was cancelled
        assert results == [], "No emission after reset()"

    def test_start_after_reset_works(self):
        """start() after reset() re-activates tracking."""
        tracker, results = _make_tracker(decay_threshold_db=15.0)
        tracker.start(amplitude=80)
        tracker.reset()
        tracker.start(amplitude=70)    # fresh start
        tracker.update(50)             # 50 <= 70-15=55 → fires
        assert len(results) == 1, "Should emit after fresh start following reset()"
