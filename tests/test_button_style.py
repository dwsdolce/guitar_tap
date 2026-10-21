# @parity test/button-style
"""What a button the app draws looks like, by kind and state, against the shared case file button-style.json —
the label's role, the fill and any wash over it, the border, and the opacity the whole button is drawn at.
palette.button_look is the rule the stylesheet's button rules are generated from. The same cases the Swift and
web suites run. Mirrors Swift ButtonStyleTests.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.utilities import palette  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "button-style.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _role(name):
    return palette.Role(name) if name else None


def _opacity(name):
    return palette.Opacity(name) if name else None


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_look(row):
    look = palette.button_look(row["kind"], _role(row.get("role")) or palette.Role.ACCENT, row["state"])
    wash = row["wash"] or [None, None]
    assert look.text is _role(row["text"]), "text"
    assert look.fill is _role(row["fill"][0]), "fill"
    assert look.fill_opacity is _opacity(row["fill"][1]), "fill opacity"
    assert look.wash_role is _role(wash[0]), "wash"
    assert look.wash_opacity is _opacity(wash[1]), "wash opacity"
    assert look.border is _role(row["border"]), "border"
    assert look.drawn_at is _opacity(row["drawnAt"]), "drawn at"
