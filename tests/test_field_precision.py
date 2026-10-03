# @parity test/field-precision
"""The numeric-precision table and its helpers (``field_precision``) against the shared case file,
``field-precision.json`` — the same cases the Swift and web suites run. Field names are Swift's; ``FIELDS``
maps them to this module's constants."""

from __future__ import annotations

import json
import os

import pytest

from guitar_tap.models import field_precision as fp

with open(os.path.join(os.path.dirname(__file__), "field-precision.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


# Swift's field names → this module's constants.
FIELDS = {
    "linearDimensionMM": fp.LINEAR_DIMENSION_MM, "massG": fp.MASS_G, "bodyDimensionMM": fp.BODY_DIMENSION_MM,
    "frequencyHz": fp.FREQUENCY_HZ, "magnitudeDB": fp.MAGNITUDE_DB, "stiffness": fp.STIFFNESS,
    "peakFrequencyHz": fp.PEAK_FREQUENCY_HZ, "peakMagnitudeDB": fp.PEAK_MAGNITUDE_DB, "qFactor": fp.Q_FACTOR,
    "youngsModulusGPa": fp.YOUNGS_MODULUS_GPA, "speedOfSoundMS": fp.SPEED_OF_SOUND_MS,
    "densityGPerCm3": fp.DENSITY_G_PER_CM3, "decayRatio": fp.DECAY_RATIO, "bandwidthHz": fp.BANDWIDTH_HZ,
    "shearModulusGPa": fp.SHEAR_MODULUS_GPA, "specificModulus": fp.SPECIFIC_MODULUS,
    "radiationRatio": fp.RADIATION_RATIO, "crossLongRatio": fp.CROSS_LONG_RATIO,
    "longCrossRatio": fp.LONG_CROSS_RATIO, "goreThicknessMM": fp.GORE_THICKNESS_MM, "decayTimeS": fp.DECAY_TIME_S,
}


def _number(v) -> float:
    return float("-inf") if v == "-Infinity" else float("inf") if v == "Infinity" else float(v)


@pytest.mark.parametrize("name,decimals", DATA["table"])
def test_table(name, decimals):
    assert FIELDS[name] == decimals


def test_table_names_every_field():
    assert sorted(FIELDS) == sorted(name for name, _ in DATA["table"])


@pytest.mark.parametrize("text,decimals,expected", DATA["decimalsWithin"])
def test_decimals_within(text, decimals, expected):
    assert fp.decimals_within(text, decimals) is expected


@pytest.mark.parametrize("row", DATA["rounded"], ids=lambda r: f'{r["value"]}@{r["decimals"]}')
def test_rounded(row):
    result = fp.rounded(_number(row["value"]), row["decimals"])
    if "tolerance" in row:
        assert abs(result - _number(row["expect"])) < row["tolerance"]
    else:
        assert result == _number(row["expect"])


@pytest.mark.parametrize("value,decimals,expected", DATA["string"])
def test_string(value, decimals, expected):
    assert fp.string(_number(value), decimals) == expected
