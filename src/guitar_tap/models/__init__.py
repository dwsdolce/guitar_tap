"""
Data models package — mirrors the Swift GuitarTap Models group.

Each module in this package corresponds to a Swift source file in
GuitarTap/Models/.  Import directly from the submodules or use the
convenience re-exports provided here.

Data model modules (safe to import anywhere):
  analysis_display_mode  → AnalysisDisplayMode
  audio_device           → AudioDevice
  guitar_type            → GuitarType, ModeRanges, DecayThresholds
  guitar_mode            → GuitarMode, get_bands, in_mode_range, ...
  material_properties    → PlateDimensions, PlateProperties, BraceProperties
  material_tap_phase     → MaterialTapPhase
  measurement_type       → MeasurementType
  pitch                  → Pitch
  plate_stiffness_preset → PlateStiffnessPreset
  microphone_calibration → MicrophoneCalibration, CalibrationStorage
  resonant_peak          → ResonantPeak
  spectrum_snapshot      → SpectrumSnapshot
  tap_display_settings   → TapDisplaySettings
  tap_tone_measurement   → TapToneMeasurement
  user_assigned_mode     → UserAssignedMode

Analyser modules (NOT imported here — import directly to avoid circular deps):
  realtime_fft_analyzer  → RealtimeFFTAnalyzer (Microphone alias), dft_anal, ...
  tap_tone_analyzer      → TapToneAnalyzer, AnalysisDisplayMode, ...
"""

from .analysis_display_mode import AnalysisDisplayMode
from .audio_device import AudioDevice
from .guitar_type import GuitarType, ModeRanges, DecayThresholds
from .guitar_mode import GuitarMode, get_bands, in_mode_range, classify_peak, mode_display_name
from .material_tap_phase import MaterialTapPhase
from .measurement_type import MeasurementType
from .pitch import Pitch
from .plate_stiffness_preset import PlateStiffnessPreset
from .microphone_calibration import MicrophoneCalibration, CalibrationStorage
from .resonant_peak import ResonantPeak
from .spectrum_snapshot import SpectrumSnapshot
from .tap_tone_measurement import TapToneMeasurement
from .user_assigned_mode import UserAssignedMode

__all__ = [
    # Models
    "AnalysisDisplayMode",
    "AudioDevice",
    "GuitarType", "ModeRanges", "DecayThresholds",
    "GuitarMode", "get_bands", "in_mode_range", "classify_peak", "mode_display_name",
    "MaterialTapPhase",
    "MeasurementType",
    "Pitch",
    "PlateStiffnessPreset",
    "MicrophoneCalibration", "CalibrationStorage",
    "ResonantPeak",
    "SpectrumSnapshot",
    "TapToneMeasurement",
    "UserAssignedMode",
]
