""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys
from dataclasses import dataclass

from PyQt6 import QtWidgets, QtCore
#from PyQt6.QtCore import Qt, pyqtSignal

import numpy as np
from scipy.signal import get_window
import pyaudio
from matplotlib.backends.backend_qtagg import (FigureCanvasQTAgg,
        NavigationToolbar2QT as NavigationToolbar)
from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation

import freq_anal as FA
import threshold_slider as TS

# pylint: disable=too-many-instance-attributes
@dataclass
class FftData:
    """ Data used to drive the FFT calculations
    """

    def __init__(self, sample_freq: int = 44100, m_t: int = 15001,
            fmin: int = 50, fmax: int = 1000):
        self.sample_freq = sample_freq
        self.m_t = m_t
        self.fmin = fmin
        self.fmax = fmax

        self.n_f = int(2 ** (np.ceil(np.log2(self.m_t))))
        self.window_fcn = get_window('blackman', self.m_t)
        self.n_fmax = (self.n_f * fmax) // self.sample_freq
        self.n_fmin = (self.n_f * fmin) // self.sample_freq

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

    skip = 0
    threshold = -50

    def __init__(self, signal, fmin, fmax):
        #fig = plt.figure(figsize=(5,3))
        fig, fft_axes = plt.subplots(figsize=(5,3))
        self.amp_signal = signal

        self.fft_data = FftData(44100, 15001, fmin, fmax)

        # Get an audio stream
        audio_stream = pyaudio.PyAudio()

        # x axis data points
        x_axis = np.arange(self.fft_data.n_fmin, self.fft_data.n_fmax)
        self.x_axis_freq = x_axis * self.fft_data.fmax // (self.fft_data.n_fmax)
        self.bounded_mag_y = np.zeros(self.x_axis_freq.size)
        fft_axes.set_xlim(min(self.x_axis_freq), max(self.x_axis_freq))

        # y axis limits
        fft_axes.set_ylim(-100, 0)

        # Open the audio stream
        self.stream = audio_stream.open(format = pyaudio.paFloat32, channels = 1,
                rate = self.fft_data.sample_freq, input = True,
                frames_per_buffer = self.fft_data.m_t)

        # set the line and point plots and ini
        self.line, = fft_axes.plot([], [], lw=1)
        self.points = fft_axes.scatter([], [])
        self.scatter_peaks = np.vstack(([], [])).T

        self.animation = FuncAnimation(fig, self.update_fft, frames=200,
                interval=20, blit=True)
        super().__init__(fig)

    def set_fmin(self, fmin):
        """ As it says """
        self.fft.data.fmin = fmin

    def set_fmax(self, fmax):
        """ As it says """
        self.fft.data.fmax = fmax

    def set_threshold(self, threshold):
        """ Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks
        """

        self.threshold = threshold

    # methods for animation
    def update_fft(self, _i):
        """ Get a chunk from the audio stream, find the fft and interpolate the peaks.
        The rest is used to update the fft plot if the maximum of the fft magnitude
        is greater than the threshold value.
        """

        chunk = np.frombuffer(self.stream.read(self.fft_data.m_t), dtype=np.float32)
        mag_y, phase_y = FA.dft_anal(chunk, self.fft_data.window_fcn, self.fft_data.n_f)

        # Find the interpolated peaks from the waveform
        ploc = FA.peak_detection(mag_y, self.threshold)
        iploc, ipmag, _ = FA.peak_interp(mag_y, phase_y, ploc)

        peaks_freq = self.fft_data.sample_freq * iploc/float(self.fft_data.n_f)

        # Get the max of just the frequencies within the range requested
        if mag_y.size > 0:
            max_mag_y = np.max(mag_y[self.fft_data.n_fmin:self.fft_data.n_fmax])
        else:
            max_mag_y = -100
        self.amp_signal.emit(int(max_mag_y + 100))

        if ipmag.size > 0:
            max_ipmag = np.max(ipmag)
        else:
            max_ipmag = -100
        if max_ipmag > self.threshold:
            if self.skip == 0:
                # Check the peaks to see if they are within the desired frequency range
                bounded_freq_indices = np.nonzero(
                        (peaks_freq < self.fft_data.fmax) & (peaks_freq > self.fft_data.fmin))
                if len(bounded_freq_indices[0]) > 0:
                    bounded_freq_min_index = bounded_freq_indices[0][0]
                    bounded_freq_max_index = bounded_freq_indices[0][-1] + 1
                else:
                    bounded_freq_min_index = 0
                    bounded_freq_max_index = 0

                if bounded_freq_max_index > 0:
                    # Update the magnitude and the peaks
                    self.bounded_mag_y = mag_y[self.fft_data.n_fmin:self.fft_data.n_fmax]

                    bounded_peaks_freq = peaks_freq[bounded_freq_min_index:bounded_freq_max_index]
                    bounded_peaks_mag = ipmag[bounded_freq_min_index:bounded_freq_max_index]
                    self.scatter_peaks = np.vstack((bounded_peaks_freq, bounded_peaks_mag)).T
            else:
                self.skip = 1
        else:
            self.skip = 0

        self.line.set_data(self.x_axis_freq, self.bounded_mag_y)
        self.points.set_offsets(self.scatter_peaks)

        # A trailing comma is required here.
        # pylint: disable=trailing-comma-tuple
        return self.line, self.points


class MainWindow(QtWidgets.QMainWindow):
    """ Defines the layout of the application window
    """


    ampChanged = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._main = QtWidgets.QWidget()

        self.setCentralWidget(self._main)
        layout = QtWidgets.QVBoxLayout(self._main)

        # Add the slider
        self.threshold_slider = TS.ThresholdSlider(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(self.threshold_slider)
        self.threshold = 50
        self.threshold_slider.valueChanged.connect(self.valuechange)

        self.ampChanged.connect(self.threshold_slider.set_amplitude)

        # Add an fft Canvas
        self.fft_canvas = DrawFft(self.ampChanged, 50, 1000)
        self.toolbar = NavigationToolbar(self.fft_canvas, self)

        layout.addWidget(self.fft_canvas)
        layout.addWidget(self.toolbar)

    def valuechange(self):
        """ Set the threshold used in fft_canvas
        """

        self.threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(self.threshold - 100)

if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
