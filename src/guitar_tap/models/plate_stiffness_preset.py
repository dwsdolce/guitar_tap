"""
Named vibrational stiffness (f_vs) presets for Gore Equation 4.5-7.

Mirrors Swift PlateStiffnessPreset enum (PlateStiffnessPreset.swift).

The Gore target thickness formula requires a vibrational stiffness
parameter that varies by instrument type and plate role.  The CUSTOM
case defers to a user-supplied value stored in settings.

Reference values (f_vs):
- Steel-string top:  75
- Steel-string back: 55
- Classical top:     60
- Classical back:    50
"""

from __future__ import annotations
from enum import Enum


class PlateStiffnessPreset(Enum):
    STEEL_STRING_TOP  = "Steel String Top"
    STEEL_STRING_BACK = "Steel String Back"
    CLASSICAL_TOP     = "Classical Top"
    CLASSICAL_BACK    = "Classical Back"
    CUSTOM            = "Custom"

    # MARK: - Vibrational Stiffness Value

    @property
    def stiffness(self) -> float:
        """The vibrational stiffness value (f_vs) for this preset.

        Returns 0 for CUSTOM; callers should use the user-entered custom value in that case.

        Mirrors Swift PlateStiffnessPreset.value.
        """
        return {
            PlateStiffnessPreset.STEEL_STRING_TOP:  75.0,
            PlateStiffnessPreset.STEEL_STRING_BACK: 55.0,
            PlateStiffnessPreset.CLASSICAL_TOP:     60.0,
            PlateStiffnessPreset.CLASSICAL_BACK:    50.0,
            PlateStiffnessPreset.CUSTOM:             0.0,
        }[self]

    # MARK: - Display

    @property
    def short_name(self) -> str:
        """Compact name used in the settings picker.

        Mirrors Swift PlateStiffnessPreset.shortName.
        """
        return {
            PlateStiffnessPreset.STEEL_STRING_TOP:  "SS Top (75)",
            PlateStiffnessPreset.STEEL_STRING_BACK: "SS Back (55)",
            PlateStiffnessPreset.CLASSICAL_TOP:     "Classical Top (60)",
            PlateStiffnessPreset.CLASSICAL_BACK:    "Classical Back (50)",
            PlateStiffnessPreset.CUSTOM:            "Custom",
        }[self]
