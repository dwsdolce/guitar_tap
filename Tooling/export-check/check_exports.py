#!/usr/bin/env python3
"""
The export checker — one judge for the spectrum images and PDF reports of all three editions.

Each edition's export tests drive its app through Import and both export paths (the main window and Saved
Measurements) and lay the files out as

    <folder>/<case>/<main|saved>/<file>.png|.pdf      (and optionally <folder>/manifest.json)

This script measures the parts of each file — not its pixels — and compares them with Swift's, within
tolerances:

  PNG  the image size; the header title and its rows; the chart title; the plot's top and bottom; the
       frequency labels, each centred on its grid line and none past the plot's edge; the x-axis title;
       the summary below the chart; the legend and its entries.
  PDF  every text line's position and text (dates, versions and the platform normalised); the chart
       image's rectangle on each page.

    check_exports.py mint  <swift-folder>  [-o expected.json]     record Swift's measurements
    check_exports.py check <folder>        [-e expected.json]     judge an edition's exports
    check_exports.py show  <file.png|file.pdf>                    print one file's measurements

The source of truth is the hub (tooling/export-check/); each edition holds a byte-identical copy.
Requires Pillow, NumPy and pdfminer.six.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent

# ── PNG ────────────────────────────────────────────────────────────────────────────────────────────


def _runs(mask) -> list[tuple[int, int]]:
    """Index ranges (first, last) where ``mask`` is true."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def measure_png(path: Path) -> dict:
    """The parts of an exported spectrum image, in points from the top-left corner."""
    im = Image.open(path)
    dpi = im.info.get("dpi", (144, 144))[0] or 144
    scale = round(dpi) / 72.0
    page = Image.new("RGBA", im.size, "white")
    page.alpha_composite(im.convert("RGBA"))          # a transparent margin reads as white
    rgb = np.asarray(page.convert("RGB")).astype(int)
    height, width, _ = rgb.shape
    darkest = rgb.min(axis=2)
    spread = rgb.max(axis=2) - darkest                  # 0 for greys, large for colours

    def pt(px: float) -> float:
        return round(px / scale, 1)

    # Long horizontal lines: the plot's grid lines. Its first and last are the plot's top and bottom.
    lines = _runs((darkest < 245).sum(axis=1) > 0.5 * width)
    if len(lines) < 2:
        raise ValueError(f"{path.name}: no plot found")
    plot_top, plot_bottom = lines[0][0], lines[-1][1]

    # Text and marks: rows holding dark pixels.
    bands = _runs((darkest < 160).sum(axis=1) > 0)
    above = [b for b in bands if b[1] < plot_top - 4]
    below = [b for b in bands if b[0] > plot_bottom + 4]
    if len(above) < 2 or len(below) < 3:
        raise ValueError(f"{path.name}: header, title or axis not found")
    header_title, chart_title = above[0], above[-1]
    header_rows = above[1:-1]
    # Below the plot, top to bottom: the frequency labels, the axis title, any summary (a measurement's
    # detected peaks or a material's properties), and the legend last.
    tick_labels, axis_title, legend = below[0], below[1], below[-1]
    summary_rows = below[2:-1]

    # Plot's left and right: its border's vertical lines — the first and last narrow columns marked over the
    # plot's whole height. (Not the top grid line's extent: the magnitude axis's "0" label sits on that line.)
    full = (darkest[plot_top + 2:plot_bottom - 1] < 245).sum(axis=0) >= 0.98 * (plot_bottom - plot_top - 3)
    borders = [r for r in _runs(full) if r[1] - r[0] <= 3 * scale]
    if len(borders) < 2:
        raise ValueError(f"{path.name}: plot border not found")
    plot_left, plot_right = borders[0][0], borders[-1][1]

    # Vertical grid lines: narrow columns marked over most of the plot's height. A mode band's tint over a
    # grid line changes its colour, not its coverage, and the tint itself is wide, so it is left out; a peak
    # annotation's box hides part of a line; a dashed band edge covers only half.
    inside = slice(plot_top + 2, plot_bottom - 1)
    marked = (darkest[inside] < 250).sum(axis=0) >= 0.75 * (plot_bottom - plot_top - 3)
    # The plot's left and right edges stand for grid lines too: a label at either end sits on one.
    grid_x = [plot_left, plot_right] + [(a + b) / 2 for a, b in _runs(marked)
                                        if b - a <= 2 * scale and plot_left + 2 < a and b < plot_right - 2]

    # Frequency labels: groups of dark columns in the tick-label band, split at gaps wider than a glyph gap.
    label_cols = (darkest[tick_labels[0]:tick_labels[1] + 1] < 160).any(axis=0)
    labels, gap = [], 8 * scale
    for a, b in _runs(label_cols):
        if labels and a - labels[-1][1] <= gap:
            labels[-1] = (labels[-1][0], b)
        else:
            labels.append((a, b))
    offsets = []
    # A label reaching past the plot's left or right edge should have been left out.
    overhanging = sum(1 for a, b in labels if a < plot_left - scale or b > plot_right + scale)
    for a, b in labels:
        centre = (a + b) / 2
        if plot_left - 4 * scale <= centre <= plot_right + 4 * scale:
            offsets.append(min(abs(centre - g) for g in grid_x))

    # Legend entries: runs of coloured columns (each entry's line or dot) in the legend band.
    legend_rows = slice(max(legend[0] - 4, 0), legend[1] + 5)
    coloured = ((spread[legend_rows] > 60) & (darkest[legend_rows] < 230)).any(axis=0)
    entries = len([r for r in _runs(coloured) if r[1] - r[0] >= 3 * scale])

    return {
        "kind": "png",
        "size": [pt(width), pt(height)],
        "header_title": [pt(header_title[0]), pt(header_title[1])],
        "header_rows": [[pt(a), pt(b)] for a, b in header_rows],
        "chart_title": [pt(chart_title[0]), pt(chart_title[1])],
        "plot": [pt(plot_left), pt(plot_top), pt(plot_right), pt(plot_bottom)],
        "tick_labels": [pt(tick_labels[0]), pt(tick_labels[1])],
        "axis_title": [pt(axis_title[0]), pt(axis_title[1])],
        "legend": [pt(legend[0]), pt(legend[1])],
        "legend_entries": entries,
        "summary_rows": [[pt(a), pt(b)] for a, b in summary_rows],
        "label_offset_max": pt(max(offsets)) if offsets else None,
        "labels": len(offsets),
        "labels_past_edge": overhanging,
    }


# ── PDF ────────────────────────────────────────────────────────────────────────────────────────────

_DATE = re.compile(r"\b[A-Z][a-z]{2} \d{1,2}, \d{4}(,| at)? \d{1,2}:\d{2}\s?[AP]M\b")
_VERSION = re.compile(r"\bv?\d+\.\d+\.\d+ \(\d+\)")
_PLATFORM = re.compile(r"\b(macOS|iPadOS|iOS|Web|Windows|Linux)\b")


def _normalise(text: str) -> str:
    """A line's text as compared. Dates are kept: a page made from a measurement shows the measurement's
    date, the same in every edition (the drivers run the apps in UTC). Only the "Generated by" footer —
    the edition, its version and the time of export — and any version or platform name are set aside."""
    # Compatibility form, so a ligature (ﬁ) reads as its letters (fi), as the editions' report tests do.
    text = " ".join(unicodedata.normalize("NFKC", text).split())
    if text.startswith("Generated by"):
        return "<generated>"
    text = _VERSION.sub("<version>", text)
    return _PLATFORM.sub("<platform>", text)


def measure_pdf(path: Path) -> dict:
    """Each page's text lines (baseline from the top, normalised text) and image rectangles, in points.

    Every character on the page is collected — text drawn inside a form object too — and grouped into lines
    by its baseline (from its own text matrix, so exact), each line left to right, with a space wherever the
    gap between characters is wider than a word gap. A line sits at the baseline of its largest characters.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTImage

    pages = []
    for page in extract_pages(str(path)):
        top = page.height
        chars, images = [], []

        def walk(item):
            if isinstance(item, LTChar):
                chars.append((round(top - item.matrix[5], 1), item.matrix[4], item.x1, item.size, item.get_text(),
                              _style(item.fontname), _colour(item.graphicstate.ncolor)))
            elif isinstance(item, LTImage):
                images.append([round(item.x0, 1), round(top - item.y1, 1),
                               round(item.width, 1), round(item.height, 1)])
            elif hasattr(item, "__iter__"):
                for child in item:
                    walk(child)

        walk(page)
        rows: list[list[tuple]] = []
        for ch in sorted(chars):
            if rows and abs(rows[-1][0][0] - ch[0]) < 3:
                rows[-1].append(ch)
            else:
                rows.append([ch])
        lines = []
        for row in rows:
            row.sort(key=lambda c: c[1])
            text, previous, runs = "", None, []
            for baseline, x, x1, size, glyph, style, colour in row:
                if previous is not None and x - previous > 0.2 * size:
                    text += " "
                text += glyph
                previous = x1
                if glyph.strip():
                    if runs and runs[-1][0] == style and runs[-1][1] == colour:
                        continue
                    runs.append([style, colour])
            baseline = max(row, key=lambda c: c[3])[0]
            lines.append([baseline, _normalise(text), runs])
        pages.append({"lines": lines, "images": sorted(images, key=lambda r: (r[1], r[0]))})
    return {"kind": "pdf", "pages": pages}


def _style(fontname: str) -> str:
    """A font's weight and slant: "bold", "italic", "bold-italic" or "regular"."""
    name = fontname.split("+")[-1].lower()
    bold = "bold" in name or "semibold" in name
    italic = "oblique" in name or "italic" in name
    return "bold-italic" if bold and italic else "bold" if bold else "italic" if italic else "regular"


def _colour(value) -> list[float]:
    """A fill colour as RGB, 0–1 (a grey level becomes three equal values)."""
    if value is None:
        return [0.0, 0.0, 0.0]
    if isinstance(value, (int, float)):
        return [round(float(value), 3)] * 3
    v = [float(c) for c in value]
    if len(v) == 1:
        v = v * 3
    if len(v) == 4:  # CMYK
        c, m, y, k = v
        v = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    return [round(c, 3) for c in v[:3]]


def measure(path: Path) -> dict:
    return measure_png(path) if path.suffix.lower() == ".png" else measure_pdf(path)


# ── Comparing ──────────────────────────────────────────────────────────────────────────────────────


def _compare_png(got: dict, want: dict, tol: dict) -> list[str]:
    problems = []

    def near(name, a, b, t):
        if isinstance(a, list):
            for i, (x, y) in enumerate(zip(a, b)):
                if abs(x - y) > t:
                    problems.append(f"{name}[{i}] {x} (Swift {y}, ±{t})")
        elif abs(a - b) > t:
            problems.append(f"{name} {a} (Swift {b}, ±{t})")

    near("size", got["size"], want["size"], tol["size"])
    for part in ("header_title", "chart_title", "plot", "tick_labels", "axis_title", "legend"):
        near(part, got[part], want[part], tol["position"])
    for rows in ("header_rows", "summary_rows"):
        if len(got[rows]) != len(want[rows]):
            problems.append(f"{rows} {len(got[rows])} (Swift {len(want[rows])})")
        else:
            for i, (a, b) in enumerate(zip(got[rows], want[rows])):
                near(f"{rows}[{i}]", a, b, tol["position"])
    if got["legend_entries"] != want["legend_entries"]:
        problems.append(f"legend entries {got['legend_entries']} (Swift {want['legend_entries']})")
    if got["labels"] != want["labels"]:
        problems.append(f"frequency labels {got['labels']} (Swift {want['labels']})")
    if got.get("labels_past_edge"):
        problems.append(f"{got['labels_past_edge']} frequency label(s) reach past the plot's edge")
    if got["label_offset_max"] is not None and got["label_offset_max"] > tol["label_centring"]:
        problems.append(f"a frequency label is {got['label_offset_max']} pt off its grid line "
                        f"(±{tol['label_centring']})")
    return problems


def _compare_pdf(got: dict, want: dict, tol: dict) -> list[str]:
    problems = []
    if len(got["pages"]) != len(want["pages"]):
        return [f"pages {len(got['pages'])} (Swift {len(want['pages'])})"]
    for p, (g, w) in enumerate(zip(got["pages"], want["pages"])):
        if [line[1] for line in g["lines"]] != [line[1] for line in w["lines"]]:
            missing = [line[1] for line in w["lines"] if line[1] not in [x[1] for x in g["lines"]]]
            extra = [line[1] for line in g["lines"] if line[1] not in [x[1] for x in w["lines"]]]
            problems.append(f"page {p + 1} text differs — missing {missing[:4]}, extra {extra[:4]}")
        else:
            def merged(runs):
                """Neighbouring runs of one weight whose colours agree within the tolerance, as one."""
                out = []
                for style, colour in runs:
                    if out and out[-1][0] == style and all(
                            abs(a - b) <= tol["pdf_colour"] for a, b in zip(out[-1][1], colour)):
                        continue
                    out.append([style, colour])
                return out

            for (gy, text, g_runs), (wy, _, w_runs) in zip(g["lines"], w["lines"]):
                g_runs, w_runs = merged(g_runs), merged(w_runs)
                if abs(gy - wy) > tol["pdf_line"]:
                    problems.append(f"page {p + 1} '{text[:40]}' at {gy} (Swift {wy}, ±{tol['pdf_line']})")
                # Typography: the line's runs of weight and colour, in order.
                if [r[0] for r in g_runs] != [r[0] for r in w_runs]:
                    problems.append(f"page {p + 1} '{text[:40]}' set {[r[0] for r in g_runs]} "
                                    f"(Swift {[r[0] for r in w_runs]})")
                elif any(abs(a - b) > tol["pdf_colour"]
                         for gr, wr in zip(g_runs, w_runs) for a, b in zip(gr[1], wr[1])):
                    problems.append(f"page {p + 1} '{text[:40]}' coloured {[r[1] for r in g_runs]} "
                                    f"(Swift {[r[1] for r in w_runs]}, ±{tol['pdf_colour']})")
        if len(g["images"]) != len(w["images"]):
            problems.append(f"page {p + 1} images {len(g['images'])} (Swift {len(w['images'])})")
        else:
            for gi, wi in zip(g["images"], w["images"]):
                if any(abs(a - b) > tol["pdf_image"] for a, b in zip(gi, wi)):
                    problems.append(f"page {p + 1} image at {gi} (Swift {wi}, ±{tol['pdf_image']})")
    return problems


def _key(entry: dict) -> str:
    return f"{entry['case']}/{entry['path']}/{entry['format']}"


def _manifest(folder: Path) -> list[dict]:
    """The folder's exports: from its manifest.json, or else found by their place, <case>/<path>/<file>."""
    manifest = folder / "manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text())["files"]
    return [{"case": f.parent.parent.name, "path": f.parent.name, "format": f.suffix.lstrip("."),
             "file": str(f.relative_to(folder))}
            for f in sorted(folder.glob("*/*/*")) if f.suffix.lower() in (".png", ".pdf")]


def mint(folder: Path, out: Path) -> None:
    expected = {"about": "Swift's exports, measured by check_exports.py mint. Regenerate when Swift's exports "
                         "change on purpose.",
                "tolerances": json.loads((HERE / "tolerances.json").read_text()),
                "files": {}}
    for entry in _manifest(folder):
        measured = measure(folder / entry["file"])
        measured["name"] = Path(entry["file"]).name
        expected["files"][_key(entry)] = measured
    out.write_text(json.dumps(expected, indent=1) + "\n")
    print(f"{len(expected['files'])} Swift exports measured → {out}")


def check(folder: Path, expected_path: Path) -> int:
    expected = json.loads(expected_path.read_text())
    tol = expected["tolerances"]
    seen, failures = set(), 0
    for entry in _manifest(folder):
        key = _key(entry)
        seen.add(key)
        want = expected["files"].get(key)
        if want is None:
            print(f"?    {key}: no Swift measurement")
            failures += 1
            continue
        try:
            got = measure(folder / entry["file"])
            problems = (_compare_png if got["kind"] == "png" else _compare_pdf)(got, want, tol)
            name = Path(entry["file"]).name
            if want.get("name") and name != want["name"]:
                problems.append(f"named {name} (Swift {want['name']})")
        except Exception as exc:  # noqa: BLE001 — a file that cannot be measured is a failure
            problems = [f"cannot measure: {exc}"]
        print(f"{'ok  ' if not problems else 'FAIL'} {key}")
        for p in problems:
            print(f"       {p}")
        failures += bool(problems)
    for key in sorted(set(expected["files"]) - seen):
        print(f"MISS {key}: not exported")
        failures += 1
    print(f"{len(seen)} exports checked, {failures} failing")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("mint")
    m.add_argument("folder", type=Path)
    m.add_argument("-o", "--out", type=Path, default=HERE / "expected.json")
    c = sub.add_parser("check")
    c.add_argument("folder", type=Path)
    c.add_argument("-e", "--expected", type=Path, default=HERE / "expected.json")
    s = sub.add_parser("show")
    s.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.command == "mint":
        mint(args.folder, args.out)
        return 0
    if args.command == "check":
        return check(args.folder, args.expected)
    print(json.dumps(measure(args.file), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
