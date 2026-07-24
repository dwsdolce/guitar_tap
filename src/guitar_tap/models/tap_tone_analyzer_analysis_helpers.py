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
        # AUTO classification (override-blind): identified_modes (populated by the classify pass),
        # falling back to a single-element classify_all for stale references. Mirrors Swift's
        # peakMode auto resolution.
        auto = GuitarMode.UNKNOWN
        for entry in self.identified_modes:
            if entry.get("peak") and entry["peak"].id == peak.id:
                auto = entry["mode"]
                break
        else:
            from models.tap_display_settings import TapDisplaySettings as _tds_pm
            auto = GuitarMode.classify_all([peak], _tds_pm.guitar_type()).get(peak.id, GuitarMode.UNKNOWN)
        # Effective = the ONE shared resolver — an override wins over auto (freeform → UNKNOWN).
        # Mirrors Swift peakMode delegating to GuitarMode.effectiveMode.
        return GuitarMode.effective_mode(self.peak_mode_overrides.get(peak.id), auto)

    def get_peak(self, mode: "GuitarMode") -> "ResonantPeak | None":
        """Return the **definitive** peak for *mode*: the **selected** peak whose **override-aware**
        mode is *mode*.

        Not the strongest auto-classified peak — the one the user (or auto-selection) chose AND whose
        effective mode is *mode*. So renaming the Top peak removes it from the ratio just as it
        removes it from every display surface. By the Phase 5 invariant there is at most one
        definitive Air/Top/Back; ``max`` guards the legacy case. Mode comparison uses ``normalized``
        so legacy aliases resolve. Mirrors Swift ``getPeak(for:)``.
        """
        candidates = [
            p for p in self.all_peaks
            if p.id in self.selected_peak_ids
            and self.peak_mode(p).normalized == mode.normalized
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

    def definitive_mode_info(self) -> "dict":
        """The definitive Air/Top/Back, each flagged if it is the user's manual override — the
        source for the multi-tap Averaged row.

        Returns ``{GuitarMode: (frequency: float, is_override: bool)}``. Uses the same definitive
        rule as ``get_peak`` and the ratio, so the Averaged row agrees with the main panel; the flag
        lets the view mark an overridden value so it is not confused with the averaged spectrum's
        auto-detected peak. Mirrors Swift ``TapToneAnalyzer.definitiveModeInfo()``.
        """
        from .guitar_mode import GuitarMode
        out: dict = {}
        for mode in (GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK):
            p = self.get_peak(mode)
            if p is None:
                continue
            out[mode] = (p.frequency, self.has_manual_override(p.id))
        return out

