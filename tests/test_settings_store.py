# @parity test/settings-store
"""The per-measurement-type display frequency range store.

Each type has its own default and its own stored minimum and maximum, a bound never stored reads
the default, a stored bound keeps its exact value at Swift's Float precision (Save Current View
comes back as saved; an untouched Settings field never rounds it), and an entered range is
validated before it is stored. Mirrors Swift SettingsStoreTests / web settings-store.test.ts.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PySide6 import QtWidgets

from guitar_tap.models.measurement_type import MeasurementType as MT
from guitar_tap.models.tap_display_settings import TapDisplaySettings as tds


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@pytest.fixture
def restore_plate_and_brace():
    saved = {(t, b): f(t) for t in (MT.PLATE, MT.BRACE)
             for b, f in (("min", tds.min_frequency_for), ("max", tds.max_frequency_for))}
    yield
    for (t, b), v in saved.items():
        (tds.set_min_frequency_for if b == "min" else tds.set_max_frequency_for)(v, t)


with open(os.path.join(os.path.dirname(__file__), "settings-store.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("type_,lo,hi", DATA["defaults"])
def test_per_type_defaults(type_, lo, hi):
    """The shared cases in ``settings-store.json``."""
    assert (tds.default_min_frequency(MT[type_.upper()]), tds.default_max_frequency(MT[type_.upper()])) == (lo, hi)


def test_a_type_with_nothing_stored_reads_its_default():
    assert tds.min_frequency_for(MT.FLAMENCO) == 75.0
    assert tds.max_frequency_for(MT.FLAMENCO) == 350.0


def test_a_stored_range_reads_back(restore_plate_and_brace):
    tds.set_min_frequency_for(15.0, MT.PLATE)
    tds.set_max_frequency_for(180.0, MT.PLATE)
    assert tds.min_frequency_for(MT.PLATE) == 15.0
    assert tds.max_frequency_for(MT.PLATE) == 180.0


def test_storing_one_type_does_not_change_another(restore_plate_and_brace):
    tds.set_min_frequency_for(18.0, MT.PLATE)
    tds.set_min_frequency_for(40.0, MT.BRACE)
    assert tds.min_frequency_for(MT.PLATE) == 18.0
    assert tds.min_frequency_for(MT.BRACE) == 40.0


def test_storing_one_bound_leaves_the_other(restore_plate_and_brace):
    tds.set_min_frequency_for(15.0, MT.PLATE)
    tds.set_max_frequency_for(250.0, MT.PLATE)
    assert tds.min_frequency_for(MT.PLATE) == 15.0
    assert tds.max_frequency_for(MT.PLATE) == 250.0


def test_a_stored_range_keeps_its_exact_value(restore_plate_and_brace):
    import numpy as np
    tds.set_min_frequency_for(15.37, MT.PLATE)
    tds.set_max_frequency_for(180.43, MT.PLATE)
    # Exactly, at Swift's Float precision.
    assert tds.min_frequency_for(MT.PLATE) == float(np.float32(15.37))
    assert tds.max_frequency_for(MT.PLATE) == float(np.float32(180.43))


# A Settings range field: untouched keeps the exact stored value.

@pytest.mark.parametrize("shown,stored,decimals,expected", DATA["enteredValue"])
def test_entered_value(shown, stored, decimals, expected):
    """A Settings range field: untouched keeps the exact stored value, edited is the number typed."""
    from guitar_tap.models.display_range import entered_value
    assert entered_value(shown, stored, decimals) == expected


# Settings validates an entered range: each bound clamped, and the two at least 10 apart; otherwise
# the saved range.

@pytest.fixture
def restore_saved_range():
    saved = (tds.min_frequency(), tds.max_frequency(), tds.min_magnitude(), tds.max_magnitude())
    yield
    tds.set_min_frequency(saved[0])
    tds.set_max_frequency(saved[1])
    tds.set_min_magnitude(saved[2])
    tds.set_max_magnitude(saved[3])


@pytest.mark.parametrize("row", DATA["validateFrequencyRange"], ids=lambda r: str(r["input"]))
def test_validate_frequency_range(row, restore_saved_range):
    if "saved" in row:
        tds.set_min_frequency(row["saved"][0])
        tds.set_max_frequency(row["saved"][1])
    assert tds.validate_frequency_range(*map(float, row["input"])) == pytest.approx(tuple(row["expect"]))


@pytest.mark.parametrize("row", DATA["validateMagnitudeRange"], ids=lambda r: str(r["input"]))
def test_validate_magnitude_range(row, restore_saved_range):
    if "saved" in row:
        tds.set_min_magnitude(row["saved"][0])
        tds.set_max_magnitude(row["saved"][1])
    assert tds.validate_magnitude_range(*map(float, row["input"])) == pytest.approx(tuple(row["expect"]))
