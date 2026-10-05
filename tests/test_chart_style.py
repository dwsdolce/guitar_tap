# @parity test/chart-style
"""The chart's line and point styles, on screen and in the exported image, against the shared case
file ``chart-style.json`` — the same cases the Swift and web suites run. Names are Swift's."""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.utilities import chart_style

with open(os.path.join(os.path.dirname(__file__), "chart-style.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _python_name(swift_name: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", swift_name).lower()


@pytest.mark.parametrize(
    "which,lines", [("screen", chart_style.SCREEN), ("export", chart_style.EXPORT)],
)
def test_styles(which, lines):
    expected = {
        _python_name(k): tuple(v) if isinstance(v, list) else v for k, v in DATA[which].items()
    }
    assert vars(lines) == expected
