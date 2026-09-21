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
        """The longitudinal (fL) peak's UUID, or None before the phase finalises.

        The identified peak for the phase, or None before it finalises.

        Two earlier layers are gone (2026-09-20): a user-override tier whose UI was removed in
        April 2026, and ``auto_selected_*_peak_id``, which was UNREACHABLE — both are assigned
        adjacently in the phase handlers and the selected one is never None when the auto id is
        set. The auto attributes THEMSELVES stay: they are the change channel the view rides to
        widen the chart axis onto a newly identified peak.

        Mirrors Swift ``effectiveLongitudinalPeakID``.
        """
        return self.selected_longitudinal_peak.id if self.selected_longitudinal_peak else None

    @property
    def effective_cross_peak_id(self) -> str | None:
        """The cross-grain (fC) peak's UUID, or None before the phase finalises.

        Nothing to resolve — see ``effective_longitudinal_peak_id`` for why the two earlier
        layers went. Mirrors Swift ``effectiveCrossPeakID``.
        """
        return self.selected_cross_peak.id if self.selected_cross_peak else None

    @property
    def effective_flc_peak_id(self) -> str | None:
        """The FLC (torsional/twist) peak's UUID, or None before the phase finalises.

        Nothing to resolve — see ``effective_longitudinal_peak_id`` for why the two earlier
        layers went. Mirrors Swift ``effectiveFlcPeakID``.
        """
        return self.selected_flc_peak.id if self.selected_flc_peak else None

    # Plate Peak Selection — REMOVED 2026-09-20
    #
    # ``select_longitudinal_peak`` / ``select_cross_peak`` / ``select_flc_peak`` let the user
    # re-assign which detected peak was the fL / fC / fFLC, from L / C / FLC buttons on each peak
    # row in the material Results panel. Those buttons were removed from Swift on 2026-04-17
    # (``c88e5e1``) and the correction path became: REDO the phase (plate) or the measurement
    # (brace). Python mirrored the leftovers rather than the feature, so this model layer sat here
    # unreachable, exercised only by its own PS1-PS6 tests, which went with it.
    #
    # Do not reintroduce without the UI. This was also the only reason material peaks had to live
    # in the shared ``all_peaks`` list — see the parity doc for that thread.
