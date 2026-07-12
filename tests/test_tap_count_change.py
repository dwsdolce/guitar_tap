# @parity test/tap-count-change
"""
Pins the model-level tap-count-change behavior: when the tap count changes while
armed-and-waiting for the first tap, the status prompt refreshes to the new count;
an idle change does nothing.  Python's set_tap_num mirrors Swift numberOfTaps.didSet
(and the web's TapToneAnalyzer.setNumberOfTaps).  The three suites assert identical
strings; only the per-platform trigger differs (Swift property didSet, Python/web a
setter method).

OUT-5: the "reduce the count mid-sequence -> finalise with the taps already captured"
branch has been REMOVED from Swift and Python (the web never had it).  The Taps stepper
is disabled from the first captured tap (currentTapCount > 0 && !isMeasurementComplete)
on every platform, so the count cannot change mid-sequence -- you cancel first.  The
branch was therefore unreachable, and being unreachable it had drifted three ways: Swift
deferred processing by captureWindow and averaged ALL captured taps; Python finalised
synchronously and TRUNCATED to the new count; the web did nothing.  Removed rather than
reconciled.  TestNoImplicitFinalise below pins the removal.
"""

from __future__ import annotations

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make_sut(number_of_taps: int = 1) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.tap_detection_threshold = -40.0
    sut.hysteresis_margin = 5.0
    sut.analyzer_start_time = time.monotonic() - 2.0
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    sut.is_detecting = False
    sut.is_detection_paused = False
    sut.is_measurement_complete = False
    sut.freq = np.linspace(0, 2000, 256)
    return sut


class TestTapCountChange:

    def setup_method(self):
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)

    # Raising the count while armed-and-waiting refreshes the prompt.
    def test_raising_count_while_armed_idle_refreshes_prompt(self):
        sut = _make_sut(1)
        sut.is_detecting = True     # armed, waiting for the first tap
        sut.captured_taps = []
        sut.set_tap_num(3)
        assert sut.status_message == "Tap the guitar 3 times..."

    # Lowering it back also refreshes (the regression the web's PC-4 fixed).
    def test_lowering_count_while_armed_idle_refreshes_prompt(self):
        sut = _make_sut(4)
        sut.is_detecting = True
        sut.captured_taps = []
        sut.set_tap_num(1)
        assert sut.status_message == "Tap the guitar..."

    # An idle change (before arming / a frozen loaded result) must NOT refresh.
    def test_changing_count_while_idle_does_not_refresh(self):
        sut = _make_sut(1)          # is_detecting = False
        before = sut.status_message
        sut.set_tap_num(5)
        assert sut.status_message == before

class TestNoImplicitFinalise:
    """OUT-5 — a count change with taps already in hand must NOT finalise the measurement.

    Guards the removal of the unreachable reduce-mid-sequence branch (see the module docstring).
    Before the removal, set_tap_num truncated captured_taps to the new count and called
    process_multiple_taps() synchronously; Swift deferred and averaged ALL of them.
    """

    def setup_method(self):
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)

    def _armed_with_taps(self, total: int, taps: int) -> TapToneAnalyzer:
        import datetime as _dt
        sut = _make_sut(total)
        mags = np.full(64, -60.0, dtype=np.float64)
        freqs = np.linspace(0, 2000, 64)
        sut.captured_taps = [(mags, freqs, _dt.datetime.now()) for _ in range(taps)]
        sut.current_tap_count = taps
        sut.is_detecting = True
        return sut

    def test_lowering_to_the_captured_count_does_not_complete(self):
        sut = self._armed_with_taps(4, 2)  # 2 of 4 captured

        sut.set_tap_num(2)  # count == captured — the old branch finalised here

        assert sut.is_measurement_complete is False
        assert sut.is_detecting is True
        assert len(sut.captured_taps) == 2  # not truncated, not averaged away

    def test_lowering_below_the_captured_count_does_not_complete_or_truncate(self):
        sut = self._armed_with_taps(4, 3)

        sut.set_tap_num(1)  # captured (3) > new total (1)

        assert sut.is_measurement_complete is False
        assert sut.is_detecting is True
        assert len(sut.captured_taps) == 3, "set_tap_num used to `del captured_taps[new_num:]`"

    def test_raising_the_count_keeps_captured_taps(self):
        sut = self._armed_with_taps(3, 2)

        sut.set_tap_num(5)

        assert sut.is_measurement_complete is False
        assert len(sut.captured_taps) == 2
        assert sut.number_of_taps == 5
