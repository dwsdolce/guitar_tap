""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
from dataclasses import dataclass
from typing import List
import time

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib import pyplot as plt

import numpy as np
import numpy.typing as npt
from scipy.signal import get_window
from PyQt6 import QtCore
import pyaudio

import fft_annotations as fft_a
import freq_anal as f_a
import microphone

matplotlib.use('Qt5Agg')

@dataclass
class FftData:
    """ Data used to drive the FFT calculations
    """

    def __init__(self, sample_freq: int = 44100, m_t: int = 15001) -> None:
        self.sample_freq = sample_freq
        self.m_t = m_t

        #self.window_fcn = get_window('blackman', self.m_t)
        self.window_fcn = get_window('boxcar', self.m_t)
        self.n_f: int = int(2 ** (np.ceil(np.log2(self.m_t))))
        self.h_n_f: int = self.n_f //2

# pylint: disable=too-many-instance-attributes
class FftCanvas(FigureCanvasQTAgg):
    """ Sample the audio stream and display the FFT

    The fft is displayed using background audio capture and callback
    for processing. During the chunk processing the interpolated peaks
    are found.  The threshold used to sample the peaks is the same as the
    threshold used to decide if a new fft is displayed. The
    amplitude of the fft is emitted to the signal passed in the class
    constructor
    """

    hold: bool = False

    peakDeselected: QtCore.pyqtSignal = QtCore.pyqtSignal()
    peakSelected: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    peaksChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(np.ndarray)
    ampChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    averagesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    framerateUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    newSample: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)

    def __init__(self,
                 window_length: int,
                 sampling_rate: int,
                 frange: dict[str, int] ,
                 threshold: int
                ) -> None:
        self.fig: FigureCanvasQTAgg = plt.figure(figsize = (5, 3))
        super().__init__(self.fig)

        self.hold_results: bool = False

        self.fft_axes: list[plt.Axes] = self.fig.subplots()

        self.annotations: fft_a.FftAnnotations = fft_a.FftAnnotations(self.fig, self.fft_axes)

        plt.grid(color='0.85')

        self.avg_enable: bool = False

        self.fft_data: FftData = FftData(sampling_rate, window_length)

        self.threshold:int = threshold

        # Set threshold value for drawing threshold line
        self.threshold_x: int = self.fft_data.sample_freq//2
        self.threshold_y: int = self.threshold - 100

        self.update_axis(frange['f_min'], frange['f_max'], True)

        # y axis limits
        self.fft_axes.set_ylim(-100, 0)

        # Set axis labels
        self.fft_axes.set_ylabel('FFT Magnitude (dB)')
        self.fft_axes.set_xlabel('Frequency (Hz)')
        self.fft_axes.set_title('FFT Peaks')

        # Open the audio stream
        self.mic: microphone.Microphone = microphone.Microphone(
            self, rate = self.fft_data.sample_freq, chunksize = self.fft_data.m_t)

        # set the line and point plots and ini
        self.line, = self.fft_axes.plot([], [], lw=1)
        self.points = self.fft_axes.scatter([], [], picker = True)
        self.selected_point = self.fft_axes.scatter([],[], c = 'red')
        self.fig.canvas.mpl_connect('pick_event', self.point_picked)
        self.fig.canvas.mpl_connect('button_release_event', self.annotations.annotation_moved)
        self.line_threshold, = self.fft_axes.plot([], [], lw=1)

        x_axis: npt.NDArray[np.int64] = np.arange(0, self.fft_data.h_n_f + 1)
        self.freq: npt.NDArray[np.int64] = x_axis * self.fft_data.sample_freq // (self.fft_data.n_f)

        # Saved waveform data for drawing
        self.saved_mag_y_db: npt.NDArray[np.float64] = []
        self.saved_peaks  = np.vstack(([], [])).T
        self.b_peaks_freq: npt.NDArray[np.float64] = []
        self.selected_peak: float = 0.0

        # Saved peak information
        self.peaks_f_min_index: int = 0
        self.peaks_f_max_index: int = 0

        # Saved averaging data
        self.max_average_count: int = 1
        self.mag_y_sum: List[float] = []
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

    def get_py_audio(self) -> pyaudio.PyAudio:
        """ Return the py_audio opened in the microphone """
        return self.mic.py_audio

    def select_peak(self, freq: float) -> None:
        """ Select the peak (scatter point) with the specified frequency """
        #print(f"FftCanvas: select_peak: freq: {freq}, hold_results: {self.hold_results}")
        if self.hold_results:
            row = np.where(self.saved_peaks[:,0] == freq)
            magdb = self.saved_peaks[row][0][1]
            self.selected_point.set_offsets(np.vstack(([freq], [magdb])).T)
            self.selected_peak = freq
            self.fig.canvas.draw()

    def deselect_peak(self, _freq: float) -> None:
        """ Deselect the peak (scatter point) with the specified frequency """
        #print(f"FftCanvas: deselect_peak: fred: {_freq}, hold_results: {self.hold_results}")
        #if self.hold_results:
        self.selected_point.set_offsets(np.vstack(([], [])).T)
        self.fig.canvas.draw()

    def clear_selected_peak(self) -> None:
        """ Reset the selected peak. """
        #print("FftCanvas: clear_selected_peak")
        self.selected_peak = -1.0

    def point_picked(self, event: matplotlib.backend_bases.PickEvent) -> None:
        """ Handle the event for scatter point being picked and emit
            the index if it is within the min/max frequency range
        """
        if self.hold_results:
            if self.annotations.select_annotation(event.artist):
                return
            index0 = event.ind[0]
            #print(f"point_picked: index0: {index0}")
            #print(f"point_picked: index0 type: {type(index0)}")
            if self.peaks_f_min_index <= index0 < self.peaks_f_max_index:
                if np.any(self.saved_peaks):
                    freq = self.saved_peaks[index0][0]
                    self.peakSelected.emit(freq)

    def update_axis(self, fmin: int, fmax: int, init:bool = False) -> None:
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

    def set_max_average_count(self, max_average_count: int) -> None:
        """ Set the number of averages to take """
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        """ Reset the number of averages taken to zero. """
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        """ Flag to enable/disable the averaging """
        self.avg_enable = avg_enable

    def set_hold_results(self, hold_results: bool) -> None:
        """ Flag to enable/disable the holding of peaks. I.e. if it is false
            the it free runs (and averaging is disabled).
        """
        #print(f"FftCanvas: set_hold_results: hold_results {hold_results}")
        self.hold_results = hold_results
        if not hold_results:
            self.selected_point.set_offsets(np.vstack(([], [])).T)
            self.clear_selected_peak()

    def set_fmin(self, fmin: int) -> None:
        """ As it says """
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax: int) -> None:
        """ As it says """
        self.update_axis(self.fmin, fmax)

    def set_threshold(self, threshold: int) -> None:
        """ Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks. The threshold value is always 0 to 100.
        """

        self.threshold = threshold

        # Set threshold value for drawing threshold line
        self.threshold_x = self.fft_data.sample_freq//2
        self.threshold_y = self.threshold - 100

        self.line_threshold.set_data([0, self.threshold_x], [self.threshold_y, self.threshold_y])

        self.find_peaks(self.saved_mag_y_db)

        # Deselect peak on graph and on table.
        # Check if peak is still within threshold
        # Then use selected_peak set peak to new value
        self.selected_point.set_offsets(np.vstack(([], [])).T)
        self.peakDeselected.emit()
        if np.any(self.b_peaks_freq):
            if self.selected_peak > 0:
                peak_index= np.where(self.b_peaks_freq == self.selected_peak)
                if len(peak_index[0]):
                    self.peakSelected.emit(self.selected_peak)

        self.fig.canvas.draw()

    def find_peaks(self, mag_y_db):
        """ For the specified magnitude in db:
            1. detect the peaks that are above the user specified threshold
            2. interpolate each peak using parabolic interpolation
            3. If there are peaks above the user specified threashld then
               from the resulting list of peaks find those that are within the
               user specified min/max frequency range and emit a signal that
               the peaks have changed.
            4. If there are no peaks in the frequency range then emit a signal
               with an empty list of peaks.
            5. If there were no peaks within the threshold then emit
               an peaks changed with the saved set of peaks.
        """
        if not np.any(mag_y_db):
            return False, self.saved_peaks


        # Find the interpolated peaks from the waveform
        # This must be done again since it may be using an average waveform.
        ploc = f_a.peak_detection(mag_y_db, self.threshold - 100)
        iploc, peaks_mag = f_a.peak_interp(mag_y_db, ploc)

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

            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            # Check the peaks to see if they are within the desired frequency range
            b_peaks_f_indices = np.nonzero((peaks_freq < self.fmax) & (peaks_freq > self.fmin))
            if len(b_peaks_f_indices[0]) > 0:
                self.peaks_f_min_index = b_peaks_f_indices[0][0]
                self.peaks_f_max_index = b_peaks_f_indices[0][-1] + 1

            # If there are peaks in frequency bounds then update the peaks_data signal
            if self.peaks_f_max_index > 0:
                # Update the peaks
                self.b_peaks_freq = peaks_freq[self.peaks_f_min_index:self.peaks_f_max_index]
                b_peaks_mag = peaks_mag[self.peaks_f_min_index:self.peaks_f_max_index]
                peaks_data = np.vstack((self.b_peaks_freq, b_peaks_mag)).T
                self.peaksChanged.emit(peaks_data)
            else:
                self.b_peaks_freq = []
                self.peaksChanged.emit(np.vstack(([], [])).T)
        else:
            self.saved_peaks = np.vstack(([], [])).T
            self.peaksChanged.emit(self.saved_peaks)
            triggered = False

        return  triggered, peaks

    def set_draw_data(self, mag_db, peaks):
        """ set the data for each of the 3 plot objects used in update_fft """
        if np.any(mag_db):
            self.line.set_data(self.freq, mag_db)
        self.points.set_offsets(peaks)
        self.line_threshold.set_data([0, self.threshold_x], [self.threshold_y, self.threshold_y])


    def process_averages(self, mag_y):
        """ For the specified magnitude find the average with all the saved magnitudes.
            If there are magnitudes above the user specified threshold then update
            the saved averages, the number of averages, the saved peaks, and emit
            the signal for the average count changes. Update the data to be drawn
            using the saved mag_db and peaks
        """

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
                    self.newSample.emit(self.hold_results)
                    self.annotations.clear_annotations()
                    # Draw avg_mag_y_db and avg_peaks
                    # Draw threshold
                    self.set_draw_data(avg_mag_y_db, avg_peaks)

                    # Save magnitude FFT for average
                    self.mag_y_sum = mag_y_sum

                    # Save num_averages and emit num_averages signal
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))

                    # Save mag_y_db and peaks
                    self.saved_mag_y_db = avg_mag_y_db
                    self.saved_peaks = avg_peaks

        # Draw Saved mag_y_db and peaks
        # Draw threshold
        self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)


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

        chunk: npt.NDArray[np.float32] = frames[-1]

        # Find DFT and amplitude
        mag_y_db, mag_y = f_a.dft_anal(chunk, self.fft_data.window_fcn, self.fft_data.n_f)

        amplitude = np.max(mag_y_db) + 100
        self.ampChanged.emit(int(amplitude))

        # Is hold_results set?
        if self.hold_results:
            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)

        # Is Amplitude above the threshold?
        elif amplitude > self.threshold:
            # Is Averaging enabled:
            if self.avg_enable:
                self.process_averages(mag_y)
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
        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))

        return
