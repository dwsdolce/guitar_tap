# Device Management Refactoring: Python → Swift Alignment

Recommendations for bringing `RealtimeFFTAnalyzer` and related Python code
closer to the Swift `RealtimeFFTAnalyzer+DeviceManagement.swift` architecture.

---

## Background

Swift's `RealtimeFFTAnalyzer` owns the full device-management lifecycle:

- `@Published var availableInputDevices: [AVAudioDevice]` — the live list
- `@Published var selectedInputDevice: AVAudioDevice?` — with a `didSet` that
  auto-loads calibration and restarts the engine
- `loadAvailableInputDevices()` → `loadAvailableInputDevicesMacOS()` /
  `loadAvailableInputDevicesIOS()` — enumerate, filter, auto-select, publish
- `registerMacOSHardwareListener()` / iOS route-change observer — drive
  re-enumeration on connect/disconnect

The Python code distributes these responsibilities across:

| Concern | Python location |
|---|---|
| Device data model | `models/audio_device.py` |
| Enumeration (on demand) | `audio_device.AudioDevice.resolve()` |
| Hot-plug listener | `realtime_fft_analyzer.RealtimeFFTAnalyzer._start_coreaudio_monitor()` |
| Device list assembly | `tap_tone_analyzer_control._on_devices_refreshed()` |
| Auto-select on hot-plug | `tap_tone_analyzer_control._on_devices_refreshed()` |
| Calibration auto-load on device change | `tap_tone_analyzer_control.set_device()` |
| Scattered `sd.query_devices()` calls | `tap_tone_analysis_view.py` (multiple sites) |

---

## Recommendation 1 — Add `available_input_devices` and `selected_input_device` to `RealtimeFFTAnalyzer` ✅ DONE

**Status:** Implemented. `available_input_devices` and `selected_input_device` are
now properties on `RealtimeFFTAnalyzer.__init__`. The view layer reads from
`mic.available_input_devices` instead of calling `sd.query_devices()` directly.

**Files changed:** `realtime_fft_analyzer.py`, `realtime_fft_analyzer_device_management.py`

---

**Original recommendation:**

**Current state:** No single object owns the live device list. It is assembled
on demand in `_on_devices_refreshed` (control mixin) and by direct
`sd.query_devices()` calls scattered across the view layer.

**Swift equivalent:** `RealtimeFFTAnalyzer` owns both properties as
`@Published` vars. Everything reads from there.

**Change:** Add to `RealtimeFFTAnalyzer.__init__`:

```python
self.available_input_devices: list[AudioDevice] = []
self.selected_input_device: AudioDevice | None = None
```

Call a new `load_available_input_devices()` method (see Recommendation 2)
at the end of `__init__`, exactly as Swift calls `loadAvailableInputDevices()`
in `init`. Have `_notify_devices_changed` update `self.available_input_devices`
and call the existing `_on_devices_changed` callback with the new list object,
rather than emitting a signal with just device names.

**Benefit:** Eliminates the scattered `sd.query_devices()` calls in the view
layer. The view asks `mic.available_input_devices` instead of calling
`sd.query_devices()` directly — matching Swift's model.

---

## Recommendation 2 — Consolidate enumeration into `RealtimeFFTAnalyzer.load_available_input_devices()` ✅ DONE

**Status:** Implemented. All device enumeration now lives in
`RealtimeFFTAnalyzerDeviceManagementMixin.load_available_input_devices()` in
`realtime_fft_analyzer_device_management.py`. The duplicate logic previously
split across `audio_device.py` and `tap_tone_analyzer_control.py` has been
consolidated. Hot-plug handling is also unified here via `_auto_select_on_hotplug`.

**Files changed:** `realtime_fft_analyzer_device_management.py` (new file with mixin),
`realtime_fft_analyzer.py` (inherits mixin, device methods removed)

---

**Original recommendation:**

**Current state:** The three-step sequence of call `sd.query_devices()`,
filter for `max_input_channels > 0`, construct `AudioDevice` objects, and
apply the auto-selection priority policy is repeated across
`audio_device.AudioDevice.resolve()`, `_on_devices_refreshed`, and the view.

**Swift equivalent:** One method — `loadAvailableInputDevicesMacOS()` — owns
all of: enumerate via CoreAudio, filter for input channels, read name/UID/
sample-rate, apply the four-priority auto-selection policy, and update
`availableInputDevices` / `selectedInputDevice`.

**Change:** Add to `RealtimeFFTAnalyzer` (mirrors `loadAvailableInputDevicesMacOS`):

```python
def load_available_input_devices(self) -> None:
    """Enumerate PortAudio input devices and update available_input_devices.

    Mirrors Swift RealtimeFFTAnalyzer.loadAvailableInputDevices() →
    loadAvailableInputDevicesMacOS().

    Auto-selection priority (mirrors Swift):
      1. Previously persisted device (fingerprint stored in AppSettings)
      2. Built-in microphone (name contains "Built-in" or "MacBook")
      3. First available device
    """
    import sounddevice as _sd
    from .audio_device import AudioDevice as _AD
    try:
        raw = list(_sd.query_devices())
    except Exception:
        return
    devices = [
        _AD.from_sounddevice_dict(d)
        for d in raw
        if int(d["max_input_channels"]) > 0
    ]
    previous = self.available_input_devices
    self.available_input_devices = devices

    if not previous:
        # Initial load — apply priority-based auto-selection
        self._auto_select_initial_device(devices)
    else:
        # Hot-plug — auto-select newly appeared real device or fall back
        self._auto_select_on_hotplug(devices, previous)

    if self._on_devices_changed is not None:
        self._on_devices_changed()
```

The two private helpers `_auto_select_initial_device` and
`_auto_select_on_hotplug` implement the same priority logic that Swift's
`loadAvailableInputDevicesMacOS` implements in its `previousDevices.isEmpty`
branch and its `else` branch respectively.

**Benefit:** Single source of truth for device enumeration. Eliminates the
duplicate logic currently split between `audio_device.py` and
`tap_tone_analyzer_control.py`.

---

## Recommendation 3 — Move calibration auto-load into `RealtimeFFTAnalyzer.set_device()` ✅ DONE

**Status:** Implemented. `RealtimeFFTAnalyzerDeviceManagementMixin.set_device()`
now performs the `CalibrationStorage.calibration_for_device()` lookup and calls
`self._on_calibration_changed(cal)`. `TapToneAnalyzerControlMixin.set_device()`
is now a thin delegator — no more `CalibrationStorage` import.
`TapToneAnalyzerControlMixin._on_mic_calibration_changed()` is the callback
target, mirroring Swift's `setCalibrationWithoutSavingDeviceMapping(_:)`.

**Files changed:** `realtime_fft_analyzer_device_management.py` (calibration lookup in `set_device`),
`realtime_fft_analyzer.py` (`on_calibration_changed` param added to `__init__`),
`tap_tone_analyzer.py` (passes `on_calibration_changed` when constructing `_Mic`),
`tap_tone_analyzer_control.py` (thinned `set_device`, added `_on_mic_calibration_changed`)

---

**Original recommendation:**

**Current state:** Calibration auto-load on device switch lives in
`TapToneAnalyzerControlMixin.set_device()` — i.e. on the tap-tone analyzer,
not on the mic.

**Swift equivalent:** `RealtimeFFTAnalyzer.selectedInputDevice.didSet` calls
`setCalibrationWithoutSavingDeviceMapping(_:)`. The FFT analyzer owns this
logic.

**Change:** Move the `CalibrationStorage.calibration_for_device()` lookup and
`load_calibration_from_profile()` call from `TapToneAnalyzerControlMixin.set_device()`
into `RealtimeFFTAnalyzer.set_device()`. Use a callback (e.g.
`on_calibration_changed: Callable[[...], None] | None`) to inform the analyzer,
mirroring the way Swift uses a Combine sink on `activeCalibration`.

`TapToneAnalyzerControlMixin.set_device()` then becomes a thin delegating
method that calls `self.mic.set_device(device)` and syncs `fft_data.sample_freq`
— nothing more.

**Benefit:** Ownership of calibration-per-device logic moves to
`RealtimeFFTAnalyzer`, matching Swift. The tap-tone analyzer stops needing to
know about `CalibrationStorage` for the device-switch path.

---

## Recommendation 4 — Expose `raw_sample_handler` on `RealtimeFFTAnalyzer` ✅ DONE

**Status:** Implemented. `RealtimeFFTAnalyzer.raw_sample_handler` is a callback
set by `TapToneAnalyzer.start()` to `self._accumulate_gated_samples`. Called by
`_FftProcessingThread.run()` on every audio chunk. The pre-roll buffer and gated
accumulator have moved from `_FftProcessingThread` to `TapToneAnalyzer` (stored
properties in `__init__`). `TapToneAnalyzerSpectrumCaptureMixin` gained
`_accumulate_gated_samples()` (the handler) and `start_gated_capture()` now
operates on `self` state directly instead of delegating to `proc_thread`.
`gatedCaptureComplete` Qt signal remains on `_FftProcessingThread` as the
delivery mechanism.

**Files changed:** `realtime_fft_analyzer.py` (added `raw_sample_handler`,
removed gated state/methods from `_FftProcessingThread`),
`tap_tone_analyzer.py` (added gated state to `__init__`, set `raw_sample_handler`
in `start()`), `tap_tone_analyzer_spectrum_capture.py` (added
`_accumulate_gated_samples()`, rewrote `start_gated_capture()` to own state directly)

---

**Original recommendation:**

**Current state:** The gated-FFT pre-roll ring buffer and gated accumulator
live on `_FftProcessingThread`. `TapToneAnalyzer` reaches into
`mic.proc_thread.start_gated_capture()` directly.

**Swift equivalent:** `RealtimeFFTAnalyzer` has:
```swift
var rawSampleHandler: (([Float], Double) -> Void)?
```
Set by `TapToneAnalyzer` at startup. Called on every audio buffer on
`audioProcessingQueue`. `TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:)`
is the handler — it owns the pre-roll buffer and gated accumulator directly.

**Change:** Add `raw_sample_handler: Callable | None = None` to
`RealtimeFFTAnalyzer`. Have `_FftProcessingThread.run()` call it on every
chunk:

```python
if self._mic.raw_sample_handler is not None:
    self._mic.raw_sample_handler(chunk_f32, float(self._mic.rate))
```

`TapToneAnalyzer.start()` then sets:
```python
self.mic.raw_sample_handler = self._accumulate_gated_samples
```

The pre-roll buffer and gated accumulator can then move from
`_FftProcessingThread` back to `TapToneAnalyzerSpectrumCaptureMixin`, matching
Swift's ownership model exactly. `_FftProcessingThread` loses all gated-capture
state and becomes purely a continuous-FFT worker.

**Benefit:** Matches Swift's architecture precisely. `_FftProcessingThread`
stops being a mixed continuous-FFT + gated-capture object. The `gatedCaptureComplete`
Qt signal can remain on `_FftProcessingThread` as a delivery mechanism, but
the accumulation logic moves to the analyzer.

---

## What is not worth changing

The following Python-only mechanisms have no Swift equivalent and should stay
as-is:

- `reinitialize_portaudio()` — PortAudio caches the device list at
  `Pa_Initialize()` time; Swift's CoreAudio APIs don't have this limitation.
- `_start_coreaudio_monitor()` via ctypes — already as close as possible to
  Swift's `AudioObjectAddPropertyListenerBlock` without rewriting in C.
- `_start_windows_monitor()` / `_start_linux_monitor()` — Swift targets
  macOS/iOS only; these are Python-only concerns.
- `AudioDevice.fingerprint` vs. Swift's `AVAudioDevice.uid` — PortAudio
  provides no stable UID; the fingerprint is the best achievable substitute.

---

## Summary

| Recommendation | Files changed | Complexity | Status |
|---|---|---|---|
| 1. Add `available_input_devices` / `selected_input_device` to `RealtimeFFTAnalyzer` | `realtime_fft_analyzer.py`, `realtime_fft_analyzer_device_management.py` | Low | ✅ Done |
| 2. Consolidate enumeration into `load_available_input_devices()` | `realtime_fft_analyzer_device_management.py` (new), `realtime_fft_analyzer.py` | Medium | ✅ Done |
| 3. Move calibration auto-load to `RealtimeFFTAnalyzer.set_device()` | `realtime_fft_analyzer_device_management.py`, `realtime_fft_analyzer.py`, `tap_tone_analyzer.py`, `tap_tone_analyzer_control.py` | Low | ✅ Done |
| 4. Add `raw_sample_handler` callback; move gated state to analyzer | `realtime_fft_analyzer.py`, `tap_tone_analyzer.py`, `tap_tone_analyzer_spectrum_capture.py` | High | ✅ Done |

All four recommendations are now complete.
