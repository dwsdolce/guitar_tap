# @parity test/state-invariants
"""State combinations the design forbids, checked after real sequences of steps. They are the rules
Pause / New Tap / Cancel enablement and the audio-thread detection guards rest on, so a refactor that
broke one would show up as a UI bug even where each function looks right on its own. The checker is
below; the shared cases in state-invariants.json (V1-V13) run it after their steps and test it on each
forbidden state, the same as Swift and the web.
"""
from __future__ import annotations

import datetime
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.detection_state import DetectionState  # noqa: E402
from guitar_tap.models.material_tap_phase import MaterialTapPhase  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "state-invariants.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

_DETECTION_STATES = {"idle": DetectionState.IDLE, "listening": DetectionState.LISTENING,
                     "paused": DetectionState.PAUSED}


def state_invariant_violation(a: TapToneAnalyzer) -> str | None:
    """The first rule ``a`` breaks, described, or None. The rules are listed in state-invariants.json;
    Swift's stateInvariantViolation and the web's stateInvariantViolation check the same ones."""
    is_guitar = TapDisplaySettings.measurement_type().is_guitar

    # I1: Guitar mode: is_detecting && is_measurement_complete is illegal.
    if is_guitar and a.is_detecting and a.is_measurement_complete:
        return "I1: is_detecting && is_measurement_complete is illegal in guitar mode"

    # I2: is_detection_paused implies actively-detecting context.
    if a.is_detection_paused and a.is_measurement_complete:
        return "I2: is_detection_paused && is_measurement_complete is illegal"

    # I3: captured_taps count must not exceed number_of_taps.
    if len(a.captured_taps) > a.number_of_taps:
        return f"I3: captured_taps ({len(a.captured_taps)}) > number_of_taps ({a.number_of_taps})"

    # I4: current_tap_count must match captured_taps count for guitar mode.
    if is_guitar and a.current_tap_count != len(a.captured_taps):
        return (
            f"I4: current_tap_count ({a.current_tap_count}) != "
            f"len(captured_taps) ({len(a.captured_taps)}) in guitar mode"
        )

    # I5: tap_progress must be in [0, 1].
    if a.tap_progress < 0 or a.tap_progress > 1:
        return f"I5: tap_progress ({a.tap_progress}) outside [0, 1]"

    # I6: During a plate/brace review phase, is_detecting must be false.
    if not is_guitar and a.material_tap_phase in (
        MaterialTapPhase.REVIEWING_LONGITUDINAL,
        MaterialTapPhase.REVIEWING_CROSS,
        MaterialTapPhase.REVIEWING_FLC,
    ):
        if a.is_detecting:
            return (
                "I6: is_detecting must be False during plate/brace review "
                f"(phase={a.material_tap_phase})"
            )

    return None


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TapDisplaySettings.measurement_type(), TapDisplaySettings.measure_flc())
    yield
    TapDisplaySettings.set_measurement_type(saved[0])
    TapDisplaySettings.set_measure_flc(saved[1])


def _captured_tap():
    """A captured tap for a ``write`` step: 64 bins at 31.25 Hz, -80 dB but bin 16 at -30."""
    mags = np.full(64, -80.0)
    mags[16] = -30.0
    return (mags, np.arange(64) * 31.25, datetime.datetime.now())


def _write(fields: dict, sut: TapToneAnalyzer) -> None:
    """Set the fields a ``write`` step names directly — only to give the checker a forbidden state."""
    for field, value in fields.items():
        if field == "detectionState":
            sut.detection_state = _DETECTION_STATES[value]
        elif field == "complete":
            sut.is_measurement_complete = value
        elif field == "capturedTaps":
            sut.captured_taps = [_captured_tap() for _ in range(value)]
        elif field == "tapCount":
            sut.current_tap_count = value
        elif field == "tapProgress":
            sut.tap_progress = value
        elif field == "phase":
            sut.material_tap_phase = MaterialTapPhase(value)
        else:
            pytest.fail(f"unknown write field {field}")


def _check(fields: dict, sut: TapToneAnalyzer) -> None:
    """Assert the fields an expectation names."""
    for field, want in fields.items():
        if field == "violation":
            violation = state_invariant_violation(sut)
            assert (violation[:2] if violation else None) == want, f"{field}: {violation}"
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "capturedTaps":
            assert len(sut.captured_taps) == want, field
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{field}: {sut.material_tap_phase}"
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_invariants(row, qapp):
    sut = make_steps_analyzer()
    for step in row["steps"]:
        if "check" in step:
            _check(step["check"], sut)
        elif "write" in step:
            _write(step["write"], sut)
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut)
