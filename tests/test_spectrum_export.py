# @parity test/spectrum-export
"""The exported spectrum image's size: every Export Spectrum PNG is 2928 pixels wide — 2376 high with the
peak summary, 2138 without — and states 144 pixels per inch, so a viewer that honours the figure shows it at
1464 points wide. Mirrors Swift SpectrumExportTests and the web's spectrum-export.test.ts (the same cases).
"""

from __future__ import annotations

import os
import struct
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets

from guitar_tap.views import tap_analysis_results_view as reports

TESTS = os.path.dirname(__file__)

# Each fixture and the image it exports: pixels wide and high, and pixels per inch.
CASES = [
    ("plate-umik-1-3-tap-swift-ipad-1784314709", 2928, 2376, 144),
    ("dws-2024-umik-1-swift-mac-1785359434", 2928, 2376, 144),
    ("5-guitar-comparison-1776708138", 2928, 2138, 144),
]


def png_size_and_ppi(png: bytes) -> tuple[int, int, int | None]:
    """A PNG's pixels wide and high (IHDR) and the pixels per inch it states (pHYs, per metre)."""
    width, height = struct.unpack(">II", png[16:24])
    ppi = None
    at = 8
    while at < len(png):
        (length,) = struct.unpack(">I", png[at:at + 4])
        if png[at + 4:at + 8] == b"pHYs" and png[at + 16] == 1:
            ppi = round(struct.unpack(">I", png[at + 8:at + 12])[0] * 0.0254)
        at += 12 + length
    return width, height, ppi


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize("fixture,width,height,ppi", CASES)
def test_export_size_and_pixels_per_inch(fixture, width, height, ppi):
    with open(os.path.join(TESTS, fixture + ".guitartap"), "rb") as f:
        measurement = reports.measurements_from_json(f.read())[0]
    # As the measurement list's Export Spectrum: a comparison through its own renderer.
    png = (reports.render_spectrum_image_for_comparison(measurement) if measurement.is_comparison
           else reports.render_spectrum_image_for_measurement(measurement))
    assert png_size_and_ppi(png) == (width, height, ppi)
