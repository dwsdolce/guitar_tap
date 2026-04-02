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

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold/fmin/fmax and emit peaksChanged.

        Mirrors Swift recalculateFrozenPeaksIfNeeded — applied when threshold or
        frequency range changes while a measurement is frozen/loaded.
        """
        import numpy as np

        assert self._loaded_measurement_peaks is not None
        threshold_db = self.threshold - 100
        peaks = self._loaded_measurement_peaks[
            self._loaded_measurement_peaks[:, 1] >= threshold_db
        ]

        empty = np.zeros((0, 3))
        if peaks.shape[0] == 0:
            self.saved_peaks = empty
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)
            return

        self.saved_peaks = peaks
        peaks_freq = peaks[:, 0]

        b_indices = np.nonzero((peaks_freq < self.fmax) & (peaks_freq > self.fmin))
        if len(b_indices[0]) > 0:
            self.peaks_f_min_index = int(b_indices[0][0])
            self.peaks_f_max_index = int(b_indices[0][-1]) + 1
            self.b_peaks_freq = peaks_freq[self.peaks_f_min_index:self.peaks_f_max_index]
            self.peaksChanged.emit(peaks[self.peaks_f_min_index:self.peaks_f_max_index])
        else:
            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)

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
            if avg_amplitude > self.threshold:
                triggered, avg_peaks = self.find_peaks(avg_mag_y_db)
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))
                    self.saved_mag_y_db = avg_mag_y_db
                    self.saved_peaks = avg_peaks
                    self.spectrumUpdated.emit(self.freq, avg_mag_y_db)

        self.spectrumUpdated.emit(self.freq, self.saved_mag_y_db)
