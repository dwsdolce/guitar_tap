# @parity test/chart-menu
"""
The chart's menu and a peak label's, against the shared case file chart-menu.json: the same items, words, order
and icons as Swift's and the web's. The Material Design icon is checked here; the SF Symbol in Swift.

Mirrors: GuitarTapTests/ChartMenuTests.swift · test/chart-menu.test.ts
"""

from __future__ import annotations

import json
import os

from guitar_tap.views import chart_menu

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "chart-menu.json"), encoding="utf-8"))


def _entries(cases: list[dict]) -> list[chart_menu.ChartMenuEntry]:
    return [chart_menu.ChartMenuEntry(c["action"], c["title"], c["mdi"]) for c in cases]


def test_chart_menu():
    assert chart_menu.GROUPS == [_entries(g) for g in DATA["groups"]]


def test_comparison_menu():
    assert chart_menu.COMPARISON_GROUPS == [_entries(g) for g in DATA["comparisonGroups"]]


def test_label_menu():
    assert chart_menu.LABEL_MENU == _entries(DATA["labelMenu"])
