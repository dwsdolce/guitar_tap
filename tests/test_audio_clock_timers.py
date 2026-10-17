# @parity test/audio-clock-timers
"""The tap lifecycle's delays — the rest between material taps, the FLC hold, the capture window — run
on the AUDIO clock, so file playback, which advances audio faster or slower than real time, moves them
with the audio; the capture's safety timeout runs on the wall clock, which a test moves by hand. The
shared cases in audio-clock-timers.json (AT1-AT8), the same as Swift and the web.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

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

