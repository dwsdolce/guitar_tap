"""
TapToneAnalyzer+AnnotationManagement — peak selection and annotation offset tracking.

Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift.

Annotation offsets are stored on the analyzer keyed by peak UUID string so that
dragged positions survive pan/zoom annotation rebuilds.  This mirrors Swift's
``peakAnnotationOffsets: [UUID: CGPoint]`` @Published property.

Key change from earlier revision: the dictionary is keyed by ``ResonantPeak.id``
(a UUID string), not by frequency.  Mirrors Swift [UUID: CGPoint].
"""

from __future__ import annotations


class TapToneAnalyzerAnnotationManagementMixin:
    """Peak selection and annotation offset helpers for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift.

    Stored properties initialised in TapToneAnalyzer.__init__:
        self.peak_annotation_offsets: dict[str, tuple[float, float]]
            UUID-string → (x, y) in data-space coordinates.
        self.user_selected_longitudinal_peak_id: str | None
        self.user_selected_cross_peak_id: str | None
        self.user_selected_flc_peak_id: str | None
        self.selected_longitudinal_peak: ResonantPeak | None
        self.selected_cross_peak: ResonantPeak | None
        self.selected_flc_peak: ResonantPeak | None
        self.auto_selected_longitudinal_peak_id: str | None
        self.auto_selected_cross_peak_id: str | None
        self.auto_selected_flc_peak_id: str | None
    """

    # ------------------------------------------------------------------ #
    # Annotation Offset Management
    # Mirrors Swift TapToneAnalyzer+AnnotationManagement.swift
    # ------------------------------------------------------------------ #

    def update_annotation_offset(
        self, peak_id: str, offset: tuple[float, float]
    ) -> None:
        """Store the dragged label position for the peak identified by *peak_id*.

        Mirrors Swift ``updateAnnotationOffset(for peakID: UUID, offset: CGPoint)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string) — the dictionary key.
            offset:  (x, y) position in data-space: x = Hz, y = dB.
                     (0.0, 0.0) represents «no saved position»; the default
                     anchor (70 pt above the peak) is used at render time.
        """
        self.peak_annotation_offsets[peak_id] = offset

    def get_annotation_offset(self, peak_id: str) -> tuple[float, float]:
        """Return the stored label position for *peak_id*, or (0.0, 0.0) if none.

        Mirrors Swift ``getAnnotationOffset(for peakID: UUID) -> CGPoint``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).

        Returns:
            (x, y) data-space offset, or (0.0, 0.0) when the label has
            never been dragged or its offset was cleared.
        """
        return self.peak_annotation_offsets.get(peak_id, (0.0, 0.0))

    def reset_annotation_offset(self, peak_id: str) -> None:
        """Remove the stored offset for a single peak, returning it to its default position.

        Mirrors Swift ``resetAnnotationOffset(for peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        self.peak_annotation_offsets.pop(peak_id, None)

    def reset_all_annotation_offsets(self) -> None:
        """Clear all stored annotation offsets, resetting every callout to its default anchor.

        Mirrors Swift ``resetAllAnnotationOffsets()``.
        Called when the analyzer resets (new tap sequence, measurement cleared).
        Mirrors Swift ``peakAnnotationOffsets = [:]`` in ``startTapSequence()``.
        """
        self.peak_annotation_offsets.clear()

    def apply_annotation_offsets(
        self, offsets: dict[str, tuple[float, float]]
    ) -> None:
        """Replace the entire annotation-offset dictionary with *offsets*.

        Called when loading a saved ``TapToneMeasurement`` to restore the
        user's previously arranged callout positions.

        Mirrors Swift ``applyAnnotationOffsets(_ offsets: [UUID: CGPoint])``.

        Args:
            offsets: Mapping of UUID strings to (x, y) data-space positions.
        """
        self.peak_annotation_offsets = dict(offsets)

    # ------------------------------------------------------------------ #
    # Plate Peak Selection
    # Mirrors Swift selectLongitudinalPeak / selectCrossPeak / selectFlcPeak
    # ------------------------------------------------------------------ #

    @property
    def effective_longitudinal_peak_id(self) -> str | None:
        """The effective longitudinal peak UUID applying three-layer priority.

        Priority: userSelectedLongitudinalPeakID > selectedLongitudinalPeak.id
        > autoSelectedLongitudinalPeakID.

        Mirrors Swift ``effectiveLongitudinalPeakID``:
            userSelectedLongitudinalPeakID ?? selectedLongitudinalPeak?.id ?? autoSelectedLongitudinalPeakID
        """
        return (
            self.user_selected_longitudinal_peak_id
            or (self.selected_longitudinal_peak.id if self.selected_longitudinal_peak else None)
            or self.auto_selected_longitudinal_peak_id
        )

    @property
    def effective_cross_peak_id(self) -> str | None:
        """The effective cross-grain peak UUID applying three-layer priority.

        Priority: userSelectedCrossPeakID > selectedCrossPeak.id
        > autoSelectedCrossPeakID.

        Mirrors Swift ``effectiveCrossPeakID``:
            userSelectedCrossPeakID ?? selectedCrossPeak?.id ?? autoSelectedCrossPeakID
        """
        return (
            self.user_selected_cross_peak_id
            or (self.selected_cross_peak.id if self.selected_cross_peak else None)
            or self.auto_selected_cross_peak_id
        )

    @property
    def effective_flc_peak_id(self) -> str | None:
        """The effective FLC peak UUID applying three-layer priority.

        Priority: userSelectedFlcPeakID > selectedFlcPeak.id
        > autoSelectedFlcPeakID.

        Mirrors Swift ``effectiveFlcPeakID``:
            userSelectedFlcPeakID ?? selectedFlcPeak?.id ?? autoSelectedFlcPeakID
        """
        return (
            self.user_selected_flc_peak_id
            or (self.selected_flc_peak.id if self.selected_flc_peak else None)
            or self.auto_selected_flc_peak_id
        )

    def select_longitudinal_peak(self, peak_id: str) -> None:
        """Toggle *peak_id* as the user-selected longitudinal peak.

        Tapping an already-selected longitudinal peak deselects it. Selecting a
        new peak clears any conflicting cross or FLC user-selection for the same
        peak ID, enforcing mutual exclusion across tap-type assignments.

        Mirrors Swift ``selectLongitudinalPeak(_ peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        if self.effective_longitudinal_peak_id == peak_id:
            self.user_selected_longitudinal_peak_id = None
            self.selected_longitudinal_peak = None
        else:
            self.user_selected_longitudinal_peak_id = peak_id
            if self.effective_cross_peak_id == peak_id:
                self.user_selected_cross_peak_id = None
                self.selected_cross_peak = None
            if self.effective_flc_peak_id == peak_id:
                self.user_selected_flc_peak_id = None
                self.selected_flc_peak = None

    def select_cross_peak(self, peak_id: str) -> None:
        """Toggle *peak_id* as the user-selected cross-grain peak.

        Mirrors the mutual-exclusion logic of ``select_longitudinal_peak``.

        Mirrors Swift ``selectCrossPeak(_ peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        if self.effective_cross_peak_id == peak_id:
            self.user_selected_cross_peak_id = None
            self.selected_cross_peak = None
        else:
            self.user_selected_cross_peak_id = peak_id
            if self.effective_longitudinal_peak_id == peak_id:
                self.user_selected_longitudinal_peak_id = None
                self.selected_longitudinal_peak = None
            if self.effective_flc_peak_id == peak_id:
                self.user_selected_flc_peak_id = None
                self.selected_flc_peak = None

    def select_flc_peak(self, peak_id: str) -> None:
        """Toggle *peak_id* as the user-selected FLC peak.

        Mirrors the mutual-exclusion logic of ``select_longitudinal_peak``.

        Mirrors Swift ``selectFlcPeak(_ peakID: UUID)``.

        Args:
            peak_id: ``ResonantPeak.id`` (UUID string).
        """
        if self.effective_flc_peak_id == peak_id:
            self.user_selected_flc_peak_id = None
            self.selected_flc_peak = None
        else:
            self.user_selected_flc_peak_id = peak_id
            if self.effective_longitudinal_peak_id == peak_id:
                self.user_selected_longitudinal_peak_id = None
                self.selected_longitudinal_peak = None
            if self.effective_cross_peak_id == peak_id:
                self.user_selected_cross_peak_id = None
                self.selected_cross_peak = None
