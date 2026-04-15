# Reactive Property Audit Guidelines

## Purpose

This document codifies the rules for auditing the Python model and view files in
`guitar_tap` to ensure that every Swift `@Published` property has a correct,
working notification path to the Python view layer.

It was written after a class of bug was found — `materialTapPhase` was written
correctly in the model but the view never received a notification because
`plateStatusChanged` was never emitted.  The root cause is structural: Swift's
`@Published` attribute provides *automatic, invisible* notification on every
write, while the Python/Qt port requires an *explicit* `Signal.emit()` call at
every write site.  Line-by-line comparison of write sites looks identical in
both languages — the notification mechanism is simply absent from the write
line in Python because there is nothing to translate.

---

## Background: Why This Class of Bug Is Hard to Catch

### Swift's notification model

In Swift, `TapToneAnalyzer` is an `ObservableObject`.  Every property marked
`@Published` has the following behaviour built in at compile time:

```swift
@Published var materialTapPhase: MaterialTapPhase = .notStarted
```

- Every assignment anywhere — `materialTapPhase = .waitingForCrossTap` — fires
  `objectWillChange.send()` automatically before the write.
- SwiftUI re-renders all views that read that property on the next run loop.
- No code at the write site refers to any notification mechanism.

### Python's notification model

The Python port uses PySide6 Qt signals.  Signals must be:

1. **Declared** as class-level `Signal(...)` attributes on the `QObject`.
2. **Connected** in the view to a slot method.
3. **Emitted** explicitly (`self.some_signal.emit(value)`) at every write site
   that should notify the view.

Step 3 has no counterpart in Swift.  A line-by-line translation produces
correct-looking Python that silently never notifies the view.

### The masking factor

The `swiftui_compat.Published` descriptor (now removed) called `_notify_change`
on every write, giving the appearance of a working notification mechanism even
though no Python callbacks were ever registered.  This masked the gap for the
lifetime of the `ObservableObject` scaffolding.

---

## The Rules

### Rule 1 — Every `@Published` property maps to exactly one Python notification path

For every Swift `@Published var foo: T` there must be a documented Python
equivalent in one of these three categories:

| Category | Description | Example |
|---|---|---|
| **Signal-driven** | A Qt `Signal` is emitted whenever `foo` changes; a view slot is connected to it | `plateStatusChanged.emit(phase.value)` |
| **Pull-on-signal** | `foo` itself is not signalled; the view reads it synchronously inside a slot handler for a related signal | `identifiedModes` read during PDF export inside `_export_pdf()` |
| **View-local** | The Swift property is owned by the model for Swift/SwiftUI reasons but Python keeps equivalent state in the view | `loaded*` settings warning properties |

Unclassified properties — properties with no documented path — are bugs.

### Rule 2 — Every signal must be emitted at every write site

If a property is classified as **Signal-driven**, every location that writes
`self.foo = value` (excluding `__init__`) must be accompanied by an emit or
must call a helper that emits.

The correct pattern is a helper setter:

```python
def _set_material_tap_phase(self, phase) -> None:
    """Assign material_tap_phase and emit plateStatusChanged.

    All writes to material_tap_phase must go through this helper so that
    the UI phase step indicator is kept in sync.  Mirrors Swift @Published
    var materialTapPhase whose every write auto-fires objectWillChange.
    """
    self.material_tap_phase = phase
    self.plateStatusChanged.emit(phase.value)
```

Direct writes that bypass the helper are bugs.

### Rule 3 — Signals must be declared, connected, AND emitted

Auditing only signal declarations or only signal connections is insufficient.
The full chain must be verified:

```
Signal declared   ← grep for Signal(
  └─ Signal connected  ← grep for .connect(
       └─ Signal emitted  ← grep for .emit(
```

A signal that is declared and connected but never emitted produces no
notifications.  A signal that is emitted but never connected produces no
UI updates.

### Rule 4 — Document the notification contract at the write site

Every property that has a Signal-driven notification path must have a comment
at its `__init__` declaration:

```python
# All writes must go through _set_material_tap_phase() to emit plateStatusChanged.
self.material_tap_phase: "_MTP" = _MTP.NOT_STARTED
```

And the helper or emit site must document which Swift @Published property it
mirrors:

```python
def _set_material_tap_phase(self, phase) -> None:
    """...Mirrors Swift @Published var materialTapPhase..."""
```

### Rule 5 — Pull-on-signal and view-local must be explicitly justified

For **Pull-on-signal** properties: document *which* signal triggers the read
and *why* the read is guaranteed to see current state at that point.

For **View-local** properties: document *why* Python keeps this state in the
view rather than reading it from the model.

If the justification cannot be written down clearly, reconsider the
classification.

### Rule 5a — View-local state must be written at every Swift write site

**This rule extends Rule 5 and addresses a specific class of bug that Rule 5
alone does not catch.**

When a `@Published` property is classified as **View-local**, the audit must
not stop at documenting *why* Python keeps equivalent state in the view.  It
must also enumerate every place Swift writes that `@Published` property and
verify that Python has a corresponding write to its view-local equivalent at
each of those sites.

**The failure mode:**

Swift writes `selectedPeakIDs` at three points:
1. Longitudinal phase complete — `selectedPeakIDs = Set(longitudinalPeaks.map { $0.id })`
2. Cross-grain phase complete — `selectedPeakIDs = Set(resolvedPlatePeaks(...).map { $0.id })`
3. FLC phase complete — `selectedPeakIDs = Set(resolvedPlatePeaks(...).map { $0.id })`
4. Guitar tap detected — `selectedPeakIDs = guitarModeSelectedPeakIDs`

Python's view-local equivalent is `peak_widget.model.selected_frequencies`.
The guitar path (4) was correctly wired via `auto_select_peaks_by_mode()`.
The plate/brace paths (1–3) had no write at all — `selected_frequencies` was
always empty for plate/brace, so "Selected" annotation mode showed nothing.

This bug was invisible to Rules 1–5 because the property was correctly
*classified* as View-local and *justified* (peak selection is view-managed),
but the write-site enumeration was never performed.

#### Rule 5a checklist for View-local properties

For each **View-local** classified property:

- [ ] Identify every location in Swift that writes `self.foo = value`
- [ ] For each Swift write site, confirm Python has a corresponding write to
      its view-local equivalent at the analogous call site
- [ ] If any Swift write site has no Python equivalent, mark as **⚠ Gap**
- [ ] Document the mapping: Swift write site → Python write site

#### Audit table format for Rule 5a

| Swift `@Published` | Swift write sites | View-local Python equivalent | Python write sites | Status |
|---|---|---|---|---|
| `selectedPeakIDs` | Phase completion (3×), guitar tap auto-select | `peak_widget.model.selected_frequencies` | Guitar: `auto_select_peaks_by_mode()`; Plate/brace: `_on_plate_analysis_complete` + `_on_material_assignment_changed` | ✅ Fixed |

#### When to re-run Rule 5a

Re-run whenever:
- A new write site for a `@Published` property is added in Swift (even to a
  property already classified as View-local)
- A new measurement mode or state machine path is added in Python

---

### Rule 6 — Audit Swift computed view properties (N-to-1 aggregation)

Swift computed view properties (not `@Published`, but `var foo: T { ... }` in a `View`
or `ObservableObject`) can aggregate multiple `@Published` inputs into one derived value.
SwiftUI re-evaluates them automatically whenever any input changes.  Python has no
equivalent automatic mechanism: every input change requires an explicit Python call to
reassemble the derived value.

**Inventory every Swift computed view property** that reads N `@Published` model vars
and confirm that Python has an explicit assembly call site for each one.

#### Audit table format

| Swift computed property | `@Published` inputs consumed | Python assembly call | Call site location | Status |
|---|---|---|---|---|
| `materialSpectra` | `longitudinalSpectrum`, `crossSpectrum`, `flcSpectrum`, `displayMode`, `comparisonSpectra` | `set_material_spectra(...)` | After each phase completes in `tap_tone_analyzer_spectrum_capture.py` | ✅ |

#### What counts as a call site

A Python assembly call site is any statement that:
1. Reads all N `@Published` inputs, **and**
2. Assembles them into the derived representation the view needs, **and**
3. Either pushes the result into the view (preferred) or stores it where the next
   signal-triggered render will pick it up.

If no such call site exists at a point where any input changes, the view will observe
stale assembled data — the same class of bug as the missing `set_material_spectra()`
calls found in the plate measurement completion paths.

#### Checklist additions for Rule 6

For each Swift computed view property:

- [ ] Property listed in the audit table
- [ ] All `@Published` inputs identified
- [ ] Python assembly call site identified
- [ ] Assembly call site present at **every point** any input changes (not just at
      one completion point)
- [ ] If there is no Python assembly call site, the property is marked **⚠ Gap**

#### When to re-run Rule 6

Re-run whenever:
- A Swift computed view property is added, removed, or modified
- A new `@Published` property is added that is consumed by an existing computed view
  property
- A new completion path or state transition is added in Python

---

### Rule 7 — Slot handlers must consume their signal payload

Every Python slot handler receives its data as signal payload parameters.  That payload
is the authoritative, current value at the moment the slot fires.  Reading alternative
sources — model attributes, canvas backing arrays, numpy arrays populated by a different
code path — instead of or alongside the payload creates stale-data bugs that are
invisible to signal-chain audits.

**The specific failure mode:**

```python
# Signal: plateAnalysisComplete.emit(f_long, f_cross, f_flc)

def _on_plate_analysis_complete(self, f_long, f_cross, f_flc):
    # WRONG: reads from a legacy array that is never populated for plate mode
    peaks = self.fft_canvas.saved_peaks
    if len(peaks) > 0:               # always False for plate
        actual_long = peaks[0, 0]    # never reached
    else:
        actual_long = 0.0            # always taken — L/C/FLC never labeled
```

The bug is invisible to Rules 1–5 because the signal is correctly declared, connected,
and emitted.  The slot fires, but reads from the wrong source.

#### Rule 7 checks

For every slot handler `_on_xxx(self, *payload_params)`:

1. **Primary source check**: Is the payload (`*payload_params`) used as the primary
   data source for the slot's main action?

2. **Alternative source check**: If the slot also reads from a model attribute, canvas
   array, or other non-payload source, is that read:
   - Clearly documented with a comment explaining why it is safe?
   - Guaranteed to be current at the time the slot fires?

3. **Legacy array check**: Any read of `self.fft_canvas.saved_peaks` (a numpy backing
   array) inside a slot handler must be justified.  `saved_peaks` is only populated for
   guitar-mode measurements; it is always empty for plate/brace measurements.  If a slot
   handles both modes and reads `saved_peaks`, it has a plate-mode gap.

#### Acceptable alternative source reads

| Source | Acceptable if... |
|---|---|
| `self._is_running`, `self._loaded_xxx` (view-local state) | Always acceptable; these are owned by the view |
| `self.fft_canvas.current_peaks` or `self.fft_canvas._current_peaks` | Acceptable; populated by `peaksChanged` signal for all modes |
| `self.fft_canvas.saved_peaks` | **Only** acceptable for guitar-mode-only slots; must be documented |
| `self.analyzer.xxx` public attribute | Acceptable if the attribute is Pull-on-signal (documented in audit results) |
| `self.analyzer._xxx` private attribute | Requires explicit justification; treat as ⚠ |

#### Audit table format for Rule 7

| Slot | Signal payload used? | Alternative source | Justified? | Status |
|---|---|---|---|---|
| `_on_plate_analysis_complete` | `f_long`, `f_cross`, `f_flc` | Previously `saved_peaks` (removed) | Fixed — now uses payload only | ✅ |
| `_on_material_assignment_changed` | `long_freq`, `cross_freq`, `flc_freq` | `saved_peaks` (for label assignment) | No — `saved_peaks` empty in plate mode | ⚠ Gap |

---

## Audit Checklist

For each Swift `@Published` property:

1. **Classify it** as Signal-driven, Pull-on-signal, or View-local.

2. **If Signal-driven:**
   - [ ] Signal declared with correct type signature in `tap_tone_analyzer.py`
   - [ ] Signal connected in the view (or relayed via `fft_canvas.py`)
   - [ ] Signal emitted at every non-`__init__` write site (via helper or directly)
   - [ ] Helper setter documented with `# Mirrors Swift @Published var X`
   - [ ] `__init__` declaration has comment pointing to helper

3. **If Pull-on-signal:**
   - [ ] Identify the trigger signal
   - [ ] Confirm the read is inside a slot handler for that signal
   - [ ] Document why pull is sufficient (e.g., only needed at export time)

4. **If View-local:**
   - [ ] Confirm the Python model does **not** own this state
   - [ ] Confirm the equivalent state exists in the view
   - [ ] Document why the model doesn't need it

5. **Record outcome** in `REACTIVE_PROPERTY_AUDIT_RESULTS.md`.

---

## When to Re-Run This Audit

Re-run the full audit (Rules 1–5) whenever:

- A new `@Published` property is added to the Swift model
- A new instance attribute is added to `TapToneAnalyzer.__init__` in Python
- A signal is added, removed, or renamed
- Any infrastructure that provided automatic notifications (e.g., `Published`
  descriptors, `ObservableObject`) is added or removed

Re-run Rule 6 (computed view property audit) whenever:

- A Swift computed view property is added, modified, or removed
- A new `@Published` property is added that feeds an existing computed view property
- A new completion path or state transition is added in Python (e.g., a new phase in
  the plate capture state machine)

Re-run Rule 7 (slot payload consumption audit) whenever:

- A new slot handler is added to the view
- An existing slot handler is modified
- A new signal is connected to the view
- Any read of `saved_peaks`, `analyzer._xxx`, or other non-payload source is added
  inside a slot handler

---

## Standard Fix Pattern

When a Signal-driven property has no emit:

**Step 1:** Identify or create the Qt signal with the right type:
```python
# In TapToneAnalyzer class body:
fooChanged: QtCore.Signal = QtCore.Signal(str)  # matches @Published var foo: String
```

**Step 2:** Add a helper setter in the relevant mixin:
```python
def _set_foo(self, value: str) -> None:
    """Assign foo and notify the view via fooChanged.

    All writes to foo must go through this helper.
    Mirrors Swift @Published var foo: String whose every write
    auto-fires objectWillChange on TapToneAnalyzer.
    """
    self.foo = value
    self.fooChanged.emit(value)
```

**Step 3:** Replace all `self.foo = ...` writes (outside `__init__`) with
`self._set_foo(...)`.

**Step 4:** Verify the connection exists in the view:
```python
# In view setup code:
self.analyzer.fooChanged.connect(self._on_foo_changed)
```

**Step 5:** Add the `__init__` comment:
```python
# All writes must go through _set_foo() to emit fooChanged.
# Mirrors Swift @Published var foo: String.
self.foo: str = ""
```

---

## Swift → Python Reactivity Mapping Reference

| Swift mechanism | Python equivalent | Notes |
|---|---|---|
| `@Published var foo: T` | `Signal(T)` + helper setter | Every write emits the signal |
| `objectWillChange.send()` | Multiple `emit()` calls batched before writes | Used for atomic multi-property updates |
| `@ObservedObject` / `@StateObject` | `.connect()` in view `__init__` | One-time wiring |
| `onChange(of: foo)` modifier | `.connect()` to a dedicated slot | Slot called on every change |
| `@Published var foo` with `didSet` | Helper setter that both assigns and has side-effects | Side-effects go in the helper, not at call sites |
| View reads `analyzer.foo` in `body` | View reads `analyzer.foo` inside a slot handler | Must be triggered by a signal, not polled |
| Swift computed view property `var bar: T { A + B + C }` | Python assembly call: `set_bar(A, B, C)` at every write site of A, B, or C | Rule 6 — N-to-1 aggregation; no automatic equivalent |
| Slot handler receives `signal.emit(x, y)` | Slot uses `x` and `y` directly, not `self.saved_peaks` | Rule 7 — payload is authoritative; legacy arrays may be empty |
| `@Published var foo` classified as **View-local** | View-local state written at every Swift write site of `foo` | Rule 5a — view-local write-site enumeration; partial coverage is a bug |

---

## Files to Audit

All `.py` files that write to properties mirroring `@Published` declarations:

| File | Properties written | Status |
|---|---|---|
| `tap_tone_analyzer_spectrum_capture.py` | `material_tap_phase`, `frozen_frequencies`, `frozen_magnitudes`, material spectra | See results doc |
| `tap_tone_analyzer_control.py` | `material_tap_phase` (via `_reset_material_phase_state`) | See results doc |
| `tap_tone_analyzer_tap_detection.py` | `tap_detected`, `is_detecting`, `is_above_threshold`, `status_message`, `current_tap_count`, `tap_progress`, `frozen_*` | See results doc |
| `tap_tone_analyzer_decay_tracking.py` | `is_tracking_decay`, `current_decay_time` | See results doc |
| `tap_tone_analyzer_measurement_management.py` | `saved_measurements`, `is_measurement_complete` | See results doc |
| `tap_tone_analyzer_analysis_helpers.py` | `identified_modes`, `current_peaks` | See results doc |
| `tap_tone_analyzer_annotation_management.py` | `peak_annotation_offsets`, `peak_mode_overrides`, `selected_peak_ids` | See results doc |

The status column is filled in by the audit results document
`REACTIVE_PROPERTY_AUDIT_RESULTS.md`.
