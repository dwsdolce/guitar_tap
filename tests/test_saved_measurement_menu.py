# @parity test/saved-measurement-menu
"""
A saved measurement's menu, against the shared case file saved-measurement-menu.json: the same items, words, order
and icons as Swift's and the web's. The Material Design icon is checked here; the SF Symbol in Swift. This edition's
items are those with a 'python' title (Swift's Share items have none), and a group left empty is not shown.

Mirrors: GuitarTapTests/SavedMeasurementMenuTests.swift · test/saved-measurement-menu.test.ts
"""

from __future__ import annotations

import json
import os

from guitar_tap.views.measurements import saved_measurement_menu

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "saved-measurement-menu.json"), encoding="utf-8"))


def expected_groups(groups, make):
    """A shared menu case file's groups as this edition shows them: the items with a 'python' title, no group left
    empty."""
    shown = [[make(c) for c in group if "python" in c["titles"]] for group in groups]
    return [group for group in shown if group]


def test_saved_measurement_menu():
    expected = expected_groups(
        DATA["groups"],
        lambda c: saved_measurement_menu.SavedMeasurementMenuEntry(c["action"], c["titles"]["python"], c["mdi"]))
    assert saved_measurement_menu.GROUPS == expected
