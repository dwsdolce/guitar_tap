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

    def recalculate_frozen_peaks_if_needed(self) -> None:
        """Refresh peak display after threshold or frequency-axis change.

        Single unified path for both live and frozen/loaded measurements —
        mirrors Swift recalculateFrozenPeaksIfNeeded().

        Additions vs the prior Python stub:
        - Respects ``is_loading_measurement`` guard (mirrors Swift).
        - Snaps annotation offsets, mode overrides, and peak selections by
          frequency proximity to the new peak UUIDs via
          ``_apply_frozen_peak_state()`` (mirrors Swift applyFrozenPeakState).

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift:
        recalculateFrozenPeaksIfNeeded().
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
        # Annotation offsets: (frequency, offset) for each stored entry.
        offsets_by_freq = []
        for uid, offset in list(self.peak_annotation_offsets.items()):
            match = next(
                (p for p in self.current_peaks if p.id == uid), None
            )
            if match is not None:
                offsets_by_freq.append((match.frequency, offset))

        # Mode overrides: (frequency, label) for each stored entry.
        overrides_by_freq = []
        for uid, label in list(self.peak_mode_overrides.items()):
            match = next(
                (p for p in self.current_peaks if p.id == uid), None
            )
            if match is not None:
                overrides_by_freq.append((match.frequency, label))

        # Previously-selected frequencies (for carry-forward when user has modified).
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

        # Loaded-measurement path: filter saved peaks by threshold.
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
            # Seed modesByFrequency from identified_modes cache, or reclassify.
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

        # Live-tap path: re-run find_peaks on frozen spectrum.
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

        Called after ``find_peaks`` or loaded-peak threshold filtering, when
        the peak array may carry new UUIDs while representing the same physical
        resonances at approximately the same frequencies.

        Mirrors Swift ``applyFrozenPeakState(peaks:modesByFrequency:...)``.
        """
        from .guitar_mode import GuitarMode, classify_peak
        from .guitar_type import GuitarType

        guitar_type = getattr(self, "_guitar_type", None) or GuitarType.CLASSICAL
        fresh_mode_map = {
            p.id: GuitarMode.classify(p.frequency, guitar_type)
            for p in peaks
        }

        # Remap mode classifications to new UUIDs.
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

        # Remap annotation offsets to new UUIDs by frequency proximity.
        new_offsets: dict = {}
        for new_peak in peaks:
            for freq_val, offset_val in offsets_by_freq:
                if abs(freq_val - new_peak.frequency) <= tolerance:
                    new_offsets[new_peak.id] = offset_val
                    break
        self.peak_annotation_offsets = new_offsets

        # Remap mode overrides to new UUIDs by frequency proximity.
        new_overrides: dict = {}
        for new_peak in peaks:
            for freq_val, label_val in overrides_by_freq:
                if abs(freq_val - new_peak.frequency) <= tolerance:
                    new_overrides[new_peak.id] = label_val
                    break
        self.peak_mode_overrides = new_overrides

        if not is_guitar:
            # Plate/brace: frozen peaks are final — select all.
            self.selected_peak_ids = {p.id for p in peaks}
            self.selected_peak_frequencies = [p.frequency for p in peaks]
        elif self.user_has_modified_peak_selection:
            # Carry forward selections by frequency proximity.
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
                    # Peak below threshold — preserve frequency for re-select later.
                    carried_freqs.append(old_freq)
            self.selected_peak_ids = carried_ids
            self.selected_peak_frequencies = carried_freqs
        else:
            # No manual changes: re-run auto-selection.
            auto_ids = self.guitar_mode_selected_peak_ids(peaks)
            self.selected_peak_ids = auto_ids
            self.selected_peak_frequencies = [
                p.frequency for p in peaks if p.id in auto_ids
            ]

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold and emit peaksChanged.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — applied when threshold or
        frequency range changes while a measurement is frozen/loaded.
        Viewport filtering (fmin/fmax) is applied by the results panel at display time.
        """
        assert self.loaded_measurement_peaks is not None
        threshold_db = self.peak_threshold
        filtered = [p for p in self.loaded_measurement_peaks if p.magnitude >= threshold_db]

        self.current_peaks = filtered
        # Emit all threshold-passing peaks — viewport filtering applied by results panel.
        self.peaksChanged.emit(filtered)

    def process_averages(self, mag_y) -> None:
        """Accumulate and average FFT linear magnitudes.

        Mirrors Swift TapToneAnalyzer+SpectrumCapture averageSpectra / processMultipleTaps.
        Emits newSample, averagesChanged, spectrumUpdated on each triggered frame.
        """
        import numpy as np

        if self.num_averages < self.max_average_count:
            if self.num_averages > 0:
                mag_y_sum = self.mag_y_sum + mag_y
            else:
                mag_y_sum = mag_y
            num_averages = self.num_averages + 1

            avg_mag_y = mag_y_sum / num_averages
            avg_mag_y[avg_mag_y < np.finfo(float).eps] = np.finfo(float).eps
            avg_mag_y_db = 20 * np.log10(avg_mag_y)

            avg_amplitude = np.max(avg_mag_y_db) + 100
            if avg_amplitude > (self.peak_threshold + 100):
                avg_peaks = self.find_peaks(list(avg_mag_y_db), list(self.freq))
                if avg_peaks:
                    self.current_peaks = avg_peaks
                    self.peaksChanged.emit(avg_peaks)
                triggered = len(avg_peaks) > 0
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))
                    self.frozen_magnitudes = avg_mag_y_db
                    self.spectrumUpdated.emit(self.freq, avg_mag_y_db)

        self.spectrumUpdated.emit(self.freq, self.frozen_magnitudes)
