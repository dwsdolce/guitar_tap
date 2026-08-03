# @parity util/field-precision
"""Single source of truth for numeric precision (decimal places) per field.

One ``P`` per field governs input (restrict-on-entry), storage, and display, so a value reads
identically in the input field, Settings, the saved measurement, and the report — and identically
across the Swift, Python, and web editions. Mirrors Swift ``FieldPrecision`` / web ``precision.ts``.

This table MUST stay identical across the Swift, Python, and web mirrors.

Precision table — P = decimal places::

    INPUT / SETTINGS
      LINEAR_DIMENSION_MM  2   plate/brace length · width · thickness   0.01 mm  (caliper)
      MASS_G               1   plate/brace mass                         0.1 g
      BODY_DIMENSION_MM    0   guitar body length · width               1 mm
      FREQUENCY_HZ         0   display frequency range                  1 Hz  (< FFT bin ~1.46 Hz)
      MAGNITUDE_DB         0   display magnitude range · thresholds     1 dB
      STIFFNESS            0   custom plate stiffness (f_vs)            1  (unitless)

    COMPUTED / DISPLAYED
      PEAK_FREQUENCY_HZ    1        YOUNGS_MODULUS_GPA   2
      PEAK_MAGNITUDE_DB    1        SPEED_OF_SOUND_MS    0
      Q_FACTOR             1        DENSITY_G_PER_CM3    3
                                    DECAY_RATIO          2
"""
from __future__ import annotations

import math
import re

# --- Input / settings fields (decimal places) ---
LINEAR_DIMENSION_MM = 2   # plate/brace length, width, thickness — 0.01 mm (caliper resolution)
MASS_G = 1                # plate/brace mass — 0.1 g
BODY_DIMENSION_MM = 0     # guitar body length/width — 1 mm (feeds only the Gore target)
FREQUENCY_HZ = 0          # display frequency range + thresholds — 1 Hz (finer than the FFT bin)
MAGNITUDE_DB = 0          # display magnitude range + thresholds — 1 dB
STIFFNESS = 0             # custom plate stiffness (f_vs) — unitless

# --- Computed / displayed values (decimal places) ---
PEAK_FREQUENCY_HZ = 1
PEAK_MAGNITUDE_DB = 1
Q_FACTOR = 1
YOUNGS_MODULUS_GPA = 2
SPEED_OF_SOUND_MS = 0
DENSITY_G_PER_CM3 = 3
DECAY_RATIO = 2


def string(value: float, decimals: int) -> str:
    """Format a value for display at the given precision."""
    return f"{value:.{decimals}f}"


def rounded(value: float, decimals: int) -> float:
    """Round to ``decimals`` places (half away from zero, matching Swift ``.rounded()``).

    A safety net for values that reach settings by a non-typed path; typed entry is restricted up
    front by the input validator (``input_regex`` / ``decimals_within``).
    """
    m = 10.0 ** decimals
    scaled = value * m
    return (math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)) / m


def input_regex(decimals: int) -> str:
    """Regex for an acceptable *partial* numeric entry limited to ``decimals`` fractional digits.

    Used to build the input validator so a keystroke that would exceed the precision is rejected —
    the extra digit never appears (a 2-dp field accepts "29.35" but not "29.356"). Allows in-progress
    states ("", "-", "29", and "29." when ``decimals > 0``); a 0-decimal field rejects the decimal
    point entirely (no stray trailing dot).
    """
    return rf"^-?[0-9]*(\.[0-9]{{0,{decimals}}})?$" if decimals > 0 else r"^-?[0-9]*$"


def decimals_within(text: str, decimals: int) -> bool:
    """Whether ``text`` is an acceptable partial entry — mirrors Swift ``decimalsWithin``."""
    if text == "" or text == "-":
        return True
    return re.match(input_regex(decimals), text) is not None
