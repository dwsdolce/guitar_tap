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
  handleRouteChange(notification:)  ↔  (iOS-only — not applicable)
  restartEngineAfterRouteChange()   ↔  (iOS-only — not applicable)
  setInputDevice(_:)                ↔  set_device()
  setCalibrationWithoutSavingDeviceMapping ↔ _on_calibration_changed callback fired
                                              from set_device(); handler lives in
                                              tap_tone_analyzer_control._on_mic_calibration_changed()
"""

from __future__ import annotations

import atexit
import os
import platform
import signal
import threading
import time
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

from guitar_tap.utilities.logging import gt_log

# ── Timeout-protected PortAudio exit handler (POSIX only) ─────────────
# sounddevice registers an atexit handler that calls Pa_Terminate().
# On macOS, Pa_Terminate can deadlock when the CoreAudio I/O thread is
# stuck.  Replace it with a version that uses SIGALRM to bail out after
# a short timeout, then falls through to os._exit() so the process
# doesn't hang.  SIGALRM is POSIX so the same guard works on Linux;
# we enable it everywhere except Windows, which has neither SIGALRM
# nor an equivalent Pa_Terminate deadlock pattern.

if platform.system() != "Windows":
    _original_sd_exit_handler = sd._exit_handler

    def _safe_exit_handler() -> None:
        """Call sounddevice's exit handler with a timeout guard."""
        def _alarm_handler(signum, frame):
            gt_log("⚠️ PortAudio exit handler timed out — forcing exit")
            os._exit(0)

        try:
            old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(3)  # 3 second deadline
            _original_sd_exit_handler()
            signal.alarm(0)  # cancel if completed in time
            signal.signal(signal.SIGALRM, old_handler)
        except Exception:
            signal.alarm(0)

    atexit.unregister(sd._exit_handler)
    atexit.register(_safe_exit_handler)
    sd._exit_handler = _safe_exit_handler
# ──────────────────────────────────────────────────────────────────────

if TYPE_CHECKING:
    from .audio_device import AudioDevice


# MARK: - Stream Diagnostics (Python-only)

def _log_stream_diagnostics(stream: "sd.InputStream", requested_rate: int) -> int:
    """Return the actual negotiated sample rate and warn if it differs from requested.

    On Windows WASAPI in shared mode, PortAudio may silently resample to the
    device's preferred rate.  Called after every sd.InputStream open.

    Args:
        stream:         The open sd.InputStream.
        requested_rate: The sample rate passed to sd.InputStream().

    Returns:
        The actual negotiated sample rate as an int (use this for self.rate).
    """
    actual_rate = requested_rate
    try:
        actual_rate = int(stream.samplerate)
    except Exception:
        pass

    if actual_rate != requested_rate:
        gt_log(
            f"WARNING: sample rate mismatch — requested={requested_rate} Hz, "
            f"stream negotiated={actual_rate} Hz. "
            f"Frequency axis will use {actual_rate} Hz."
        )

    return actual_rate


def input_device_to_use(devices: list, saved_fingerprint: "str | None",
                        system_default_fingerprint: "str | None") -> "AudioDevice | None":
    """The input device to use from *devices*: the saved device when it is present, otherwise
    the system default input, otherwise the first device. None when there are no devices.

    Mirrors Swift ``RealtimeFFTAnalyzer.inputDeviceToUse(in:savedUID:systemDefaultUID:)``.
    """
    if saved_fingerprint:
        saved = next((d for d in devices if d.fingerprint == saved_fingerprint), None)
        if saved is not None:
            return saved
    if system_default_fingerprint:
        system_default = next(
            (d for d in devices if d.fingerprint == system_default_fingerprint), None
        )
        if system_default is not None:
            return system_default
    return devices[0] if devices else None


def _system_default_fingerprint(inputs: "list[dict]") -> "str | None":
    """Fingerprint of the system default input among *inputs* (filtered PortAudio device dicts),
    or None.

    The default is the default input of the host API the inputs are listed under — on Windows
    the filter keeps one API (WASAPI when present), whose default is Windows' default recording
    device. PortAudio's global default (``sd.default.device``) belongs to its own host API (MME
    on Windows), so it is only the fallback. Mirrors Swift reading
    kAudioHardwarePropertyDefaultInputDevice.
    """
    candidates: list[int] = []
    try:
        apis = list(sd.query_hostapis())
        for api_index in dict.fromkeys(int(d.get("hostapi", -1)) for d in inputs):
            if 0 <= api_index < len(apis):
                candidates.append(int(apis[api_index].get("default_input_device", -1)))
    except Exception:
        pass
    try:
        global_default = sd.default.device[0]
        if global_default is not None:
            candidates.append(int(global_default))
    except Exception:
        pass
    from .audio_device import AudioDevice as _AD
    for index in candidates:
        if index < 0:
            continue
        match = next((d for d in inputs if int(d["index"]) == index), None)
        if match is not None:
            return _AD.from_sounddevice_dict(match).fingerprint
    return None


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
        """Enumerate PortAudio input devices and apply them with ``apply_input_device_list``.

        Mirrors Swift RealtimeFFTAnalyzer.loadAvailableInputDevices() →
        loadAvailableInputDevicesMacOS().
        """
        from .audio_device import AudioDevice as _AD
        from .audio_device import filter_input_devices as _filter
        try:
            raw = list(sd.query_devices())
        except Exception:
            return

        # Annotate each device dict with its host API name so filter_input_devices
        # can exclude WDM-KS reliably even if a subsequent query_hostapis() call
        # inside the filter fails during a Windows device-enumeration cascade.
        try:
            apis = list(sd.query_hostapis())
            for d in raw:
                idx = int(d.get("hostapi", -1))
                if 0 <= idx < len(apis):
                    d["_hostapi_name"] = apis[idx].get("name", "")
        except Exception:
            pass

        inputs = _filter(raw)
        devices: list[AudioDevice] = [_AD.from_sounddevice_dict(d) for d in inputs]

        for d in devices:
            gt_log(f"🎤 Found input device: {d.name} @ {d.sample_rate} Hz")
        gt_log(f"🎤 Found {len(devices)} audio input device(s) total")

        self.apply_input_device_list(devices, _system_default_fingerprint(inputs))

        if self._on_devices_changed is not None:
            self._on_devices_changed()

    def apply_input_device_list(self, devices: list,
                                system_default_fingerprint: "str | None") -> None:
        """Apply a freshly enumerated device list to available_input_devices and the selection.

        - The first list: selects ``input_device_to_use``.
        - A new device that is not an aggregate device: selects it.
        - The selected device is gone: selects the system default, otherwise the first device.

        Every selection is saved (the selected_input_device setter), so what Settings shows is
        what the next launch uses. Mirrors Swift ``applyInputDeviceList``.

        Assigning selected_input_device does not open a stream; the analyzer reopens it
        (``_on_devices_refreshed_impl``) or, at construction, the stream opens on it.
        """
        from guitar_tap.views.utilities.tap_settings_view import AppSettings as _AS

        previous = list(self.available_input_devices)
        self.available_input_devices = devices

        if not previous:
            saved_fp = _AS.selected_input_device_fingerprint()
            device = input_device_to_use(devices, saved_fp, system_default_fingerprint)
            if device is None:
                return
            self.selected_input_device = device
            if device.fingerprint == saved_fp:
                gt_log(f"🎤 Restored previously selected mic: {device.name}")
            else:
                gt_log(f"🎤 Saved mic not connected — selected: {device.name}")
            return

        previous_fps = {d.fingerprint for d in previous}
        # Transient system-created aggregate devices are never auto-selected.
        newly_connected = [
            d for d in devices
            if d.fingerprint not in previous_fps and "aggregate" not in d.name.lower()
        ]
        if newly_connected:
            self.selected_input_device = newly_connected[0]
            gt_log(f"🎤 New device connected, selected: {newly_connected[0].name}")
            return

        current = self.selected_input_device
        if current is not None and not any(d.fingerprint == current.fingerprint for d in devices):
            self.selected_input_device = input_device_to_use(
                devices, None, system_default_fingerprint
            )
            chosen = self.selected_input_device
            gt_log(f"🎤 '{current.name}' disconnected, switched to: "
                   f"{chosen.name if chosen is not None else 'none'}")

    # MARK: - Device Switch (mirrors setInputDevice(_:))

    def set_device(self, device: "AudioDevice") -> None:
        """Switch to a different input device and restart the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:).

        Assigning self.selected_input_device fires the property setter which
        persists the fingerprint and auto-loads calibration — mirroring Swift's
        selectedInputDevice.didSet.
        """
        # No-op if we're already on this device with a live stream.  set_device is
        # called redundantly (e.g. _show_settings syncs the saved device on every
        # open, and the device-combo selection signal also fires), and each call
        # tears the stream down and reopens it.  Rapid open/close churns the CoreAudio
        # AUHAL into -10851 (InvalidPropertyValue) / Pa -9986 on some mics (e.g. the
        # UMIK-1), so skip the rebuild when nothing actually changed.
        if (
            device.index == getattr(self, "device_index", None)
            and getattr(self, "stream", None) is not None
            and not self.is_stopped
        ):
            return

        self._close_stream_only()
        self.device_index = device.index
        self.rate = int(device.sample_rate)
        self.selected_input_device = device  # property setter persists fingerprint + loads calibration
        gt_log(f"🎤 Device index={device.index}, native SR={device.sample_rate} Hz — switching")

        # Reset diagnostic counters so each device session is reported independently.
        self._diag_chunk_sizes_seen: set = set()
        self._diag_chunk_count: int = 0
        with self._stop_lock:
            self.is_stopped = False
        try:
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.rate,
                dtype=np.float32,
                blocksize=self.chunksize,
                callback=self.new_frame,
            )
            self.stream.start()
        except sd.PortAudioError as exc:
            # Don't raise into the UI action; leave the stream closed and log.  The
            # hot-plug refresh or the next valid selection recovers.
            gt_log(f"Could not open '{device.name}' ({exc}); stream left closed")
            self.stream = None
            return
        gt_log(f"🎤 Audio engine started")
        gt_log(f"🎤 Hardware sample rate: {self.rate} Hz, hardware channels: 1 (tap will use mono)")

        # Verify the negotiated stream rate; warns if WASAPI resampled to a different rate.
        self.rate = _log_stream_diagnostics(self.stream, self.rate)

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
        """Stop and close the audio stream without touching the hot-plug monitor.

        Uses ``abort()`` (Pa_AbortStream) instead of ``stop()``
        (Pa_StopStream) because Pa_StopStream waits for the audio I/O
        callback to finish its current invocation.  On macOS, the
        CoreAudio I/O thread can stall in native code, causing
        Pa_StopStream to block the main thread indefinitely.
        Pa_AbortStream terminates the stream immediately and avoids the
        deadlock.

        Even Pa_AbortStream can hang if the CoreAudio I/O thread is stuck
        in native code, so we run the abort/close on a daemon thread with
        a timeout.  If it doesn't complete in time we log and move on —
        the OS reclaims PortAudio resources at process exit anyway.
        """
        with self._stop_lock:
            self.is_stopped = True

        stream = self.stream

        def _do_close() -> None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        t = threading.Thread(target=_do_close, daemon=True, name="StreamClose")
        t.start()
        t.join(timeout=2.0)
        if t.is_alive():
            gt_log("⚠️ _close_stream_only: abort/close timed out after 2 s — "
                   "proceeding without waiting")

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

    # -- macOS: CoreAudio sample-rate listener (kAudioDevicePropertyNominalSampleRate) --
    # Mirrors Swift registerSampleRateListener(for:) / unregisterSampleRateListener().

    def _get_coreaudio_device_id(self, device_name: str) -> int:
        """Return the CoreAudio AudioDeviceID for a device whose name matches device_name.

        Enumerates kAudioHardwarePropertyDevices (0x64657623) on
        kAudioObjectSystemObject (1), then reads kAudioObjectPropertyName
        (0x6C6E616D) for each device.  Returns 0 if not found or on any error.

        Python equivalent of Swift's device.deviceID which is natively
        available on AVAudioEngine's input node.
        """
        try:
            import ctypes
            import ctypes.util

            _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))

            class _PropAddr(ctypes.Structure):
                _fields_ = [
                    ("mSelector", ctypes.c_uint32),
                    ("mScope",    ctypes.c_uint32),
                    ("mElement",  ctypes.c_uint32),
                ]

            # kAudioObjectSystemObject=1, kAudioHardwarePropertyDevices='dev#'=0x64657623
            # kAudioObjectPropertyScopeGlobal='glob'=0x676C6F62, mElement=0
            addr_devices = _PropAddr(0x64657623, 0x676C6F62, 0)

            # First call: get the required data size
            data_size = ctypes.c_uint32(0)
            ret = _ca.AudioObjectGetPropertyDataSize(
                ctypes.c_uint32(1),
                ctypes.byref(addr_devices),
                ctypes.c_uint32(0),
                None,
                ctypes.byref(data_size),
            )
            if ret != 0 or data_size.value == 0:
                return 0

            n_devices = data_size.value // ctypes.sizeof(ctypes.c_uint32)
            DeviceIDArray = ctypes.c_uint32 * n_devices
            device_ids = DeviceIDArray()
            ret = _ca.AudioObjectGetPropertyData(
                ctypes.c_uint32(1),
                ctypes.byref(addr_devices),
                ctypes.c_uint32(0),
                None,
                ctypes.byref(data_size),
                ctypes.byref(device_ids),
            )
            if ret != 0:
                return 0

            # kAudioObjectPropertyName = 'lnam' = 0x6C6E616D
            addr_name = _PropAddr(0x6C6E616D, 0x676C6F62, 0)

            for dev_id in device_ids:
                # AudioObjectGetPropertyData returns a CFStringRef for the name
                cf_str = ctypes.c_void_p(0)
                sz = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
                ret = _ca.AudioObjectGetPropertyData(
                    ctypes.c_uint32(dev_id),
                    ctypes.byref(addr_name),
                    ctypes.c_uint32(0),
                    None,
                    ctypes.byref(sz),
                    ctypes.byref(cf_str),
                )
                if ret != 0 or not cf_str.value:
                    continue

                # Convert CFStringRef → Python str using CoreFoundation
                _cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
                _cf.CFStringGetLength.restype = ctypes.c_long
                _cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
                _cf.CFStringGetCString.restype = ctypes.c_bool

                # kCFStringEncodingUTF8 = 0x08000100
                buf_len = _cf.CFStringGetMaximumSizeForEncoding(
                    _cf.CFStringGetLength(cf_str), 0x08000100
                ) + 1
                buf = ctypes.create_string_buffer(buf_len)
                ok = _cf.CFStringGetCString(cf_str, buf, buf_len, 0x08000100)
                _cf.CFRelease(cf_str)
                if ok:
                    name = buf.value.decode("utf-8", errors="replace")
                    if name == device_name:
                        return int(dev_id)
        except Exception:
            pass
        return 0

    # -- Windows: CM_Register_Notification (cfgmgr32, Windows 8+) ---------
    # Python-only — Swift targets macOS/iOS only.

    def _start_windows_monitor(self) -> None:
        """Register a Windows device-interface arrival/removal notification.

        Uses CM_Register_Notification (cfgmgr32) filtered to the USB audio
        device interface class GUID (KSCATEGORY_AUDIO =
        {6994AD04-93EF-11D0-A3CC-00A0C9223196}) so only real audio device
        arrivals and removals trigger the callback.

        Previously used CM_NOTIFY_FILTER_FLAG_ALL_INTERFACE_CLASSES (0x1) which
        fired on every device-interface event system-wide (USB hubs, HID, network
        adapters, and PortAudio's own stream open/close).  Filtering to the audio
        GUID eliminates those spurious callbacks.

        Python-only — Swift targets macOS/iOS only.
        """
        import ctypes
        import struct

        cfgmgr = ctypes.WinDLL("cfgmgr32")  # type: ignore[attr-defined]

        # CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 0. The Windows union is sized
        # by the DeviceInstance.InstanceId variant (200 WCHARs = 400 bytes), so
        # we must match that total size or CM_Register_Notification returns
        # CR_INVALID_DATA (0x1F).
        class _CMNotifyFilter(ctypes.Structure):
            class _U(ctypes.Union):
                class _DevIface(ctypes.Structure):
                    _fields_ = [("ClassGuid", ctypes.c_byte * 16)]

                class _DevHandle(ctypes.Structure):
                    _fields_ = [("hTarget", ctypes.c_void_p)]

                class _DevInstance(ctypes.Structure):
                    _fields_ = [("InstanceId", ctypes.c_wchar * 200)]

                _fields_ = [
                    ("DeviceInterface", _DevIface),
                    ("DeviceHandle",    _DevHandle),
                    ("DeviceInstance",  _DevInstance),
                ]

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
        filt.FilterType = 0  # CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE
        filt.Flags = 0       # 0 = filter to specific ClassGuid (not all classes)

        # KSCATEGORY_AUDIO = {6994AD04-93EF-11D0-A3CC-00A0C9223196}
        # Packed as Windows GUID: Data1(4B LE) Data2(2B LE) Data3(2B LE) Data4(8B BE)
        guid_bytes = struct.pack(
            "<IHH8s",
            0x6994AD04, 0x93EF, 0x11D0,
            bytes([0xA3, 0xCC, 0x00, 0xA0, 0xC9, 0x22, 0x31, 0x96])
        )
        ctypes.memmove(filt.u.DeviceInterface.ClassGuid, guid_bytes, 16)

        self._win_cb = CB_TYPE(_cb)
        self._win_hnotify = ctypes.c_void_p()
        self._win_cfgmgr = cfgmgr
        rc = cfgmgr.CM_Register_Notification(
            ctypes.byref(filt),
            None,
            self._win_cb,
            ctypes.byref(self._win_hnotify),
        )
        if rc != 0:
            gt_log(f"CM_Register_Notification failed (CR=0x{rc:08X}); hot-plug disabled")

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

