# @parity test/plate
"""Plate material properties (PlateProperties, MaterialDimensions, WoodQuality) against the shared case
file, ``plate.json`` — the same cases the Swift and web suites run. Its first row is the hub's committed
plate measurement (Tests/Plate/plate-umik-1-swift-mac-1778816330.guitartap), whose values match the ones
GuitarTap reported for it in the .pdf beside that file."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from guitar_tap.models.material_properties import PlateProperties, WoodQuality  # noqa: E402
import material_cases  # noqa: E402

DATA = material_cases.load("plate")


@pytest.mark.parametrize("row", DATA["plates"], ids=lambda r: r["id"])
def test_plate(row):
    e = row["expect"]
    dims = material_cases.dimensions(row)
    p = PlateProperties(dims, row["fL"], row["fC"], row["fLC"])
    numbers = {
        "volume": dims.volume(), "density": dims.density(), "densityGPerCm3": dims.density_g_per_cm3(),
        "youngsModulusLong": p.youngsModulusLong, "youngsModulusCross": p.youngsModulusCross,
        "youngsModulusLongGPa": p.youngsModulusLongGPa, "youngsModulusCrossGPa": p.youngsModulusCrossGPa,
        "speedOfSoundLong": p.c_long_m_s, "speedOfSoundCross": p.c_cross_m_s,
        "specificModulusLong": p.specific_modulus_long, "specificModulusCross": p.specific_modulus_cross,
        "radiationRatioLong": p.radiation_ratio_long, "radiationRatioCross": p.radiation_ratio_cross,
        "crossLongRatio": p.cross_long_ratio, "longCrossRatio": p.long_cross_ratio,
        "goreYoungsModulusLong": p.gore_E_long_pa, "goreYoungsModulusCross": p.gore_E_cross_pa,
    }
    for name, value in numbers.items():
        assert material_cases.close(value, e[name], DATA), f"{name}: {value} != {e[name]}"
    assert p.quality_long == e["spruceQualityLong"]
    assert p.quality_cross == e["spruceQualityCross"]
    assert p.overall_quality == e["overallQuality"]
    if e["goreShearModulus"] is None:
        assert p.gore_shear_modulus is None
    else:
        assert p.gore_shear_modulus is not None
        assert material_cases.close(p.gore_shear_modulus, e["goreShearModulus"], DATA)
    for g in row.get("goreTargetThickness", []):
        t = p.gore_target_thickness(g["bodyLengthMm"], g["bodyWidthMm"], g["vibrationalStiffness"])
        if g["expect"] is None:
            assert t is None, g
        else:
            assert t is not None and material_cases.close(t, g["expect"], DATA), f"{g} -> {t}"


def test_wood_quality():
    D, T = WoodQuality.Direction, WoodQuality.WoodType
    for row in DATA["woodQuality"]:
        q = WoodQuality.evaluate(row["specificModulus"], D[row["direction"].upper()], T[row["woodType"].upper()])
        assert q.value == row["expect"], row


def test_numeric_score():
    for row in DATA["numericScore"]:
        assert WoodQuality(row["quality"]).numeric_score == row["expect"], row
