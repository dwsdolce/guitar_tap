"""
    Guitar mode definitions and automatic peak classification.

    Frequency band ranges are based on Trevor Gore's Contemporary Acoustic
    Guitar Design and Build methodology.  Ranges are intentionally wide to
    accommodate natural variation; they can overlap, in which case the
    lowest-order mode that matches is returned.
"""

from enum import Enum


class GuitarType(Enum):
    CLASSICAL = "Classical"
    FLAMENCO = "Flamenco"
    ACOUSTIC = "Acoustic"


# Mode strings match the existing mode_strings list in PeaksModel so that
# auto-classified values are valid entries in the combo delegate.
_HELMHOLTZ = "Helmholtz T(1,1)_1"
_TOP        = "Top T(1,1)_2"
_BACK       = "Back T(1,1)_3"
_CROSS_DIP  = "Cross Dipole T(2,1)"
_LONG_DIP   = "Long Dipole T(1,2)"
_QUAD       = "Quadrapole T(2,2)"
_TRIPOLE    = "Cross Tripole T(3,1)"

# (lo_hz, hi_hz, mode_string) ordered lowest → highest so the first match
# for a given frequency is always the lowest-order plausible mode.
_BANDS: dict[GuitarType, list[tuple[float, float, str]]] = {
    GuitarType.CLASSICAL: [
        ( 80,  130, _HELMHOLTZ),
        (140,  215, _TOP),
        (185,  280, _BACK),
        (250,  375, _CROSS_DIP),
        (330,  465, _LONG_DIP),
        (430,  620, _QUAD),
        (580,  850, _TRIPOLE),
    ],
    GuitarType.FLAMENCO: [
        ( 90,  140, _HELMHOLTZ),
        (155,  235, _TOP),
        (200,  300, _BACK),
        (265,  395, _CROSS_DIP),
        (350,  490, _LONG_DIP),
        (460,  650, _QUAD),
        (610,  890, _TRIPOLE),
    ],
    GuitarType.ACOUSTIC: [
        ( 90,  145, _HELMHOLTZ),
        (170,  260, _TOP),
        (215,  325, _BACK),
        (290,  430, _CROSS_DIP),
        (380,  540, _LONG_DIP),
        (500,  720, _QUAD),
        (660,  970, _TRIPOLE),
    ],
}


# RGBA fill colours for each mode (semi-transparent)
_BAND_COLOUR: dict[str, tuple[int, int, int, int]] = {
    _HELMHOLTZ: ( 80, 130, 220, 35),
    _TOP:       ( 60, 180,  80, 35),
    _BACK:      (220, 140,  40, 35),
    _CROSS_DIP: (170,  60, 210, 35),
    _LONG_DIP:  (210,  60,  60, 35),
    _QUAD:      ( 30, 170, 170, 35),
    _TRIPOLE:   (170, 200,  40, 35),
}


def get_bands(
    guitar_type: GuitarType,
) -> list[tuple[float, float, str, tuple[int, int, int, int]]]:
    """Return (lo_hz, hi_hz, mode_name, rgba) for every band of *guitar_type*."""
    return [
        (lo, hi, mode, _BAND_COLOUR[mode])
        for lo, hi, mode in _BANDS[guitar_type]
    ]


def classify_peak(freq: float, guitar_type: GuitarType) -> str:
    """Return the mode string for the first band that contains *freq*.

    Returns "" (unknown) if no band matches.
    """
    for lo, hi, mode in _BANDS[guitar_type]:
        if lo <= freq <= hi:
            return mode
    return ""
