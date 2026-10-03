"""Reading a material case file (plate.json, brace.json): samples, and the shared tolerance."""

from __future__ import annotations

import json
import os

from guitar_tap.models.material_properties import MaterialDimensions


def load(name: str) -> dict:
    with open(os.path.join(os.path.dirname(__file__), f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def dimensions(row: dict) -> MaterialDimensions:
    s = row["sample"]
    return MaterialDimensions(
        length_mm=s["lengthMm"], width_mm=s["widthMm"], thickness_mm=s["thicknessMm"], mass_g=s["massG"]
    )


def close(actual: float, expected: float, data: dict) -> bool:
    """|actual - expected| <= relative * |expected| + absolute, from the file's tolerance."""
    tol = data["tolerance"]
    return abs(actual - expected) <= tol["relative"] * abs(expected) + tol["absolute"]
