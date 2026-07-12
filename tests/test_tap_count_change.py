# @parity test/tap-count-change
"""
Pins the model-level tap-count-change behavior: when the tap count changes while
armed-and-waiting for the first tap, the status prompt refreshes to the new count;
an idle change does nothing.  Python's set_tap_num mirrors Swift numberOfTaps.didSet
(and the web's TapToneAnalyzer.setNumberOfTaps).  The three suites assert identical
strings; only the per-platform trigger differs (Swift property didSet, Python/web a
setter method).

NOTE: the reduce-count-to-at-or-below-captured branch is intentionally NOT pinned
here — it is not part of the web's tap-count-change slug, and it diverges from Swift:
Swift sets "All taps captured. Processing..." and defers processing, whereas Python's
set_tap_num calls process_multiple_taps synchronously.  Tracked separately (6-TEST 4c).
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