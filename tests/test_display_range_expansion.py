# @parity test/display-range
"""The chart's display range against the shared case file ``display-range.json`` — the same cases the Swift
and web suites run: widening onto a newly identified plate / brace peak (a guitar's range is the
user's analysis window and is never widened; a load shows the range it was saved with), when the
chart's range moves, a zoom or pan step of an axis, and the spectrum points drawn for a range. The
analyzer's announcing each peak is tested in test_material_peak_announcement.py.
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
    panned_range,
    widened_onto,
    zoomed_range,
)
from guitar_tap.models import display_range as dr
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


def _axis(name):
    if name == "magnitude":
        return dr.MIN_MAGNITUDE_DB, dr.MAX_MAGNITUDE_DB, dr.MIN_MAGNITUDE_SPAN_DB
    return dr.MIN_FREQUENCY_HZ, dr.MAX_FREQUENCY_HZ, dr.MIN_FREQUENCY_SPAN_HZ


@pytest.mark.parametrize("row", DATA["zoom"], ids=lambda r: r["id"])
def test_zoom(row):
    lower, upper, span = _axis(row["axis"])
    got = zoomed_range(*row["range"], row["anchor"], row["scale"], lower, upper, span)
    assert got == (None if row["expect"] is None else pytest.approx(tuple(row["expect"]), abs=1e-3)), got


@pytest.mark.parametrize("row", DATA["pan"], ids=lambda r: r["id"])
def test_pan(row):
    lower, upper, _span = _axis(row["axis"])
    got = panned_range(*row["range"], row["delta"], lower, upper)
    assert got == pytest.approx(tuple(row["expect"]), abs=1e-3), got


@pytest.mark.parametrize("row", DATA["drawnIndices"], ids=lambda r: r["id"])
def test_drawn_indices(row):
    assert list(dr.drawn_indices(row["frequencies"], *row["range"])) == row["expect"]
