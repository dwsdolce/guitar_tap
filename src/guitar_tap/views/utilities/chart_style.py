# @parity view/chart-style tests=test/chart-style
"""How the spectrum chart draws its lines and points: widths, dashes, opacities and point sizes.

Unlike the palette's colours these do not change with the colour scheme; they are pinned here so
every edition draws the chart the same way. The screen and the exported image each have their own
set. Mirrors Swift ``ChartStyle``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Lines:
    """One set of chart styles. Widths and dashes in points, opacities 0–1, point sizes as areas
    (pt²)."""

    spectrum_width: float
    overlay_width: float
    grid_width: float
    mode_boundary_width: float
    mode_boundary_dash: tuple[float, ...]
    mode_boundary_opacity: float
    peak_min_width: float
    peak_min_dash: tuple[float, ...]
    peak_min_opacity: float
    crosshair_width: float
    crosshair_dash: tuple[float, ...]
    leader_width: float
    leader_dash: tuple[float, ...]
    leader_opacity: float
    label_border_width: float
    dot_area: float
    highlighted_dot_area: float
    # The magnitude axis's tick spacing (dB), or None to choose it from the visible range.
    magnitude_stride: float | None


def diameter(area: float) -> float:
    """A round point's diameter for its area: 2·√(area/π)."""
    return 2 * math.sqrt(area / math.pi)


# The chart on screen.
SCREEN = Lines(
    spectrum_width=1, overlay_width=1.5, grid_width=1,
    mode_boundary_width=1.5, mode_boundary_dash=(5, 5), mode_boundary_opacity=0.3,
    peak_min_width=1.5, peak_min_dash=(8, 3), peak_min_opacity=0.7,
    crosshair_width=1, crosshair_dash=(4, 3),
    leader_width=1.5, leader_dash=(4, 3), leader_opacity=0.4,
    label_border_width=1.5,
    dot_area=40, highlighted_dot_area=120,
    magnitude_stride=None,
)

# The exported spectrum image (PNG, and the image in the PDF report).
EXPORT = Lines(
    spectrum_width=2, overlay_width=2, grid_width=1,
    mode_boundary_width=2, mode_boundary_dash=(8, 8), mode_boundary_opacity=0.3,
    peak_min_width=1.5, peak_min_dash=(8, 3), peak_min_opacity=0.7,
    crosshair_width=1, crosshair_dash=(4, 3),
    leader_width=2, leader_dash=(5, 4), leader_opacity=0.5,
    label_border_width=1.5,
    dot_area=200, highlighted_dot_area=200,
    magnitude_stride=20,
)


def pen(
    color, width: float, dash: tuple[float, ...] | None = None, opacity: float = 1.0,
    pixels_per_point: float | None = None,
):
    """A pyqtgraph pen of ``color`` (a QColor or (r, g, b)) at ``width`` points, its alpha scaled by
    ``opacity``, dashed by ``dash`` in points (Qt counts a dash in line widths).

    The pen is cosmetic — its width does not grow with the plot's zoom — and Qt draws a cosmetic
    width in device pixels, so the width is converted at ``pixels_per_point``: the screen's
    device pixel ratio by default, the image's scale for an export."""
    import pyqtgraph as pg
    from PySide6 import QtGui

    if pixels_per_point is None:
        app = QtGui.QGuiApplication.instance()
        pixels_per_point = app.devicePixelRatio() if app is not None else 1.0
    c = QtGui.QColor(color) if isinstance(color, QtGui.QColor) else QtGui.QColor(*color)
    c.setAlphaF(c.alphaF() * opacity)
    p = pg.mkPen(c, width=width * pixels_per_point)
    if dash:
        p.setDashPattern([d / width for d in dash])
    p.setCosmetic(True)
    return p
