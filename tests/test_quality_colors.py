# @parity test/quality-colors
"""The wood-quality grades — label against the shared case file ``quality-colors.json``, colour
against the grade's ``wood.*`` role in ``theme.json`` — the same cases the Swift and web suites run.
Grade names are Swift's."""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.material_properties import WoodQuality
from guitar_tap.views.utilities import palette

with open(os.path.join(os.path.dirname(__file__), "quality-colors.json"), encoding="utf-8") as _f:
    GRADES = json.load(_f)["grades"]


def _grade(name: str) -> WoodQuality:
    return WoodQuality[re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).upper()]


@pytest.mark.parametrize("name,label", GRADES)
def test_label_and_role(name, label):
    assert _grade(name).value == label
    assert palette.quality_role(_grade(name)).value == "wood." + name


def test_every_grade_has_its_own_colour_in_each_scheme():
    """The file names every grade, and five grades are five colours, told apart in each scheme."""
    assert len(GRADES) == len(WoodQuality)
    roles = [palette.quality_role(q) for q in WoodQuality]
    assert len({palette.pair(r).light for r in roles}) == len(roles)
    assert len({palette.pair(r).dark for r in roles}) == len(roles)
