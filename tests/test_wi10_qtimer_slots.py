"""
WI-10 — QTimer.singleShot thread-delivery and slot-correctness tests.

Verifies that the callbacks formerly dispatched via threading.Timer +
QMetaObject.invokeMethod now fire correctly when scheduled with
QTimer.singleShot.

Two verification strategies are used:

1. THREAD DELIVERY (via processEvents):
   Schedule a QTimer.singleShot(0, slot) and call processEvents() to
   drain pending events on the current (main) thread.  If the slot ran,
   the state change it produces must be visible — proving that delivery
   occurred on the Qt event-loop thread (main).

2. SLOT CORRECTNESS (direct call):
   Call the timer-fired slot directly (the pattern used throughout the
   test suite) and assert the state it should produce.  This mirrors the
   approach in test_tap_detection.py and test_decay_tracking.py.
"""

from __future__ import annotations

import sys
import os
import time

import pytest
from PySide6 import QtCore, QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


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

        # _do_reenable_detection is one of the WI-10 refactored slots.
        # Set is_detecting=False first so the slot's effect is visible.
        sut.is_detecting = False
        sut.tap_detected = True

        QtCore.QTimer.singleShot(0, sut._do_reenable_detection)
        # Before processEvents — slot has not yet run.
        assert sut.is_detecting is False

        QtWidgets.QApplication.instance().processEvents()
        # Slot ran on the main thread and applied its state.
        assert sut.is_detecting is True
        assert sut.tap_detected is False


# ---------------------------------------------------------------------------
# Slot correctness — tap detection path (sites 4, 5, 6)
# ---------------------------------------------------------------------------

class TestTapDetectionSlots:
    """Verify the WI-10 refactored tap-detection slots apply correct state."""

    def _make(self):
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.measurement_type import MeasurementType
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
        sut = _make_sut()
        sut.tap_detection_threshold = -40.0
        sut.hysteresis_margin = 5.0
        sut.analyzer_start_time = time.monotonic() - 2.0
        sut.just_exited_warmup = False
        return sut

    def test_do_reenable_detection_sets_is_detecting_true(self):
        """_do_reenable_detection (site 6) enables detection after plate cooldown."""
        sut = self._make()
        sut.is_detecting = False
        sut.tap_detected = True
        # Simulate very quiet input so is_above_threshold should be False.
        sut._current_input_level_db = -80.0

        sut._do_reenable_detection()

        assert sut.is_detecting is True
        assert sut.tap_detected is False
        # Level (-80) < falling threshold (-45) → not above threshold.
        assert sut.is_above_threshold is False

    def test_do_reenable_guitar_sets_is_detecting_true(self):
        """_do_reenable_guitar (site 5) re-enables detection for guitar mode."""
        sut = self._make()
        sut.is_detecting = False
        sut.tap_detected = True
        sut._current_input_level_db = -80.0

        sut._do_reenable_guitar()

        assert sut.is_detecting is True
        assert sut.tap_detected is False

    def test_finish_capture_transitions_state(self):
        """_finish_capture (site 4) clears captured taps after processing.

        We seed captured_taps with synthetic data so _finish_capture can
        average them.  After the call the captured list must be cleared.
        """
        import numpy as np
        sut = self._make()
        sut.number_of_taps = 1
        sut.current_tap_count = 1

        # Seed captured_taps with a minimal valid entry so averaging succeeds.
        # Production code stores bare magnitude arrays (not tuples) — see
        # tap_tone_analyzer_tap_detection.py captured_taps.append(mag_y_db.copy()).
        mags = np.full(64, -60.0, dtype=np.float32)
        sut.captured_taps = [mags]

        # _finish_capture calls _average_captured_taps then clears captured_taps.
        sut._finish_capture()

        assert sut.captured_taps == [], (
            "_finish_capture must clear captured_taps after averaging"
        )


# ---------------------------------------------------------------------------
# Slot correctness — spectrum capture path (sites 2, 3)
# ---------------------------------------------------------------------------

class TestSpectrumCapturePhaseSlots:
    """Verify the WI-10 refactored phase-transition slots apply correct state."""

    def _make(self):
        sut = _make_sut()
        return sut

    def test_do_start_cross_arms_cross_grain_detection(self):
        """Accepting REVIEWING_LONGITUDINAL sets phase to CAPTURING_CROSS and enables detection.

        The dedicated _do_start_cross slot was inlined into accept_current_phase().
        The behaviour is unchanged: advancing from REVIEWING_LONGITUDINAL must set
        CAPTURING_CROSS and arm tap detection.
        """
        import numpy as _np
        # Use the bare 'models' import path to match the internal code's enum identity.
        # The analyzer imports MaterialTapPhase as 'from models.material_tap_phase import ...'
        # so we must use the same path to avoid the dual-import-path enum mismatch.
        from models.material_tap_phase import MaterialTapPhase
        sut = self._make()
        # Seed a minimal frozen spectrum so accept_current_phase doesn't crash
        sut.set_frozen_spectrum(_np.array([100.0]), _np.array([-40.0]))
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)

        sut.accept_current_phase()

        # Compare via .value to avoid enum identity issues from dual import paths.
        assert sut.material_tap_phase.value == "Capturing Cross-grain"
        assert sut.is_detecting is True

    def test_do_start_flc_arms_flc_detection(self):
        """_do_start_flc (site 3) sets phase to CAPTURING_FLC and enables detection."""
        sut = self._make()

        sut._do_start_flc()

        assert sut.material_tap_phase.value == "Capturing FLC"
        assert sut.is_detecting is True


# ---------------------------------------------------------------------------
# Slot correctness — decay tracking path (site 7)
# ---------------------------------------------------------------------------

class TestDecayTrackingTimerSlot:
    """Verify the WI-10 QTimer-based decay tracking timer."""

    def test_start_decay_tracking_creates_qtimer(self):
        """start_decay_tracking creates a QTimer (not threading.Timer)."""
        sut = _make_sut()
        sut.tap_peak_level = -30.0
        sut.start_decay_tracking()

        assert sut._decay_tracking_timer is not None
        assert isinstance(sut._decay_tracking_timer, QtCore.QTimer), (
            "_decay_tracking_timer must be a QTimer after WI-10 refactor"
        )
        assert sut._decay_tracking_timer.isSingleShot()
        assert sut.is_tracking_decay is True

        # Clean up.
        sut.stop_decay_tracking()

    def test_start_decay_tracking_cancels_previous_timer(self):
        """Calling start_decay_tracking twice stops the first QTimer."""
        sut = _make_sut()
        sut.tap_peak_level = -30.0
        sut.start_decay_tracking()
        first_timer = sut._decay_tracking_timer

        sut.tap_peak_level = -25.0
        sut.start_decay_tracking()
        second_timer = sut._decay_tracking_timer

        # The first timer must have been stopped (isActive() == False).
        assert not first_timer.isActive(), (
            "First QTimer must be stopped when start_decay_tracking is called again"
        )
        assert second_timer is not first_timer

        sut.stop_decay_tracking()

    def test_stop_decay_tracking_stops_timer(self):
        """stop_decay_tracking stops the QTimer and clears the reference."""
        sut = _make_sut()
        sut.tap_peak_level = -30.0
        sut.start_decay_tracking()
        timer = sut._decay_tracking_timer

        sut.stop_decay_tracking()

        assert sut.is_tracking_decay is False
        assert sut._decay_tracking_timer is None
        assert not timer.isActive()

    def test_stop_decay_tracking_via_timer_signal(self):
        """Timer signal → stop_decay_tracking via processEvents."""
        sut = _make_sut()
        sut.tap_peak_level = -30.0
        sut.start_decay_tracking()

        # Override the timer interval so we don't wait 3 s in the test.
        sut._decay_tracking_timer.stop()
        sut._decay_tracking_timer.setInterval(0)
        sut._decay_tracking_timer.start()

        QtWidgets.QApplication.instance().processEvents()

        assert sut.is_tracking_decay is False, (
            "stop_decay_tracking must have been called via the timer signal"
        )
