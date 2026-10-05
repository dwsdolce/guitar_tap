# @parity test/analysis-quality
"""The guitar tap-tone quality helpers against the shared case file ``analysis-quality.json`` — the
same cases the Swift and web suites run. Guitar types are Swift's; colour names are the quality
roles of ``theme.json``."""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.views.utilities import palette
from guitar_tap.views.utilities.extensions import (
    decay_quality_color,
    decay_quality_label,
    tap_tone_ratio_quality_color,
    tap_tone_ratio_quality_label,
)

with open(os.path.join(os.path.dirname(__file__), "analysis-quality.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

PALETTE = {"gray": palette.GRAY, "orange": palette.ORANGE, "yellow": palette.YELLOW,
           "green": palette.GREEN, "blue": palette.BLUE, "red": palette.RED}


def _type(name: str) -> GuitarType:
    return GuitarType[name.upper()]


def _number(v) -> float:
    return math.nan if v == "NaN" else float(v)


@pytest.mark.parametrize("row", DATA["decayThresholds"], ids=lambda r: r[0])
def test_decay_thresholds(row):
    t = _type(row[0]).decay_thresholds
    assert (t.very_short, t.short, t.moderate, t.good) == tuple(row[1:])


@pytest.mark.parametrize("type_,value,label", DATA["decayLabel"])
def test_decay_label(type_, value, label):
    assert decay_quality_label(_number(value), _type(type_)) == label


@pytest.mark.parametrize("type_,value,color", DATA["decayColor"])
def test_decay_color(type_, value, color):
    assert decay_quality_color(_number(value), _type(type_)) == PALETTE[color]


@pytest.mark.parametrize("value,label", DATA["ratioLabel"])
def test_ratio_label(value, label):
    assert tap_tone_ratio_quality_label(_number(value)) == label


@pytest.mark.parametrize("value,color", DATA["ratioColor"])
def test_ratio_color(value, color):
    assert tap_tone_ratio_quality_color(_number(value)) == PALETTE[color]


@pytest.mark.parametrize("value", DATA["outsideEveryBand"]["values"])
def test_outside_every_band(value):
    o = DATA["outsideEveryBand"]
    gt, v = _type(o["guitarType"]), _number(value)
    assert decay_quality_label(v, gt) == o["label"]
    assert decay_quality_color(v, gt) == PALETTE[o["color"]]
    assert tap_tone_ratio_quality_label(v) == o["label"]
    assert tap_tone_ratio_quality_color(v) == PALETTE[o["color"]]

