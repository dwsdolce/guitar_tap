"""
Global QSettings-backed settings store for GuitarTap's analysis and display
configuration.

Mirrors Swift TapDisplaySettings struct (Models/TapDisplaySettings.swift).

TapDisplaySettings is a namespace of static properties; it is never
instantiated.  Every property is a classmethod that reads from and writes to
QSettings (via AppSettings) using the same key constants as Swift.

Settings are grouped by function:
- Measurement type — which kind of analysis is active.
- Plate/brace dimensions — physical dimensions entered by the user.
- Gore thicknessing — guitar body dimensions and f_vs preset.
- Display frequency range — per-measurement-type min/max Hz for the chart.
- dB range — min/max dB for the vertical axis.
- Analysis frequency range — band within which peaks are searched.
- Peak detection — threshold, maximum peak count, hysteresis margin.
- Tap sequencing — FLC tap inclusion (measure_flc).

Python-only: storage is delegated to AppSettings (tap_settings_view.py).
Swift uses UserDefaults directly; Python uses QSettings via AppSettings.

SeeAlso: TapSettingsView, TapToneAnalyzer, SpectrumView
"""

from __future__ import annotations


def _app_settings():
    """Lazy import of AppSettings to avoid circular dependencies."""
    from views.utilities.tap_settings_view import AppSettings  # noqa: PLC0415
    return AppSettings


class TapDisplaySettings:
    """Global, QSettings-backed settings for spectrum display and analysis configuration.

    Mirrors Swift TapDisplaySettings struct (Models/TapDisplaySettings.swift).

    Never instantiated — all access is through classmethods.
    """

    # MARK: - Default Constants (mirrors Swift static let)

    # Default minimum frequency for guitar spectrum display (Hz)
    DEFAULT_MIN_FREQUENCY: float = 75.0

    # Default maximum frequency for guitar spectrum display (Hz)
    DEFAULT_MAX_FREQUENCY: float = 350.0

    # Default minimum frequency for plate spectrum display (Hz)
    DEFAULT_PLATE_MIN_FREQUENCY: float = 30.0

    # Default maximum frequency for plate spectrum display (Hz)
    DEFAULT_PLATE_MAX_FREQUENCY: float = 600.0

    # Default minimum frequency for brace spectrum display (Hz)
    DEFAULT_BRACE_MIN_FREQUENCY: float = 30.0

    # Default maximum frequency for brace spectrum display (Hz)
    DEFAULT_BRACE_MAX_FREQUENCY: float = 1000.0

    # Default minimum magnitude for spectrum display (dB)
    DEFAULT_MIN_MAGNITUDE: float = -100.0

    # Default maximum magnitude for spectrum display (dB)
    DEFAULT_MAX_MAGNITUDE: float = 0.0

    # Default minimum frequency for peak detection and analysis (Hz)
    DEFAULT_ANALYSIS_MIN_FREQUENCY: float = 30.0

    # Default maximum frequency for peak detection and analysis (Hz)
    DEFAULT_ANALYSIS_MAX_FREQUENCY: float = 2000.0

    # Default minimum magnitude threshold for peak detection (dB)
    DEFAULT_PEAK_THRESHOLD: float = -60.0

    # Default maximum number of peaks to detect and store (0 = all peaks)
    DEFAULT_MAX_PEAKS: int = 0

    # Default hop size overlap percentage
    DEFAULT_HOP_SIZE_OVERLAP: float = 0.0

    # Default tap detection threshold in dB
    DEFAULT_TAP_DETECTION_THRESHOLD: float = -40.0

    # Default hysteresis margin in dB
    DEFAULT_HYSTERESIS_MARGIN: float = 3.0

    # MARK: - Measurement Type

    @classmethod
    def measurement_type(cls) -> "MeasurementType":
        """The currently selected measurement type (persisted in QSettings).

        Mirrors Swift TapDisplaySettings.measurementType.
        """
        return _app_settings().measurement_type()

    @classmethod
    def set_measurement_type(cls, mt: "MeasurementType") -> None:
        """Mirrors Swift TapDisplaySettings.measurementType setter."""
        _app_settings().set_measurement_type(mt)

    # MARK: - Guitar Type (backward compatibility)

    @classmethod
    def guitar_type(cls) -> str:
        """The currently selected guitar type (for backward compatibility).

        Mirrors Swift TapDisplaySettings.guitarType.
        """
        return _app_settings().guitar_type()

    @classmethod
    def set_guitar_type(cls, v: str) -> None:
        """Mirrors Swift TapDisplaySettings.guitarType setter."""
        _app_settings().set_guitar_type(v)

    # MARK: - Plate Dimensions

    @classmethod
    def plate_length(cls) -> float:
        """Plate length in mm (along grain direction).

        Mirrors Swift TapDisplaySettings.plateLength.
        """
        return _app_settings().plate_length()

    @classmethod
    def set_plate_length(cls, v: float) -> None:
        _app_settings().set_plate_length(v)

    @classmethod
    def plate_width(cls) -> float:
        """Plate width in mm (cross grain direction).

        Mirrors Swift TapDisplaySettings.plateWidth.
        """
        return _app_settings().plate_width()

    @classmethod
    def set_plate_width(cls, v: float) -> None:
        _app_settings().set_plate_width(v)

    @classmethod
    def plate_thickness(cls) -> float:
        """Plate thickness in mm.

        Mirrors Swift TapDisplaySettings.plateThickness.
        """
        return _app_settings().plate_thickness()

    @classmethod
    def set_plate_thickness(cls, v: float) -> None:
        _app_settings().set_plate_thickness(v)

    @classmethod
    def plate_mass(cls) -> float:
        """Plate mass in grams.

        Mirrors Swift TapDisplaySettings.plateMass.
        """
        return _app_settings().plate_mass()

    @classmethod
    def set_plate_mass(cls, v: float) -> None:
        _app_settings().set_plate_mass(v)

    # MARK: - Gore Thicknessing Settings

    @classmethod
    def guitar_body_length(cls) -> float:
        """Guitar body length (neck join to tail, finished dimensions) in mm.

        Mirrors Swift TapDisplaySettings.guitarBodyLength.
        """
        return _app_settings().guitar_body_length()

    @classmethod
    def set_guitar_body_length(cls, v: float) -> None:
        _app_settings().set_guitar_body_length(v)

    @classmethod
    def guitar_body_width(cls) -> float:
        """Guitar lower bout width (finished dimensions) in mm.

        Mirrors Swift TapDisplaySettings.guitarBodyWidth.
        """
        return _app_settings().guitar_body_width()

    @classmethod
    def set_guitar_body_width(cls, v: float) -> None:
        _app_settings().set_guitar_body_width(v)

    @classmethod
    def plate_stiffness_preset(cls) -> str:
        """Selected plate vibrational stiffness preset.

        Mirrors Swift TapDisplaySettings.plateStiffnessPreset.
        """
        return _app_settings().plate_stiffness_preset()

    @classmethod
    def set_plate_stiffness_preset(cls, v: str) -> None:
        _app_settings().set_plate_stiffness_preset(v)

    @classmethod
    def custom_plate_stiffness(cls) -> float:
        """Custom plate vibrational stiffness value (used when preset is 'Custom').

        Mirrors Swift TapDisplaySettings.customPlateStiffness.
        """
        return _app_settings().custom_plate_stiffness()

    @classmethod
    def set_custom_plate_stiffness(cls, v: float) -> None:
        _app_settings().set_custom_plate_stiffness(v)

    # MARK: - Brace Dimensions

    @classmethod
    def brace_length(cls) -> float:
        """Brace length in mm (along grain direction).

        Mirrors Swift TapDisplaySettings.braceLength.
        """
        return _app_settings().brace_length()

    @classmethod
    def set_brace_length(cls, v: float) -> None:
        _app_settings().set_brace_length(v)

    @classmethod
    def brace_width(cls) -> float:
        """Brace width in mm (across grain).

        Mirrors Swift TapDisplaySettings.braceWidth.
        """
        return _app_settings().brace_width()

    @classmethod
    def set_brace_width(cls, v: float) -> None:
        _app_settings().set_brace_width(v)

    @classmethod
    def brace_thickness(cls) -> float:
        """Brace height in mm — the vertical cross-section (t in the formula).

        Mirrors Swift TapDisplaySettings.braceThickness.
        """
        return _app_settings().brace_thickness()

    @classmethod
    def set_brace_thickness(cls, v: float) -> None:
        _app_settings().set_brace_thickness(v)

    @classmethod
    def brace_mass(cls) -> float:
        """Brace mass in grams.

        Mirrors Swift TapDisplaySettings.braceMass.
        """
        return _app_settings().brace_mass()

    @classmethod
    def set_brace_mass(cls, v: float) -> None:
        _app_settings().set_brace_mass(v)

    # MARK: - Unknown Mode Display

    @classmethod
    def show_unknown_modes(cls) -> bool:
        """Whether to display/report peaks classified as 'Unknown' mode.

        Mirrors Swift TapDisplaySettings.showUnknownModes.
        """
        return _app_settings().show_unknown_modes()

    @classmethod
    def set_show_unknown_modes(cls, v: bool) -> None:
        _app_settings().set_show_unknown_modes(v)

    # MARK: - Annotation Visibility Mode

    @classmethod
    def annotation_visibility_mode(cls) -> str:
        """The last-used annotation visibility mode ('Selected', 'None', or 'All').

        Mirrors Swift TapDisplaySettings.annotationVisibilityMode.
        """
        return _app_settings().annotation_visibility_mode()

    @classmethod
    def set_annotation_visibility_mode(cls, mode: str) -> None:
        """Mirrors Swift TapDisplaySettings.annotationVisibilityMode setter."""
        _app_settings().set_annotation_visibility_mode(mode)

    # MARK: - Display Frequency Range

    @classmethod
    def default_min_frequency(cls, meas_type: "str | object | None" = None) -> float:
        """Default minimum display frequency for the given measurement type (Hz).

        Mirrors Swift TapDisplaySettings.defaultMinFrequency(for:).
        """
        if meas_type is None:
            return cls.DEFAULT_MIN_FREQUENCY
        return float(_app_settings().default_f_min(meas_type))

    @classmethod
    def default_max_frequency(cls, meas_type: "str | object | None" = None) -> float:
        """Default maximum display frequency for the given measurement type (Hz).

        Mirrors Swift TapDisplaySettings.defaultMaxFrequency(for:).
        """
        if meas_type is None:
            return cls.DEFAULT_MAX_FREQUENCY
        return float(_app_settings().default_f_max(meas_type))

    @classmethod
    def min_frequency(cls, meas_type: "str | object | None" = None) -> float:
        """Persisted minimum frequency for display (Hz).

        Mirrors Swift TapDisplaySettings.minFrequency(for:) and .minFrequency.
        """
        if meas_type is None:
            meas_type = cls.measurement_type()
        return float(_app_settings().f_min(meas_type))

    @classmethod
    def set_min_frequency(cls, v: float, meas_type: "str | object | None" = None) -> None:
        """Mirrors Swift TapDisplaySettings.setMinFrequency(_:for:)."""
        if meas_type is None:
            meas_type = cls.measurement_type()
        _app_settings().set_f_min(int(v), meas_type)

    @classmethod
    def max_frequency(cls, meas_type: "str | object | None" = None) -> float:
        """Persisted maximum frequency for display (Hz).

        Mirrors Swift TapDisplaySettings.maxFrequency(for:) and .maxFrequency.
        """
        if meas_type is None:
            meas_type = cls.measurement_type()
        return float(_app_settings().f_max(meas_type))

    @classmethod
    def set_max_frequency(cls, v: float, meas_type: "str | object | None" = None) -> None:
        """Mirrors Swift TapDisplaySettings.setMaxFrequency(_:for:)."""
        if meas_type is None:
            meas_type = cls.measurement_type()
        _app_settings().set_f_max(int(v), meas_type)

    # MARK: - dB Range

    @classmethod
    def min_magnitude(cls) -> float:
        """Persisted minimum magnitude for display (dB).

        Mirrors Swift TapDisplaySettings.minMagnitude.
        """
        return _app_settings().db_min()

    @classmethod
    def set_min_magnitude(cls, v: float) -> None:
        _app_settings().set_db_min(v)

    @classmethod
    def max_magnitude(cls) -> float:
        """Persisted maximum magnitude for display (dB).

        Mirrors Swift TapDisplaySettings.maxMagnitude.
        """
        return _app_settings().db_max()

    @classmethod
    def set_max_magnitude(cls, v: float) -> None:
        _app_settings().set_db_max(v)

    # MARK: - Analysis Frequency Range

    @classmethod
    def analysis_min_frequency(cls) -> float:
        """Persisted minimum frequency for analysis (Hz).

        Mirrors Swift TapDisplaySettings.analysisMinFrequency.
        """
        return _app_settings().analysis_f_min()

    @classmethod
    def set_analysis_min_frequency(cls, v: float) -> None:
        _app_settings().set_analysis_f_min(v)

    @classmethod
    def analysis_max_frequency(cls) -> float:
        """Persisted maximum frequency for analysis (Hz).

        Mirrors Swift TapDisplaySettings.analysisMaxFrequency.
        """
        return _app_settings().analysis_f_max()

    @classmethod
    def set_analysis_max_frequency(cls, v: float) -> None:
        _app_settings().set_analysis_f_max(v)

    # MARK: - Peak Detection

    @classmethod
    def peak_threshold(cls) -> float:
        """Persisted peak threshold (dB).

        Mirrors Swift TapDisplaySettings.peakThreshold.
        """
        return _app_settings().peak_threshold()

    @classmethod
    def set_peak_threshold(cls, v: float) -> None:
        _app_settings().set_peak_threshold(v)

    @classmethod
    def max_peaks(cls) -> int:
        """Persisted maximum number of peaks to detect and store (0 = all).

        Mirrors Swift TapDisplaySettings.maxPeaks.
        """
        return _app_settings().max_peaks()

    @classmethod
    def set_max_peaks(cls, v: int) -> None:
        _app_settings().set_max_peaks(v)

    # MARK: - FFT Settings

    @classmethod
    def hop_size_overlap(cls) -> float:
        """Persisted hop size overlap percentage.

        Mirrors Swift TapDisplaySettings.hopSizeOverlap.
        """
        return _app_settings().hop_size_overlap()

    @classmethod
    def set_hop_size_overlap(cls, v: float) -> None:
        _app_settings().set_hop_size_overlap(v)

    # MARK: - Tap Detection

    @classmethod
    def tap_detection_threshold(cls) -> float:
        """Persisted tap detection threshold (dB).

        Mirrors Swift TapDisplaySettings.tapDetectionThreshold.
        """
        return _app_settings().tap_threshold()

    @classmethod
    def set_tap_detection_threshold(cls, v: float) -> None:
        _app_settings().set_tap_threshold(int(v))

    @classmethod
    def hysteresis_margin(cls) -> float:
        """Persisted hysteresis margin (dB).

        Mirrors Swift TapDisplaySettings.hysteresisMargin.
        """
        return _app_settings().hysteresis_margin()

    @classmethod
    def set_hysteresis_margin(cls, v: float) -> None:
        _app_settings().set_hysteresis_margin(v)

    @classmethod
    def measure_flc(cls) -> bool:
        """Whether to perform the optional FLC (diagonal/shear) tap measurement.

        Mirrors Swift TapDisplaySettings.measureFlc.
        """
        return _app_settings().measure_flc()

    @classmethod
    def set_measure_flc(cls, v: bool) -> None:
        _app_settings().set_measure_flc(v)

    # MARK: - Validation

    @classmethod
    def validate_frequency_range(cls, min_freq: float, max_freq: float) -> tuple[float, float]:
        """Validate and clamp a frequency range.

        Mirrors Swift TapDisplaySettings.validateFrequencyRange(minFreq:maxFreq:).
        Returns (min, max) — falls back to persisted display range if invalid.
        """
        clamped_min = max(20.0, min(min_freq, 20000.0))
        clamped_max = max(20.0, min(max_freq, 20000.0))
        if clamped_min < clamped_max and (clamped_max - clamped_min) >= 10.0:
            return (clamped_min, clamped_max)
        return (cls.min_frequency(), cls.max_frequency())

    @classmethod
    def validate_magnitude_range(cls, min_db: float, max_db: float) -> tuple[float, float]:
        """Validate and clamp a magnitude range.

        Mirrors Swift TapDisplaySettings.validateMagnitudeRange(minDB:maxDB:).
        Returns (min, max) — falls back to persisted dB range if invalid.
        """
        clamped_min = max(-120.0, min(min_db, 20.0))
        clamped_max = max(-120.0, min(max_db, 20.0))
        if clamped_min < clamped_max and (clamped_max - clamped_min) >= 10.0:
            return (clamped_min, clamped_max)
        return (cls.min_magnitude(), cls.max_magnitude())

    # MARK: - Reset to Defaults

    @classmethod
    def reset_to_defaults(cls) -> None:
        """Reset all persisted settings to their default values.

        Mirrors Swift TapDisplaySettings.resetToDefaults().
        """
        s = _app_settings()
        s.set_guitar_type("acoustic")
        s.set_show_unknown_modes(True)
        s.set_f_min(int(cls.DEFAULT_MIN_FREQUENCY))
        s.set_f_max(int(cls.DEFAULT_MAX_FREQUENCY))
        s.set_db_min(cls.DEFAULT_MIN_MAGNITUDE)
        s.set_db_max(cls.DEFAULT_MAX_MAGNITUDE)
        s.set_analysis_f_min(cls.DEFAULT_ANALYSIS_MIN_FREQUENCY)
        s.set_analysis_f_max(cls.DEFAULT_ANALYSIS_MAX_FREQUENCY)
        s.set_peak_threshold(cls.DEFAULT_PEAK_THRESHOLD)
        s.set_max_peaks(cls.DEFAULT_MAX_PEAKS)
        s.set_hop_size_overlap(cls.DEFAULT_HOP_SIZE_OVERLAP)
        s.set_tap_threshold(int(cls.DEFAULT_TAP_DETECTION_THRESHOLD))
        s.set_hysteresis_margin(cls.DEFAULT_HYSTERESIS_MARGIN)
        s.set_measure_flc(False)

    # MARK: - Legacy aliases (Python-only, for backward compatibility)
    # These alias the old AppSettings method names used by model files.

    @classmethod
    def analysis_f_min(cls) -> float:
        """Legacy alias for analysis_min_frequency()."""
        return cls.analysis_min_frequency()

    @classmethod
    def analysis_f_max(cls) -> float:
        """Legacy alias for analysis_max_frequency()."""
        return cls.analysis_max_frequency()

    @classmethod
    def tap_threshold(cls) -> float:
        """Legacy alias for tap_detection_threshold()."""
        return cls.tap_detection_threshold()
