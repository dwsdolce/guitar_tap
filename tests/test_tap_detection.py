# @parity test/tap-decisions
"""
Port of TapDetectionTests.swift — hysteresis, warmup, cooldown, EMA.

Mirrors Swift TapDetectionTests test suite (T1–T9; T4, the cooldown gate, removed in #19).

Strategy: detectTap() is a method on TapToneAnalyzer.  We manipulate its
internal guard state (warmup_start_audio_time, is_above_threshold)
directly so the method exercises pure logic without a real audio engine.
TapToneAnalyzer() is now constructible without audio hardware (Part 5).
"""

from __future__ import annotations

import sys, os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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


from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer


# ---------------------------------------------------------------------------
# Synthetic spectrum — sufficient for the detection path
# ---------------------------------------------------------------------------

_FAKE_MAGS: list[float] = [-80.0] * 64
_FAKE_FREQS: list[float] = [float(i) * 375 for i in range(64)]


# ---------------------------------------------------------------------------
# Helper: build a non-running TapToneAnalyzer in guitar mode
# with its warm-up period satisfied so detect_tap can fire.
# Mirrors Swift makeSUT().
# ---------------------------------------------------------------------------

def _make_sut(
    threshold: float = -40.0,
    hysteresis: float = 5.0,
    number_of_taps: int = 1,
) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.tap_detection_threshold = threshold
    sut.hysteresis_margin = hysteresis
    sut.number_of_taps = number_of_taps
    # Defeat the warmup guard by setting the start time 2 s in the past.
    # Mirrors Swift: sut.analyzerStartTime = Date(timeIntervalSinceNow: -2)
    import time as _t
    sut.warmup_start_audio_time = -2.0  # audio-seconds in the past
    # Defeat the post-warmup sync frame.
    sut.just_exited_warmup = False
    # Guitar mode (absolute threshold) — ensure measurement_type is acoustic.
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    return sut


# ---------------------------------------------------------------------------
# T1: Signal crossing rising threshold fires tap
# ---------------------------------------------------------------------------

class TestRisingEdge:
    """Mirrors Swift TapDetectionTests T1/T1b."""

    def test_T1_above_threshold_records_a_tap(self):
        """T1: Rising edge above threshold records a tap.

        These tests observe ``decay_tap_audio_time``, which a confirmed tap sets to its own audio time
        and nothing clears.  (They observed ``last_tap_time`` until #19 removed it with the cooldown
        gate it fed.)  They
        used to observe a ``tap_detected`` flag that existed on the analyzer for no other purpose:
        no view and no model logic read it in ANY edition -- Python had wired a status-dot flash to
        a signal that was never emitted, so even that never ran.  A production field kept alive to
        make tests observable is the application bending to the suite, so it was removed and the
        assertions moved onto state the app actually keeps (#17 F43).  It also reads better: the
        flag was true for ONE frame and the next frame cleared it, so a test feeding one chunk too
        many failed while the code was right.
        """
        sut = _make_sut(threshold=-40)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False

        # Rising edge fires after RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS
        # consecutive above-rising-threshold calls — see TapToneAnalyzer.detect_tap.
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            sut.detect_tap(level=-35, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is not None, "a tap should be recorded after crossing the rising threshold"

    # T1c-T1e: the detector must use the threshold the APPLICATION configured.
    #
    # The test/tap-decisions DSP cases pin the detection rule with the threshold handed to them as an
    # argument, which says nothing about whether the shipping path delivers the right number.
    # PARITY-TEST-METHOD rule 1 -- check what the APPLICATION passes, not what the test does.  Here
    # the application's path IS tap_detection_threshold on the analyzer: the slider writes it and
    # detect_tap reads it.  These pass in Python and Swift for that reason, and failed on the web,
    # where #17 F30 moved the detector onto the analyzer and left the threshold behind in the
    # engine's config -- the slider went dead and detection sat at the -40 dB default.

    def test_T1c_below_configured_threshold_does_not_fire(self):
        """A level BELOW the configured threshold must not fire."""
        sut = _make_sut(threshold=-30)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False

        # -35 is quieter than the configured -30 but LOUDER than the -40 default.  An edition that
        # ignores the configured value and falls back to its default fires here.
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            sut.detect_tap(level=-35, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is None, (
            "a tap quieter than the configured threshold must not fire -- if this fails, the "
            "detector is not reading the configured value"
        )

    def test_T1d_above_configured_threshold_fires(self):
        """The control -- so T1c cannot pass by detecting nothing at all."""
        sut = _make_sut(threshold=-30)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False

        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            sut.detect_tap(level=-25, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is not None

    def test_T1e_same_tap_decided_differently_by_the_threshold(self):
        """The same tap, judged against two thresholds, must be decided differently."""
        lenient = _make_sut(threshold=-50)
        lenient.detection_state = DetectionState.LISTENING
        lenient.is_above_threshold = False
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            lenient.detect_tap(level=-45, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        assert lenient.decay_tap_audio_time is not None, "-45 clears a -50 threshold"

        strict = _make_sut(threshold=-35)
        strict.detection_state = DetectionState.LISTENING
        strict.is_above_threshold = False
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            strict.detect_tap(level=-45, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        assert strict.decay_tap_audio_time is None, "the same tap is too quiet for a -35 threshold"

    def test_T1f_ring_out_above_falling_threshold_is_not_a_new_tap(self):
        """The re-arm rule -- a ring-out above the falling threshold is not a new tap.

        Between taps in a multi-tap sequence the detector sits LATCHED ABOVE with no capture
        running.  Hysteresis says the ring-out must fall below ``falling`` (threshold -
        hysteresis_margin) before anything counts as a new strike; a decay that dips past
        ``rising`` but stays above ``falling`` is the SAME tap still sounding.  Here
        ``is_above_threshold`` is both the latch and the gate, so while it is up no counting
        happens at all.  Web splits the two -- its latch is ``isAboveThreshold`` but firing is
        gated by ``prevAbove``, which clears as soon as the level drops below ``rising`` -- so a
        ring-out that never reaches ``falling`` re-arms it.  Paired with Swift T1f and web's
        "the re-arm rule" cases.
        """
        sut = _make_sut(threshold=-40)      # rising -40, falling -43
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = True       # fired, capture done, not yet settled

        for _ in range(3):                  # ring-out: below rising, ABOVE falling
            sut.detect_tap(level=-42, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        for _ in range(3):                  # the decay swings back up
            sut.detect_tap(level=-20, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is None, (
            "a ring-out that never fell below the falling threshold must not be taken as a new tap"
        )

    def test_T1g_dip_below_falling_threshold_does_rearm(self):
        """The control -- so T1f cannot pass by never firing at all."""
        sut = _make_sut(threshold=-40)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = True

        for _ in range(3):                  # the signal genuinely settled
            sut.detect_tap(level=-60, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            sut.detect_tap(level=-20, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is not None

    def test_T1b_tap_is_stamped_with_its_audio_time(self):
        """T1b: a detected tap is stamped with the AUDIO time of the chunk that confirmed it."""
        sut = _make_sut(threshold=-40)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False

        chunks = RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS
        for k in range(chunks):
            sut.detect_tap(level=-35, audio_time=2.0 + k * 0.02, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time == 2.0 + (chunks - 1) * 0.02, \
            "the tap's time is the confirming chunk's audio time"


# ---------------------------------------------------------------------------
# T2: Signal below threshold records no tap
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    """Mirrors Swift TapDetectionTests T2."""

    def test_T2_below_threshold_does_not_detect(self):
        """T2: A level below threshold records no tap."""
        sut = _make_sut(threshold=-40)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False

        sut.detect_tap(level=-50, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is None, "Signal below threshold must not trigger detection"


# ---------------------------------------------------------------------------
# T3: Warm-up suppression
# ---------------------------------------------------------------------------

class TestWarmup:
    """Mirrors Swift TapDetectionTests T3."""

    def test_T3_during_warmup_suppresses_detection(self):
        """T3: Calls during warm-up period suppress detection entirely."""
        import time as _t
        sut = _make_sut()
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = False
        # Set start time to 'now' so warmup is still active.
        sut.warmup_start_audio_time = 0.0  # audio clock: warm-up starts now

        sut.detect_tap(level=-20, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.decay_tap_audio_time is None, "Should not detect during warm-up"


# ---------------------------------------------------------------------------
# T5: Hysteresis prevents bouncing
# ---------------------------------------------------------------------------

class TestHysteresis:
    """Mirrors Swift TapDetectionTests T5/T5b."""

    def test_T5_hysteresis_prevents_bouncing_on_falling_edge(self):
        """T5: Signal between falling and rising threshold keeps is_above_threshold True."""
        import time as _t
        sut = _make_sut(threshold=-40, hysteresis=5)
        sut.detection_state = DetectionState.LISTENING

        # First sequence: rising-edge confirmation requires N consecutive
        # above-rising-threshold calls before firing — feed enough to latch.
        sut.is_above_threshold = False
        for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
            sut.detect_tap(level=-35, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        # A tap has fired; is_above_threshold == True.

        # The anchor: the first tap was stamped at audio time 0; a second tap, fed at 1, would move it.
        anchor = sut.decay_tap_audio_time

        # Second call: signal at -43 dB — between falling_threshold (-45) and
        # rising_threshold (-40). Should stay "above" and not fire a new tap.
        sut.detect_tap(level=-43, audio_time=1.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.is_above_threshold is True, \
            "Signal above falling_threshold should keep is_above_threshold = True"
        assert anchor == 0.0 and sut.decay_tap_audio_time == anchor, \
            "No new tap should fire when still above falling threshold"

    def test_T5b_signal_below_falling_threshold_resets_above_threshold(self):
        """T5b: Once signal drops below falling_threshold, is_above_threshold becomes False."""
        sut = _make_sut(threshold=-40, hysteresis=5)
        sut.detection_state = DetectionState.LISTENING
        sut.is_above_threshold = True   # currently above

        # Signal drops below falling_threshold (-45)
        sut.detect_tap(level=-50, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.is_above_threshold is False, \
            "Signal below falling_threshold should set is_above_threshold = False"


# ---------------------------------------------------------------------------
# T8: Post-warmup sync frame
# ---------------------------------------------------------------------------

class TestPostWarmupSync:
    """Mirrors Swift TapDetectionTests T8."""

    def test_T8_just_exited_warmup_syncs_then_skips(self):
        """T8: First frame after warmup syncs is_above_threshold but does not fire tap."""
        sut = _make_sut(threshold=-40)
        sut.detection_state = DetectionState.LISTENING
        sut.just_exited_warmup = True
        # warmup_start_audio_time is 2 audio-seconds ago → warm-up check passes

        sut.detect_tap(level=-30, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        # No tap must fire on the sync frame
        assert sut.decay_tap_audio_time is None, \
            "First frame after warmup should sync state but not fire a tap"
        # just_exited_warmup should be cleared
        assert sut.just_exited_warmup is False, \
            "just_exited_warmup flag should be cleared after sync frame"


# ---------------------------------------------------------------------------
# T6: Plate mode uses relative noise-floor detection
# ---------------------------------------------------------------------------

class TestPlateMode:
    """Mirrors Swift TapDetectionTests T6."""

    def test_T6_plate_mode_uses_relative_noise_floor(self):
        """T6: Plate mode uses noise_floor + headroom, not absolute tap_detection_threshold."""
        import time as _t
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        try:
            sut = TapToneAnalyzer()
            sut.tap_detection_threshold = -40.0
            sut.hysteresis_margin = 5.0
            sut.number_of_taps = 1
            sut.warmup_start_audio_time = -2.0  # audio-seconds in the past
            sut.just_exited_warmup = False
            sut.detection_state = DetectionState.LISTENING
            sut.is_above_threshold = False

            # Set a controlled noise floor estimate.
            # headroom = max(-40 - (-70), 10) = 30 dB
            # effective_rising_threshold = -70 + 30 = -40 dB
            # So a signal at -35 dB should fire after N consecutive
            # above-threshold calls.
            sut.noise_floor_estimate = -70.0
            for _ in range(RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS):
                sut.detect_tap(level=-35, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

            # Plate taps do not start ring-out tracking, so decay_tap_audio_time is not set here; the
            # tap's own effect is that detection stops while its gated capture runs.
            assert sut.detection_state == DetectionState.IDLE, \
                "Plate mode: signal above noise floor + headroom should fire"
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)


# ---------------------------------------------------------------------------
# T7: EMA noise-floor convergence
# ---------------------------------------------------------------------------

class TestEMAConvergence:
    """Mirrors Swift TapDetectionTests T7."""

    def test_T7_noise_floor_ema_converges_with_repeated_below_threshold_frames(self):
        """T7: After many frames at a constant level, the EMA converges."""
        import time as _t
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        try:
            sut = TapToneAnalyzer()
            sut.tap_detection_threshold = -40.0
            sut.hysteresis_margin = 5.0
            sut.warmup_start_audio_time = -2.0  # audio-seconds in the past
            sut.just_exited_warmup = False
            sut.is_above_threshold = False   # stays below threshold

            start_estimate = sut.noise_floor_estimate   # initial value (-60)
            target = -55.0  # ambient level to feed

            # Feed 50 frames at -55 dB (below threshold → EMA updates)
            for _ in range(50):
                sut.detect_tap(level=target, audio_time=0.0, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

            # EMA with α=0.05, 50 steps from -60 toward -55:
            # After 50 steps: estimate ≈ -57.4; should be > -58
            assert sut.noise_floor_estimate > start_estimate, \
                "Noise floor should move toward ambient level after repeated frames"
            assert sut.noise_floor_estimate > -58.0, (
                f"Noise floor after 50 frames at -55 dB should be close to -55 "
                f"(got {sut.noise_floor_estimate:.2f})"
            )
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)


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

    Python-only: the other editions have a single delivery by construction.
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
        original = sut.track_decay_fast   # runs in every detection pass
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
        original = sut.track_decay_fast   # the first thing each detection pass does
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
