# @parity test/material-selection
"""A material (plate / brace) measurement's effective selection ignores the saved selection, against the shared
case file ``material-selection.json`` — the same cases the Swift and web suites run. Material has no per-peak
selection: the identified L / C / FLC are the peaks. The case is a genuine iPad-saved plate whose saved selection
was clobbered to the cross peak alone; reading it resolves all three, healing the file."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "material-selection.json"), encoding="utf-8") as _f:
    CASES = json.load(_f)["cases"]


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_effective_selection_is_every_material_peak(row):
    with open(os.path.join(HERE, row["fixture"] + ".guitartap"), encoding="utf-8") as f:
        m = TapToneMeasurement.from_dict(json.load(f)[0])
    assert m.is_material is row["isMaterial"]
    assert len(m.peaks) == row["peakCount"]
    assert len(m.selected_peak_ids or []) == row["savedSelectionCount"]
    assert m.effective_selected_peak_ids == {p.id for p in m.peaks}
    assert len(m.effective_selected_peak_ids) == row["effectiveSelectionCount"]
