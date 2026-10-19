# @parity none — Qt's QTimer.singleShot delivery on the main thread, PySide6's own (Swift's deferred
# work is DispatchQueue.main.asyncAfter, the web's setTimeout). What the deferred steps do is tested
# in the shared cases (audio-clock-timers, measurement-complete, tap-progress).
"""
QTimer.singleShot delivery: a callback the analyzer schedules with QTimer.singleShot runs on the Qt
event loop's (main) thread — scheduled with a delay of 0, then drained with processEvents(), its
state change is visible.
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6 import QtCore, QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.detection_state import DetectionState  # noqa: E402


# ---------------------------------------------------------------------------
# Shared QApplication fixture
# ---------------------------------------------------------------------------

_APP: "QtWidgets.QApplication | None" = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make_sut():
    _get_app()
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer()


# ---------------------------------------------------------------------------
# Thread-delivery proof
# ---------------------------------------------------------------------------

class TestQTimerMainThreadDelivery:
    """Prove that QTimer.singleShot fires on the Qt main thread."""

    def test_singleshot_zero_fires_via_process_events(self):
        """A QTimer.singleShot(0, fn) fires when processEvents() is called.

        This demonstrates that the timer callback is queued on the Qt event
        loop (main thread), not on a background thread.
        """
        fired = []

        def _slot():
            fired.append(True)

        QtCore.QTimer.singleShot(0, _slot)
        assert fired == [], "Must not fire before processEvents"

        QtWidgets.QApplication.instance().processEvents()
        assert fired == [True], "Must fire exactly once after processEvents"

    def test_singleshot_on_qobject_slot_fires_via_process_events(self):
        """QTimer.singleShot targeting a QObject @Slot fires via processEvents."""
        sut = _make_sut()

        # _do_reenable_detection is one of the timer-fired slots.
        # Start from IDLE so the slot's effect is visible.
        sut.detection_state = DetectionState.IDLE

        QtCore.QTimer.singleShot(0, sut._do_reenable_detection)
        # Before processEvents — slot has not yet run.
        assert sut.is_detecting is False

        QtWidgets.QApplication.instance().processEvents()
        # Slot ran on the main thread and applied its state.
        assert sut.is_detecting is True
