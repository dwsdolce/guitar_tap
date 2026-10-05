# @parity test/theme
"""The palette against the shared case file ``theme.json`` — every colour role with its light and dark value, and
the opacities applied to other roles — the same cases the Swift and web suites run. Role names are Swift's."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.utilities import palette

with open(os.path.join(os.path.dirname(__file__), "theme.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("name,light,dark", DATA["roles"])
def test_role_and_its_values(name, light, dark):
    assert palette.pair(palette.Role(name)) == palette.ColorPair(light, dark)


def test_every_role_in_the_file_order():
    assert [r.value for r in palette.Role] == [row[0] for row in DATA["roles"]]


@pytest.mark.parametrize("name,light,dark", DATA["opacities"])
def test_opacity(name, light, dark):
    assert palette.OPACITIES[palette.Opacity(name)] == (light, dark)


def test_every_opacity_in_the_file_order():
    assert [o.value for o in palette.Opacity] == [row[0] for row in DATA["opacities"]]
