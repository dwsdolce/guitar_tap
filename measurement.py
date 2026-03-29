"""
Measurement data model matching Swift TapToneMeasurement.

JSON format:
  - Single saved_measurements.json in ~/Documents/GuitarTap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - format is cross-compatible with Swift GuitarTap .guitartap files

Old per-file format (~/Documents/GuitarTap/measurements/*.json) is
automatically migrated on first run.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── SpectrumSnapshot ──────────────────────────────────────────────────────────

@dataclass
class SpectrumSnapshot:
    """Embedded spectrum data + display settings. Matches Swift SpectrumSnapshot."""
    frequencies: list[float]
    magnitudes: list[float]
    min_freq: float = 75.0
    max_freq: float = 350.0
    min_db: float = -90.0
    max_db: float = -20.0
    guitar_type: str = "Classical"
    measurement_type: str = "Classical Guitar"
    max_peaks: int = 20

    def to_dict(self) -> dict:
        return {
            "frequencies": self.frequencies,
            "magnitudes": self.magnitudes,
            "minFreq": self.min_freq,
            "maxFreq": self.max_freq,
            "minDB": self.min_db,
            "maxDB": self.max_db,
            "isLogarithmic": False,
            "showUnknownModes": True,
            "guitarType": self.guitar_type,
            "measurementType": self.measurement_type,
            "maxPeaks": self.max_peaks,
        }

    @staticmethod
    def from_dict(d: dict) -> "SpectrumSnapshot":
        import base64, struct

        # Mirrors SpectrumSnapshot.swift: try compact binary first, fall back to legacy arrays.
        # Swift encodes float32 arrays as little-endian bytes, then base64-encoded.
        if "frequenciesData" in d:
            raw = base64.b64decode(d["frequenciesData"])
            n = len(raw) // 4
            frequencies: list[float] = list(struct.unpack(f"<{n}f", raw))
        else:
            frequencies = d.get("frequencies", [])

        if "magnitudesData" in d:
            raw = base64.b64decode(d["magnitudesData"])
            n = len(raw) // 4
            magnitudes: list[float] = list(struct.unpack(f"<{n}f", raw))
        else:
            magnitudes = d.get("magnitudes", [])

        return SpectrumSnapshot(
            frequencies=frequencies,
            magnitudes=magnitudes,
            min_freq=d.get("minFreq", 75.0),
            max_freq=d.get("maxFreq", 350.0),
            min_db=d.get("minDB", -90.0),
            max_db=d.get("maxDB", -20.0),
            guitar_type=d.get("guitarType", "Classical"),
            measurement_type=d.get("measurementType", "Classical Guitar"),
            max_peaks=d.get("maxPeaks", 20),
        )


# ── PeakEntry ─────────────────────────────────────────────────────────────────

@dataclass
class PeakEntry:
    """A single detected resonant peak. Matches Swift ResonantPeak + modeLabel."""
    id: str           # UUID string
    frequency: float
    magnitude: float  # dBFS
    quality: float    # Q factor
    bandwidth: float  # Hz = frequency / quality
    timestamp: str    # ISO-8601
    mode_label: str = ""
    pitch_note: str | None = None
    pitch_cents: float | None = None
    pitch_frequency: float | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "frequency": self.frequency,
            "magnitude": self.magnitude,
            "quality": self.quality,
            "bandwidth": self.bandwidth,
            "timestamp": self.timestamp,
            "modeLabel": self.mode_label,
        }
        if self.pitch_note is not None:
            d["pitchNote"] = self.pitch_note
        if self.pitch_cents is not None:
            d["pitchCents"] = self.pitch_cents
        if self.pitch_frequency is not None:
            d["pitchFrequency"] = self.pitch_frequency
        return d

    @staticmethod
    def from_dict(d: dict) -> "PeakEntry":
        """Decode a Swift-format ResonantPeak JSON object."""
        return PeakEntry(
            id=d.get("id", str(uuid.uuid4())),
            frequency=d.get("frequency", 0.0),
            magnitude=d.get("magnitude", 0.0),
            quality=d.get("quality", 0.0),
            bandwidth=d.get("bandwidth", 0.0),
            timestamp=d.get("timestamp", _now_iso()),
            mode_label=d.get("modeLabel", ""),
            pitch_note=d.get("pitchNote"),
            pitch_cents=d.get("pitchCents"),
            pitch_frequency=d.get("pitchFrequency"),
        )


# ── TapToneMeasurement ────────────────────────────────────────────────────────

@dataclass
class TapToneMeasurement:
    """
    Complete record of a tap-tone analysis session.
    Matches Swift TapToneMeasurement; JSON is cross-compatible with the iOS/macOS app.
    """
    id: str        # UUID string
    timestamp: str  # ISO-8601
    peaks: list[PeakEntry]

    decay_time: float | None = None
    tap_location: str | None = None
    notes: str | None = None

    spectrum_snapshot: SpectrumSnapshot | None = None

    # Per-phase spectra for plate/brace measurements (nil for guitar)
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
    peak_mode_overrides: dict[str, str] | None = None  # UUID → mode string (guitar only)
    annotation_offsets: dict[str, list[float]] | None = None  # UUID → [hzOffset, dbOffset] (Swift convention: positive dbOffset = down in screen = lower dB)
    annotation_visibility_mode: str | None = None

    # Plate/brace phase-selected peak IDs (mirrors Swift selectedLongitudinalPeakID etc.)
    selected_longitudinal_peak_id: str | None = None
    selected_cross_peak_id: str | None = None
    selected_flc_peak_id: str | None = None

    # Microphone provenance
    microphone_name: str | None = None
    microphone_uid: str | None = None
    calibration_name: str | None = None

    # Convenience top-level fields (for external consumers)
    measurement_type: str | None = None
    guitar_type: str | None = None

    # ── Computed ─────────────────────────────────────────────────────────────

    @property
    def tap_tone_ratio(self) -> float | None:
        """fTop / fAir ratio. Returns None if either mode is not found."""
        import guitar_modes as gm
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

    # ── Serialization ─────────────────────────────────────────────────────────

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
        """Decode Swift-format TapToneMeasurement JSON."""
        peaks = [PeakEntry.from_dict(p) for p in d.get("peaks", [])]

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
        peaks: list[PeakEntry],
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


# ── Persistence paths ─────────────────────────────────────────────────────────

_DATA_DIR = os.path.expanduser("~/Documents/GuitarTap")
_MEASUREMENTS_FILE = os.path.join(_DATA_DIR, "saved_measurements.json")
_OLD_DIR = os.path.join(_DATA_DIR, "measurements")


def measurements_file() -> str:
    os.makedirs(_DATA_DIR, exist_ok=True)
    return _MEASUREMENTS_FILE


# ── Persistence API ───────────────────────────────────────────────────────────

def load_all_measurements() -> list[TapToneMeasurement]:
    """
    Load all measurements from saved_measurements.json.
    On first run, migrates old per-file measurements from the legacy directory.
    """
    path = measurements_file()

    # First-run migration
    if not os.path.exists(path) and os.path.isdir(_OLD_DIR):
        migrated = _migrate_old_measurements()
        if migrated:
            save_all_measurements(migrated)
            return migrated
        return []

    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [TapToneMeasurement.from_dict(d) for d in data]
        return [TapToneMeasurement.from_dict(data)]
    except Exception as exc:
        print(f"Failed to load measurements: {exc}")
        return []


def save_all_measurements(measurements: list[TapToneMeasurement]) -> None:
    """Write the full measurements list to disk atomically."""
    path = measurements_file()
    try:
        data = [m.to_dict() for m in measurements]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"Failed to save measurements: {exc}")


def export_measurement_json(m: TapToneMeasurement) -> str:
    """Return pretty-printed JSON for a single measurement."""
    return json.dumps(m.to_dict(), indent=2, ensure_ascii=False)


def import_measurements_from_json(data: str | bytes) -> list[TapToneMeasurement]:
    """
    Parse JSON from a .guitartap or .json file.
    Accepts a JSON array or a single measurement object.
    """
    raw = json.loads(data)
    if isinstance(raw, list):
        return [TapToneMeasurement.from_dict(d) for d in raw]
    return [TapToneMeasurement.from_dict(raw)]


def export_pdf(
    m: TapToneMeasurement, spectrum_png_path: str | None, output_path: str
) -> None:
    """Export measurement to PDF using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image,
    )
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Guitar Tap Measurement Report", styles["Title"]))
    story.append(Spacer(1, 0.5 * cm))

    meta = [
        ["Date", m.display_name()],
    ]
    if m.guitar_type:
        meta.append(["Guitar Type", m.guitar_type])
    if m.measurement_type:
        meta.append(["Measurement Type", m.measurement_type])
    if m.spectrum_snapshot:
        meta.append([
            "Freq Range",
            f"{m.spectrum_snapshot.min_freq} – {m.spectrum_snapshot.max_freq} Hz",
        ])
    if m.decay_time is not None:
        meta.append(["Ring-out", f"{m.decay_time:.2f} s"])
    if m.notes:
        meta.append(["Notes", m.notes])

    meta_table = Table(meta, colWidths=[4 * cm, 12 * cm])
    meta_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 0.5 * cm))

    if spectrum_png_path and os.path.isfile(spectrum_png_path):
        img = Image(spectrum_png_path, width=16 * cm, height=8 * cm)
        story.append(img)
        story.append(Spacer(1, 0.5 * cm))

    if m.peaks:
        story.append(Paragraph("Peaks", styles["Heading2"]))
        headers = ["Freq (Hz)", "Mag (dB)", "Q", "Mode"]
        rows = [headers]
        for p in m.peaks:
            rows.append([
                f"{p.frequency:.1f}",
                f"{p.magnitude:.1f}",
                f"{p.quality:.0f}" if p.quality > 0 else "",
                p.mode_label or "",
            ])
        peaks_table = Table(
            rows, colWidths=[3.5 * cm, 3.5 * cm, 3.5 * cm, 7.5 * cm]
        )
        peaks_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("ALIGN", (3, 0), (3, -1), "LEFT"),
                ]
            )
        )
        story.append(peaks_table)

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    doc.build(story)


def _migrate_old_measurements() -> list[TapToneMeasurement]:
    """Read old per-file JSON measurements from the legacy directory."""
    result = []
    try:
        names = sorted(os.listdir(_OLD_DIR))
    except OSError:
        return result
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(_OLD_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            result.append(TapToneMeasurement.from_dict(d))
        except Exception as exc:
            print(f"Migration: skipping {name}: {exc}")
    return result
