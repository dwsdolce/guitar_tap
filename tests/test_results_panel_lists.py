# @parity none — Qt widgets keep the visibility they were last given; SwiftUI and React choose the Results list from the measurement type each time they draw.
"""The Results panel shows a guitar's peak list only for a guitar: a comparison that ends when the
measurement type changes to a plate leaves the plate's list, not the empty guitar list over it. Drives the
real main window, importing the comparison through Saved Measurements as a user does."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from test_export_e2e import _import, edges, window  # noqa: F401  (pytest fixtures)


def test_comparison_ending_in_a_plate_shows_the_plate_list(qtbot, window, edges):  # noqa: F811
    _import(qtbot, window, edges, "5-guitar-comparison-1776708138.guitartap")
    qtbot.waitUntil(lambda: window.fft_canvas.analyzer.is_saved_measurement_comparison, timeout=10_000)

    # Settings → Plate, as a user changes the type: the layout follows the type, then a new tap
    # sequence starts, which ends the comparison.
    TDS.set_measurement_type(MeasurementType.PLATE)
    window._on_measurement_type_changed("", measurement_changed=True)
    qtbot.waitUntil(lambda: not window.fft_canvas.analyzer.is_comparing, timeout=10_000)

    assert window.peak_widget.isHidden()
    assert not window._material_scroll.isHidden()
