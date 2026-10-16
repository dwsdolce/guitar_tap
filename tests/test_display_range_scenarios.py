# @parity test/display-range
"""The analyzer's side of the chart's range: the range a load publishes for the chart (a measurement's
snapshot range exactly, or the saved range when it has none) without moving the analysis range, and the
announcements of the three material peaks the chart widens onto. The 'scenarios' of the shared
display-range.json (DR1-DR6; DR7 is the web's own), the same as Swift and the web. The widening decision
itself is test_display_range_expansion.py.
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
with open(os.path.join(_HERE, "display-range.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

# The scenarios for Python: all but those marked for the web alone.
SCENARIOS = [c for c in DATA["scenarios"] if c.get("only") != "web"]


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


def _check(fields: dict, sut, ranges: list, heard: "dict | None") -> None:
    for field, want in fields.items():
        if field == "loadedRange":
            assert ranges, "a range was published"
            wanted = ((TDS.min_frequency(), TDS.max_frequency(), TDS.min_magnitude(), TDS.max_magnitude())
                      if want == "saved" else tuple(want))
            assert ranges[-1] == pytest.approx(wanted, abs=1e-4), f"{field}: {ranges[-1]}"
        elif field == "analysisRange":
            assert [sut.min_frequency, sut.max_frequency] == pytest.approx(want), field
        elif field == "lastAnnounced":
            for phase, hz in want.items():
                assert heard and heard[phase] and heard[phase][-1] == pytest.approx(hz, abs=1e-3), f"{field} {phase}"
        elif field == "announced":
            for phase, wanted in want.items():
                assert heard is not None and heard[phase] == [w if w is None else pytest.approx(w) for w in wanted], \
                    f"{field} {phase}: {heard and heard[phase]}"
        elif field == "peaksFromLoad":
            assert sut.material_peaks_from_load is want, field
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", SCENARIOS, ids=lambda r: r["id"])
def test_scenario(row, qapp):
    sut = make_steps_analyzer()
    ranges: list = []
    sut.loadedAxisRangeChanged.connect(lambda *r: ranges.append(r))
    heard = None
    for step in row["steps"]:
        if "load" in step:
            sut.load_measurement(measurements_from_json(json.dumps(DATA["files"][step["load"]]))[0])
        elif step.get("listen"):
            heard = {"L": [], "C": [], "FLC": []}
            sut.selectedLongitudinalPeakChanged.connect(lambda p: heard["L"].append(p and p.frequency))
            sut.selectedCrossPeakChanged.connect(lambda p: heard["C"].append(p and p.frequency))
            sut.selectedFlcPeakChanged.connect(lambda p: heard["FLC"].append(p and p.frequency))
        elif "check" in step:
            _check(step["check"], sut, ranges, heard)
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut, ranges, heard)
