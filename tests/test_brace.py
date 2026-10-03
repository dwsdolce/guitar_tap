# @parity test/brace
"""Brace material properties (BraceProperties) against the shared case file, ``brace.json`` — the same
cases the Swift and web suites run."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from guitar_tap.models.material_properties import BraceProperties  # noqa: E402
import material_cases  # noqa: E402

DATA = material_cases.load("brace")


@pytest.mark.parametrize("row", DATA["braces"], ids=lambda r: r["id"])
def test_brace(row):
    e = row["expect"]
    dims = material_cases.dimensions(row)
    p = BraceProperties(dims, row["fL"])
    numbers = {
        "volume": dims.volume(), "density": dims.density(), "densityGPerCm3": dims.density_g_per_cm3(),
        "youngsModulusLong": p.youngsModulusLong, "youngsModulusLongGPa": p.youngsModulusLongGPa,
        "speedOfSoundLong": p.c_long_m_s, "specificModulusLong": p.specific_modulus,
        "radiationRatioLong": p.radiation_ratio,
    }
    for name, value in numbers.items():
        assert material_cases.close(value, e[name], DATA), f"{name}: {value} != {e[name]}"
    assert p.quality == e["spruceQuality"]
