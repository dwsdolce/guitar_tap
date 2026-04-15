# Threading Audit Results

Audit performed against all files in `src/guitar_tap/models/` using the rules
in `THREADING_AUDIT_GUIDELINES.md`.

---

## Key Finding: Published Properties vs Qt @Property

Before the file-by-file results, one important clarification about the
`Published` descriptor used on several `TapToneAnalyzer` properties:

`Published.__set__` (in `swiftui_compat/descriptors.py`) stores the value in
`obj.__dict__` and calls `_notify_change`, which fires into a list of Python
callbacks — it does **not** emit a Qt signal and does not call any Qt method.
Therefore, writing a `Published` property from a background thread is **not**
a Qt thread-safety violation in the strict sense (no Qt data structures are
touched).

However, it **is** a Python data-race: the main thread may be reading the
same `__dict__` slot while the background thread writes it. Python's GIL
prevents torn reads/writes on simple objects, but composite state changes
(e.g., writing three related properties in sequence) are not atomic. The
main thread could observe a partially-updated state between writes.

The `@Slot()`-decorated properties (signals like `peaksChanged.emit()`,
`tapDetectedSignal.emit()`, etc.) **do** touch Qt structures and are
**safe** to emit from background threads — Qt queues cross-thread signals
automatically.

For the purposes of this audit: **any background-thread write to a `Published`
property that is part of a multi-field state transition (e.g., setting
`is_detecting`, `is_above_threshold`, and `tap_detected` together) is flagged
as a race hazard** even though no individual write crashes Qt. These multi-field
updates must be on the main thread to ensure the main thread never observes
a half-updated state.

---

## Results by File

### Files with no timers or threads — PASS (no issues possible)

| File | Reason |
|---|---|
| `__init__.py` | Empty re-exports only |
| `analysis_display_mode.py` | Pure enum |
| `annotation_visibility_mode.py` | Pure enum |
| `audio_device.py` | Named tuple / dataclass |
| `fft_parameters.py` | Dataclass |
| `guitar_mode.py` | Pure enum |
| `guitar_type.py` | Pure enum |
| `material_properties.py` | Dataclass / pure computation |
| `material_tap_phase.py` | Pure enum |
| `measurement_type.py` | Pure enum |
| `microphone_calibration.py` | Dataclass |
| `pitch.py` | Dataclass / pure computation |
| `plate_stiffness_preset.py` | Pure enum |
| `resonant_peak.py` | Dataclass |
| `spectrum_snapshot.py` | Dataclass |
| `tap_display_settings.py` | Class-level settings singleton, no threads |
| `tap_tone_analyzer_analysis_helpers.py` | Pure computation methods |
| `tap_tone_analyzer_annotation_management.py` | Synchronous methods only |
| `tap_tone_analyzer_measurement_management.py` | Synchronous methods only |
| `tap_tone_analyzer_mode_override_management.py` | Synchronous methods only |
| `tap_tone_analyzer_peak_analysis.py` | Pure computation methods |
| `tap_tone_measurement.py` | Data container |
| `user_assigned_mode.py` | Pure enum |

---

### `realtime_fft_analyzer.py` — PASS

**Timer/Thread sites:** `_monitor_thread` field (type annotation only, no start here).

No `threading.Timer` or `threading.Thread` calls in this file. The field is
initialised and used in `realtime_fft_analyzer_device_management.py`.

---

### `realtime_fft_analyzer_engine_control.py` — PASS

No `threading.Timer` or `threading.Thread` calls. The audio processing runs
in a `QThread` (`_FftProcessingThread`) whose signals are delivered via Qt's
queued connection mechanism, making them thread-safe by design.

---

### `realtime_fft_analyzer_fft_processing.py` — PASS

No `threading.Timer` or `threading.Thread` calls. All work is done inside the
`QThread` run loop; all outputs go through `Signal.emit()`, which Qt queues
safely across threads.

---

### `realtime_fft_analyzer_device_management.py` — PASS WITH NOTE

**Timer/Thread sites:**
- Line 395: `threading.Thread(target=self._notify_devices_changed, daemon=True).start()`
  (CoreAudio listener callback, macOS)
- Line 459: `threading.Thread(target=self._notify_devices_changed, daemon=True)`
  (Windows CM_Register_Notification callback)
- Line 513: `self._monitor_thread = threading.Thread(target=_run, daemon=True)`
  (Linux inotify/udev monitor)

**`_notify_devices_changed` body (line 307-320):**
```python
def _notify_devices_changed(self) -> None:
    if self._on_devices_changed is None:
        return
    time.sleep(0.5)
    self._on_devices_changed()
```

`_on_devices_changed` is set to `self._devicesRefreshed.emit` in
`tap_tone_analyzer.py` (line 452). `Signal.emit()` from a background thread
is **safe** in Qt/PySide6 — Qt automatically queues the signal for delivery on
the connected slot's thread.

**Note:** The comment at line 314-315 says "calls loadAvailableInputDevices()
on the main thread" — this is correct because `_devicesRefreshed` is connected
via a `QueuedConnection` to the view's device-refresh slot. The pattern is safe
as written.

**Status:** PASS. No Qt property mutations on background threads.

---

### `tap_tone_analyzer.py` — PASS WITH NOTE

No `threading.Timer` or `threading.Thread` call sites in this file itself.
The `Published` properties are plain Python descriptors (see key finding above).
The `TapToneAnalyzer` class itself is the `QObject`; all direct property writes
to it from the audio path arrive via Qt `QueuedConnection` signals and run on
the main thread.

**Note for future work:** The `STRUCTURAL_DIVERGENCE_PLAN.md` recommends
removing `ObservableObject` and `Published` descriptors and replacing them with
plain `self.x = default` attributes. This would have no effect on threading
correctness (both are plain `__dict__` writes) but would remove the pretense
of SwiftUI-style observability.

---

### `tap_tone_analyzer_control.py` — PASS

No `threading.Timer` or `threading.Thread` calls. All methods are called from
the main thread (from Qt signal handlers or the view layer).

---

### `tap_tone_analyzer_decay_tracking.py` — **BUG: Rule 1 violation**

**Timer site:** Line 78:
```python
self._decay_tracking_timer = threading.Timer(3.0, self.stop_decay_tracking)
```

**`stop_decay_tracking` body (lines 87-99):**
```python
def stop_decay_tracking(self) -> None:
    self.is_tracking_decay = False          # ← Published property write
    if self._decay_tracking_timer is not None:
        self._decay_tracking_timer.cancel()
        self._decay_tracking_timer = None
```

**Issue:** The timer fires `stop_decay_tracking` directly on a background
thread. `stop_decay_tracking` writes `self.is_tracking_decay`, which is a
multi-step state change (`is_tracking_decay = False` plus clearing the timer
reference). The main thread reads `is_tracking_decay` in `track_decay_fast()`
at ~10 Hz. This is a data race: the main thread could observe
`is_tracking_decay = False` but `_decay_tracking_timer` still non-None (or
vice versa).

**Swift equivalent:** Swift's `Timer.scheduledTimer` fires on the RunLoop of
the thread that schedules it. Since `startDecayTracking()` runs on the main
thread, the timer fires on the main thread — the same thread that reads
`isTrackingDecay`. No race is possible in Swift.

**Fix required:** The `threading.Timer` callback must dispatch to the main
thread before touching any state shared with the main thread.

**Recommended fix:**
```python
# In start_decay_tracking():
def _fire_stop():
    # threading.Timer fires on a background thread; post to main thread.
    QtCore.QMetaObject.invokeMethod(
        self,
        "_do_stop_decay_tracking",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
self._decay_tracking_timer = threading.Timer(3.0, _fire_stop)

# New @Slot():
@Slot()
def _do_stop_decay_tracking(self) -> None:
    """Main-thread slot: finalise decay tracking window.
    Invoked via QMetaObject.invokeMethod(QueuedConnection) from the
    threading.Timer callback in start_decay_tracking.
    Mirrors Swift stopDecayTracking() which always fires on the main thread
    (Timer.scheduledTimer fires on the scheduling RunLoop = main thread).
    """
    self.is_tracking_decay = False
    if self._decay_tracking_timer is not None:
        self._decay_tracking_timer.cancel()
        self._decay_tracking_timer = None
```

`stop_decay_tracking` (the public method) should also be updated to call
`_do_stop_decay_tracking` or have its body be the actual work, depending on
whether it is called directly from the main thread (e.g., on tap detection
reset). If it is always called from the main thread when called directly,
the private `_do_stop_decay_tracking` slot can simply call `stop_decay_tracking`
instead, and the timer fires the slot.

---

### `tap_tone_analyzer_spectrum_capture.py` — PASS (fixed in previous session)

**Timer sites:**
- Line 192: `threading.Timer(2.0, _safety_timeout)` — safety timeout
- Line 622: `threading.Timer(cooldown, _start_cross)` — cross-phase transition
- Line 683: `threading.Timer(cooldown, _start_flc)` — FLC-phase transition

**Status of each:**

`_safety_timeout` (lines 163-192): The callback body calls
`QMetaObject.invokeMethod(self, "_do_safety_timeout", QueuedConnection)`.
`_do_safety_timeout` is decorated `@Slot()`. **PASS.**

`_start_cross` (lines 611-622): The callback body calls
`QMetaObject.invokeMethod(self, "_do_start_cross", QueuedConnection)`.
`_do_start_cross` is decorated `@Slot()`. **PASS.** (Fixed in previous session.)

`_start_flc` (lines 673-683): The callback body calls
`QMetaObject.invokeMethod(self, "_do_start_flc", QueuedConnection)`.
`_do_start_flc` is decorated `@Slot()`. **PASS.** (Fixed in previous session.)

---

### `tap_tone_analyzer_tap_detection.py` — **TWO ISSUES**

#### Issue 1 (BUG): Guitar-mode `_reenable` closure — Rule 1 violation

**Timer site:** Lines 349-351:
```python
t = threading.Timer(cooldown, _reenable)
```

**`_reenable` body (lines 325-347):** Directly writes to multiple `Published`
properties from the background thread:
```python
def _reenable() -> None:
    current_level = self._current_peak_magnitude_db
    falling_threshold = self.tap_detection_threshold - self.hysteresis_margin
    if current_level <= falling_threshold:
        self.is_above_threshold = False     # ← background-thread write
        self.is_detecting = True            # ← background-thread write
        self.tap_detected = False           # ← background-thread write
        self.status_message = ...           # ← background-thread write
    else:
        self.is_above_threshold = True      # ← background-thread write
        self.is_detecting = True            # ← background-thread write
        self.tap_detected = False           # ← background-thread write
        self.status_message = ...           # ← background-thread write
```

**Issue:** Four `Published` properties are written in a non-atomic group from
the background thread. The main thread (`detect_tap`) reads
`is_above_threshold`, `is_detecting`, and `tap_detected` at ~2.7 Hz. It could
observe an inconsistent state between writes (e.g., `is_detecting = True` but
`is_above_threshold` not yet updated).

**Swift equivalent:** The equivalent closure in Swift is dispatched with
`DispatchQueue.main.asyncAfter`, so it always runs on the main thread.

**Fix required:** Same pattern as `_do_reenable_detection` (plate mode):
```python
def _reenable() -> None:
    # threading.Timer fires on a background thread; post to main thread.
    QtCore.QMetaObject.invokeMethod(
        self,
        "_do_reenable_guitar",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )

@Slot()
def _do_reenable_guitar(self) -> None:
    """Main-thread slot: re-arm detection after guitar tap cooldown.
    Invoked via QMetaObject.invokeMethod(QueuedConnection) from _reenable,
    so this always runs on the main thread.
    Mirrors Swift handleTapDetection re-enable closure (DispatchQueue.main.asyncAfter).
    Uses _current_peak_magnitude_db (instantaneous FFT peak) — mirrors Swift
    fftAnalyzer.peakMagnitude read in the re-enable closure.
    """
    current_level = self._current_peak_magnitude_db
    falling_threshold = self.tap_detection_threshold - self.hysteresis_margin
    if current_level <= falling_threshold:
        self.is_above_threshold = False
        self.is_detecting = True
        self.tap_detected = False
        self.status_message = (
            f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
        )
    else:
        self.is_above_threshold = True
        self.is_detecting = True
        self.tap_detected = False
        self.status_message = (
            f"Tap {self.current_tap_count}/{self.number_of_taps} captured."
            " Waiting for settle..."
        )
```

#### Issue 2 (BUG): `_finish_capture` called directly from `threading.Timer` — Rule 1 violation

**Timer site:** Line 317:
```python
t = threading.Timer(self.capture_window, self._finish_capture)
```

**`_finish_capture` body (lines 357-375):** Writes multiple Qt-adjacent
properties and emits two signals from the background thread:
```python
def _finish_capture(self) -> None:
    ...
    self.frozen_magnitudes = avg_db         # ← background-thread write
    self.frozen_frequencies = self.freq     # ← background-thread write
    self.current_peaks = peaks              # ← background-thread write
    self.peaksChanged.emit(peaks)           # ← signal emit (safe, but runs body on bg thread)
    self.tapDetectedSignal.emit()           # ← signal emit (safe, but runs body on bg thread)
```

**Issue:** The three property writes are a group that the main thread may read
in a partially-updated state. `peaksChanged.emit()` and `tapDetectedSignal.emit()`
are safe as cross-thread signal emissions (Qt queues them), but the property
writes that precede them are not.

**Note:** This may be why in some test runs the frozen spectrum displayed
incorrectly or the tap was credited before the spectrum was fully set.

**Fix required:**
```python
# Timer callback — dispatcher only:
t = threading.Timer(self.capture_window, self._schedule_finish_capture)

def _schedule_finish_capture(self) -> None:
    QtCore.QMetaObject.invokeMethod(
        self,
        "_finish_capture",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
```

Or more simply, add `@Slot()` to `_finish_capture` and change the timer
target to a one-line dispatcher:

```python
def _enqueue_finish_capture() -> None:
    QtCore.QMetaObject.invokeMethod(
        self, "_finish_capture",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
t = threading.Timer(self.capture_window, _enqueue_finish_capture)
```

And add `@Slot()` to `_finish_capture`. Since `_finish_capture` is also
called from other places, verify those call sites are on the main thread
before adding `@Slot()`. If they are, `@Slot()` is harmless.

---

## Summary of Issues Found

| File | Issue | Severity | Status |
|---|---|---|---|
| `tap_tone_analyzer_decay_tracking.py` | `threading.Timer(3.0, self.stop_decay_tracking)` fires `stop_decay_tracking` directly; writes `is_tracking_decay` and clears timer reference from background thread | Race hazard | **Fixed** |
| `tap_tone_analyzer_tap_detection.py` | Guitar-mode `_reenable` closure writes 4 properties from background thread | Race hazard | **Fixed** |
| `tap_tone_analyzer_tap_detection.py` | `_finish_capture` called directly from `threading.Timer`; writes `frozen_magnitudes`, `frozen_frequencies`, `current_peaks` from background thread | Race hazard | **Fixed** |

Previously fixed (prior session):

| File | Issue | Status |
|---|---|---|
| `tap_tone_analyzer_spectrum_capture.py` | `_start_cross` closure wrote Qt properties from background thread | Fixed |
| `tap_tone_analyzer_spectrum_capture.py` | `_start_flc` closure wrote Qt properties from background thread | Fixed |
| `tap_tone_analyzer_spectrum_capture.py` | `_safety_timeout` closure wrote Qt properties from background thread | Fixed |
| `tap_tone_analyzer_tap_detection.py` | Plate `_reenable` closure wrote Qt properties from background thread | Fixed |

---

## Prioritisation

**Fix immediately (correctness impact):**

1. `_reenable` guitar mode — this is the direct equivalent of the plate
   `_reenable` bug that was already fixed; it has the same race on the same
   set of detection-state properties.

2. `_finish_capture` — writes the frozen spectrum properties and emits the
   "tap detected" signal from a background thread; this is the final step of
   every guitar tap and the race could cause stale or partially-written spectra.

3. `stop_decay_tracking` timer — lower severity because `is_tracking_decay`
   is a boolean flag read by `track_decay_fast` which tolerates a one-sample
   delay, but should be fixed for correctness.
