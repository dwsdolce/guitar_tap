# @parity test/chart-legend
"""
The chart legend's lines against the shared case file chart-legend.json: the same entries on the same lines as
Swift's and the web's for the same widths.

Mirrors: GuitarTapTests/ChartLegendTests.swift · test/chart-legend.test.ts
"""

from __future__ import annotations

import json
import os

import pytest

from guitar_tap.views.chart_legend import legend_lines

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "chart-legend.json"), encoding="utf-8"))


@pytest.mark.parametrize("row", DATA["lines"], ids=lambda r: r[0])
def test_lines(row):
    _id, widths, width, spacing, expected = row
    assert legend_lines(widths, width, spacing) == expected
