# @parity test/axis-ticks
"""The chart's axis ticks — its grid lines — against the shared case file ``axis-ticks.json``: the
frequency ticks and their screen and export labels, and the magnitude tick spacing. The same cases
the Swift and web suites run."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.utilities import axis_tick_generator as atg

with open(os.path.join(os.path.dirname(__file__), "axis-ticks.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("range_,ticks,screen,export", DATA["frequency"])
def test_frequency_ticks_and_labels(range_, ticks, screen, export):
    got = atg.generate_ticks(range_[0], range_[1], max_ticks=8)
    assert got == pytest.approx(ticks, rel=1e-9, abs=1e-9)
    visible = [t for t in got if range_[0] <= t <= range_[1]]
    labels = atg.format_tick_labels(visible)
    assert [labels[t] for t in visible] == screen
    assert [atg.format_tick_label(t) for t in visible] == export


@pytest.mark.parametrize("range_,stride", DATA["magnitude"])
def test_magnitude_stride(range_, stride):
    assert atg.magnitude_stride(range_[1] - range_[0]) == stride
