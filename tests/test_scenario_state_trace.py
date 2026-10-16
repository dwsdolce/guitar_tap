# @parity test/scenario-trace
"""End-to-end scenarios, pinned by the state they pass through — detecting, paused, complete, the tap
count and the taps held — not only where they end: the app's behaviour on screen follows each
intermediate state, so two editions reaching the same result by different paths would differ. Every
tap is a real capture finish and every wait is audio fed through the analyzer's clock. The shared
cases in scenario-trace.json (S1-S4), the same as Swift and the web.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.detection_state import DetectionState  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "scenario-trace.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_type():
    """The measurement type is global; put it back afterwards."""
    saved = TDS.measurement_type()
    yield
    TDS.set_measurement_type(saved)


def _snapshot(label: str, sut) -> dict:
    """The state a ``snap`` step records, in the case file's form."""
    return {"label": label, "detecting": sut.is_detecting, "paused": sut.is_detection_paused,
            "complete": sut.is_measurement_complete, "tapCount": sut.current_tap_count,
            "capturedTaps": len(sut.captured_taps)}


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_scenario(row, qapp):
    sut = make_steps_analyzer()
    trace = []
    for step in row["steps"]:
        if "snap" in step:
            trace.append(_snapshot(step["snap"], sut))
        elif step.get("strayDetection"):
            sut.detection_state = DetectionState.IDLE
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    assert trace == row["expect"]["trace"]
