"""
Guitar resonance mode classification.

Mirrors Swift GuitarMode enum (GuitarMode.swift).

Guitar body mode classification using luthier-friendly terminology.
Each case represents one of the principal low-frequency resonances of a
completed guitar body.  The frequency boundaries for each mode depend on
the guitar type (classical, flamenco, acoustic) and are defined in
GuitarType.ModeRanges.

Mode Map (approximate detection ranges, guitar-type-dependent):

  Mode        Classical    Flamenco     Acoustic     Physical description
  ----        ---------    --------     --------     --------------------
  Air         80–110 Hz    85–115 Hz    90–120 Hz    Helmholtz air resonance of the sound-hole cavity
  Top         170–230 Hz   190–250 Hz   150–210 Hz   Main monopole resonance of the top plate
  Back        190–280 Hz   180–240 Hz   210–290 Hz   Main monopole resonance of the back plate
  Dipole      330–430 Hz   350–450 Hz   360–460 Hz   T(1,2) anti-symmetric bending mode
  Ring Mode   580–820 Hz   600–850 Hz   620–880 Hz   Higher structural mode
  Upper       820+ Hz      850+ Hz      880+ Hz      Cluster of higher-order modes

Exact boundaries are defined in GuitarType.mode_ranges.

Legacy Cases:
  Four legacy raw values are retained for backward compatibility with
  measurements saved under older naming conventions.  They are mapped to
  their modern equivalents by the ``normalized`` property and ``display_name``.
"""

from __future__ import annotations
from enum import Enum

from .guitar_type import GuitarType


# MARK: - Module-Level Helpers (Python-only, no direct Swift equivalent)

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


# MARK: - GuitarMode

class GuitarMode(Enum):
    """A resonance mode classification for a completed guitar body.

    Mirrors Swift GuitarMode enum (GuitarMode.swift).

    Use classify() or classify_all() to map a detected peak frequency to
    the appropriate mode.  The ``normalized`` property converts any legacy
    case to its modern equivalent for programmatic comparisons.

    See Also: GuitarType for the frequency-band definitions used during classification.
    See Also: UserAssignedMode for overriding the displayed label without changing the mode.
    """

    # MARK: - Current Cases

    # Helmholtz resonance of the air cavity, combined with the coupled air/top mode.
    # Corresponds to T(1,1)_1 in the acoustic physics literature.
    AIR         = "Air (Helmholtz)"

    # Main top-plate monopole resonance (formerly called the long-grain mode).
    # Corresponds to T(1,1)_2.
    TOP         = "Top"

    # Main back-plate monopole resonance (formerly called the monopole mode).
    # Corresponds to T(1,1)_3.
    BACK        = "Back"

    # Anti-symmetric dipole bending mode, T(1,2).
    DIPOLE      = "Dipole"

    # Higher structural ring mode.
    RING_MODE   = "Ring Mode"

    # Cluster of higher-order modes above the ring mode.
    UPPER_MODES = "Upper Modes"

    # Frequency falls outside all defined mode ranges.
    UNKNOWN     = "Unknown"

    # MARK: - Legacy Cases (Backward Compatibility)
    # Warning: these cases exist only for decoding measurements saved under old
    # naming conventions.  Use the current cases for all new code.

    HELMHOLTZ   = "Helmholtz (Air)"   # Legacy name for AIR. normalized → AIR.
    CROSS_GRAIN = "Cross-Grain"       # Legacy name for AIR. normalized → AIR.
    LONG_GRAIN  = "Long-Grain"        # Legacy name for TOP. normalized → TOP.
    MONOPOLE    = "Monopole"          # Legacy name for BACK. normalized → BACK.

    # MARK: - Current Case Enumeration

    # current_cases and additional_mode_labels are set as class attributes
    # after the class body — see bottom of file.
    # Mirrors Swift GuitarMode.currentCases and GuitarMode.additionalModeLabels.

    # MARK: - Classification

    @classmethod
    def classify(cls, freq: float, guitar_type: GuitarType) -> GuitarMode:
        """Classify a frequency into a guitar mode for a specific guitar type.

        - Parameters:
          - freq: The peak frequency to classify, in Hz.
          - guitar_type: The guitar type whose mode-range bands are used for classification.
        - Returns: The matching GuitarMode, or UNKNOWN if no band matches.

        Mirrors Swift GuitarMode.classify(frequency:guitarType:).
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
        peaks: list,
        guitar_type: GuitarType,
    ) -> dict:
        """Classify a set of ResonantPeak objects into guitar modes using a context-aware claiming algorithm.

        Mirrors Swift ``GuitarMode.classifyAll(_:guitarType:)`` exactly:
        - Accepts objects with ``.id``, ``.frequency``, and ``.magnitude`` attributes
          (i.e. ``ResonantPeak`` instances).
        - Returns ``{peak.id: GuitarMode}`` keyed by the peak's UUID — the same key
          type that Swift uses so call sites can look up a mode by peak ID directly
          without any index-to-id translation layer.

        Unlike classify(), which maps each frequency independently, this method processes
        all peaks together so that overlapping mode ranges (e.g. the Top/Back overlap
        zone for classical guitar) resolve correctly: the first peak claimed by a
        lower-frequency mode cannot be re-claimed by a higher-frequency mode.

        Algorithm:
        1. Sorts the canonical modes (Air, Top, Back, Dipole, Ring, Upper) by ascending
           lower-bound of their frequency range for the given guitar type.
        2. For each mode in that order, picks the highest-magnitude unclaimed peak whose
           frequency lies within the mode's range (and strictly above the last claimed
           frequency), then marks that peak as claimed.
        3. A per-claim 2 Hz duplicate check discards a candidate within 2 Hz of an
           already-claimed peak from an earlier mode.
        4. Any remaining unclaimed peaks are classified via the per-frequency classify()
           lookup.  Peaks outside all mode ranges resolve to UNKNOWN.

        NOTE — Algorithm divergence from Swift:
          Swift classifyAll uses only a Set of claimed UUIDs (no cursor or 2 Hz check).
          The Python implementation adds a ``last_claimed_freq`` cursor and a 2 Hz
          duplicate guard, making it slightly more restrictive in overlap zones.
          Both implementations agree on the common case.

        - Parameters:
          - peaks: List of objects with ``.id``, ``.frequency``, and ``.magnitude``.
          - guitar_type: The guitar type whose mode-range bands are used.
        - Returns: A dict mapping each peak's ``.id`` to its GuitarMode.
          Mirrors Swift ``[UUID: GuitarMode]``.
        """
        ordered_modes = sorted(
            [cls.AIR, cls.TOP, cls.BACK, cls.DIPOLE, cls.RING_MODE, cls.UPPER_MODES],
            key=lambda m: m.mode_range(guitar_type)[0],
        )
        result: dict = {}
        claimed_ids: set = set()
        last_claimed_freq: float = -1.0
        claimed_freqs: list[float] = []

        for mode in ordered_modes:
            lo, hi = mode.mode_range(guitar_type)
            candidates = [
                (p.id, p.magnitude) for p in peaks
                if lo <= p.frequency <= hi
                and p.id not in claimed_ids
                and p.frequency > last_claimed_freq
            ]
            if not candidates:
                continue
            best_id = max(candidates, key=lambda x: x[1])[0]
            best_peak = next(p for p in peaks if p.id == best_id)
            best_freq = best_peak.frequency
            # Post-claim 2 Hz duplicate check
            if any(abs(best_freq - f) < 2.0 for f in claimed_freqs):
                continue
            result[best_id] = mode
            claimed_ids.add(best_id)
            last_claimed_freq = best_freq
            claimed_freqs.append(best_freq)

        for peak in peaks:
            if peak.id not in result:
                result[peak.id] = cls.classify(peak.frequency, guitar_type)

        return result

    @classmethod
    def _classify_all_tuples(
        cls,
        peaks: list[tuple[float, float]],
        guitar_type: GuitarType,
    ) -> dict[int, "GuitarMode"]:
        """Classify (frequency, magnitude) tuples, returning {index: GuitarMode}.

        Internal helper for call sites that have no peak UUIDs (e.g. live numpy data
        in PeaksModel).  All code that works with ResonantPeak objects should use
        classify_all() instead so that the return type matches Swift's [UUID: GuitarMode].
        """
        ordered_modes = sorted(
            [cls.AIR, cls.TOP, cls.BACK, cls.DIPOLE, cls.RING_MODE, cls.UPPER_MODES],
            key=lambda m: m.mode_range(guitar_type)[0],
        )
        result: dict[int, GuitarMode] = {}
        claimed: set[int] = set()
        last_claimed_freq: float = -1.0
        claimed_freqs: list[float] = []

        for mode in ordered_modes:
            lo, hi = mode.mode_range(guitar_type)
            candidates = [
                (i, mag) for i, (freq, mag) in enumerate(peaks)
                if lo <= freq <= hi and i not in claimed and freq > last_claimed_freq
            ]
            if not candidates:
                continue
            best_i = max(candidates, key=lambda x: x[1])[0]
            best_freq = peaks[best_i][0]
            if any(abs(best_freq - f) < 2.0 for f in claimed_freqs):
                continue
            result[best_i] = mode
            claimed.add(best_i)
            last_claimed_freq = best_freq
            claimed_freqs.append(best_freq)

        for i, (freq, _) in enumerate(peaks):
            if i not in result:
                result[i] = cls.classify(freq, guitar_type)

        return result

    @staticmethod
    def is_known(freq: float, guitar_type: GuitarType) -> bool:
        """Return True if *freq* falls within any named mode range for the given guitar type.

        Use this for filtering peaks by visibility (the "hide unknown modes" setting) instead
        of calling classify() and comparing against UNKNOWN.  This avoids any ambiguity around
        the overlap zone: a frequency in the Top/Back overlap is always "known" regardless of
        which mode classify_all() ultimately assigns it to.

        - Parameters:
          - freq: The peak frequency to test, in Hz.
          - guitar_type: The guitar type whose mode-range bands are used.

        Mirrors Swift GuitarMode.isKnown(frequency:guitarType:).
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

    # MARK: - Frequency Ranges

    def mode_range(self, guitar_type: GuitarType) -> tuple[float, float]:
        """The classification frequency range for this mode for a specific guitar type.

        - Parameter guitar_type: The guitar type whose mode_ranges table is consulted.
        - Returns: A (lo_hz, hi_hz) tuple.  Returns (0.0, 20000.0) for UNKNOWN and
          for any unrecognised future cases.

        Mirrors Swift GuitarMode.modeRange(for:).
        """
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

    # MARK: - Display

    @property
    def display_name(self) -> str:
        """The human-readable mode name shown in the UI.

        All legacy cases are mapped to their modern display string so that
        measurements saved under the old naming convention render correctly
        after an upgrade.

        Mirrors Swift GuitarMode.displayName.
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
    def color(self) -> tuple[int, int, int]:
        """Display color for a guitar mode, derived from self.normalized.

        Legacy enum cases are collapsed to their canonical equivalents via
        normalized before the color is resolved, so all historical variants
        of e.g. AIR map to cyan.

        Mirrors Swift GuitarMode.color (Color extension).
        """
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
    def abbreviation(self) -> str:
        """Short mode abbreviation for compact UI display (e.g., "Air", "DP").

        Mirrors Swift GuitarMode.abbreviation.
        """
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
        """Human-readable description of the acoustic mode, suitable for tooltips and detail views.

        Mirrors Swift GuitarMode.description.
        """
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
    def icon(self) -> str:
        """qtawesome icon name representing this guitar mode visually.

        Maps to equivalent SF Symbols names used in Swift (GuitarMode.icon):
          wind → fa5s.wind
          arrow.up.and.down → fa5s.arrows-alt-v
          square.fill → fa5s.square
          circle.lefthalf.filled → fa5s.adjust
          circle.dashed → fa5s.circle-notch
          waveform → fa5s.wave-square
          questionmark.circle → fa5s.question-circle

        Mirrors Swift GuitarMode.icon.
        """
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

    # MARK: - Normalisation

    @property
    def normalized(self) -> GuitarMode:
        """Convert any legacy case to its current equivalent for programmatic comparisons.

        Use this property whenever you need to compare two GuitarMode values for
        semantic equality, since e.g. HELMHOLTZ == AIR is False as raw-value enums
        but HELMHOLTZ.normalized == AIR.normalized is True.

        Current cases are returned unchanged.

        Mirrors Swift GuitarMode.normalized.
        """
        _map = {
            GuitarMode.HELMHOLTZ:   GuitarMode.AIR,
            GuitarMode.CROSS_GRAIN: GuitarMode.AIR,
            GuitarMode.LONG_GRAIN:  GuitarMode.TOP,
            GuitarMode.MONOPOLE:    GuitarMode.BACK,
        }
        return _map.get(self, self)

    # MARK: - Conversion from Legacy Python Strings (Python-only, no Swift equivalent)

    @classmethod
    def from_mode_string(cls, mode_str: str) -> GuitarMode:
        """Convert any stored mode string to a GuitarMode.

        Accepts three kinds of strings:
        - GuitarMode raw values (e.g. "Air (Helmholtz)", "Top") — returned directly.
        - Legacy Python mode strings (e.g. "Helmholtz T(1,1)_1") — mapped via
          ``_PYTHON_STR_TO_MODE``.
        - Custom / unrecognised strings — returns ``UNKNOWN``.

        Python-only: Swift stores GuitarMode as a Codable raw-value enum and does
        not need a separate string-conversion method.
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

# MARK: - Current Case Enumeration
# Defined after the class body because Python Enum members cannot reference
# their own enum type at class-body evaluation time.

# All current (non-legacy) cases in display order.
# Use this instead of iterating all cases (which includes legacy backward-compatibility
# cases) for pickers, suggestion lists, and anywhere the full canonical set is needed.
# Mirrors Swift GuitarMode.currentCases.
GuitarMode.current_cases = [
    GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK, GuitarMode.DIPOLE,
    GuitarMode.RING_MODE, GuitarMode.UPPER_MODES, GuitarMode.UNKNOWN,
]

# Extended mode label strings using acoustical physics T(m,n) notation.
# Presented as secondary choices in the mode-override picker for users who prefer
# the academic designation system over the luthier-friendly names in current_cases.
# Mirrors Swift GuitarMode.additionalModeLabels.
GuitarMode.additional_mode_labels = [
    "Helmholtz T(1,1)_1", "Top T(1,1)_2", "Back T(1,1)_3",
    "Cross Dipole T(2,1)", "Long Dipole T(1,2)", "Quadrapole T(2,2)", "Cross Tripole T(3,1)",
]
