# @parity test/dimming
"""How a control that cannot be used shows it, against the shared case file dimming.json: the whole group is
disabled and drawn at the theme opacity its case names — disabled_dimmed for one that cannot act now,
not_applicable_dimmed for one that has no meaning here. The same cases the Swift and web suites run. Mirrors Swift
DimmingTests.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.utilities import palette  # noqa: E402
from guitar_tap.views.utilities.extensions import disabled_dimmed, not_applicable_dimmed  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "dimming.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _apply(widget: QtWidgets.QWidget, kind: str) -> None:
    if kind == "cannotActNow":
        disabled_dimmed(widget, True)
    elif kind == "doesNotApply":
        not_applicable_dimmed(widget, True)
    else:
        disabled_dimmed(widget, True)       # dimmed, then made available again: the dimming goes
        disabled_dimmed(widget, False)


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_dimming(row, qapp):
    group = QtWidgets.QWidget()
    label = QtWidgets.QLabel("Taps:", group)
    _apply(group, row["kind"])
    assert group.isEnabled() is row["enabled"], "the group's enabled state"
    assert label.isEnabled() is row["enabled"], "its label goes with it"
    effect = group.graphicsEffect()
    drawn_at = effect.opacity() if isinstance(effect, QtWidgets.QGraphicsOpacityEffect) and effect.isEnabled() else 1.0
    want = palette.opacity(palette.Opacity(row["opacity"])) if row["opacity"] else 1.0
    assert drawn_at == pytest.approx(want), "the whole group is drawn at the case's opacity"
