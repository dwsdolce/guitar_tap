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
        sut.is_detecting = False

        # Drain any deferred work.  If start_tap_sequence ever grows a
        # deferred is_detecting=True assignment, the drain will expose it.
        _drain_event_loop()

        assert sut.is_detecting is False, (
            "PARITY GUARD: is_detecting must remain false after any deferred "
            "work in start_tap_sequence; re-asserting it would reintroduce "
            "the Swift line-304 race."
        )

    # R2: End-to-end repro of the iPad bug scenario.  Same final state
    # asserted as the Swift test: complete, not detecting, not paused.
    def test_spurious_tap_on_type_change_settles_to_complete_not_detecting(self):
        sut = _make_sut(number_of_taps=1)

        sut.start_tap_sequence()
        sut.is_detecting = False              # handle_tap_detection effect
        _drain_event_loop()
        sut.captured_taps.append(_fake_tap())  # gated capture finished
        sut.current_tap_count = 1
        sut.process_multiple_taps()

        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False, (
            "REGRESSION: is_detecting must be False once measurement completes"
        )
        assert sut.is_detection_paused is False

    # R3: Multi-tap variant.
    def test_spurious_tap_multi_tap_eventually_completes_cleanly(self):
        sut = _make_sut(number_of_taps=3)

        sut.start_tap_sequence()
        _drain_event_loop()

        sut.captured_taps = [_fake_tap(), _fake_tap(), _fake_tap()]
        sut.current_tap_count = 3
        sut.is_detecting = False
        sut.process_multiple_taps()

        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False
        assert sut.is_detection_paused is False

    # R4: Audio-queue gated-capture path regression.  Mirrors Swift R4 in
    # GuitarTapTests/StartTapSequenceRaceTests.swift.
    #
    # The _level_crossing_handler starts a gated capture directly without
    # ever calling handle_tap_detection, so is_detecting stays True through
    # the capture.  finish_guitar_gated_capture must clear it; without that,
    # process_multiple_taps would set is_measurement_complete=True with
    # is_detecting still True — the impossible state the Swift iPad bug
    # exhibited.  R1–R3 drove the model through the RMS path and missed
    # this; this test drives the audio-queue path explicitly.
    def test_R4_audio_queue_gated_capture_path_clears_is_detecting(self):
        import numpy as np
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer

        sut = _make_sut(number_of_taps=1)
        # finish_guitar_gated_capture reads self.mic.fft_size / window_fcn /
        # _calibration / _settings_lock to compute the FFT; attach a
        # non-running analyzer so those attributes are present.
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)
        sut.freq = np.linspace(0, 24000, sut.mic.fft_size // 2 + 1)

        sut.start_tap_sequence()

        # Do NOT call handle_tap_detection — that's the audio-queue path's
        # defining trait.
        assert sut.is_detecting is True, "post-start_tap_sequence: detection must be armed"

        fft_size = int(sut.mic.fft_size)
        samples = np.zeros(fft_size, dtype=np.float32)
        sut.finish_guitar_gated_capture(samples, 48000.0)

        assert sut.is_detecting is False, (
            "REGRESSION: finish_guitar_gated_capture must clear is_detecting so "
            "the audio-queue path doesn't leave the analyzer stuck in 'detecting' "
            "through measurement completion."
        )

        sut.process_multiple_taps()
        assert sut.is_measurement_complete is True
        assert sut.is_detecting is False
        assert sut.is_detection_paused is False
