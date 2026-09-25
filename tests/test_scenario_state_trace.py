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

import os
import sys
import time
from dataclasses import dataclass

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from audio_clock_feed import advance_audio  # noqa: E402

from PySide6 import QtCore, QtWidgets

from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

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
    sut.warmup_start_audio_time = -2.0
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    sut.freq = np.linspace(0, 2000, 256)
    sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)  # the capture's FFT engine
    return sut


def _capture_tap(sut: TapToneAnalyzer) -> None:
    """Capture one tap through the REAL completion path (finish_guitar_gated_capture)."""
    t = np.arange(sut.mic.fft_size) / 48000.0
    sut.finish_guitar_gated_capture(
        (0.5 * np.exp(-t * 6) * np.sin(2 * np.pi * 100 * t)).astype(np.float32), 48000.0)


def _drain(ms: int = 50):
    app = _get_app()
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 5)


def _after_cooldown(sut: TapToneAnalyzer) -> None:
    advance_audio(sut, sut.tap_cooldown)


def _after_capture_window(sut: TapToneAnalyzer) -> None:
    advance_audio(sut, sut.capture_window)


# Every tap goes through the real finish_guitar_gated_capture, and the waits are the real ones — the tap
# cooldown before re-arming, the capture window before averaging — measured, as the app measures them, in
# AUDIO fed through _on_rms_level_changed (#19). The traces used to assign the "tap
# happened" state by hand, so their capture rows recorded what the TEST wrote; and S3/S4's postTap1 said
# detection was back on the instant a tap was captured, a path the app never takes (#17 F46). These
# traces are identical in Swift, Python and web.
class TestScenarioStateTrace:
    """Python parity for Swift ScenarioStateTraceTests."""

    def test_S1_clean_single_tap_guitar(self):
        sut = _make_sut(number_of_taps=1)
        trace = [_snap("init", sut)]
        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))
        _capture_tap(sut)
        trace.append(_snap("postCapture", sut))
        _after_capture_window(sut)                 # completion averages after the capture window
        trace.append(_snap("postProcess", sut))

        expected = [
            StateSnapshot("init",        False, False, False, 0, 0),
            StateSnapshot("postStart",   True,  False, False, 0, 0),
            StateSnapshot("postCapture", False, False, False, 1, 1),
            StateSnapshot("postProcess", False, False, True,  1, 1),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"

    def test_S2_spurious_tap_on_type_change_matches_clean_single_tap(self):
        # The stray DETECTION is simulated (it is the scenario); the capture that follows is real.
        sut = _make_sut(number_of_taps=1)
        trace = [_snap("init", sut)]
        sut.start_tap_sequence()              # triggered by type-change handler
        sut.detection_state = DetectionState.IDLE              # spurious tap fires immediately
        _drain()                              # drain any deferred work
        trace.append(_snap("postStart", sut))
        _capture_tap(sut)
        trace.append(_snap("postCapture", sut))
        _after_capture_window(sut)
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
        trace = [_snap("init", sut)]
        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))
        _capture_tap(sut)                          # tap 1: detection rests through the cooldown
        trace.append(_snap("postTap1", sut))
        advance_audio(sut, sut.tap_cooldown / 2)   # halfway: still resting
        trace.append(_snap("midCooldown", sut))
        advance_audio(sut, sut.tap_cooldown / 2)   # ...then re-arms
        trace.append(_snap("postReArm", sut))
        sut.pause_tap_detection()
        trace.append(_snap("postPause", sut))
        sut.resume_tap_detection()
        trace.append(_snap("postResume", sut))
        _capture_tap(sut)                          # tap 2
        _after_cooldown(sut)
        _capture_tap(sut)                          # tap 3 — the last
        _after_capture_window(sut)
        trace.append(_snap("postProcess", sut))

        expected = [
            StateSnapshot("init",        False, False, False, 0, 0),
            StateSnapshot("postStart",   True,  False, False, 0, 0),
            StateSnapshot("postTap1",    False, False, False, 1, 1),
            StateSnapshot("midCooldown", False, False, False, 1, 1),
            StateSnapshot("postReArm",   True,  False, False, 1, 1),
            StateSnapshot("postPause",   False, True,  False, 1, 1),
            StateSnapshot("postResume",  True,  False, False, 1, 1),
            StateSnapshot("postProcess", False, False, True,  3, 3),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"

    def test_S4_multi_tap_cancel(self):
        # Cancel is a restart — cancel_tap_sequence re-arms a fresh sequence (== New Tap):
        # is_detecting=True, is_measurement_complete=False, counts reset to 0.
        sut = _make_sut(number_of_taps=3)
        trace = [_snap("init", sut)]
        sut.start_tap_sequence()
        _drain()
        trace.append(_snap("postStart", sut))
        _capture_tap(sut)
        trace.append(_snap("postTap1", sut))
        advance_audio(sut, sut.tap_cooldown / 2)   # halfway: still resting
        trace.append(_snap("midCooldown", sut))
        advance_audio(sut, sut.tap_cooldown / 2)
        trace.append(_snap("postReArm", sut))
        sut.cancel_tap_sequence()
        _drain()
        trace.append(_snap("postCancel", sut))

        expected = [
            StateSnapshot("init",       False, False, False, 0, 0),
            StateSnapshot("postStart",  True,  False, False, 0, 0),
            StateSnapshot("postTap1",   False, False, False, 1, 1),
            StateSnapshot("midCooldown", False, False, False, 1, 1),
            StateSnapshot("postReArm",  True,  False, False, 1, 1),
            StateSnapshot("postCancel", True,  False, False, 0, 0),
        ]
        assert trace == expected, f"trace mismatch:\n  got: {trace}\n  exp: {expected}"
