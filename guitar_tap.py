""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys

import numpy as np
from PyQt6 import QtWidgets, QtCore
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

import threshold_slider as TS
import fft_canvas as fft_c

class MainWindow(QtWidgets.QMainWindow):
    """ Defines the layout of the application window
    """

    ampChanged = QtCore.pyqtSignal(int)
    peaksChanged = QtCore.pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self._main = QtWidgets.QWidget()

        self.setCentralWidget(self._main)

        hlayout = QtWidgets.QHBoxLayout(self._main)

        # Create layout with threshold slider and fft canvas
        plot_layout = QtWidgets.QVBoxLayout()

        # Add the slider
        self.threshold_slider = TS.ThresholdSlider(QtCore.Qt.Orientation.Horizontal)
        plot_layout.addWidget(self.threshold_slider)
        self.threshold = 50
        self.threshold_slider.valueChanged.connect(self.threshold_changed)

        self.ampChanged.connect(self.threshold_slider.set_amplitude)
        self.peaksChanged.connect(self.print_peaks)

        # Add an fft Canvas
        f_range = {'f_min': 50, 'f_max': 1000}
        self.fft_canvas = fft_c.DrawFft(
                self.ampChanged, self.peaksChanged, f_range, self.threshold)
        self.toolbar = NavigationToolbar(self.fft_canvas, self)

        self.fft_canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.fft_canvas.setFocus()

        plot_layout.addWidget(self.fft_canvas)
        plot_layout.addWidget(self.toolbar)

        hlayout.addLayout(plot_layout)

        # Create control layout
        control_layout = QtWidgets.QVBoxLayout()

        #run_animation = QtWidgets.QRadioButton("Run Animation", self)
        #run_animation.setChecked(True)
        #run_animation.toggled.connect(self.toggle_animation)
        #control_layout.addWidget(run_animation)

        min_max_layout = QtWidgets.QHBoxLayout()

        min_layout = QtWidgets.QVBoxLayout()
        min_label = QtWidgets.QLabel("Start Freq (Hz)")
        min_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        min_layout.addWidget(min_label)
        self.min_spin = QtWidgets.QSpinBox(self._main)
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_range['f_min'])
        self.min_spin.valueChanged.connect(self.fmin_changed)
        min_layout.addWidget(self.min_spin)

        min_max_layout.addLayout(min_layout)

        max_layout = QtWidgets.QVBoxLayout()
        max_label = QtWidgets.QLabel("Stop Freq (Hz)")
        max_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        max_layout.addWidget(max_label)
        self.max_spin = QtWidgets.QSpinBox(self._main)
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(f_range['f_max'])
        self.max_spin.valueChanged.connect(self.fmax_changed)
        max_layout.addWidget(self.max_spin)

        min_max_layout.addLayout(max_layout)

        control_layout.addLayout(min_max_layout)

        hlayout.addLayout(control_layout)

    def print_peaks(self, peaks):
        """ Temporary for handling peaks changed signal """
        print(peaks)

    def threshold_changed(self):
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """

        self.threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(self.threshold)

    def fmin_changed(self):
        """ Change the minimum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmin(self.min_spin.value())

    def fmax_changed(self):
        """ Change the maximum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmax(self.max_spin.value())

if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.resize(800, 500)
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
