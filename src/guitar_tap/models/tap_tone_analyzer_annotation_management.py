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
    # Identified material peaks and capture provenance
    # ------------------------------------------------------------------ #

    @property
    def effective_longitudinal_peak_id(self) -> str | None:
        """The longitudinal (fL) peak's UUID, or None before the phase finalises: the phase's identified
        peak. Mirrors Swift ``effectiveLongitudinalPeakID``."""
        return self.selected_longitudinal_peak.id if self.selected_longitudinal_peak else None

    @property
    def effective_cross_peak_id(self) -> str | None:
        """The cross-grain (fC) peak's UUID, or None before the phase finalises. Mirrors Swift
        ``effectiveCrossPeakID``."""
        return self.selected_cross_peak.id if self.selected_cross_peak else None

    @property
    def effective_flc_peak_id(self) -> str | None:
        """The FLC (torsional/twist) peak's UUID, or None before the phase finalises. Mirrors Swift
        ``effectiveFlcPeakID``."""
        return self.selected_flc_peak.id if self.selected_flc_peak else None

    @property
    def has_result_to_save_or_export(self) -> bool:
        """There is something to save or export: a complete measurement (captured, loaded, multi-tap, or a
        finished plate/brace) or a comparison. Save, Export Spectrum and Export PDF — the buttons and the
        menu items — are enabled only then. Mirrors Swift ``hasResultToSaveOrExport``."""
        from .analysis_display_mode import AnalysisDisplayMode
        return self.is_measurement_complete or self.display_mode == AnalysisDisplayMode.COMPARISON

    # ``result_provenance`` (set in ``__init__``) — where the current result came from when it is not the
    # live input: a played file or a loaded measurement; None while listening to the input. Set by
    # ``play_file`` and ``load_measurement``; a new sequence clears it. Mirrors Swift ``resultProvenance``.

    @property
    def capture_microphone_name(self) -> "str | None":
        """The microphone the current result was captured with, as shown, saved and reported: the input
        device for a live result; the recorded one for a played file or a loaded measurement, None
        (unknown) when there is none. Mirrors Swift ``captureMicrophoneName``."""
        if self.result_provenance is not None:
            return self.result_provenance.microphone_name
        device = getattr(self.mic, "selected_input_device", None) if self.mic is not None else None
        return getattr(device, "name", None) or None

    @property
    def capture_microphone_uid(self) -> "str | None":
        """The UID of ``capture_microphone_name``'s device. Mirrors Swift ``captureMicrophoneUID``."""
        if self.result_provenance is not None:
            return self.result_provenance.microphone_uid
        device = getattr(self.mic, "selected_input_device", None) if self.mic is not None else None
        return getattr(device, "fingerprint", None) or None

    @property
    def capture_calibration_name(self) -> "str | None":
        """The calibration the current result was captured with: the input's for a live result, the
        recorded one otherwise (none for a file played uncalibrated). Mirrors Swift
        ``captureCalibrationName``."""
        if self.result_provenance is not None:
            return self.result_provenance.calibration_name
        return self._active_calibration_name or None

    @property
    def capture_sample_rate(self) -> "float | None":
        """The sample rate the current result was captured at: the input's for a live result (None when
        the engine has no rate yet), the recorded one otherwise. Mirrors Swift ``captureSampleRate``."""
        if self.result_provenance is not None:
            return self.result_provenance.sample_rate
        rate = getattr(self.mic, "rate", None) if self.mic is not None else None
        return float(rate) if rate else None
