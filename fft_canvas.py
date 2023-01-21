""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window
import pyaudio
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.projections import register_projection
from PyQt6 import QtCore

import time

import freq_anal as FA
import microphone as microphone

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

    The fft is displayed using background audio capture and callback
    for processing. During the chunk processing the interpolated peaks
    are found.  The threshold used to sample the peaks is the same as the
    threshold used to decide if a new fft is displayed. The
    amplitude of the fft is emitted to the signal passed in the class
    constructor
    """

    hold = False
    pan_running = QtCore.pyqtSignal(bool)

    def __init__(self, ampChanged, peaksChanged, averagesChanged, framerateUpdate, frange, threshold):
        self.fig = plt.figure(figsize = (5, 3))
        super().__init__(self.fig)

        self.fft_axes = self.fig.subplots(
            subplot_kw={'projection': 'pan_projection', "pan_signal" : self.pan_running})

        plt.grid(color='0.85')
        self.amp_signal = ampChanged
        self.peaks_signal = peaksChanged
        self.averages_signal = averagesChanged
        self.framerate_signal = framerateUpdate

        self.avg_enable = False

        # Get an audio stream
        audio_stream = pyaudio.PyAudio()

        #self.fft_data = FftData(44100, 15001)
        self.fft_data = FftData(11025, 16384)

        #self.set_threshold(threshold)
        self.threshold = threshold

        # Set threshold value for drawing threshold line
        self.threshold_x = self.fft_data.sample_freq//2
        self.threshold_y = self.threshold - 100

        self.update_axis(frange['f_min'], frange['f_max'], True)

        # y axis limits
        self.fft_axes.set_ylim(-100, 0)

        # Set axis labels
        self.fft_axes.set_ylabel('FFT Magnitude (dB)')
        self.fft_axes.set_xlabel('Frequency (Hz)')
        self.fft_axes.set_title('FFT Peaks')

        # Open the audio stream
        self.mic = microphone.Microphone(rate = self.fft_data.sample_freq, chunksize = self.fft_data.m_t)

        # set the line and point plots and ini
        self.line, = self.fft_axes.plot([], [], lw=1)
        self.points = self.fft_axes.scatter([], [])
        self.line_threshold, = self.fft_axes.plot([], [], lw=1)

        x_axis = np.arange(0, self.fft_data.h_n_f + 1)
        self.freq = x_axis * self.fft_data.sample_freq // (self.fft_data.n_f)

        # Saved waveform data for drawing
        self.saved_mag_y_db = []
        self.saved_peaks = np.vstack(([], [])).T

        # Saved averaging data
        self.max_average_count = 1
        self.mag_y_sum = []
        self.num_averages = 0

        # For framerate calculation
        self.lastupdate = time.time()
        self.fps = 0.0

        # Start the microphone
        self.mic.start()

        # Create timer for callbacks
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_fft)
        self.timer.start(100)

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
                # Update the Peaks
                self.find_peaks(self.saved_mag_y_db)
                self.fig.canvas.draw()

    def set_max_average_count(self, max_average_count):
        self.max_average_count = max_average_count
    
    def reset_averaging(self):
        self.num_averages = 0

    def set_avg_enable(self, avg_enable):
        """ Flag to enable/disable the averaging
        """
        self.avg_enable = avg_enable

    def set_hold_results(self, hold_results):
        """ Flag to enable/disable the holding of peaks. I.e. if it is false
            the it free runs (and averaging is disabled).
        """
        self.hold_results = hold_results

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

        # Set threshold value for drawing threshold line
        self.threshold_x = self.fft_data.sample_freq//2
        self.threshold_y = self.threshold - 100

        self.line_threshold.set_data([0, self.threshold_x], [self.threshold_y, self.threshold_y])

        self.find_peaks(self.saved_mag_y_db)
        self.fig.canvas.draw()

    def find_peaks(self, mag_y_db):
        if not np.any(mag_y_db):
            return False, self.saved_peaks


        # Find the interpolated peaks from the waveform
        # This must be done again since it may be using an average waveform.
        ploc = FA.peak_detection(mag_y_db, self.threshold - 100)
        iploc, peaks_mag = FA.peak_interp(mag_y_db, ploc)

        peaks_freq = (iploc * self.fft_data.sample_freq) /float(self.fft_data.n_f)

        peaks = np.vstack((peaks_freq, peaks_mag)).T

        if peaks_mag.size > 0:
            max_peaks_mag = np.max(peaks_mag)
        else:
            max_peaks_mag = -100

        # If there are peaks above the threshold then update the saved mag_db and scatter peaks
        if max_peaks_mag > (self.threshold - 100):
            self.saved_mag_y_db = mag_y_db
            self.saved_peaks = peaks
            triggered = True

            bounded_peaks_freq_min_index = 0
            bounded_peaks_freq_max_index = 0
            # Check the peaks to see if they are within the desired frequency range
            bounded_peaks_freq_indices = np.nonzero((peaks_freq < self.fmax) & (peaks_freq > self.fmin))
            if len(bounded_peaks_freq_indices[0]) > 0:
                bounded_peaks_freq_min_index = bounded_peaks_freq_indices[0][0]
                bounded_peaks_freq_max_index = bounded_peaks_freq_indices[0][-1] + 1

            # If there are peaks in frequency bounds then update the peaks_data signal
            if bounded_peaks_freq_max_index > 0:
                # Update the peaks
                bounded_peaks_freq = peaks_freq[bounded_peaks_freq_min_index:bounded_peaks_freq_max_index]
                bounded_peaks_mag = peaks_mag[bounded_peaks_freq_min_index:bounded_peaks_freq_max_index]
                peaks_data = np.vstack( (bounded_peaks_freq, bounded_peaks_mag)).T
                self.peaks_signal.emit(peaks_data)
            else:
                self.peaks_signal.emit(np.vstack(([], [])).T)
        else:
            self.saved_peaks = np.vstack(([], [])).T
            self.peaks_signal.emit(self.saved_peaks)
            triggered = False

        return  triggered, peaks

    def set_draw_data(self, mag_db, peaks):
        if np.any(mag_db):
            self.line.set_data(self.freq, mag_db)
        self.points.set_offsets(peaks)
        self.line_threshold.set_data([0, self.threshold_x], [self.threshold_y, self.threshold_y])

    # methods for processing chunk
    def update_fft(self):
        """ Get a chunk from the audio stream, find the fft and interpolate the peaks.
        The rest is used to update the fft plot if the maximum of the fft magnitude
        is greater than the threshold value.
        """


        # Read Data
        frames = self.mic.get_frames()
        if len(frames) <= 0:
            return

        enter_now = time.time()
        sample_dt = enter_now - self.lastupdate
        if sample_dt <= 0:
            sample_dt = 0.000000000001
        fps = 1.0/sample_dt
        self.lastupdate = enter_now

        chunk = frames[-1]

        # Find DFT and amplitude
        mag_y_db, mag_y = FA.dft_anal(chunk, self.fft_data.window_fcn, self.fft_data.n_f)

        amplitude = np.max(mag_y_db) + 100
        self.amp_signal.emit(int(amplitude))

        # Is hold_results set?
        if self.hold_results:
            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)

        # Is Amplitude above the threshold?
        elif amplitude > self.threshold:
            # Is Averaging enabled:
            if self.avg_enable:
                # Have the maximum number of averages been found
                if self.num_averages < self.max_average_count:
                    # Calculate average based on the magnitude of the FFT -
                    # ignore phase since it is highly variable.
                    if self.num_averages > 0:
                        mag_y_sum = self.mag_y_sum + mag_y
                    else:
                        mag_y_sum = mag_y
                    num_averages = self.num_averages + 1

                    avg_mag_y = mag_y_sum/num_averages

                    avg_mag_y[avg_mag_y < np.finfo(float).eps] = np.finfo(float).eps

                    avg_mag_y_db = 20 * np.log10(avg_mag_y)

                    avg_amplitude = np.max(avg_mag_y_db) + 100
                    if avg_amplitude > self.threshold:
                        # Find peaks using average mag_y_db
                        triggered, avg_peaks = self.find_peaks(avg_mag_y_db)
                        if triggered:
                            # Draw avg_mag_db and avg_peaks
                            # Draw threshold
                            self.set_draw_data(avg_mag_y_db, avg_peaks)

                            # Save magnitude FFT for average
                            self.mag_y_sum = mag_y_sum

                            # Save num_averages and emit num_averages signal
                            self.num_averages = num_averages
                            self.averages_signal.emit(int(self.num_averages))

                            # Save mag_y_db and peaks
                            self.saved_mag_y_db = avg_mag_y_db
                            self.saved_peaks = avg_peaks
                            # Set Hold Flag True
                        else:
                            # Draw Saved mag_y_db and peaks
                            # Draw threshold
                            # Set Hold Flag False
                            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)

                    else:
                        # Draw Saved mag_y_db and peaks
                        # Draw threshold
                        # Set Hold Flag False
                        self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)
                else:
                    # Draw Saved mag_y_db and peaks
                    # Draw threshold
                    self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)
            else:
                # Find peaks
                triggered, peaks = self.find_peaks(mag_y_db)
                # Were Peaks Triggered?
                if triggered:
                    # Draw mag_y_db and peaks
                    # Draw threshold
                    # Set hold flag True
                    self.set_draw_data(mag_y_db, peaks)
                else:
                    # Draw Saved mag_y_db and peaks
                    # Draw threshold
                    self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)
        else:
            # Draw Saved mag_y_db and peaks
            # Draw threshold
            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)

        self.fig.canvas.draw()

        exit_now = time.time()
        processing_dt = exit_now - enter_now
        if processing_dt <= 0:
            processing_dt = 0.000000000001
        self.framerate_signal.emit(float(fps), float(sample_dt), float(processing_dt))

        return self.line, self.points, self.line_threshold
