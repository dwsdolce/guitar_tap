"""
    Custom toolbar for the FFT plot. Replaces the matplotlib NavigationToolbar
    with a simple QToolBar providing Home, Save, and Help actions.
"""

import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6 import QtWidgets
import fft_canvas as fft_c


class FftToolbar(QtWidgets.QToolBar):
    """Toolbar providing Home, Save, and Help actions for the FFT plot."""

    def __init__(self, canvas: fft_c.FftCanvas, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.canvas = canvas

        home_action = self.addAction("Home")
        home_action.setToolTip("Reset to original view (Ctrl+H)")
        home_action.triggered.connect(self.home)

        self.addSeparator()

        save_action = self.addAction("Save")
        save_action.setToolTip("Save the figure to an image file")
        save_action.triggered.connect(self.save)

        self.addSeparator()

        help_action = self.addAction("Help")
        help_action.setToolTip("Show navigation shortcuts")
        help_action.triggered.connect(self.display_help)

    def home(self) -> None:
        """Reset view to the full frequency range and full dB range."""
        vb = self.canvas.getViewBox()
        vb.setXRange(self.canvas.fmin, self.canvas.fmax, padding=0)
        vb.setYRange(-100, 0, padding=0)

    def save(self) -> None:
        """Export the plot to an image file."""
        exporter = pg.exporters.ImageExporter(self.canvas.getPlotItem())
        exporter.export()

    def display_help(self) -> None:
        """Show navigation help dialog."""
        html = (
            "<style>td { padding: 2px 8px }</style>"
            "<table>"
            "<thead><tr><td><b>Action</b></td><td><b>Description</b></td></tr></thead>"
            "<tbody>"
            "<tr><td>Left-drag</td><td>Pan the plot</td></tr>"
            "<tr><td>Right-drag / Scroll</td><td>Zoom</td></tr>"
            "<tr><td>Click peak point</td><td>Select peak</td></tr>"
            "<tr><td>Drag annotation</td><td>Reposition annotation label</td></tr>"
            "<tr><td>Home button</td><td>Reset to original view</td></tr>"
            "<tr><td>Save button</td><td>Export plot to image</td></tr>"
            "</tbody></table>"
        )
        QtWidgets.QMessageBox.information(None, "Help", html)

    def update(self) -> None:
        """Called when fmin/fmax changes — no action needed."""
        pass
