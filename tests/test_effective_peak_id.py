# @parity test/effective-peak-id
"""The id each material phase's peak is saved and exported under — effective_longitudinal_peak_id,
effective_cross_peak_id, effective_flc_peak_id: none until the phase's peak is chosen, then that peak's
id. The shared cases in effective-peak-id.json (EP1-EP4), the same as Swift and the web, through real
plate taps.
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
with open(os.path.join(_HERE, "effective-peak-id.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_effective_peak_id(row, qapp):
    sut = make_steps_analyzer()
    for step in row["steps"]:
        assert run_analyzer_step(step, sut), f"unknown step {step}"
    phases = {
        "L": (sut.effective_longitudinal_peak_id, sut.selected_longitudinal_peak),
        "C": (sut.effective_cross_peak_id, sut.selected_cross_peak),
        "FLC": (sut.effective_flc_peak_id, sut.selected_flc_peak),
    }
    for phase, want in row["expect"].items():
        effective, selected = phases[phase]
        if want == "selected":
            assert effective is not None and selected is not None and effective == selected.id, phase
        else:
            assert effective is None, f"{phase}: {effective}"
