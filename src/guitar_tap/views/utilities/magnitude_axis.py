"""The magnitude (dB) axis of the spectrum chart, on screen and in the exported image.

pyqtgraph drops a tick label that reaches past the area its axis covers, and with the grid on that
area ends at the plot's top and bottom — so the labels at the ends of the range (0 and -100 dB)
were never drawn. Swift's AxisMarks label every tick, the ends included. This axis covers half a
label more at each end, so the end labels are drawn too.
"""

from __future__ import annotations

import pyqtgraph as pg


class MagnitudeAxis(pg.AxisItem):
    """A left axis whose end tick labels are drawn, as Swift's are."""

    # Half a tick label's height, in scene pixels: the end labels are centred on the plot's edges.
    END_LABEL_ROOM = 12

    def boundingRect(self):  # noqa: N802 (Qt API)
        return super().boundingRect().adjusted(0, -self.END_LABEL_ROOM, 0, self.END_LABEL_ROOM)
