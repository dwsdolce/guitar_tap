"""
Display-only settings constants and thin wrappers.

Mirrors Swift's TapDisplaySettings.swift — static constants and UserDefaults
keys that control purely visual behaviour (axis defaults, unknown-mode
visibility, max-peaks / capture-all-peaks toggle).

The full settings store is AppSettings (tap_settings_view.py).  This module
extracts the display-facing subset so views can import a single, focused
namespace without pulling in the entire settings object.
"""

from __future__ import annotations

from views.utilities.tap_settings_view import AppSettings


# ── Factory defaults ──────────────────────────────────────────────────────────

#: Lowest frequency shown on the spectrum chart for guitar measurements (Hz).
GUITAR_MIN_FREQ: int = 75
#: Highest frequency shown for guitar measurements (Hz).
GUITAR_MAX_FREQ: int = 350

#: Lowest frequency shown for plate measurements (Hz).
PLATE_MIN_FREQ: int = 30
#: Highest frequency shown for plate measurements (Hz).
PLATE_MAX_FREQ: int = 600

#: Lowest frequency shown for brace measurements (Hz).
BRACE_MIN_FREQ: int = 30
#: Highest frequency shown for brace measurements (Hz).
BRACE_MAX_FREQ: int = 1000

#: Default lower dB bound for the magnitude axis.
DEFAULT_DB_MIN: float = -100.0
#: Default upper dB bound for the magnitude axis.
DEFAULT_DB_MAX: float = 0.0


# ── Thin wrappers (delegate to AppSettings) ───────────────────────────────────

def show_unknown_modes() -> bool:
    """Whether peaks with no assigned mode label are shown in the peak list."""
    return AppSettings.show_unknown_modes()


def set_show_unknown_modes(value: bool) -> None:
    AppSettings.set_show_unknown_modes(value)


def default_freq_range(meas_type: "str | object" = "") -> tuple[int, int]:
    """Return (fmin, fmax) factory defaults for the given measurement type."""
    return (
        AppSettings.default_f_min(meas_type),
        AppSettings.default_f_max(meas_type),
    )


def saved_freq_range(meas_type: "str | object" = "") -> tuple[int, int]:
    """Return (fmin, fmax) from persistent settings for the given measurement type."""
    return (
        AppSettings.f_min(meas_type),
        AppSettings.f_max(meas_type),
    )


def saved_db_range() -> tuple[float, float]:
    """Return (db_min, db_max) from persistent settings."""
    return AppSettings.db_min(), AppSettings.db_max()


def annotation_visibility_mode() -> str:
    """Return the saved annotation visibility mode name ("Selected", "None", or "All").

    Mirrors Swift's TapDisplaySettings.annotationVisibilityMode.
    """
    return AppSettings.annotation_visibility_mode()


def set_annotation_visibility_mode(mode: str) -> None:
    """Persist the annotation visibility mode name.

    Mirrors Swift's TapDisplaySettings.annotationVisibilityMode setter.
    """
    AppSettings.set_annotation_visibility_mode(mode)
