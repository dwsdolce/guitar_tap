# @parity test/tap-progress
"""The values the status bar's progress bar shows:

    total_plate_taps = number_of_taps × (brace 1, plate 2, plate with FLC 3)
    tap_progress     = min(1, current_tap_count / (guitar: number_of_taps, else total_plate_taps)),
                       stored at each capture, so a later Taps change cannot rewrite a finished bar
    current_tap_count (material) is CUMULATIVE across L -> C -> FLC, and rebases to the earlier
                       phases' taps on Redo

The cumulative count is the rule a phase boundary can break while the equations still hold, so the
cases drive real captures across Accepts. The shared cases in tap-progress.json (TP1-TP15), the same as
Swift and the web.
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
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "tap-progress.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


def _measurement(name: str):
    """The measurement a load step names: an inline file of the case table, or a fixture."""
    inline = DATA.get("files", {}).get(name)
    if inline is not None:
        return measurements_from_json(json.dumps(inline))[0]
    with open(os.path.join(_HERE, name), encoding="utf-8") as f:
        return measurements_from_json(f.read())[0]


def _check(fields: dict, sut) -> None:
    """Assert the fields an expectation names."""
    for field, want in fields.items():
        if field == "totalPlateTaps":
            assert sut.total_plate_taps == want, field
        elif field == "tapProgress":
            assert sut.tap_progress == pytest.approx(want, abs=1e-4), f"{field}: {sut.tap_progress}"
        elif field == "tapCount":
            assert sut.current_tap_count == want, f"{field}: {sut.current_tap_count}"
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{field}: {sut.material_tap_phase}"
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "detecting":
            assert sut.is_detecting is want, field
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_tap_progress(row, qapp):
    sut = make_steps_analyzer()
    for step in row["steps"]:
        if "check" in step:
            _check(step["check"], sut)
        elif "load" in step:
            sut.load_measurement(_measurement(step["load"]))
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut)
