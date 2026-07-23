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
    # it a peak can neither be drawn nor admitted. See PEAK-MIN-SEMANTICS.md (GuitarTapWeb).
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
        from .measurement_type import MeasurementType
        from .tap_display_settings import TapDisplaySettings
        m_type = TapDisplaySettings.measurement_type()
        uses_fast_tap_detection = (m_type == MeasurementType.PLATE or m_type == MeasurementType.BRACE)

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

        # For plate/brace, use an adaptive noise-floor threshold (median of the
        # analysis range) instead of the guitar-mode peak_min_threshold so the live peak list
        # self-calibrates to each tap's actual signal level.
        live_threshold = None
        if uses_fast_tap_detection:
            lo_freq = self.min_frequency
            hi_freq = self.max_frequency
            s_idx = next((i for i, f in enumerate(frequencies) if f >= lo_freq), 0)
            e_idx = next((i for i, f in enumerate(frequencies) if f > hi_freq), len(frequencies) - 1)
            if s_idx < e_idx:
                search_mags = sorted(magnitudes[s_idx:e_idx])
                live_threshold = search_mags[len(search_mags) // 2]

        peaks = self.find_peaks(magnitudes, frequencies, peak_min_override=live_threshold)
        # Mirrors Swift allPeaks = peaks — store the durable set; current_peaks is its
        # Peak-Min projection (refreshed by the all_peaks setter).
        self.all_peaks = peaks
        # Auto-select all newly detected peaks so visibility mode «selected»
        # shows everything by default — mirrors Swift selectedPeakIDs = Set(peaks.map { $0.id }).
        # In plate/brace mode, selection is managed exclusively by the phase-completion handlers
        # so that only the identified peak(s) appear selected — don't clobber it here.
        from models.tap_display_settings import TapDisplaySettings as _tds_pa
        if _tds_pa.measurement_type().is_guitar:
            self.selected_peak_ids = {p.id for p in peaks}

        # Classify modes using the context-aware algorithm.
        # Read from TapDisplaySettings — mirrors Swift GuitarMode.classifyAll
        # using TapDisplaySettings.guitarType as the default parameter.
        from models.tap_display_settings import TapDisplaySettings as _tds_classify
        mode_map = GuitarMode.classify_all(peaks, _tds_classify.guitar_type())
        self.identified_modes = [
            {"peak": p, "mode": mode_map.get(p.id, GuitarMode.UNKNOWN)}
            for p in peaks
        ]

        # Notify observers — mirrors Swift @Published var currentPeaks which
        # automatically publishes to all subscribers including the peaks display.
        # Material (plate/brace): do NOT emit on every live FFT frame. The identified L/C/FLC change
        # only at phase completion (driven by the gated-phase handlers via _emit_peaks_array); emitting
        # per frame would re-run the results refresh + annotation rebuild, flickering the table and
        # repainting the whole live spectrum as "Peak". Guitar emits live per frame. (RESPIN-1.0.2, fix R.)
        if m_type.is_guitar:
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
                    for p in self.all_peaks
                    if p.id in self.selected_peak_ids
                ]

        if self.loaded_measurement_peaks is not None:
            # Mirrors Swift: allPeaks = savedPeaks (the FULL saved set — never a filtered
            # view). current_peaks is its Peak-Min projection via the all_peaks setter.
            self.all_peaks = list(self.loaded_measurement_peaks)
            peaks = self.all_peaks
            if not peaks:
                self.identified_modes = []
                self.peaksChanged.emit([])
                return

            modes_by_freq = [
                (entry["peak"].frequency, entry["mode"])
                for entry in self.identified_modes
                if "peak" in entry and "mode" in entry
            ]
            if not modes_by_freq:
                from models.tap_display_settings import TapDisplaySettings as _tds_rfp

                from .guitar_mode import GuitarMode
                # Use classify_all (claiming algorithm) not GuitarMode.classify (simple
                # range lookup per peak) — mirrors Swift GuitarMode.classifyAll(peaks).
                _gt = _tds_rfp.guitar_type()
                _cand = self.loaded_measurement_peaks
                _mode_map = GuitarMode.classify_all(_cand, _gt)
                modes_by_freq = [
                    (p.frequency, _mode_map.get(p.id, GuitarMode.UNKNOWN))
                    for p in _cand
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
            if self.tap_entries:
                self._recalculate_tap_entry_peaks()
            self.peaksChanged.emit(self.current_peaks)
            return

        modes_by_freq = [
            (entry["peak"].frequency, entry["mode"])
            for entry in self.identified_modes
            if "peak" in entry and "mode" in entry
        ]

        # Mirrors Swift: allPeaks = findPeaks(frozen…, peakMinOverride: peakDetectionFloor)
        # — detect the FULL set at the -100 floor; current_peaks is its Peak-Min projection.
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
            modes_by_freq=modes_by_freq,
            offsets_by_freq=offsets_by_freq,
            overrides_by_freq=overrides_by_freq,
            previously_selected_freqs=previously_selected_freqs,
            is_guitar=is_guitar,
            tolerance=tolerance,
        )
        # Recompute per-tap peaks so the multi-tap comparison table reflects
        # the current Peak Min setting.  Mirrors Swift recalculateTapEntryPeaks().
        if self.tap_entries:
            self._recalculate_tap_entry_peaks()
        self.peaksChanged.emit(self.current_peaks)

    # ------------------------------------------------------------------ #
    # _recalculate_tap_entry_peaks
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift recalculateTapEntryPeaks()
    # ------------------------------------------------------------------ #

    def _recalculate_tap_entry_peaks(self) -> None:
        """Re-run peak detection on every stored TapEntry snapshot using the
        current peak_min_threshold, then update tap_entries so the multi-tap
        comparison table shows peaks consistent with the Peak Min slider.
        """
        for entry in self.tap_entries:
            tap_peaks = self.find_peaks(
                list(entry.snapshot.magnitudes),
                list(entry.snapshot.frequencies),
            )
            mode_selected = self.guitar_mode_selected_peak_ids(tap_peaks)
            entry.peaks = tap_peaks
            entry.selected_peak_ids = list(mode_selected)

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
        open-ended: the peaks came from a file; mode assignments were carried forward
        across Peak Min moves rather than re-claimed (``_apply_frozen_peak_state``); the
        analysis range moved; selections were hand-edited.  Proving "it will definitely
        change something" would mean enumerating all of those correctly, forever, with
        nothing to tell us when we got it wrong.  The two failure modes are not
        symmetric: a wrongly-DISABLED button is a dead end (the user cannot force the
        recomputation they want, and has no other route to it), while a wrongly-ENABLED
        one costs a click that recomputes the same answer.

        (The previous rule, ``loaded_measurement_peaks is not None``, was a proxy for
        "the peaks are stale" and was wrong in both directions: it disabled itself after
        a single press, and never lit up for a live capture whose mode assignments had
        drifted.)

        Never for plate/brace: material peaks come from the per-phase captures, and
        running ``find_peaks`` over them would destroy the saved L / C / FLC peaks.
        Material used to be disabled only *by accident* — a loaded material measurement
        leaves the frozen spectrum empty — so the intent is now stated.

        Mirrors Swift ``canReanalyze``.
        """
        from models.tap_display_settings import TapDisplaySettings as _tds_cr

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
        type) without re-tapping.  Clears ``loaded_measurement_peaks`` so that
        ``recalculate_frozen_peaks_if_needed()`` falls through to the live-tap
        path which calls ``find_peaks()`` on the frozen spectrum.

        Also re-claims the mode assignments from scratch: ``identified_modes`` is
        cleared, so the carry-forward in ``_apply_frozen_peak_state`` has nothing to
        match and every peak is classified afresh.  This is the only route back to a
        clean classification once assignments have drifted across Peak Min moves.

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

        # Clear loadedMeasurementPeaks so recalculate_frozen_peaks_if_needed()
        # falls through to the live-tap path, which calls find_peaks() on the
        # frozen spectrum.
        self.loaded_measurement_peaks = None
        self.user_has_modified_peak_selection = False
        self.selected_peak_frequencies = []
        self.identified_modes = []

        # Now re-run the full peak analysis pipeline.
        self.recalculate_frozen_peaks_if_needed()
        from guitar_tap.utilities.logging import gt_log
        gt_log(f"\U0001f52c Re-analyzed peaks from frozen spectrum: "
               f"{len(self.current_peaks)} peaks found")

    # ------------------------------------------------------------------ #
    # reset_to_auto_selection
    # Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift resetToAutoSelection()
    # ------------------------------------------------------------------ #

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
        # stays empty (it was cleared above).  selected_peak_frequencies is a carry-forward
        # cache used by threshold adjustments — not a UI signal.  The view layer pushes
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
        guitar capture on every platform saved one duplicated peak. See
        Development/PEAK-FINDING-DUPLICATE-PEAKS.md in the GuitarTapWeb repo.

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
        from models.tap_display_settings import TapDisplaySettings as _tds_afps

        from .guitar_mode import GuitarMode

        # Mirrors Swift applyFrozenPeakState: freshModeMap = GuitarMode.classifyAll(peaks)
        # Swift uses the claiming algorithm (all peaks together) not single-peak classify,
        # so peaks in the TOP/BACK overlap zone (180–260 Hz) are correctly disambiguated.
        fresh_mode_map = GuitarMode.classify_all(peaks, _tds_afps.guitar_type())

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
            # Plate/brace: selection is managed exclusively by the phase-completion handlers
            # (only the identified peak is selected). Don't clobber it here.
            self.selected_peak_frequencies = [
                p.frequency for p in peaks if p.id in self.selected_peak_ids
            ]
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
        from models.tap_display_settings import TapDisplaySettings as _tds_gms

        from .guitar_mode import GuitarMode

        candidates = peaks if peaks is not None else self.all_peaks
        guitar_type = _tds_gms.guitar_type()

        # Use classify_all (claiming algorithm) — mirrors Swift guitarModeSelectedPeakIDs(from:)
        # which calls GuitarMode.classifyAll(candidates).  Using classify_peak (simple range
        # lookup) is wrong because overlapping TOP/BACK ranges (e.g. 180–260 Hz) cause
        # classify_peak to always return TOP for peaks in the overlap zone, making BACK
        # unselectable when it falls below 260 Hz.
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
        from models.tap_display_settings import TapDisplaySettings as _tds_rcp

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
        self.peaksChanged.emit(list(self.current_peaks))

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


    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold and emit peaksChanged.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — applied when threshold or
        frequency range changes while a measurement is frozen/loaded.

        **Guitar only.**  Peak Min is a guitar-mode control: plate/brace capture uses its own
        adaptive per-phase noise floor, and the identified L / C / FLC peaks ARE the material
        result — they must never be filtered out from under it.  A loaded plate whose fL sits
        below the saved Peak Min (e.g. fL at -62.4 dB with Peak Min -60) otherwise loses that
        peak from both the peak table and the chart annotations.

        Swift reaches the same outcome, but only by accident: recalculateFrozenPeaksIfNeeded
        guards on a non-empty frozen spectrum, and a loaded material measurement leaves the
        frozen spectrum empty, so its equivalent filter is never reached.  We state the intent
        instead of relying on that.  Python's own capture path already branches this way --
        see tap_tone_analyzer_spectrum_capture.py (emit_peaks = ... if is_guitar else
        material_identified_peaks).
        """
        assert self.loaded_measurement_peaks is not None
        # Mirrors Swift: store the FULL loaded set as the durable all_peaks; current_peaks is
        # its Peak-Min projection (guitar filters; material passes through). Emitting the
        # projection keeps the view filtered without all_peaks ever holding a filtered view.
        self.all_peaks = list(self.loaded_measurement_peaks)
        self.peaksChanged.emit(self.current_peaks)

    @staticmethod
    def resolved_mode_peaks(
        peaks: list,
        guitar_type: "str | None" = None,
    ) -> dict:
        """Return {GuitarMode: ResonantPeak} for the highest-magnitude peak per mode.

        Runs GuitarMode.classify_all on ``peaks`` using ``guitar_type`` for mode-range
        boundaries, then returns a map from each identified GuitarMode to the strongest
        ResonantPeak classified into that mode.

        Callers that only need the frequency can use ``peak.frequency``; tests can
        access both ``.frequency`` and ``.magnitude`` directly.

        Mirrors Swift TapToneAnalyzer.resolvedModePeaks(peaks:guitarType:)
        (TapToneAnalyzer+PeakAnalysis.swift).
        """
        from .guitar_mode import GuitarMode
        from .guitar_type import GuitarType

        # Resolve guitar_type string to enum value, falling back to Classical.
        gt: "GuitarType | None" = None
        if guitar_type is not None:
            try:
                gt = GuitarType(guitar_type)
            except Exception:
                gt = GuitarType.CLASSICAL

        mode_map: dict = GuitarMode.classify_all(peaks, gt)

        result: dict = {}
        for peak in peaks:
            mode = mode_map.get(peak.id)
            if mode is None or mode == GuitarMode.UNKNOWN:
                continue
            existing = result.get(mode)
            if existing is not None and peak.magnitude <= existing.magnitude:
                continue
            result[mode] = peak
        return result
