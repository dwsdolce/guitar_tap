# @parity none — pyqtgraph keeps a plot item per overlaid curve, holding the points it draws; Swift's chart and the web's canvas trim each curve as they draw it and keep no curve to inspect.
"""The chart's overlaid curves — a comparison's measurements, here — hold only the points drawn for the
visible range (``drawn_indices``: those inside it and one beyond each edge), as the spectrum line does,
and are re-trimmed when the range changes; the crosshair reads their whole spectra. Drives the real main
window, importing the comparison through Saved Measurements as a user does."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from guitar_tap.models import display_range as dr  # noqa: E402
from test_export_e2e import _import, edges, window  # noqa: F401  (pytest fixtures)


def _drawn(canvas) -> list[tuple[int, int]]:
    """For each overlaid curve: the points it holds, and the points drawn_indices gives for the view."""
    x0, x1 = (float(v) for v in canvas.getPlotItem().vb.viewRange()[0])
    out = []
    for curve, (freqs, _mags) in zip(canvas._overlay_curves, canvas._overlay_spectra):
        lo, hi = dr.drawn_indices(freqs, x0, x1)
        out.append((len(curve.getData()[0]), hi - lo))
    return out


def test_overlaid_curves_hold_only_the_drawn_points(qtbot, window, edges):  # noqa: F811
    _import(qtbot, window, edges, "18-compare-1792944381.guitartap")
    canvas = window.fft_canvas
    qtbot.waitUntil(lambda: len(canvas._overlay_curves) == 18, timeout=10_000)

    for held, drawn in _drawn(canvas):
        assert held == drawn
    # Each whole spectrum is kept beside its curve, for the crosshair.
    full = [len(freqs) for freqs, _mags in canvas._overlay_spectra]
    assert all(held < n for (held, _), n in zip(_drawn(canvas), full))

    # A range change re-trims every curve.
    canvas.setXRange(150.0, 200.0, padding=0)
    qtbot.waitUntil(lambda: all(h == d for h, d in _drawn(canvas)), timeout=5_000)
    assert [len(freqs) for freqs, _mags in canvas._overlay_spectra] == full
