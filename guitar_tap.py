""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys
from dataclasses import dataclass

from PyQt6 import QtWidgets, QtCore

import numpy as np
from scipy.signal import get_window
import pyaudio
from matplotlib.backends.backend_qtagg import (FigureCanvasQTAgg,
        NavigationToolbar2QT as NavigationToolbar)
from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation

import freq_anal as FA
import threshold_slider as TS

@dataclass
class FftData:
    """ Data used to drive the FFT calculations
    """

    def __init__(self, sample_freq: int = 44100, m_t: int = 15001):
        self.sample_freq = sample_freq
        self.m_t = m_t

        self.window_fcn = get_window('blackman', self.m_t)
        self.n_f = int(2 ** (np.ceil(np.log2(self.m_t))))
        self.h_n_f = self.n_f //2

# pylint: disable=too-many-instance-attributes
class DrawFft(FigureCanvasQTAgg):
    """ Sample the audio stream and display the FFT

    The fft is displayed using function animation and during the
    chunk processing the interpolated peaks are found.
    The threshold used to sample the peaks is the same as the
    threshold used to decide if a new fft is displayed. The
    amplitude of the fft is emitted to the signal passed in the class
    constructor
    """

    skip = False

    def __init__(self, ampChanged, peaksChanged, fmin, fmax, threshold):
        self.fig, self.fft_axes = plt.subplots(figsize=(5,3))
        plt.grid(color='0.85')
        self.amp_signal = ampChanged
        self.peaks_signal = peaksChanged


        # Get an audio stream
        audio_stream = pyaudio.PyAudio()

        self.fft_data = FftData(44100, 15001)

        self.set_threshold(threshold)

        self.update_axis(fmin, fmax, True)

        # y axis limits
        self.fft_axes.set_ylim(-100, 0)

        # Open the audio stream
        self.stream = audio_stream.open(format = pyaudio.paFloat32, channels = 1,
                rate = self.fft_data.sample_freq, input = True,
                frames_per_buffer = self.fft_data.m_t)

        # set the line and point plots and ini
        self.line, = self.fft_axes.plot([], [], lw=1)
        self.points = self.fft_axes.scatter([], [])
        self.line_threshold, = self.fft_axes.plot([], [], lw=1)

        x_axis = np.arange(0, self.fft_data.h_n_f + 1)
        self.freq = x_axis * self.fft_data.sample_freq // (self.fft_data.n_f)

        self.bounded_scatter_peaks = np.vstack(([], [])).T
        self.saved_mag_y = []
        self.saved_scatter_peaks = np.vstack(([], [])).T

        self.animation = FuncAnimation(self.fig, self.update_fft, frames=200,
                interval=20, blit=True)
                #interval=100, blit=False)
        super().__init__(self.fig)

    def update_axis(self, fmin, fmax, init = False):
        """ Update the mag_y and x_axis """

        # x axis data points
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq

            self.fft_axes.set_xlim(fmin, fmax)
            if init == False:
                self.fig.canvas.draw()

    def set_fmin(self, fmin):
        """ As it says """
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax):
        """ As it says """
        self.update_axis(self.fmin, fmax)

    def set_threshold(self, threshold):
        """ Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks. The threshold value is always 0 to 100.
        """

        self.threshold = threshold

    # methods for animation
    def update_fft(self, _i):
        """ Get a chunk from the audio stream, find the fft and interpolate the peaks.
        The rest is used to update the fft plot if the maximum of the fft magnitude
        is greater than the threshold value.
        """

        chunk = np.frombuffer(self.stream.read(self.fft_data.m_t), dtype=np.float32)
        amplitude = np.max(chunk)
        mag_y = FA.dft_anal(chunk, self.fft_data.window_fcn, self.fft_data.n_f)

        # Get the max of just the frequencies within the range requested
        if mag_y.size > 0:
            max_mag_y = np.max(mag_y[self.n_fmin:self.n_fmax])
        else:
            max_mag_y = -100
        self.amp_signal.emit(int(amplitude * 100))

        if (np.any(self.saved_mag_y) == False):
            self.saved_mag_y = mag_y

        if (100 * amplitude) > self.threshold:
            if self.skip == False:
                # Find the interpolated peaks from the waveform
                ploc = FA.peak_detection(mag_y, self.threshold - 100)
                iploc, peaks_mag = FA.peak_interp(mag_y, ploc)

                peaks_freq = (iploc * self.fft_data.sample_freq) /float(self.fft_data.n_f)

                scatter_peaks = np.vstack((peaks_freq, peaks_mag)).T

                if peaks_mag.size > 0:
                    max_peaks_mag = np.max(peaks_mag)
                else:
                    max_peaks_mag = -100

                if max_peaks_mag > (self.threshold - 100):
                    self.saved_mag_y = mag_y
                    self.saved_scatter_peaks = scatter_peaks

                    # Alternative is to keep ALL of the peaks that exceed the threshold
                    # setting and pass them to the signal. The consumer of the signal
                    # can then decide what to do with them. For example:
                    #   sort by largest values and then pick N of them and then sort
                    #   by frequency.
                    # The other alternative is to filter by the indicated fmin/fmax
                    # and only send the ones in the range.
                    """
                    self.peaks_signal.emit(scatter_peaks)
                    if self.skip == False:
                        self.skip = True
                    """
                    # Check the peaks to see if they are within the desired frequency range
                    bounded_peaks_freq_indices = np.nonzero(
                            (peaks_freq < self.fmax) & (peaks_freq > self.fmin))
                    if len(bounded_peaks_freq_indices[0]) > 0:
                        bounded_peaks_freq_min_index = bounded_peaks_freq_indices[0][0]
                        bounded_peaks_freq_max_index = bounded_peaks_freq_indices[0][-1] + 1
                    else:
                        bounded_peaks_freq_min_index = 0
                        bounded_peaks_freq_max_index = 0

                    if bounded_peaks_freq_max_index > 0:
                        # Update the peaks
                        bounded_peaks_freq = peaks_freq[
                                bounded_peaks_freq_min_index:bounded_peaks_freq_max_index]
                        bounded_peaks_mag = peaks_mag[
                                bounded_peaks_freq_min_index:bounded_peaks_freq_max_index]
                        self.bounded_scatter_peaks = np.vstack(
                                (bounded_peaks_freq, bounded_peaks_mag)).T
                        self.peaks_signal.emit(self.bounded_scatter_peaks)
                        if self.skip == False:
                            self.skip = True
        else:
            self.skip = False

        self.line.set_data(self.freq, self.saved_mag_y)
        self.points.set_offsets(self.saved_scatter_peaks)
        self.line_threshold.set_data([0, self.fft_data.sample_freq//2], [self.threshold - 100, self.threshold - 100])

        return self.line, self.points, self.line_threshold


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
        #plot_layout = QtWidgets.QVBoxLayout(self._main)
        plot_layout = QtWidgets.QVBoxLayout()

        # Add the slider
        self.threshold_slider = TS.ThresholdSlider(QtCore.Qt.Orientation.Horizontal)
        plot_layout.addWidget(self.threshold_slider)
        self.threshold = 50
        self.threshold_slider.valueChanged.connect(self.threshold_changed)

        self.ampChanged.connect(self.threshold_slider.set_amplitude)
        self.peaksChanged.connect(self.print_peaks)

        # Add an fft Canvas
        f_min = 50
        f_max = 1000
        self.fft_canvas = DrawFft(self.ampChanged, self.peaksChanged, f_min, f_max, self.threshold)
        self.toolbar = NavigationToolbar(self.fft_canvas, self)

        self.fft_canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.fft_canvas.setFocus()

        plot_layout.addWidget(self.fft_canvas)
        plot_layout.addWidget(self.toolbar)

        hlayout.addLayout(plot_layout)

        # Create control layout
        control_layout = QtWidgets.QVBoxLayout() 

        min_max_layout = QtWidgets.QHBoxLayout()

        min_layout = QtWidgets.QVBoxLayout()
        min_label = QtWidgets.QLabel("Start Freq (Hz)")
        min_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        min_layout.addWidget(min_label)
        self.min_spin = QtWidgets.QSpinBox(self._main)
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_min)
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
        self.max_spin.setValue(f_max)
        self.max_spin.valueChanged.connect(self.fmax_changed)
        max_layout.addWidget(self.max_spin)

        min_max_layout.addLayout(max_layout)

        control_layout.addLayout(min_max_layout)

        hlayout.addLayout(control_layout)

    def print_peaks(self, peaks):
        print(peaks)

    def threshold_changed(self):
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """

        self.threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(self.threshold)

    def fmin_changed(self):
        self.fft_canvas.set_fmin(self.min_spin.value())

    def fmax_changed(self):
        self.fft_canvas.set_fmax(self.max_spin.value())

if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.resize(800, 500)
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
