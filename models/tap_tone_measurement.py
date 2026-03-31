"""
Complete measurement record — mirrors Swift TapToneMeasurement.swift.

JSON format:
  - Single saved_measurements.json in ~/Documents/GuitarTap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - Format is cross-compatible with Swift GuitarTap .guitartap files
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
    """
    Complete record of a tap-tone analysis session.

    Mirrors Swift TapToneMeasurement struct (TapToneMeasurement.swift).
    JSON is cross-compatible with the iOS/macOS app.
    """
    id: str        # UUID string — mirrors Swift TapToneMeasurement.id
    timestamp: str  # ISO-8601 — mirrors Swift TapToneMeasurement.timestamp
    peaks: list[ResonantPeak]

    decay_time: float | None = None
    tap_location: str | None = None
    notes: str | None = None

    # Primary spectrum — mirrors Swift TapToneMeasurement.spectrumSnapshot
    spectrum_snapshot: SpectrumSnapshot | None = None

    # Per-phase spectra for plate/brace measurements (nil for guitar)
    # Mirrors Swift TapToneMeasurement.longitudinalSnapshot / crossSnapshot / flcSnapshot
    longitudinal_snapshot: SpectrumSnapshot | None = None
    cross_snapshot: SpectrumSnapshot | None = None
    flc_snapshot: SpectrumSnapshot | None = None

    # Analysis settings at save time
    tap_detection_threshold: float | None = None
    hysteresis_margin: float | None = None
    number_of_taps: int | None = None
    peak_threshold: float | None = None

    # Peak selections (all keyed by peak UUID)
    selected_peak_ids: list[str] | None = None       # peaks marked visible
    # Mirrors Swift TapToneMeasurement.peakModeOverrides ([UUID: UserAssignedMode])
    peak_mode_overrides: dict[str, str] | None = None  # UUID → mode string
    # Mirrors Swift TapToneMeasurement.peakAnnotationOffsets ([UUID: CGPoint])
    annotation_offsets: dict[str, list[float]] | None = None  # UUID → [hzOffset, dbOffset]
    annotation_visibility_mode: str | None = None

    # Plate/brace phase-selected peak IDs
    # Mirrors Swift TapToneMeasurement.selectedLongitudinalPeakID etc.
    selected_longitudinal_peak_id: str | None = None
    selected_cross_peak_id: str | None = None
    selected_flc_peak_id: str | None = None

    # Microphone provenance — mirrors Swift TapToneMeasurement.microphoneName etc.
    microphone_name: str | None = None
    microphone_uid: str | None = None
    calibration_name: str | None = None

    # Convenience top-level fields (for external consumers)
    measurement_type: str | None = None
    guitar_type: str | None = None

    # ── Computed ─────────────────────────────────────────────────────────────

    @property
    def tap_tone_ratio(self) -> float | None:
        """fTop / fAir ratio.

        Mirrors Swift TapToneMeasurement.tapToneRatio.
        Returns None if either mode is not found.
        """
        from . import guitar_mode as gm
        if not self.peaks:
            return None
        peaks_fm = [(p.frequency, p.magnitude) for p in self.peaks]
        gt = self.guitar_type or "Classical"
        try:
            idx_map = gm.GuitarMode.classify_all(peaks_fm, gt)
        except Exception:
            return None
        mode_by_freq = {peaks_fm[i][0]: mode for i, mode in idx_map.items()}
        air = next(
            (p.frequency for p in self.peaks
             if mode_by_freq.get(p.frequency, gm.GuitarMode.UNKNOWN).normalized
             == gm.GuitarMode.AIR),
            None,
        )
        top = next(
            (p.frequency for p in self.peaks
             if mode_by_freq.get(p.frequency, gm.GuitarMode.UNKNOWN).normalized
             == gm.GuitarMode.TOP),
            None,
        )
        if air and top and air > 0:
            return top / air
        return None

    @property
    def base_filename(self) -> str:
        """Mirrors Swift TapToneMeasurement.baseFilename."""
        loc = (self.tap_location or "measurement").replace(" ", "-").replace("/", "-").lower()
        try:
            ts = int(datetime.fromisoformat(self.timestamp).timestamp())
        except Exception:
            ts = 0
        return f"{loc}-{ts}"

    def display_name(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            time_str = self.timestamp[:16] if len(self.timestamp) >= 16 else self.timestamp
        if self.tap_location:
            return f"{self.tap_location} — {time_str}"
        return time_str

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "timestamp": self.timestamp,
            "peaks": [p.to_dict() for p in self.peaks],
        }
        if self.decay_time is not None:
            d["decayTime"] = self.decay_time
        if self.tap_location:
            d["tapLocation"] = self.tap_location
        if self.notes:
            d["notes"] = self.notes
        if self.spectrum_snapshot is not None:
            d["spectrumSnapshot"] = self.spectrum_snapshot.to_dict()
        if self.tap_detection_threshold is not None:
            d["tapDetectionThreshold"] = self.tap_detection_threshold
        if self.hysteresis_margin is not None:
            d["hysteresisMargin"] = self.hysteresis_margin
        if self.number_of_taps is not None:
            d["numberOfTaps"] = self.number_of_taps
        if self.peak_threshold is not None:
            d["peakThreshold"] = self.peak_threshold
        if self.selected_peak_ids:
            d["selectedPeakIDs"] = self.selected_peak_ids
        if self.peak_mode_overrides:
            # Swift format: {uuid: {"type": "assigned", "label": "mode_string"}}
            d["peakModeOverrides"] = {
                uid: {"type": "assigned", "label": label}
                for uid, label in self.peak_mode_overrides.items()
            }
        if self.annotation_offsets:
            # Swift format: {uuid: {"hzOffset": hz_delta, "dbOffset": db_delta}}
            # dbOffset is in screen-Y direction: positive = downward = lower dB.
            d["peakAnnotationOffsets"] = {
                k: {"hzOffset": v[0], "dbOffset": v[1]}
                for k, v in self.annotation_offsets.items()
            }
        if self.annotation_visibility_mode:
            d["annotationVisibilityMode"] = self.annotation_visibility_mode
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
        if self.microphone_name:
            d["microphoneName"] = self.microphone_name
        if self.microphone_uid:
            d["microphoneUID"] = self.microphone_uid
        if self.calibration_name:
            d["calibrationName"] = self.calibration_name
        if self.measurement_type:
            d["measurementType"] = self.measurement_type
        if self.guitar_type:
            d["guitarType"] = self.guitar_type
        return d

    @staticmethod
    def from_dict(d: dict) -> "TapToneMeasurement":
        """Decode a Swift-format TapToneMeasurement JSON object."""
        peaks = [ResonantPeak.from_dict(p) for p in d.get("peaks", [])]

        snap_d = d.get("spectrumSnapshot")
        snapshot = SpectrumSnapshot.from_dict(snap_d) if snap_d else None

        long_d  = d.get("longitudinalSnapshot")
        cross_d = d.get("crossSnapshot")
        flc_d   = d.get("flcSnapshot")
        long_snap  = SpectrumSnapshot.from_dict(long_d)  if long_d  else None
        cross_snap = SpectrumSnapshot.from_dict(cross_d) if cross_d else None
        flc_snap   = SpectrumSnapshot.from_dict(flc_d)   if flc_d   else None

        # Annotation offsets — {uuid: {"hzOffset": hz_delta, "dbOffset": db_delta}}
        # hzOffset: Hz delta from peak frequency (positive = right)
        # dbOffset: screen-Y direction (positive = downward = lower dB)
        ann_raw = d.get("peakAnnotationOffsets")
        ann_offsets: dict[str, list[float]] | None = None
        if ann_raw and isinstance(ann_raw, dict):
            ann_offsets = {}
            for k, v in ann_raw.items():
                if isinstance(v, dict):
                    ann_offsets[k.upper()] = [
                        float(v.get("hzOffset", 0)),
                        float(v.get("dbOffset", 0)),
                    ]

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
            longitudinal_snapshot=long_snap,
            cross_snapshot=cross_snap,
            flc_snapshot=flc_snap,
            tap_detection_threshold=d.get("tapDetectionThreshold"),
            hysteresis_margin=d.get("hysteresisMargin"),
            number_of_taps=d.get("numberOfTaps"),
            peak_threshold=d.get("peakThreshold"),
            selected_peak_ids=d.get("selectedPeakIDs"),
            peak_mode_overrides=peak_mode_overrides,
            annotation_offsets=ann_offsets,
            annotation_visibility_mode=d.get("annotationVisibilityMode"),
            selected_longitudinal_peak_id=d.get("selectedLongitudinalPeakID"),
            selected_cross_peak_id=d.get("selectedCrossPeakID"),
            selected_flc_peak_id=d.get("selectedFlcPeakID"),
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
        longitudinal_snapshot: SpectrumSnapshot | None = None,
        cross_snapshot: SpectrumSnapshot | None = None,
        flc_snapshot: SpectrumSnapshot | None = None,
        selected_peak_ids: list[str] | None = None,
        peak_mode_overrides: dict[str, str] | None = None,
        annotation_offsets: dict[str, list[float]] | None = None,
        tap_detection_threshold: float | None = None,
        hysteresis_margin: float | None = None,
        number_of_taps: int | None = None,
        peak_threshold: float | None = None,
        selected_longitudinal_peak_id: str | None = None,
        selected_cross_peak_id: str | None = None,
        selected_flc_peak_id: str | None = None,
        microphone_name: str | None = None,
        microphone_uid: str | None = None,
        calibration_name: str | None = None,
        measurement_type: str | None = None,
        guitar_type: str | None = None,
    ) -> "TapToneMeasurement":
        """Factory method — mirrors Swift TapToneMeasurement.create()."""
        return TapToneMeasurement(
            id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            peaks=peaks,
            decay_time=decay_time,
            tap_location=tap_location or None,
            notes=notes or None,
            spectrum_snapshot=spectrum_snapshot,
            longitudinal_snapshot=longitudinal_snapshot,
            cross_snapshot=cross_snapshot,
            flc_snapshot=flc_snapshot,
            selected_peak_ids=selected_peak_ids or None,
            peak_mode_overrides=peak_mode_overrides or None,
            annotation_offsets=annotation_offsets or None,
            tap_detection_threshold=tap_detection_threshold,
            hysteresis_margin=hysteresis_margin,
            number_of_taps=number_of_taps,
            peak_threshold=peak_threshold,
            selected_longitudinal_peak_id=selected_longitudinal_peak_id,
            selected_cross_peak_id=selected_cross_peak_id,
            selected_flc_peak_id=selected_flc_peak_id,
            microphone_name=microphone_name,
            microphone_uid=microphone_uid,
            calibration_name=calibration_name,
            measurement_type=measurement_type,
            guitar_type=guitar_type,
        )
