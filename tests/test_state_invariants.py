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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtCore, QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType
from models.material_tap_phase import MaterialTapPhase

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
    sut.hysteresis_margin = 5.0
    sut.analyzer_start_time = time.monotonic() - 2.0
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
        sut.is_detecting = False
        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        sut.process_multiple_taps()
        assert state_invariant_violation(sut) is None, (
            "Single-tap completion must leave the analyzer in a valid state"
        )

    def test_V4_mid_multi_tap_sequence_holds_invariants(self):
        sut = _make_sut(number_of_taps=3)
        sut.start_tap_sequence()
        sut.captured_taps.append(_fake_tap())
        sut.current_tap_count = 1
        sut.is_detecting = True   # schedule_guitar_re_enable result
        assert state_invariant_violation(sut) is None

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
        sut.is_detecting = True
        sut.is_measurement_complete = True
        assert state_invariant_violation(sut) is not None, (
            "Invariant checker must reject (is_detecting && is_measurement_complete) in guitar mode"
        )
