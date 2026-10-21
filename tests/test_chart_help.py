# @parity test/chart-help
"""
The chart's help against the shared case file chart-help.json: the same lines, words and groups as Swift's and the
web's, and on each device the lines that work there.

Mirrors: GuitarTapTests/ChartHelpTests.swift · test/chart-help.test.ts
"""

from __future__ import annotations

import json
import os

import pytest

from guitar_tap.views import chart_help

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "chart-help.json"), encoding="utf-8"))


def test_lines():
    assert chart_help.TITLE == DATA["title"]
    expected = [[chart_help.ChartHelpLine(c["gesture"], c.get("otherKeys"), c["effect"], frozenset(c["needs"]))
                 for c in group] for group in DATA["groups"]]
    assert chart_help.GROUPS == expected


@pytest.mark.parametrize("row", DATA["devices"], ids=lambda r: r["id"])
def test_shown(row):
    device = chart_help.Device(row["pointer"], row["keyboard"], row["pinch"], row["appleKeys"])
    assert [[g for g, _ in group] for group in chart_help.shown(device)] == row["shows"]
