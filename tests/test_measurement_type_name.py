# @parity test/measurement-type-name
"""The Details pane's measurement type (``TapToneMeasurement.measurement_type_short_name``) and the material flag
(``is_material``), both resolved from the snapshots field by field — the type lives only there in memory — against
the shared case file ``measurement-type-name.json``, the same cases the Swift and web suites run. In-memory
measurements, the shape a round trip cannot test (loading a file fills the top-level type in)."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

with open(os.path.join(os.path.dirname(__file__), "measurement-type-name.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _snapshot(v):
    """A snapshot as the file describes it: "absent" is none, None is one with no type."""
    if v == "absent":
        return None
    return SpectrumSnapshot(frequencies=[], magnitudes=[], min_freq=20, max_freq=200, min_db=-100, max_db=0,
                            is_logarithmic=False, measurement_type=v)


def _measurement(row) -> TapToneMeasurement:
    m = TapToneMeasurement.create(peaks=[])
    m.spectrum_snapshot = _snapshot(row["spectrum"])
    m.longitudinal_snapshot = _snapshot(row["longitudinal"])
    m.measurement_type = row.get("topLevelType")
    if row.get("isComparison"):
        m.comparison_entries = []
    return m


@pytest.mark.parametrize("row", [r for r in DATA["shortName"] if "python" in r.get("editions", ["python"])],
                         ids=lambda r: r["id"])
def test_short_name(row):
    assert _measurement(row).measurement_type_short_name == row["expect"]


@pytest.mark.parametrize("row", DATA["isMaterial"], ids=lambda r: str(r["expect"]))
def test_is_material(row):
    assert _measurement(row).is_material is row["expect"]
