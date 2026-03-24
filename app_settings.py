"""
    Persistent application settings backed by QSettings.
"""

from __future__ import annotations
from PyQt6 import QtCore


def _meas_key(meas_type) -> str:
    """Return the storage-key string for a measurement type argument.

    Accepts either a MeasurementType enum value or a plain string
    (e.g. the legacy combo-box text "Guitar", "Plate", "Brace").
    Importing here avoids a circular dependency at module load time.
    """
    try:
        from measurement_type import MeasurementType  # noqa: PLC0415
        if isinstance(meas_type, MeasurementType):
            return meas_type.storage_key
    except ImportError:
        pass
    return str(meas_type)


class AppSettings:
    """Read/write persistent settings using QSettings.

    All values are accessed via class-level properties so callers never
    construct the QSettings object themselves.
    """

    _ORG = "Dolcesfogato"
    _APP = "GuitarTap"

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def _s(cls) -> QtCore.QSettings:
        return QtCore.QSettings(cls._ORG, cls._APP)

    @classmethod
    def _get(cls, key: str, default):
        return cls._s().value(key, default)

    @classmethod
    def _set(cls, key: str, value) -> None:
        cls._s().setValue(key, value)

    # ------------------------------------------------------------------ #
    # Display frequency range (per-measurement-type keys)
    # ------------------------------------------------------------------ #
    @classmethod
    def default_f_min(cls, meas_type: "str | object" = "") -> int:
        """Factory default fmin — does not read QSettings."""
        key_str = _meas_key(meas_type)
        return 30 if key_str in ("Plate", "Brace") else 75

    @classmethod
    def default_f_max(cls, meas_type: "str | object" = "") -> int:
        """Factory default fmax — does not read QSettings."""
        key_str = _meas_key(meas_type)
        return {"Plate": 600, "Brace": 1000}.get(key_str, 350)

    @classmethod
    def default_db_min(cls) -> float:
        return -100.0

    @classmethod
    def default_db_max(cls) -> float:
        return 0.0

    @classmethod
    def f_min(cls, meas_type: "str | object" = "") -> int:
        key_str = _meas_key(meas_type)
        key = f"display/f_min_{key_str}" if key_str else "display/f_min"
        default = cls.default_f_min(meas_type)
        return int(cls._get(key, default))

    @classmethod
    def set_f_min(cls, v: int, meas_type: "str | object" = "") -> None:
        key_str = _meas_key(meas_type)
        key = f"display/f_min_{key_str}" if key_str else "display/f_min"
        cls._set(key, v)

    @classmethod
    def f_max(cls, meas_type: "str | object" = "") -> int:
        key_str = _meas_key(meas_type)
        key = f"display/f_max_{key_str}" if key_str else "display/f_max"
        default = cls.default_f_max(meas_type)
        return int(cls._get(key, default))

    @classmethod
    def set_f_max(cls, v: int, meas_type: "str | object" = "") -> None:
        key_str = _meas_key(meas_type)
        key = f"display/f_max_{key_str}" if key_str else "display/f_max"
        cls._set(key, v)

    # ------------------------------------------------------------------ #
    # Display magnitude range (dB)
    # ------------------------------------------------------------------ #
    @classmethod
    def db_min(cls) -> float:
        v = cls._get("display/db_min", None)
        return float(v) if v is not None else -100.0

    @classmethod
    def set_db_min(cls, v: float) -> None:
        cls._set("display/db_min", v)

    @classmethod
    def db_max(cls) -> float:
        v = cls._get("display/db_max", None)
        return float(v) if v is not None else 0.0

    @classmethod
    def set_db_max(cls, v: float) -> None:
        cls._set("display/db_max", v)

    # ------------------------------------------------------------------ #
    # Peak-detection threshold (0–100 scale, 50 → −50 dBFS)
    # ------------------------------------------------------------------ #
    @classmethod
    def threshold(cls) -> int:
        return int(cls._get("analysis/threshold", 40))

    @classmethod
    def set_threshold(cls, v: int) -> None:
        cls._set("analysis/threshold", v)

    # ------------------------------------------------------------------ #
    # Audio device
    # ------------------------------------------------------------------ #
    @classmethod
    def device_name(cls) -> str:
        return str(cls._get("audio/device_name", ""))

    @classmethod
    def set_device_name(cls, name: str) -> None:
        cls._set("audio/device_name", name)

    # ------------------------------------------------------------------ #
    # Guitar type
    # ------------------------------------------------------------------ #
    @classmethod
    def guitar_type(cls) -> str:
        return str(cls._get("analysis/guitar_type", "Classical"))

    @classmethod
    def set_guitar_type(cls, v: str) -> None:
        cls._set("analysis/guitar_type", v)

    # ------------------------------------------------------------------ #
    # Show unknown modes (guitar only)
    # ------------------------------------------------------------------ #
    @classmethod
    def show_unknown_modes(cls) -> bool:
        v = cls._get("analysis/show_unknown_modes", None)
        return bool(v) if v is not None else True

    @classmethod
    def set_show_unknown_modes(cls, v: bool) -> None:
        cls._set("analysis/show_unknown_modes", v)

    # ------------------------------------------------------------------ #
    # Tap-detection threshold (0–100 scale, 60 → −40 dBFS)
    # ------------------------------------------------------------------ #
    @classmethod
    def tap_threshold(cls) -> int:
        return int(cls._get("analysis/tap_threshold", 40))

    @classmethod
    def set_tap_threshold(cls, v: int) -> None:
        cls._set("analysis/tap_threshold", v)

    # ------------------------------------------------------------------ #
    # Tap-detection hysteresis margin (dB, 1–10)
    # ------------------------------------------------------------------ #
    @classmethod
    def hysteresis_margin(cls) -> float:
        v = cls._get("analysis/hysteresis_margin", None)
        return float(v) if v is not None else 3.0

    @classmethod
    def set_hysteresis_margin(cls, v: float) -> None:
        cls._set("analysis/hysteresis_margin", v)

    # ------------------------------------------------------------------ #
    # Analysis frequency range
    # ------------------------------------------------------------------ #
    @classmethod
    def analysis_f_min(cls) -> float:
        v = cls._get("analysis/analysis_f_min", None)
        return float(v) if v is not None else 30.0

    @classmethod
    def set_analysis_f_min(cls, v: float) -> None:
        cls._set("analysis/analysis_f_min", v)

    @classmethod
    def analysis_f_max(cls) -> float:
        v = cls._get("analysis/analysis_f_max", None)
        return float(v) if v is not None else 2000.0

    @classmethod
    def set_analysis_f_max(cls, v: float) -> None:
        cls._set("analysis/analysis_f_max", v)

    # ------------------------------------------------------------------ #
    # Peak detection threshold (dB, e.g. -60)
    # ------------------------------------------------------------------ #
    @classmethod
    def peak_threshold(cls) -> float:
        v = cls._get("analysis/peak_threshold", None)
        return float(v) if v is not None else -60.0

    @classmethod
    def set_peak_threshold(cls, v: float) -> None:
        cls._set("analysis/peak_threshold", v)

    # ------------------------------------------------------------------ #
    # Maximum peaks (0 = all)
    # ------------------------------------------------------------------ #
    @classmethod
    def max_peaks(cls) -> int:
        v = cls._get("analysis/max_peaks", None)
        return int(v) if v is not None else 0

    @classmethod
    def set_max_peaks(cls, v: int) -> None:
        cls._set("analysis/max_peaks", max(0, v))

    # ------------------------------------------------------------------ #
    # Hop size overlap (0–75 %)
    # ------------------------------------------------------------------ #
    @classmethod
    def hop_size_overlap(cls) -> float:
        v = cls._get("fft/hop_size_overlap", None)
        return float(v) if v is not None else 0.0

    @classmethod
    def set_hop_size_overlap(cls, v: float) -> None:
        cls._set("fft/hop_size_overlap", v)

    # ------------------------------------------------------------------ #
    # Plate dimensions (mm / g)
    # ------------------------------------------------------------------ #
    @classmethod
    def plate_length(cls) -> float:
        v = cls._get("plate/length", None)
        return float(v) if v is not None and float(v) > 0 else 500.0

    @classmethod
    def set_plate_length(cls, v: float) -> None:
        cls._set("plate/length", v)

    @classmethod
    def plate_width(cls) -> float:
        v = cls._get("plate/width", None)
        return float(v) if v is not None and float(v) > 0 else 200.0

    @classmethod
    def set_plate_width(cls, v: float) -> None:
        cls._set("plate/width", v)

    @classmethod
    def plate_thickness(cls) -> float:
        v = cls._get("plate/thickness", None)
        return float(v) if v is not None and float(v) > 0 else 3.0

    @classmethod
    def set_plate_thickness(cls, v: float) -> None:
        cls._set("plate/thickness", v)

    @classmethod
    def plate_mass(cls) -> float:
        v = cls._get("plate/mass", None)
        return float(v) if v is not None and float(v) > 0 else 100.0

    @classmethod
    def set_plate_mass(cls, v: float) -> None:
        cls._set("plate/mass", v)

    # ------------------------------------------------------------------ #
    # Gore thicknessing — guitar body dimensions and f_vs preset
    # ------------------------------------------------------------------ #
    @classmethod
    def guitar_body_length(cls) -> float:
        v = cls._get("plate/gore_body_length", None)
        return float(v) if v is not None and float(v) > 0 else 490.0

    @classmethod
    def set_guitar_body_length(cls, v: float) -> None:
        cls._set("plate/gore_body_length", v)

    @classmethod
    def guitar_body_width(cls) -> float:
        v = cls._get("plate/gore_body_width", None)
        return float(v) if v is not None and float(v) > 0 else 390.0

    @classmethod
    def set_guitar_body_width(cls, v: float) -> None:
        cls._set("plate/gore_body_width", v)

    @classmethod
    def plate_stiffness_preset(cls) -> str:
        return str(cls._get("plate/stiffness_preset", "Steel String Top"))

    @classmethod
    def set_plate_stiffness_preset(cls, v: str) -> None:
        cls._set("plate/stiffness_preset", v)

    @classmethod
    def custom_plate_stiffness(cls) -> float:
        v = cls._get("plate/custom_stiffness", None)
        return float(v) if v is not None and float(v) > 0 else 75.0

    @classmethod
    def set_custom_plate_stiffness(cls, v: float) -> None:
        cls._set("plate/custom_stiffness", v)

    # ------------------------------------------------------------------ #
    # Measure FLC (optional diagonal tap)
    # ------------------------------------------------------------------ #
    @classmethod
    def measure_flc(cls) -> bool:
        v = cls._get("plate/measure_flc", None)
        return bool(v) if v is not None else False

    @classmethod
    def set_measure_flc(cls, v: bool) -> None:
        cls._set("plate/measure_flc", v)

    # ------------------------------------------------------------------ #
    # Brace dimensions (mm / g)
    # ------------------------------------------------------------------ #
    @classmethod
    def brace_length(cls) -> float:
        v = cls._get("brace/length", None)
        return float(v) if v is not None and float(v) > 0 else 300.0

    @classmethod
    def set_brace_length(cls, v: float) -> None:
        cls._set("brace/length", v)

    @classmethod
    def brace_width(cls) -> float:
        v = cls._get("brace/width", None)
        return float(v) if v is not None and float(v) > 0 else 6.0

    @classmethod
    def set_brace_width(cls, v: float) -> None:
        cls._set("brace/width", v)

    @classmethod
    def brace_thickness(cls) -> float:
        """Brace height (tap direction / t dimension)."""
        v = cls._get("brace/thickness", None)
        return float(v) if v is not None and float(v) > 0 else 12.0

    @classmethod
    def set_brace_thickness(cls, v: float) -> None:
        cls._set("brace/thickness", v)

    @classmethod
    def brace_mass(cls) -> float:
        v = cls._get("brace/mass", None)
        return float(v) if v is not None and float(v) > 0 else 8.0

    @classmethod
    def set_brace_mass(cls, v: float) -> None:
        cls._set("brace/mass", v)

    # ------------------------------------------------------------------ #
    # Calibration — global last-used path and per-device mapping
    # ------------------------------------------------------------------ #
    @classmethod
    def calibration_path(cls) -> str:
        """Last imported calibration file path (for the open-file dialog default)."""
        return str(cls._get("calibration/last_path", ""))

    @classmethod
    def set_calibration_path(cls, path: str) -> None:
        cls._set("calibration/last_path", path)

    @classmethod
    def calibration_for_device(cls, device_name: str) -> str:
        """Return the calibration file path stored for *device_name*, or ''."""
        mapping: dict = cls._get("calibration/devices", {}) or {}
        return str(mapping.get(device_name, ""))

    @classmethod
    def set_calibration_for_device(cls, device_name: str, path: str) -> None:
        mapping: dict = dict(cls._get("calibration/devices", {}) or {})
        mapping[device_name] = path
        cls._set("calibration/devices", mapping)

    @classmethod
    def all_calibrations(cls) -> dict:
        """Return the full device→path calibration mapping."""
        return dict(cls._get("calibration/devices", {}) or {})

    @classmethod
    def delete_all_calibrations(cls) -> None:
        """Remove all stored per-device calibrations."""
        cls._set("calibration/devices", {})

    # ------------------------------------------------------------------ #
    # Window geometry
    # ------------------------------------------------------------------ #
    @classmethod
    def window_geometry(cls) -> QtCore.QByteArray | None:
        v = cls._get("window/geometry", None)
        return v if isinstance(v, QtCore.QByteArray) else None

    @classmethod
    def set_window_geometry(cls, geom: QtCore.QByteArray) -> None:
        cls._set("window/geometry", geom)
