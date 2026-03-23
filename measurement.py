"""
    Measurement save/load (JSON) and PDF report export.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class PeakEntry:
    freq: float
    mag: float
    q: float
    show: str
    mode: str


@dataclass
class AnnotationEntry:
    freq: float
    mag: float
    mode_str: str
    xytext: list[float]  # [x, y]


@dataclass
class PeakMeasurement:
    timestamp: str
    guitar_type: str
    f_min: int
    f_max: int
    threshold: int
    ring_out: float | None
    notes: str
    peaks: list[PeakEntry] = field(default_factory=list)
    annotations: list[AnnotationEntry] = field(default_factory=list)

    @staticmethod
    def create(
        guitar_type: str,
        f_min: int,
        f_max: int,
        threshold: int,
        ring_out: float | None,
        notes: str,
        peaks: list[PeakEntry],
        annotations: list[AnnotationEntry],
    ) -> "PeakMeasurement":
        return PeakMeasurement(
            timestamp=datetime.now().isoformat(),
            guitar_type=guitar_type,
            f_min=f_min,
            f_max=f_max,
            threshold=threshold,
            ring_out=ring_out,
            notes=notes,
            peaks=peaks,
            annotations=annotations,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PeakMeasurement":
        peaks = [PeakEntry(**p) for p in d.get("peaks", [])]
        annotations = [
            AnnotationEntry(
                freq=a["freq"],
                mag=a["mag"],
                mode_str=a.get("mode_str", ""),  # "text" key in older files is ignored
                xytext=list(a["xytext"]),
            )
            for a in d.get("annotations", [])
        ]
        return PeakMeasurement(
            timestamp=d["timestamp"],
            guitar_type=d.get("guitar_type", "Classical"),
            f_min=d.get("f_min", 75),
            f_max=d.get("f_max", 350),
            threshold=d.get("threshold", 50),
            ring_out=d.get("ring_out"),
            notes=d.get("notes", ""),
            peaks=peaks,
            annotations=annotations,
        )

    def display_name(self) -> str:
        """Short name for UI display."""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.timestamp


_MEASUREMENTS_DIR = os.path.expanduser("~/Documents/GuitarTap/measurements")


def measurements_dir() -> str:
    os.makedirs(_MEASUREMENTS_DIR, exist_ok=True)
    return _MEASUREMENTS_DIR


def save_measurement(m: PeakMeasurement, directory: str | None = None) -> str:
    """Save measurement as JSON. Returns the file path."""
    dir_ = directory or measurements_dir()
    os.makedirs(dir_, exist_ok=True)
    try:
        dt = datetime.fromisoformat(m.timestamp)
        filename = dt.strftime("%Y%m%d_%H%M%S") + ".json"
    except ValueError:
        filename = "measurement.json"
    path = os.path.join(dir_, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m.to_dict(), f, indent=2)
    return path


def load_measurement(path: str) -> PeakMeasurement:
    """Load measurement from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return PeakMeasurement.from_dict(d)


def list_measurements(directory: str | None = None) -> list[str]:
    """Return sorted list of .json measurement file paths, newest first."""
    dir_ = directory or measurements_dir()
    if not os.path.isdir(dir_):
        return []
    paths = [
        os.path.join(dir_, name)
        for name in os.listdir(dir_)
        if name.endswith(".json")
    ]
    return sorted(paths, reverse=True)


def export_pdf(
    m: PeakMeasurement, spectrum_png_path: str | None, output_path: str
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
        ["Guitar Type", m.guitar_type],
        ["Freq Range", f"{m.f_min} \u2013 {m.f_max} Hz"],
        ["Threshold", str(m.threshold)],
    ]
    if m.ring_out is not None:
        meta.append(["Ring-out", f"{m.ring_out:.2f} s"])
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
            rows.append(
                [
                    f"{p.freq:.1f}",
                    f"{p.mag:.1f}",
                    f"{p.q:.0f}" if p.q > 0 else "",
                    p.mode,
                ]
            )
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
