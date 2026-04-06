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
        mirrors Swift recalculateFrozenPeaksIfNeeded() which handles both cases
        in one method rather than at every call site.

        Mirrors Swift TapToneAnalyzer+AnalysisHelpers.swift:
        recalculateFrozenPeaksIfNeeded().
        """
        if self.loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            # Frozen-spectrum path — mirrors Swift analyzeMagnitudes() store+publish block.
            peaks = self.find_peaks(list(self.frozen_magnitudes), list(self.freq))
            self.current_peaks = peaks
            self.peaksChanged.emit(peaks)

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
