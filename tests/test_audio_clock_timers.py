# @parity test/audio-clock-timers
"""The tap lifecycle's delays — the rest between material taps, the FLC hold, the capture window — run
on the AUDIO clock, so file playback, which advances audio faster or slower than real time, moves them
with the audio. The shared cases in audio-clock-timers.json (AT1-AT6), the same as Swift and the web,
advance only audio. Below them, the safety timeout, which runs on the wall clock by design and so waits
in real time.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6 import QtWidgets  # noqa: E402

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402
from audio_clock_feed import advance_audio  # noqa: E402

from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "audio-clock-timers.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TapDisplaySettings.measurement_type(), TapDisplaySettings.measure_flc())
    yield
    TapDisplaySettings.set_measurement_type(saved[0])
    TapDisplaySettings.set_measure_flc(saved[1])


def _check(fields: dict, sut, noted_warmup) -> None:
    for field, want in fields.items():
        if field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{field}: {sut.material_tap_phase}"
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "gatedCapture":
            assert sut._gated_capture_active is want, field
        elif field == "aboveThreshold":
            assert sut.is_above_threshold is want, field
        elif field == "warmupAtLastChunk":
            assert (sut.warmup_start_audio_time == sut.last_audio_time) is want, field
        elif field == "warmupUnchanged":
            assert (sut.warmup_start_audio_time == noted_warmup) is want, field
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_audio_clock(row, qapp):
    sut = make_steps_analyzer()
    noted_warmup = None
    for step in row["steps"]:
        if step.get("fileEnd"):
            sut._flush_gated_capture_on_file_end()
        elif step.get("playingFile"):
            sut.mic.is_playing_file = True
        elif step.get("noteWarmup"):
            noted_warmup = sut.warmup_start_audio_time
        elif "check" in step:
            _check(step["check"], sut, noted_warmup)
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut, noted_warmup)


class TestSafetyTimeout:
    """The safety timeout runs on the wall clock: it exists for when the audio stops."""

    def test_the_safety_timeout_closes_a_capture_the_audio_stopped_filling(self):
        """T6: a capture the audio stops filling is closed on the WALL clock — it exists for when the
        audio stops, and then the audio clock stops too. After it, detection rests and re-arms."""
        import time
        from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        sut = make_steps_analyzer()
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
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)

    def test_the_safety_timeout_does_not_fire_while_audio_keeps_arriving(self):
        """T6 measures SILENCE, not time since the capture started: while audio keeps arriving —
        however slowly, as under throttled playback — it does not fire."""
        import time
        from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        sut = make_steps_analyzer()
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
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
