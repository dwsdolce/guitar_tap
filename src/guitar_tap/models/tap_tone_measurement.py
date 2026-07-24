"""
Complete measurement record — mirrors Swift TapToneMeasurement.swift.

The complete, serialisable record of a single tap-tone analysis session.

A measurement captures everything needed to reproduce the original analysis view:
- The detected ResonantPeak array and the SpectrumSnapshot (or per-phase snapshots
  for plate/brace) that back the spectrum chart.
- Display ranges and analysis settings so the chart re-opens at the correct zoom level.
- Annotation positions and peak selections so the user's layout is preserved exactly.
- Per-peak mode overrides for any labels the user customised.
- Microphone and calibration metadata for provenance.

Persistence Format:
  Measurements are serialised to JSON in the application's Documents directory.
  The JSON file is self-contained: all spectrum data needed to recreate the chart is
  embedded in the spectrumSnapshot (guitar) or per-phase snapshots (plate/brace).
  The format is cross-compatible with the Swift GuitarTap application.

Measurement Types:
  | Type    | Fields populated                                                  |
  |---------|-------------------------------------------------------------------|
  | Guitar  | spectrum_snapshot, peaks, decay_time                              |
  | Plate   | longitudinal_snapshot, cross_snapshot, optional flc_snapshot;     |
  |         | selected_longitudinal_peak_id, selected_cross_peak_id,            |
  |         | optional selected_flc_peak_id                                     |
  | Brace   | longitudinal_snapshot, selected_longitudinal_peak_id              |
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from guitar_tap.utilities.json_float import f32, f32_list
from .resonant_peak import ResonantPeak
from .spectrum_snapshot import SpectrumSnapshot


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TapEntry:
    """One individual tap's spectrum and detected peaks within a multi-tap guitar sequence.

    Stores everything needed to display one tap's overlay on the comparison chart
    and to populate its row in the multi-tap comparison results table.

    Mirrors Swift TapEntry struct (TapToneMeasurement.swift).

    JSON key mapping (camelCase, matching Swift CodingKeys):
      id, tapIndex, snapshot, peaks, selectedPeakIDs
    """

    # Stable unique identifier for this tap entry.
    # Mirrors Swift TapEntry.id (UUID).
    id: str

    # 1-based display index ("Tap 1", "Tap 2", …).
    # Mirrors Swift TapEntry.tapIndex.
    tap_index: int

    # Full spectrum snapshot for this individual tap.
    # Mirrors Swift TapEntry.snapshot (SpectrumSnapshot).
    snapshot: SpectrumSnapshot

    # All peaks detected on this tap's spectrum.
    # Mirrors Swift TapEntry.peaks ([ResonantPeak]).
    peaks: list[ResonantPeak]

    # UUIDs of the auto-selected peaks for guitar mode (Air/Top/Back/…).
    # Mirrors Swift TapEntry.selectedPeakIDs ([UUID]).
    selected_peak_ids: list[str]

    def to_dict(self) -> dict:
        """Encode as a JSON-compatible dict using Swift camelCase field names.

        Mirrors Swift TapEntry's synthesized Codable encode(to:).
        Python-only — Swift uses synthesized Codable.
        """
        return {
            "id": self.id,
            "tapIndex": self.tap_index,
            "snapshot": self.snapshot.to_dict(),
            # Swift encodes TapEntry.peaks with plain ResonantPeak Codable — no modeLabel.
            "peaks": [p.to_dict(include_mode_label=False) for p in self.peaks],
            "selectedPeakIDs": self.selected_peak_ids,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TapEntry":
        """Decode a Swift-format TapEntry JSON object.

        Python-only — Swift uses synthesized Codable.
        """
        snap_d = d.get("snapshot", {})
        snapshot = SpectrumSnapshot.from_dict(snap_d)
        peaks = [ResonantPeak.from_dict(p) for p in d.get("peaks", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            tap_index=d.get("tapIndex", 1),
            snapshot=snapshot,
            peaks=peaks,
            selected_peak_ids=d.get("selectedPeakIDs", []),
        )

    def resolved_mode_peaks(self, guitar_type=None):
        """Filter selected peaks and resolve guitar modes — returns {GuitarMode: ResonantPeak}.

        Bundles the selectedPeakIDs filtering + classification into a single call.
        Mirrors Swift TapEntry.resolvedModePeaks().
        """
        from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin

        selected_ids = set(self.selected_peak_ids)
        selected = [p for p in self.peaks if p.id in selected_ids]
        # A tap's own auto-classification — no overrides (per-tap rows are unrelated to the
        # averaged override). guitar_type keyworded now that `overrides` is the 2nd positional.
        return TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            selected, guitar_type=guitar_type or self.snapshot.guitar_type
        )


@dataclass
class ComparisonEntry:
    """A single spectrum entry within a saved comparison measurement.

    Stores everything needed to restore one overlay in a comparison chart:
    the full spectrum snapshot, selected peaks, guitar type, display label,
    and chart color (as RGBA components, since Color is not serialisable).

    Mirrors Swift ComparisonEntry struct (TapToneMeasurement.swift).

    JSON key mapping (camelCase, matching Swift CodingKeys):
      id, label, colorComponents, snapshot, peaks, guitarType, sourceMeasurementID
    """

    # Stable unique identifier for this entry.
    # Mirrors Swift ComparisonEntry.id (UUID).
    id: str

    # Display label for this spectrum (e.g. "Bridge", "Bridge (2)").
    # Mirrors Swift ComparisonEntry.label.
    label: str

    # Chart color stored as [red, green, blue, alpha], each 0.0–1.0.
    # Color is not serialisable; the fixed comparison palette makes this round-trip exact.
    # Mirrors Swift ComparisonEntry.colorComponents ([Double]).
    color_components: list[float]

    # Full spectrum snapshot providing magnitudes, frequencies, and axis ranges.
    # Mirrors Swift ComparisonEntry.snapshot (SpectrumSnapshot).
    snapshot: SpectrumSnapshot

    # Selected peaks for this measurement at save time.
    # Mirrors Swift ComparisonEntry.peaks ([ResonantPeak]).
    peaks: list[ResonantPeak]

    # Guitar type active when the source measurement was recorded, used for mode classification.
    # Stored as raw string in Python; Swift uses GuitarType enum.
    # Mirrors Swift ComparisonEntry.guitarType (GuitarType?).
    guitar_type: str | None = None

    # UUID of the source TapToneMeasurement this entry was created from, if available.
    # Mirrors Swift ComparisonEntry.sourceMeasurementID (UUID?).
    source_measurement_id: str | None = None

    # The DEFINITIVE Air/Top/Back for this overlaid spectrum, resolved once from the source
    # measurement's own selection AND overrides, and stored as {canonical mode name: peak UUID}
    # (the UUID references one of this entry's own `peaks`). Makes a saved comparison
    # self-describing: a reader reproduces the displayed table by looking each ID up in `peaks` —
    # no need to re-run classify_all, and no need for the source's override data (absent from this
    # file). `None` on files written before Phase 6b; those are healed on decode and re-saved.
    # Mirrors Swift ComparisonEntry.modePeakIDs ([String: UUID]?). (Phase 6b)
    mode_peak_ids: dict[str, str] | None = None

    @staticmethod
    def mode_id_map(resolved: dict) -> dict[str, str]:
        """Build the {mode name: peak id} map for the three ratio-bearing modes from a resolved
        mode→peak dictionary. Keyed by GuitarMode raw value so Swift/web read it directly.

        Mirrors Swift ComparisonEntry.modeIDMap(from:).
        """
        from . import guitar_mode as gm

        out: dict[str, str] = {}
        for mode in (gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK):
            p = resolved.get(mode)
            if p is not None:
                out[mode.value] = p.id
        return out

    def mode_frequency(self, mode) -> float | None:
        """The frequency of this entry's definitive peak for *mode*, from ``mode_peak_ids`` when
        present (self-describing), else re-derived positionally from ``peaks`` (legacy / in-memory
        fallback).

        Mirrors Swift ComparisonEntry.modeFrequency(_:).
        """
        from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin

        if self.mode_peak_ids is not None:
            pid = self.mode_peak_ids.get(mode.value)
            if pid is not None:
                for p in self.peaks:
                    if p.id == pid:
                        return p.frequency
        resolved = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            self.peaks, guitar_type=self.guitar_type
        )
        p = resolved.get(mode)
        return p.frequency if p is not None else None

    def to_dict(self) -> dict[str, Any]:
        """Encode as a JSON-compatible dict using Swift camelCase field names.

        Mirrors Swift ComparisonEntry's synthesized Codable encode(to:).
        Python-only — Swift uses synthesized Codable.
        """
        d: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "colorComponents": self.color_components,
            "snapshot": self.snapshot.to_dict(),
            # Swift encodes ComparisonEntry.peaks with plain ResonantPeak Codable — no modeLabel.
            "peaks": [p.to_dict(include_mode_label=False) for p in self.peaks],
        }
        if self.guitar_type is not None:
            d["guitarType"] = self.guitar_type
        if self.source_measurement_id is not None:
            d["sourceMeasurementID"] = self.source_measurement_id
        if self.mode_peak_ids is not None:
            d["modePeakIDs"] = self.mode_peak_ids
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ComparisonEntry":
        """Decode a Swift-format ComparisonEntry JSON object.

        Python-only — Swift uses synthesized Codable.
        """
        snap_d = d.get("snapshot", {})
        snapshot = SpectrumSnapshot.from_dict(snap_d)
        peaks = [ResonantPeak.from_dict(p) for p in d.get("peaks", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            label=d.get("label", ""),
            color_components=d.get("colorComponents", [0.0, 0.0, 1.0, 1.0]),
            snapshot=snapshot,
            peaks=peaks,
            guitar_type=d.get("guitarType"),
            source_measurement_id=d.get("sourceMeasurementID"),
            mode_peak_ids=d.get("modePeakIDs"),
        )


@dataclass
class TapToneMeasurement:
    """A complete record of a tap-tone measurement session, including spectrum data, peaks,
    display state, and all analysis settings active at the time of capture.

    Mirrors Swift TapToneMeasurement struct (TapToneMeasurement.swift).
    JSON is cross-compatible with the iOS/macOS Swift GuitarTap app.

    NOTE — Python vs Swift structural differences:
      - ``id`` and ``timestamp`` are stored as strings in Python; Swift uses UUID and Date.
      - ``annotation_offsets`` is stored as ``{uuid: [absFreqHz, absDB]}`` in Python;
        Swift uses ``[UUID: CGPoint]`` (x=absFreqHz, y=absDB, decoded from named absFreqHz/absDB fields).
      - ``peak_mode_overrides`` is stored as ``{uuid: str}`` in Python;
        Swift uses ``[UUID: UserAssignedMode]``.
      - ``annotation_visibility_mode`` is stored as a raw string in Python;
        Swift uses ``AnnotationVisibilityMode`` enum.
      - ``to_dict()`` / ``from_dict()`` provide JSON serialisation; Swift uses Codable.
      - ``create()`` is the Python factory equivalent of Swift's ``init(...)`` with defaults.
      - ``display_name()`` is Python-only (no Swift equivalent).
    """

    # MARK: - Identity & Timestamps

    # Stable unique identifier for this measurement.
    # Stored as a UUID string in Python; Swift uses UUID.
    # Mirrors Swift TapToneMeasurement.id.
    id: str

    # Wall-clock time at which the measurement was saved, as an ISO-8601 string.
    # Swift stores this as Date; Python stores it as an ISO-8601 string.
    # Mirrors Swift TapToneMeasurement.timestamp.
    timestamp: str

    # MARK: - Analysis Results

    # All resonant peaks detected during this measurement session.
    # For guitar measurements these are the peaks from the averaged multi-tap spectrum.
    # For plate/brace measurements this array combines peaks from all captured phases.
    # Mirrors Swift TapToneMeasurement.peaks.
    peaks: list[ResonantPeak]

    # Time for the tap transient to decay to the configured threshold, in seconds.
    # None for plate/brace measurements (decay is not meaningful for material analysis)
    # or if decay tracking was not active.
    # Mirrors Swift TapToneMeasurement.decayTime.
    decay_time: float | None = None

    # MARK: - User Metadata

    # Descriptive name for the measurement, e.g. "Contreras", "Gore", "Ramirez".
    # Mirrors Swift TapToneMeasurement.measurementName.
    measurement_name: str | None = None

    # Free-form notes entered by the user at save time.
    # Mirrors Swift TapToneMeasurement.notes.
    notes: str | None = None

    # MARK: - Guitar Spectrum

    # The averaged frequency spectrum for guitar-mode measurements.
    # Contains the full chart display settings needed to restore the spectrum plot.
    # None for plate/brace measurements, which use the per-phase snapshots instead.
    # Mirrors Swift TapToneMeasurement.spectrumSnapshot.
    spectrum_snapshot: SpectrumSnapshot | None = None

    # MARK: - Annotation State

    # Absolute data-space positions for draggable peak annotation labels, keyed by peak UUID string.
    # Each value is [absFreqHz, absDB] — the label-center position in data-space coordinates.
    # Equivalent to Swift's CGPoint(x: absFreqHz, y: absDB) stored in peakAnnotationOffsets.
    # Allows the user's manual label layout to survive a save/load cycle.
    # Mirrors Swift TapToneMeasurement.peakAnnotationOffsets ([UUID: CGPoint]).
    annotation_offsets: dict[str, list[float]] | None = None

    # UUIDs of peaks the user marked as significant results (deselected peaks are dimmed).
    # None means all peaks are considered selected (backward-compatible default).
    # Mirrors Swift TapToneMeasurement.selectedPeakIDs.
    selected_peak_ids: list[str] | None = None

    # Frequencies (Hz) of the selected peaks, parallel to selected_peak_ids.
    # Used to re-match selections after findPeaks() re-runs with a new threshold
    # (which generates new UUIDs). Frequencies are stable across re-analysis; UUIDs are not.
    # Mirrors Swift TapToneMeasurement.selectedPeakFrequencies.
    selected_peak_frequencies: list[float] | None = None

    # Whether the saved peak selection was hand-modified (vs the automatic mode-priority selection).
    # Restored on load so a loaded measurement behaves like a live one: an AUTOMATIC selection
    # re-runs auto-selection when Peak Min changes; a MANUAL one is carried forward. None in files
    # saved before this field — those default to True (manual), preserving prior behaviour.
    # Never touches peak_mode_overrides (user-assigned mode labels). Mirrors Swift userModifiedSelection.
    user_modified_selection: bool | None = None

    # The annotation visibility mode (show all / show selected / hide all) that was active
    # when the measurement was saved. Stored as a raw string in Python;
    # Swift uses AnnotationVisibilityMode enum.
    # Mirrors Swift TapToneMeasurement.annotationVisibilityMode.
    annotation_visibility_mode: str | None = None

    # MARK: - Analysis Settings

    # The tap-detection threshold (dB above noise floor) configured at save time.
    # Mirrors Swift TapToneMeasurement.tapDetectionThreshold.
    tap_detection_threshold: float | None = None

    # The number of taps that were averaged to produce the final spectrum.
    # Mirrors Swift TapToneMeasurement.numberOfTaps.
    number_of_taps: int | None = None

    # The minimum peak magnitude (dBFS) that the peak-finder accepted, at save time.
    # Mirrors Swift TapToneMeasurement.peakMinThreshold.
    peak_min_threshold: float | None = None

    # MARK: - Material Measurement Peak Selections

    # UUID of the peak selected as the longitudinal (along-grain) resonance in a plate/brace measurement.
    # Used to look up the correct peak in peaks when reloading material property calculations.
    # Mirrors Swift TapToneMeasurement.selectedLongitudinalPeakID.
    selected_longitudinal_peak_id: str | None = None

    # UUID of the peak selected as the cross-grain resonance in a plate measurement.
    # Mirrors Swift TapToneMeasurement.selectedCrossPeakID.
    selected_cross_peak_id: str | None = None

    # UUID of the peak selected as the FLC (diagonal / shear) resonance.
    # Only present when the optional third tap was performed and measure_flc was true.
    # Mirrors Swift TapToneMeasurement.selectedFlcPeakID.
    selected_flc_peak_id: str | None = None

    # MARK: - Per-Phase Spectra (Plate / Brace)

    # Averaged FFT spectrum from the longitudinal (along-grain) tap orientation.
    # Populated for plate and brace measurements.  None for guitar measurements.
    # Mirrors Swift TapToneMeasurement.longitudinalSnapshot.
    longitudinal_snapshot: SpectrumSnapshot | None = None

    # Averaged FFT spectrum from the cross-grain tap orientation.
    # Populated for plate measurements only.  None for guitar and brace measurements.
    # Mirrors Swift TapToneMeasurement.crossSnapshot.
    cross_snapshot: SpectrumSnapshot | None = None

    # Averaged FFT spectrum from the FLC (45°-diagonal) tap orientation.
    # Populated only when the optional third tap was performed.
    # Mirrors Swift TapToneMeasurement.flcSnapshot.
    flc_snapshot: SpectrumSnapshot | None = None

    # MARK: - Mode Overrides

    # Per-peak user mode label overrides, keyed by peak UUID string.
    # Stored as {uuid: label_string} in Python; Swift uses [UUID: UserAssignedMode].
    # None means all peaks use automatic classification on load (backward-compatible default).
    # Mirrors Swift TapToneMeasurement.peakModeOverrides.
    peak_mode_overrides: dict[str, str] | None = None

    # MARK: - Microphone Provenance

    # Human-readable name of the microphone (input device) used for this measurement.
    # Mirrors Swift TapToneMeasurement.microphoneName.
    microphone_name: str | None = None

    # Unique device identifier (UID) of the microphone, used to match a device on reload.
    # Mirrors Swift TapToneMeasurement.microphoneUID.
    microphone_uid: str | None = None

    # Name of the active calibration profile applied during this measurement, if any.
    # Mirrors Swift TapToneMeasurement.calibrationName.
    calibration_name: str | None = None

    # Effective capture sample rate (Hz) used for this measurement, for reload
    # provenance checks. None for older files saved before this field existed.
    # Mirrors Swift TapToneMeasurement.sampleRate.
    sample_rate: float | None = None

    # Convenience top-level fields written to JSON for external consumers.
    # Mirrors Swift TapToneMeasurement encode(to:) convenience fields.
    measurement_type: str | None = None
    guitar_type: str | None = None

    # MARK: - Comparison Record

    # When non-None, this measurement is a saved comparison record rather than a single tap.
    # Each entry holds the full spectrum data for one overlaid spectrum in the comparison.
    # Additive and backward-compatible: existing measurements decode with None and are unaffected.
    # Mirrors Swift TapToneMeasurement.comparisonEntries ([ComparisonEntry]?).
    comparison_entries: list[ComparisonEntry] | None = None

    # MARK: - Multi-Tap Entries

    # Individual tap spectra and peaks from a multi-tap guitar sequence.
    # None for single-tap, plate, brace, and older saved measurements.
    # Additive and backward-compatible: existing measurements decode with None and are unaffected.
    # Mirrors Swift TapToneMeasurement.tapEntries ([TapEntry]?).
    tap_entries: list[TapEntry] | None = None

    # True when from_dict() repaired duplicate peaks in this measurement.
    #
    # Transient and deliberately NOT serialised: it describes what happened during one
    # decode, not a property of the file. The saved-measurements store reads it to force a
    # save so the library repairs itself; a .guitartap opened from disk is healed in memory
    # and written in corrected form only if the user saves it.
    # Mirrors Swift TapToneMeasurement.wasHealed.
    was_healed: bool = False

    # MARK: - Computed Properties

    @property
    def is_comparison(self) -> bool:
        """True when this measurement is a saved comparison record.

        Mirrors Swift TapToneMeasurement.isComparison.
        """
        return self.comparison_entries is not None

    @property
    def resolved_measurement_type(self) -> str | None:
        """Measurement type resolved from the stored snapshots (mirrors ``to_dict``);
        None for legacy files that predate the top-level type.

        Mirrors Swift ``TapToneMeasurement.resolvedMeasurementType``.
        """
        snap = self.spectrum_snapshot or self.longitudinal_snapshot
        return (snap.measurement_type if snap else None) or self.measurement_type

    @property
    def is_material(self) -> bool:
        """True for a plate/brace (material) measurement, which has **no per-peak selection**
        — the identified L/C/FLC in ``peaks`` are the peaks.

        Falls back to material-only fields for legacy files whose snapshot type is unresolved.
        Mirrors Swift ``TapToneMeasurement.isMaterial``.
        """
        from .measurement_type import MeasurementType
        mt_str = self.resolved_measurement_type
        if mt_str is not None:
            try:
                return not MeasurementType(mt_str).is_guitar
            except ValueError:
                pass
        return (self.longitudinal_snapshot is not None
                or self.selected_longitudinal_peak_id is not None)

    # @parity model/material-selection tests=test/material-selection
    @property
    def effective_selected_peak_ids(self) -> set[str]:
        """Peak IDs to render, annotate, and export for this measurement.

        - Guitar: the saved selection (``selected_peak_ids``), or all ``peaks`` when none saved.
        - Material: **always all of ``peaks``.** Plate/brace have no per-peak selection, and the
          saved aggregate can be corrupted by an intermittent phase-transition write (an iPad-only
          Swift glitch), so it is ignored on read. Heals existing corrupt files at render time —
          the same rule Swift and the web apply.

        Mirrors Swift ``TapToneMeasurement.effectiveSelectedPeakIDs``.
        """
        if self.is_material:
            return {p.id for p in self.peaks}
        return set(self.selected_peak_ids or [p.id for p in self.peaks])

    @property
    def tap_tone_ratio(self) -> float | None:
        """The Top-to-Air frequency ratio, a key quality indicator for guitar tap-tone analysis.

        Computed as f_Top / f_Air where each frequency is taken from the first peak whose
        auto-classified mode normalises to ``.top`` or ``.air`` respectively.

        An ideal ratio is approximately **2.0**, meaning the main top-plate resonance sits
        one octave above the Helmholtz air resonance.  Ratios below ~1.7 or above ~2.4
        typically indicate the instrument is outside optimal tonal balance.

        Returns ``None`` when either an Air or a Top peak cannot be found in ``peaks``.

        Mirrors Swift TapToneMeasurement.tapToneRatio.

        NOTE — Algorithm difference from Swift:
          Python must pass guitar_type explicitly to GuitarMode.classify_all.
          Swift calls GuitarMode.classifyAll(peaks) with auto-resolved guitar type.
          Python falls back to the guitar_type stored on this measurement, or "Classical".
        """
        from . import guitar_mode as gm
        # Definitive Air/Top: the SELECTED peak whose OVERRIDE-AWARE (effective) mode is that mode.
        # Mirrors Swift tapToneRatio → definitivePeak(for:). Replaces the old selection-aware but
        # override-BLIND classify — renaming the Top peak must remove the ratio, as it does on every
        # display surface.
        air = self.definitive_peak(gm.GuitarMode.AIR)
        top = self.definitive_peak(gm.GuitarMode.TOP)
        if air is None or top is None or air.frequency <= 0:
            return None
        return top.frequency / air.frequency

    def definitive_peak(self, mode) -> "ResonantPeak | None":
        """The **definitive** peak for *mode*: the **selected** peak whose **override-aware**
        (effective) mode is *mode*.

        Selection uses ``effective_selected_peak_ids`` (guitar: the saved selection, or all peaks when
        none; material: all). By the Phase 5 invariant there is at most one definitive Air/Top/Back;
        ``max`` guards the legacy case. Mirrors Swift ``TapToneMeasurement.definitivePeak(for:)``.
        """
        from . import guitar_mode as gm
        from . import guitar_type as gt_module
        if not self.peaks:
            return None
        try:
            gt = gt_module.GuitarType(self.guitar_type or "Classical")
        except Exception:
            gt = gt_module.GuitarType.CLASSICAL
        selected = self.effective_selected_peak_ids
        overrides = self.peak_mode_overrides or {}
        auto_map = gm.GuitarMode.classify_all(self.peaks, gt)
        candidates = [
            p for p in self.peaks
            if p.id in selected
            and gm.GuitarMode.effective_mode(
                overrides.get(p.id), auto_map.get(p.id, gm.GuitarMode.UNKNOWN)
            ).normalized == mode.normalized
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.magnitude)

    def definitive_mode_info(self) -> dict:
        """The definitive Air/Top/Back for this measurement, each with a flag for whether it is the
        user's manual override — for the multi-tap Averaged row (on screen and in the PDF), where an
        overridden value must be marked so it is not read as the averaged spectrum's auto peak.

        Returns ``{GuitarMode: (frequency: float, is_override: bool)}``. Mirrors Swift
        ``TapToneMeasurement.definitiveModeInfo()``. Python stores only *assigned* overrides in
        ``peak_mode_overrides`` (id → label), so membership is the override test.
        """
        from . import guitar_mode as gm
        overrides = self.peak_mode_overrides or {}
        out: dict = {}
        for mode in (gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK):
            p = self.definitive_peak(mode)
            if p is None:
                continue
            out[mode] = (p.frequency, p.id in overrides)
        return out

    @property
    def base_filename(self) -> str:
        """Base filename (without extension) derived from the measurement name and Unix timestamp.

        Spaces and slashes in ``measurement_name`` are replaced with hyphens and the string is
        lowercased, producing a filesystem-safe component such as ``"ramirez-1975-1771351833"``.
        Falls back to ``"measurement"`` when ``measurement_name`` is ``None``.

        Mirrors Swift TapToneMeasurement.baseFilename.
        """
        return self.export_stem_for("measurement")

    def export_stem_for(self, unnamed: str) -> str:
        """The export filename stem with a per-artifact default word (``"measurement"`` /
        ``"report"`` / ``"spectrum"``).

        Thin **Python-only adapter** over the shared ``export_filename.export_stem`` — it exists
        solely because this model stores ``timestamp`` as an ISO-8601 string that must be parsed to
        integer seconds, whereas Swift's ``Date`` converts for free and its call sites invoke
        ``ExportFilename.stem`` directly. No divergent logic: the rule lives in ``export_stem``.
        See FILE-PATHS-AND-NAMES-SPEC §2b.
        """
        from .export_filename import export_stem
        try:
            ts = int(datetime.fromisoformat(self.timestamp).timestamp())
        except Exception:
            ts = 0
        return export_stem(self.measurement_name, ts, unnamed)

    # ── Name validation (FILE-PATHS-AND-NAMES-SPEC §3) ──────────────────────
    # @parity model/measurement-name tests=test/measurement-name

    @staticmethod
    def is_valid_name(name: str) -> bool:
        """Whether ``name`` is acceptable to save: non-empty after trimming whitespace.

        The Save action is disabled until this holds. Single source of truth so all three
        platforms — and their tests — agree; a view must bind its Save button to this, never
        re-implement it. Mirrors Swift ``TapToneMeasurement.isValidName``.
        """
        return bool(name.strip())

    @staticmethod
    def normalized_name(name: str) -> "str | None":
        """The name to store: trimmed, or ``None`` if blank. Blank is prevented at the UI by
        ``is_valid_name``, but the model stays tolerant so nameless files from older builds still
        read (the format keeps ``measurement_name`` optional). Mirrors Swift ``normalizedName``.
        """
        trimmed = name.strip()
        return trimmed or None

    def display_name(self) -> str:
        """Human-readable display name combining measurement name and formatted timestamp.

        Example: ``"Contreras — 2026-01-25 14:32"``

        Python-only — no Swift equivalent.
        """
        from utilities.date_format import format_display_datetime
        time_str = format_display_datetime(self.timestamp)
        if self.measurement_name:
            return f"{self.measurement_name} — {time_str}"
        return time_str

    def with_(self, measurement_name: str | None, notes: str | None) -> "TapToneMeasurement":
        """Return a copy of the measurement with only ``measurement_name`` and ``notes`` replaced.

        All other fields — including ``id`` and ``timestamp`` — are preserved exactly.

        Mirrors Swift TapToneMeasurement.with(measurementName:notes:).
        """
        import dataclasses
        return dataclasses.replace(self, measurement_name=measurement_name, notes=notes)

    # MARK: - Serialisation (Python-only)

    def _resolve_peak_mode_labels(
        self, resolved_mt: "str | None", resolved_gt: "str | None"
    ) -> "list[str]":
        """Resolved human-readable mode label for each top-level peak, in order.

        Mirrors Swift TapToneMeasurement.encode(to:)'s PeakExportCodingKeys loop:
        guitar peaks are classified by GuitarMode (with any user override applied);
        plate/brace peaks get their role name (Longitudinal / Cross-grain / FLC / Peak).
        Called only from to_dict() so persistence, single export, and Export All all
        share this one resolution path — exactly like Swift's single encoder.
        """
        is_guitar = True
        if resolved_mt:
            try:
                from .measurement_type import MeasurementType
                is_guitar = MeasurementType(resolved_mt).is_guitar
            except Exception:
                pass

        if is_guitar and self.peaks:
            try:
                from .guitar_mode import GuitarMode
                from .guitar_type import GuitarType
                gt_enum = GuitarType(resolved_gt) if resolved_gt else GuitarType.CLASSICAL
                mode_map = GuitarMode.classify_all(self.peaks, gt_enum)
            except Exception:
                mode_map = {}
            overrides = self.peak_mode_overrides or {}
            guitar_labels: list[str] = []
            for peak in self.peaks:
                override = overrides.get(peak.id)
                if override:
                    guitar_labels.append(override)
                else:
                    mode = mode_map.get(peak.id)
                    guitar_labels.append(mode.display_name if mode else "Unknown")
            return guitar_labels

        # Plate / brace: label by which selected-peak role each peak fills.
        role_labels: list[str] = []
        for peak in self.peaks:
            if peak.id == self.selected_longitudinal_peak_id:
                role_labels.append("Longitudinal")
            elif peak.id == self.selected_cross_peak_id:
                role_labels.append("Cross-grain")
            elif peak.id == self.selected_flc_peak_id:
                role_labels.append("FLC")
            else:
                role_labels.append("Peak")
        return role_labels

    def to_dict(self) -> dict[str, Any]:
        """Encode this measurement as a JSON-compatible dict using Swift field names.

        Keys are written in the same order as Swift's custom encode(to:) so that
        files produced by Python and Swift are directly comparable line-by-line.

        Mirrors Swift TapToneMeasurement.encode(to:).  This is THE measurement
        serializer: persistence (saved_measurements.json), single-measurement
        export, and whole-library Export All all go through it, so every written
        `.guitartap` file is byte-identical regardless of which path produced it.
        Python-only — Swift uses Codable with a custom encoder.
        """
        d: dict[str, Any] = {}

        # Standard stored properties — mirrors Swift encoding order exactly.
        d["id"] = self.id
        d["timestamp"] = self.timestamp
        if self.decay_time is not None:
            d["decayTime"] = f32(self.decay_time)
        if self.measurement_name:
            d["measurementName"] = self.measurement_name
        if self.notes:
            d["notes"] = self.notes
        if self.spectrum_snapshot is not None:
            d["spectrumSnapshot"] = self.spectrum_snapshot.to_dict()
        # Mirrors Swift encodeIfPresent(namedOffsets, forKey: .peakAnnotationOffsets):
        # nil -> key omitted; non-nil -> flat array of alternating UUID-string /
        # offset-object pairs (because UUID is not a JSON string key), which is the
        # empty array [] for a non-nil empty dict.  Values are absolute data-space
        # label-center positions: absFreqHz, absDB.
        if self.annotation_offsets is not None:
            offsets_array: list[Any] = []
            for k, v in self.annotation_offsets.items():
                offsets_array.append(k)
                offsets_array.append({"absFreqHz": v[0], "absDB": v[1]})
            d["peakAnnotationOffsets"] = offsets_array
        if self.tap_detection_threshold is not None:
            d["tapDetectionThreshold"] = f32(self.tap_detection_threshold)
        if self.number_of_taps is not None:
            d["numberOfTaps"] = self.number_of_taps
        if self.peak_min_threshold is not None:
            # Canonical key is "peakMinThreshold" (matches Swift encode(to:) and the
            # user manual, App. B).  The legacy "peakThreshold" key is read on import
            # for backward compatibility but no longer written.
            d["peakMinThreshold"] = f32(self.peak_min_threshold)
        if self.selected_longitudinal_peak_id:
            d["selectedLongitudinalPeakID"] = self.selected_longitudinal_peak_id
        if self.selected_cross_peak_id:
            d["selectedCrossPeakID"] = self.selected_cross_peak_id
        if self.selected_flc_peak_id:
            d["selectedFlcPeakID"] = self.selected_flc_peak_id
        if self.longitudinal_snapshot is not None:
            d["longitudinalSnapshot"] = self.longitudinal_snapshot.to_dict()
        if self.cross_snapshot is not None:
            d["crossSnapshot"] = self.cross_snapshot.to_dict()
        if self.flc_snapshot is not None:
            d["flcSnapshot"] = self.flc_snapshot.to_dict()
        if self.selected_peak_ids:
            d["selectedPeakIDs"] = self.selected_peak_ids
        if self.selected_peak_frequencies:
            # Swift [Float] -> quantise each to float32.
            d["selectedPeakFrequencies"] = f32_list(self.selected_peak_frequencies)
        if self.user_modified_selection is not None:
            d["userModifiedSelection"] = self.user_modified_selection
        if self.annotation_visibility_mode:
            d["annotationVisibilityMode"] = self.annotation_visibility_mode
        if self.peak_mode_overrides:
            # Swift encodes [UUID: UserAssignedMode] as a flat array of alternating
            # UUID-string / mode-object pairs (UUID is not a JSON string key), exactly
            # like peakAnnotationOffsets above.  Each mode object is
            # {"type": "assigned", "label": "<mode_string>"}.  Python only ever stores
            # assigned overrides (the model is {uuid: label}); ".auto" entries are
            # semantically equivalent to "no entry" and are simply omitted.
            overrides_array: list[Any] = []
            for uid, label in self.peak_mode_overrides.items():
                overrides_array.append(uid)
                overrides_array.append({"type": "assigned", "label": label})
            d["peakModeOverrides"] = overrides_array
        if self.microphone_name:
            d["microphoneName"] = self.microphone_name
        if self.microphone_uid:
            d["microphoneUID"] = self.microphone_uid
        if self.calibration_name:
            d["calibrationName"] = self.calibration_name
        if self.sample_rate is not None:
            d["sampleRate"] = self.sample_rate

        # Convenience top-level fields for external consumers.
        # Mirrors Swift encode(to:): resolved from the snapshot, not from stored fields.
        # Swift: resolvedMeasurementType = spectrumSnapshot?.measurementType ?? longitudinalSnapshot?.measurementType
        #        resolvedGuitarType       = spectrumSnapshot?.guitarType      ?? longitudinalSnapshot?.guitarType
        _snap_for_type = self.spectrum_snapshot or self.longitudinal_snapshot
        _resolved_mt = (
            (_snap_for_type.measurement_type if _snap_for_type else None)
            or self.measurement_type
        )
        _resolved_gt = (
            (_snap_for_type.guitar_type if _snap_for_type else None)
            or self.guitar_type
        )
        if _resolved_mt:
            d["measurementType"] = _resolved_mt
        if _resolved_gt:
            d["guitarType"] = _resolved_gt

        # Peaks written last, each with a *resolved* modeLabel — mirrors Swift's
        # single encode(to:) (PeakExportCodingKeys loop), which always classifies
        # rather than emitting a stored label.  Resolving here (not in a separate
        # export-only function) is what makes persistence and every export path
        # byte-identical, matching Swift's one-encoder design.
        peak_dicts = [p.to_dict() for p in self.peaks]
        for peak_d, label in zip(
            peak_dicts, self._resolve_peak_mode_labels(_resolved_mt, _resolved_gt)
        ):
            peak_d["modeLabel"] = label
        d["peaks"] = peak_dicts

        # Comparison entries — omitted (encodeIfPresent) when None.
        # Mirrors Swift TapToneMeasurement.encode(to:) comparisonEntries.
        if self.comparison_entries is not None:
            d["comparisonEntries"] = [e.to_dict() for e in self.comparison_entries]

        # Multi-tap entries — omitted (encodeIfPresent) when None.
        # Mirrors Swift TapToneMeasurement.encode(to:) tapEntries.
        if self.tap_entries is not None:
            d["tapEntries"] = [e.to_dict() for e in self.tap_entries]

        return d

    # MARK: - Duplicate-Peak Heal

    PEAK_PROXIMITY_HZ: float = 2.0

    @staticmethod
    def heal_duplicate_peaks(
        peaks: list, selected_ids: set
    ) -> tuple[list, set]:
        """Collapse peaks that describe the same spectral feature.

        Files written before the find_peaks duplicate fix contain one bit-identical twin per
        capture (and one per tap entry in multi-tap files): the detector visited overlap bins
        once per overlapping mode range and minted a peak each time. Loaded peaks are
        authoritative and are never re-derived, so without this every existing file would show
        a phantom Analysis Results row forever. See
        Development/PEAK-FINDING-DUPLICATE-PEAKS.md in the GuitarTapWeb repo.

        Keeps, in order of preference: the peak in ``selected_ids`` (the claimed mode winner),
        then the louder, then the first seen. find_peaks guarantees legitimately saved peaks
        are at least PEAK_PROXIMITY_HZ apart, so any closer pair is corruption by definition.

        Mirrors Swift TapToneMeasurement.healDuplicatePeaks(_:selectedIDs:).

        Returns:
            (healed peaks, ids that were dropped) — the id set is empty when nothing changed.
        """
        kept: list = []
        removed: set = set()

        for peak in peaks:
            idx = next(
                (
                    i
                    for i, k in enumerate(kept)
                    if abs(k.frequency - peak.frequency)
                    < TapToneMeasurement.PEAK_PROXIMITY_HZ
                ),
                None,
            )
            if idx is None:
                kept.append(peak)
                continue

            incumbent = kept[idx]
            if (peak.id in selected_ids) != (incumbent.id in selected_ids):
                prefer_incoming = peak.id in selected_ids
            else:
                prefer_incoming = peak.magnitude > incumbent.magnitude

            if prefer_incoming:
                removed.add(incumbent.id)
                kept[idx] = peak
            else:
                removed.add(peak.id)

        return kept, removed

    @staticmethod
    def from_dict(d: dict) -> "TapToneMeasurement":
        """Decode a Swift-format TapToneMeasurement JSON object.

        Python-only — Swift uses Codable.
        """
        peaks = [ResonantPeak.from_dict(p) for p in d.get("peaks", [])]

        snap_d = d.get("spectrumSnapshot")
        snapshot = SpectrumSnapshot.from_dict(snap_d) if snap_d else None

        long_d  = d.get("longitudinalSnapshot")
        cross_d = d.get("crossSnapshot")
        flc_d   = d.get("flcSnapshot")
        long_snap  = SpectrumSnapshot.from_dict(long_d)  if long_d  else None
        cross_snap = SpectrumSnapshot.from_dict(cross_d) if cross_d else None
        flc_snap   = SpectrumSnapshot.from_dict(flc_d)   if flc_d   else None

        # Annotation positions — absolute data-space label-center positions (absFreqHz, absDB).
        # Swift encodes as a flat array: [uuid_str, {"absFreqHz": x, "absDB": y}, ...]
        # Legacy files may have {"hzOffset": x, "dbOffset": y} (old delta format) — those
        # are dropped (labels fall back to default positions) since the values are incompatible.
        # Preserve Swift's nil-vs-empty distinction: an absent/null key -> None
        # (Swift wrote nil), an empty array [] -> empty dict {} (Swift wrote a
        # non-nil empty dict), so re-serialisation reproduces Swift's output.
        ann_raw = d.get("peakAnnotationOffsets")
        ann_offsets: dict[str, list[float]] | None
        if isinstance(ann_raw, list):
            # Swift flat-array format: alternating uuid / offset-object pairs.
            ann_offsets = {}
            it = iter(ann_raw)
            for k in it:
                v = next(it, None)
                if isinstance(k, str) and isinstance(v, dict):
                    if "absFreqHz" in v and "absDB" in v:
                        ann_offsets[k.upper()] = [
                            float(v["absFreqHz"]),
                            float(v["absDB"]),
                        ]
                    # Old hzOffset/dbOffset entries are silently dropped.
        elif isinstance(ann_raw, dict):
            # Legacy {uuid: offset} object form.  Swift drops an all-legacy map to
            # nil, so collapse an empty result to None here.
            ann_offsets = {}
            for k, v in ann_raw.items():
                if isinstance(v, dict) and "absFreqHz" in v and "absDB" in v:
                    ann_offsets[k.upper()] = [
                        float(v["absFreqHz"]),
                        float(v["absDB"]),
                    ]
            ann_offsets = ann_offsets or None
        else:
            ann_offsets = None

        # Mode overrides.  Each value is a UserAssignedMode object
        # {"type": "assigned", "label": "mode_string"}; "auto" entries carry no
        # override and are skipped.  Canonical (Swift) encoding is a flat array of
        # alternating uuid / mode-object pairs.  A legacy {uuid: mode-object} object
        # form was written by GuitarTap Python 1.0.x — accepted here on import for
        # backward compatibility.
        mode_raw = d.get("peakModeOverrides")
        overrides: dict[str, str] = {}
        if isinstance(mode_raw, list):
            it = iter(mode_raw)
            for k in it:
                v = next(it, None)
                if isinstance(k, str) and isinstance(v, dict) and v.get("type") == "assigned":
                    label = v.get("label", "")
                    if label:
                        overrides[k] = label
        elif isinstance(mode_raw, dict):
            for uid, val in mode_raw.items():
                if isinstance(val, dict) and val.get("type") == "assigned":
                    label = val.get("label", "")
                    if label:
                        overrides[str(uid)] = label
        peak_mode_overrides: dict[str, str] | None = overrides or None

        # Comparison entries — None when absent (backward-compatible).
        comp_entries_raw = d.get("comparisonEntries")
        comparison_entries = (
            [ComparisonEntry.from_dict(e) for e in comp_entries_raw]
            if comp_entries_raw is not None
            else None
        )

        # Multi-tap entries — None when absent (backward-compatible).
        tap_entries_raw = d.get("tapEntries")
        tap_entries = (
            [TapEntry.from_dict(e) for e in tap_entries_raw]
            if tap_entries_raw is not None
            else None
        )

        # --- Heal duplicate peaks written by the pre-fix find_peaks ---
        # Every read path reaches from_dict(): .guitartap import and the saved-measurements
        # store both build measurements through it.
        healed = False
        selected_ids_raw = d.get("selectedPeakIDs")
        sel_set = set(selected_ids_raw or [])
        peaks, removed_ids = TapToneMeasurement.heal_duplicate_peaks(peaks, sel_set)
        if removed_ids:
            healed = True
            # Drop dangling references so nothing points at a peak that no longer exists.
            if selected_ids_raw is not None:
                selected_ids_raw = [i for i in selected_ids_raw if i not in removed_ids]
            if ann_offsets:
                ann_offsets = {k: v for k, v in ann_offsets.items() if k not in removed_ids}
            if peak_mode_overrides:
                peak_mode_overrides = {
                    k: v for k, v in peak_mode_overrides.items() if k not in removed_ids
                }

        # Multi-tap files carry a duplicate inside every tap entry as well; the Taps view and
        # the multi-tap PDF read those, so they need the same repair.
        if tap_entries:
            for te in tap_entries:
                te_peaks, te_removed = TapToneMeasurement.heal_duplicate_peaks(
                    te.peaks, set(te.selected_peak_ids or [])
                )
                if not te_removed:
                    continue
                te.peaks = te_peaks
                te.selected_peak_ids = [
                    i for i in (te.selected_peak_ids or []) if i not in te_removed
                ]
                healed = True

        # --- Phase 6b: heal legacy comparison entries — fill the definitive mode→peak map ---
        # Pre-6b saved comparisons stored no `modePeakIDs`, so their Air/Top/Back was re-derived
        # positionally at render — and could not reflect a source measurement's override. Compute it
        # once now from each entry's own selected peaks. Override-BLIND (an old file never wrote the
        # source's overrides, so nothing better is recoverable), but it freezes what the old app
        # showed and makes the file self-describing from here on. Mirrors Swift init(from:).
        if comparison_entries:
            from .tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin as _PA
            for _e in comparison_entries:
                if _e.mode_peak_ids is None:
                    _resolved = _PA.resolved_mode_peaks(_e.peaks, guitar_type=_e.guitar_type)
                    _e.mode_peak_ids = ComparisonEntry.mode_id_map(_resolved)
                    healed = True

        # --- Phase 6: heal the guitar DEFINITIVE selection (Air/Top/Back at most one each) ---
        # Guitar only. A file with no saved selection is auto-selected (strongest per mode via the
        # EFFECTIVE mode); a pre-Phase-5 file with >1 selected in a single-holder mode is pruned to the
        # strongest. Same `healed` re-save contract as the duplicate heal. Mirrors Swift init(from:).
        _mt_raw = d.get("measurementType")
        if _mt_raw:
            try:
                from .measurement_type import MeasurementType as _MT
                _is_material_at_decode = not _MT.from_string(_mt_raw).is_guitar
            except Exception:
                _is_material_at_decode = long_snap is not None
        else:
            _is_material_at_decode = long_snap is not None
        if not _is_material_at_decode and peaks:
            from . import guitar_mode as _gm
            from . import guitar_type as _gt_mod
            try:
                _gt = _gt_mod.GuitarType(d.get("guitarType") or "Classical")
            except Exception:
                _gt = _gt_mod.GuitarType.CLASSICAL
            _auto = _gm.GuitarMode.classify_all(peaks, _gt)
            _ovr = peak_mode_overrides or {}
            _single = {_gm.GuitarMode.AIR, _gm.GuitarMode.TOP, _gm.GuitarMode.BACK}

            def _eff(p):
                return _gm.GuitarMode.effective_mode(
                    _ovr.get(p.id), _auto.get(p.id, _gm.GuitarMode.UNKNOWN)
                ).normalized

            if selected_ids_raw is None:
                # Auto-select the strongest peak per (effective) mode.
                _chosen: dict = {}
                for p in peaks:
                    m = _eff(p)
                    if m == _gm.GuitarMode.UNKNOWN:
                        continue
                    if _chosen.get(m) is None or p.magnitude > _chosen[m].magnitude:
                        _chosen[m] = p
                selected_ids_raw = [p.id for p in _chosen.values()]
                healed = True
            else:
                # Prune each single-holder mode with >1 selected down to its strongest.
                _sel = set(selected_ids_raw)
                _winners: dict = {}
                for p in peaks:
                    if p.id not in _sel:
                        continue
                    m = _eff(p)
                    if m not in _single:
                        continue
                    if _winners.get(m) is None or p.magnitude > _winners[m].magnitude:
                        _winners[m] = p
                _winner_ids = {p.id for p in _winners.values()}
                _by_id = {p.id: p for p in peaks}
                _pruned = [
                    i for i in selected_ids_raw
                    if (_p := _by_id.get(i)) is not None
                    and (_eff(_p) not in _single or i in _winner_ids)
                ]
                if len(_pruned) != len(selected_ids_raw):
                    selected_ids_raw = _pruned
                    healed = True

        return TapToneMeasurement(
            id=d.get("id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", _now_iso()),
            peaks=peaks,
            decay_time=d.get("decayTime"),
            # Fall back to legacy "tapLocation" key for files saved before the rename.
            measurement_name=d.get("measurementName") or d.get("tapLocation"),
            notes=d.get("notes"),
            spectrum_snapshot=snapshot,
            annotation_offsets=ann_offsets,
            selected_peak_ids=selected_ids_raw,
            selected_peak_frequencies=d.get("selectedPeakFrequencies"),
            user_modified_selection=d.get("userModifiedSelection"),
            annotation_visibility_mode=d.get("annotationVisibilityMode"),
            tap_detection_threshold=d.get("tapDetectionThreshold"),
            number_of_taps=d.get("numberOfTaps"),
            # Canonical key is "peakMinThreshold"; fall back to the legacy
            # "peakThreshold" key for files written before the rename (and by
            # GuitarTap Python 1.0.x).
            peak_min_threshold=(
                d["peakMinThreshold"]
                if d.get("peakMinThreshold") is not None
                else d.get("peakThreshold")
            ),
            selected_longitudinal_peak_id=d.get("selectedLongitudinalPeakID"),
            selected_cross_peak_id=d.get("selectedCrossPeakID"),
            selected_flc_peak_id=d.get("selectedFlcPeakID"),
            longitudinal_snapshot=long_snap,
            cross_snapshot=cross_snap,
            flc_snapshot=flc_snap,
            peak_mode_overrides=peak_mode_overrides,
            microphone_name=d.get("microphoneName"),
            microphone_uid=d.get("microphoneUID"),
            calibration_name=d.get("calibrationName"),
            sample_rate=d.get("sampleRate"),
            measurement_type=d.get("measurementType"),
            guitar_type=d.get("guitarType"),
            comparison_entries=comparison_entries,
            tap_entries=tap_entries,
            was_healed=healed,
        )

    @staticmethod
    def create(
        peaks: list[ResonantPeak],
        decay_time: float | None = None,
        measurement_name: str | None = None,
        notes: str | None = None,
        spectrum_snapshot: SpectrumSnapshot | None = None,
        annotation_offsets: dict[str, list[float]] | None = None,
        selected_peak_ids: list[str] | None = None,
        selected_peak_frequencies: list[float] | None = None,
        user_modified_selection: bool | None = None,
        annotation_visibility_mode: str | None = None,
        tap_detection_threshold: float | None = None,
        number_of_taps: int | None = None,
        peak_min_threshold: float | None = None,
        selected_longitudinal_peak_id: str | None = None,
        selected_cross_peak_id: str | None = None,
        selected_flc_peak_id: str | None = None,
        longitudinal_snapshot: SpectrumSnapshot | None = None,
        cross_snapshot: SpectrumSnapshot | None = None,
        flc_snapshot: SpectrumSnapshot | None = None,
        peak_mode_overrides: dict[str, str] | None = None,
        microphone_name: str | None = None,
        microphone_uid: str | None = None,
        calibration_name: str | None = None,
        sample_rate: float | None = None,
        measurement_type: str | None = None,
        guitar_type: str | None = None,
        comparison_entries: list[ComparisonEntry] | None = None,
        tap_entries: list[TapEntry] | None = None,
    ) -> "TapToneMeasurement":
        """Factory method — creates a new measurement with a fresh UUID and current timestamp.

        All parameters except ``peaks`` have sensible defaults of ``None`` so callers only
        need to supply the fields relevant to their measurement type.

        Mirrors Swift TapToneMeasurement.init(...) with defaults.
        ``measurement_name`` mirrors Swift ``measurementName``.

        Python-only — Swift uses a struct initialiser with default parameters.
        """
        return TapToneMeasurement(
            id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            peaks=peaks,
            decay_time=decay_time,
            measurement_name=measurement_name or None,
            notes=notes or None,
            spectrum_snapshot=spectrum_snapshot,
            annotation_offsets=annotation_offsets or None,
            selected_peak_ids=selected_peak_ids or None,
            selected_peak_frequencies=selected_peak_frequencies or None,
            user_modified_selection=user_modified_selection,
            annotation_visibility_mode=annotation_visibility_mode,
            tap_detection_threshold=tap_detection_threshold,
            number_of_taps=number_of_taps,
            peak_min_threshold=peak_min_threshold,
            selected_longitudinal_peak_id=selected_longitudinal_peak_id,
            selected_cross_peak_id=selected_cross_peak_id,
            selected_flc_peak_id=selected_flc_peak_id,
            longitudinal_snapshot=longitudinal_snapshot,
            cross_snapshot=cross_snapshot,
            flc_snapshot=flc_snapshot,
            peak_mode_overrides=peak_mode_overrides or None,
            microphone_name=microphone_name,
            microphone_uid=microphone_uid,
            calibration_name=calibration_name,
            sample_rate=sample_rate,
            measurement_type=measurement_type,
            guitar_type=guitar_type,
            comparison_entries=comparison_entries,
            tap_entries=tap_entries,
        )
