# Threading Audit Guidelines

## Purpose

This document codifies the rules for auditing Python model files in `guitar_tap`
for thread-safety correctness when translated from Swift. It was written after a
class of bug was found — background-thread Qt property mutation — that earlier
property-level audits missed because they checked *what* was written, not *on
which thread*.

The canonical examples of this bug were `_start_cross` and `_start_flc` in
`tap_tone_analyzer_spectrum_capture.py`, which were `threading.Timer` callbacks
that directly mutated PySide6 `QObject` properties from a background thread.
The equivalent Swift code used `DispatchQueue.main.asyncAfter`, which always
delivers to the main thread, making the same pattern safe in Swift but unsafe
in Python.

---

## Background: Why This Class of Bug is Hard to Catch

Swift's `DispatchQueue.main.asyncAfter` encodes a threading guarantee in the
call-site wrapper, not in the closure body. A line-by-line property comparison
sees identical assignments in the closure body and appears to match — but the
delivery guarantee is fundamentally different.

| Swift | Python equivalent | Notes |
|---|---|---|
| `DispatchQueue.main.async { body }` | `QMetaObject.invokeMethod(self, "_do_x", QueuedConnection)` | Main-thread post |
| `DispatchQueue.main.asyncAfter(d) { body }` | `threading.Timer(d, lambda: QMetaObject.invokeMethod(...)).start()` | Delayed main-thread post |
| `DispatchQueue.global().async { body }` | `threading.Thread(target=...).start()` | Background; no Qt contact permitted in body |

The key insight: **`threading.Timer` callbacks run on a background thread.**
Any write to a PySide6 `@Property`-decorated attribute, any signal `.emit()`,
or any call to a Qt method from a timer callback is undefined behaviour and
will silently corrupt state or be dropped.

---

## The Rules

### Rule 1 — Every `threading.Timer` callback must be a pure dispatcher

A `threading.Timer` callback **must not** touch any Qt state directly.
Its only permitted body is:

```python
def _my_callback() -> None:
    QtCore.QMetaObject.invokeMethod(
        self,
        "_do_my_action",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
```

All actual work belongs in the `@Slot()`-decorated method `_do_my_action`,
which runs on the main thread.

**Exception:** If the callback only reads or writes plain Python objects (no
Qt properties, no signals, no Qt methods), it is safe to run directly on the
background thread. But even then, prefer to document this explicitly.

### Rule 2 — Every `threading.Thread` target must obey the same rule

A `threading.Thread` target function that calls back into a `QObject` must
post to the main thread via `invokeMethod` before touching any Qt state.
The signal `.emit()` is thread-safe for **cross-thread signal delivery** (Qt
queues it automatically when the target slot's thread differs), but a direct
property write is never safe from a non-main thread.

### Rule 3 — `@Slot()` is required for `invokeMethod` to find the method

Without the `@Slot()` decorator, PySide6's meta-object system cannot find the
method by name string, and `invokeMethod` silently does nothing (logging
`QMetaObject::invokeMethod: No such method TapToneAnalyzer::_do_x()`).

Every method referenced in an `invokeMethod` call **must** carry `@Slot()`.

### Rule 4 — Signals are thread-safe; properties are not

A `Signal.emit()` from a background thread is safe: Qt will queue the call
and deliver it to the connected slot on the correct thread.

A `self.some_property = value` write from a background thread (where
`some_property` is a `@Property` or a plain attribute that drives a Qt
property) is **not** safe. Treat any `self.` write that could affect a bound
Qt property as a thread-safety issue.

### Rule 5 — Document the threading context at every timer/thread site

Every `threading.Timer(...)` or `threading.Thread(...)` call must have a
comment:
1. Which thread the callback/target runs on.
2. Whether it touches Qt state.
3. If it posts to the main thread: which `@Slot()` it invokes.

Example:
```python
# threading.Timer fires on a background thread; post to main thread
# before touching any Qt properties or state.
def _start_cross() -> None:
    QtCore.QMetaObject.invokeMethod(
        self,
        "_do_start_cross",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
t = threading.Timer(cooldown, _start_cross)
```

---

## Audit Checklist

For each file in `models/`:

1. **Find all `threading.Timer` and `threading.Thread` call sites.**
   - `grep -n "threading\.Timer\|threading\.Thread"`

2. **For each `threading.Timer` callback function, check its body.**
   - Does it write `self.` properties? → **Bug if any are Qt properties.**
   - Does it emit signals? → Safe (Qt queues cross-thread signals automatically).
   - Does it call `QMetaObject.invokeMethod`? → Correct pattern.
   - Does it only read/write plain Python state? → Safe, but add a comment.

3. **For each `threading.Thread` target function, apply the same check.**

4. **Verify every `invokeMethod` target carries `@Slot()`.**
   - `grep -n "invokeMethod"` — note each string argument (the slot name).
   - `grep -n "@Slot"` — verify every named slot exists.

5. **Check `stop_*/start_*` methods called from timers.**
   - If the timer fires directly on a target method (not a lambda or closure),
     check the method body itself.

6. **Record outcome per file:** PASS, PASS (no timers), or BUG (list issues).

---

## Standard Fix Pattern

When a `threading.Timer` callback directly writes Qt properties, the fix is:

**Step 1:** Replace the callback body with a single `invokeMethod` call:
```python
def _my_callback() -> None:
    QtCore.QMetaObject.invokeMethod(
        self,
        "_do_my_action",
        QtCore.Qt.ConnectionType.QueuedConnection,
    )
```

**Step 2:** Create a new `@Slot()` method with the original logic:
```python
@Slot()
def _do_my_action(self) -> None:
    """Main-thread slot: [description].

    Invoked via QMetaObject.invokeMethod(QueuedConnection) from
    [callback name], so this always runs on the main thread.
    Mirrors Swift: [Swift method and dispatch context].
    """
    # original body here
    self.some_property = value
    ...
```

**Step 3:** Add a comment at the `threading.Timer` call site explaining
the threading context and the slot it dispatches to.

---

## Swift → Python Concurrency Mapping Reference

| Swift pattern | Python equivalent |
|---|---|
| `DispatchQueue.main.async { body }` | `QMetaObject.invokeMethod(self, "_do_x", QueuedConnection)` |
| `DispatchQueue.main.asyncAfter(d) { body }` | `threading.Timer(d, dispatcher).start()` where `dispatcher` calls `invokeMethod` |
| `DispatchQueue.global().async { body }` | `threading.Thread(target=_work).start()` — no Qt contact in `_work` |
| `Timer.scheduledTimer(interval: t, ...) { body }` | `threading.Timer(t, target_method).start()` — if `target_method` writes Qt, it needs `@Slot()` and must be called via `invokeMethod` |
| `@MainActor func foo()` | `@Slot()` + called only via signal/slot or `invokeMethod` from background threads |
| Combine `.sink { ... }` on `@Published` on main thread | Qt `@Slot` connected to a signal via `QueuedConnection` |

---

## Files to Audit

All `.py` files in `src/guitar_tap/models/`:

| File | Timer/Thread sites | Status |
|---|---|---|
| `__init__.py` | — | — |
| `analysis_display_mode.py` | — | — |
| `annotation_visibility_mode.py` | — | — |
| `audio_device.py` | — | — |
| `fft_parameters.py` | — | — |
| `guitar_mode.py` | — | — |
| `guitar_type.py` | — | — |
| `material_properties.py` | — | — |
| `material_tap_phase.py` | — | — |
| `measurement_type.py` | — | — |
| `microphone_calibration.py` | — | — |
| `pitch.py` | — | — |
| `plate_stiffness_preset.py` | — | — |
| `realtime_fft_analyzer.py` | `_monitor_thread` field | — |
| `realtime_fft_analyzer_device_management.py` | `_listener` → `threading.Thread(_notify_devices_changed)`, Windows/Linux monitors | — |
| `realtime_fft_analyzer_engine_control.py` | — | — |
| `realtime_fft_analyzer_fft_processing.py` | — | — |
| `resonant_peak.py` | — | — |
| `spectrum_snapshot.py` | — | — |
| `tap_display_settings.py` | — | — |
| `tap_tone_analyzer.py` | — | — |
| `tap_tone_analyzer_analysis_helpers.py` | — | — |
| `tap_tone_analyzer_annotation_management.py` | — | — |
| `tap_tone_analyzer_control.py` | — | — |
| `tap_tone_analyzer_decay_tracking.py` | `threading.Timer(3.0, self.stop_decay_tracking)` | — |
| `tap_tone_analyzer_measurement_management.py` | — | — |
| `tap_tone_analyzer_mode_override_management.py` | — | — |
| `tap_tone_analyzer_peak_analysis.py` | — | — |
| `tap_tone_analyzer_spectrum_capture.py` | `_safety_timeout`, `_start_cross`, `_start_flc` | — |
| `tap_tone_analyzer_tap_detection.py` | `_reenable` (guitar), `threading.Timer(captureWindow, _finish_capture)`, `_reenable` (plate) | — |
| `tap_tone_measurement.py` | — | — |
| `user_assigned_mode.py` | — | — |

The status column will be filled in by the audit results document
`THREADING_AUDIT_RESULTS.md`.
