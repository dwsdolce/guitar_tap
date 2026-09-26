# @parity test/tap-decisions
"""
The tap detector's decisions — the rising edge, the threshold the application configured, the
hysteresis latch and the re-arm rule, the warm-up and its sync frame, relative detection and its noise
floor — the gated capture's onset alignment, and what the audio pipeline delivers to the analyzer.

Every detector case feeds audio through ``_on_chunk_level``, the per-chunk entry audio takes, after
arming the way the app does: ``start_tap_sequence()``, then the warm-up on quiet audio. No case sets the
detector's state by hand. A tap has fired when a capture has started (``_gated_capture_active``) — the
one effect a tap has in both capture kinds; cases about the detector's state read that state. The same
cases, with the same numbers, are in Swift GuitarTapTests/TapDetectionTests.swift and web
test/tap-decisions.test.ts (#17 F50 item 3).

They used to call ``detect_tap`` directly with the warm-up, sync flag, detection state and latch set by
hand, and with a hysteresis margin of 5 dB, which production never has (it is 3 in all three editions).
"""

from __future__ import annotations

import sys, os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6 import QtCore, QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer


from audio_clock_feed import advance_audio, AUDIO_FEED_CHUNK_SECONDS  # noqa: E402
from guitar_tap.models.material_tap_phase import MaterialTapPhase  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _armed(threshold: float, meas_type: MeasurementType = MeasurementType.CLASSICAL) -> TapToneAnalyzer:
    """An analyzer armed the way the app arms it — warm-up included — with the threshold the app sets."""
    _get_app()
    TapDisplaySettings.set_measurement_type(meas_type)
    sut = TapToneAnalyzer.for_testing(sample_rate=48000)
    sut.tap_detection_threshold = threshold
    sut.start_tap_sequence()
    return sut


def _chunks(sut: TapToneAnalyzer, level: float, n: int) -> None:
    """Feed n chunks at level, each one chunk of audio after the last."""
    for _ in range(n):
        sut._on_chunk_level(level, sut.last_audio_time + AUDIO_FEED_CHUNK_SECONDS)


def _settled(sut: TapToneAnalyzer, level: float = -90.0) -> None:
    """Through the warm-up on quiet audio, and one chunk past it: the sync chunk sees quiet, so the latch
    is down and the detector is ready for a rising edge."""
    advance_audio(sut, sut.warmup_period + AUDIO_FEED_CHUNK_SECONDS, level=level)


def _latched_above(sut: TapToneAnalyzer) -> None:
    """Through the warm-up on quiet audio, then a LOUD first chunk after it: the sync chunk latches the
    detector above — the state between taps, a tap still sounding — without firing."""
    advance_audio(sut, sut.warmup_period - 0.001)
    _chunks(sut, -20.0, 1)


_CONFIRM = RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS


def _decaying_tone(hz: float, count: int):
    """A decaying tone — a tap's ring-out — at 48 kHz."""
    import numpy as np
    t = np.arange(count) / 48000.0
    return (0.5 * np.exp(-t * 6) * np.sin(2 * np.pi * hz * t)).astype(np.float32)


class TestDetectorDecisions:
    """Mirrors Swift TapDetectionTests, case for case."""

    @pytest.fixture(autouse=True)
    def _restore_measurement_type(self):
        yield
        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)

    def test_T1_rising_edge_fires_a_tap(self):
        """T1: a rising edge above the threshold is a tap."""
        sut = _armed(-40.0)
        _settled(sut)
        _chunks(sut, -35.0, _CONFIRM)
        assert sut._gated_capture_active, "a tap should start a capture after crossing the rising threshold"

    def test_T1b_the_tap_is_stamped_with_the_confirming_chunks_audio_time(self):
        """T1b: the tap is stamped with the AUDIO time of the chunk that confirmed it."""
        sut = _armed(-40.0)
        _settled(sut)
        _chunks(sut, -35.0, _CONFIRM)
        assert sut.decay_tap_audio_time == sut.last_audio_time, \
            "the tap's time is the confirming chunk's audio time"

    # T1c–T1e: the detector uses the threshold the APPLICATION configured — tap_detection_threshold, which
    # the slider writes. The web once left it behind in the engine's config, so the slider went dead and
    # detection sat at the -40 dB default (#17 F30).

    def test_T1c_below_the_configured_threshold_does_not_fire(self):
        """T1c: a level below the configured threshold, but above the -40 default, is not a tap."""
        sut = _armed(-30.0)
        _settled(sut)
        _chunks(sut, -35.0, _CONFIRM)
        assert not sut._gated_capture_active, (
            "a tap quieter than the configured threshold must not fire -- if this fails, the "
            "detector is not reading the configured value"
        )

    def test_T1d_above_the_configured_threshold_fires(self):
        """T1d: the control — a level above it fires, so T1c cannot pass by detecting nothing."""
        sut = _armed(-30.0)
        _settled(sut)
        _chunks(sut, -25.0, _CONFIRM)
        assert sut._gated_capture_active

    def test_T1e_the_same_tap_is_accepted_or_rejected_by_the_threshold(self):
        """T1e: the same tap, judged against two thresholds, is decided differently."""
        lenient = _armed(-50.0)
        _settled(lenient)
        _chunks(lenient, -45.0, _CONFIRM)
        assert lenient._gated_capture_active, "-45 clears a -50 threshold"

        strict = _armed(-35.0)
        _settled(strict)
        _chunks(strict, -45.0, _CONFIRM)
        assert not strict._gated_capture_active, "the same tap is too quiet for a -35 threshold"

    def test_T1f_a_ring_out_above_the_falling_threshold_is_not_a_new_tap(self):
        """T1f: the re-arm rule — while latched above, a ring-out that dips below the rising threshold but
        not below the falling one (threshold - margin) is the same tap still sounding, so its next rise
        is not a new tap. is_above_threshold is both the latch and the gate."""
        sut = _armed(-40.0)                  # rising -40, falling -43
        _latched_above(sut)
        _chunks(sut, -42.0, 3)               # below rising, ABOVE falling — still the same tap
        _chunks(sut, -20.0, 3)               # the decay swings back up
        assert not sut._gated_capture_active, \
            "a ring-out that never fell below the falling threshold must not be taken as a new tap"

    def test_T1g_a_dip_below_the_falling_threshold_re_arms(self):
        """T1g: the control — a dip below the falling threshold does re-arm, so T1f cannot pass by never
        firing."""
        sut = _armed(-40.0)
        _latched_above(sut)
        _chunks(sut, -60.0, 3)               # the signal genuinely settled
        _chunks(sut, -20.0, _CONFIRM)        # a real second strike
        assert sut._gated_capture_active

    def test_T2_below_the_threshold_does_not_fire(self):
        """T2: a level below the threshold is not a tap."""
        sut = _armed(-40.0)
        _settled(sut)
        _chunks(sut, -50.0, _CONFIRM)
        assert not sut._gated_capture_active, "a level below the threshold must not start a capture"

    def test_T3_the_warm_up_suppresses_detection(self):
        """T3: the warm-up suppresses detection."""
        sut = _armed(-40.0)
        _chunks(sut, -20.0, _CONFIRM)        # loud, but inside the warm-up
        assert sut.last_audio_time < sut.warmup_period
        assert not sut._gated_capture_active, "no tap during the warm-up"

    def test_T5_between_falling_and_rising_holds_the_latch(self):
        """T5: once latched above, a level between the falling and rising thresholds holds the latch."""
        sut = _armed(-40.0)                  # rising -40, falling -43
        _latched_above(sut)
        _chunks(sut, -42.0, 1)
        assert sut.is_above_threshold, "above the falling threshold, the latch holds"
        assert not sut._gated_capture_active, "no new tap"

    def test_T5b_below_the_falling_threshold_clears_the_latch(self):
        """T5b: a level below the falling threshold clears the latch."""
        sut = _armed(-40.0)
        _latched_above(sut)
        _chunks(sut, -50.0, 1)
        assert not sut.is_above_threshold, "below the falling threshold, the latch clears"

    def test_T6_plate_detection_is_relative_to_the_noise_floor(self):
        """T6: plate detection is RELATIVE to the noise floor. With the floor raised to -45 and the
        threshold at -40, the relative rising threshold is -35 — above the absolute one — so a -38 level,
        which the absolute rule fires on, is not a tap here, and -30 is. The plate is in a real capture
        phase, and the tap must start a capture."""
        guitar = _armed(-40.0)
        _settled(guitar)
        _chunks(guitar, -38.0, _CONFIRM)
        assert guitar._gated_capture_active, "the control: -38 clears the absolute -40 threshold"

        sut = _armed(-40.0, MeasurementType.PLATE)
        assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL
        _settled(sut, level=-45.0)           # the warm-up, then the floor re-anchors at -45
        assert sut.noise_floor_estimate == -45.0

        _chunks(sut, -38.0, 3)
        assert not sut._gated_capture_active, "-38 is below the relative threshold (-35): not a tap"

        _chunks(sut, -30.0, _CONFIRM)
        assert sut._gated_capture_active, "-30 clears the relative threshold: a capture starts"

    def test_T7_the_noise_floor_converges_toward_the_ambient_level(self):
        """T7: in plate mode the noise-floor estimate follows the ambient level while below the threshold."""
        sut = _armed(-40.0, MeasurementType.PLATE)
        _settled(sut, level=-60.0)           # the floor re-anchors at -60
        start = sut.noise_floor_estimate
        assert start == -60.0

        _chunks(sut, -55.0, 50)              # α = 0.05, 50 steps from -60 toward -55: ≈ -57.4
        assert sut.noise_floor_estimate > start, "the floor moves toward the ambient level"
        assert sut.noise_floor_estimate > -58.0, \
            f"after 50 chunks at -55 dB it is close to -55 (got {sut.noise_floor_estimate:.2f})"

    def test_T8_the_first_chunk_after_the_warm_up_syncs_the_latch(self):
        """T8: the first chunk after the warm-up syncs the latch from its level, and does not fire."""
        sut = _armed(-40.0)
        advance_audio(sut, sut.warmup_period - 0.001)   # every chunk still inside the warm-up
        assert sut.just_exited_warmup
        _chunks(sut, -30.0, 1)               # the first chunk after it — loud
        assert not sut.just_exited_warmup, "the sync chunk clears the flag"
        assert sut.is_above_threshold, "the latch is synced from the level"
        assert not sut._gated_capture_active, "the sync chunk does not fire"


    # The settle — the latched ring-out falling below the falling threshold — leaves the prompt alone.
    # It used to rewrite it with the GUITAR loop status whatever the mode, so a plate's
    # "fL tap 1/2 captured. Tap again..." became "Tap 1/2 captured. Tap again..." (#17 F50 item 7).

    def test_settle_leaves_a_plate_prompt_alone(self):
        sut = _armed(-40.0, MeasurementType.PLATE)
        sut.number_of_taps = 2
        _settled(sut, level=-60.0)
        _chunks(sut, -10.0, _CONFIRM)                    # a tap: the capture opens
        assert sut._gated_capture_active
        sut.finish_gated_fft_capture(_decaying_tone(60.0, 24_000), 48000.0,
                                     MaterialTapPhase.CAPTURING_LONGITUDINAL)
        QtWidgets.QApplication.processEvents()
        prompt = sut.status_message
        assert prompt.startswith("fL tap 1/2")
        advance_audio(sut, sut.tap_cooldown, level=-20.0)   # the rest ends while it still rings: latched above
        assert sut.is_detecting and sut.is_above_threshold
        _chunks(sut, -60.0, 3)                           # the ring-out falls: the settle
        assert not sut.is_above_threshold
        assert sut.status_message == prompt, "the settle must leave the plate prompt alone"

    def test_settle_leaves_a_guitar_prompt_alone(self):
        sut = _armed(-40.0)
        sut.number_of_taps = 2
        _settled(sut)
        _chunks(sut, -10.0, _CONFIRM)
        assert sut._gated_capture_active
        sut.finish_guitar_gated_capture(_decaying_tone(100.0, sut.mic.fft_size), 48000.0)
        QtWidgets.QApplication.processEvents()
        prompt = sut.status_message
        assert prompt == "Tap 1/2 captured. Tap again..."
        advance_audio(sut, sut.tap_cooldown, level=-20.0)
        assert sut.is_detecting and sut.is_above_threshold
        _chunks(sut, -60.0, 3)
        assert not sut.is_above_threshold
        assert sut.status_message == prompt

    # Arming and resuming (#17 F50 item 13). A new sequence seeds the noise floor from the current input
    # level — here from a chunk, the way the level reaches the analyzer — and -100 when the warm-up is
    # skipped.

    def test_start_seeds_the_noise_floor_from_the_input_level(self):
        _get_app()
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        sut = TapToneAnalyzer.for_testing(sample_rate=48000)
        _chunks(sut, -50.0, 1)               # the current input level
        sut.start_tap_sequence()
        assert sut.noise_floor_estimate == -50.0

        TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
        sut.start_tap_sequence(skip_warmup=True)
        assert sut.noise_floor_estimate == -100.0, "the warm-up skipped (guitar file playback)"

    def test_resume_restarts_the_tap_confirmation(self):
        """One chunk above the threshold before the pause and one after it do not make a tap. Swift and
        Python kept the count across the pause, so a single loud chunk after a resume could fire one."""
        sut = _armed(-40.0)
        _settled(sut)
        _chunks(sut, -35.0, 1)               # one chunk counted
        assert not sut._gated_capture_active
        sut.pause_tap_detection()
        sut.resume_tap_detection()
        _chunks(sut, -35.0, 1)               # one chunk after the resume
        assert not sut._gated_capture_active, "one chunk after the resume must not confirm a tap"
        _chunks(sut, -35.0, 1)
        assert sut._gated_capture_active, "two chunks do"

    def test_start_restarts_the_tap_confirmation(self):
        """A new sequence restarts the tap confirmation too: a chunk counted before it cannot help confirm
        its first tap."""
        sut = _armed(-40.0)
        _settled(sut)
        _chunks(sut, -35.0, 1)               # one chunk counted
        sut.start_tap_sequence()
        # No quiet chunk in between — one would reset the count by itself. (The engine's clock stays at 0
        # in a test, so the new warm-up, anchored to it, has already run; the same holds for a resume.)
        _chunks(sut, -35.0, 1)
        assert not sut._gated_capture_active, "one chunk of the new sequence must not confirm a tap"
        _chunks(sut, -35.0, 1)
        assert sut._gated_capture_active, "two chunks do"

    def test_resume_keeps_the_noise_floor_and_puts_the_latch_down(self):
        sut = _armed(-40.0, MeasurementType.PLATE)
        _latched_above(sut)
        floor = sut.noise_floor_estimate
        sut.pause_tap_detection()
        sut.resume_tap_detection()
        assert sut.noise_floor_estimate == floor, "the floor is left as it was"
        assert not sut.is_above_threshold, "the latch goes down"


# ---------------------------------------------------------------------------
# The gated capture's onset alignment
# ---------------------------------------------------------------------------

class TestOnsetAlignment:
    """Mirrors Swift onsetAlignment_placesTheTransientAtPreOnsetPlusBackup and the web's onset-alignment
    case. tap_tone_analyzer_spectrum_capture's tag names this suite as one of the gated capture's tests."""

    def test_onset_alignment(self):
        """The transient lands at the pre-onset position plus the backup, at full amplitude."""
        import numpy as np
        _get_app()
        sut = TapToneAnalyzer()
        buf = np.zeros(10000, dtype=np.float32)
        buf[5000] = 0.5   # a single transient after silence
        out = np.asarray(sut.align_capture_to_onset(buf, 4096, 1000))
        argmax = int(np.argmax(np.abs(out)))
        assert out.shape[0] == 4096
        assert argmax == 1032, "the pre-onset 1000, plus the onset backed up 32 samples"
        assert out[argmax] == pytest.approx(0.5, abs=1e-6)

    # The fallbacks: when the onset cannot be found, the start of the buffer, still window-sized — so the
    # tap reaches the transform at the same length as every other (same bin grid, same window gain).

    def test_onset_alignment_too_short(self):
        """A buffer too short for the noise estimate: its start, window-sized."""
        import numpy as np
        _get_app()
        sut = TapToneAnalyzer()
        buf = np.full(1000, 0.25, dtype=np.float32)   # shorter than the 2048-sample noise estimate
        out = np.asarray(sut.align_capture_to_onset(buf, 4096, 1000))
        assert out.shape[0] == 4096
        assert out[0] == pytest.approx(0.25) and out[999] == pytest.approx(0.25)
        assert out[1000] == 0 and out[4095] == 0, "zero-padded after the buffer"

    def test_onset_alignment_no_onset(self):
        """No onset: the start of the buffer, window-sized."""
        import numpy as np
        _get_app()
        sut = TapToneAnalyzer()
        # A level that never rises 10x above its own RMS: no onset.
        buf = (0.1 + 0.00001 * np.arange(10000)).astype(np.float32)
        out = np.asarray(sut.align_capture_to_onset(buf, 4096, 1000))
        assert out.shape[0] == 4096, "window-sized, not the whole buffer"
        assert out[0] == pytest.approx(buf[0]) and out[4095] == pytest.approx(buf[4095]), \
            "the start of the buffer"


# ---------------------------------------------------------------------------
# The pipeline delivers each level and each frame to the analyzer ONCE, exactly
# ---------------------------------------------------------------------------

class TestPipelineDeliversOnceAndExact:
    """What the analyzer receives from the audio pipeline — through the real process_raw_samples.

    Swift delivers each chunk's level once (rmsLevelHandler, called on the audio queue, hopping to
    the main thread — as Python's now does, #19) and each FFT frame once (a Combine sink on the main
    thread), both as Float dB. Python delivered both TWICE — a
    direct callback plus a Qt signal — with the level truncated to a whole-dB integer on the way,
    and a duplicate guard (on the level only) keyed to the mic's current sample count, which a late
    queued copy could slip past, doubling the "N consecutive chunks" confirmation (#17 F44).

    Python-only, because the risk is Python's: its outlets are Qt signals on its own processing thread,
    where each connect() ADDS a receiver and a replacement thread object would have none. Swift's
    rmsLevelHandler and the web's callbacks are single assignments, which a second assignment replaces.
    """

    @staticmethod
    def _sut() -> TapToneAnalyzer:
        _get_app()
        return TapToneAnalyzer.for_testing(sample_rate=48000)

    @staticmethod
    def _tone(rms_db: float, n: int = 1024):
        import numpy as np
        t = np.arange(n)
        amp = (10 ** (rms_db / 20.0)) * np.sqrt(2.0)  # sine peak whose RMS is rms_db
        return (amp * np.sin(2 * np.pi * 1000.0 * t / 48000.0)).astype(np.float32)

    def test_detection_receives_the_exact_float_level(self):
        """-37.6 dB must arrive as -37.6, not as int(62.4) - 100 = -38.0."""
        import math
        import numpy as np
        sut = self._sut()
        chunk = self._tone(-37.6)
        expected = 20.0 * math.log10(float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))))
        sut.mic.process_raw_samples(chunk)
        QtWidgets.QApplication.processEvents()  # the level is queued to the main thread (#19)
        assert sut._current_input_level_db == pytest.approx(expected, abs=1e-9)
        assert abs(sut._current_input_level_db - (-38.0)) > 0.1, "truncated to whole dB"

    def test_detection_runs_on_the_main_thread_when_the_chunk_is_processed_off_it(self):
        """A chunk processed on another thread reaches detection on the MAIN thread, as Swift's does
        (rmsLevelHandler hops with DispatchQueue.main.async). Detection used to run right there on the
        processing thread, while a capture's finish arrived on the main thread, so the audio time seen
        at a finish depended on thread timing (#19)."""
        import threading
        sut = self._sut()
        seen: list = []
        original = sut.track_decay_fast   # runs once per chunk delivered, after detection
        sut.track_decay_fast = lambda *a, **k: (seen.append(threading.current_thread()), original(*a, **k))
        worker = threading.Thread(target=lambda: sut.mic.process_raw_samples(self._tone(-50.0)))
        worker.start()
        worker.join()
        assert seen == [], "detection ran on the processing thread"
        QtWidgets.QApplication.processEvents()
        assert seen == [threading.main_thread()], f"detection ran on {seen}"

    def test_one_chunk_runs_detection_once(self):
        sut = self._sut()
        calls: list = []
        original = sut.track_decay_fast   # runs once per chunk delivered, after detection
        sut.track_decay_fast = lambda *a, **k: (calls.append(a), original(*a, **k))
        sut.mic.process_raw_samples(self._tone(-50.0))
        QtWidgets.QApplication.processEvents()  # deliver anything that was queued
        assert len(calls) == 1, f"detection ran {len(calls)} times for one chunk"

    def test_one_frame_is_analysed_once(self):
        sut = self._sut()
        frames: list = []
        sut.framerateUpdate.connect(lambda *a: frames.append(a))  # emitted once per on_fft_frame
        sut.mic.process_raw_samples(self._tone(-50.0, n=sut.mic.fft_size))
        QtWidgets.QApplication.processEvents()
        assert len(frames) == 1, f"one FFT frame was analysed {len(frames)} times"

    def test_the_started_processing_thread_reaches_the_analyzer_once(self):
        """Starting the processing thread the way the app does — FftCanvas.start_analyzer — leaves every
        receiver the analyzer connected at construction in place, each once: the clipping warning, the
        dead-input warning, and the FFT frame.

        The thread object carries the pipeline's Qt signals and is never replaced. It used to be replaced
        on a restart, and only some receivers were connected to the new object, so the clipping and
        dead-input warnings stopped reaching the analyzer — on a path the app never took, now removed
        (#17 F50 item 8). FftCanvas opens the audio device when constructed, so the view's real
        start_analyzer runs on a stand-in holding only what it uses.
        """
        import numpy as np
        from types import SimpleNamespace
        from guitar_tap.views.fft_canvas import FftCanvas

        sut = self._sut()
        view = SimpleNamespace(analyzer=sut, _overlay_label=SimpleNamespace(setVisible=lambda _v: None))
        assert not sut.mic.proc_thread.isRunning()
        try:
            FftCanvas.start_analyzer(view)
            assert sut.mic.proc_thread.isRunning()

            # Clipping, through the real per-chunk detection: a full-scale chunk.
            sut.mic.process_raw_samples(np.ones(1024, dtype=np.float32))
            QtWidgets.QApplication.processEvents()
            assert sut.is_clipping, "the clipping warning does not reach the analyzer"

            # Dead input, through the watchdog's real emitter.
            sut.mic._emit_input_appears_dead(True)
            QtWidgets.QApplication.processEvents()
            assert sut.input_appears_dead, "the dead-input warning does not reach the analyzer"

            # The frame, once.
            frames: list = []
            sut.framerateUpdate.connect(lambda *a: frames.append(a))
            sut.mic.process_raw_samples(self._tone(-50.0, n=sut.mic.fft_size))
            QtWidgets.QApplication.processEvents()
            assert len(frames) == 1, f"one FFT frame was analysed {len(frames)} times"
        finally:
            sut.mic.proc_thread.stop()
            sut.mic.proc_thread.wait(2000)
