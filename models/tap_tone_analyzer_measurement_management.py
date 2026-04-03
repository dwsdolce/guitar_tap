"""
TapToneAnalyzer+MeasurementManagement — freeze/unfreeze spectrum,
comparison overlay loading, and measurement-complete state.

Mirrors Swift TapToneAnalyzer+MeasurementManagement.swift.
"""

from __future__ import annotations

from .analysis_display_mode import AnalysisDisplayMode


class TapToneAnalyzerMeasurementManagementMixin:
    """Measurement state and comparison overlay management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+MeasurementManagement.swift.
    """

    def set_measurement_complete(self, is_complete: bool) -> None:
        """Freeze/unfreeze the spectrum and reset related state."""
        self.is_measurement_complete = is_complete
        if self._proc_thread is not None:
            self._proc_thread.set_measurement_complete(is_complete)
        if not is_complete:
            self._tap_spectra.clear()
            self._loaded_measurement_peaks = None
            # Restore freq to native FFT bins — a loaded measurement may have overwritten
            # self.freq with its saved frequency array (different length from the live FFT).
            import numpy as np
            x_axis = np.arange(0, self.fft_data.h_n_f + 1)
            self.freq = x_axis * self.fft_data.sample_freq // self.fft_data.n_f
            # Clear comparison overlay — uses clear_comparison() so comparisonChanged(False)
            # is emitted when needed, allowing the UI to hide the comparison status bar.
            self.clear_comparison()
        self.measurementComplete.emit(is_complete)

    def _clear_comparison_state(self) -> None:
        """Clear the analyzer's comparison data (view curves cleared by FftCanvas)."""
        self._display_mode = AnalysisDisplayMode.LIVE
        self.comparison_labels.clear()
        self._comparison_data.clear()

    def load_comparison(self, measurements: list) -> list:
        """Prepare comparison data from measurements.

        Returns list of (label, color, freq_arr, mag_arr) tuples for FftCanvas
        to create PlotDataItem curves.  Mirrors loadComparison(measurements:) in Swift.
        """
        from datetime import datetime
        import numpy as np

        self._comparison_data.clear()
        self.comparison_labels.clear()

        _PALETTE = [
            (0,   122, 255),
            (255, 149,   0),
            (52,  199,  89),
            (175,  82, 222),
            (48,  176, 199),
        ]

        with_snapshots = [m for m in measurements if m.spectrum_snapshot is not None]
        result = []
        for idx, m in enumerate(with_snapshots):
            snap = m.spectrum_snapshot
            color = _PALETTE[idx % len(_PALETTE)]
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes,  dtype=np.float64)
            label = self._comparison_label(m)
            self.comparison_labels.append((label, color))
            self._comparison_data.append({
                "label": label, "color": color,
                "freqs": freq_arr, "mags": mag_arr,
            })
            result.append((label, color, freq_arr, mag_arr))

        if with_snapshots:
            snaps = [m.spectrum_snapshot for m in with_snapshots]
            min_freq = int(min(s.min_freq for s in snaps))
            max_freq = int(max(s.max_freq for s in snaps))
            self.update_axis(min_freq, max_freq)
            self._display_mode = AnalysisDisplayMode.COMPARISON
            self.comparisonChanged.emit(True)

        return result

    def clear_comparison(self) -> None:
        """Clear comparison overlay state."""
        was_comparing = self.is_comparing
        self._display_mode = AnalysisDisplayMode.LIVE
        self._comparison_data.clear()
        self.comparison_labels.clear()
        if was_comparing:
            self.comparisonChanged.emit(False)

    @staticmethod
    def _comparison_label(m) -> str:
        """Short label for the comparison legend."""
        from datetime import datetime
        loc = getattr(m, "tap_location", None)
        if loc:
            return loc
        ts = getattr(m, "timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%b %-d %H:%M")
        except Exception:
            return ts[:16]
