# @parity view/palette tests=test/analysis-quality
"""The app's fixed colours: each has one light value and one dark value, chosen by the background.

They are pinned rather than taken from a platform palette, so every edition shows the same colours on
every OS. The colour only tells values apart; the exact shade does not matter, but it must be the same
everywhere. A PDF is printed on white, so it uses the light values. Mirrors Swift ``Palette``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtGui, QtWidgets


@dataclass(frozen=True)
class ColorPair:
    """A colour's two values, as "#RRGGBB"."""

    light: str
    dark: str

    def on(self, widget: QtWidgets.QWidget) -> str:
        """The value for the background ``widget`` is drawn on: dark when its window is dark."""
        window = widget.palette().color(QtGui.QPalette.ColorRole.Window)
        return self.dark if window.lightness() < 128 else self.light


GRAY = ColorPair("#8E8E93", "#8E8E93")
ORANGE = ColorPair("#FF9500", "#FF9F0A")
YELLOW = ColorPair("#FFCC00", "#FFD60A")
GREEN = ColorPair("#34C759", "#30D158")
BLUE = ColorPair("#007AFF", "#0A84FF")
RED = ColorPair("#FF3B30", "#FF453A")
