"""
    This class is inspired by:
    https://flothesof.github.io/pyqt-microphone-fft-application.html
"""
from sys import platform

import threading
import atexit
import pyaudio
import numpy as np
if platform == 'darwin':
    import macAccess

class Microphone():
    """ Run the audio capture in a thread using the rate and buffer
        size specified. Closes on exit.
    """
    def __init__(self, parent, rate=44100, chunksize=16384):

        if platform == 'darwin':
            ma = macAccess.MacAccess(parent)

        self.rate = rate
        self.chunksize = chunksize
        self.py_audio = pyaudio.PyAudio()
        self.stream = self.py_audio.open(format=pyaudio.paFloat32,
                                  channels=1,
                                  rate=self.rate,
                                  input=True,
                                  frames_per_buffer=self.chunksize,
                                  stream_callback=self.new_frame)
        self.lock = threading.Lock()
        self.stop = False
        self.frames = []
        atexit.register(self.close)

    # pylint: disable=unused-argument
    def new_frame(self, data, frame_count, time_info, status):
        """ Callback used by pyaudio stream to capture the
            next buffer. If the buffers are short then this could
            be slow (append is not particularly fast
        """
        data = np.frombuffer(data, np.float32)
        with self.lock:
            self.frames.append(data)
            if self.stop:
                return None, pyaudio.paComplete
        return None, pyaudio.paContinue

    def get_frames(self):
        """ Get the frames that have be saved """
        with self.lock:
            frames = self.frames
            self.frames = []
            return frames

    def start(self):
        """ Start the thread. """
        self.stream.start_stream()

    def close(self):
        """ close the thread """
        with self.lock:
            self.stop = True
        self.stream.close()
        self.py_audio.terminate()
