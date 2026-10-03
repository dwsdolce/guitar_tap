# @parity test/display-range
"""The chart's display range against the shared case file ``display-range.json`` — the same cases the Swift
and web suites run: widening onto a newly identified plate / brace peak (a guitar's range is the user's
analysis window and is never widened; a load shows the range it was saved with), and when the chart's range
moves. The analyzer's announcing each peak is tested in test_material_peak_announcement.py.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.display_range import (
    ChartRange,
    expanded_to_include,
    loaded_after_widening,
    on_new_measurement,
    on_settings_done,
    widened_onto,
)
from guitar_tap.models.measurement_type import MeasurementType

with open(os.path.join(os.path.dirname(__file__), "display-range.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _range(v):
    return None if v is None else ChartRange(*map(float, v))


@pytest.mark.parametrize("hz,lo,hi,exp_lo,exp_hi", DATA["expandedToInclude"])
def test_expanded_to_include(hz, lo, hi, exp_lo, exp_hi):
    assert expanded_to_include(hz, lo, hi) == (exp_lo, exp_hi)


@pytest.mark.parametrize("hz,type_,from_load,lo,hi,exp_lo,exp_hi", DATA["widenedOnto"])
def test_widened_onto(hz, type_, from_load, lo, hi, exp_lo, exp_hi):
    assert widened_onto(hz, MeasurementType[type_.upper()], from_load, lo, hi) == (exp_lo, exp_hi)


@pytest.mark.parametrize("row", DATA["onSettingsDone"])
def test_on_settings_done(row):
    assert on_settings_done(_range(row["saved"]), _range(row["previouslySaved"]), row["typeChanged"]) == _range(row["expect"])


@pytest.mark.parametrize("row", DATA["onNewMeasurement"])
def test_on_new_measurement(row):
    assert on_new_measurement(_range(row["current"]), _range(row["loaded"]), _range(row["saved"])) == _range(row["expect"])


@pytest.mark.parametrize("row", DATA["loadedAfterWidening"])
def test_loaded_after_widening(row):
    assert loaded_after_widening(_range(row["loaded"]), _range(row["before"]), _range(row["after"])) == _range(row["expect"])
