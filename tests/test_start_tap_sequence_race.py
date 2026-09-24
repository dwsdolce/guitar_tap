# @parity test/start-tap-race
"""
Regression tests for the same race the Swift fix (TapToneAnalyzer+Control.swift
line 304) addressed.

In Swift, `startTapSequence()` armed detection synchronously and then enqueued
a DispatchQueue.main.async block that redundantly re-asserted
`isDetecting = true`, clobbering a legitimate `false` set by
`handleTapDetection` from the audio thread between the sync arming and the
async block running.  The fix removed the redundant assignment.

Python's `start_tap_sequence` is synchronous end-to-end, so the equivalent
race window does not exist here today.  These tests still belong in the
Python suite as a parity assertion: if anyone ever introduces a deferred
callback into `start_tap_sequence` that re-asserts `is_detecting`, these
tests will fail in exactly the way the Swift tests would have failed before
the fix.

Mirror of GuitarTapTests/StartTapSequenceRaceTests.swift.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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


def _drain_event_loop(ms: int = 50) -> None:
    """Process pending Qt events; mirrors Swift's Task.sleep to drain main queue.

    Python's start_tap_sequence is synchronous so this is mostly a no-op, but
    if a future change adds a QTimer / signal-slot deferred path the drain
    would surface the same race the Swift code had.
    """
    app = _get_app()
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 5)


class TestStartTapSequenceRace:
    """Python parity for Swift StartTapSequenceRaceTests."""

    # R1: After start_tap_sequence, a subsequent flip of is_detecting=False
    # must survive any deferred work in the function.  In Python today the
    # function is fully synchronous so this is a tautology, but the test
    # locks in the property — any future refactor that introduces a deferred
    # is_detecting=True assignment will fail here.
    def test_is_detecting_false_survives_any_deferred_work(self):
        sut = _make_sut(number_of_taps=1)

        sut.start_tap_sequence()
        assert sut.is_detecting is True, "start_tap_sequence must arm detection"

        # Simulate handle_tap_detection's effect on is_detecting.
        sut.detection_state = DetectionState.IDLE

        # Drain any deferred work.  If start_tap_sequence ever grows a
        # deferred is_detecting=True assignment, the drain will expose it.
        _drain_event_loop()

        assert sut.is_detecting is False, (
            "PARITY GUARD: is_detecting must remain false after any deferred "
            "work in start_tap_sequence; re-asserting it would reintroduce "
            "the Swift line-304 race."
        )

    # R2: End-to-end repro of the iPad bug scenario — spurious detection, then the capture completes
    # through the REAL path and the measurement completes on its own after the capture window. Same
    # final state as the Swift test: complete, not detecting, not paused. (The capture used to be
    # simulated by appending to captured_taps and calling process_multiple_taps by hand — #17 F48.)
    def test_spurious_tap_on_type_change_settles_to_complete_not_detecting(self):
        sut = _make_sut(number_of_taps=1)

        sut.start_tap_sequence()
        sut.detection_state = DetectionState.IDLE              # handle_tap_detection effect
        _drain_event_loop()
        _capture_tap(sut)
        _drain_event_loop(int((sut.capture_window + 0.3) * 1000))

        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False, (
            "REGRESSION: is_detecting must be False once measurement completes"
        )
        assert sut.is_detection_paused is False

    # R3: Multi-tap variant — three real captures, the real cooldowns, the real completion.
    def test_spurious_tap_multi_tap_eventually_completes_cleanly(self):
        sut = _make_sut(number_of_taps=3)

        sut.start_tap_sequence()
        _drain_event_loop()
        for tap in range(1, 4):
            _capture_tap(sut)
            if tap < 3:
                _drain_event_loop(int((sut.tap_cooldown + 0.3) * 1000))
        _drain_event_loop(int((sut.capture_window + 0.3) * 1000))

        assert sut.current_tap_count == 3
        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False
        assert sut.is_detection_paused is False

    # R4: Audio-queue gated-capture path regression.  Mirrors Swift R4 in
    # GuitarTapTests/StartTapSequenceRaceTests.swift.
    #
    # The _level_crossing_handler starts a gated capture directly without
    # ever calling handle_tap_detection, so is_detecting stays True through
    # the capture.  finish_guitar_gated_capture must clear it; without that,
    # the measurement would complete with is_detecting still True — the
    # impossible state the Swift iPad bug exhibited.  The measurement then
    # completes on its own: the capture schedules process_multiple_taps, and
    # calling it here as well ran it twice (#17 F48).
    def test_R4_audio_queue_gated_capture_path_clears_is_detecting(self):
        sut = _make_sut(number_of_taps=1)
        sut.freq = np.linspace(0, 24000, sut.mic.fft_size // 2 + 1)

        sut.start_tap_sequence()

        # Do NOT call handle_tap_detection — that's the audio-queue path's
        # defining trait.
        assert sut.is_detecting is True, "post-start_tap_sequence: detection must be armed"

        samples = np.zeros(int(sut.mic.fft_size), dtype=np.float32)
        sut.finish_guitar_gated_capture(samples, 48000.0)

        assert sut.is_detecting is False, (
            "REGRESSION: finish_guitar_gated_capture must clear is_detecting so "
            "the audio-queue path doesn't leave the analyzer stuck in 'detecting' "
            "through measurement completion."
        )

        _drain_event_loop(int((sut.capture_window + 0.3) * 1000))
        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False
        assert sut.is_detection_paused is False

    # R5: A restart from PAUSED must end LISTENING, not paused.
    #
    # start_tap_sequence used to clear the pause flag up front; with one detection state it
    # simply moves to LISTENING at the arming step, and nothing in between may leave PAUSED
    # standing. Cancel is the reachable route: the button rule DISABLES New Tap while paused
    # (a paused sequence is still in flight, B6) and ENABLES Cancel, which delegates to
    # start_tap_sequence in all three editions.
    def test_R5_restart_from_paused_ends_listening(self):
        sut = _make_sut(number_of_taps=3)

        sut.start_tap_sequence()
        sut.current_tap_count = 1
        sut.pause_tap_detection()
        assert sut.is_detection_paused is True, "precondition: the sequence is paused"

        sut.cancel_tap_sequence()

        assert sut.detection_state is DetectionState.LISTENING, (
            "REGRESSION: a restart from paused must arm; leaving it PAUSED strands the user "
            "with a sequence they cannot resume or restart."
        )
        assert sut.is_detection_paused is False
        assert sut.current_tap_count == 0
