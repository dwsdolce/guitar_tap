"""
Real-time FFT audio analyser — mirrors Swift RealtimeFFTAnalyzer.swift.

The Swift RealtimeFFTAnalyzer class is split across four Swift files:
  RealtimeFFTAnalyzer.swift                — class declaration, init/deinit
  RealtimeFFTAnalyzer+EngineControl.swift  — start() / stop()
  RealtimeFFTAnalyzer+FFTProcessing.swift  — performFFT, computeGatedFFT,
                                             peak detection, parabolic interp, Q-factor, HPS
  RealtimeFFTAnalyzer+DeviceManagement.swift — device enumeration, CoreAudio /
                                              AVAudioSession listeners, setInputDevice

In Python, the equivalent code lives in this file:

  Microphone class        ↔  RealtimeFFTAnalyzer class
    __init__ / close      ↔  init / deinit
    start / stop          ↔  start() / stop()
    set_device            ↔  setInputDevice(_:)
    reinitialize_portaudio↔  (PortAudio-specific; no Swift equivalent)
    _start_hotplug_monitor↔  registerMacOSHardwareListener /
                              iOS routeChangeNotification observer
    _start_coreaudio_monitor ↔ AudioObjectAddPropertyListener block
    _start_windows_monitor   ↔ CM_Register_Notification
    _start_linux_monitor     ↔ (Linux-only; no Swift equivalent)
    get_frames / queue    ↔  rawSampleHandler / inputBuffer

  Free functions          ↔  RealtimeFFTAnalyzer+FFTProcessing.swift methods
    dft_anal              ↔  performFFT / computeGatedFFT (rectangular or Hann window)
    peak_detection        ↔  findPeaks — threshold + local-maximum filter
    peak_interp           ↔  findPeaks — parabolic sub-bin interpolation
    peak_q_factor         ↔  findPeaks — −3 dB bandwidth Q calculation
    hps_peak_freq         ↔  HPS dominant peak selection (plate/brace gated FFT)
    is_power2             ↔  (utility; implicit in Swift vDSP calls)

The real-time spectrum accumulation loop (Swift inputBuffer accumulation →
performFFT continuous path → @Published magnitudes) lives in fft_canvas.py.
"""

from __future__ import annotations

# ── Microphone / device management ────────────────────────────────────────────

import platform
import queue
import threading
import atexit
import time
from typing import Callable

import sounddevice as sd
import numpy as np
import numpy.typing as npt

if platform.system() == "Darwin":
    import mac_access


class Microphone:
    """Run the audio capture in a thread using the rate and buffer
    size specified. Closes on exit.

    Python equivalent of Swift RealtimeFFTAnalyzer.
    """

    def __init__(self, parent, rate: int = 44100, chunksize: int = 16384,
                 device_index: int | None = None,
                 on_devices_changed: Callable[[], None] | None = None):

        if platform.system() == "Darwin":
            mac_access.MacAccess(parent)

        self.rate: int = rate
        self.chunksize: int = chunksize
        self.device_index: int | None = device_index
        self.stream: sd.InputStream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame)

        self._stop_lock: threading.Lock = threading.Lock()
        self.is_stopped: bool = False
        self.queue: queue.Queue[npt.NDArray[np.float32]] = queue.Queue()

        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._start_hotplug_monitor()

        atexit.register(self.close)

    # pylint: disable=unused-argument
    def new_frame(self, data: np.ndarray, _frame_count, _time_info, _status) -> tuple[None, int]:
        """Callback used by sounddevice stream to capture the
        next buffer. Puts the new chunk into the queue for consumption
        by FftProcessingThread.
        """
        with self._stop_lock:
            if self.is_stopped:
                raise sd.CallbackStop
        self.queue.put(data[:, 0])  # take first channel

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Non-blocking shim that drains the queue and returns all available frames."""
        frames: list[npt.NDArray[np.float32]] = []
        try:
            while True:
                frames.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return frames

    def start(self) -> None:
        """Start the thread."""
        self.stream.start()

    def stop(self) -> None:
        """Stop the thread."""
        with self._stop_lock:
            self.is_stopped = True
        self.stream.stop()

    def set_device(self, device_index: int) -> None:
        """Switch to a different input device without re-checking permissions.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:).
        """
        self._close_stream_only()
        self.device_index = device_index
        # Use the device's native sample rate so PortAudio doesn't resample.
        try:
            info = sd.query_devices(device_index)
            native = int(info["default_samplerate"])
            if native > 0:
                self.rate = native
        except Exception:
            pass
        with self._stop_lock:
            self.is_stopped = False
        self.stream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame,
        )
        self.stream.start()

    def reinitialize_portaudio(self) -> None:
        """Stop stream, reinit PortAudio (refreshes device list), restart stream.

        PortAudio caches the device list at Pa_Initialize() time.  Calling
        sd._terminate() + sd._initialize() forces a fresh enumeration so that
        sd.query_devices() reflects the current OS device list.

        If the current device is no longer available after reinit (it was
        unplugged), the stream is left closed; the caller is responsible for
        selecting a replacement via set_device().
        """
        self._close_stream_only()
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        try:
            with self._stop_lock:
                self.is_stopped = False
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.rate,
                dtype=np.float32,
                blocksize=self.chunksize,
                callback=self.new_frame,
            )
            self.stream.start()
        except Exception:
            # Device no longer available — stream stays closed until
            # set_device() is called with a working device index.
            pass

    def close(self) -> None:
        """close the thread"""
        self._stop_hotplug_monitor()
        self._close_stream_only()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _close_stream_only(self) -> None:
        """Stop and close the audio stream without touching the hotplug monitor."""
        with self._stop_lock:
            self.is_stopped = True
        try:
            self.stream.stop()
        except Exception:
            pass
        try:
            self.stream.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Hot-plug monitoring — platform-specific implementations
    # Mirrors Swift RealtimeFFTAnalyzer+DeviceManagement.swift
    # ------------------------------------------------------------------ #

    def _notify_devices_changed(self) -> None:
        """Signal the caller that the device list has changed.

        Always invoked from a daemon thread so the OS callback returns fast.
        A brief sleep lets the OS finish its own device enumeration before
        the caller reinitializes PortAudio.
        """
        if self._on_devices_changed is None:
            return
        time.sleep(0.5)
        self._on_devices_changed()

    def _start_hotplug_monitor(self) -> None:
        if self._on_devices_changed is None:
            return
        p = platform.system()
        if p == "Darwin":
            self._start_coreaudio_monitor()
        elif p == "Windows":
            self._start_windows_monitor()
        elif p == "Linux":
            self._start_linux_monitor()

    def _stop_hotplug_monitor(self) -> None:
        self._monitor_stop.set()
        p = platform.system()
        if p == "Darwin":
            self._stop_coreaudio_monitor()
        elif p == "Windows":
            self._stop_windows_monitor()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

    # -- macOS: CoreAudio AudioObjectAddPropertyListener ------------------- #
    # Mirrors Swift registerMacOSHardwareListener()

    def _start_coreaudio_monitor(self) -> None:
        import ctypes
        import ctypes.util

        _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))

        class _PropAddr(ctypes.Structure):
            _fields_ = [
                ("mSelector", ctypes.c_uint32),
                ("mScope",    ctypes.c_uint32),
                ("mElement",  ctypes.c_uint32),
            ]

        # kAudioObjectSystemObject          = 1
        # kAudioHardwarePropertyDevices     = 'dev#' = 0x64657623
        # kAudioObjectPropertyScopeGlobal   = 'glob' = 0x676C6F62
        # kAudioObjectPropertyElementMain   = 0
        prop = _PropAddr(0x64657623, 0x676C6F62, 0)

        CB_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(_PropAddr),
            ctypes.c_void_p,
        )

        def _listener(obj, n, addrs, data):
            # Return immediately; do the real work on a daemon thread
            threading.Thread(
                target=self._notify_devices_changed, daemon=True
            ).start()
            return 0

        self._ca_cb = CB_TYPE(_listener)   # keep reference — ctypes won't
        self._ca = _ca
        self._ca_prop = prop
        _ca.AudioObjectAddPropertyListener(
            1, ctypes.byref(prop), self._ca_cb, None
        )

    def _stop_coreaudio_monitor(self) -> None:
        try:
            import ctypes
            self._ca.AudioObjectRemovePropertyListener(
                1, ctypes.byref(self._ca_prop), self._ca_cb, None
            )
        except Exception:
            pass

    # -- Windows: CM_Register_Notification (cfgmgr32, Windows 8+) --------- #

    def _start_windows_monitor(self) -> None:
        import ctypes

        cfgmgr = ctypes.WinDLL("cfgmgr32")  # type: ignore[attr-defined]

        # CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1
        # Filter on all device-interface arrivals/removals (no GUID restriction).
        class _CMNotifyFilter(ctypes.Structure):
            class _U(ctypes.Union):
                class _DevIface(ctypes.Structure):
                    _fields_ = [("ClassGuid", ctypes.c_byte * 16)]
                _fields_ = [("DeviceInterface", _DevIface)]
            _fields_ = [
                ("cbSize",     ctypes.c_ulong),
                ("Flags",      ctypes.c_ulong),
                ("FilterType", ctypes.c_ulong),
                ("Reserved",   ctypes.c_ulong),
                ("u",          _U),
            ]

        CB_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_ulong,    # DWORD return
            ctypes.c_void_p,   # HCMNOTIFICATION
            ctypes.c_void_p,   # Context
            ctypes.c_ulong,    # CM_NOTIFY_ACTION (0=arrival, 1=removal)
            ctypes.c_void_p,   # PCM_NOTIFY_EVENT_DATA
            ctypes.c_ulong,    # EventDataSize
        )

        def _cb(hnotify, context, action, event_data, data_size):
            threading.Thread(
                target=self._notify_devices_changed, daemon=True
            ).start()
            return 0

        filt = _CMNotifyFilter()
        filt.cbSize = ctypes.sizeof(_CMNotifyFilter)
        filt.FilterType = 1

        self._win_cb = CB_TYPE(_cb)    # keep reference
        self._win_hnotify = ctypes.c_void_p()
        self._win_cfgmgr = cfgmgr
        cfgmgr.CM_Register_Notification(
            ctypes.byref(filt),
            None,
            self._win_cb,
            ctypes.byref(self._win_hnotify),
        )

    def _stop_windows_monitor(self) -> None:
        try:
            self._win_cfgmgr.CM_Unregister_Notification(self._win_hnotify)
        except Exception:
            pass

    # -- Linux: udev via pyudev -------------------------------------------- #

    def _start_linux_monitor(self) -> None:
        try:
            import pyudev  # optional dependency
        except ImportError:
            return  # hot-plug detection unavailable without pyudev

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="sound")

        def _run() -> None:
            monitor.start()
            while not self._monitor_stop.is_set():
                device = monitor.poll(timeout=1.0)
                if device is not None and device.action in ("add", "remove"):
                    self._notify_devices_changed()

        self._monitor_thread = threading.Thread(target=_run, daemon=True)
        self._monitor_thread.start()


# ── FFT computation ────────────────────────────────────────────────────────────
# Mirrors Swift RealtimeFFTAnalyzer+FFTProcessing.swift and
# TapToneAnalyzer+PeakAnalysis.swift

import numpy as np          # already imported above; repeated for clarity
import numpy.typing as npt
from scipy.fft import fft

Float64_1D = npt.NDArray[np.float64]


def is_power2(num: int) -> bool:
    """Check if num is power of two."""
    return ((num & (num - 1)) == 0) and num > 0


def dft_anal(
    chunk: npt.NDArray[np.float32], window_function: Float64_1D, n_freq_samples: int
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Analysis of a signal using the discrete Fourier transform.

    x: input signal, w: analysis window, N: FFT size.
    Returns (magnitude_dB, abs_fft).

    Mirrors Swift performFFT (continuous rectangular-window path) and
    computeGatedFFT (Hann-window path for plate/brace measurements).
    """

    if not is_power2(n_freq_samples):
        raise ValueError("FFT size (N) is not a power of 2")

    if window_function.size > n_freq_samples:
        raise ValueError("Window size (M) is bigger than FFT size")

    half_n_freq_samples = (n_freq_samples // 2) + 1
    half_time_samples_1 = (window_function.size + 1) // 2
    half_time_samples_2 = window_function.size // 2

    fftbuffer = np.zeros(n_freq_samples)

    window_function = window_function / sum(window_function)
    windowed_chunk = chunk * window_function

    fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
    fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]
    complex_fft = fft(fftbuffer)

    abs_fft = abs(complex_fft[:half_n_freq_samples])
    abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps

    magnitude = 20 * np.log10(abs_fft)
    return magnitude, abs_fft


def peak_detection(
    magnitude: npt.NDArray[np.float32], threshold: int
) -> npt.NDArray[np.signedinteger]:
    """Detect spectral peak locations.

    magnitude: magnitude spectrum, t: threshold.
    Returns ploc: peak locations.

    Mirrors Swift findPeaks — threshold + local-maximum filter.
    """
    thresh_values = np.where(np.greater(magnitude[1:-1], threshold), magnitude[1:-1], 0)
    next_minor = np.where(magnitude[1:-1] > magnitude[2:], magnitude[1:-1], 0)
    prev_minor = np.where(magnitude[1:-1] > magnitude[:-2], magnitude[1:-1], 0)
    ploc = thresh_values * next_minor * prev_minor
    ploc = ploc.nonzero()[0] + 1
    return ploc


def peak_q_factor(
    magnitude: Float64_1D,
    ploc: npt.NDArray[np.signedinteger],
    iploc: Float64_1D,
    ipmag: Float64_1D,
    sample_freq: int,
    n_f: int,
) -> Float64_1D:
    """Compute Q = f0 / bandwidth for each peak using the −3 dB method.

    Walks left and right from each integer peak bin until the spectrum
    drops below peak_mag − 3 dB, then Q = f0 / (f_hi − f_lo).
    Returns 0 for peaks where the boundary is not found within the spectrum.

    Mirrors Swift findPeaks Q-factor calculation.
    """
    hz_per_bin = sample_freq / n_f
    q_values = np.zeros(len(ploc), dtype=np.float64)

    for i, peak_bin in enumerate(ploc):
        half_power = ipmag[i] - 3.0

        bin_lo = int(peak_bin) - 1
        while bin_lo > 0 and magnitude[bin_lo] > half_power:
            bin_lo -= 1

        bin_hi = int(peak_bin) + 1
        while bin_hi < len(magnitude) - 1 and magnitude[bin_hi] > half_power:
            bin_hi += 1

        bandwidth = (bin_hi - bin_lo) * hz_per_bin
        if bandwidth > 0:
            q_values[i] = (iploc[i] * hz_per_bin) / bandwidth

    return q_values


def hps_peak_freq(
    mag_linear: npt.NDArray[np.float32],
    sample_freq: float,
    n_f: int,
    f_min: float = 50.0,
    f_max: float = 2000.0,
    harmonics: int = 4,
) -> float:
    """Harmonic Product Spectrum peak-frequency estimator.

    Multiplies the spectrum by progressively downsampled copies of itself to
    reinforce the fundamental and suppress harmonics.  Returns the dominant
    fundamental frequency (Hz) within [f_min, f_max], or 0.0 if no peak is
    found.

    Mirrors Swift HPS dominant-peak selection used by computeGatedFFT.

    Args:
        mag_linear:  Linear (not dB) magnitude spectrum — the abs_fft returned
                     by dft_anal.
        sample_freq: Audio sample rate (Hz).
        n_f:         FFT size (number of samples).
        f_min:       Lower frequency search limit (Hz).
        f_max:       Upper frequency search limit (Hz).
        harmonics:   Number of harmonics to include (2 → 4 is typical).
    """
    hps = mag_linear.astype(np.float64).copy()

    for h in range(2, harmonics + 1):
        downsampled = mag_linear[::h]
        n = min(len(hps), len(downsampled))
        hps[:n] *= downsampled[:n]

    bin_min = max(1, int(f_min * n_f / sample_freq))
    bin_max = min(len(hps) - 1, int(f_max * n_f / sample_freq))

    if bin_max <= bin_min:
        return 0.0

    peak_bin = int(np.argmax(hps[bin_min : bin_max + 1])) + bin_min
    return float(peak_bin * sample_freq / n_f)


def peak_interp(
    magnitude: npt.NDArray[np.float32], ploc: npt.NDArray[np.int64]
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Interpolate peak values using parabolic interpolation.

    magnitude: magnitude spectrum, ploc: locations of peaks.
    Returns iploc, ipmag: interpolated peak location, magnitude.

    Mirrors Swift findPeaks parabolic sub-bin interpolation.
    """
    val = magnitude[ploc]
    lval = magnitude[ploc - 1]
    rval = magnitude[ploc + 1]
    iploc = ploc + 0.5 * (lval - rval) / (lval - 2 * val + rval)
    ipmag = val - 0.25 * (lval - rval) * (iploc - ploc)
    return iploc, ipmag
