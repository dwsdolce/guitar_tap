"""
    Custom widget containing the plot controls for the FFT and the FFT plot.
"""
from PyQt6 import QtWidgets, QtCore

import threshold_slider as TS
import fft_canvas as fft_c
import fft_toolbar as fft_t

class PlotControls(QtWidgets.QWidget):
    """ Create a custom widget with the threshold slider, the FFT canvas, and
        the navigation controls.
    """

    def __init__(self,
                 threshold: int,
                 f_range: dict[str, int],
                 fft_settings: dict[str, int]
                ) -> None:
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
        self.fft_canvas = fft_c.FftCanvas(
            fft_settings['window_length'], fft_settings['sampling_rate'], f_range, threshold)
        self.fft_canvas.setMinimumSize(600, 400)
        self.toolbar = fft_t.FftToolbar(self.fft_canvas, self)

        self.fft_canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.fft_canvas.setFocus()

        plot_layout.addWidget(self.fft_canvas)
        plot_layout.addWidget(self.toolbar)

        # Connect signals
        self.fft_canvas.ampChanged.connect(self.threshold_slider.set_amplitude)

        self.setLayout(plot_layout)

    def threshold_changed(self) -> None:
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """
        threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(threshold)

    def fmin_changed(self) -> None:
        """ Change the minimum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmin(self.sender().value())

    def fmax_changed(self) -> None:
        """ Change the maximum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmax(self.sender().value())
