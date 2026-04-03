"""
Measurement persistence layer.

Data model classes live in the models/ package:
  models.resonant_peak        → ResonantPeak
  models.spectrum_snapshot    → SpectrumSnapshot
  models.tap_tone_measurement → TapToneMeasurement

JSON format:
  - Single saved_measurements.json in the platform Application Support dir:
      macOS:   ~/Library/Application Support/GuitarTap/
      Windows: %APPDATA%\\GuitarTap\\
      Linux:   ~/.local/share/GuitarTap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - Format is cross-compatible with Swift GuitarTap .guitartap files
"""

from __future__ import annotations

import json
import os
from typing import Any

from models.tap_tone_measurement import TapToneMeasurement
from models.resonant_peak import ResonantPeak
from models.spectrum_snapshot import SpectrumSnapshot

__all__ = [
    "load_all_measurements",
    "save_all_measurements",
    "export_measurement_json",
    "import_measurements_from_json",
    "export_pdf",
    "measurements_file",
    "render_spectrum_image_for_pdf",
]

# Image rendering lives in exportable_spectrum_chart.py (mirrors ExportableSpectrumChart.swift).
from views.exportable_spectrum_chart import make_exportable_spectrum_view  # noqa: E402


# ── Persistence paths ─────────────────────────────────────────────────────────

def _app_data_dir() -> str:
    """Return the platform-appropriate Application Support directory.

    Uses QStandardPaths.AppDataLocation which resolves to:
      macOS:   ~/Library/Application Support/GuitarTap
      Windows: %APPDATA%\\GuitarTap
      Linux:   ~/.local/share/GuitarTap
    """
    from PyQt6.QtCore import QStandardPaths
    path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return path


def measurements_file() -> str:
    data_dir = _app_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "saved_measurements.json")


# ── Spectrum image rendering ───────────────────────────────────────────────────

def render_spectrum_image_for_pdf(m: TapToneMeasurement) -> str | None:
    """Render the composite spectrum PNG for a measurement and return the temp file path.

    Mirrors ``PDFReportGenerator.renderSpectrumImage(for:)`` in PDFReportGenerator.swift,
    which calls ``makeExportableSpectrumView(...)`` directly to produce the PNG.

    Returns the path to a temporary PNG file, or None if the measurement has no
    spectrum snapshot.  The caller is responsible for deleting the temp file.
    """
    import tempfile

    primary_snapshot = m.spectrum_snapshot or m.longitudinal_snapshot
    if primary_snapshot is None:
        return None

    snap = primary_snapshot

    # Build material spectra list — mirrors Swift's materialSpectra construction.
    material_spectra = []
    if m.longitudinal_snapshot:
        ls = m.longitudinal_snapshot
        material_spectra.append({
            "frequencies": ls.frequencies,
            "magnitudes": ls.magnitudes,
            "color": "blue",
            "label": "Longitudinal (L)",
        })
    if m.cross_snapshot:
        cs = m.cross_snapshot
        material_spectra.append({
            "frequencies": cs.frequencies,
            "magnitudes": cs.magnitudes,
            "color": "orange",
            "label": "Cross-grain (C)",
        })
    if m.flc_snapshot:
        fs = m.flc_snapshot
        material_spectra.append({
            "frequencies": fs.frequencies,
            "magnitudes": fs.magnitudes,
            "color": "purple",
            "label": "FLC",
        })

    # Mirror TapToneAnalyzer.visiblePeaks: filter by annotationVisibilityMode and selectedPeakIDs.
    all_peaks = m.peaks or []
    visibility_mode = (m.annotation_visibility_mode or "all").lower()
    selected_ids = set(m.selected_peak_ids or [p.id for p in all_peaks])
    if visibility_mode == "selected":
        visible_peaks = [p for p in all_peaks if p.id in selected_ids]
    elif visibility_mode == "none":
        visible_peaks = []
    else:
        visible_peaks = all_peaks

    measurement_type_str = snap.measurement_type or None

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()

    # Mirrors Swift: makeExportableSpectrumView called directly from renderSpectrumImage(for:).
    make_exportable_spectrum_view(
        frequencies=list(snap.frequencies),
        magnitudes=list(snap.magnitudes),
        min_freq=float(snap.min_freq),
        max_freq=float(snap.max_freq),
        min_db=float(snap.min_db),
        max_db=float(snap.max_db),
        peaks=visible_peaks,
        annotation_offsets=m.annotation_offsets or {},
        show_unknown_modes=snap.show_unknown_modes,
        measurement_type_str=measurement_type_str,
        selected_longitudinal_peak_id=m.selected_longitudinal_peak_id,
        selected_cross_peak_id=m.selected_cross_peak_id,
        selected_flc_peak_id=m.selected_flc_peak_id,
        mode_overrides=m.peak_mode_overrides or {},
        material_spectra=material_spectra if material_spectra else None,
        date_label=str(m.timestamp) if m.timestamp else "",
        chart_title=f"FFT Peaks — {m.tap_location or 'New'}",
        guitar_type_str=snap.guitar_type,
        output_path=tmp.name,
    )
    return tmp.name


# ── Persistence API ───────────────────────────────────────────────────────────

def load_all_measurements() -> list[TapToneMeasurement]:
    """Load all measurements from saved_measurements.json."""
    path = measurements_file()
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
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"Failed to save measurements: {exc}")


def export_measurement_json(m: TapToneMeasurement) -> str:
    """Return pretty-printed JSON for a single measurement.

    Mirrors Swift TapToneMeasurement.encode(to:) by injecting a resolved
    ``modeLabel`` into each peak entry.  For guitar measurements the label is
    determined by GuitarMode.classify_all (with any user override applied);
    for plate/brace it is the role name (Longitudinal, Cross-grain, FLC, Peak).
    """
    d = m.to_dict()

    # Resolve measurement type and guitar type from the snapshot — mirrors Swift:
    #   let resolvedMeasurementType = spectrumSnapshot?.measurementType
    #                               ?? longitudinalSnapshot?.measurementType
    snap = m.spectrum_snapshot or m.longitudinal_snapshot
    resolved_mt = (snap.measurement_type if snap else None) or m.measurement_type
    resolved_gt = (snap.guitar_type if snap else None) or m.guitar_type

    is_guitar = True
    if resolved_mt:
        try:
            from models import measurement_type as _mt_mod
            mt_obj = _mt_mod.MeasurementType(resolved_mt)
            is_guitar = mt_obj.is_guitar
        except Exception:
            pass

    # Build the mode-label map for peaks — mirrors Swift PeakExportCodingKeys loop.
    if is_guitar and m.peaks:
        try:
            from models.guitar_mode import GuitarMode
            from models.guitar_type import GuitarType
            gt_enum = GuitarType(resolved_gt) if resolved_gt else GuitarType.CLASSICAL
            mode_map = GuitarMode.classify_all(m.peaks, gt_enum)
        except Exception:
            mode_map = {}

        overrides = m.peak_mode_overrides or {}
        for i, peak_d in enumerate(d["peaks"]):
            peak = m.peaks[i]
            override = overrides.get(peak.id)
            if override:
                label = override
            else:
                mode = mode_map.get(peak.id)
                label = mode.display_name if mode else "Unknown"
            peak_d["modeLabel"] = label
    else:
        # Plate / brace: label by which selected-peak-id matches.
        for i, peak_d in enumerate(d["peaks"]):
            peak = m.peaks[i]
            if peak.id == m.selected_longitudinal_peak_id:
                label = "Longitudinal"
            elif peak.id == m.selected_cross_peak_id:
                label = "Cross-grain"
            elif peak.id == m.selected_flc_peak_id:
                label = "FLC"
            else:
                label = "Peak"
            peak_d["modeLabel"] = label

    return json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True)


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

    meta: list[list[Any]] = [
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
        rows: list[list[str]] = [headers]
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


