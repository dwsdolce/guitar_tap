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

from .resonant_peak import ResonantPeak
from .spectrum_snapshot import SpectrumSnapshot


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # Descriptive label for the tap location, e.g. "Bridge", "Soundhole", "Upper Bout".
    # Mirrors Swift TapToneMeasurement.tapLocation.
    tap_location: str | None = None

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

    # The annotation visibility mode (show all / show selected / hide all) that was active
    # when the measurement was saved. Stored as a raw string in Python;
    # Swift uses AnnotationVisibilityMode enum.
    # Mirrors Swift TapToneMeasurement.annotationVisibilityMode.
    annotation_visibility_mode: str | None = None

    # MARK: - Analysis Settings

    # The tap-detection threshold (dB above noise floor) configured at save time.
    # Mirrors Swift TapToneMeasurement.tapDetectionThreshold.
    tap_detection_threshold: float | None = None

    # The hysteresis margin (dB) used to prevent re-triggering after a tap, at save time.
    # Mirrors Swift TapToneMeasurement.hysteresisMargin.
    hysteresis_margin: float | None = None

    # The number of taps that were averaged to produce the final spectrum.
    # Mirrors Swift TapToneMeasurement.numberOfTaps.
    number_of_taps: int | None = None

    # The minimum peak magnitude (dBFS) that the peak-finder accepted, at save time.
    # Mirrors Swift TapToneMeasurement.peakThreshold.
    peak_threshold: float | None = None

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

    # Convenience top-level fields written to JSON for external consumers.
    # Mirrors Swift TapToneMeasurement encode(to:) convenience fields.
    measurement_type: str | None = None
    guitar_type: str | None = None

    # MARK: - Computed Properties

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
        from . import guitar_type as gt_module
        if not self.peaks:
            return None
        gt_str = self.guitar_type or "Classical"
        try:
            gt = gt_module.GuitarType(gt_str)
        except Exception:
            gt = gt_module.GuitarType.CLASSICAL
        # Mirrors Swift calculateTapToneRatio() which reads from identifiedModes —
        # identifiedModes is built from currentPeaks (the selected peaks only).
        # Run classify_all on selected peaks only; fall back to all peaks when
        # no selection is recorded (e.g. legacy measurements without selectedPeakIDs).
        selected_ids: set[str] = set(self.selected_peak_ids or [])
        peaks_for_ratio = (
            [p for p in self.peaks if p.id in selected_ids]
            if selected_ids else self.peaks
        )
        try:
            id_map = gm.GuitarMode.classify_all(peaks_for_ratio, gt)
        except Exception:
            return None
        # id_map is {peak.id: GuitarMode} — mirrors Swift [UUID: GuitarMode]
        air_freq = next(
            (p.frequency for p in peaks_for_ratio
             if id_map.get(p.id, gm.GuitarMode.UNKNOWN).normalized == gm.GuitarMode.AIR),
            None,
        )
        top_freq = next(
            (p.frequency for p in peaks_for_ratio
             if id_map.get(p.id, gm.GuitarMode.UNKNOWN).normalized == gm.GuitarMode.TOP),
            None,
        )
        if air_freq and top_freq and air_freq > 0:
            return top_freq / air_freq
        return None

    @property
    def base_filename(self) -> str:
        """Base filename (without extension) derived from the tap location and Unix timestamp.

        Spaces and slashes in ``tap_location`` are replaced with hyphens and the string is
        lowercased, producing a filesystem-safe component such as ``"bridge-1771351833"``.
        Falls back to ``"measurement"`` when ``tap_location`` is ``None``.

        Mirrors Swift TapToneMeasurement.baseFilename.
        """
        loc = (self.tap_location or "measurement").replace(" ", "-").replace("/", "-").lower()
        try:
            ts = int(datetime.fromisoformat(self.timestamp).timestamp())
        except Exception:
            ts = 0
        return f"{loc}-{ts}"

    def display_name(self) -> str:
        """Human-readable display name combining tap location and formatted timestamp.

        Example: ``"Bridge — 2026-01-25 14:32"``

        Python-only — no Swift equivalent.
        """
        try:
            dt = datetime.fromisoformat(self.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            time_str = self.timestamp[:16] if len(self.timestamp) >= 16 else self.timestamp
        if self.tap_location:
            return f"{self.tap_location} — {time_str}"
        return time_str

    def with_(self, tap_location: str | None, notes: str | None) -> "TapToneMeasurement":
        """Return a copy of the measurement with only ``tap_location`` and ``notes`` replaced.

        All other fields — including ``id`` and ``timestamp`` — are preserved exactly.

        Mirrors Swift TapToneMeasurement.with(tapLocation:notes:).
        """
        import dataclasses
        return dataclasses.replace(self, tap_location=tap_location, notes=notes)

    # MARK: - Serialisation (Python-only)

    def to_dict(self) -> dict[str, Any]:
        """Encode this measurement as a JSON-compatible dict using Swift field names.

        Keys are written in the same order as Swift's custom encode(to:) so that
        files produced by Python and Swift are directly comparable line-by-line.

        Mirrors Swift TapToneMeasurement.encode(to:).
        Python-only — Swift uses Codable with a custom encoder.
        """
        d: dict[str, Any] = {}

        # Standard stored properties — mirrors Swift encoding order exactly.
        d["id"] = self.id
        d["timestamp"] = self.timestamp
        if self.decay_time is not None:
            d["decayTime"] = self.decay_time
        if self.tap_location:
            d["tapLocation"] = self.tap_location
        if self.notes:
            d["notes"] = self.notes
        if self.spectrum_snapshot is not None:
            d["spectrumSnapshot"] = self.spectrum_snapshot.to_dict()
        # Always written — mirrors Swift encodeIfPresent(namedOffsets, forKey: .peakAnnotationOffsets).
        # Swift encodes [UUID: PeakAnnotationOffset] as a flat array of alternating UUID-string /
        # offset-object pairs (because UUID is not a JSON string key).  Empty dict → empty array [].
        # Values are absolute data-space label-center positions: absFreqHz, absDB.
        if self.annotation_offsets:
            offsets_array = []
            for k, v in self.annotation_offsets.items():
                offsets_array.append(k)
                offsets_array.append({"absFreqHz": v[0], "absDB": v[1]})
            d["peakAnnotationOffsets"] = offsets_array
        else:
            d["peakAnnotationOffsets"] = []
        if self.tap_detection_threshold is not None:
            d["tapDetectionThreshold"] = self.tap_detection_threshold
        if self.hysteresis_margin is not None:
            d["hysteresisMargin"] = self.hysteresis_margin
        if self.number_of_taps is not None:
            d["numberOfTaps"] = self.number_of_taps
        if self.peak_threshold is not None:
            d["peakThreshold"] = self.peak_threshold
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
            d["selectedPeakFrequencies"] = self.selected_peak_frequencies
        if self.annotation_visibility_mode:
            d["annotationVisibilityMode"] = self.annotation_visibility_mode
        if self.peak_mode_overrides:
            # Swift format: {uuid: {"type": "assigned", "label": "mode_string"}}
            d["peakModeOverrides"] = {
                uid: {"type": "assigned", "label": label}
                for uid, label in self.peak_mode_overrides.items()
            }
        if self.microphone_name:
            d["microphoneName"] = self.microphone_name
        if self.microphone_uid:
            d["microphoneUID"] = self.microphone_uid
        if self.calibration_name:
            d["calibrationName"] = self.calibration_name

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

        # Peaks written last, with modeLabel injected per entry — mirrors Swift
        # encode(to:) PeakExportCodingKeys loop.  Note: export_measurement_json()
        # overwrites modeLabel with the resolved classification; to_dict() emits
        # whatever is already stored in peak.mode_label.
        d["peaks"] = [p.to_dict() for p in self.peaks]

        return d

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
        ann_raw = d.get("peakAnnotationOffsets")
        ann_offsets: dict[str, list[float]] | None = None
        if ann_raw and isinstance(ann_raw, list):
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
            ann_offsets = ann_offsets or None
        elif ann_raw and isinstance(ann_raw, dict):
            ann_offsets = {}
            for k, v in ann_raw.items():
                if isinstance(v, dict) and "absFreqHz" in v and "absDB" in v:
                    ann_offsets[k.upper()] = [
                        float(v["absFreqHz"]),
                        float(v["absDB"]),
                    ]
            ann_offsets = ann_offsets or None

        # Mode overrides — {uuid: {"type": "assigned", "label": "mode_string"}}
        # type == "auto" entries have no override and are skipped.
        mode_raw = d.get("peakModeOverrides")
        peak_mode_overrides: dict[str, str] | None = None
        if isinstance(mode_raw, dict) and mode_raw:
            overrides: dict[str, str] = {}
            for uid, val in mode_raw.items():
                if isinstance(val, dict) and val.get("type") == "assigned":
                    label = val.get("label", "")
                    if label:
                        overrides[str(uid)] = label
            peak_mode_overrides = overrides if overrides else None

        return TapToneMeasurement(
            id=d.get("id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", _now_iso()),
            peaks=peaks,
            decay_time=d.get("decayTime"),
            tap_location=d.get("tapLocation"),
            notes=d.get("notes"),
            spectrum_snapshot=snapshot,
            annotation_offsets=ann_offsets,
            selected_peak_ids=d.get("selectedPeakIDs"),
            selected_peak_frequencies=d.get("selectedPeakFrequencies"),
            annotation_visibility_mode=d.get("annotationVisibilityMode"),
            tap_detection_threshold=d.get("tapDetectionThreshold"),
            hysteresis_margin=d.get("hysteresisMargin"),
            number_of_taps=d.get("numberOfTaps"),
            peak_threshold=d.get("peakThreshold"),
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
            measurement_type=d.get("measurementType"),
            guitar_type=d.get("guitarType"),
        )

    @staticmethod
    def create(
        peaks: list[ResonantPeak],
        decay_time: float | None = None,
        tap_location: str | None = None,
        notes: str | None = None,
        spectrum_snapshot: SpectrumSnapshot | None = None,
        annotation_offsets: dict[str, list[float]] | None = None,
        selected_peak_ids: list[str] | None = None,
        selected_peak_frequencies: list[float] | None = None,
        annotation_visibility_mode: str | None = None,
        tap_detection_threshold: float | None = None,
        hysteresis_margin: float | None = None,
        number_of_taps: int | None = None,
        peak_threshold: float | None = None,
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
        measurement_type: str | None = None,
        guitar_type: str | None = None,
    ) -> "TapToneMeasurement":
        """Factory method — creates a new measurement with a fresh UUID and current timestamp.

        All parameters except ``peaks`` have sensible defaults of ``None`` so callers only
        need to supply the fields relevant to their measurement type.

        Mirrors Swift TapToneMeasurement.init(...) with defaults.

        Python-only — Swift uses a struct initialiser with default parameters.
        """
        return TapToneMeasurement(
            id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            peaks=peaks,
            decay_time=decay_time,
            tap_location=tap_location or None,
            notes=notes or None,
            spectrum_snapshot=spectrum_snapshot,
            annotation_offsets=annotation_offsets or None,
            selected_peak_ids=selected_peak_ids or None,
            selected_peak_frequencies=selected_peak_frequencies or None,
            annotation_visibility_mode=annotation_visibility_mode,
            tap_detection_threshold=tap_detection_threshold,
            hysteresis_margin=hysteresis_margin,
            number_of_taps=number_of_taps,
            peak_threshold=peak_threshold,
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
            measurement_type=measurement_type,
            guitar_type=guitar_type,
        )
