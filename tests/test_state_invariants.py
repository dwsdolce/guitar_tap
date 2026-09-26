# @parity test/state-invariants
"""
State-machine invariants for TapToneAnalyzer.

These tests don't drive a specific scenario — they verify that the analyzer's
state, after any sequence of operations, never enters a combination the design
forbids.

Mirror of GuitarTapTests/StateInvariantTests.swift.  If either side's set of
invariants changes, the other must follow.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from audio_clock_feed import advance_audio  # noqa: E402

from PySide6 import QtCore, QtWidgets

from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.material_tap_phase import MaterialTapPhase
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


def _make_sut(number_of_taps: int = 1, measurement_type=MeasurementType.GENERIC) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.tap_detection_threshold = -40.0
    sut.warmup_start_audio_time = -2.0
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(measurement_type)
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


def _tap_samples(freq_hz: float, count: int, sample_rate: float = 48000.0):
    """A decaying sinusoid — a synthetic tap with one resonance at freq_hz."""
    t = np.arange(count, dtype=np.float64) / sample_rate
    return (0.5 * np.exp(-t * 6.0) * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _pump_events(seconds: float) -> None:
    """Run the Qt event loop for `seconds`, so QTimer-scheduled work (the tap cooldown) fires."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


def state_invariant_violation(a: TapToneAnalyzer) -> str | None:
    """Return a string describing the first invariant violation found, or None.

    Keep this list in sync with Swift's stateInvariantViolation in
    GuitarTapTests/StateInvariantTests.swift.
    """
    is_guitar = TapDisplaySettings.measurement_type().is_guitar

    # I1: Guitar mode: is_detecting && is_measurement_complete is illegal.
    if is_guitar and a.is_detecting and a.is_measurement_complete:
        return "I1: is_detecting && is_measurement_complete is illegal in guitar mode"

    # I2: is_detection_paused implies actively-detecting context.
    if a.is_detection_paused and a.is_measurement_complete:
        return "I2: is_detection_paused && is_measurement_complete is illegal"

    # I3: captured_taps count must not exceed number_of_taps.
    if len(a.captured_taps) > a.number_of_taps:
        return f"I3: captured_taps ({len(a.captured_taps)}) > number_of_taps ({a.number_of_taps})"

    # I4: current_tap_count must match captured_taps count for guitar mode.
    if is_guitar and a.current_tap_count != len(a.captured_taps):
        return (
            f"I4: current_tap_count ({a.current_tap_count}) != "
            f"len(captured_taps) ({len(a.captured_taps)}) in guitar mode"
        )

    # I5: tap_progress must be in [0, 1].
    if a.tap_progress < 0 or a.tap_progress > 1:
        return f"I5: tap_progress ({a.tap_progress}) outside [0, 1]"

    # I6: During a plate/brace review phase, is_detecting must be false.
    if not is_guitar and a.material_tap_phase in (
        MaterialTapPhase.REVIEWING_LONGITUDINAL,
        MaterialTapPhase.REVIEWING_CROSS,
        MaterialTapPhase.REVIEWING_FLC,
    ):
        if a.is_detecting:
            return (
                "I6: is_detecting must be False during plate/brace review "
                f"(phase={a.material_tap_phase})"
            )

    return None


class TestStateInvariants:
    """Python parity for Swift StateInvariantTests."""

    def test_V1_fresh_analyzer_holds_invariants(self):
        sut = _make_sut()
        assert state_invariant_violation(sut) is None

    def test_V2_after_start_tap_sequence_holds_invariants(self):
        sut = _make_sut()
        sut.start_tap_sequence()
        assert state_invariant_violation(sut) is None

    def test_V3_after_single_tap_complete_holds_invariants(self):
        sut = _make_sut(number_of_taps=1)
        sut.start_tap_sequence()
        sut.detection_state = DetectionState.IDLE
        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        sut.process_multiple_taps()
        assert state_invariant_violation(sut) is None, (
            "Single-tap completion must leave the analyzer in a valid state"
        )

    def test_V4_mid_multi_tap_sequence_holds_invariants(self):
        """Reached through the REAL capture path (finish_guitar_gated_capture), not by assigning
        captured_taps / current_tap_count / detection_state by hand — that only tested the checker on
        a state the test invented (#17 F45). Checked resting through the cooldown, and re-armed."""
        sut = _make_sut(number_of_taps=3)
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)  # the capture's FFT engine
        sut.start_tap_sequence()
        sut.finish_guitar_gated_capture(_tap_samples(100.0, sut.mic.fft_size), 48000.0)
        assert len(sut.captured_taps) == 1
        assert not sut.is_detecting, "detection rests through the tap cooldown"
        assert state_invariant_violation(sut) is None, "mid-sequence, resting"

        advance_audio(sut, sut.tap_cooldown)   # the rest runs on the audio clock (#19)
        assert sut.is_detecting, "re-armed for the next tap once the cooldown has passed"
        assert state_invariant_violation(sut) is None, "mid-sequence, re-armed"

    def test_V5_after_cancel_holds_invariants(self):
        sut = _make_sut(number_of_taps=3)
        sut.start_tap_sequence()
        sut.cancel_tap_sequence()
        assert state_invariant_violation(sut) is None

    def test_V6_after_pause_holds_invariants(self):
        sut = _make_sut(number_of_taps=3)
        sut.start_tap_sequence()
        sut.pause_tap_detection()
        assert state_invariant_violation(sut) is None

    def test_V7_impossible_state_detecting_and_complete_is_flagged(self):
        """If this passes with violation == None, the checker itself has regressed."""
        sut = _make_sut(number_of_taps=1)
        sut.detection_state = DetectionState.LISTENING
        sut.is_measurement_complete = True
        assert state_invariant_violation(sut) is not None, (
            "Invariant checker must reject (is_detecting && is_measurement_complete) in guitar mode"
        )

    def test_V8_plate_review_phase_holds_invariants(self):
        """A plate capture reaches its REVIEW phase through the real gated path, and invariants hold
        there — including I6, which no guitar case can reach (#17 F45)."""
        sut = _make_sut(number_of_taps=1, measurement_type=MeasurementType.PLATE)
        try:
            sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)  # gated-FFT engine
            sut.tap_detection_threshold = -90.0  # accept the synthetic tap
            sut.start_tap_sequence()
            sut.finish_gated_fft_capture(_tap_samples(60.0, 24_000), 48000.0,
                                         MaterialTapPhase.CAPTURING_LONGITUDINAL)
            assert sut.material_tap_phase == MaterialTapPhase.REVIEWING_LONGITUDINAL
            assert not sut.is_detecting
            assert state_invariant_violation(sut) is None
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)

    # V9–V13: each invariant REPORTS its forbidden state. V7 did this for I1 alone (#17 F45).

    def test_I2_paused_and_complete_is_flagged(self):
        sut = _make_sut()
        sut.detection_state = DetectionState.PAUSED
        sut.is_measurement_complete = True
        assert (state_invariant_violation(sut) or "").startswith("I2")

    def test_I3_more_taps_than_requested_is_flagged(self):
        sut = _make_sut(number_of_taps=1)
        sut.captured_taps.extend([_fake_tap(), _fake_tap()])
        assert (state_invariant_violation(sut) or "").startswith("I3")

    def test_I4_count_out_of_step_with_taps_is_flagged(self):
        sut = _make_sut(number_of_taps=3)
        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 0
        assert (state_invariant_violation(sut) or "").startswith("I4")

    def test_I5_progress_out_of_range_is_flagged(self):
        sut = _make_sut()
        sut.tap_progress = 1.5
        assert (state_invariant_violation(sut) or "").startswith("I5")

    def test_I6_detecting_while_reviewing_is_flagged(self):
        sut = _make_sut(measurement_type=MeasurementType.PLATE)
        try:
            sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)
            sut.detection_state = DetectionState.LISTENING
            assert (state_invariant_violation(sut) or "").startswith("I6")
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)

