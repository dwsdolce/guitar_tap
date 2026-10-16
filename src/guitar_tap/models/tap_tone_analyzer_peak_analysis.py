"""
TapToneAnalyzer+PeakAnalysis — findPeaks, parabolic interpolation, Q-factor,
and mode-priority assembly.

Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
"""

# @parity dsp/peak-analysis

from __future__ import annotations


class TapToneAnalyzerPeakAnalysisMixin:
    """Peak detection and classification for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
    """

    # Proximity threshold for near-duplicate peak removal (Hz).
    # Mirrors Swift TapToneAnalyzer.peakProximityHz.
    PEAK_PROXIMITY_HZ: float = 2.0

    # Absolute magnitude floor (dBFS) for the peak set persisted with a guitar measurement.
    # A saved measurement records every peak down to this floor, not just those above the current
    # Peak Min, so a reloaded measurement can reveal peaks below the capture-time Peak Min exactly
    # as the live one can. -100 dB is the chart floor and the Peak Min slider's lower bound — below
    # it a peak can neither be drawn nor admitted.
    PEAK_DETECTION_FLOOR: float = -100.0

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

        Called on each FFT output frame while detection is active. For a guitar sequence finds
        peaks at Peak Min, updates ``peaks_above_peak_min``, auto-selects all new peaks, and
        classifies modes; a material sequence has no live peaks.

        Mirrors Swift ``analyzeMagnitudes(_:frequencies:peakMagnitude:)``.

        Args:
            magnitudes:     Magnitude spectrum in dBFS, one value per FFT bin.
            frequencies:    Frequency axis in Hz matching *magnitudes*.
            peak_magnitude: Maximum bin magnitude in dBFS (used by tap detection
                            and decay tracking; not used in Python peak finding
                            since tap detection is handled separately).
        """
        from .guitar_mode import GuitarMode
        from .tap_display_settings import TapDisplaySettings

        # Nothing to analyze unless the engine is running. Mirrors Swift's guard fftAnalyzer.isRunning.
        if self.mic is None or self.mic.is_stopped:
            return

        # Only analyze when detection is active, paused (spectrum stays live),
        # or in a capture window; stop once the measurement is complete.
        # Mirrors Swift's guard on isDetecting || isDetectionPaused || captureTimer != nil.
        if not (
            getattr(self, "is_detecting", False)
            or getattr(self, "is_detection_paused", False)
            or getattr(self, "capture_timer_active", False)
        ):
            return
        if getattr(self, "is_measurement_complete", False):
            return

        # Material (plate/brace) has no live peaks: its peaks are the identified L/C/FLC
        # (material_identified_peaks), and all_peaks is guitar-only. Mirrors Swift.
        if not TapDisplaySettings.measurement_type().is_guitar:
            if self.all_peaks:
                self.all_peaks = []
                self.identified_modes = []
            return

        peaks = self.find_peaks(magnitudes, frequencies)
        # Mirrors Swift allPeaks = peaks — store the durable set; peaks_above_peak_min is its
        # Peak-Min projection (refreshed by the all_peaks setter).
        self.all_peaks = peaks
        # Auto-select all newly detected peaks so visibility mode «selected»
        # shows everything by default — mirrors Swift selectedPeakIDs = Set(peaks.map { $0.id }).
        self.selected_peak_ids = {p.id for p in peaks}

        # Classify modes using the context-aware algorithm.
        # Read from TapDisplaySettings — mirrors Swift GuitarMode.classifyAll
        # using TapDisplaySettings.guitarType as the default parameter.
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds_classify
        mode_map = GuitarMode.classify_all(peaks, _tds_classify.guitar_type())
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
            for p in peaks
        ]

        # Notify observers — mirrors Swift @Published var currentPeaks which
        # automatically publishes to all subscribers including the peaks display. (Material returned
        # above: its identified L/C/FLC are emitted at phase completion via _emit_peaks_array.)
        self.peaksChanged.emit(peaks)

    # ------------------------------------------------------------------ #
    # recalculate_frozen_peaks_if_needed / _apply_frozen_peak_state
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift
    # ------------------------------------------------------------------ #

    def recalculate_frozen_peaks_if_needed(self) -> None:
        """Re-analyze's re-detection: re-run peak finding on the frozen spectrum, classify the new
        peaks afresh and auto-select them, and carry each peak's dragged label position and custom
        name onto the new peak by frequency.

        Reached only through ``reanalyze_peaks``, which checks first that the measurement is complete
        and its spectrum frozen (Peak Min only projects the durable set). Mirrors Swift
        recalculateFrozenPeaksIfNeeded().
        """
        frozen_mag = self.frozen_magnitudes
        frozen_freq = self.frozen_frequencies

        tolerance = 5.0  # Hz — matches Swift tolerance constant

        # Snapshot frequency-keyed state BEFORE UUIDs change.
        offsets_by_freq = []
        for uid, offset in list(self.peak_annotation_offsets.items()):
            # Resolve against the DURABLE set, not the display projection — a peak hidden
            # by Peak Min still owns its dragged label. Mirrors Swift (reads allPeaks).
            match = next(
                (p for p in self.all_peaks if p.id == uid), None
            )
            if match is not None:
                offsets_by_freq.append((match.frequency, offset))

        overrides_by_freq = []
        for uid, label in list(self.peak_mode_overrides.items()):
            # Durable set — a hidden peak keeps its custom mode name. Mirrors Swift (allPeaks).
            match = next(
                (p for p in self.all_peaks if p.id == uid), None
            )
            if match is not None:
                overrides_by_freq.append((match.frequency, label))

        # Mirrors Swift: allPeaks = findPeaks(frozen…, peakMinOverride: peakDetectionFloor)
        # — detect the FULL set at the -100 floor; peaks_above_peak_min is its Peak-Min projection.
        self.all_peaks = self.find_peaks(
            list(frozen_mag), list(frozen_freq),
            peak_min_override=self.PEAK_DETECTION_FLOOR,
        )
        peaks = self.all_peaks
        if not peaks:
            self.identified_modes = []
            self.peaksChanged.emit([])
            return

        self._apply_frozen_peak_state(
            peaks=peaks,
            offsets_by_freq=offsets_by_freq,
            overrides_by_freq=overrides_by_freq,
            tolerance=tolerance,
        )
        # TapEntry peaks are computed once, at capture, and are durable; a display recalc never
        # re-derives them.
        self.peaksChanged.emit(self.peaks_above_peak_min)

    # A TapEntry's peaks are computed ONCE, at capture, over the full set (see the per-tap block in
    # tap_tone_analyzer_spectrum_capture.py) and are never re-derived — not by a recalc, not on load,
    # not by a display control. tap_entries is PERSISTED, so re-deriving at the current Peak Min would
    # truncate the saved per-tap set and make a reloaded multi-tap measurement disagree with a fresh
    # one. Mirrors Swift.

    # ------------------------------------------------------------------ #
    # can_reanalyze
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift canReanalyze
    # ------------------------------------------------------------------ #

    @property
    def can_reanalyze(self) -> bool:
        """Whether the Re-analyze button is offered.

        **Any complete guitar measurement with a frozen spectrum**, and never a
        plate/brace one.

        Re-analyze is a **reset**, not a dirty-flag indicator.  It is offered whenever
        it *could* do something, not only when we can prove it *will* — deliberately.
        What can leave the displayed analysis differing from a clean re-derivation is
        open-ended: the peaks came from a file; the guitar type or the analysis range
        moved; selections or mode names were hand-edited.  Proving "it will definitely
        change something" would mean enumerating all of those correctly, forever, with
        nothing to tell us when we got it wrong.  The two failure modes are not
        symmetric: a wrongly-DISABLED button is a dead end (the user cannot force the
        recomputation they want, and has no other route to it), while a wrongly-ENABLED
        one costs a click that recomputes the same answer.

        (The previous rule, "a measurement is loaded", was a proxy for "the peaks are
        stale" and was wrong in both directions: it disabled itself after a single press,
        and never lit up for a live capture whose mode assignments had drifted.)

        Never for plate/brace: material peaks come from the per-phase captures, and
        running ``find_peaks`` over them would destroy the saved L / C / FLC peaks.
        Material used to be disabled only *by accident* — a loaded material measurement
        leaves the frozen spectrum empty — so the intent is now stated.

        Mirrors Swift ``canReanalyze``.
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds_cr

        return (
            _tds_cr.measurement_type().is_guitar
            and self.is_measurement_complete
            and bool(len(self.frozen_frequencies))
            and bool(len(self.frozen_magnitudes))
        )

    # ------------------------------------------------------------------ #
    # reanalyze_peaks
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift reanalyzePeaks()
    # ------------------------------------------------------------------ #

    def reanalyze_peaks(self) -> None:
        """Re-run peak detection on the frozen spectrum using the current analysis settings.

        Lets the user retune a saved measurement (Peak Min, analysis range, guitar
        type) without re-tapping: ``recalculate_frozen_peaks_if_needed()`` runs
        ``find_peaks()`` on the frozen spectrum, and the re-detected peaks replace the
        saved ones.

        Also re-claims the mode assignments from scratch: every peak is classified afresh.

        What survives: user mode **overrides** (remapped onto the new peak ids by ±5 Hz
        frequency proximity) and annotation offsets.  What does not: the manual
        **selection** — auto-selection re-runs, so a hand-selected peak is deselected
        (its override is still attached; re-select it and the custom label returns).

        Mirrors Swift ``reanalyzePeaks()``.
        """
        if (
            not self.is_measurement_complete
            or not len(self.frozen_frequencies)
            or not len(self.frozen_magnitudes)
        ):
            return

        self.user_has_modified_peak_selection = False
        self.selected_peak_frequencies = []
        self.identified_modes = []

        # Now re-run the full peak analysis pipeline.
        self.recalculate_frozen_peaks_if_needed()
        from guitar_tap.utilities.logging import gt_log
        gt_log(f"\U0001f52c Re-analyzed peaks from frozen spectrum: "
               f"{len(self.peaks_above_peak_min)} peaks found")

    # ------------------------------------------------------------------ #
    # reset_to_auto_selection
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift resetToAutoSelection()
    # ------------------------------------------------------------------ #

    def reclassify_for_guitar_type_change(self) -> None:
        """Apply a guitar-subtype change (e.g. Classical → Flamenco) as a **clean slate** for the new
        type.

        The guitar type changes what "Top" *means* (the mode bands), so classification and selection
        are re-derived for the new type, and manual mode labels — made against the OLD bands' meaning —
        are cleared. Peak identities and dragged-label positions are untouched (this does not
        re-detect; ``reclassify_peaks`` only recomputes modes). Contract: *"Changing the guitar type
        re-analyses every peak for the new type; manual labels and selections are cleared."*

        Deliberately NOT the wand (``reset_to_auto_selection``), which preserves the labels — the wand
        is the user's "clear my selection, give me pure auto" action and must stay reachable. Mirrors
        Swift ``reclassifyForGuitarTypeChange()``.
        """
        self.peak_mode_overrides = {}
        self.reclassify_peaks()
        self.reset_to_auto_selection()

    def reset_to_auto_selection(self) -> None:
        """Clear the manual-modification flag and re-run auto-selection.

        Mirrors Swift ``resetToAutoSelection()``.
        Does nothing if ``all_peaks`` is empty.
        """
        self.user_has_modified_peak_selection = False
        self.selected_peak_frequencies = []
        # Auto-selection runs over the DURABLE set, never the display projection — a
        # selected peak may legitimately sit below Peak Min. Mirrors Swift `let peaks = allPeaks`.
        peaks = self.all_peaks
        if not peaks:
            return
        # Re-run guitar mode auto-selection.
        # Mirrors Swift exactly: only selected_peak_ids is set; selected_peak_frequencies
        # stays empty (it was cleared above); it is not a UI signal.  The view layer pushes
        # the selection to the model directly after calling this method.
        self.selected_peak_ids = self.guitar_mode_selected_peak_ids(peaks)

    # ------------------------------------------------------------------ #
    def find_peaks(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        min_hz: "float | None" = None,
        max_hz: "float | None" = None,
        peak_min_override: "float | None" = None,
    ) -> "list":
        """Detect every significant spectral peak within the configured range.

        **Detection only — this function knows nothing about guitar modes.**

        A single sweep over the spectrum in ascending frequency order. Each bin is
        visited exactly once and mints at most one ResonantPeak, so two peaks can
        never describe the same spectral feature.

        This is deliberate and load-bearing. The previous implementation iterated the
        mode ranges as its outer loop and the bins as its inner loop; because Top and
        Back overlap on every guitar type, a bin inside the overlap was scanned by two
        mode passes and _make_peak was called on it twice, minting two peaks with two
        ids and otherwise identical values. The assembly step then reconciled two
        independently deduplicated lists **by id** and let the twin survive, so every
        guitar capture on every platform saved one duplicated peak.

        Classification and mode claiming belong to GuitarMode.classify_all(), which
        operates on the returned peak *list* — where each peak has one identity and can
        be claimed exactly once. Do not reintroduce mode-range awareness here.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift findPeaks(magnitudes:
        frequencies:minHz:maxHz:peakMinOverride:).

        Args:
            magnitudes:          dBFS magnitude spectrum, one value per FFT bin.
            frequencies:         Frequency axis matching magnitudes, in Hz.
            min_hz:              Lower bound (Hz). Defaults to self.min_frequency.
            max_hz:              Upper bound (Hz). Defaults to self.max_frequency.
            peak_min_override:   When set, used as the magnitude gate instead of
                                 self.peak_min_threshold. Pass the median of the search
                                 range for plate/brace to get an adaptive noise floor.

        Returns:
            list[ResonantPeak] sorted by magnitude descending.
        """
        if len(magnitudes) != len(frequencies):
            return []

        n = len(magnitudes)
        window_size = 5  # ±5 bins local-max window — mirrors Swift windowSize

        lo_freq = min_hz if min_hz is not None else self.min_frequency
        hi_freq = max_hz if max_hz is not None else self.max_frequency

        # Find start/end indices — mirrors Swift firstIndex(where:)
        start_idx = next((i for i, f in enumerate(frequencies) if f >= lo_freq), 0)
        end_idx   = next((i for i, f in enumerate(frequencies) if f > hi_freq), n - 1)

        # For plate/brace the caller may supply an adaptive noise-floor threshold
        # (median of the search range) instead of the guitar-mode peak_min_threshold.
        # Mirrors Swift: effectiveThreshold = peakMinOverride ?? peakMinThreshold.
        effective_threshold = peak_min_override if peak_min_override is not None else self.peak_min_threshold

        # The ±window_size local-maximum test needs that many neighbours on each side.
        scan_start = start_idx + window_size
        scan_end   = end_idx - window_size
        if scan_start >= scan_end:
            return []

        peaks: "list" = []

        for i in range(scan_start, scan_end):
            magnitude = magnitudes[i]
            if magnitude <= effective_threshold:
                continue

            # Local maximum check
            is_local_max = True
            for offset in range(-window_size, window_size + 1):
                if offset == 0:
                    continue
                if magnitudes[i + offset] >= magnitude:
                    is_local_max = False
                    break
            if not is_local_max:
                continue

            peaks.append(self._make_peak(i, magnitudes, frequencies))

        # Two adjacent bins can still resolve to interpolated vertices within
        # peak_proximity_hz of one another; collapse those, keeping the louder.
        return sorted(
            self.remove_duplicate_peaks(peaks),
            key=lambda p: p.magnitude,
            reverse=True,
        )

    # ------------------------------------------------------------------ #
    # _apply_frozen_peak_state  (private helper)
    # Mirrors Swift applyFrozenPeakState(peaks:modesByFrequency:...)
    # ------------------------------------------------------------------ #

    def _apply_frozen_peak_state(
        self,
        peaks: list,
        offsets_by_freq: list,
        overrides_by_freq: list,
        tolerance: float,
    ) -> None:
        """Classify the new peaks afresh, remap annotation offsets and mode overrides to their UUIDs
        by frequency proximity, and auto-select.

        Mirrors Swift ``applyFrozenPeakState(peaks:offsetsByFrequency:...)``.
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds_afps

        from .guitar_mode import GuitarMode

        # The claiming algorithm (all peaks together), as Swift's classifyAll, so peaks in the
        # TOP/BACK overlap zone (180–260 Hz) are disambiguated.
        mode_map = GuitarMode.classify_all(peaks, _tds_afps.guitar_type())
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)} for p in peaks
        ]

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

        auto_ids = self.guitar_mode_selected_peak_ids(peaks)
        self.selected_peak_ids = auto_ids
        self.selected_peak_frequencies = [p.frequency for p in peaks if p.id in auto_ids]

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
        from guitar_tap.models.resonant_peak import ResonantPeak

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
            peaks: Peaks to evaluate; defaults to ``self.all_peaks`` (the durable set —
                   auto-selection is a fact about the measurement, not the display).

        Returns:
            Set of ``ResonantPeak.id`` strings for the auto-selected peaks.
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds_gms

        from .guitar_mode import GuitarMode

        candidates = peaks if peaks is not None else self.all_peaks
        guitar_type = _tds_gms.guitar_type()

        # The claiming algorithm (classify_all) — mirrors Swift guitarModeSelectedPeakIDs(from:),
        # which calls GuitarMode.classifyAll(candidates). A per-frequency lookup would return TOP
        # for every peak in the overlapping TOP/BACK ranges (e.g. 180–260 Hz), making BACK
        # unselectable there.
        claimed_modes = {GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK,
                         GuitarMode.DIPOLE, GuitarMode.RING_MODE, GuitarMode.UPPER_MODES}
        mode_map = GuitarMode.classify_all(candidates, guitar_type)

        best_per_mode: dict = {}
        for peak in candidates:
            mode = mode_map.get(peak.id)
            if mode not in claimed_modes:
                continue
            existing = best_per_mode.get(mode)
            if existing is None or peak.magnitude > existing.magnitude:
                best_per_mode[mode] = peak

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
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds_rcp

        from .guitar_mode import GuitarMode

        mode_map = GuitarMode.classify_all(self.all_peaks, _tds_rcp.guitar_type())
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
            for p in self.all_peaks
        ]
        # Unlike Swift where @Published identified_modes auto-notifies subscribers,
        # Python requires an explicit signal emission so the scatter plot and results
        # panel receive the reclassified peaks.  Mirrors the pattern used in
        # recalculate_frozen_peaks_if_needed() and analyze_magnitudes().
        self.peaksChanged.emit(list(self.peaks_above_peak_min))

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


    def _emit_displayed_peaks(self) -> None:
        """Announce the peaks to show as ``peaksChanged`` — the view's peak list, chart markers and
        annotations take them from this signal. Guitar: the Peak-Min projection of the durable set.
        Material (plate/brace): the identified L / C / FLC peaks, unfiltered — they ARE the result,
        and Peak Min is a guitar control. The capture path emits the same way (``_emit_peaks_array``).
        Mirrors Swift's views reading ``peaksAbovePeakMin`` / ``materialIdentifiedPeaks``.
        """
        if not self._tds.measurement_type().is_guitar:
            self.peaksChanged.emit(list(self.material_identified_peaks))
            return
        self.peaksChanged.emit(self.peaks_above_peak_min)

    @staticmethod
    def resolved_mode_peaks(
        peaks: list,
        overrides: "dict | None" = None,
        guitar_type: "str | None" = None,
    ) -> dict:
        """Return {GuitarMode: ResonantPeak} for the highest-magnitude peak per EFFECTIVE mode.

        Runs GuitarMode.classify_all on ``peaks`` using ``guitar_type`` for mode-range
        boundaries, then — override-aware, so a relabelled peak resolves to the mode the user
        assigned — returns a map from each identified GuitarMode to the strongest ResonantPeak
        whose effective mode is that mode.

        ``overrides`` is ``{peak id: label str}`` (the measurement's ``peak_mode_overrides``);
        ``{}``/``None`` reproduces the old override-blind behaviour.

        Callers that only need the frequency can use ``peak.frequency``; tests can
        access both ``.frequency`` and ``.magnitude`` directly.

        Mirrors Swift TapToneAnalyzer.resolvedModePeaks(peaks:overrides:guitarType:)
        (TapToneAnalyzer+PeakAnalysis.swift).
        """
        from .guitar_mode import GuitarMode
        from .guitar_type import GuitarType

        ovr = overrides or {}

        # Resolve guitar_type string to enum value, falling back to Generic.
        gt: "GuitarType | None" = None
        if guitar_type is not None:
            try:
                gt = GuitarType(guitar_type)
            except Exception:
                gt = GuitarType.GENERIC

        mode_map: dict = GuitarMode.classify_all(peaks, gt)

        result: dict = {}
        for peak in peaks:
            # Override-aware, so a relabelled peak resolves to the mode the user assigned — the
            # same rule the analyzer and the ratio use.
            mode = GuitarMode.effective_mode(
                ovr.get(peak.id), mode_map.get(peak.id, GuitarMode.UNKNOWN)
            )
            if mode == GuitarMode.UNKNOWN:
                continue
            existing = result.get(mode)
            if existing is not None and peak.magnitude <= existing.magnitude:
                continue
            result[mode] = peak
        return result
