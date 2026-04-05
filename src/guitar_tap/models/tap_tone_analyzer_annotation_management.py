"""
TapToneAnalyzer+AnnotationManagement — peak selection and annotation offset tracking.

Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift.

Annotation offsets are stored on the analyzer (keyed by peak frequency) so that
dragged positions survive pan/zoom annotation rebuilds.  This mirrors Swift's
``peakAnnotationOffsets: [UUID: CGPoint]`` @Published property.
"""

from __future__ import annotations


class TapToneAnalyzerAnnotationManagementMixin:
    """Peak selection and annotation offset helpers for TapToneAnalyzer.

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

    # ── Annotation offset persistence ─────────────────────────────────────────
    # Mirrors Swift updateAnnotationOffset(for:offset:) and the clearing done
    # in startTapSequence / loadMeasurement / set_measurement_complete.

    def update_annotation_offset(
        self, freq: float, x: float, y: float
    ) -> None:
        """Store the dragged position for the annotation at *freq*.

        Mirrors Swift ``TapToneAnalyzer.updateAnnotationOffset(for:offset:)``.

        Args:
            freq: Peak frequency (Hz) — used as the key.
            x:    Label x-position in data-space coordinates.
            y:    Label y-position in data-space coordinates.
        """
        self.peak_annotation_offsets[freq] = (x, y)

    def clear_annotation_offsets(self) -> None:
        """Remove all saved annotation offsets.

        Called when the analyzer resets (new tap sequence, measurement cleared)
        so annotations start fresh at their default positions.
        Mirrors Swift ``peakAnnotationOffsets = [:]`` in ``startTapSequence()``.
        """
        self.peak_annotation_offsets.clear()
