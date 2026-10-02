# @parity util/field-precision
"""Single source of truth for numeric precision (decimal places) per field.

An input field's ``P`` limits what can be typed and rounds what is committed; a computed value's ``P``
is the decimals it is shown with, on screen, in exports and in the PDF. Every display of a number
formats it through ``string`` with its entry, so a value reads identically everywhere and across the
Swift, Python and web editions. The saved display range is stored exactly, not rounded to
``FREQUENCY_HZ`` / ``MAGNITUDE_DB``. Mirrors Swift ``FieldPrecision`` / web ``precision.ts``.

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
      PEAK_FREQUENCY_HZ    1        YOUNGS_MODULUS_GPA   2        RADIATION_RATIO     1
      PEAK_MAGNITUDE_DB    1        SHEAR_MODULUS_GPA    3        CROSS_LONG_RATIO    3
      Q_FACTOR             1        SPECIFIC_MODULUS     1        LONG_CROSS_RATIO    1
      BANDWIDTH_HZ         1        SPEED_OF_SOUND_MS    0        DECAY_TIME_S        2
      GORE_THICKNESS_MM    2        DENSITY_G_PER_CM3    3        DECAY_RATIO         2
"""
from __future__ import annotations

import math
import re

import numpy as np

# --- Input / settings fields (decimal places) ---
LINEAR_DIMENSION_MM = 2   # plate/brace length, width, thickness — 0.01 mm (caliper resolution)
MASS_G = 1                # plate/brace mass — 0.1 g
BODY_DIMENSION_MM = 0     # guitar body length/width — 1 mm (feeds only the Gore target)
FREQUENCY_HZ = 0          # display frequency range — 1 Hz (finer than the FFT bin)
MAGNITUDE_DB = 0          # display magnitude range + thresholds — 1 dB
STIFFNESS = 0             # custom plate stiffness (f_vs) — unitless

# --- Computed / displayed values (decimal places) ---
PEAK_FREQUENCY_HZ = 1
PEAK_MAGNITUDE_DB = 1
Q_FACTOR = 1
BANDWIDTH_HZ = 1          # a peak's bandwidth (frequency / Q)
YOUNGS_MODULUS_GPA = 2
SHEAR_MODULUS_GPA = 3     # the plate's GLC shear modulus
SPECIFIC_MODULUS = 1      # E / ρ, in GPa per g/cm³
SPEED_OF_SOUND_MS = 0
DENSITY_G_PER_CM3 = 3
RADIATION_RATIO = 1
CROSS_LONG_RATIO = 3      # fC / fL stiffness ratio
LONG_CROSS_RATIO = 1      # fL / fC stiffness ratio
GORE_THICKNESS_MM = 2
DECAY_TIME_S = 2          # ring-out (decay) time, in seconds
DECAY_RATIO = 2           # the tap-tone ratio (f_Top / f_Air)


def string(value: float, decimals: int) -> str:
    """Format a value for display at the given precision: the value as Swift's ``Float`` (32 bits),
    rounded to the nearest, an exact tie to even — what Swift's ``String(format:)`` shows.

    Infinity reads as "-∞" / "∞" — what Swift's status bar shows — not Python's "-inf". A silent
    input's peak is -∞ dB, and it must not look different from one screen to the next.
    """
    if math.isinf(value):
        return "-∞" if value < 0 else "∞"
    return f"{float(np.float32(value)):.{decimals}f}"


def rounded(value: float, decimals: int) -> float:
    """Round to ``decimals`` places (half away from zero, matching Swift ``.rounded()``).

    A safety net for values that reach settings by a non-typed path; typed entry is restricted up
    front by the input validator (``decimals_within``).
    """
    m = 10.0 ** decimals
    scaled = value * m
    return (math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)) / m


def input_regex(decimals: int) -> str:
    """Regex for an acceptable *partial* numeric entry limited to ``decimals`` fractional digits.

    The pattern ``decimals_within`` matches, so a keystroke that would exceed the precision is
    rejected — the extra digit never appears (a 2-dp field accepts "29.35" but not "29.356"). Allows in-progress
    states ("", "-", "29", and "29." when ``decimals > 0``); a 0-decimal field rejects the decimal
    point entirely (no stray trailing dot).
    """
    return rf"^-?[0-9]*(\.[0-9]{{0,{decimals}}})?$" if decimals > 0 else r"^-?[0-9]*$"


def decimals_within(text: str, decimals: int) -> bool:
    """Whether ``text`` is an acceptable partial entry — mirrors Swift ``decimalsWithin``."""
    if text == "" or text == "-":
        return True
    return re.match(input_regex(decimals), text) is not None
