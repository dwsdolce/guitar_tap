"""
TapToneAnalyzer+AnalysisHelpers — loaded-peak threshold filtering,
spectrum averaging, and supporting query methods.

Mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift.
"""

from __future__ import annotations


class TapToneAnalyzerAnalysisHelpersMixin:
    """Analysis helper methods for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift.
    """

    # MARK: - Query methods
    # Mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift

    def peak_mode(self, peak) -> "GuitarMode":
        """Return the context-aware GuitarMode assigned to *peak*.

        If the user has overridden this peak's mode to a predefined GuitarMode,
        return that mode so color/icon update everywhere.  Freeform labels that
        do not match any predefined mode return UNKNOWN; views detect the
        freeform case separately via has_manual_override + from_mode_string.

        Falls back to ``identified_modes`` (populated by classify pass), then
        to a single-element ``classify_all`` call for stale references.

        Mirrors Swift ``peakMode(for:)``.
        """
        from .guitar_mode import GuitarMode
        # Check user override first.
        override_label = self.peak_mode_overrides.get(peak.id)
        if override_label:
            overridden_mode = GuitarMode.from_mode_string(override_label)
            if overridden_mode is not GuitarMode.UNKNOWN:
                return overridden_mode
            # Freeform label — return UNKNOWN; views use USER_DEFINED_COLOR.
            return GuitarMode.UNKNOWN

        for entry in self.identified_modes:
            if entry.get("peak") and entry["peak"].id == peak.id:
                return entry["mode"]
        # Fall back: use classify_all (claiming algorithm) not GuitarMode.classify
        # (simple range lookup) — mirrors Swift peakMode(for:) which uses classifyAll.
        from models.tap_display_settings import TapDisplaySettings as _tds_pm
        mode_map = GuitarMode.classify_all([peak], _tds_pm.guitar_type())
        return mode_map.get(peak.id, GuitarMode.UNKNOWN)

    def get_peak(self, mode: "GuitarMode") -> "ResonantPeak | None":
        """Return the highest-magnitude peak classified as *mode*.

        Mode comparison uses ``GuitarMode.normalized`` so legacy aliases
        (e.g. ``.helmholtz``) resolve correctly.

        Mirrors Swift ``getPeak(for:)``.

        Returns:
            The strongest ``ResonantPeak`` classified as *mode*, or ``None``
            if no such peak exists in ``identified_modes``.
        """
        candidates = [
            entry["peak"]
            for entry in self.identified_modes
            if (
                "peak" in entry and "mode" in entry
                and entry["mode"].normalized == mode.normalized
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.magnitude)

    def calculate_tap_tone_ratio(self) -> "float | None":
        """Compute the tap-tone ratio f_Top / f_Air from identified modes.

        An ideal acoustic-guitar top yields a ratio close to 2.0 (Top
        resonance approximately one octave above the Air/Helmholtz resonance).

        Mirrors Swift ``calculateTapToneRatio()``.

        Returns:
            ``f_Top / f_Air`` as a float, or ``None`` if either the Air or
            Top mode peak is absent from ``identified_modes``.
        """
        from .guitar_mode import GuitarMode
        air_peak = self.get_peak(GuitarMode.AIR)
        top_peak = self.get_peak(GuitarMode.TOP)
        if air_peak is None or top_peak is None:
            return None
        if air_peak.frequency == 0:
            return None
        return top_peak.frequency / air_peak.frequency

