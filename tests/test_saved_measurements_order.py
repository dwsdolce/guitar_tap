# @parity test/saved-measurements-order
"""The order Saved Measurements shows the library in — ``saved_measurements_order.shown`` — against the shared
case file ``saved-measurements-order.json``, the same cases the Swift and web suites run."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.saved_measurements_order import (  # noqa: E402
    Key, SavedMeasurementsSort, duplicates, parse_date, shown)

with open(os.path.join(os.path.dirname(__file__), "saved-measurements-order.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

KEYS = [Key(name=m["name"], date=parse_date(m["timestamp"]), type=m["type"]) for m in DATA["measurements"]]


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_shown_order(row):
    got = shown(KEYS, SavedMeasurementsSort(row["sort"]), row["ascending"], row["filter"])
    assert got == row["expect"], row["name"]


@pytest.mark.parametrize("row", DATA["duplicates"], ids=lambda r: r["id"])
def test_duplicates(row):
    assert duplicates(row["ids"]) == row["expect"], row["name"]
