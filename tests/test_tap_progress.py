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

The canonical model these tests lock down (Swift `totalPlateTaps` / `redoCurrentPhase`):

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
sys.path.insert(0, os.path.dirname(__file__))
from audio_clock_feed import advance_audio  # noqa: E402

from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

_APP: "QtWidgets.QApplication | None" = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make(meas_type: MeasurementType, taps: int, measure_flc: bool = False) -> TapToneAnalyzer:
    _get_app()
    TapDisplaySettings.set_measurement_type(meas_type)
    TapDisplaySettings.set_measure_flc(measure_flc)
    sut = TapToneAnalyzer.for_testing(sample_rate=48000)
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
    def test_guitar_progress_advances_by_number_of_taps(self):
        """A guitar measurement's bar advances by number_of_taps, through the real capture finish -- the
        place progress is decided. (This used to compute min(1, count / taps) in the test itself and
        assert that; the material denominator is asserted by the count-across-phases case below, and the
        clamp is unreachable in production -- #17 F51.) Mirrors Swift
        guitarProgressAdvancesByNumberOfTaps."""
        sut = TapToneAnalyzer.for_testing(sample_rate=48000)
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut.number_of_taps = 4
        sut.start_tap_sequence()
        assert sut.tap_progress == 0

        tap = _tap_samples(100.0, dur=sut.mic.fft_size / 48000.0)
        sut.finish_guitar_gated_capture(tap, 48000.0)
        assert sut.tap_progress == pytest.approx(0.25)
        sut.finish_guitar_gated_capture(tap, 48000.0)
        assert sut.tap_progress == pytest.approx(0.5)
        sut.finish_guitar_gated_capture(tap, 48000.0)
        assert sut.tap_progress == pytest.approx(0.75)

    def test_new_sequence_resets_the_bar(self):
        """A new sequence starts its bar at 0 -- a finished measurement's full bar does not carry into
        it. Mirrors Swift newSequenceResetsTheBar."""
        sut = _make(MeasurementType.GENERIC, 1)
        sut.start_tap_sequence()
        sut.finish_guitar_gated_capture(_tap_samples(100.0, dur=sut.mic.fft_size / 48000.0), 48000.0)
        advance_audio(sut, sut.capture_window)   # complete
        QtWidgets.QApplication.processEvents()
        assert sut.is_measurement_complete
        assert sut.tap_progress == 1.0

        sut.start_tap_sequence()                 # New Tap

        assert sut.tap_progress == 0


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


def _plate_reviewing_l(sut: TapToneAnalyzer) -> None:
    """A plate sequence driven to its first review through real taps at the capture finish: L tapped
    number_of_taps times. The phase and count are the app's, not the test's."""
    sut.start_tap_sequence()
    for _ in range(sut.number_of_taps):
        sut.finish_gated_fft_capture(_tap_samples(60.0), 48000.0, MaterialTapPhase.CAPTURING_LONGITUDINAL)


def _plate_reviewing_c(sut: TapToneAnalyzer) -> None:
    """On to C's review: Accept L, then C tapped number_of_taps times."""
    _plate_reviewing_l(sut)
    sut.accept_current_phase()
    for _ in range(sut.number_of_taps):
        sut.finish_gated_fft_capture(_tap_samples(150.0), 48000.0, MaterialTapPhase.CAPTURING_CROSS)


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
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total_plate_taps = 6
        sut.start_tap_sequence()                                 # capturing L, as the app arms it
        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL
        sr = 48000.0

        # --- Phase L: two taps at 60 Hz (plate L band = 20-100 Hz) ---
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

        # --- Accept C -> waiting for the FLC tap: L + C stay counted through the hold ---
        sut.accept_current_phase()
        assert sut.material_tap_phase == MaterialTapPhase.WAITING_FOR_FLC_TAP
        assert sut.current_tap_count == 4
        assert sut.tap_progress == pytest.approx(4 / 6)

    def test_brace_bar_fills_over_its_taps(self):
        """Brace has one phase: its count and bar fill over its taps, and the last tap completes it."""
        sut = _make(MeasurementType.BRACE, 2)  # total = 2
        sut.start_tap_sequence()
        sut.finish_gated_fft_capture(_tap_samples(150.0), 48000.0, MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert sut.current_tap_count == 1
        assert sut.tap_progress == pytest.approx(0.5)

        sut.finish_gated_fft_capture(_tap_samples(150.0), 48000.0, MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert sut.current_tap_count == 2
        assert sut.tap_progress == 1.0
        assert sut.is_measurement_complete


# --------------------------------------------------------------------------- #
# Redo rebases the cumulative count to the PRIOR phases
# --------------------------------------------------------------------------- #

class TestRedoRebasesCumulativeCount:
    """Each case reaches its review through real taps, real Accepts and -- for FLC -- the real hold,
    fed in audio; none sets a spectrum, a count or a phase by hand (#17 F51). Mirrors Swift
    RedoRebasesCumulativeCountTests."""

    def test_redo_cross_keeps_longitudinal_taps_counted(self):
        """Redo C -> current_tap_count = l_count (= number_of_taps), NOT 0."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total = 6
        _plate_reviewing_c(sut)
        assert sut.material_tap_phase == MaterialTapPhase.REVIEWING_CROSS
        assert sut.current_tap_count == 4  # L (2) + C (2)

        sut.redo_current_phase()

        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_CROSS
        assert sut.current_tap_count == 2  # L's taps stay counted
        assert sut.tap_progress == pytest.approx(2 / 6)

    def test_redo_flc_keeps_longitudinal_and_cross_counted(self):
        """Redo FLC -> current_tap_count = lc_count (= number_of_taps * 2)."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)  # total = 6
        _plate_reviewing_c(sut)
        sut.accept_current_phase()                   # -> waiting for the FLC tap
        advance_audio(sut, sut.tap_cooldown)         # the hold, in audio -> capturing FLC
        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_FLC
        for _ in range(2):
            sut.finish_gated_fft_capture(_tap_samples(60.0), 48000.0, MaterialTapPhase.CAPTURING_FLC)
        assert sut.material_tap_phase == MaterialTapPhase.REVIEWING_FLC
        assert sut.current_tap_count == 6

        sut.redo_current_phase()

        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_FLC
        assert sut.current_tap_count == 4  # L + C stay counted
        assert sut.tap_progress == pytest.approx(4 / 6)

    def test_redo_longitudinal_resets_to_zero(self):
        """Nothing precedes L, so redoing it drops the count to 0."""
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)
        _plate_reviewing_l(sut)
        assert sut.material_tap_phase == MaterialTapPhase.REVIEWING_LONGITUDINAL
        assert sut.current_tap_count == 2

        sut.redo_current_phase()

        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL
        assert sut.current_tap_count == 0
        assert sut.tap_progress == 0.0

# --------------------------------------------------------------------------- #
# FLC cooldown cancellation -- the re-arm must not fire into a restarted sequence
# --------------------------------------------------------------------------- #

class TestFlcCooldownCancellation:
    """Accepting fC schedules a cooldown, after which detection re-arms for the FLC tap.

    If the user restarts (Cancel / New Tap) before the cooldown elapses, that timer must not drag
    the fresh sequence into the FLC phase.  Swift shipped without this guard until #17: its
    timer (now ``afterAudio``, #19) cannot be cancelled and ``cancelTapSequence()``'s
    ``captureTimer.invalidate()`` does not reach the closure, so the re-arm fired into whatever was
    running 0.5 s later.  Python and the web have always guarded; this pins it in all three.
    """

    def test_restart_during_cooldown_does_not_rearm_flc(self):
        sut = _make(MeasurementType.PLATE, 1, measure_flc=True)
        _plate_reviewing_c(sut)                      # real taps and Accepts to C's review

        sut.accept_current_phase()
        assert sut.material_tap_phase == MaterialTapPhase.WAITING_FOR_FLC_TAP

        # The user cancels before the cooldown elapses.
        sut.cancel_tap_sequence()
        phase_after_restart = sut.material_tap_phase
        assert phase_after_restart != MaterialTapPhase.WAITING_FOR_FLC_TAP

        # The hold ends — in AUDIO (#19) — against the restarted sequence.
        advance_audio(sut, 0.8)

        assert sut.material_tap_phase == phase_after_restart
        assert sut.material_tap_phase != MaterialTapPhase.CAPTURING_FLC


# --------------------------------------------------------------------------- #
# Loading a measurement tears down an interrupted capture
# --------------------------------------------------------------------------- #

def _saved_measurement():
    """A saved classical measurement to load -- built as test_measurement_complete_transitions builds one."""
    from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    freqs = list(np.linspace(0, 2000, 64))
    mags = [-80.0] * 64
    mags[16] = -30.0
    snap = SpectrumSnapshot(frequencies=freqs, magnitudes=mags, measurement_type="Classical Guitar")
    return TapToneMeasurement.create(measurement_type="Classical Guitar", guitar_type=None, peaks=[],
                                     spectrum_snapshot=snap, number_of_taps=1)


class TestLoadTearsDownInterruptedCapture:
    """Loading a measurement while a capture is unfinished tears it down, so the progress bar and the
    Analyzing indicator do not linger over the loaded measurement. The sequence is driven for real; the
    load is the real load_measurement. Mirrors Swift LoadTearsDownInterruptedCaptureTests."""

    def test_abandoned_plate_sequence_resets_on_load(self):
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)
        _plate_reviewing_c(sut)
        sut.accept_current_phase()                   # -> waiting for the FLC tap
        assert sut.current_tap_count == 4
        assert sut.material_tap_phase == MaterialTapPhase.WAITING_FOR_FLC_TAP

        sut.load_measurement(_saved_measurement())

        assert sut.current_tap_count == 0
        assert sut.tap_progress == 0
        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE
        assert not sut.is_detecting
        assert sut.is_measurement_complete

    def test_load_while_detecting_stops_detection(self):
        sut = _make(MeasurementType.PLATE, 2, measure_flc=True)
        sut.start_tap_sequence()
        sut.finish_gated_fft_capture(_tap_samples(60.0), 48000.0, MaterialTapPhase.CAPTURING_LONGITUDINAL)
        advance_audio(sut, sut.tap_cooldown)         # the rest ends: listening for tap 2
        assert sut.is_detecting
        assert sut.current_tap_count == 1

        sut.load_measurement(_saved_measurement())

        assert not sut.is_detecting
        assert sut.current_tap_count == 0
        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE


# ---------------------------------------------------------------------------
# A later count change must not rewrite a finished measurement (#17 F34)
# ---------------------------------------------------------------------------


class TestTapProgressAfterCountChange:
    """tap_progress is STORED, written at each capture site (the last tap leaves it at 1) — so a
    completed measurement's bar records what was actually measured. Raising the tap count afterwards
    configures the NEXT measurement and must leave the finished one alone. Web derived it at render
    time instead, so a complete 1-tap measurement's full bar dropped to a third when Taps went to 3.
    The measurement is completed for real: one tap through the finish, then the capture window's audio.

    Mirrors Swift TapProgressAfterCountChangeTests.
    """

    def test_complete_measurement_keeps_full_bar_when_tap_count_raised(self):
        sut = _make(MeasurementType.GENERIC, 1)
        sut.start_tap_sequence()
        sut.finish_guitar_gated_capture(_tap_samples(100.0, dur=sut.mic.fft_size / 48000.0), 48000.0)
        advance_audio(sut, sut.capture_window)   # "All taps captured. Processing..." -> complete
        QtWidgets.QApplication.processEvents()
        assert sut.is_measurement_complete
        assert sut.tap_progress == 1.0

        sut.number_of_taps = 3  # configures the next measurement

        assert sut.tap_progress == 1.0, (
            "REGRESSION: tap_progress must be stored, not derived — a later count change cannot "
            "rewrite a finished measurement's bar"
        )
