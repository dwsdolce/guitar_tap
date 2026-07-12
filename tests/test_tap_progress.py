# @parity test/tap-progress
"""Pins `total_plate_taps` + `tap_progress` + the CUMULATIVE material `current_tap_count`.

These are the values the status-bar tap/phase progress bar renders (Swift
`ProgressView(value: tap.tapProgress)`).

Why this suite exists: the web port's material `current_tap_count` used to RESET at every phase
advance, while Swift/Python count CUMULATIVELY across L -> C -> FLC.  The status text agreed by
coincidence (the web printed its per-phase count directly; Swift/Python subtract the completed
phases from the cumulative one), so nothing caught it -- until a progress bar was added, where the
web's bar would have refilled 0->100% on EVERY phase instead of filling once across the sequence.
Python had a matching latent bug in the VIEW: it recomputed the bar percentage from
`number_of_taps` instead of rendering `tap_progress`, pinning the bar at 100% from the end of
phase L onward.

The canonical model these tests lock down (Swift TapDetection:360 / Control:465-487):

    total_plate_taps = number_of_taps * (1 if brace else 3 if measure_flc else 2)
    tap_progress     = min(1.0, current_tap_count / (number_of_taps if guitar
                                                     else total_plate_taps))
    current_tap_count (material) is CUMULATIVE, and rebases to the PRIOR phases' taps on redo.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType
from models.material_tap_phase import MaterialTapPhase


_APP: "QtWidgets.QApplication | None" = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _spec():
    """A minimal (magnitudes, frequencies) spectrum tuple -- presence is all these tests need."""
    return (np.full(64, -60.0, dtype=np.float64), np.linspace(0, 2000, 64))


def _make(meas_type: MeasurementType, taps: int, measure_flc: bool = False) -> TapToneAnalyzer:
    _get_app()
    TapDisplaySettings.set_measurement_type(meas_type)
    TapDisplaySettings.set_measure_flc(measure_flc)
    sut = TapToneAnalyzer()
    sut.number_of_taps = taps
    return sut


# --------------------------------------------------------------------------- #
# total_plate_taps -- taps expected across ALL phases
# --------------------------------------------------------------------------- #

class TestTotalPlateTaps:
    def test_brace_is_number_of_taps(self):
        """Brace has a single (longitudinal) phase."""
        assert _make(MeasurementType.BRACE, 3).total_plate_taps == 3

    def test_plate_without_flc_is_twice_number_of_taps(self):
        """Plate without FLC: L + C."""
        assert _make(MeasurementType.PLATE, 3, measure_flc=False).total_plate_taps == 6

    def test_plate_with_flc_is_three_times_number_of_taps(self):
        """Plate with FLC: L + C + FLC."""
        assert _make(MeasurementType.PLATE, 3, measure_flc=True).total_plate_taps == 9


# --------------------------------------------------------------------------- #
# tap_progress -- the fraction the bar renders
# --------------------------------------------------------------------------- #

class TestTapProgress:
    def test_guitar_divides_by_number_of_taps(self):
        sut = _make(MeasurementType.CLASSICAL, 4)
        sut.current_tap_count = 1
        sut.tap_progress = min(1.0, sut.current_tap_count / sut.number_of_taps)
        assert sut.tap_progress == pytest.approx(0.25)

    def test_material_divides_by_total_plate_taps_not_number_of_taps(self):
        """The bar must fill ONCE across L->C->FLC, not once per phase.

        This is the assertion the web violated: with number_of_taps as the denominator, a
        cumulative count of 2 in a 2-tap plate reads 100% at the END OF PHASE L.
        """
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total_plate_taps = 6
        assert sut.total_plate_taps == 6

        # End of phase L: 2 of 6 taps done -> one third, NOT 100%.
        sut.current_tap_count = 2
        assert sut.current_tap_count / sut.total_plate_taps == pytest.approx(2 / 6)
        assert sut.current_tap_count / sut.number_of_taps == pytest.approx(1.0)  # the WRONG denominator

    def test_progress_is_clamped_to_one(self):
        sut = _make(MeasurementType.BRACE, 2)
        sut.current_tap_count = 5  # over-count
        assert min(1.0, sut.current_tap_count / sut.total_plate_taps) == 1.0


# --------------------------------------------------------------------------- #
# The counter must SURVIVE a phase advance -- drives the real gated-capture path
# --------------------------------------------------------------------------- #

def _tap_samples(freq_hz: float, sample_rate: float = 48000.0,
                 dur: float = 0.5, amp: float = 0.5):
    """A decaying sinusoid -- a synthetic tap with a single resonance at `freq_hz`."""
    n = int(sample_rate * dur)
    t = np.arange(n) / sample_rate
    env = np.exp(-t * 6.0)
    return (amp * env * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float64)


class TestCountSurvivesPhaseAdvance:
    """The regression the whole suite exists for.

    `current_tap_count` must be CUMULATIVE across L -> C -> FLC. Deriving it from
    `len(captured_taps)` looked right but silently restarted at 0 on every phase change,
    because `captured_taps` is the WITHIN-phase buffer and gets cleared at each phase
    completion. Symptoms: the status-bar progress bar reset to 0 each phase, and the plate
    label's `max(0, captured - (step - 1) * number_of_taps)` clamped to "Tap 0/N".

    This drives the REAL gated-capture path (finish_gated_fft_capture), which is the only
    way to catch it -- asserting the equations alone does not.
    """

    def test_count_accumulates_across_L_to_C(self):
        from models.realtime_fft_analyzer import RealtimeFFTAnalyzer

        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total_plate_taps = 6
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)  # gated-FFT engine
        sut.tap_detection_threshold = -90.0  # accept our synthetic taps
        sr = 48000.0

        # --- Phase L: two taps at 60 Hz (plate L band = 20-100 Hz) ---
        sut._set_material_tap_phase(MaterialTapPhase.CAPTURING_LONGITUDINAL)
        sut.finish_gated_fft_capture(_tap_samples(60.0, sr), sr,
                                     MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert sut.current_tap_count == 1
        assert sut.tap_progress == pytest.approx(1 / 6)

        sut.finish_gated_fft_capture(_tap_samples(60.0, sr), sr,
                                     MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert sut.current_tap_count == 2  # L complete
        assert sut.tap_progress == pytest.approx(2 / 6)

        # --- Accept L -> C: the count must NOT reset ---
        sut.accept_current_phase()
        assert sut.current_tap_count == 2, "accept must not reset the cumulative count"

        # --- Phase C: two taps at 150 Hz (plate C band = 40-220 Hz) ---
        # THE assertion: the 1st C tap is the 3rd tap of the sequence, not the 1st.
        sut.finish_gated_fft_capture(_tap_samples(150.0, sr), sr,
                                     MaterialTapPhase.CAPTURING_CROSS)
        assert sut.current_tap_count == 3, (
            "count restarted at the phase boundary — it must be cumulative "
            "(this is the bug: current_tap_count = len(captured_taps))"
        )
        assert sut.tap_progress == pytest.approx(3 / 6)

        sut.finish_gated_fft_capture(_tap_samples(150.0, sr), sr,
                                     MaterialTapPhase.CAPTURING_CROSS)
        assert sut.current_tap_count == 4
        assert sut.tap_progress == pytest.approx(4 / 6)


# --------------------------------------------------------------------------- #
# Redo rebases the cumulative count to the PRIOR phases (Swift Control:465-487)
# --------------------------------------------------------------------------- #

class TestRedoRebasesCumulativeCount:
    def test_redo_cross_keeps_longitudinal_taps_counted(self):
        """Redo C -> current_tap_count = l_count (= number_of_taps), NOT 0."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total = 6
        sut.longitudinal_spectrum = _spec()  # L was captured
        sut.current_tap_count = 4  # L (2) + C (2)
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_CROSS)

        sut.redo_current_phase()

        assert sut.current_tap_count == 2  # L's taps stay counted
        assert sut.tap_progress == pytest.approx(2 / 6)

    def test_redo_flc_keeps_longitudinal_and_cross_counted(self):
        """Redo FLC -> current_tap_count = lc_count (= number_of_taps * 2)."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total = 6
        sut.longitudinal_spectrum = _spec()
        sut.cross_spectrum = _spec()
        sut.current_tap_count = 6
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_FLC)

        sut.redo_current_phase()

        assert sut.current_tap_count == 4  # L + C stay counted
        assert sut.tap_progress == pytest.approx(4 / 6)

    def test_redo_longitudinal_resets_to_zero(self):
        """Nothing precedes L, so redoing it drops the count to 0."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)
        sut.longitudinal_spectrum = _spec()
        sut.current_tap_count = 2
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)

        sut.redo_current_phase()

        assert sut.current_tap_count == 0
        assert sut.tap_progress == 0.0