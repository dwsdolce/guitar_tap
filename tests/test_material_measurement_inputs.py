# @parity test/material-measurement-inputs
"""The two-store material-dimensions model — Python mirror of Swift MaterialMeasurementInputsTests.

A measurement's own dimensions (Store B, ``TapToneAnalyzer.material_inputs``) are seeded from the
Settings template (Store A) at completion, restored from the file's snapshot on load, and — crucially —
loading NEVER writes the Settings defaults (the origin bug this design fixes). Also covers notes-on-load
(R10).

These are the *sourcing* invariants that existing tests don't cover: material_properties tests the calc
math (dims passed in directly) and test_measurement_codable tests the format round-trip — neither
exercises where the dimensions come from. See GuitarTapWeb/Development/MEASUREMENT-DIMENSIONS-SPEC.md.
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType
from models.plate_stiffness_preset import PlateStiffnessPreset
from models.spectrum_snapshot import SpectrumSnapshot
from models.tap_tone_measurement import TapToneMeasurement


_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(autouse=True)
def qt_app():
    return _get_app()


def _make_sut() -> TapToneAnalyzer:
    _get_app()
    return TapToneAnalyzer()


def _plate_measurement(
    notes: str | None = None,
    length: float = 111, width: float = 222,
    thickness: float = 3.33, mass: float = 44,
    body_length: float = 480, body_width: float = 370,
    preset: PlateStiffnessPreset = PlateStiffnessPreset.CLASSICAL_TOP,
) -> TapToneMeasurement:
    """A minimal loadable plate measurement whose snapshot carries its own dimensions."""
    snap = SpectrumSnapshot(
        frequencies=[100, 200], magnitudes=[-10, -20],
        min_freq=50, max_freq=300, min_db=-100, max_db=0,
        measurement_type=MeasurementType.PLATE.value,
        plate_length=length, plate_width=width, plate_thickness=thickness, plate_mass=mass,
        guitar_body_length=body_length, guitar_body_width=body_width,
        plate_stiffness_preset=preset.value, custom_plate_stiffness=60,
    )
    return TapToneMeasurement.create(
        peaks=[], notes=notes,
        measurement_type=MeasurementType.PLATE.value,
        longitudinal_snapshot=snap,
    )


# ── Seed at complete ────────────────────────────────────────────────────────

def test_seeds_store_b_from_settings_when_plate_completes():
    TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
    TapDisplaySettings.set_plate_length(501)
    TapDisplaySettings.set_plate_width(201)
    TapDisplaySettings.set_plate_thickness(4.5)
    TapDisplaySettings.set_plate_mass(210)
    TapDisplaySettings.set_plate_stiffness_preset(PlateStiffnessPreset.CLASSICAL_TOP.value)
    sut = _make_sut()
    assert sut.material_inputs is None              # None until the measurement completes
    sut.set_measurement_complete(True)
    mi = sut.material_inputs
    assert mi is not None
    assert mi.length_mm == 501
    assert mi.width_mm == 201
    assert mi.thickness_mm == 4.5
    assert mi.mass_g == 210
    assert mi.stiffness_preset == PlateStiffnessPreset.CLASSICAL_TOP


def test_does_not_seed_store_b_for_guitar():
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    sut = _make_sut()
    sut.set_measurement_complete(True)
    assert sut.material_inputs is None              # guitar has no material dimensions


def test_does_not_seed_store_b_while_loading():
    TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
    sut = _make_sut()
    sut.is_loading_measurement = True
    sut.set_measurement_complete(True)              # the load path sets complete; the seed must be
    assert sut.material_inputs is None              # suppressed — load sets Store B from the snapshot
    sut.is_loading_measurement = False


# ── Load sets Store B without clobbering Settings (the origin bug) ────────────

def test_load_sets_store_b_from_snapshot_and_leaves_settings_untouched():
    TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
    # Store A (the template) — deliberately DIFFERENT from the measurement's own dims.
    TapDisplaySettings.set_plate_length(999)
    TapDisplaySettings.set_plate_width(999)
    TapDisplaySettings.set_plate_thickness(9.9)
    TapDisplaySettings.set_plate_mass(999)

    sut = _make_sut()
    sut.load_measurement(_plate_measurement())

    # Store B carries the measurement's OWN dimensions.
    mi = sut.material_inputs
    assert mi is not None
    assert mi.length_mm == 111
    assert mi.width_mm == 222
    assert mi.thickness_mm == 3.33
    assert mi.mass_g == 44
    assert mi.body_length_mm == 480
    assert mi.body_width_mm == 370
    assert mi.stiffness_preset == PlateStiffnessPreset.CLASSICAL_TOP

    # The Settings template (Store A) is UNTOUCHED — the invariant the de-clobber restored.
    assert TapDisplaySettings.plate_length() == 999
    assert TapDisplaySettings.plate_width() == 999
    assert TapDisplaySettings.plate_thickness() == 9.9
    assert TapDisplaySettings.plate_mass() == 999


# ── Notes on load (R10) ───────────────────────────────────────────────────────

def test_load_restores_notes_for_resave():
    TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
    sut = _make_sut()
    sut.load_measurement(_plate_measurement(notes="spruce, tight grain"))
    assert sut.loaded_notes == "spruce, tight grain"


def test_load_treats_blank_notes_as_none():
    TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
    sut = _make_sut()
    sut.load_measurement(_plate_measurement(notes=""))
    assert sut.loaded_notes is None