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

    def get_peaks(self, low: float, high: float) -> list:
        """Return current peaks whose frequency falls within [low, high] Hz.

        Mirrors Swift ``getPeaks(in:)`` — filters ``currentPeaks`` by a
        closed frequency range.

        Args:
            low:  Lower bound of the Hz range (inclusive).
            high: Upper bound of the Hz range (inclusive).

        Returns:
            Subset of ``current_peaks`` within the range, in source order
            (descending magnitude).
        """
        return [p for p in self.current_peaks if low <= p.frequency <= high]

    def peak_mode(self, peak) -> "GuitarMode":
        """Return the context-aware GuitarMode assigned to *peak*.

        Looks the peak up in ``identified_modes`` (populated by
        ``_apply_frozen_peak_state`` / classify pass).  Falls back to a
        single-element ``GuitarMode.classify`` call for stale references.

        Mirrors Swift ``peakMode(for:)``.
        """
        from .guitar_mode import GuitarMode
        for entry in self.identified_modes:
            if entry.get("peak") and entry["peak"].id == peak.id:
                return entry["mode"]
        # Fall back to classify on the single peak.
        guitar_type = getattr(self, "_guitar_type", None)
        return GuitarMode.classify(peak.frequency, guitar_type)

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

    def compare_to(self, measurement) -> list:
        """Compare live peaks against a saved measurement by frequency proximity.

        For each peak in *measurement.peaks* finds the live peak closest in
        frequency and reports the signed Hz delta.

        Mirrors Swift ``compareTo(_:)``.

        Args:
            measurement: A ``TapToneMeasurement`` whose ``.peaks`` list is
                compared against the current live ``current_peaks``.

        Returns:
            A list of dicts with keys:
              - ``"current"``: the nearest live ``ResonantPeak``, or ``None``
                if ``current_peaks`` is empty.
              - ``"saved"``: the original ``ResonantPeak`` from the measurement.
              - ``"difference"``: ``current.frequency − saved.frequency`` in Hz;
                0 when no current peak is available.
        """
        result = []
        for saved_peak in measurement.peaks:
            if self.current_peaks:
                current_peak = min(
                    self.current_peaks,
                    key=lambda p: abs(p.frequency - saved_peak.frequency),
                )
                difference = current_peak.frequency - saved_peak.frequency
            else:
                current_peak = None
                difference = 0.0
            result.append({
                "current": current_peak,
                "saved": saved_peak,
                "difference": difference,
            })
        return result
