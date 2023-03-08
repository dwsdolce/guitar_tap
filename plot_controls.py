"""
    Custom widget containing the plot controls for the FFT and the FFT plot.
"""
from PyQt6 import QtWidgets, QtCore
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib import pyplot as plt
import re

import threshold_slider as TS
import fft_canvas as fft_c

class MyNavigationToolbar(NavigationToolbar):
    """ Overload the Navigation Toolbar class so that the home button behavior
        is modified to set the ylimits to -100. This takes care of any pan or
        zoom that was done before the home button was pressed.
    """
    extended_toolitems=""
    def __init__ (self, canvas, parent):

        # Add the Help tool
        self.toolitems.insert(
            # Add 'customize' action after 'subplots'
            [name for name, *_ in self.toolitems].index("Save") + 1,
            ("Help", "List information on support for navigation bar",
            "help", "display_help"))

        # Remove two of the tools since they are confusing
        self.extended_toolitems = [item for item in self.toolitems if item[0] != "Customize" and item[0] != "Subplots"]
        self.toolitems = self.extended_toolitems.copy()

        # Add in the grid and grid_minor keybindings since they are helpful.
        self.extended_toolitems = [item for item in self.extended_toolitems if item[0] != None and item[0] != "Help"]
        self.extended_toolitems.append(('grid', 'Toggle major grids', '', ''))
        self.extended_toolitems.append(('grid_minor', 'Toggle major and minor grids', '', ''))
        extended_toolitems = self.extended_toolitems.sort(key=lambda x: x[0])
        super().__init__(canvas, parent)

    def format_shortcut(self, key_sequence):
        """
        Convert a shortcut string from the notation used in rc config to the
        standard notation for displaying shortcuts, e.g. 'ctrl+a' -> 'Ctrl+A'.
        """
        return (key_sequence if len(key_sequence) == 1 else
                re.sub(r"\+[A-Z]", r"+Shift\g<0>", key_sequence).title())

    def _format_tool_keymap(self, name):
        #print(f"_format_tool_keymap: {name}")
        keymap = f"keymap.{name}"
        if keymap in plt.rcParams:
            keys = plt.rcParams[keymap]
        else:
            keys = ""
        return ", ".join(self.format_shortcut(key) for key in keys)

    def _get_help_entries(self):
        
        return [(name, self._format_tool_keymap(name.lower()), description)
                for name, description, _, _ in self.extended_toolitems
                if name]

    def _get_help_html(self):
        fmt = "<tr><td>{}</td><td>{}</td><td>{}</td></tr>"
        rows = [fmt.format("<b>Action</b>", "<b>Shortcuts</b>", "<b>Description</b>")]
        rows += [fmt.format(*row) for row in self._get_help_entries()]
        return ("<style>td {padding: 0px 4px}</style>"
                "<table><thead>" + rows[0] + "</thead>"
                "<tbody>".join(rows[1:]) + "</tbody></table>")

    def display_help(self):
        QtWidgets.QMessageBox.information(None, "Help", self._get_help_html())

    def home(self, *args):
        self.canvas.fft_axes.set_ylim(-100,0)
        super().home()

class PlotControls(QtWidgets.QWidget):
    """ Create a custom widget with the threshold slider, the FFT canvas, and
        the navigation controls.
    """

    def __init__(self, threshold, f_range, fft_settings):
        super().__init__()

        # ==========================================================
        # Create the plot plus controls
        # ==========================================================
        # Create layout with threshold slider and fft canvas
        plot_layout = QtWidgets.QVBoxLayout()

        # Add the slider
        self.threshold_slider = TS.ThresholdSlider(QtCore.Qt.Orientation.Horizontal)
        self.threshold_slider.setToolTip('Shows the magnitude of the FFT of the signal.\n'
            'Move the red slider to define threshold used for finding peaks.')
        plot_layout.addWidget(self.threshold_slider)

        self.threshold_slider.valueChanged.connect(self.threshold_changed)

        # Add an fft Canvas
        self.fft_canvas = fft_c.DrawFft(
            fft_settings['window_length'], fft_settings['sampling_rate'], f_range, threshold)
        self.fft_canvas.setMinimumSize(600, 400)
        self.toolbar = MyNavigationToolbar(self.fft_canvas, self)

        self.fft_canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.fft_canvas.setFocus()

        plot_layout.addWidget(self.fft_canvas)
        plot_layout.addWidget(self.toolbar)

        # Connect signals
        self.fft_canvas.ampChanged.connect(self.threshold_slider.set_amplitude)

        self.setLayout(plot_layout)

    def threshold_changed(self):
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """

        threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(threshold)

    def fmin_changed(self):
        """ Change the minimum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmin(self.sender().value())

    def fmax_changed(self):
        """ Change the maximum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmax(self.sender().value())
