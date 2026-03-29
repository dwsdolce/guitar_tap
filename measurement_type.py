"""
MeasurementType — mirrors the Swift MeasurementType enum in TapDisplaySettings.swift.

Five measurement types are defined: three guitar types (Classical, Flamenco, Acoustic)
and two material types (Plate, Brace).  Guitar types map 1-to-1 with GuitarType so
the two enums can be converted to each other.
"""

from __future__ import annotations

from enum import Enum

import guitar_type as gt


class MeasurementType(Enum):
    CLASSICAL = "Classical Guitar"
    FLAMENCO  = "Flamenco Guitar"
    ACOUSTIC  = "Acoustic Guitar"
    PLATE     = "Material (Plate)"
    BRACE     = "Material (Brace)"

    # ── display ──────────────────────────────────────────────────────────────

    @property
    def short_name(self) -> str:
        """Short label used in badges and compact UI."""
        return {
            MeasurementType.CLASSICAL: "Classical",
            MeasurementType.FLAMENCO:  "Flamenco",
            MeasurementType.ACOUSTIC:  "Acoustic",
            MeasurementType.PLATE:     "Plate",
            MeasurementType.BRACE:     "Brace",
        }[self]

    @property
    def description(self) -> str:
        return {
            MeasurementType.CLASSICAL: "Nylon string, fan-braced, deep body",
            MeasurementType.FLAMENCO:  "Nylon string, light bracing, shallow body",
            MeasurementType.ACOUSTIC:  "Steel string, X-braced (Dreadnought, OM, etc.)",
            MeasurementType.PLATE:     "Rectangular wood plate for calculating stiffness and sound radiation",
            MeasurementType.BRACE:     "Brace strip — longitudinal stiffness (fL only)",
        }[self]

    # ── classification ────────────────────────────────────────────────────────

    @property
    def is_guitar(self) -> bool:
        return self in (
            MeasurementType.CLASSICAL,
            MeasurementType.FLAMENCO,
            MeasurementType.ACOUSTIC,
        )

    @property
    def is_brace(self) -> bool:
        return self is MeasurementType.BRACE

    # ── conversion ────────────────────────────────────────────────────────────

    @property
    def guitar_type(self) -> gt.GuitarType | None:
        """Return the corresponding GuitarType, or None for plate/brace."""
        return {
            MeasurementType.CLASSICAL: gt.GuitarType.CLASSICAL,
            MeasurementType.FLAMENCO:  gt.GuitarType.FLAMENCO,
            MeasurementType.ACOUSTIC:  gt.GuitarType.ACOUSTIC,
        }.get(self)

    @staticmethod
    def from_guitar_type(guitar_type: gt.GuitarType) -> MeasurementType:
        return {
            gt.GuitarType.CLASSICAL: MeasurementType.CLASSICAL,
            gt.GuitarType.FLAMENCO:  MeasurementType.FLAMENCO,
            gt.GuitarType.ACOUSTIC:  MeasurementType.ACOUSTIC,
        }[guitar_type]

    @property
    def storage_key(self) -> str:
        """Key fragment used in QSettings — guitar types share 'Guitar' so that
        saved view settings are not broken when the user switches guitar type."""
        return "Guitar" if self.is_guitar else self.short_name

    @staticmethod
    def from_string(s: str) -> "MeasurementType":
        """Resolve from any string form (Swift raw value, short name, combo text, etc.).

        Handles: "plate", "Plate", "Material (Plate)", "brace", "Brace",
        "Material (Brace)", "classicalGuitar", "Classical Guitar",
        "Classical", "flamencoGuitar", "Flamenco Guitar", "acousticGuitar", etc.
        """
        lower = s.lower().strip()
        if "plate" in lower:
            return MeasurementType.PLATE
        if "brace" in lower:
            return MeasurementType.BRACE
        if "flamenco" in lower:
            return MeasurementType.FLAMENCO
        if "acoustic" in lower:
            return MeasurementType.ACOUSTIC
        # Default guitar → classical
        return MeasurementType.CLASSICAL

    @staticmethod
    def from_combo_values(measurement: str, guitar_type: str) -> MeasurementType:
        """Resolve from the two legacy combo-box string values used in guitar_tap.py."""
        if measurement == "Plate":
            return MeasurementType.PLATE
        if measurement == "Brace":
            return MeasurementType.BRACE
        # Guitar — distinguish by guitar_type combo
        try:
            return MeasurementType.from_guitar_type(gt.GuitarType(guitar_type))
        except (ValueError, KeyError):
            return MeasurementType.CLASSICAL
