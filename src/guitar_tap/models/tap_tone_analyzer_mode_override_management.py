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

