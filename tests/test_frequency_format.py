# @parity test/frequency-format
"""A frequency for display, the range line built from it, and whole hertz grouped by the locale, against the
shared case file ``frequency-format.json`` — the same cases the Swift and web suites run."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtCore

from guitar_tap.views.utilities.extensions import (
    display_range_label,
    formatted_as_frequency,
    formatted_as_whole_hertz,
)

with open(os.path.join(os.path.dirname(__file__), "frequency-format.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("hz,expected", DATA["formattedAsFrequency"])
def test_formatted_as_frequency(hz, expected):
    assert formatted_as_frequency(hz) == expected


@pytest.mark.parametrize("lo,hi,expected", DATA["displayRangeLabel"])
def test_display_range_label(lo, hi, expected):
    assert display_range_label(lo, hi) == expected


@pytest.mark.parametrize("hz,locale,expected", DATA["formattedAsWholeHertz"])
def test_formatted_as_whole_hertz(hz, locale, expected):
    assert formatted_as_whole_hertz(hz, QtCore.QLocale(locale)) == expected
