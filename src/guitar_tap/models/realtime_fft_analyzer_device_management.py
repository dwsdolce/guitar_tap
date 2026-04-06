"""
RealtimeFFTAnalyzer — Device Management
=========================================

Python counterpart to Swift ``RealtimeFFTAnalyzer+DeviceManagement.swift``.

Swift uses an extension on ``RealtimeFFTAnalyzer`` in a separate file.
Python achieves the same separation via a mixin class
``RealtimeFFTAnalyzerDeviceManagementMixin`` that ``RealtimeFFTAnalyzer``
inherits from.  The mixin provides all device-enumeration, hot-plug monitoring,
and device-switch methods.  Nothing outside this file needs to change — callers
still access everything through the ``RealtimeFFTAnalyzer`` instance.

Swift ↔ Python method correspondence:

  loadAvailableInputDevices()       ↔  load_available_input_devices()
  loadAvailableInputDevicesMacOS()  ↔  _load_available_input_devices_macos() [called internally]
  registerMacOSHardwareListener()   ↔  _start_coreaudio_monitor()
  unregisterMacOSHardwareListener() ↔  _stop_coreaudio_monitor()
  registerSampleRateListener(for:)  ↔  (no equivalent — PortAudio limitation)
  unregisterSampleRateListener()    ↔  (no equivalent — PortAudio limitation)
  handleRouteChange(notification:)  ↔  (iOS-only — not applicable)
  restartEngineAfterRouteChange()   ↔  (iOS-only — not applicable)
  setInputDevice(_:)                ↔  set_device()
  setCalibrationWithoutSavingDeviceMapping ↔ _on_calibration_changed callback fired
                                              from set_device(); handler lives in
                                              tap_tone_analyzer_control._on_mic_calibration_changed()

Recommendations from docs/DEVICE_MANAGEMENT_REFACTORING.md:
  Rec 1 — DONE: available_input_devices / selected_input_device on RealtimeFFTAnalyzer
  Rec 2 — DONE: load_available_input_devices() consolidated here
  Rec 3 — DONE: calibration auto-load in set_device() via _on_calibration_changed callback
  Rec 4 — PENDING: raw_sample_handler callback
"""

from __future__ import annotations

import platform
import threading
import time
from typing import TYPE_CHECKING

import sounddevice as sd
import numpy as np

if TYPE_CHECKING:
    from .audio_device import AudioDevice


# MARK: - Device Management Mixin

class RealtimeFFTAnalyzerDeviceManagementMixin:
    """Device management methods for RealtimeFFTAnalyzer.

    Python equivalent of the Swift RealtimeFFTAnalyzer+DeviceManagement.swift
    extension.  Mixed into RealtimeFFTAnalyzer via inheritance.

    Expects the following attributes to exist on self (set by
    RealtimeFFTAnalyzer.__init__ before the mixin methods are called):
      self.available_input_devices  : list[AudioDevice]
      self.selected_input_device    : AudioDevice | None
      self.device_index             : int | None
      self.rate                     : int
      self.chunksize                : int
      self.stream                   : sd.InputStream
      self._stop_lock               : threading.Lock
      self.is_stopped               : bool
      self._on_devices_changed      : Callable[[], None] | None
      self._monitor_stop            : threading.Event
      self._monitor_thread          : threading.Thread | None
    """

    # MARK: - Device Enumeration (mirrors loadAvailableInputDevices / loadAvailableInputDevicesMacOS)

    def load_available_input_devices(self) -> None:
        """Enumerate PortAudio input devices and update available_input_devices.

        Mirrors Swift RealtimeFFTAnalyzer.loadAvailableInputDevices() →
        loadAvailableInputDevicesMacOS().

        On initial load (available_input_devices is empty) applies the
        priority-based auto-selection policy below.  On subsequent calls
        (hot-plug) auto-selects newly appeared real devices or falls back.

        Auto-selection priority (mirrors Swift loadAvailableInputDevicesMacOS):
          1. Previously persisted device (fingerprint in AppSettings)
             Swift: UserDefaults "selectedInputDeviceUID"
          2. Built-in microphone (name contains "Built-in" or "MacBook")
             Swift: uid.contains("BuiltInMicrophone")
          3. System default PortAudio input device
             Swift: kAudioHardwarePropertyDefaultInputDevice
          4. First available device
        """
        from .audio_device import AudioDevice as _AD
        try:
            raw = list(sd.query_devices())
        except Exception:
            return

        devices: list[AudioDevice] = [
            _AD.from_sounddevice_dict(d)
            for d in raw
            if int(d["max_input_channels"]) > 0
        ]

        previous = list(self.available_input_devices)
        self.available_input_devices = devices

        if not previous:
            self._auto_select_initial_device(devices)
        else:
            self._auto_select_on_hotplug(devices, previous)

        if self._on_devices_changed is not None:
            self._on_devices_changed()

    def _auto_select_initial_device(self, devices: list) -> None:
        """Apply priority-based auto-selection on the first device enumeration.

        Mirrors the ``previousDevices.isEmpty`` branch of Swift's
        ``loadAvailableInputDevicesMacOS()``.
        """
        if not devices:
            return

        from .audio_device import AudioDevice as _AD

        # Priority 1: Previously persisted device fingerprint
        try:
            from models.app_settings import AppSettings as _AS
            saved_fp = _AS.load().selected_input_device_fingerprint
            if saved_fp:
                match = next(
                    (d for d in devices if d.fingerprint == saved_fp), None
                )
                if match:
                    self.selected_input_device = match
                    return
        except Exception:
            pass

        # Priority 2: Built-in microphone
        builtins = [
            d for d in devices
            if "built-in" in d.name.lower() or "macbook" in d.name.lower()
        ]
        if builtins:
            self.selected_input_device = builtins[0]
            return

        # Priority 3: System default PortAudio input device
        try:
            default_index = sd.default.device[0]
            if default_index is not None and default_index >= 0:
                match = next(
                    (d for d in devices if d.index == default_index), None
                )
                if match:
                    self.selected_input_device = match
                    return
        except Exception:
            pass

        # Priority 4: First available device
        self.selected_input_device = devices[0]

    def _auto_select_on_hotplug(self, devices: list, previous: list) -> None:
        """Auto-select on device connect/disconnect.

        Mirrors the ``else`` branch of Swift's ``loadAvailableInputDevicesMacOS()``.

        Newly connected real devices are auto-selected.
        Aggregate devices (name contains "CADefaultDeviceAggregate" equivalent)
        are ignored.  If the currently selected device disappeared, falls back
        to built-in or first.
        """
        previous_fps = {d.fingerprint for d in previous}
        newly_connected = [
            d for d in devices if d.fingerprint not in previous_fps
        ]
        # Ignore transient system-created aggregate devices
        real_new = [
            d for d in newly_connected
            if "aggregate" not in d.name.lower()
        ]

        if real_new:
            self.selected_input_device = real_new[0]
            return

        # If selected device disappeared, fall back
        current = self.selected_input_device
        if current is not None:
            still_present = any(d.fingerprint == current.fingerprint for d in devices)
            if not still_present:
                builtins = [
                    d for d in devices
                    if "built-in" in d.name.lower() or "macbook" in d.name.lower()
                ]
                self.selected_input_device = builtins[0] if builtins else (devices[0] if devices else None)

    # MARK: - Device Switch (mirrors setInputDevice(_:))

    def set_device(self, device: "AudioDevice") -> None:
        """Switch to a different input device and auto-load its calibration.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:) +
        selectedInputDevice.didSet (+DeviceManagement.swift).

        Swift (macOS): stops AVAudioEngine, assigns selectedInputDevice
        (guarded by isApplyingDeviceSwitch to suppress didSet restart),
        restarts the engine, then selectedInputDevice.didSet calls
        setCalibrationWithoutSavingDeviceMapping(_:) to apply the
        device-specific calibration without triggering activeCalibration.didSet.

        Python: closes and reopens the sounddevice InputStream, then looks up
        the device's calibration from CalibrationStorage and fires
        self._on_calibration_changed(cal) so the TapToneAnalyzer can apply it.
        No isApplyingDeviceSwitch / isLoadingDeviceCalibration guard is needed
        because Python has no property observers.
        """
        self._close_stream_only()
        self.device_index = device.index
        self.rate = int(device.sample_rate)
        self.selected_input_device = device
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

        # Auto-load device-specific calibration.
        # Mirrors Swift selectedInputDevice.didSet → setCalibrationWithoutSavingDeviceMapping(_:).
        # Try fingerprint key first, then fall back to name-only key for profiles
        # saved before fingerprints were introduced.
        if self._on_calibration_changed is not None:
            try:
                from models.microphone_calibration import CalibrationStorage as _CS
                cal = _CS.calibration_for_device(device.fingerprint)
                if cal is None:
                    cal = _CS.calibration_for_device(device.name)
                self._on_calibration_changed(cal)
            except Exception:
                pass

    def reinitialize_portaudio(self) -> None:
        """Stop, reinitialize PortAudio (refreshes device list), then restart.

        PortAudio caches the device list at Pa_Initialize() time.  Calling
        sd._terminate() + sd._initialize() forces a fresh enumeration so that
        sd.query_devices() reflects the current OS device list.

        If the current device is no longer available after reinit (it was
        unplugged), the stream is left closed; the caller is responsible for
        selecting a replacement via set_device().

        Python-only — Swift reloads the device list via
        loadAvailableInputDevices() which calls CoreAudio/AVAudioSession APIs
        directly (no reinit step needed).
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

    # MARK: - Hot-plug Monitoring (mirrors registerMacOSHardwareListener / routeChangeNotification)

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

        Mirrors Swift registerMacOSHardwareListener() (macOS) and the iOS
        AVAudioSession.routeChangeNotification observer setup in init.
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

        Watches kAudioHardwarePropertyDevices (0x64657623) on
        kAudioObjectSystemObject (1).

        Mirrors Swift AudioObjectAddPropertyListenerBlock on
        kAudioHardwarePropertyDevices.  The callback reference is stored in
        self._ca_cb to prevent ctypes from garbage-collecting it — mirrors
        Swift's hardwareListenerBlock stored property.
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
    # Python-only — Swift targets macOS/iOS only.

    def _start_windows_monitor(self) -> None:
        """Register a Windows device-interface arrival/removal notification.

        Uses CM_Register_Notification (cfgmgr32) to watch all device-interface
        events (CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1).

        Python-only — Swift targets macOS/iOS only.
        """
        import ctypes

        cfgmgr = ctypes.WinDLL("cfgmgr32")  # type: ignore[attr-defined]

        # CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 1
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
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
        )

        def _cb(hnotify, context, action, event_data, data_size):
            threading.Thread(
                target=self._notify_devices_changed, daemon=True
            ).start()
            return 0

        filt = _CMNotifyFilter()
        filt.cbSize = ctypes.sizeof(_CMNotifyFilter)
        filt.FilterType = 1

        self._win_cb = CB_TYPE(_cb)
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

        Python-only — Swift targets macOS/iOS only.
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
            return

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
