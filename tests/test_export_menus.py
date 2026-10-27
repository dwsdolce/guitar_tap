# @parity test/export-menus
"""
Saved Measurements' library menu and Analysis Results' menu, against the shared case file export-menus.json: each
button's word and icon, and its items, words, order and icons — the same as Swift's and the web's. This edition's
items are those with a 'python' title, and a group left empty is not shown.

Mirrors: GuitarTapTests/ExportMenusTests.swift · test/export-menus.test.ts
"""

from __future__ import annotations

import json
import os

import pytest

from guitar_tap.views.measurements import export_menus
from tests.test_saved_measurement_menu import expected_groups

DATA = json.load(open(os.path.join(os.path.dirname(__file__), "export-menus.json"), encoding="utf-8"))


@pytest.mark.parametrize("key, menu", [("panel", export_menus.PANEL), ("analysisResults", export_menus.ANALYSIS_RESULTS)])
def test_export_menu(key, menu):
    spec = DATA[key]
    assert menu.button == spec["button"]["python"]
    assert menu.mdi == spec["mdi"]
    assert menu.groups == expected_groups(
        spec["groups"], lambda c: export_menus.ExportMenuEntry(c["action"], c["titles"]["python"], c["mdi"]))
