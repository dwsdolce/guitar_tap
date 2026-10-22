# @parity test/snap-interpolation
"""The crosshair's snap to a curve against the shared case file ``snap-interpolation.json`` — the same cases the
Swift and web suites run: the point on a curve at the pointer's frequency, interpolated between the two bins either
side, and which of several curves the crosshair follows."""

from __future__ import annotations

import json
import os

import pytest

from guitar_tap.views.spectrum_view_snap_interpolation import locked_series, snap_to_waveform

with open(os.path.join(os.path.dirname(__file__), "snap-interpolation.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("case", DATA["snapToWaveform"], ids=lambda c: c["id"])
def test_snap_to_waveform(case):
    r = snap_to_waveform(case["targetHz"], case["magnitudes"], case["frequencies"])
    if case["expect"] is None:
        assert r is None
    else:
        assert r is not None
        assert r[0] == pytest.approx(case["expect"][0], abs=1e-3)
        assert r[1] == pytest.approx(case["expect"][1], abs=1e-3)


@pytest.mark.parametrize("case", DATA["lockedSeries"], ids=lambda c: c["id"])
def test_locked_series(case):
    candidates = [(int(i), float(d)) for i, d in case["candidates"]]
    assert locked_series(candidates, case["locked"]) == case["expect"]
