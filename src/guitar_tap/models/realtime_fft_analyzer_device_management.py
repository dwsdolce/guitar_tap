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


# MARK: - Stream Open

def _wasapi_raw_settings(device_index: "int | None") -> "sd.WasapiSettings | None":
    """WASAPI settings that request a RAW stream, or None when *device_index* is not a WASAPI device.

    RAW skips the Windows audio effects (Settings → Sound → Audio enhancements: "Device default
    effects", Voice Clarity, vendor noise suppression). Those gate and suppress taps as noise: on
    one Acer laptop they cost ~70 dB on every shared-mode path. Swift gets the
    same result on iOS from the `.measurement` session mode; the web edition from turning off
    echoCancellation / noiseSuppression / autoGainControl.

    sounddevice has no RAW option, so this sets PaWasapiStreamInfo.streamOption directly; the
    struct version must stay 1 (PortAudio rejects any other).
    """
    if platform.system() != "Windows":
        return None
    try:
        dev = sd.query_devices(device_index, "input")
        if sd.query_hostapis(int(dev["hostapi"]))["name"] != "Windows WASAPI":
            return None
        settings = sd.WasapiSettings()
        settings._streaminfo.streamOption = sd._lib.eStreamOptionRaw
        return settings
    except Exception as exc:   # a sounddevice without these internals: open without RAW
        gt_log(f"⚠️ WASAPI RAW mode unavailable ({exc}) — Windows audio effects stay on")
        return None


def _open_input_stream(device_index: "int | None", rate: int, blocksize: int, callback) -> "sd.InputStream":
    """Open (not start) the mono float32 input stream — in WASAPI RAW mode on Windows, falling
    back to a plain open if the device refuses RAW. Raises sd.PortAudioError if neither opens."""
    kw = dict(device=device_index, channels=1, samplerate=rate, dtype=np.float32,
              blocksize=blocksize, callback=callback)
    raw = _wasapi_raw_settings(device_index)
    if raw is not None:
        try:
            stream = sd.InputStream(extra_settings=raw, **kw)
            gt_log("🎤 WASAPI RAW stream (Windows audio effects bypassed)")
            return stream
        except sd.PortAudioError as exc:
            gt_log(f"⚠️ WASAPI RAW open failed ({exc}) — opening without RAW")
    return sd.InputStream(**kw)


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


def failed_open_message(name: str) -> str:
    """The message shown when an input device cannot be opened. Mirrors Swift
    ``RealtimeFFTAnalyzer.failedOpenMessage(for:)``."""
    return (f"Could not open the microphone '{name}'. The previous input is still in use — "
            f"please check the microphone.")


class InputDeviceOpenError(Exception):
    """An input device could not be opened; the previous device is still selected and in use."""

    def __init__(self, device_name: str) -> None:
        super().__init__(failed_open_message(device_name))
        self.device_name = device_name


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
        if current is None:
            return
        fresh = next((d for d in devices if d.fingerprint == current.fingerprint), None)
        if fresh is None:
            self.selected_input_device = input_device_to_use(
                devices, None, system_default_fingerprint
            )
            chosen = self.selected_input_device
            gt_log(f"🎤 '{current.name}' disconnected, switched to: "
                   f"{chosen.name if chosen is not None else 'none'}")
        elif fresh.index != current.index:
            # The same device, renumbered: PortAudio numbers devices by position and renumbers them
            # when it is re-initialised, so the selection takes the fresh entry — its index is what
            # the stream is opened with. Not a new selection: nothing is saved or reloaded.
            self._selected_input_device = fresh

    # MARK: - Device Switch (mirrors setInputDevice(_:))

    def set_device(self, device: "AudioDevice") -> None:
        """Switch to a different input device and restart the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:) / switchInputDevice(to:open:).

        Assigning self.selected_input_device fires the property setter which saves the device and
        auto-loads its calibration — mirroring Swift's selectedInputDevice.didSet. If the device
        cannot be opened, the previous device is selected and opened again and
        ``InputDeviceOpenError`` is raised, so a device that cannot be used is never left selected
        or saved.
        """
        # No-op if we're already on this device with a live stream.  set_device is
        # called redundantly (e.g. the device-combo selection signal and a refresh), and each call
        # tears the stream down and reopens it.  Rapid open/close churns the CoreAudio
        # AUHAL into -10851 (InvalidPropertyValue) / Pa -9986 on some mics (e.g. the
        # UMIK-1), so skip the rebuild when nothing actually changed.
        if (
            device.index == getattr(self, "device_index", None)
            and getattr(self, "stream", None) is not None
            and not self.is_stopped
        ):
            return

        previous = self._selected_input_device
        try:
            self._open_device(device)
        except sd.PortAudioError as exc:
            gt_log(f"❌ Could not open '{device.name}' ({exc}) — keeping "
                   f"'{previous.name if previous is not None else 'none'}'")
            if previous is not None and previous.fingerprint != device.fingerprint:
                try:
                    self._open_device(previous)
                except sd.PortAudioError as exc2:
                    gt_log(f"Could not reopen '{previous.name}' ({exc2}); stream left closed")
            raise InputDeviceOpenError(device.name) from exc

    def _open_device(self, device: "AudioDevice") -> None:
        """Select *device* (the setter saves it and loads its calibration) and open its stream.
        Raises sd.PortAudioError, with the stream left closed, if it cannot be opened."""
        self._close_stream_only()
        self.device_index = device.index
        self.rate = int(device.sample_rate)
        self.selected_input_device = device
        gt_log(f"🎤 Device index={device.index}, native SR={device.sample_rate} Hz — switching")

        # Reset diagnostic counters so each device session is reported independently.
        self._diag_chunk_sizes_seen: set = set()
        self._diag_chunk_count: int = 0
        with self._stop_lock:
            self.is_stopped = False
        try:
            self.stream = _open_input_stream(self.device_index, self.rate, self.chunksize, self.new_frame)
            self.stream.start()
        except sd.PortAudioError:
            self.stream = None
            raise
        gt_log(f"🎤 Audio engine started")
        gt_log(f"🎤 Hardware sample rate: {self.rate} Hz, hardware channels: 1 (tap will use mono)")

        # Verify the negotiated stream rate; warns if WASAPI resampled to a different rate.
        self.rate = _log_stream_diagnostics(self.stream, self.rate)

    def reinitialize_portaudio(self) -> None:
        """Stop, reinitialize PortAudio (refreshes device list), then reopen the selected device.

        PortAudio caches the device list at Pa_Initialize() time.  Calling
        sd._terminate() + sd._initialize() forces a fresh enumeration so that
        sd.query_devices() reflects the current OS device list — and renumbers the devices, so the
        selected device is looked up again by its fingerprint before its stream is opened.

        Raises ``InputDeviceOpenError`` if the selected device is no longer listed or cannot be
        opened (the stream is left closed); the watchdog counts that as a failed attempt.

        Python-only — Swift reloads the device list via
        loadAvailableInputDevices() which calls CoreAudio/AVAudioSession APIs
        directly (no reinit step needed).
        """
        self._close_stream_only()
        self.terminate_and_reinitialize_portaudio()
        selected = self._selected_input_device
        if selected is None:
            raise InputDeviceOpenError("none")
        fresh = self._listed_device(selected.fingerprint)
        if fresh is None:
            self.stream = None
            raise InputDeviceOpenError(selected.name)
        self._selected_input_device = fresh  # the same device, as PortAudio now numbers it
        self.device_index = fresh.index
        self.rate = int(fresh.sample_rate)
        try:
            with self._stop_lock:
                self.is_stopped = False
            self.stream = _open_input_stream(self.device_index, self.rate, self.chunksize, self.new_frame)
            self.stream.start()
        except sd.PortAudioError as exc:
            self.stream = None
            raise InputDeviceOpenError(fresh.name) from exc
        self.rate = _log_stream_diagnostics(self.stream, self.rate)
        # The selected device may have changed while the restart was pending (a hot-plug refresh only
        # updates the selection then), so the listener re-reads the device and its rate.
        on_reopened = getattr(self, "_on_stream_reopened", None)
        if on_reopened is not None:
            on_reopened()

    def terminate_and_reinitialize_portaudio(self) -> bool:
        """Terminate and re-initialise PortAudio, so its device list is current. Returns False —
        and does neither — while a stream close is still pending: terminating waits for every
        stream to finish, and a close that timed out never does (on macOS, a stuck CoreAudio I/O
        thread), so it would block the calling thread for good."""
        pending = getattr(self, "_pending_stream_close", None)
        if pending is not None and pending.is_alive():
            gt_log("⚠️ A stream close is still pending — PortAudio not re-initialised "
                   "(terminating would wait on it); it is retried when the close finishes")
            self._portaudio_reinit_owed = True
            return False
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        self._portaudio_reinit_owed = False
        return True

    def _retry_owed_reinit(self) -> bool:
        """Ask for the device refresh a pending close made ``terminate_and_reinitialize_portaudio``
        skip, once no close is pending. Called when the stuck close finishes and on every
        watchdog tick; the refresh re-initialises PortAudio and clears the debt. Returns whether
        it asked."""
        if not getattr(self, "_portaudio_reinit_owed", False):
            return False
        pending = getattr(self, "_pending_stream_close", None)
        if pending is not None and pending.is_alive():
            return False
        callback = getattr(self, "_on_devices_changed", None)
        if callback is None:
            return False
        gt_log("🔄 Retrying the PortAudio re-initialise skipped while a stream close was pending")
        callback()
        return True

    def _listed_device(self, fingerprint: str) -> "AudioDevice | None":
        """The listed input device with *fingerprint*, as PortAudio numbers it now, or None."""
        from .audio_device import AudioDevice as _AD
        from .audio_device import filter_input_devices as _filter
        try:
            for d in _filter(list(sd.query_devices())):
                device = _AD.from_sounddevice_dict(d)
                if device.fingerprint == fingerprint:
                    return device
        except Exception:
            pass
        return None

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
            # A close that outlived its timeout may have made a re-initialise wait; now that it has
            # finished, that re-initialise can run.
            if getattr(self, "_pending_stream_close", None) is threading.current_thread():
                self._pending_stream_close = None
                self._retry_owed_reinit()

        t = threading.Thread(target=_do_close, daemon=True, name="StreamClose")
        t.start()
        t.join(timeout=2.0)
        if t.is_alive():
            gt_log("⚠️ _close_stream_only: abort/close timed out after 2 s — "
                   "proceeding without waiting")
            # Remembered so PortAudio is not terminated while it is still pending.
            self._pending_stream_close = t

    # MARK: - Hot-plug Monitoring (mirrors registerMacOSHardwareListener / routeChangeNotification)

    def _notify_devices_changed(self) -> None:
        """Signal the caller that the device list has changed.

        Always invoked from a daemon thread so the OS callback returns fast.
        A brief sleep lets the OS finish its own device enumeration before
        the caller reinitializes PortAudio.

        Mirrors the body of Swift's hardwareListenerBlock / handleRouteChange
        which calls loadAvailableInputDevices() on the main thread.
        """
        gt_log("🔌 Device change reported by the system")
        if self._on_devices_changed is None:
            gt_log("🔌 Device change dropped — no handler connected")
            return
        time.sleep(0.5)
        callback = self._on_devices_changed
        if callback is None:
            gt_log("🔌 Device change dropped — handler disconnected during an enumeration")
            return
        callback()

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
        """Start the Windows hot-plug monitor: MMDevice endpoint events, else cfgmgr32.

        MMDevice is the correct source and cfgmgr32 is the fallback, not the other way
        round. ``CM_Register_Notification`` reports that a USB *device interface* arrived;
        what we need to know is that an audio *endpoint* became active, which happens
        later. Measured, a UMIK-1 plug-in produces:

            t=9.275  OnPropertyValueChanged x7      <- 28 ms EARLY, must be ignored
            t=9.303  OnDeviceStateChanged ACTIVE    <- the real event
            t=9.336  OnDefaultDeviceChanged x3 (capture)
                     PortAudio enumerates the device from here on

        Acting on the interface arrival meant re-enumerating before PortAudio could see
        the device, so nothing was selected; the later notification that would have found
        it was then dropped by the caller's cooldown. Hence the microphone never switched.

        With endpoint events there is no settle delay to choose: the event and PortAudio's
        WASAPI enumeration read the same list, so a refresh triggered by ACTIVE finds the
        device. No timing constant is introduced here.
        """
        if self._start_windows_mmdevice_monitor():
            self._hotplug_kind = "mmdevice"
            return
        self._start_windows_cm_monitor()
        self._hotplug_kind = "cm"

    def _start_windows_mmdevice_monitor(self) -> bool:
        """Register an IMMNotificationClient for audio endpoint changes.

        Returns True when the monitor is running. comtypes is a Windows-only dependency
        declared in requirements.txt; if it is missing the caller falls back to cfgmgr32
        (the same optional-import shape as pyudev on Linux).

        Threading: comtypes CoInitializes the importing thread as an STA, and an STA
        callback object only receives calls while a message pump runs. Registration
        therefore happens on a dedicated thread that joins the MTA, where callbacks arrive
        directly on COM worker threads.
        """
        try:
            import comtypes
            from comtypes import COMMETHOD, GUID, COMObject, IUnknown
            from comtypes.client import CreateObject
        except ImportError:
            gt_log("🔌 comtypes not installed — falling back to the cfgmgr32 monitor")
            return False

        import ctypes
        from ctypes import POINTER, Structure, c_wchar_p

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        class IMMNotificationClient(IUnknown):
            _iid_ = GUID("{7991EEC9-7E89-4D85-8390-6C703CEC60C0}")
            _methods_ = [
                COMMETHOD([], comtypes.HRESULT, "OnDeviceStateChanged",
                          (["in"], c_wchar_p, "pwstrDeviceId"),
                          (["in"], ctypes.c_ulong, "dwNewState")),
                COMMETHOD([], comtypes.HRESULT, "OnDeviceAdded",
                          (["in"], c_wchar_p, "pwstrDeviceId")),
                COMMETHOD([], comtypes.HRESULT, "OnDeviceRemoved",
                          (["in"], c_wchar_p, "pwstrDeviceId")),
                COMMETHOD([], comtypes.HRESULT, "OnDefaultDeviceChanged",
                          (["in"], ctypes.c_uint, "flow"),
                          (["in"], ctypes.c_uint, "role"),
                          (["in"], c_wchar_p, "pwstrDefaultDeviceId")),
                COMMETHOD([], comtypes.HRESULT, "OnPropertyValueChanged",
                          (["in"], c_wchar_p, "pwstrDeviceId"),
                          (["in"], PROPERTYKEY, "key")),
            ]

        class IMMDeviceEnumerator(IUnknown):
            # Only the slots up to the two we call; declaration order sets the offsets.
            _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            _methods_ = [
                COMMETHOD([], comtypes.HRESULT, "EnumAudioEndpoints",
                          (["in"], ctypes.c_uint, "dataFlow"),
                          (["in"], ctypes.c_ulong, "dwStateMask"),
                          (["out"], POINTER(POINTER(IUnknown)), "ppDevices")),
                COMMETHOD([], comtypes.HRESULT, "GetDefaultAudioEndpoint",
                          (["in"], ctypes.c_uint, "dataFlow"),
                          (["in"], ctypes.c_uint, "role"),
                          (["out"], POINTER(POINTER(IUnknown)), "ppEndpoint")),
                COMMETHOD([], comtypes.HRESULT, "GetDevice",
                          (["in"], c_wchar_p, "pwstrId"),
                          (["out"], POINTER(POINTER(IUnknown)), "ppDevice")),
                COMMETHOD([], comtypes.HRESULT, "RegisterEndpointNotificationCallback",
                          (["in"], POINTER(IMMNotificationClient), "pClient")),
                COMMETHOD([], comtypes.HRESULT, "UnregisterEndpointNotificationCallback",
                          (["in"], POINTER(IMMNotificationClient), "pClient")),
            ]

        analyzer = self

        class _NotificationClient(COMObject):
            """Endpoint events only. Property changes are ignored, deliberately.

            They are the majority of the traffic (21 of 25 events in the measured
            plug-in/unplug cycle) and they fire BEFORE the endpoint is active, so acting
            on them reproduces the very race this replaces.
            """

            _com_interfaces_ = [IMMNotificationClient]

            def IMMNotificationClient_OnDeviceStateChanged(self, this, pwstrDeviceId, dwNewState):
                analyzer._mmdevice_event(f"state={dwNewState}")
                return 0

            def IMMNotificationClient_OnDeviceAdded(self, this, pwstrDeviceId):
                analyzer._mmdevice_event("added")
                return 0

            def IMMNotificationClient_OnDeviceRemoved(self, this, pwstrDeviceId):
                analyzer._mmdevice_event("removed")
                return 0

            def IMMNotificationClient_OnDefaultDeviceChanged(self, this, flow, role, pwstrId):
                # Ignored, like property changes. It reports which device Windows now
                # PREFERS, never a change to the device list: plugging one microphone in
                # fires it three times (console, multimedia, communications) right after
                # the state change we already acted on, and each one drove a full
                # PortAudio re-init, stream reopen and detection reset. The fallback that
                # does care about the system default - an unplug of the device in use -
                # reads it at enumeration time, driven by OnDeviceStateChanged.
                return 0

            def IMMNotificationClient_OnPropertyValueChanged(self, this, pwstrDeviceId, key):
                return 0

        started = threading.Event()
        self._mm_client = None
        self._monitor_stop.clear()

        def _run() -> None:
            enumerator = None
            client = None
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                enumerator = CreateObject(
                    GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),  # CLSID_MMDeviceEnumerator
                    interface=IMMDeviceEnumerator,
                )
                client = _NotificationClient()
                enumerator.RegisterEndpointNotificationCallback(client)
                self._mm_client = client        # keep alive; COM holds only a raw pointer
                self._mm_enumerator = enumerator
                started.set()
            except Exception as exc:  # noqa: BLE001 - any COM failure falls back
                gt_log(f"🔌 MMDevice monitor failed to start ({exc!r})")
                started.set()
                return
            self._monitor_stop.wait()
            try:
                enumerator.UnregisterEndpointNotificationCallback(client)
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass

        self._monitor_thread = threading.Thread(
            target=_run, daemon=True, name="mmdevice-monitor"
        )
        self._monitor_thread.start()
        started.wait(5.0)
        if getattr(self, "_mm_client", None) is None:
            return False
        gt_log("🔌 Watching audio endpoint changes (MMDevice)")
        return True

    def _mmdevice_event(self, what: str) -> None:
        """An endpoint event arrived on a COM worker thread.

        Does no work here: the callback must return promptly, and re-initializing
        PortAudio inside it is how the first version of the diagnostic probe made its own
        events disappear. Hands off to a daemon thread exactly as the CoreAudio listener
        does — but with no settle sleep, because an endpoint event already means the
        device list has changed.
        """
        gt_log(f"🔌 Audio endpoint change ({what})")
        threading.Thread(
            target=self._notify_devices_changed_now, daemon=True
        ).start()

    def _notify_devices_changed_now(self) -> None:
        """Signal the caller immediately (Windows/MMDevice only).

        Deliberately a separate method rather than a parameter on
        _notify_devices_changed: that one is shared with the CoreAudio and udev monitors,
        whose 0.5 s settle sleep is part of behaviour validated on those platforms.
        """
        if self._on_devices_changed is None:
            gt_log("🔌 Device change dropped — no handler connected")
            return
        callback = self._on_devices_changed
        if callback is None:
            return
        callback()

    def _start_windows_cm_monitor(self) -> None:
        """FALLBACK: register a Windows device-interface arrival/removal notification.

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
        """Stop whichever Windows monitor is running.

        _monitor_stop is already set by the caller, which releases the MMDevice thread
        from its wait; it unregisters the callback itself, on the apartment that
        registered it. Python-only — Swift targets macOS/iOS only.
        """
        self._mm_client = None
        self._mm_enumerator = None
        try:
            self._win_cfgmgr.CM_Unregister_Notification(self._win_hnotify)
        except Exception:
            pass

    # -- Linux: hot-plug is NOT supported, deliberately (2026-09-28) -------
    # Python-only — Swift targets macOS/iOS only.

    def _start_linux_monitor(self) -> None:
        """Deliberately does nothing. Linux does not hot-plug. Please do not re-implement.

        This is a decision, not an omission and not a TODO.

        A udev monitor lived here from 2026-03-22. It never ran for anybody: the import was
        ``try: import pyudev / except ImportError: return`` and ``pyudev`` was never declared
        in requirements.txt, pyproject.toml or the PyInstaller spec, so every install - source
        or AppImage - took the early return. Hot-plug on Linux has therefore never shipped,
        and the release notes only ever claimed it for Windows and macOS.

        In September 2026 it was made to work, and then removed again. Getting the events
        right turned out to be the easy half, and is measurable: udev emits its sound events
        3-20 ms *after* creating the /dev/snd nodes, the uaccess ACL that makes those nodes
        readable lands 6-10 ms later, and that ACL - not the node, and not any single event -
        is when PortAudio can first enumerate the card. The node-to-ACL interval measured
        20 ms, 42 ms and 214 ms on consecutive plug cycles of one idle machine, which is why
        a fixed settle sleep cannot be right for every machine.

        The device list underneath those events is the part that does not work:

        * PortAudio's Linux enumeration lists raw ALSA ``hw:`` devices alongside PipeWire's
          ``default`` / ``pipewire`` / ``sysdefault`` aliases, and filter_input_devices keeps
          everything with max_input_channels > 0 - the careful Windows pruning above does not
          apply to Linux at all.
        * Whenever PipeWire holds a card, that card reports 0 input channels and drops out of
          the list. Confirmed directly: ``fuser /dev/snd/pcmC0D0c`` shows pipewire holding it
          while ``arecord -D hw:0,0`` answers "Device or resource busy".
        * PipeWire moves its active source by itself - it auto-switches to a newly plugged
          microphone and suspends idle ones - so devices enter and leave the list with no
          hardware change whatsoever. One session was observed going 5 -> 4 -> 3 -> 2 devices.
        * A device that reappears because PipeWire released it is indistinguishable from one
          just plugged in, so apply_input_device_list's ``newly_connected`` branch selects it,
          and because every selection is saved it also becomes what the next launch uses.
          A selection the user never made then becomes what the next launch restores - which is
          why leaving hot-plug half-working is worse than not having it.

        Fixing that means deciding what Linux should enumerate at all - PipeWire's sources
        rather than raw hw: devices - a design change with consequences for what users can
        pick, needing verification on real hardware. Judged not worth the effort against a
        Linux user base that may well be empty, when macOS and Windows both work.

        What Linux gets instead is the contract Windows shipped with for a time: the device
        list is built at startup, and a microphone connected later is selected by opening
        Settings and choosing it. Documented in docs/ReleaseNotes.md and the user manual.
        """
        return

