"""
TapToneAnalyzer+ModeOverrideManagement — guitar type and per-peak mode override control.

Mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift.

Per-peak mode overrides are stored on the analyzer keyed by peak UUID string so
that user-assigned labels survive FFT recalculations.  This mirrors Swift's
``peakModeOverrides: [UUID: UserAssignedMode]`` @Published property.

Three-layer peak selection:
  1. User override — a ``UserAssignedMode`` entry in ``peak_mode_overrides`` set
     by the user.
  2. Phase-stored peak — a remembered peak ID persisted across multi-tap capture
     phases (e.g. longitudinal vs cross-grain for plates).
  3. Auto-selected peak — the highest-magnitude peak in the expected frequency
     range for a given ``GuitarMode``.

When a user override is present it takes precedence over the other two layers,
regardless of magnitude or frequency.
"""

from __future__ import annotations


class TapToneAnalyzerModeOverrideManagementMixin:
    """Guitar type and per-peak mode override management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift.

    Stored properties initialised in TapToneAnalyzer.__init__:
        self.peak_mode_overrides: dict[str, str]
            UUID-string → mode-label string (mirrors [UUID: UserAssignedMode]).
    """

    def set_guitar_type(self, guitar_type) -> None:
        """Update the guitar type used for mode classification."""
        self._guitar_type = guitar_type

    # ------------------------------------------------------------------ #
    # Mode Override Management
    # Mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift
    # ------------------------------------------------------------------ #

    def apply_mode_overrides(self, overrides: dict[str, str]) -> None:
        """Replace the entire mode-override dictionary with *overrides*.

        Called when loading a saved ``TapToneMeasurement`` to restore the
        user's previously assigned peak labels.

        Mirrors Swift ``applyModeOverrides(_ overrides: [UUID: UserAssignedMode])``.

        Args:
            overrides: Mapping of UUID strings to mode-label strings.
        """
        self.peak_mode_overrides = dict(overrides)

    def reset_all_mode_overrides(self) -> None:
        """Remove all per-peak mode overrides, returning every peak to auto-classification.

        After this call the analyser's mode assignment falls back to the
        frequency-range heuristic for every peak displayed on the spectrum.

        Mirrors Swift ``resetAllModeOverrides()``.
        """
        self.peak_mode_overrides.clear()

    def reset_mode_override(self, peak_id: str) -> None:
        """Remove the mode override for a single peak, reverting it to auto-classification.

        Preserves overrides on all other peaks.

        Mirrors Swift ``resetModeOverride(for peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        self.peak_mode_overrides.pop(peak_id, None)

    def set_mode_override(self, mode: "str | None", peak_id: str) -> None:
        """Set or clear a mode-label override for a specific peak.

        Passing ``None`` or the string ``"auto"`` clears any existing override
        (equivalent to Swift ``setModeOverride(.auto, for: peakID)``).
        Any other string is stored as a manual label
        (equivalent to Swift ``setModeOverride(.assigned("label"), for: peakID)``).

        Mirrors Swift ``setModeOverride(_ override: UserAssignedMode, for peakID: UUID)``.

        Args:
            mode:    Label string for ``assigned`` overrides, or ``None`` / ``"auto"``
                     to revert to auto-classification.
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        if mode is None or mode == "auto":
            self.peak_mode_overrides.pop(peak_id, None)
        else:
            self.peak_mode_overrides[peak_id] = mode

    def has_manual_override(self, peak_id: str) -> bool:
        """Return ``True`` when the peak has a manually-assigned (non-auto) mode label.

        Mirrors Swift ``hasManualOverride(for peakID: UUID) -> Bool``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        return peak_id in self.peak_mode_overrides

    def effective_mode_label(self, peak) -> str:
        """Return the display label for a peak, respecting any user override.

        If ``peak_mode_overrides`` contains an entry for ``peak.id``, that
        string is returned. Otherwise the auto-classification from
        ``GuitarMode.classify_peak`` is used.

        Mirrors Swift ``effectiveModeLabel(for peak: ResonantPeak) -> String``.

        Args:
            peak: A ``ResonantPeak`` instance.
        """
        override = self.peak_mode_overrides.get(peak.id)
        if override:
            return override
        from .guitar_mode import classify_peak
        from .guitar_type import GuitarType
        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
        return classify_peak(peak.frequency, guitar_type)

    # ------------------------------------------------------------------ #
    # Plate analysis (mirrors TapToneAnalyzer+SpectrumCapture.swift)
    # ------------------------------------------------------------------ #

    def start_plate_analysis(self) -> None:
        """Start a new plate/brace tap sequence via the gated-FFT pipeline.

        The gated pipeline arms itself via start_tap_sequence(), which transitions
        material_tap_phase to CAPTURING_LONGITUDINAL automatically.
        Mirrors Swift's equivalent call that triggers the first capture phase.
        """
        self.start_tap_sequence()

    def reset_plate_analysis(self) -> None:
        """Abort the current plate/brace tap sequence and return to idle."""
        self.cancel_tap_sequence()
