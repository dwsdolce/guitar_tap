""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window
import pyaudio
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.projections import register_projection
from PyQt6 import QtCore

import freq_anal as FA

class PanAxes(Axes):
    """ Create a new projection so that we can override the start_pan
        and stop_pan methods.
        """
    name = 'pan_projection'

    def __init__(self, * args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clear()

    # Disable since pylint does not know that this is
    # used by the  __init__ for the kwargs """
    # pylint: disable=attribute-defined-outside-init
    def set_pan_signal(self, pan_signal):
        """ Required setter for the pan_signal kw_args passed to subplot
        """
        self.pan_signal = pan_signal

    def start_pan(self, x, y, button):
        """ SIgnal that pan has started """
        self.pan_signal.emit(True)
        super().start_pan(x, y, button)

    def end_pan(self):
        """ SIgnal that pan has ended """
        self.pan_signal.emit(False)
        super().end_pan()

register_projection(PanAxes)

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
    animation_running = True
    pan_running = QtCore.pyqtSignal(bool)

    def __init__(self, ampChanged, peaksChanged, frange, threshold):
        self.fig = plt.figure(figsize = (5, 3))
        super().__init__(self.fig)

        self.fft_axes = self.fig.subplots(
            subplot_kw={'projection': 'pan_projection', "pan_signal" : self.pan_running})

        self.pan_running.connect(self.pan_animation)

        plt.grid(color='0.85')
        self.amp_signal = ampChanged
        self.peaks_signal = peaksChanged

        # Get an audio stream
        audio_stream = pyaudio.PyAudio()

        self.fft_data = FftData(44100, 15001)

        self.set_threshold(threshold)

        self.update_axis(frange['f_min'], frange['f_max'], True)

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
                interval=100, blit=True)
                #interval=100, blit=False)

    def update_axis(self, fmin, fmax, init = False):
        """ Update the mag_y and x_axis """

        # x axis data points
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq

            self.fft_axes.set_xlim(fmin, fmax)
            if not init:
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

    def pan_animation(self, in_pan):
        """ Pause andd resume animation when in pan """
        if in_pan:
            if self.animation_running:
                self.animation.pause()
                self.animation_running = False
        else:
            if not self.animation_running:
                self.animation.resume()
                self.fig.canvas.draw()
                self.animation_running = True

    # methods for animation
    def update_fft(self, _i):
        """ Get a chunk from the audio stream, find the fft and interpolate the peaks.
        The rest is used to update the fft plot if the maximum of the fft magnitude
        is greater than the threshold value.
        """

        chunk = np.frombuffer(self.stream.read(self.fft_data.m_t), dtype=np.float32)
        amplitude = np.max(chunk)

        self.amp_signal.emit(int(amplitude * 100))


        if (100 * amplitude) > self.threshold:
            if not self.skip:
                mag_y = FA.dft_anal(chunk, self.fft_data.window_fcn, self.fft_data.n_f)
                if not np.any(self.saved_mag_y):
                    self.saved_mag_y = mag_y
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
                        data_len = np.size(bounded_peaks_freq)
                        notes = np.arange(0, data_len)
                        cents = np.arange(0, data_len)
                        peaks_data = np.vstack(
                                (bounded_peaks_freq, bounded_peaks_mag, bounded_peaks_freq, bounded_peaks_freq)).T
                        self.peaks_signal.emit(peaks_data)
                        if not self.skip:
                            self.skip = True
        else:
            self.skip = False

        if np.any(self.saved_mag_y):
            self.line.set_data(self.freq, self.saved_mag_y)
        self.points.set_offsets(self.saved_scatter_peaks)
        self.line_threshold.set_data(
                [0, self.fft_data.sample_freq//2],
                [self.threshold - 100, self.threshold - 100])

        return self.line, self.points, self.line_threshold
