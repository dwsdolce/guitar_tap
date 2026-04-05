"""
Real-time FFT audio analyser — mirrors Swift RealtimeFFTAnalyzer.swift.

The Swift RealtimeFFTAnalyzer class is split across four Swift files:
  RealtimeFFTAnalyzer.swift                — class declaration, init/deinit
  RealtimeFFTAnalyzer+EngineControl.swift  — start() / stop()
  RealtimeFFTAnalyzer+FFTProcessing.swift  — performFFT, computeGatedFFT,
                                             peak detection, parabolic interp, Q-factor, HPS
  RealtimeFFTAnalyzer+DeviceManagement.swift — device enumeration, CoreAudio /
                                              AVAudioSession listeners, setInputDevice

This Python package mirrors that structure using two modules:

  realtime_fft_analyzer.py               → RealtimeFFTAnalyzer class
      mirrors RealtimeFFTAnalyzer.swift + +EngineControl.swift + +DeviceManagement.swift

  realtime_fft_analyzer_fft_processing.py → module-level FFT functions
      mirrors RealtimeFFTAnalyzer+FFTProcessing.swift

This file (realtime_fft_analyzer.py) contains:
  - The RealtimeFFTAnalyzer class (audio capture, device management, start/stop)
  - Re-export of all FFT functions from realtime_fft_analyzer_fft_processing for
    backward compatibility (callers that do `import models.realtime_fft_analyzer as f_a`
    and call `f_a.dft_anal(...)` continue to work unchanged)
  - Microphone alias for backward compatibility with existing import sites

Python ↔ Swift correspondence:
  RealtimeFFTAnalyzer class  ↔  RealtimeFFTAnalyzer class
    __init__ / close         ↔  init / deinit
    start / stop             ↔  start() / stop()
    set_device               ↔  setInputDevice(_:)
    reinitialize_portaudio   ↔  (PortAudio-specific; no Swift equivalent)
    _start_hotplug_monitor   ↔  registerMacOSHardwareListener /
                                 iOS routeChangeNotification observer
    _start_coreaudio_monitor ↔  AudioObjectAddPropertyListener block
    _start_windows_monitor   ↔  CM_Register_Notification
    _start_linux_monitor     ↔  (Linux-only; no Swift equivalent)
    get_frames / queue       ↔  rawSampleHandler / inputBuffer

NOTE — Python vs Swift architectural differences:
  Swift uses AVAudioEngine with a tap on AVAudioInputNode; Python uses PortAudio
  via sounddevice's InputStream with a per-chunk callback.
  Swift publishes results as @Published properties on the main thread via
  DispatchQueue.main.async; Python pushes raw audio chunks into a queue.Queue
  for consumption by fft_canvas.py's FftProcessingThread.
  The real-time spectrum accumulation loop (Swift inputBuffer accumulation →
  performFFT continuous path → @Published magnitudes) lives in fft_canvas.py.
"""

from __future__ import annotations

# ── FFT function re-exports (backward compatibility) ─────────────────────────
# Existing code that does:
#   import models.realtime_fft_analyzer as f_a
#   f_a.dft_anal(...)
# continues to work unchanged.

from .realtime_fft_analyzer_fft_processing import (
    is_power2,
    dft_anal,
    peak_detection,
    peak_interp,
    peak_q_factor,
    hps_peak_freq,
    Float64_1D,
)

# ── RealtimeFFTAnalyzer / device management ───────────────────────────────────

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
    from views.utilities import platform_adapters as mac_access


class RealtimeFFTAnalyzer:
    """Real-time FFT audio analyser using PortAudio/sounddevice.

    Captures audio from a selected input device, delivers raw PCM chunks via
    ``queue`` for downstream FFT processing, and monitors device hot-plug events.

    Mirrors Swift RealtimeFFTAnalyzer (class declaration, init/deinit from
    RealtimeFFTAnalyzer.swift; start/stop from +EngineControl.swift; device
    management from +DeviceManagement.swift).

    NOTE — Python vs Swift architectural differences:
      Swift uses AVAudioEngine with a tap on AVAudioInputNode and publishes
      results as @Published properties on the main thread.
      Python uses PortAudio (sounddevice) with a blocking Queue callback model;
      downstream FFT processing is done by fft_canvas.py's FftProcessingThread.

    Python-only properties:
      queue              — audio chunk queue; Swift has rawSampleHandler + inputBuffer
      device_index       — PortAudio device index; Swift has selectedInputDevice (AVAudioDevice)
      chunksize          — PortAudio block size; Swift uses 1024-sample AVAudioEngine tap
      stream             — sounddevice.InputStream; Swift has audioEngine + inputNode
      is_stopped         — stream stop flag; Swift has isRunning (@Published)
      _stop_lock         — threading.Lock for is_stopped; Swift uses DispatchQueue sync
      _monitor_stop      — threading.Event to signal monitor thread exit
      _on_devices_changed — plain callback; Swift uses @Published availableInputDevices

    Python FFT configuration properties (mirrors Swift RealtimeFFTAnalyzer):
      fft_size    ↔  Swift fftSize      — FFT window size (power of 2)
      window_fcn  ↔  Swift window       — pre-computed window function array (length fft_size)
      m_t         ↔  (same as fft_size) — ring-buffer length; equals fft_size, matching Swift
      h_fft_size  —  Python-only fft_size // 2 convenience field

    Swift-only properties (no Python equivalent):
      audioEngine, inputNode, audioProcessingQueue, bufferAccessQueue
      magnitudes, frequencies, peakFrequency, peakMagnitude (@Published)
      inputLevelDB, displayLevelDB, recentPeakLevelDB, recentPeakTime
      actualSampleRate, hopSizeOverlap, frequencyResolution, bandwidth
      sampleLengthSeconds, frameRate, processingTimeMs, avgProcessingTimeMs
      activeCalibration, calibrationCorrections, rawSampleHandler
      fftSetup, targetSampleRate, useHardwareSampleRate
      isRunning, microphonePermissionDenied, routeChangeRestartCount
      firstBufferReceived, fftCount, engineStartTime
    """

    # MARK: - Initialization

    def __init__(self, parent, rate: int = 44100, chunksize: int = 16384,
                 device: "AudioDevice | None" = None,
                 on_devices_changed: Callable[[], None] | None = None,
                 fft_size: int = 16384):
        """Create a new real-time FFT analyser and open the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.init(fftSize:targetSampleRate:useHardwareSampleRate:).
        The Swift initialiser creates the AVAudioEngine and registers device listeners;
        this Python initialiser opens a sounddevice InputStream and starts the hot-plug monitor.

        Args:
            parent:             Parent QObject (used to anchor a MacAccess helper on macOS).
            rate:               Fallback sample rate in Hz; overridden by device.sample_rate.
            chunksize:          PortAudio block size in frames (Python-only; Swift uses 1024).
            device:             AudioDevice to open, or None for the system default.
            on_devices_changed: Callback fired on hot-plug connect/disconnect events.
                                Mirrors Swift's @Published availableInputDevices update.
            fft_size:           FFT window size (power of 2).
                                Mirrors Swift RealtimeFFTAnalyzer.fftSize.
        """
        from .audio_device import AudioDevice as _AudioDevice
        from scipy.signal import get_window as _get_window

        if platform.system() == "Darwin":
            mac_access.MacAccess(parent)

        # Python-only: PortAudio session state
        self.rate: int = int(device.sample_rate) if device else rate
        self.chunksize: int = chunksize
        self.device_index: int | None = device.index if device else None

        # MARK: - FFT Configuration (mirrors Swift RealtimeFFTAnalyzer)

        # FFT window size — must be a power of 2.
        # Mirrors Swift RealtimeFFTAnalyzer.fftSize.
        self.fft_size: int = fft_size

        # Ring-buffer length in samples — identical to fft_size, matching Swift's
        # inputBuffer which accumulates exactly fftSize samples before each FFT.
        self.m_t: int = fft_size

        # Half FFT size — number of positive-frequency bins (DC to Nyquist inclusive).
        self.h_fft_size: int = fft_size // 2

        # Window function applied to the ring buffer before the FFT.
        # Using a rectangular (boxcar) window of fft_size samples — matching Swift's
        # performFFT which applies a rectangular window of exactly fftSize samples
        # with no zero-padding.
        # See realtime_fft_analyzer_fft_processing.py for why rectangular is preferred.
        self.window_fcn = _get_window("boxcar", fft_size)

        # Open the sounddevice stream; Swift opens AVAudioEngine in start()
        self.stream: sd.InputStream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.rate,
            dtype=np.float32,
            blocksize=self.chunksize,
            callback=self.new_frame)

        # Python-only: audio chunk delivery via Queue
        # Swift delivers audio via rawSampleHandler callback + inputBuffer accumulation
        self._stop_lock: threading.Lock = threading.Lock()
        self.is_stopped: bool = False
        self.queue: queue.Queue[npt.NDArray[np.float32]] = queue.Queue()

        # Python-only: hot-plug monitoring threads
        self._on_devices_changed = on_devices_changed
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._start_hotplug_monitor()

        atexit.register(self.close)

    # MARK: - Engine Control (mirrors +EngineControl.swift)

    # pylint: disable=unused-argument
    def new_frame(self, data: np.ndarray, _frame_count, _time_info, _status) -> tuple[None, int]:
        """PortAudio stream callback — enqueues the incoming audio chunk.

        Called by PortAudio on every block of ``chunksize`` frames.
        Enqueues the first channel's samples for FftProcessingThread.

        Python-only — Swift delivers audio via an AVAudioInputNode installTap block
        that feeds ``processAudioBuffer(_:)`` on ``audioProcessingQueue``.
        """
        with self._stop_lock:
            if self.is_stopped:
                raise sd.CallbackStop
        self.queue.put(data[:, 0])  # take first channel

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Non-blocking drain: returns all audio chunks currently in the queue.

        Python-only — Swift exposes audio via ``rawSampleHandler`` and the
        ``inputBuffer`` accumulation inside ``processAudioBuffer(_:)``.
        """
        frames: list[npt.NDArray[np.float32]] = []
        try:
            while True:
                frames.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return frames

    def start(self) -> None:
        """Start the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.start() (+EngineControl.swift).
        Swift starts AVAudioEngine and installs the input tap after checking
        microphone permission; Python starts the PortAudio InputStream directly.
        """
        self.stream.start()

    def stop(self) -> None:
        """Stop the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.stop() (+EngineControl.swift).
        """
        with self._stop_lock:
            self.is_stopped = True
        self.stream.stop()

    def close(self) -> None:
        """Stop the audio stream and shut down the hot-plug monitor.

        Mirrors Swift RealtimeFFTAnalyzer.deinit.
        """
        self._stop_hotplug_monitor()
        self._close_stream_only()

    # MARK: - Device Management (mirrors +DeviceManagement.swift)

    def set_device(self, device: "AudioDevice") -> None:
        """Switch to a different input device without re-checking permissions.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:) (+DeviceManagement.swift).
        Swift restarts AVAudioEngine with the new device set via CoreAudio AUHAL
        on macOS or AVAudioSession.setPreferredInput on iOS; Python closes and
        reopens the sounddevice InputStream.
        """
        from .audio_device import AudioDevice as _AudioDevice
        self._close_stream_only()
        self.device_index = device.index
        self.rate = int(device.sample_rate)
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
        """Stop, reinitialize PortAudio (refreshes device list), then restart the stream.

        PortAudio caches the device list at Pa_Initialize() time.  Calling
        sd._terminate() + sd._initialize() forces a fresh enumeration so that
        sd.query_devices() reflects the current OS device list.

        If the current device is no longer available after reinit (it was
        unplugged), the stream is left closed; the caller is responsible for
        selecting a replacement via set_device().

        Python-only — Swift reloads the device list via loadAvailableInputDevices()
        which calls CoreAudio/AVAudioSession APIs directly.
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

    # MARK: - Internal Helpers

    def _close_stream_only(self) -> None:
        """Stop and close the audio stream without touching the hot-plug monitor."""
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

    # MARK: - Hot-plug Monitoring (mirrors +DeviceManagement.swift)
    #
    # Swift registers:
    #   macOS — AudioObjectAddPropertyListenerBlock on kAudioHardwarePropertyDevices
    #   iOS   — AVAudioSession.routeChangeNotification observer
    # Python registers the OS-appropriate listener on a background thread.

    def _notify_devices_changed(self) -> None:
        """Signal the caller that the device list has changed.

        Always invoked from a daemon thread so the OS callback returns fast.
        A brief sleep lets the OS finish its own device enumeration before
        the caller reinitializes PortAudio.

        Mirrors the body of Swift's hardwareListenerBlock / handleRouteChange
        which calls loadAvailableInputDevices() on the main thread.
        """
        if self._on_devices_changed is None:
            return
        time.sleep(0.5)
        self._on_devices_changed()

    def _start_hotplug_monitor(self) -> None:
        """Start the platform-appropriate hot-plug monitor.

        Mirrors Swift registerMacOSHardwareListener() and the iOS
        routeChangeNotification observer setup in init.
        """
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
        """Stop the platform-appropriate hot-plug monitor.

        Mirrors Swift unregisterMacOSHardwareListener() and the iOS
        NotificationCenter.removeObserver call in deinit.
        """
        self._monitor_stop.set()
        p = platform.system()
        if p == "Darwin":
            self._stop_coreaudio_monitor()
        elif p == "Windows":
            self._stop_windows_monitor()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

    # -- macOS: CoreAudio AudioObjectAddPropertyListener -------------------
    # Mirrors Swift registerMacOSHardwareListener() in +DeviceManagement.swift.

    def _start_coreaudio_monitor(self) -> None:
        """Register a CoreAudio property listener for device connect/disconnect.

        Watches kAudioHardwarePropertyDevices (0x64657623) on kAudioObjectSystemObject (1).
        Mirrors Swift's AudioObjectAddPropertyListenerBlock on
        kAudioObjectPropertyAddress(selector: .hardwarePropertyDevices).
        """
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
        """Unregister the CoreAudio property listener.

        Mirrors Swift unregisterMacOSHardwareListener().
        """
        try:
            import ctypes
            self._ca.AudioObjectRemovePropertyListener(
                1, ctypes.byref(self._ca_prop), self._ca_cb, None
            )
        except Exception:
            pass

    # -- Windows: CM_Register_Notification (cfgmgr32, Windows 8+) ---------

    def _start_windows_monitor(self) -> None:
        """Register a Windows device-interface arrival/removal notification.

        Python-only — Swift targets macOS/iOS only.
        Uses CM_Register_Notification (cfgmgr32) to watch all device-interface
        events (CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1).
        """
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
        """Unregister the Windows CM_Register_Notification handle.

        Python-only.
        """
        try:
            self._win_cfgmgr.CM_Unregister_Notification(self._win_hnotify)
        except Exception:
            pass

    # -- Linux: udev via pyudev --------------------------------------------
    # Python-only — Swift targets macOS/iOS only.

    def _start_linux_monitor(self) -> None:
        """Monitor Linux udev 'sound' subsystem events for device changes.

        Requires the optional ``pyudev`` package; silently disabled if absent.
        Python-only — Swift targets macOS/iOS only.
        """
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


# ── Backward-compatibility alias ─────────────────────────────────────────────
# Existing code that does:
#   from models.realtime_fft_analyzer import Microphone
# continues to work unchanged.

Microphone = RealtimeFFTAnalyzer
