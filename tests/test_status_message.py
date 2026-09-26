# @parity test/status-message
"""
Pins the analyzer's `status_message` to its canonical strings by DRIVING
TRANSITIONS on a real TapToneAnalyzer and asserting the field — the same behavior
the web pins in test/status-message.test.ts and Swift pins in StatusMessageTests.swift.
The three suites assert identical strings; only the per-platform driving differs
(as test_scenario_state_trace.py does for state tuples).

SCOPE: the state-reachable strings only.  Two families are intentionally NOT pinned:

1. Material phase-guidance — "Ready for fL tap", "Rotate 90° and tap for fC" — is now
   VISIBLE (OUT-1 fixed by the status state-machine alignment: the warm-up is silent).
   Pinned below by the "survives the warm-up" cases, which feed a warm-up frame and
   assert the guidance persists (these FAILED before the alignment — the warm-up
   overwrote them with "Initializing…"). The redo / FLC phase strings follow the same
   mechanism and are covered by the material accept/redo transitions.

2. Per-tap capture PROGRESS transients — "Tap n/N capturing...",
   "Tap n/N captured. Tap again...", "All taps captured. Processing...", the material
   "L/C/FLC tap n/N captured..." / review / "No resonance detected" strings — are pinned
   below, in TestCaptureProgressStrings.

   This used to say they were written too deep in the gated-capture pipeline for a
   state-driven suite to reach, and were covered by the file-playback regression tests.
   Neither held (#17 F29): those tests run the pipeline but assert no status at all, and
   the handlers take a spectrum and a peak, which test_frozen_peak_recalculation has always
   called directly.  The strings were pinned in no edition but web.
"""

from __future__ import annotations

import datetime
import os
import sys
import time
import uuid

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from audio_clock_feed import advance_audio  # noqa: E402

from PySide6 import QtWidgets

from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

CLIP = "⚠ Input clipping — reduce mic gain"

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make_sut(number_of_taps: int = 1,
              measurement_type: MeasurementType = MeasurementType.CLASSICAL) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.tap_detection_threshold = -40.0
    sut.warmup_start_audio_time = -2.0  # past the warm-up window
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(measurement_type)
    sut.detection_state = DetectionState.LISTENING
    sut.is_measurement_complete = False
    sut.freq = np.linspace(0, 2000, 256)
    return sut


def _fake_spectrum(n: int = 256, peak_db: float = -30.0):
    mags = np.full(n, -80.0)
    mags[n // 4] = peak_db
    freqs = np.linspace(0, 2000, n)
    return (mags, freqs, datetime.datetime.now())


def _settle(sut: TapToneAnalyzer, level: float = -80.0) -> None:
    """Arm the analyzer to its settled resting prompt.  start_tap_sequence now sets the
    guitar prompt (the warm-up is silent — it no longer writes status); the below-threshold
    warm-up frame then confirms the prompt persists through the warm-up.  Mirrors the Swift
    armAndSettle helper.  (level stays under the -40 dB threshold so no tap fires.)
    """
    sut.start_tap_sequence()
    sut.warmup_start_audio_time = -2.0
    sut.just_exited_warmup = True
    sut.detect_tap(level, 0.0, np.full(len(sut.freq), -80.0), sut.freq)


def _peak(freq: float, mag: float = -40.0) -> ResonantPeak:
    return ResonantPeak(id=str(uuid.uuid4()), frequency=freq, magnitude=mag,
                        quality=10.0, bandwidth=freq / 10.0)


def _spec():
    """A (magnitudes, frequencies) phase-spectrum tuple the finalisers unpack."""
    return (np.full(256, -80.0), np.linspace(0, 2000, 256))


class TestStatusMessage:

    def setup_method(self):
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
        TapDisplaySettings.set_measure_flc(False)

    # ── initial ─────────────────────────────────────────────────────────────
    def test_initial_is_canonical_begin_message(self):
        _get_app()
        assert TapToneAnalyzer().status_message == "Tap the guitar to begin"

    # ── guitar detection-loop resting prompts ───────────────────────────────
    def test_guitar_armed_single_tap_rests_at_tap_prompt(self):
        sut = _make_sut(1)
        _settle(sut)
        assert sut.status_message == "Tap the guitar..."

    def test_guitar_armed_multi_tap_rests_at_count_prompt(self):
        sut = _make_sut(3)
        _settle(sut)
        assert sut.status_message == "Tap the guitar 3 times..."

    # ── clipping override / restore ─────────────────────────────────────────
    def test_clipping_overrides_and_restores_latest_real_status(self):
        sut = _make_sut(1)
        _settle(sut)
        assert sut.status_message == "Tap the guitar..."
        sut._set_clipping(True)
        assert sut.status_message == CLIP
        # A real write while clipping stays pinned to the warning but is stashed.
        sut.number_of_taps = 3
        _settle(sut)  # real write "Tap the guitar 3 times..."
        assert sut.status_message == CLIP
        sut._set_clipping(False)
        assert sut.status_message == "Tap the guitar 3 times..."

    # ── device change (route restart) — BEGIN only ──────────────────────────
    # The settled restore runs later, gated on the mic + a fresh frame, so it is not
    # reachable headless; it is covered at the integration level.
    def test_device_change_shows_reinitializing(self):
        sut = _make_sut(1)
        _settle(sut)
        sut.handle_route_change_restart()
        assert sut.status_message == "Audio device changed - reinitializing..."

    # ── paused / resume ─────────────────────────────────────────────────────
    def test_paused_then_resume_restores_prompt(self):
        sut = _make_sut(1)
        _settle(sut)
        sut.pause_tap_detection()
        assert sut.status_message == "Detection paused – tap freely, then resume"  # en-dash
        sut.resume_tap_detection()
        assert sut.status_message == "Tap the guitar..."

    # ── completion — announced once, FROZEN across a Peak-Min recalc ─────────
    def test_completion_announced_once_frozen_across_recalc(self):
        sut = _make_sut(2)
        sut.captured_taps = [_fake_spectrum(), _fake_spectrum()]
        sut.current_tap_count = 2
        sut.detection_state = DetectionState.IDLE
        sut._finish_capture()
        announced = sut.status_message
        assert announced.startswith("Analysis complete! ")
        assert announced.endswith(" (from 2 averaged taps).")
        # A Peak-Min recompute must NOT re-announce.
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.status_message == announced

    # ── loaded measurement (frozen) ─────────────────────────────────────────
    def test_loaded_measurement_shows_frozen_loaded_prompt(self):
        from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
        from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

        sut = _make_sut(1)
        sut.captured_taps = [_fake_spectrum()]
        sut.is_measurement_complete = True
        freqs = list(np.linspace(0, 2000, 64))
        mags = list(_fake_spectrum(n=64)[0])
        snap = SpectrumSnapshot(frequencies=freqs, magnitudes=mags,
                                measurement_type="Classical Guitar")
        m = TapToneMeasurement.create(measurement_type="Classical Guitar", guitar_type=None,
                                      peaks=[], spectrum_snapshot=snap, number_of_taps=1)
        sut.load_measurement(m)
        loaded = "Loaded measurement (frozen). Press ‘New Tap’ to start a new measurement."
        assert sut.status_message == loaded
        # A recalc on the loaded measurement must NOT re-announce "Analysis complete".
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.status_message == loaded

    # ── material completion (warm-up-independent: no re-arm after complete) ──
    def test_plate_complete_no_flc_lists_fl_and_fc(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        TapDisplaySettings.set_measure_flc(False)
        sut.longitudinal_spectrum = _spec()
        sut.cross_spectrum = _spec()
        sut.selected_longitudinal_peak = _peak(100.0)
        sut.selected_cross_peak = _peak(200.0)
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_CROSS)
        sut.accept_current_phase()  # no FLC → _finalise_plate_no_flc
        assert sut.status_message == "Complete — fL: 100.0 Hz, fC: 200.0 Hz"  # em-dash

    def test_plate_complete_with_flc_shows_check_results(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        TapDisplaySettings.set_measure_flc(True)
        sut.longitudinal_spectrum = _spec()
        sut.cross_spectrum = _spec()
        sut.flc_spectrum = _spec()
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_FLC)
        sut.accept_current_phase()  # → _finalise_plate_with_flc
        assert sut.status_message == "Complete - check Results"  # ASCII hyphen

    # ── OUT-1 fixed: material phase-guidance survives the (now silent) warm-up ──
    # Each phase-arm restarts the warm-up; feed a warm-up frame and assert the guidance
    # persists. These FAILED before the state-machine alignment (the warm-up overwrote
    # them with "Initializing…" → "Tap the guitar…").
    def test_material_arm_ready_for_l_tap_survives_warmup(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        sut.start_tap_sequence()  # plate → "Ready for fL tap"
        assert sut.status_message == "Ready for fL tap"
        sut.warmup_start_audio_time = 0.0  # warm-up active
        sut.just_exited_warmup = False
        sut.detect_tap(-80.0, 0.0, np.full(len(sut.freq), -80.0), sut.freq)  # a warm-up frame
        assert sut.status_message == "Ready for fL tap"

    def test_accept_l_rotate90_survives_warmup(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)
        sut.accept_current_phase()  # → "Rotate 90° and tap for fC" + warm-up restart
        assert sut.status_message == "Rotate 90° and tap for fC"
        sut.warmup_start_audio_time = 0.0  # warm-up active
        sut.just_exited_warmup = False
        sut.detect_tap(-80.0, 0.0, np.full(len(sut.freq), -80.0), sut.freq)  # a warm-up frame
        assert sut.status_message == "Rotate 90° and tap for fC"

    def test_accept_c_prompts_to_set_up_for_flc_and_survives_warmup(self):
        """The OTHER accept transition: fC → the FLC set-up prompt, shown during the disarmed cooldown.

        Web covered both accepts in one case; the natives covered only the first, so this string was
        asserted in no edition but web (#17 F29).  It is the prompt the FLC cooldown guard hands the
        user while detection is deliberately off.
        """
        saved = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = _make_sut(1, MeasurementType.PLATE)
            sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_CROSS)
            sut.accept_current_phase()
            assert sut.status_message == "Set up for fLC tap, then tap"
            sut.warmup_start_audio_time = 0.0  # warm-up active
            sut.just_exited_warmup = False
            sut.detect_tap(-80.0, 0.0, np.full(len(sut.freq), -80.0), sut.freq)
            assert sut.status_message == "Set up for fLC tap, then tap"
        finally:
            TapDisplaySettings.set_measure_flc(saved)

# ---------------------------------------------------------------------------
# Capture-progress strings (#17 F29)
# ---------------------------------------------------------------------------
#
# These were excluded on the grounds that they are written deep in the gated-capture pipeline and
# are "produced by" the file-playback regression tests.  Those tests run the pipeline, so the
# strings are certainly set — but status_message is asserted in exactly two test files here, and
# neither is one of them: deleting "No signal detected — tap again" left both native suites green.
# Web pinned them all along, which is why the slug read 12/12/16 as though web carried extras.
#
# Each case drives a method another test file already calls without audio.

class TestCaptureProgressStrings:
    """Mirrors Swift StatusMessageCaptureProgressTests."""

    @staticmethod
    def _peak_spectrum(freq: float, min_hz: float, max_hz: float):
        """A synthetic spectrum with one gaussian peak — enough for find_dominant_peak."""
        freqs = np.linspace(min_hz, max_hz, 512)
        mags = -80.0 + 50.0 * np.exp(-0.5 * ((freqs - freq) / 8.0) ** 2)
        return mags, freqs

    def test_guitar_loop_capturing_and_between_taps(self):
        sut = _make_sut(3)
        sut.current_tap_count = 0
        assert sut._guitar_loop_status(capturing=True) == "Tap 1/3 capturing..."
        sut.current_tap_count = 1
        assert sut._guitar_loop_status(capturing=False) == "Tap 1/3 captured. Tap again..."
        sut.current_tap_count = 2
        # the last tap's provisional string announces processing, not 3/3 capturing
        assert sut._guitar_loop_status(capturing=True) == "All taps captured. Processing..."

    def test_redo_longitudinal_prompts_to_tap_again(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)
        sut.redo_current_phase()
        assert sut.status_message == "Ready for fL tap — tap again"

    def test_material_progress_counts_and_asks_for_another(self):
        sut = _make_sut(3, MeasurementType.BRACE)
        sut.min_frequency = 100
        sut.max_frequency = 1200
        mags, freqs = self._peak_spectrum(300, 100, 1200)
        dominant = sut.find_dominant_peak(
            magnitudes=mags, frequencies=freqs, min_hz=100, max_hz=1200,
            prefer_lowest_significant=False,
        )
        assert dominant is not None, "precondition: the synthetic tap has a dominant peak"
        sut.captured_taps = [(mags, freqs, 0.0)]  # Swift calls this materialCapturedTaps
        sut._handle_longitudinal_gated_progress(
            mags, freqs, dominant, min_hz=100, max_hz=1200, prefer_lowest=False,
        )
        assert sut.status_message == "fL tap 1/3 captured. Tap again..."

    def test_no_resonance_in_band_asks_to_tap_again(self):
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        sut = _make_sut(1, MeasurementType.PLATE)
        # The analyzer asks the engine for the gated transform, as Swift's does — give it a real one.
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)
        silence = np.zeros(24000, dtype=np.float32)
        sut.finish_gated_fft_capture(silence, 48000.0, MaterialTapPhase.CAPTURING_LONGITUDINAL)
        # a tap with nothing in band must prompt again, not advance
        assert sut.status_message.endswith("— tap again")
        assert not sut.captured_taps, "and it must not count toward the phase"

    def test_file_playback_announces_the_auto_advance(self):
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        sut = _make_sut(1, MeasurementType.PLATE)
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)
        sut.mic.is_playing_file = True
        sut.min_frequency = 100
        sut.max_frequency = 1200
        mags, freqs = self._peak_spectrum(300, 100, 1200)
        dominant = sut.find_dominant_peak(
            magnitudes=mags, frequencies=freqs, min_hz=100, max_hz=1200,
            prefer_lowest_significant=False,
        )
        assert dominant is not None
        sut.captured_taps = [(mags, freqs, 0.0)]
        sut._handle_longitudinal_gated_progress(
            mags, freqs, dominant, min_hz=100, max_hz=1200, prefer_lowest=False,
        )
        assert sut.status_message == "File: fL complete, capturing fC..."


class TestStatusMessageReArm:
    """The re-arm after a guitar tap's cooldown does not touch the status: the capture set the loop
    prompt and it stays, as in Swift and the web. Python used to rewrite it here, and to show
    "Tap N/M captured. Waiting for settle..." while the level was still high (#17 F45)."""

    def test_re_arm_leaves_status_as_the_capture_set_it(self):
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        sut = _make_sut(number_of_taps=3)
        sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)
        sut.start_tap_sequence()
        t = np.arange(sut.mic.fft_size) / 48000.0
        sut.finish_guitar_gated_capture(
            (0.5 * np.exp(-t * 6) * np.sin(2 * np.pi * 100 * t)).astype(np.float32), 48000.0)
        after_capture = sut.status_message
        assert after_capture == sut._guitar_loop_status(capturing=False)

        # The rest runs on the audio clock (#19); the audio is still ringing, above the falling
        # threshold, when the re-arm falls due.
        advance_audio(sut, sut.tap_cooldown, level=-20.0)
        assert sut.is_detecting, "re-armed"
        assert sut.status_message == after_capture, "the re-arm leaves the status alone"

