"""
    Guitar mode definitions and automatic peak classification.

    Mirrors Swift GuitarMode.swift / GuitarType.swift.  A single unified set
    of frequency bands (GuitarType.mode_ranges) is used for both FFT band
    display and auto-classification — matching the Swift behaviour after the
    removal of the separate idealRanges in commit f1b4f04.

    GuitarMode mirrors the Swift GuitarMode enum (GuitarMode.swift),
    providing display_name, normalized, color, abbreviation, description,
    icon, classify(), and mode_range().
"""

from __future__ import annotations
from enum import Enum

from guitar_type import GuitarType


# ── public helpers ────────────────────────────────────────────────────────────

def get_bands(
    guitar_type: GuitarType,
) -> list[tuple[float, float, str, tuple[int, int, int, int]]]:
    """Return (lo_hz, hi_hz, mode_value, rgba) for every band of *guitar_type*.

    Uses the same modeRanges as Swift — a single unified set of bands for both
    display and auto-classification.  *mode_value* is the GuitarMode raw value
    string (e.g. ``"Air (Helmholtz)"``), accepted by ``GuitarMode.from_mode_string``.
    """
    r = guitar_type.mode_ranges
    entries: list[tuple[GuitarMode, tuple[float, float]]] = [
        (GuitarMode.AIR,         r.air),
        (GuitarMode.TOP,         r.top),
        (GuitarMode.BACK,        r.back),
        (GuitarMode.DIPOLE,      r.dipole),
        (GuitarMode.RING_MODE,   r.ring_mode),
        (GuitarMode.UPPER_MODES, r.upper_modes),
    ]
    result = []
    for mode, (lo, hi) in entries:
        rv, gv, bv = mode.color
        result.append((lo, hi, mode.value, (rv, gv, bv, 35)))
    return result


def in_mode_range(freq: float, mode_str: str, guitar_type: GuitarType) -> bool:
    """Return True if *freq* falls within the mode_ranges window for *mode_str*.

    Accepts GuitarMode raw values (e.g. ``"Air (Helmholtz)"``), legacy Python
    mode strings (e.g. ``"Helmholtz T(1,1)_1"``), and custom labels.
    Returns False for unrecognised / UNKNOWN modes.
    """
    mode = GuitarMode.from_mode_string(mode_str)
    if mode is GuitarMode.UNKNOWN:
        return False
    lo, hi = mode.mode_range(guitar_type)
    return lo <= freq <= hi


def classify_peak(freq: float, guitar_type: GuitarType) -> str:
    """Return the GuitarMode raw value string for *freq* using *guitar_type*'s mode ranges.

    Delegates to ``GuitarMode.classify`` — uses the same unified bands as Swift.
    Returns ``""`` (unknown) if no band matches.
    """
    mode = GuitarMode.classify(freq, guitar_type)
    return mode.value


def mode_display_name(mode_str: str) -> str:
    """Return the human-readable display name for any stored mode string.

    Handles GuitarMode raw values, legacy Python mode strings, and custom
    labels.  Custom labels (unrecognised strings) are returned unchanged.
    """
    if not mode_str:
        return ""
    mode = GuitarMode.from_mode_string(mode_str)
    if mode is not GuitarMode.UNKNOWN:
        return mode.display_name
    return mode_str  # custom label — show as-is


# ── GuitarMode enum ───────────────────────────────────────────────────────────

class GuitarMode(Enum):
    """Resonance mode classification for a completed guitar body.

    Mirrors Swift GuitarMode enum (GuitarMode.swift).

    Current cases use the same display strings as the Swift raw values.
    Legacy cases are retained for decoding old data; ``normalized`` maps
    them to their modern equivalents.

    Use ``classify()`` to map a frequency to a mode, and
    ``from_mode_string()`` to convert the legacy Python mode strings
    (e.g. "Helmholtz T(1,1)_1") stored in PeaksModel to a GuitarMode.
    """

    # ── current cases ─────────────────────────────────────────────────────
    AIR         = "Air (Helmholtz)"
    TOP         = "Top"
    BACK        = "Back"
    DIPOLE      = "Dipole"
    RING_MODE   = "Ring Mode"
    UPPER_MODES = "Upper Modes"
    UNKNOWN     = "Unknown"

    # ── legacy cases (backward compatibility) ─────────────────────────────
    HELMHOLTZ   = "Helmholtz (Air)"   # → AIR
    CROSS_GRAIN = "Cross-Grain"       # → AIR
    LONG_GRAIN  = "Long-Grain"        # → TOP
    MONOPOLE    = "Monopole"          # → BACK

    # ── normalisation ─────────────────────────────────────────────────────

    @property
    def normalized(self) -> GuitarMode:
        """Return the canonical (non-legacy) case for this mode."""
        _map = {
            GuitarMode.HELMHOLTZ:   GuitarMode.AIR,
            GuitarMode.CROSS_GRAIN: GuitarMode.AIR,
            GuitarMode.LONG_GRAIN:  GuitarMode.TOP,
            GuitarMode.MONOPOLE:    GuitarMode.BACK,
        }
        return _map.get(self, self)

    # ── display ───────────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """Human-readable mode name shown in the UI.

        All legacy cases are mapped to their modern display string, matching
        the Swift displayName switch exactly.
        """
        _names = {
            GuitarMode.AIR:         "Air (Helmholtz)",
            GuitarMode.HELMHOLTZ:   "Air (Helmholtz)",
            GuitarMode.CROSS_GRAIN: "Air (Helmholtz)",
            GuitarMode.TOP:         "Top",
            GuitarMode.LONG_GRAIN:  "Top",
            GuitarMode.BACK:        "Back",
            GuitarMode.MONOPOLE:    "Back",
            GuitarMode.DIPOLE:      "Dipole",
            GuitarMode.RING_MODE:   "Ring Mode",
            GuitarMode.UPPER_MODES: "Upper Modes",
            GuitarMode.UNKNOWN:     "Unknown",
        }
        return _names.get(self, "Unknown")

    @property
    def abbreviation(self) -> str:
        """Short label for compact UI display."""
        n = self.normalized
        _abbr = {
            GuitarMode.AIR:         "Air",
            GuitarMode.TOP:         "Top",
            GuitarMode.BACK:        "Back",
            GuitarMode.DIPOLE:      "DP",
            GuitarMode.RING_MODE:   "Ring",
            GuitarMode.UPPER_MODES: "Upper",
            GuitarMode.UNKNOWN:     "?",
        }
        return _abbr.get(n, "?")

    @property
    def description(self) -> str:
        """Human-readable acoustic description."""
        n = self.normalized
        _desc = {
            GuitarMode.AIR:         "Air resonance (Helmholtz) - the 'breathing' of the guitar body",
            GuitarMode.TOP:         "Main top plate resonance",
            GuitarMode.BACK:        "Back plate resonance",
            GuitarMode.DIPOLE:      "Top plate moving out of phase (dipole)",
            GuitarMode.RING_MODE:   "Higher frequency body resonances",
            GuitarMode.UPPER_MODES: "Upper harmonic modes",
            GuitarMode.UNKNOWN:     "Unclassified frequency",
        }
        return _desc.get(n, "Unclassified frequency")

    @property
    def color(self) -> tuple[int, int, int]:
        """RGB colour tuple for this mode (matches Swift .cyan/.green/.orange etc.)."""
        n = self.normalized
        _colors = {
            GuitarMode.AIR:         (  0, 183, 235),  # cyan
            GuitarMode.TOP:         ( 40, 160,  40),  # green
            GuitarMode.BACK:        (220, 120,  40),  # orange
            GuitarMode.DIPOLE:      (210,  50,  50),  # red
            GuitarMode.RING_MODE:   (130,  60, 200),  # purple
            GuitarMode.UPPER_MODES: (130, 130, 130),  # gray
            GuitarMode.UNKNOWN:     (130, 130, 130),  # secondary
        }
        return _colors.get(n, (130, 130, 130))

    @property
    def icon(self) -> str:
        """qtawesome icon name for this mode (mirrors Swift SF Symbol names)."""
        n = self.normalized
        _icons = {
            GuitarMode.AIR:         "fa5s.wind",
            GuitarMode.TOP:         "fa5s.arrows-alt-v",
            GuitarMode.BACK:        "fa5s.square",
            GuitarMode.DIPOLE:      "fa5s.adjust",
            GuitarMode.RING_MODE:   "fa5s.circle-notch",
            GuitarMode.UPPER_MODES: "fa5s.wave-square",
            GuitarMode.UNKNOWN:     "fa5s.question-circle",
        }
        return _icons.get(n, "fa5s.question-circle")

    # ── frequency range ───────────────────────────────────────────────────

    def mode_range(self, guitar_type: GuitarType) -> tuple[float, float]:
        """Return (lo_hz, hi_hz) classification range for this mode and guitar type."""
        ranges = guitar_type.mode_ranges
        n = self.normalized
        _range_map = {
            GuitarMode.AIR:         ranges.air,
            GuitarMode.TOP:         ranges.top,
            GuitarMode.BACK:        ranges.back,
            GuitarMode.DIPOLE:      ranges.dipole,
            GuitarMode.RING_MODE:   ranges.ring_mode,
            GuitarMode.UPPER_MODES: ranges.upper_modes,
        }
        return _range_map.get(n, (0.0, 20000.0))

    # ── classification ────────────────────────────────────────────────────

    @classmethod
    def classify(cls, freq: float, guitar_type: GuitarType) -> GuitarMode:
        """Classify *freq* into a GuitarMode using *guitar_type*'s mode ranges.

        Uses the tighter Swift-matching mode_ranges windows (not the wide
        _BANDS classification bands).  Returns ``UNKNOWN`` if no band matches.
        """
        ranges = guitar_type.mode_ranges
        checks: list[tuple[tuple[float, float], GuitarMode]] = [
            (ranges.air,         cls.AIR),
            (ranges.top,         cls.TOP),
            (ranges.back,        cls.BACK),
            (ranges.dipole,      cls.DIPOLE),
            (ranges.ring_mode,   cls.RING_MODE),
            (ranges.upper_modes, cls.UPPER_MODES),
        ]
        for (lo, hi), mode in checks:
            if lo <= freq <= hi:
                return mode
        return cls.UNKNOWN

    @classmethod
    def classify_all(
        cls,
        peaks: list[tuple[float, float]],
        guitar_type: GuitarType,
    ) -> dict[int, GuitarMode]:
        """Classify a list of (freq, magnitude) peaks using context-aware claiming.

        Mirrors Swift ``GuitarMode.classifyAll``:
        1. Modes are visited in ascending lower-bound order.
        2. For each mode the highest-magnitude unclaimed peak in its range is
           claimed; no other mode can later claim the same peak.
        3. Unclaimed peaks are classified individually via ``classify()``.

        Returns a dict mapping each peak's index to its ``GuitarMode``.
        """
        ordered_modes = sorted(
            [cls.AIR, cls.TOP, cls.BACK, cls.DIPOLE, cls.RING_MODE, cls.UPPER_MODES],
            key=lambda m: m.mode_range(guitar_type)[0],
        )
        result: dict[int, GuitarMode] = {}
        claimed: set[int] = set()

        for mode in ordered_modes:
            lo, hi = mode.mode_range(guitar_type)
            candidates = [
                (i, mag) for i, (freq, mag) in enumerate(peaks)
                if lo <= freq <= hi and i not in claimed
            ]
            if candidates:
                best_i = max(candidates, key=lambda x: x[1])[0]
                result[best_i] = mode
                claimed.add(best_i)

        for i, (freq, _) in enumerate(peaks):
            if i not in result:
                result[i] = cls.classify(freq, guitar_type)

        return result

    @staticmethod
    def is_known(freq: float, guitar_type: GuitarType) -> bool:
        """Return True if *freq* falls within any named mode range.

        Mirrors Swift ``GuitarMode.isKnown(frequency:guitarType:)``.
        Use this instead of checking whether ``classify()`` returns ``UNKNOWN``
        when a frequency is in an overlap zone — it is always "known" regardless
        of which mode ``classify_all`` ultimately assigns it to.
        """
        r = guitar_type.mode_ranges
        return (
            r.air[0]         <= freq <= r.air[1]         or
            r.top[0]         <= freq <= r.top[1]         or
            r.back[0]        <= freq <= r.back[1]        or
            r.dipole[0]      <= freq <= r.dipole[1]      or
            r.ring_mode[0]   <= freq <= r.ring_mode[1]   or
            r.upper_modes[0] <= freq <= r.upper_modes[1]
        )

    # ── conversion from legacy Python mode strings ────────────────────────

    @classmethod
    def from_mode_string(cls, mode_str: str) -> GuitarMode:
        """Convert any stored mode string to a GuitarMode.

        Accepts three kinds of strings:
        - GuitarMode raw values (e.g. "Air (Helmholtz)", "Top") — returned directly.
        - Legacy Python mode strings (e.g. "Helmholtz T(1,1)_1") — mapped via
          ``_PYTHON_STR_TO_MODE``.
        - Custom / unrecognised strings — returns ``UNKNOWN``.
        """
        # Try as a GuitarMode raw value first (new-style strings)
        try:
            return cls(mode_str)
        except ValueError:
            pass
        # Fall back to the legacy Python string mapping
        return _PYTHON_STR_TO_MODE.get(mode_str, cls.UNKNOWN)


# Mapping from PeaksModel mode strings to GuitarMode cases.
# Defined after the class so enum members are available.
_PYTHON_STR_TO_MODE: dict[str, GuitarMode] = {
    "Helmholtz T(1,1)_1":   GuitarMode.HELMHOLTZ,   # normalises → AIR
    "Top T(1,1)_2":         GuitarMode.TOP,
    "Back T(1,1)_3":        GuitarMode.BACK,
    "Cross Dipole T(2,1)":  GuitarMode.DIPOLE,
    "Long Dipole T(1,2)":   GuitarMode.DIPOLE,
    "Quadrapole T(2,2)":    GuitarMode.UPPER_MODES,
    "Cross Tripole T(3,1)": GuitarMode.RING_MODE,
}

# ── class-level lists (mirrors Swift static properties) ───────────────────────

# All current (non-legacy) cases in display order.
# Mirrors Swift GuitarMode.currentCases.
# Use this for pickers and suggestion lists instead of iterating all cases,
# which would include the legacy backward-compatibility cases.
GuitarMode.current_cases = [
    GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK, GuitarMode.DIPOLE,
    GuitarMode.RING_MODE, GuitarMode.UPPER_MODES, GuitarMode.UNKNOWN,
]

# Extended mode label strings using acoustical physics T(m,n) notation.
# Presented as secondary choices in the mode-override picker.
# Mirrors Swift GuitarMode.additionalModeLabels.
GuitarMode.additional_mode_labels = [
    "Helmholtz T(1,1)_1", "Top T(1,1)_2", "Back T(1,1)_3",
    "Cross Dipole T(2,1)", "Long Dipole T(1,2)", "Quadrapole T(2,2)", "Cross Tripole T(3,1)",
]
