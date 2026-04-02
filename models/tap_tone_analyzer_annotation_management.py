"""
TapToneAnalyzer+AnnotationManagement — peak selection tracking.

Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift.

Note: In the Python implementation annotation offset dragging and visibility
cycling are delegated to fft_annotations.FftAnnotations (owned by FftCanvas).
This mixin covers the peak selection state that the analyzer owns.
"""

from __future__ import annotations


class TapToneAnalyzerAnnotationManagementMixin:
    """Peak selection helpers for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift.
    """

    def select_peak(self, freq: float) -> None:
        """Record the selected peak frequency."""
        self.selected_peak = freq

    def deselect_peak(self, _freq: float) -> None:
        """Clear the selected peak."""
        pass  # selection display handled by FftCanvas

    def clear_selected_peak(self) -> None:
        """Reset the selected peak."""
        self.selected_peak = -1.0
