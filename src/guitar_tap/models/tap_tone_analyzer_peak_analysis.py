"""
TapToneAnalyzer+PeakAnalysis — findPeaks, parabolic interpolation, Q-factor,
and mode-priority assembly.

Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
"""

from __future__ import annotations


class TapToneAnalyzerPeakAnalysisMixin:
    """Peak detection and classification for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
    """

    # Proximity threshold for near-duplicate peak removal (Hz).
    # Mirrors Swift TapToneAnalyzer.peakProximityHz.
    PEAK_PROXIMITY_HZ: float = 2.0

    # ------------------------------------------------------------------ #
    # analyze_magnitudes
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift analyzeMagnitudes(_:frequencies:peakMagnitude:)
    # ------------------------------------------------------------------ #

    def analyze_magnitudes(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        peak_magnitude: float,
    ) -> None:
        """Update live peaks from a new FFT frame.

        Called on each FFT output frame while detection is active. Finds peaks,
        updates ``current_peaks``, auto-selects all new peaks, and classifies modes.

        Mirrors Swift ``analyzeMagnitudes(_:frequencies:peakMagnitude:)``.

        Args:
            magnitudes:     Magnitude spectrum in dBFS, one value per FFT bin.
            frequencies:    Frequency axis in Hz matching *magnitudes*.
            peak_magnitude: Maximum bin magnitude in dBFS (used by tap detection
                            and decay tracking; not used in Python peak finding
                            since tap detection is handled separately).
        """
        from .guitar_mode import GuitarMode
        from .guitar_type import GuitarType

        # Only analyze when detection is active, paused (spectrum stays live),
        # or in a capture window; stop once the measurement is complete.
        # Mirrors Swift's guard on isDetecting || isDetectionPaused || captureTimer != nil.
        if not (
            getattr(self, "is_detecting", False)
            or getattr(self, "is_detection_paused", False)
            or getattr(self, "capture_timer", None) is not None
        ):
            return
        if getattr(self, "is_measurement_complete", False):
            return

        peaks = self.find_peaks(magnitudes, frequencies)
        self.current_peaks = peaks
        # Auto-select all newly detected peaks so visibility mode «selected»
        # shows everything by default — mirrors Swift selectedPeakIDs = Set(peaks.map { $0.id }).
        self.selected_peak_ids = {p.id for p in peaks}

        # Classify modes using the context-aware algorithm.
        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
        mode_map = GuitarMode.classify_all(peaks, guitar_type)
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
            for p in peaks
        ]

        # Notify observers — mirrors Swift @Published var currentPeaks which
        # automatically publishes to all subscribers including the peaks display.
        self.peaksChanged.emit(peaks)

    # ------------------------------------------------------------------ #
    # recalculate_frozen_peaks_if_needed / _apply_frozen_peak_state
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift
    # ------------------------------------------------------------------ #

    def recalculate_frozen_peaks_if_needed(self) -> None:
        """Refresh peak display after threshold or frequency-axis change.

        Single unified path for both live and frozen/loaded measurements —
        mirrors Swift recalculateFrozenPeaksIfNeeded().
        """
        if getattr(self, "is_loading_measurement", False):
            return

        import numpy as np
        frozen_mag = self.frozen_magnitudes
        frozen_freq = self.frozen_frequencies
        if (
            not self.is_measurement_complete
            or (hasattr(frozen_freq, "__len__") and len(frozen_freq) == 0)
            or (hasattr(frozen_mag, "__len__") and len(frozen_mag) == 0)
        ):
            return

        is_guitar = getattr(self._measurement_type, "is_guitar", True)
        tolerance = 5.0  # Hz — matches Swift tolerance constant

        # Snapshot frequency-keyed state BEFORE UUIDs change.
        offsets_by_freq = []
        for uid, offset in list(self.peak_annotation_offsets.items()):
            match = next(
                (p for p in self.current_peaks if p.id == uid), None
            )
            if match is not None:
                offsets_by_freq.append((match.frequency, offset))

        overrides_by_freq = []
        for uid, label in list(self.peak_mode_overrides.items()):
            match = next(
                (p for p in self.current_peaks if p.id == uid), None
            )
            if match is not None:
                overrides_by_freq.append((match.frequency, label))

        previously_selected_freqs: list = []
        if is_guitar and self.user_has_modified_peak_selection:
            if self.selected_peak_frequencies:
                previously_selected_freqs = list(self.selected_peak_frequencies)
            elif self.loaded_measurement_peaks:
                previously_selected_freqs = [
                    p.frequency
                    for p in self.loaded_measurement_peaks
                    if p.id in self.selected_peak_ids
                ]
            else:
                previously_selected_freqs = [
                    p.frequency
                    for p in self.current_peaks
                    if p.id in self.selected_peak_ids
                ]

        if self.loaded_measurement_peaks is not None:
            peaks = [
                p for p in self.loaded_measurement_peaks
                if p.magnitude >= self.peak_threshold
            ]
            if not peaks:
                self.current_peaks = []
                self.identified_modes = []
                self.peaksChanged.emit([])
                return

            self.current_peaks = peaks
            modes_by_freq = [
                (entry["peak"].frequency, entry["mode"])
                for entry in self.identified_modes
                if "peak" in entry and "mode" in entry
            ]
            if not modes_by_freq:
                from .guitar_mode import GuitarMode, classify_peak
                from .guitar_type import GuitarType
                guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
                modes_by_freq = [
                    (p.frequency, GuitarMode.classify(p.frequency, guitar_type))
                    for p in self.loaded_measurement_peaks
                ]

            self._apply_frozen_peak_state(
                peaks=peaks,
                modes_by_freq=modes_by_freq,
                offsets_by_freq=offsets_by_freq,
                overrides_by_freq=overrides_by_freq,
                previously_selected_freqs=previously_selected_freqs,
                is_guitar=is_guitar,
                tolerance=tolerance,
            )
            self.peaksChanged.emit(peaks)
            return

        modes_by_freq = [
            (entry["peak"].frequency, entry["mode"])
            for entry in self.identified_modes
            if "peak" in entry and "mode" in entry
        ]

        peaks = self.find_peaks(list(frozen_mag), list(frozen_freq))
        if not peaks:
            self.current_peaks = []
            self.identified_modes = []
            self.peaksChanged.emit([])
            return

        self.current_peaks = peaks
        self._apply_frozen_peak_state(
            peaks=peaks,
            modes_by_freq=modes_by_freq,
            offsets_by_freq=offsets_by_freq,
            overrides_by_freq=overrides_by_freq,
            previously_selected_freqs=previously_selected_freqs,
            is_guitar=is_guitar,
            tolerance=tolerance,
        )
        self.peaksChanged.emit(peaks)

    # ------------------------------------------------------------------ #
    # reset_to_auto_selection
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift resetToAutoSelection()
    # ------------------------------------------------------------------ #

    def reset_to_auto_selection(self) -> None:
        """Clear the manual-modification flag and re-run auto-selection.

        Mirrors Swift ``resetToAutoSelection()``.
        Does nothing if ``current_peaks`` is empty.
        """
        self.user_has_modified_peak_selection = False
        self.selected_peak_frequencies = []
        peaks = self.current_peaks
        if not peaks:
            return
        # Re-run guitar mode auto-selection.
        self.selected_peak_ids = self.guitar_mode_selected_peak_ids(peaks)

    # ------------------------------------------------------------------ #
    # find_peaks
    # Mirrors Swift findPeaks(magnitudes:frequencies:minHz:maxHz:)
    # ------------------------------------------------------------------ #

    def find_peaks(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        min_hz: "float | None" = None,
        max_hz: "float | None" = None,
    ) -> "list":
        """Detect, interpolate, and deduplicate peaks above threshold.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift findPeaks(magnitudes:
        frequencies:minHz:maxHz:) using the same two-pass strategy:

        Pass 1 — Known-mode ranges (sequential, low→high):
            Scans each mode's band for local maxima that exceed peak_threshold.
            The last-claimed-frequency cursor prevents the same physical peak
            from being claimed by two overlapping mode ranges.

        Pass 2 — Unknown/inter-mode peaks:
            Scans the full analysis window for local maxima outside every
            known-mode range.

        Assembly:
            The strongest peak from each mode occupies a guaranteed slot.
            Remaining slots (up to max_peaks, 0 = unlimited) are filled from
            Pass-2 peaks by magnitude.  Final list is sorted by magnitude
            descending.

        Args:
            magnitudes:  dBFS magnitude spectrum, one value per FFT bin.
            frequencies: Frequency axis matching magnitudes, in Hz.
            min_hz:      Lower bound (Hz). Defaults to self.min_frequency.
            max_hz:      Upper bound (Hz). Defaults to self.max_frequency.

        Returns:
            list[ResonantPeak] sorted by magnitude descending.
        """
        from models.guitar_mode import GuitarMode

        if len(magnitudes) != len(frequencies):
            return []

        n = len(magnitudes)
        window_size = 5  # ±5 bins local-max window — mirrors Swift windowSize

        lo_freq = min_hz if min_hz is not None else self.min_frequency
        hi_freq = max_hz if max_hz is not None else self.max_frequency

        # Find start/end indices — mirrors Swift firstIndex(where:)
        start_idx = next((i for i, f in enumerate(frequencies) if f >= lo_freq), 0)
        end_idx   = next((i for i, f in enumerate(frequencies) if f > hi_freq), n - 1)

        # Known modes sorted ascending by range lower bound.
        # Mirrors Swift knownModes sorted by modeRange.lowerBound.
        guitar_type = self._guitar_type
        known_modes = sorted(
            [GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK,
             GuitarMode.DIPOLE, GuitarMode.RING_MODE, GuitarMode.UPPER_MODES],
            key=lambda m: m.mode_range(guitar_type)[0],
        )

        # ---------------------------------------------------------------- #
        # Pass 1: scan each known-mode range for the strongest peak.
        # ---------------------------------------------------------------- #
        # Mirrors Swift Step 1: strongestPeakPerMode, lastClaimedFrequency.
        strongest_per_mode: "dict" = {}  # GuitarMode → ResonantPeak
        last_claimed_frequency: float = 0.0

        for mode in known_modes:
            mode_range = mode.mode_range(guitar_type)
            lo, hi = float(mode_range[0]), float(mode_range[1])

            # Index boundaries for this mode, clamped to analysis window.
            mode_start_idx = next(
                (i for i, f in enumerate(frequencies) if f >= lo), start_idx
            )
            mode_start_idx = max(mode_start_idx, start_idx)
            mode_end_idx = next(
                (i for i, f in enumerate(frequencies) if f > hi), end_idx
            )
            mode_end_idx = min(mode_end_idx, end_idx)
            if mode_start_idx >= mode_end_idx:
                continue

            # Advance scan start past the last claimed peak.
            claimed_idx = next(
                (i for i, f in enumerate(frequencies) if f > last_claimed_frequency),
                start_idx,
            )
            effective_start = max(mode_start_idx, claimed_idx)

            scan_start = max(effective_start, start_idx + window_size)
            scan_end   = min(mode_end_idx,   end_idx   - window_size)
            if scan_start >= scan_end:
                continue

            for i in range(scan_start, scan_end):
                mag = magnitudes[i]
                if mag <= self.peak_threshold:
                    continue

                # Local maximum check — mirrors Swift ±windowSize loop.
                is_local_max = True
                for offset in range(-window_size, window_size + 1):
                    if offset == 0:
                        continue
                    if magnitudes[i + offset] >= mag:
                        is_local_max = False
                        break
                if not is_local_max:
                    continue

                peak = self._make_peak(i, magnitudes, frequencies)

                # Track strongest peak for this mode (normalised key).
                # Mirrors Swift: normalizedMode / strongestPeakPerMode.
                norm_mode = mode.normalized if hasattr(mode, "normalized") else mode
                existing = strongest_per_mode.get(norm_mode)
                if existing is None or mag > existing.magnitude:
                    strongest_per_mode[norm_mode] = peak

            # Advance claimed-frequency cursor.
            # Mirrors Swift: isDuplicate check + lastClaimedFrequency update.
            norm_for_cursor = mode.normalized if hasattr(mode, "normalized") else mode
            claimed = strongest_per_mode.get(norm_for_cursor)
            if claimed is not None:
                # 2 Hz duplicate guard: discard if another mode already claimed
                # a peak at essentially the same frequency.
                is_dup = any(
                    abs(other.frequency - claimed.frequency) < self.PEAK_PROXIMITY_HZ
                    for key, other in strongest_per_mode.items()
                    if key != norm_for_cursor
                )
                if is_dup:
                    del strongest_per_mode[norm_for_cursor]
                else:
                    last_claimed_frequency = max(
                        last_claimed_frequency, claimed.frequency
                    )

        # ---------------------------------------------------------------- #
        # Pass 2: unknown/inter-mode peaks outside all known-mode ranges.
        # ---------------------------------------------------------------- #
        # Mirrors Swift Step 2: outer scan excluding isInKnownMode bins.
        all_peaks: "list" = []
        outer_scan_start = start_idx + window_size
        outer_scan_end   = end_idx   - window_size

        if outer_scan_start < outer_scan_end:
            for i in range(outer_scan_start, outer_scan_end):
                mag = magnitudes[i]
                freq = frequencies[i]

                if mag <= self.peak_threshold:
                    continue

                # Skip bins inside a known-mode range.
                in_known = any(
                    float(m.mode_range(guitar_type)[0]) <= freq <= float(m.mode_range(guitar_type)[1])
                    for m in known_modes
                )
                if in_known:
                    continue

                # Local maximum check.
                is_local_max = True
                for offset in range(-window_size, window_size + 1):
                    if offset == 0:
                        continue
                    if magnitudes[i + offset] >= mag:
                        is_local_max = False
                        break
                if not is_local_max:
                    continue

                all_peaks.append(self._make_peak(i, magnitudes, frequencies))

        # Remove near-duplicates from Pass-2 results.
        all_peaks = self.remove_duplicate_peaks(all_peaks)

        # ---------------------------------------------------------------- #
        # Assembly: guaranteed slots first, then fill by magnitude.
        # ---------------------------------------------------------------- #
        # Mirrors Swift Step 3: finalPeaks, includedPeakIDs.
        guaranteed_peaks = self.remove_duplicate_peaks(
            list(strongest_per_mode.values())
        )
        final_peaks: "list" = list(guaranteed_peaks)
        included_ids: "set[str]" = {p.id for p in final_peaks}

        if self.max_peaks == 0:
            # No limit — add all Pass-2 peaks sorted by magnitude descending.
            others = sorted(
                [p for p in all_peaks if p.id not in included_ids],
                key=lambda p: p.magnitude,
                reverse=True,
            )
            final_peaks.extend(others)
        else:
            remaining_slots = self.max_peaks - len(final_peaks)
            if remaining_slots > 0:
                others = sorted(
                    [p for p in all_peaks if p.id not in included_ids],
                    key=lambda p: p.magnitude,
                    reverse=True,
                )[:remaining_slots]
                final_peaks.extend(others)

        # Sort final result by magnitude descending — mirrors Swift.
        final_peaks = sorted(final_peaks, key=lambda p: p.magnitude, reverse=True)

        # Pure computation — return only.  Mirrors Swift findPeaks() which returns
        # the array and leaves store + publish to the caller (analyzeMagnitudes,
        # recalculateFrozenPeaksIfNeeded, etc.).  Each call site owns its own
        # self.current_peaks = … / self.peaksChanged.emit(…) block.
        return final_peaks

    # ------------------------------------------------------------------ #
    # _apply_frozen_peak_state  (private helper)
    # Mirrors Swift applyFrozenPeakState(peaks:modesByFrequency:...)
    # ------------------------------------------------------------------ #

    def _apply_frozen_peak_state(
        self,
        peaks: list,
        modes_by_freq: list,
        offsets_by_freq: list,
        overrides_by_freq: list,
        previously_selected_freqs: list,
        is_guitar: bool,
        tolerance: float,
    ) -> None:
        """Remap annotation offsets, mode overrides, and selections to new peak UUIDs.

        Mirrors Swift ``applyFrozenPeakState(peaks:modesByFrequency:...)``.
        """
        from .guitar_mode import GuitarMode, classify_peak
        from .guitar_type import GuitarType

        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
        fresh_mode_map = {
            p.id: GuitarMode.classify(p.frequency, guitar_type)
            for p in peaks
        }

        new_identified: list = []
        for new_peak in peaks:
            saved_mode = None
            for freq_val, mode_val in modes_by_freq:
                if abs(freq_val - new_peak.frequency) <= tolerance:
                    saved_mode = mode_val
                    break
            mode = saved_mode if saved_mode is not None else (
                fresh_mode_map.get(new_peak.id, GuitarMode.UNKNOWN)
            )
            new_identified.append({"peak": new_peak, "mode": mode})
        self.identified_modes = new_identified

        new_offsets: dict = {}
        for new_peak in peaks:
            for freq_val, offset_val in offsets_by_freq:
                if abs(freq_val - new_peak.frequency) <= tolerance:
                    new_offsets[new_peak.id] = offset_val
                    break
        self.peak_annotation_offsets = new_offsets

        new_overrides: dict = {}
        for new_peak in peaks:
            for freq_val, label_val in overrides_by_freq:
                if abs(freq_val - new_peak.frequency) <= tolerance:
                    new_overrides[new_peak.id] = label_val
                    break
        self.peak_mode_overrides = new_overrides

        if not is_guitar:
            self.selected_peak_ids = {p.id for p in peaks}
            self.selected_peak_frequencies = [p.frequency for p in peaks]
        elif self.user_has_modified_peak_selection:
            carried_ids: set = set()
            carried_freqs: list = []
            for old_freq in previously_selected_freqs:
                candidates = [
                    p for p in peaks
                    if abs(p.frequency - old_freq) <= tolerance
                ]
                if candidates:
                    closest = min(
                        candidates, key=lambda p: abs(p.frequency - old_freq)
                    )
                    if closest.id not in carried_ids:
                        carried_ids.add(closest.id)
                        carried_freqs.append(closest.frequency)
                else:
                    carried_freqs.append(old_freq)
            self.selected_peak_ids = carried_ids
            self.selected_peak_frequencies = carried_freqs
        else:
            auto_ids = self.guitar_mode_selected_peak_ids(peaks)
            self.selected_peak_ids = auto_ids
            self.selected_peak_frequencies = [
                p.frequency for p in peaks if p.id in auto_ids
            ]

    # ------------------------------------------------------------------ #
    # _make_peak  (private helper)
    # Mirrors Swift makePeak(at:magnitudes:frequencies:)
    # ------------------------------------------------------------------ #

    def _make_peak(
        self,
        index: int,
        magnitudes: "list[float]",
        frequencies: "list[float]",
    ) -> "object":
        """Build a ResonantPeak from a single FFT bin with parabolic interpolation.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift private func
        makePeak(at:magnitudes:frequencies:).

        Args:
            index:      Bin index of the local maximum.
            magnitudes: dBFS magnitude spectrum.
            frequencies: Frequency axis in Hz matching magnitudes.

        Returns:
            A fully-populated ResonantPeak.
        """
        from models.resonant_peak import ResonantPeak

        interp_freq, interp_mag = self._parabolic_interpolate(
            magnitudes, frequencies, index
        )
        quality, bandwidth = self._calculate_q_factor(
            magnitudes, frequencies, index, interp_mag
        )

        # Pitch information — mirrors Swift makePeak pitchCalculator calls.
        pitch_note = None
        pitch_cents = None
        pitch_frequency = None
        if hasattr(self, "pitch_calculator") and self.pitch_calculator is not None:
            try:
                pitch_note      = self.pitch_calculator.note(float(interp_freq))
                pitch_cents     = self.pitch_calculator.cents(float(interp_freq))
                pitch_frequency = self.pitch_calculator.freq0(float(interp_freq))
            except Exception:
                pass

        return ResonantPeak(
            frequency=interp_freq,
            magnitude=interp_mag,
            quality=quality,
            bandwidth=bandwidth,
            pitch_note=pitch_note,
            pitch_cents=pitch_cents,
            pitch_frequency=pitch_frequency,
        )

    # ------------------------------------------------------------------ #
    # guitar_mode_selected_peak_ids
    # Mirrors Swift guitarModeSelectedPeakIDs(from:)
    # ------------------------------------------------------------------ #

    def guitar_mode_selected_peak_ids(self, peaks: "list | None" = None) -> set:
        """Return the set of peak IDs that should be auto-selected for guitar modes.

        Picks the highest-magnitude peak within each claimed guitar mode band
        (Air, Top, Back, Dipole, RingMode, UpperModes).

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift
        ``guitarModeSelectedPeakIDs(from:)``.

        Args:
            peaks: Peaks to evaluate; defaults to ``self.current_peaks``.

        Returns:
            Set of ``ResonantPeak.id`` strings for the auto-selected peaks.
        """
        from .guitar_mode import classify_peak
        from .guitar_type import GuitarType

        candidates = peaks if peaks is not None else self.current_peaks
        claimed_modes = {"Air (Helmholtz)", "Top", "Back", "Dipole", "Ring Mode", "Upper Modes"}
        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL

        best_per_mode: dict = {}
        for peak in candidates:
            mode_label = classify_peak(peak.frequency, guitar_type)
            if mode_label not in claimed_modes:
                continue
            existing = best_per_mode.get(mode_label)
            if existing is None or peak.magnitude > existing.magnitude:
                best_per_mode[mode_label] = peak

        return {p.id for p in best_per_mode.values()}

    # ------------------------------------------------------------------ #
    # reclassify_peaks
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift reclassifyPeaks()
    # ------------------------------------------------------------------ #

    def reclassify_peaks(self) -> None:
        """Re-run mode classification on the current peaks without re-detecting them.

        Called when the guitar type changes (acoustic ↔ classical) so that
        ``identified_modes`` stays consistent with the updated mode-range
        boundaries without requiring a new tap.

        Mirrors Swift ``reclassifyPeaks()``.
        """
        from .guitar_mode import GuitarMode
        from .guitar_type import GuitarType

        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
        mode_map = GuitarMode.classify_all(self.current_peaks, guitar_type)
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
            for p in self.current_peaks
        ]

    # ------------------------------------------------------------------ #
    # remove_duplicate_peaks
    # Mirrors Swift removeDuplicatePeaks(_:)
    # ------------------------------------------------------------------ #

    def remove_duplicate_peaks(self, peaks: "list") -> "list":
        """Remove near-duplicate peaks (within PEAK_PROXIMITY_HZ of each other).

        Keeps the higher-magnitude peak from each near-duplicate pair.
        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift removeDuplicatePeaks(_:).

        Args:
            peaks: Input peak list (any order).

        Returns:
            List with near-duplicates removed, preserving insertion order of
            the first-seen instance (updated if a later duplicate has higher
            magnitude).
        """
        unique: "list" = []
        tol = self.PEAK_PROXIMITY_HZ

        for peak in peaks:
            dup_idx = next(
                (
                    j for j, existing in enumerate(unique)
                    if abs(existing.frequency - peak.frequency) < tol
                ),
                None,
            )
            if dup_idx is None:
                unique.append(peak)
            elif peak.magnitude > unique[dup_idx].magnitude:
                unique[dup_idx] = peak

        return unique

    # ------------------------------------------------------------------ #
    # _parabolic_interpolate  (private helper)
    # Mirrors Swift parabolicInterpolate(magnitudes:frequencies:peakIndex:)
    # ------------------------------------------------------------------ #

    def _parabolic_interpolate(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        i: int,
    ) -> "tuple[float, float]":
        """Refine a bin-level peak using parabolic interpolation.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift
        parabolicInterpolate(magnitudes:frequencies:peakIndex:).

        δ = 0.5 · (α − γ) / (α − 2β + γ),   δ ∈ (−0.5, 0.5)
        f_true  = f_bin + δ · Δf
        A_true  = β − 0.25 · (α − γ) · δ

        Returns:
            (frequency_hz, magnitude_dBFS) of the interpolated peak.
            Falls back to raw bin values at boundaries or flat-top peaks.
        """
        if i <= 0 or i >= len(magnitudes) - 1:
            return frequencies[i], magnitudes[i]

        val  = magnitudes[i]
        lval = magnitudes[i - 1]
        rval = magnitudes[i + 1]
        denom = lval - 2.0 * val + rval

        if abs(denom) <= 1e-6:
            return frequencies[i], val

        delta     = 0.5 * (lval - rval) / denom
        bin_width = frequencies[i] - frequencies[i - 1]
        interp_freq = frequencies[i] + delta * bin_width
        interp_mag  = val - 0.25 * (lval - rval) * delta
        return interp_freq, interp_mag

    # ------------------------------------------------------------------ #
    # _calculate_q_factor  (private helper)
    # Mirrors Swift calculateQFactor(magnitudes:frequencies:peakIndex:peakMagnitude:)
    # ------------------------------------------------------------------ #

    def _calculate_q_factor(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        peak_index: int,
        peak_magnitude: float,
    ) -> "tuple[float, float]":
        """Calculate the Q factor and −3 dB bandwidth for a spectral peak.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift
        calculateQFactor(magnitudes:frequencies:peakIndex:peakMagnitude:).

        Walks outward from peak_index until the magnitude drops below
        peak_magnitude − 3 dB, then computes:
            bandwidth = f_upper − f_lower
            Q         = f_centre / bandwidth

        Returns:
            (quality, bandwidth_hz).  Both are 0.0 if index bounds are exceeded.
        """
        n = len(magnitudes)
        threshold = peak_magnitude - 3.0

        lower_idx = peak_index
        while lower_idx > 0 and magnitudes[lower_idx] > threshold:
            lower_idx -= 1

        upper_idx = peak_index
        while upper_idx < n - 1 and magnitudes[upper_idx] > threshold:
            upper_idx += 1

        if peak_index >= len(frequencies) or lower_idx >= len(frequencies) or upper_idx >= len(frequencies):
            return 0.0, 0.0

        lower_freq  = frequencies[lower_idx]
        upper_freq  = frequencies[upper_idx]
        center_freq = frequencies[peak_index]

        bandwidth = upper_freq - lower_freq
        quality   = center_freq / bandwidth if bandwidth > 0.0 else 0.0

        return quality, bandwidth

    # ------------------------------------------------------------------ #
    # average_spectra
    # Mirrors Swift averageSpectra(from:)
    # ------------------------------------------------------------------ #

    def average_spectra(
        self,
        from_taps: "list[tuple]",
    ) -> "tuple[list[float], list[float]]":
        """Average multiple captured spectra in the linear power domain.

        Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift averageSpectra(from:).

        Each element of from_taps must have:
            .magnitudes (or [0]) — dBFS magnitude array
            .frequencies (or [1]) — frequency axis in Hz

        Averaging in the power domain (not amplitude or dB) is physically
        correct for non-periodic impulse responses where inter-tap phase
        alignment cannot be guaranteed.  Mirrors Swift:
            p_avg = (1/N) × Σ 10^(dB_n / 10)   [per bin]
            dB_avg = 10 × log10(p_avg)

        Args:
            from_taps: List of tap-capture tuples/objects.  Each entry is
                       expected to expose .magnitudes and .frequencies, OR
                       be a plain tuple (magnitudes, frequencies[, ...]).

        Returns:
            (frequencies, magnitudes) — averaged frequency axis and dBFS
            magnitude array, both as list[float].  Returns ([], []) if
            from_taps is empty.
        """
        import math

        if not from_taps:
            return [], []

        # Accept both named-attribute objects and plain (mags, freqs[, ...]) tuples.
        def _mags(entry):
            return entry.magnitudes if hasattr(entry, "magnitudes") else entry[0]

        def _freqs(entry):
            return entry.frequencies if hasattr(entry, "frequencies") else entry[1]

        freqs = list(_freqs(from_taps[0]))
        n_bins = len(freqs)
        n_taps = len(from_taps)

        # Accumulate linear power per bin.
        power_sum = [0.0] * n_bins
        for tap in from_taps:
            mags = _mags(tap)
            for b in range(min(n_bins, len(mags))):
                # 10^(dB / 10) — power domain averaging (mirrors Swift).
                power_sum[b] += 10.0 ** (mags[b] / 10.0)

        # Convert averaged power back to dB.
        avg_mags = [
            10.0 * math.log10(max(power_sum[b] / n_taps, 1e-30))
            for b in range(n_bins)
        ]

        return freqs, avg_mags

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold and emit peaksChanged.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — applied when threshold or
        frequency range changes while a measurement is frozen/loaded.
        """
        assert self.loaded_measurement_peaks is not None
        threshold_db = self.peak_threshold
        filtered = [p for p in self.loaded_measurement_peaks if p.magnitude >= threshold_db]

        self.current_peaks = filtered
        self.peaksChanged.emit(filtered)
