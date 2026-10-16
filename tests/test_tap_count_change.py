# @parity test/tap-count-change
"""Changing Taps (Swift ``numberOfTaps.didSet``): while armed and waiting for the first tap the prompt
follows the new count; otherwise it is left alone; and a change never completes a measurement or
drops captured taps — there is no "lower the count mid-sequence -> finalise with the taps in hand"
rule. The Taps spinner is disabled from the first captured tap, so the count cannot change
mid-sequence in the app; these pin that the model would not finalise if it did. The shared cases in
tap-count-change.json (TC1-TC10), the same as Swift and the web, through the app's own paths.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "tap-count-change.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_tap_count_change(row, qapp):
    sut = make_steps_analyzer()
    status_before_step = sut.status_message
    for step in row["steps"]:
        status_before_step = sut.status_message
        assert run_analyzer_step(step, sut), f"unknown step {step}"

    for field, want in row["expect"].items():
        if field == "statusMessage":
            assert sut.status_message == want, f"{field}: {sut.status_message!r}"
        elif field == "statusUnchangedByLastStep":
            assert (sut.status_message == status_before_step) is want, \
                f"{field}: {status_before_step!r} -> {sut.status_message!r}"
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{field}: {sut.material_tap_phase}"
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "capturedTaps":
            assert len(sut.captured_taps) == want, f"{field}: {len(sut.captured_taps)}"
        elif field == "numberOfTaps":
            assert sut.number_of_taps == want, field
        else:
            pytest.fail(f"unknown field {field}")
