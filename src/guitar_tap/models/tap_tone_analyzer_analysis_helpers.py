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

    def _recalculate_peaks(self) -> None:
        """Refresh peak display after threshold or frequency-axis change.

        Single unified path for both live and frozen/loaded measurements —
        mirrors Swift recalculateFrozenPeaksIfNeeded which handles both cases
        in one method rather than at every call site.
        """
        if self.loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            self.find_peaks(list(self.frozen_magnitudes), list(self.freq))

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold and emit peaksChanged.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — applied when threshold or
        frequency range changes while a measurement is frozen/loaded.
        Viewport filtering (fmin/fmax) is applied by the results panel at display time.
        """
        import numpy as np

        assert self.loaded_measurement_peaks is not None
        threshold_db = self.peak_threshold
        peaks = self.loaded_measurement_peaks[
            self.loaded_measurement_peaks[:, 1] >= threshold_db
        ]

        empty = np.zeros((0, 3))
        if peaks.shape[0] == 0:
            self.current_peaks = empty
            self.peaksChanged.emit(empty)
            return

        self.current_peaks = peaks
        # Emit all threshold-passing peaks — viewport filtering applied by results panel.
        self.peaksChanged.emit(peaks)

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
                # find_peaks stores current_peaks and emits peaksChanged internally.
                avg_peaks = self.find_peaks(list(avg_mag_y_db), list(self.freq))
                triggered = len(avg_peaks) > 0
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))
                    self.frozen_magnitudes = avg_mag_y_db
                    self.spectrumUpdated.emit(self.freq, avg_mag_y_db)

        self.spectrumUpdated.emit(self.freq, self.frozen_magnitudes)
