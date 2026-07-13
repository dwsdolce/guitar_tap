# @parity test/status-message
"""
Pins the analyzer's `status_message` to its canonical strings by DRIVING
TRANSITIONS on a real TapToneAnalyzer and asserting the field — the same behavior
the web pins in test/status-message.test.ts and Swift pins in StatusMessageTests.swift.
The three suites assert identical strings; only the per-platform driving differs
(as test_scenario_state_trace.py does for state tuples).

SCOPE: the state-reachable strings only.  Two families are intentionally NOT pinned:

1. Material phase-guidance — "Ready for L tap", "Rotate 90° and tap for C" — is now
   VISIBLE (OUT-1 fixed by the status state-machine alignment: the warm-up is silent).
   Pinned below by the "survives the warm-up" cases, which feed a warm-up frame and
   assert the guidance persists (these FAILED before the alignment — the warm-up
   overwrote them with "Initializing…"). The redo / FLC phase strings follow the same
   mechanism and are covered by the material accept/redo transitions.

2. Per-tap capture PROGRESS transients — "Tap n/N capturing...",
   "Tap n/N captured. Tap again...", "All taps captured. Processing...", the material
   "L/C/FLC tap n/N captured..." / review / "No resonance detected" strings — are
   written deep in the gated-capture pipeline and are produced by the file-playback +
   gated-capture regression tests running the real capture.  The web pins them
   directly because it has an explicit engine-state setter (setEngineState);
   Swift/Python set them imperatively mid-pipeline, so a state-driven suite can't
   reach them cleanly.
"""

from __future__ import annotations

import sys
import os
import time
import uuid
import datetime

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType
from models.material_tap_phase import MaterialTapPhase
from models.resonant_peak import ResonantPeak

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
    sut.hysteresis_margin = 5.0
    sut.warmup_start_audio_time = -2.0  # past the warm-up window
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(measurement_type)
    sut.is_detecting = True
    sut.is_detection_paused = False
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
        sut.is_detecting = False
        sut._finish_capture()
        announced = sut.status_message
        assert announced.startswith("Analysis complete! ")
        assert announced.endswith(" (from 2 averaged taps).")
        # A Peak-Min recompute must NOT re-announce.
        sut.recalculate_frozen_peaks_if_needed()
        assert sut.status_message == announced

    # ── loaded measurement (frozen) ─────────────────────────────────────────
    def test_loaded_measurement_shows_frozen_loaded_prompt(self):
        from models.tap_tone_measurement import TapToneMeasurement
        from models.spectrum_snapshot import SpectrumSnapshot

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
        sut.start_tap_sequence()  # plate → "Ready for L tap"
        assert sut.status_message == "Ready for L tap"
        sut.warmup_start_audio_time = 0.0  # warm-up active
        sut.just_exited_warmup = False
        sut.detect_tap(-80.0, 0.0, np.full(len(sut.freq), -80.0), sut.freq)  # a warm-up frame
        assert sut.status_message == "Ready for L tap"

    def test_accept_l_rotate90_survives_warmup(self):
        sut = _make_sut(1, MeasurementType.PLATE)
        sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_LONGITUDINAL)
        sut.accept_current_phase()  # → "Rotate 90° and tap for C" + warm-up restart
        assert sut.status_message == "Rotate 90° and tap for C"
        sut.warmup_start_audio_time = 0.0  # warm-up active
        sut.just_exited_warmup = False
        sut.detect_tap(-80.0, 0.0, np.full(len(sut.freq), -80.0), sut.freq)  # a warm-up frame
        assert sut.status_message == "Rotate 90° and tap for C"