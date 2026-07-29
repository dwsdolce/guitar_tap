# @parity model/material-measurement-inputs tests=test/material-measurement-inputs
"""
The material inputs of the **current measurement** — "Store B" in the measurement-dimensions
design (GuitarTapWeb/Development/MEASUREMENT-DIMENSIONS-SPEC.md).

Mirrors Swift MaterialMeasurementInputs.swift.

This is the *sole* source for a material measurement's derived properties, its Results-panel
display/edit, and Save. It is distinct from TapDisplaySettings, which holds only the **defaults
for a new measurement** (Store A). A measurement's values are seeded from the settings *at
completion*, restored from the file's snapshot on load, and edited in the Results panel — none of
which touch the settings. The analyzer holds it as ``material_inputs`` (``None`` for guitar, and
before a material measurement completes).
"""

from __future__ import annotations

from dataclasses import dataclass

from .material_properties import MaterialDimensions
from .plate_stiffness_preset import PlateStiffnessPreset


@dataclass
class MaterialMeasurementInputs:
    length_mm: float
    width_mm: float
    thickness_mm: float
    mass_g: float
    # Plate-only (Gore target thickness); carried but unused for brace. These affect only the
    # calculated Gore target thickness — nothing about capture — so they are editable per-measurement.
    # (measure_flc is deliberately NOT here: it decides *at capture* whether the FLC phase is tapped;
    # the completed calc then keys on whether an FLC peak was captured, not on this flag. Editing it
    # post-capture could only *ignore a captured FLC* — not worth supporting — so it stays a
    # Settings-only capture setting.)
    body_length_mm: float
    body_width_mm: float
    stiffness_preset: PlateStiffnessPreset
    custom_stiffness: float

    @property
    def dimensions(self) -> MaterialDimensions:
        """The four sample dimensions as a MaterialDimensions for the property calculations."""
        return MaterialDimensions(
            length_mm=self.length_mm,
            width_mm=self.width_mm,
            thickness_mm=self.thickness_mm,
            mass_g=self.mass_g,
        )

    @property
    def stiffness(self) -> float:
        """Effective vibrational stiffness f_vs — the custom value when the preset is Custom, else
        the preset's value. Mirrors Swift MaterialMeasurementInputs.stiffness / TapDisplaySettings.plateStiffness.
        """
        if self.stiffness_preset == PlateStiffnessPreset.CUSTOM:
            return self.custom_stiffness
        return self.stiffness_preset.stiffness

    @staticmethod
    def from_settings(measurement_type) -> "MaterialMeasurementInputs":
        """Snapshot the current Settings defaults (Store A) for a measurement of ``measurement_type``
        — used to seed the measurement's own values when it completes. Mirrors Swift ``fromSettings(for:)``.
        """
        from .tap_display_settings import TapDisplaySettings as TDS

        brace = measurement_type.is_brace
        try:
            preset = PlateStiffnessPreset(TDS.plate_stiffness_preset())
        except ValueError:
            preset = PlateStiffnessPreset.CUSTOM
        return MaterialMeasurementInputs(
            length_mm=TDS.brace_length() if brace else TDS.plate_length(),
            width_mm=TDS.brace_width() if brace else TDS.plate_width(),
            thickness_mm=TDS.brace_thickness() if brace else TDS.plate_thickness(),
            mass_g=TDS.brace_mass() if brace else TDS.plate_mass(),
            body_length_mm=TDS.guitar_body_length(),
            body_width_mm=TDS.guitar_body_width(),
            stiffness_preset=preset,
            custom_stiffness=TDS.custom_plate_stiffness(),
        )
