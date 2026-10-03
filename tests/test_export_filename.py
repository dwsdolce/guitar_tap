# @parity test/export-filename
"""The export filename stem (export_stem) and a saved measurement's base filename against the shared case file
``export-filename.json``, the same cases the Swift and web suites run."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.export_filename import export_stem
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

with open(os.path.join(os.path.dirname(__file__), "export-filename.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("row", DATA["stem"], ids=lambda r: f'{r["name"]}-{r["seconds"]}-{r["unnamed"]}')
def test_stem(row):
    assert export_stem(row["name"], row["seconds"], row["unnamed"]) == row["expect"]


@pytest.mark.parametrize("row", DATA["measurementBaseFilename"], ids=lambda r: f'{r["name"]}-{r["timestamp"]}')
def test_measurement_base_filename(row):
    m = TapToneMeasurement.create(peaks=[], measurement_name=row["name"])
    m.timestamp = row["timestamp"]
    assert m.base_filename == row["expect"]
