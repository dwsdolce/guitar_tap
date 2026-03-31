"""
Measurement persistence layer.

Data model classes live in the models/ package:
  models.resonant_peak        → ResonantPeak
  models.spectrum_snapshot    → SpectrumSnapshot
  models.tap_tone_measurement → TapToneMeasurement

JSON format:
  - Single saved_measurements.json in ~/Documents/GuitarTap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - Format is cross-compatible with Swift GuitarTap .guitartap files

Old per-file format (~/Documents/GuitarTap/measurements/*.json) is
automatically migrated on first run.
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
]


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
