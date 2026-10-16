# @parity test/tap-decisions
"""
The tap detector's decisions — the rising edge, the threshold the application configured, the
hysteresis latch and the re-arm rule, the warm-up and its sync chunk, relative detection and its noise
floor, the confirmation a resume or a new sequence restarts — the gated capture's onset alignment, and
what the audio pipeline delivers to the analyzer.

Every chunk goes through ``_on_chunk_level``, the per-chunk entry audio takes, after arming the way the
app does; no case sets the detector's state by hand. The shared cases in tap-decisions.json (T1–T14,
O1–O3), the same as Swift and the web. The pipeline's delivery cases below them are Python's own (the
case file says why).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6 import QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


import numpy as np  # noqa: E402

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "tap-decisions.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _check(fields: dict, sut, case_id: str) -> None:
    for field, want in fields.items():
        if field == "captureOpen":
            assert sut._gated_capture_active is want, f"{case_id} {field}"
        elif field == "aboveThreshold":
            assert sut.is_above_threshold is want, f"{case_id} {field}"
        elif field == "justExitedWarmUp":
            assert sut.just_exited_warmup is want, f"{case_id} {field}"
        elif field == "inWarmUp":
            assert (sut.last_audio_time < sut.warmup_period) is want, f"{case_id} {field}: {sut.last_audio_time}"
        elif field == "noiseFloor":
            assert abs(sut.noise_floor_estimate - want) < 0.01, f"{case_id} {field}: {sut.noise_floor_estimate}"
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{case_id} {field}: {sut.material_tap_phase}"
        elif field == "detecting":
            assert sut.is_detecting is want, f"{case_id} {field}"
        elif field == "statusMessage":
            assert sut.status_message == want, f"{case_id} {field}: {sut.status_message}"
        else:
            pytest.fail(f"{case_id}: unknown field {field}")


@pytest.fixture
def _restore_measurement_type():
    saved = TapDisplaySettings.measurement_type()
    yield
    TapDisplaySettings.set_measurement_type(saved)


def test_confirm_chunks():
    assert RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS == DATA["confirmChunks"]


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_decision(row, _restore_measurement_type):
    sut = make_steps_analyzer()
    for step in row["steps"]:
        if "check" in step:
            _check(step["check"], sut, row["id"])
        else:
            assert run_analyzer_step(step, sut), f"{row['id']}: unknown step {step}"
    _check(row["expect"], sut, row["id"])


def _buffer(spec: dict):
    """The buffer an onset case names, as float32."""
    n = spec["length"]
    if spec["kind"] == "impulse":
        buf = np.zeros(n, dtype=np.float32)
        buf[spec["at"]] = spec["value"]
        return buf
    if spec["kind"] == "constant":
        return np.full(n, spec["value"], dtype=np.float32)
    if spec["kind"] == "ramp":
        return (spec["start"] + spec["step"] * np.arange(n)).astype(np.float32)
    raise ValueError(spec["kind"])


@pytest.mark.parametrize("row", DATA["onset"], ids=lambda r: r["id"])
def test_onset(row):
    out = np.asarray(TapToneAnalyzer().align_capture_to_onset(_buffer(row["buffer"]), row["windowSize"], row["preOnset"]))
    expected = row["expect"]
    assert out.shape[0] == expected["length"], f"{row['id']} length"
    if "argmax" in expected:
        assert int(np.argmax(np.abs(out))) == expected["argmax"], f"{row['id']} argmax"
    for index, value in expected.get("samples", {}).items():
        assert abs(float(out[int(index)]) - value) < 1e-6, f"{row['id']} sample {index}: {out[int(index)]}"


# ---------------------------------------------------------------------------
# The pipeline delivers each level and each frame to the analyzer ONCE, exactly
# ---------------------------------------------------------------------------

class TestPipelineDeliversOnceAndExact:
    """What the analyzer receives from the audio pipeline — through the real process_raw_samples.

    Each chunk's level arrives once (rmsLevelHandler, called on the audio queue, hopping to the
    main thread) and each FFT frame once (a Combine sink on the main thread), both as unrounded
    Float dB — in Swift and here. A second delivery would double the "N consecutive chunks"
    confirmation.

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
        QtWidgets.QApplication.processEvents()  # the level is queued to the main thread
        assert sut._current_input_level_db == pytest.approx(expected, abs=1e-9)
        assert abs(sut._current_input_level_db - (-38.0)) > 0.1, "truncated to whole dB"

    def test_detection_runs_on_the_main_thread_when_the_chunk_is_processed_off_it(self):
        """A chunk processed on another thread reaches detection on the MAIN thread, as Swift's does
        (rmsLevelHandler hops with DispatchQueue.main.async) — the thread a capture's finish arrives
        on, so the audio time seen at a finish does not depend on thread timing."""
        import threading
        sut = self._sut()
        seen: list = []
        original = sut._on_rms_level_changed   # detection: runs once per chunk delivered
        sut._on_rms_level_changed = lambda *a, **k: (seen.append(threading.current_thread()), original(*a, **k))
        worker = threading.Thread(target=lambda: sut.mic.process_raw_samples(self._tone(-50.0)))
        worker.start()
        worker.join()
        assert seen == [], "detection ran on the processing thread"
        QtWidgets.QApplication.processEvents()
        assert seen == [threading.main_thread()], f"detection ran on {seen}"

    def test_one_chunk_runs_detection_once(self):
        sut = self._sut()
        calls: list = []
        original = sut._on_rms_level_changed   # detection: runs once per chunk delivered
        sut._on_rms_level_changed = lambda *a, **k: (calls.append(a), original(*a, **k))
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

        The thread object carries the pipeline's Qt signals and is never replaced, so every receiver
        connected at construction keeps reaching the analyzer. FftCanvas opens the audio device when
        constructed, so the view's real start_analyzer runs on a stand-in holding only what it uses.
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
