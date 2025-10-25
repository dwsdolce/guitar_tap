"""
    This class is inspired by:
    https://flothesof.github.io/pyqt-microphone-fft-application.html
"""

import platform

import threading
import atexit

import sounddevice as sd
import numpy as np
import numpy.typing as npt

if platform.system() == "Darwin":
    import mac_access


class Microphone:
    """Run the audio capture in a thread using the rate and buffer
    size specified. Closes on exit.
    """

    def __init__(self, parent, rate: int = 44100, chunksize: int = 16384):

        if platform.system() == "Darwin":
            mac_access.MacAccess(parent)

        self.rate: int = rate
        self.chunksize: int = chunksize
        self.stream: sd.InputStream = sd.InputStream(
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame)

        self.lock: threading.Lock = threading.Lock()
        self.is_stopped: bool = False
        self.frames: list[npt.NDArray[np.float32]] = []
        atexit.register(self.close)

    # pylint: disable=unused-argument
    def new_frame(self, data: np.ndarray, _frame_count, _time_info, _status) -> tuple[None, int]:
        """Callback used by sounddevice stream to capture the
        next buffer. If the buffers are short then this could
        be slow (append is not particularly fast)
        """
        # print(f"Microphone: new_frame: data type: {type(data)}")
        with self.lock:
            self.frames.append(data[:, 0])  # take first channel
            if self.is_stopped:
                raise sd.CallbackStop

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Get the frames that have be saved"""
        with self.lock:
            frames = self.frames
            self.frames = []
            return frames

    def start(self) -> None:
        """Start the thread."""
        self.stream.start()

    def stop(self) -> None:
        """Stop the thread."""
        with self.lock:
            self.is_stopped = True
        self.stream.stop()

    def close(self) -> None:
        """close the thread"""
        with self.lock:
            self.is_stopped = True
        self.stream.close()
