# @parity test/mode-colors
"""Each guitar mode's colour role against the shared case file ``theme.json`` — the same cases the
Swift and web suites run — and that the modes, and a freeform label, are told apart in each
scheme. Mode names are Swift's."""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.views.utilities import palette

with open(os.path.join(os.path.dirname(__file__), "theme.json"), encoding="utf-8") as _f:
    MODE_ROLES = json.load(_f)["modeRoles"]


def _mode(swift_name: str) -> GuitarMode:
    return GuitarMode[re.sub(r"(?<=[a-z])(?=[A-Z])", "_", swift_name).upper()]


def test_every_mode_and_its_role():
    for name, role in MODE_ROLES:
        assert palette.mode_role(_mode(name)).value == role, name
    assert len(MODE_ROLES) == len(GuitarMode.current_cases)


def test_every_mode_has_its_own_colour_in_each_scheme():
    """Seven modes and a freeform label are eight colours, told apart in each scheme."""
    roles = [palette.mode_role(m) for m in GuitarMode.current_cases]
    roles.append(palette.Role.MODE_USER_DEFINED)
    assert len({palette.pair(r).light for r in roles}) == len(roles)
    assert len({palette.pair(r).dark for r in roles}) == len(roles)
