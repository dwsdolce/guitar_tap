# @parity test/saved-measurement-menu
"""
A saved measurement's menu, against the shared case file saved-measurement-menu.json: the same items, words, order
and icons as Swift's and the web's. The Material Design icon is checked here; the SF Symbol in Swift. The item only
Swift's Mac edition has (macOSOnly) is not in this edition.

Mirrors: GuitarTapTests/SavedMeasurementMenuTests.swift · test/saved-measurement-menu.test.ts
"""

from __future__ import annotations

import json
import os

from guitar_tap.views.measurements import saved_measurement_menu

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "saved-measurement-menu.json"), encoding="utf-8"))


def test_saved_measurement_menu():
    expected = [
        [saved_measurement_menu.SavedMeasurementMenuEntry(c["action"], c["title"], c["mdi"])
         for c in group if not c.get("macOSOnly")]
        for group in DATA["groups"]
    ]
    assert saved_measurement_menu.GROUPS == expected
