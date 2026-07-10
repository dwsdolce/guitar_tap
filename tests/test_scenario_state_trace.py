# @parity test/scenario-trace
"""
Scenario state-trace tests for TapToneAnalyzer.

Each scenario drives the analyzer through a sequence of operations and captures
a snapshot of (is_detecting, is_detection_paused, is_measurement_complete,
current_tap_count, captured_taps_count) at each checkpoint.  The trace is
compared to a canonical expected trace hardcoded in this file.

The same canonical trace is hardcoded in
GuitarTapTests/ScenarioStateTraceTests.swift.  If either side changes its
expected trace, the other must follow — this is the cross-implementation
parity bar for state evolution, not just final outputs.
"""

from __future__ import annotations

from dataclasses import dataclass

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtCore, QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType


_APP = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


@dataclass(frozen=True)
class StateSnapshot:
    label: str
    is_detecting: bool
    is_detection_paused: bool
    is_measurement_complete: bool
    current_tap_count: int
    captured_taps_count: int


def _snap(label: str, a: TapToneAnalyzer) -> StateSnapshot:
    return StateSnapshot(
        label=label,
        is_detecting=a.is_detecting,
        is_detection_paused=a.is_detection_paused,
        is_measurement_complete=a.is_measurement_complete,
        current_tap_count=a.current_tap_count,
        captured_taps_count=len(a.captured_taps),
    )


def _make_sut(number_of_taps: int = 1) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.tap_detection_threshold = -40.0
    sut.hysteresis_margin = 5.0
    sut.analyzer_start_time = time.monotonic() - 2.0
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    sut.freq = np.linspace(0, 2000, 256)
    return sut


def _fake_tap(n: int = 64, peak_db: float = -30.0):
    """Match the captured_taps entry shape used by the Python analyzer:
    a (magnitudes, frequencies, datetime) tuple."""
    import datetime as _dt
    mags = np.full(n, -80.0, dtype=np.float32)
    mags[n // 4] = peak_db
    freqs = np.arange(n, dtype=np.float32) * 31.25
    return (mags, freqs, _dt.datetime.now())


def _drain(ms: int = 50):
    app = _get_app()
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 5)


class TestScenarioStateTrace:
    """Python parity for Swift ScenarioStateTraceTests."""

    def test_S1_clean_single_tap_guitar(self):
        sut = _make_sut(number_of_taps=1)
        trace = []
        trace.append(_snap("init", sut))

        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))

        sut.is_detecting = False               # handle_tap_detection effect
        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        trace.append(_snap("postCapture", sut))

        sut.process_multiple_taps()
        trace.append(_snap("postProcess", sut))

        expected = [
            StateSnapshot("init",        False, False, False, 0, 0),
            StateSnapshot("postStart",   True,  False, False, 0, 0),
            StateSnapshot("postCapture", False, False, False, 1, 1),
            StateSnapshot("postProcess", False, False, True,  1, 1),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"

    def test_S2_spurious_tap_on_type_change_matches_clean_single_tap(self):
        sut = _make_sut(number_of_taps=1)
        trace = []
        trace.append(_snap("init", sut))

        sut.start_tap_sequence()              # triggered by type-change handler
        sut.is_detecting = False              # spurious tap fires immediately
        _drain()                              # drain any deferred work
        trace.append(_snap("postStart", sut))

        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        trace.append(_snap("postCapture", sut))

        sut.process_multiple_taps()
        trace.append(_snap("postProcess", sut))

        expected = [
            StateSnapshot("init",        False, False, False, 0, 0),
            StateSnapshot("postStart",   False, False, False, 0, 0),
            StateSnapshot("postCapture", False, False, False, 1, 1),
            StateSnapshot("postProcess", False, False, True,  1, 1),
        ]
        assert trace == expected, (
            "REGRESSION: spurious-tap trace must end with is_detecting=False "
            "at every checkpoint; non-False at postStart would mean a "
            "deferred is_detecting=True path has been introduced in Python "
            "matching the Swift line-304 race."
        )

    def test_S3_multi_tap_pause_resume(self):
        sut = _make_sut(number_of_taps=3)
        trace = []
        trace.append(_snap("init", sut))

        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))

        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        sut.is_detecting = True               # schedule_guitar_re_enable result
        trace.append(_snap("postTap1", sut))

        sut.pause_tap_detection()
        trace.append(_snap("postPause", sut))

        sut.resume_tap_detection()
        trace.append(_snap("postResume", sut))

        sut.captured_taps = [_fake_tap(), _fake_tap(), _fake_tap()]
        sut.current_tap_count = 3
        sut.is_detecting = False
        sut.process_multiple_taps()
        trace.append(_snap("postProcess", sut))

        expected = [
            StateSnapshot("init",        False, False, False, 0, 0),
            StateSnapshot("postStart",   True,  False, False, 0, 0),
            StateSnapshot("postTap1",    True,  False, False, 1, 1),
            StateSnapshot("postPause",   False, True,  False, 1, 1),
            StateSnapshot("postResume",  True,  False, False, 1, 1),
            StateSnapshot("postProcess", False, False, True,  3, 3),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"

    def test_S4_multi_tap_cancel(self):
        # Cancel is a restart — cancel_tap_sequence re-arms a fresh sequence (== New Tap):
        # is_detecting=True, is_measurement_complete=False, counts reset to 0.
        sut = _make_sut(number_of_taps=3)
        trace = []
        trace.append(_snap("init", sut))

        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))

        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        sut.is_detecting = True
        trace.append(_snap("postTap1", sut))

        sut.cancel_tap_sequence()
        _drain()
        trace.append(_snap("postCancel", sut))

        expected = [
            StateSnapshot("init",       False, False, False, 0, 0),
            StateSnapshot("postStart",  True,  False, False, 0, 0),
            StateSnapshot("postTap1",   True,  False, False, 1, 1),
            StateSnapshot("postCancel", True,  False, False, 0, 0),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"
