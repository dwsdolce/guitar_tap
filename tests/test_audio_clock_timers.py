# @parity test/audio-clock-timers
"""The tap lifecycle's delays run on the AUDIO clock, not the wall clock (#19).

File playback advances audio at "real time + processing time", so a wall-clock delay covered a
different stretch of audio on a slower run and late captures in a sequence moved.

Each case here advances only audio — through _on_rms_level_changed, the path audio takes — and no
wall time to speak of, so a delay that went back to the wall clock would not have fired and the case
fails. The guitar rest (T1) and the capture window (T5) are pinned by the scenario traces'
midCooldown / postReArm / postProcess rows; this file pins what nothing else did.

Paired with Swift GuitarTapTests/AudioClockTimerTests.swift and web test/audio-clock-timers.test.ts.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6 import QtWidgets  # noqa: E402

from audio_clock_feed import advance_audio  # noqa: E402
from guitar_tap.models.material_tap_phase import MaterialTapPhase  # noqa: E402
from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402


def _get_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _make_sut(meas_type: MeasurementType, number_of_taps: int, measure_flc: bool = False) -> TapToneAnalyzer:
    _get_app()
    TapDisplaySettings.set_measurement_type(meas_type)
    TapDisplaySettings.set_measure_flc(measure_flc)
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.freq = np.linspace(0, 24000, 65536 // 2 + 1)
    sut.mic = RealtimeFFTAnalyzer(parent=None, for_testing=True)  # the capture's FFT engine
    return sut


def _tap_samples(hz: float, count: int) -> np.ndarray:
    """A decaying tone — a tap's ring-out."""
    t = np.arange(count) / 48000.0
    return (0.5 * np.exp(-t * 6) * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _spec():
    """A material spectrum whose presence is all accept_current_phase needs."""
    return (np.full(64, -60.0), np.arange(64) * 30.0)


def _restore():
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    TapDisplaySettings.set_measure_flc(False)


class TestAudioClockTimers:
    """Mirrors Swift AudioClockTimerTests."""

    def test_plate_rest_between_taps_runs_on_the_audio_clock(self):
        """T2: between taps of one plate/brace phase, detection rests tap_cooldown of audio."""
        sut = _make_sut(MeasurementType.PLATE, 2)
        try:
            sut.tap_detection_threshold = -90.0   # accept the synthetic tap
            sut.start_tap_sequence()
            # A detected tap, as detection delivers it: detection stops and the gated capture opens...
            sut._handle_tap_detection(np.array([]), np.array([]), sut.last_audio_time)
            # ...and the capture completes through the real path.
            sut.finish_gated_fft_capture(_tap_samples(60.0, 24_000), 48000.0,
                                         MaterialTapPhase.CAPTURING_LONGITUDINAL)
            assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL, \
                "1 of 2 taps — the phase is not done"
            assert not sut.is_detecting, "resting after the tap"

            advance_audio(sut, sut.tap_cooldown / 2)
            assert not sut.is_detecting, "halfway through the rest, in audio"

            advance_audio(sut, sut.tap_cooldown / 2)
            assert sut.is_detecting, "re-armed once the rest's audio has passed"
        finally:
            _restore()

    def test_flc_hold_runs_on_the_audio_clock(self):
        """T3: after C is accepted, the FLC phase arms tap_cooldown of audio later — anchored on the
        chunk that made the hold due."""
        sut = _make_sut(MeasurementType.PLATE, 1, measure_flc=True)
        try:
            sut.longitudinal_spectrum = _spec()
            sut.cross_spectrum = _spec()
            sut._set_material_tap_phase(MaterialTapPhase.REVIEWING_CROSS)

            sut.accept_current_phase()
            assert sut.material_tap_phase == MaterialTapPhase.WAITING_FOR_FLC_TAP

            advance_audio(sut, sut.tap_cooldown / 2)
            assert sut.material_tap_phase == MaterialTapPhase.WAITING_FOR_FLC_TAP, \
                "halfway through the hold, in audio"
            assert not sut.is_detecting

            advance_audio(sut, sut.tap_cooldown / 2)
            assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_FLC
            assert sut.is_detecting
            assert sut.warmup_start_audio_time == sut.last_audio_time, \
                "the FLC warm-up starts at the audio time of the chunk that ended the hold"
        finally:
            _restore()

    def test_file_end_releases_the_pending_capture_window(self):
        """File end: the capture window is released at once, so a measurement whose last capture ends
        with the file still completes — the audio clock stops with the file."""
        sut = _make_sut(MeasurementType.GENERIC, 1)
        sut.start_tap_sequence()
        sut.finish_guitar_gated_capture(_tap_samples(100.0, sut.mic.fft_size), 48000.0)
        assert not sut.is_measurement_complete, "the capture window is pending"

        sut._flush_gated_capture_on_file_end()
        QtWidgets.QApplication.processEvents()   # the release is queued behind the flush's finish
        assert sut.is_measurement_complete, "released at file end, with no further audio"

    def test_file_end_does_not_release_a_pending_rest(self):
        """File end does NOT release a rest: with no audio there is nothing to detect, so the re-arm
        waits for audio like any other."""
        sut = _make_sut(MeasurementType.GENERIC, 2)
        sut.start_tap_sequence()
        sut.finish_guitar_gated_capture(_tap_samples(100.0, sut.mic.fft_size), 48000.0)

        sut._flush_gated_capture_on_file_end()
        QtWidgets.QApplication.processEvents()
        assert not sut.is_detecting, "file end left the rest pending"

        advance_audio(sut, sut.tap_cooldown)
        assert sut.is_detecting, "the rest still ends when its audio has passed"

    def test_a_detected_tap_turns_detection_off(self):
        """A detected tap turns detection off first, and it stays off through the capture — the rest
        (T2) then starts from the state the natives have always had. The tap is detected from fed
        audio."""
        from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS
        sut = _make_sut(MeasurementType.PLATE, 2)
        try:
            sut.start_tap_sequence()
            advance_audio(sut, sut.warmup_period + 0.1)             # the warm-up, on quiet audio
            assert sut.is_detecting
            advance_audio(sut, 2 * AUDIO_FEED_CHUNK_SECONDS, level=-10.0)   # a tap: two loud chunks
            assert not sut.is_detecting, "detection is off once the tap is detected"
        finally:
            _restore()

    def test_the_safety_timeout_closes_a_capture_the_audio_stopped_filling(self):
        """T6: a capture the audio stops filling is closed on the WALL clock — it exists for when the
        audio stops, and then the audio clock stops too. After it, detection rests and re-arms."""
        import time
        from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS
        sut = _make_sut(MeasurementType.PLATE, 1)
        try:
            sut.start_tap_sequence()
            advance_audio(sut, sut.warmup_period + 0.1)
            advance_audio(sut, 2 * AUDIO_FEED_CHUNK_SECONDS, level=-10.0)   # a tap opens the capture...
            QtWidgets.QApplication.processEvents()
            assert sut._gated_capture_active
            # ...and then no more audio arrives.
            deadline = time.monotonic() + 2.3
            while time.monotonic() < deadline:
                QtWidgets.QApplication.processEvents()
                time.sleep(0.01)
            assert not sut._gated_capture_active, "closed by the wall-clock safety timeout"

            advance_audio(sut, sut.tap_cooldown)
            assert sut.is_detecting, "and detection rests, then re-arms, as after any capture"
        finally:
            _restore()

    def test_the_safety_timeout_does_not_fire_while_audio_keeps_arriving(self):
        """T6 measures SILENCE, not time since the capture started: while audio keeps arriving —
        however slowly, as under throttled playback — it does not fire (#19)."""
        import time
        from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS
        sut = _make_sut(MeasurementType.PLATE, 1)
        try:
            sut.start_tap_sequence()
            advance_audio(sut, sut.warmup_period + 0.1)
            advance_audio(sut, 2 * AUDIO_FEED_CHUNK_SECONDS, level=-10.0)   # a tap opens the capture
            QtWidgets.QApplication.processEvents()
            assert sut._gated_capture_active
            # Slow audio: one quiet chunk every 0.4 s of wall time, for 2.8 s — longer than the 2 s timeout.
            for _ in range(7):
                deadline = time.monotonic() + 0.4
                while time.monotonic() < deadline:
                    QtWidgets.QApplication.processEvents()
                    time.sleep(0.01)
                advance_audio(sut, AUDIO_FEED_CHUNK_SECONDS)
            QtWidgets.QApplication.processEvents()
            assert sut._gated_capture_active, "audio kept arriving, so the capture is still open"
        finally:
            _restore()

    def test_file_playback_auto_advance_arms_the_next_phase_at_once_latched_above(self):
        """File playback's auto-advance: when a phase completes while a file plays, the next phase is
        listening at once, the latch ABOVE so the last tap's ring-out must fall before anything counts;
        the warm-up is not restarted."""
        sut = _make_sut(MeasurementType.PLATE, 1)
        try:
            sut.mic.is_playing_file = True
            sut.tap_detection_threshold = -90.0   # accept the synthetic tap
            sut.start_tap_sequence()
            warmup_anchor = sut.warmup_start_audio_time
            sut._handle_tap_detection(np.array([]), np.array([]), sut.last_audio_time)
            sut.finish_gated_fft_capture(_tap_samples(60.0, 24_000), 48000.0,
                                         MaterialTapPhase.CAPTURING_LONGITUDINAL)

            assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_CROSS, "L done — auto-advanced to C"
            assert sut.is_detecting, "listening at once"
            assert sut.is_above_threshold, "latched above: the ring-out must fall first"
            assert sut.warmup_start_audio_time == warmup_anchor, "the warm-up is not restarted"
        finally:
            _restore()

    def test_ring_out_tracking_stops_on_the_audio_clock(self):
        """T7: ring-out tracking stops once a chunk arrives decay_tracking_duration of audio after the
        tap, and that chunk is not applied."""
        sut = _make_sut(MeasurementType.GENERIC, 1)
        sut.start_decay_tracking(10.0)
        end = 10.0 + sut.decay_tracking_duration

        sut.track_decay_fast(-40.0, end - 0.01)
        assert sut.is_tracking_decay, "still inside the window"
        samples_before = len(sut.peak_magnitude_history)

        sut.track_decay_fast(-40.0, end)
        assert not sut.is_tracking_decay, "stopped by the audio clock alone"
        assert len(sut.peak_magnitude_history) == samples_before, "the stopping chunk is not applied"
