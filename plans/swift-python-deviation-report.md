# Swift → Python Deviation Report

**Scope:** Uncommitted Swift changes in `GuitarTap/` vs the Python port at
`src/guitar_tap/`.
**Coverage:** Algorithmic, structural, normative, behavioural, and visual
deviations.
**Directive:** Analysis only — no code changes until instructed.
**Date:** 2026-04-27

---

## Legend

| Symbol | Meaning |
|--------|---------|
| 🔴 | Behavioural / algorithmic deviation — user-visible difference |
| 🟡 | Normative / stylistic deviation — output is equivalent but wording differs |
| 🔵 | Structural deviation — different code organisation, no runtime difference |
| ⚪ | Missing feature — Swift has it; Python is absent or stub-only |

---

## 1. Status Message: `load_measurement()` — "Resume" wording

**Severity:** 🔴 Behavioural (text shown to user)
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:623`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:680`

**Swift (current):**
```swift
statusMessage = "Loaded measurement (frozen). Press \u{2018}New Tap\u{2019} to start a new measurement."
```
Uses Unicode typographic quotes (`'New Tap'`) and does **not** mention "Resume".

**Python (current):**
```python
self._set_status_message(
    "Loaded measurement (frozen). Press 'Resume' or 'New Tap' to continue."
)
```
Uses ASCII straight quotes and still references "Resume", which was removed
from the UI in an earlier Swift fix.

**Required fix:** Change the Python string to match Swift exactly:
```python
self._set_status_message(
    "Loaded measurement (frozen). Press \u2018New Tap\u2019 to start a new measurement."
)
```

---

## 2. Status Bar: "Comparing N measurements" vs. "Tap comparison — N taps + averaged"

**Severity:** 🔴 Behavioural (text shown to user)
**File (Swift):** `TapToneAnalysisView+Controls.swift` (full and compact status
bars)
**File (Python):** Python status bar logic lives in
`views/tap_tone_analysis_view_controls.py` (stub) and
`views/tap_tone_analysis_view.py` (main window)

**Swift (current):**
- Full status bar:
  ```swift
  Text(tap.showingMultiTapComparison
       ? "Tap comparison — \(tap.tapEntries.count) taps + averaged"
       : "Comparing \(tap.comparisonSpectra.count) measurements")
  ```
- Compact status bar: same conditional with identical strings.

The key point is that `tap.tapEntries.count` (number of individual taps, *not*
counting the averaged entry) is used for the multi-tap branch, while
`comparisonSpectra.count` (which includes the averaged entry) is used for the
saved-measurement comparison branch.

**Python:** This specific conditional has not been confirmed in
`tap_tone_analysis_view_controls.py` (the file is currently a stub at 14 lines).
The status bar logic appears to remain in `tap_tone_analysis_view.py` (main
window). The status text for the comparison case must be audited to ensure it
uses `len(self.analyzer.tap_entries)` when `showing_multi_tap_comparison` is
`True`, and `len(self.analyzer._comparison_data)` otherwise.

**Required fix:** Verify the Python status bar emits:
- Multi-tap comparison active: `f"Tap comparison — {len(tap_entries)} taps + averaged"`
- Saved-measurement comparison: `f"Comparing {len(_comparison_data)} measurements"`

---

## 3. Selection Buttons Hidden During Multi-Tap Comparison

**Severity:** 🔴 Behavioural (UI control visible when it should not be)
**File (Swift):** `TapAnalysisResultsView.swift:196`
**File (Python):** `views/tap_analysis_results_view.py` (Qt results panel)

**Swift (current):**
```swift
if !sortedPeaksWithModes.isEmpty && !analyzer.showingMultiTapComparison {
    // All / None / Auto buttons
}
```
The All/Clear/Auto selection buttons are suppressed when
`showingMultiTapComparison` is `true`.

**Python:** The Python results panel renders the peak selection controls in its
`_build_controls_section()` or equivalent. It must guard on
`self.analyzer.showing_multi_tap_comparison` the same way.  The Python port of
this specific guard has not been confirmed present.

**Required fix:** Add `and not self.analyzer.showing_multi_tap_comparison` to
the Python condition that shows the All/Clear/Auto buttons.

---

## 4. `process_multiple_taps()` — `captured_taps` cleared inside vs. after

**Severity:** 🔴 Algorithmic (subtle ordering difference)
**File (Swift):** `TapToneAnalyzer+SpectrumCapture.swift:871`
**File (Python):** `models/tap_tone_analyzer_spectrum_capture.py:1058`

**Swift:** `capturedTaps` is **NOT** cleared inside `processMultipleTaps()` —
it is only cleared in `resetForNewSequence()` / `reset()`. This means the
per-tap data survives until the next sequence starts, which is correct:
`applyMultiTapComparisonOverlays(enabled:)` reads `tapEntries` (not `capturedTaps`)
so clearing `capturedTaps` immediately is safe. The code in Swift never clears
`capturedTaps` at the end of `processMultipleTaps`.

**Python:** At `process_multiple_taps()` line 1058:
```python
self.captured_taps.clear()
```
`captured_taps` is cleared **at the end of** `process_multiple_taps()`, immediately
after building `tap_entries`. This is functionally equivalent because `tap_entries`
has already been populated, but it differs structurally from Swift.

**Note:** This is a low-risk deviation since `tap_entries` carries the needed
data. However it could cause subtle differences if any code path reads
`captured_taps` after `processMultipleTaps()` returns — Swift retains them until
reset, Python does not.

---

## 5. `process_multiple_taps()` — `set_measurement_complete(True)` call

**Severity:** 🔴 Algorithmic / structural
**File (Swift):** `TapToneAnalyzer+SpectrumCapture.swift:804`
**File (Python):** `models/tap_tone_analyzer_spectrum_capture.py:965`

**Swift:**
```swift
setFrozenSpectrum(frequencies: avgFrequencies, magnitudes: avgMagnitudes)
isMeasurementComplete = true
```
`isMeasurementComplete` is set directly (no side effects in a setter beyond
`@Published` notification).

**Python:**
```python
self.set_frozen_spectrum(self.freq, avg_db)
self.set_measurement_complete(True)
```
`set_measurement_complete(True)` in Python calls `self.measurementComplete.emit(True)`
**immediately**, which fires view callbacks before `current_peaks`, `selected_peak_ids`,
and `identified_modes` are set. Swift's `@Published` defers UI updates to end-of-runloop,
so SwiftUI re-renders after all assignments complete.

This means in Python, if any slot connected to `measurementComplete` reads
`current_peaks` or `selected_peak_ids`, it will see stale values. The load path
avoids this by placing `measurementComplete.emit(True)` last; the live capture
path has this ordering issue.

**Required fix consideration:** Call `self.set_measurement_complete(True)` last
(after `peaksChanged` and all other state is set) to match Swift's deferred
update semantics, OR don't emit `measurementComplete` inside `set_measurement_complete`
for the live capture path.

---

## 6. `process_multiple_taps()` — Missing `loadedMeasurementPeaks = nil` reset

**Severity:** 🔴 Algorithmic
**File (Swift):** `TapToneAnalyzer+SpectrumCapture.swift:819`
**File (Python):** `models/tap_tone_analyzer_spectrum_capture.py` (around line 1001)

**Swift:**
```swift
loadedMeasurementPeaks = nil      // New live result — no longer remapping from a loaded measurement
selectedPeakFrequencies = []      // Reset frequency cache for the new live session
```

**Python:**
```python
self.loaded_measurement_peaks = None   # ← at line 1001, AFTER peaksChanged.emit()
```
`loaded_measurement_peaks` is set to `None` after `peaksChanged.emit()` in Python.
In Swift it is cleared before the peaks are classified and before `identifiedModes`
is set. The ordering could affect `recalculate_frozen_peaks_if_needed()` if it
runs during the `peaksChanged` handler.

Additionally, Swift also clears `selectedPeakFrequencies = []` at this point to
reset the frequency cache. Python sets:
```python
self.selected_peak_frequencies = [
    p.frequency for p in peaks if p.id in self.selected_peak_ids
]
```
…but this is set *before* `peaksChanged`, which is a difference from Swift's
ordering (`selectedPeakFrequencies = []` first, then a fresh list is built in
the caller).

---

## 7. `applyMultiTapComparisonOverlays()` — `displayMode` set to `.comparison`

**Severity:** ✅ Consistent — intentional two-flag design
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:988`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:805`

Both Swift and Python set `displayMode = .comparison` (/ `COMPARISON`) when
activating multi-tap comparison overlays. This is **intentional** in both — the
chart's `materialSpectra` computed property reads `comparisonSpectra` only in
`.comparison` mode.

The Results panel uses `showingMultiTapComparison` (not `displayMode`) as the
authoritative gate for its content. This two-flag design is what keeps the guitar
summary footer visible and suppresses the "Comparison" badge while the per-tap
overlays are displayed. The Swift doc comment has been updated to make this design
explicit (previously it incorrectly stated "The analyzer stays in `.frozen` display
mode throughout").

**Status:** ✅ Consistent — no deviation.

---

## 8. `MultiTapComparisonResultsView` — No Python equivalent view class

**Severity:** ⚪ Missing feature
**File (Swift):** `GuitarTap/Views/MultiTapComparisonResultsView.swift`
**File (Python):** No `MultiTapComparisonResultsView` widget exists

**Swift:** `MultiTapComparisonResultsView` is a dedicated SwiftUI `View` struct
with:
- Per-tap rows (colored circle + "Tap N" label + Air/Top/Back Hz columns)
- Averaged row (filled square indicator + "Averaged" + Air/Top/Back Hz, bold/semibold)
- `labelColumnWidth = 110`, `columnWidth = 72`
- Uses `TapToneAnalyzer.resolvedModePeaks(peaks:guitarType:)` for frequency lookup
- Colors from fixed `palette: [.blue, .orange, .green, .purple, .teal]`
- Averaged row color: `Color(red: 1.0, green: 0.85, blue: 0.0)` (bold yellow)

**Python:** The existing `ComparisonResultsView` Qt widget (in
`views/comparison_results_view.py`) handles the saved-measurement comparison
grid (Air/Top/Back per spectrum). It accepts a generic `comparison_data` list
and could in principle be reused for multi-tap comparison, but:
- There is no `MultiTapComparisonResultsView` class in Python
- The `TapAnalysisResultsView` (Python results panel) has not been confirmed to
  instantiate and show this view when `showing_multi_tap_comparison` is `True`

**Required fix:** Either create a new `MultiTapComparisonResultsView` Qt widget
or extend `ComparisonResultsView` to handle the multi-tap case. The widget must
be wired into the Python analysis results panel, shown when
`analyzer.showing_multi_tap_comparison` is `True`.

---

## 9. `TapAnalysisResultsView` — Taps Toggle Button

**Severity:** ⚪ Missing feature
**File (Swift):** `TapAnalysisResultsView.swift:138–165`
**File (Python):** Python results panel (in `tap_tone_analysis_view.py` or its
submodules)

**Swift:**
```swift
// Show "Taps" button when: guitar, complete, tapEntries non-empty, not already showing multi-tap, not in saved comparison
if measurementType.isGuitar
    && analyzer.isMeasurementComplete
    && !analyzer.tapEntries.isEmpty
    && !analyzer.showingMultiTapComparison
    && analyzer.displayMode != .comparison {
    Button { … Label("Taps", systemImage: "waveform.path.badge.plus") … }
        .tint(default)
} else if analyzer.showingMultiTapComparison {
    Button { … Label("Taps", systemImage: "waveform.path.badge.minus") … }
        .tint(.orange)
}
```

The toggle button:
- Has `waveform.path.badge.plus` icon when off, `waveform.path.badge.minus` when on
- Tinted orange when active
- Suppressed during saved-measurement comparison (`displayMode == .comparison && !showingMultiTapComparison`)

**Python:** This toggle button (or equivalent) has not been confirmed present
in the Python results panel.

---

## 10. `TapAnalysisResultsView` — `guitarAnalysisSummary` footer during multi-tap

**Severity:** 🔴 Behavioural
**File (Swift):** `TapAnalysisResultsView.swift:292–295`

**Swift:**
```swift
if measurementType.isGuitar
    && (analyzer.displayMode != .comparison || analyzer.showingMultiTapComparison) {
    guitarAnalysisSummary
}
```
The Ring-Out / Tap Ratio footer **remains visible** during multi-tap comparison
because `showingMultiTapComparison == true` overrides the comparison-mode
suppression.

**Python:** The Python results panel must apply the same combined condition.
If it currently hides the footer for any `displayMode == COMPARISON` state
(without the `showingMultiTapComparison` exception), this is a deviation.

---

## 11. `TapAnalysisResultsView` — "Comparison" badge suppression

**Severity:** 🔴 Behavioural (visual badge shown when it should not be)
**File (Swift):** `TapAnalysisResultsView.swift:169`

**Swift:**
```swift
// Show "Comparison" badge only for saved-measurement comparisons,
// not for the multi-tap comparison view.
if analyzer.displayMode == .comparison && !analyzer.showingMultiTapComparison {
    Text("Comparison") …
} else {
    Text(measurementType.shortName) …
}
```
When `showingMultiTapComparison` is `True`, the "Comparison" badge is NOT shown;
the measurement type badge (e.g., "Classical") IS shown.

**Python:** Must apply the same `and not showing_multi_tap_comparison` condition
when deciding whether to show the "Comparison" badge vs the measurement-type badge.

---

## 12. `sortedPeaksWithModes` guard during multi-tap comparison

**Severity:** 🔴 Algorithmic / behavioural
**File (Swift):** `TapAnalysisResultsView.swift:343`

**Swift:**
```swift
private var sortedPeaksWithModes: [(peak: ResonantPeak, mode: GuitarMode)] {
    // Return empty during saved-measurement comparison, but NOT during multi-tap comparison
    guard analyzer.displayMode != .comparison || analyzer.showingMultiTapComparison else { return [] }
    …
}
```
During multi-tap comparison (`displayMode == .comparison` AND
`showingMultiTapComparison == true`), `sortedPeaksWithModes` returns the
averaged peaks (non-empty), because the averaged peaks are still valid and
displayed in the `MultiTapComparisonResultsView` "Averaged" row.

**Python:** The Python equivalent of `sortedPeaksWithModes` must apply the same
combined guard, or `MultiTapComparisonResultsView` will receive no averaged peaks
for its "Averaged" row.

---

## 13. `load_comparison()` — Missing `min_db / max_db` axis union

**Severity:** 🟡 Normative
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:851–856`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:938–944`

**Swift:**
```swift
if !snapshots.isEmpty,
   let minF = snapshots.map(\.minFreq).min(),
   let maxF = snapshots.map(\.maxFreq).max(),
   let minD = snapshots.map(\.minDB).min(),
   let maxD = snapshots.map(\.maxDB).max() {
    setLoadedAxisRange(minFreq: minF, maxFreq: maxF, minDB: minD, maxDB: maxD)
}
```
Swift sets both the frequency **and** dB axis ranges from the union of all
snapshot bounds.

**Python:**
```python
if with_snapshots:
    snaps = [m.spectrum_snapshot for m in with_snapshots]
    min_freq = int(min(s.min_freq for s in snaps))
    max_freq = int(max(s.max_freq for s in snaps))
    self.update_axis(min_freq, max_freq)
```
Python only updates the frequency axis (`update_axis`). The dB range is not
restored from snapshot data. This means loading a comparison may render at the
wrong dB scale if the saved measurements used a non-default dB range.

---

## 14. `load_measurement()` — `_restore_comparison_from_entries` missing `min_db / max_db`

**Severity:** 🟡 Normative
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:442–445`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:1044–1049`

**Swift:**
```swift
if let minF = snaps.map(\.minFreq).min(), let maxF = snaps.map(\.maxFreq).max(),
   let minD = snaps.map(\.minDB).min(), let maxD = snaps.map(\.maxDB).max() {
    setLoadedAxisRange(minFreq: minF, maxFreq: maxF, minDB: minD, maxDB: maxD)
}
```

**Python:**
```python
snaps = [e.snapshot for e in entries]
if snaps:
    min_f = min(s.min_freq for s in snaps)
    max_f = max(s.max_freq for s in snaps)
    self.update_axis(int(min_f), int(max_f))
```
Same omission as item 13 — dB range is not restored.

---

## 15. `save_measurement()` — `measurement_type` field not saved in Python

**Severity:** 🔴 Behavioural (affects reload fidelity)
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:284–312` — `TapToneMeasurement` init
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:309–336`

**Swift:** `TapToneMeasurement` does not have a top-level `measurementType` field;
the measurement type is embedded inside the `SpectrumSnapshot` (as
`snapshot.measurementType`) and in per-phase snapshots.

**Python `TapToneMeasurement.create()`** receives `measurement_type=mt_str` as a
top-level field, which is stored directly on the measurement. This is an
additive Python-only field (not in Swift) and does not cause a reload regression,
but means the Python JSON contains `measurementType` at the top level while
Swift JSON does not (the type is only in the snapshot). Cross-compatibility
round-trips should still work because `load_measurement()` reads the type from
the snapshot first and falls back to the top-level field.

**Assessment:** 🔵 Structural — no behavioural deviation, round-trip safe.

---

## 16. `apply_multi_tap_comparison_overlays()` — `avg_snap` missing `show_unknown_modes`, `guitar_type`, `measurement_type`

**Severity:** 🟡 Normative
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:960–972`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:775–783`

**Swift builds `avgSnap` with all `TapDisplaySettings` fields:**
```swift
let avgSnap = SpectrumSnapshot(
    …
    showUnknownModes: TapDisplaySettings.showUnknownModes,
    guitarType: TapDisplaySettings.guitarType,
    measurementType: TapDisplaySettings.measurementType,
    maxPeaks: maxPeaks
)
```

**Python builds a minimal snapshot:**
```python
avg_snap = _SS(
    frequencies=list(avg_freqs),
    magnitudes=list(avg_mags),
    min_freq=…, max_freq=…, min_db=…, max_db=0.0,
    is_logarithmic=False,
)
```
Missing: `show_unknown_modes`, `guitar_type`, `measurement_type`, `max_peaks`.
These are used by `ComparisonResultsView` to classify peaks and by export
functions to determine the measurement type. Since the averaged snapshot is
used for display only (not saved), the impact is limited but classification
of the "Averaged" row's modes may fall back to defaults.

---

## 17. `_comparison_data` structure — `"snapshot"` key presence inconsistency

**Severity:** 🔵 Structural
**File (Python):** `models/tap_tone_analyzer_measurement_management.py`

In `apply_multi_tap_comparison_overlays()` the per-tap entries added to
`self._comparison_data` use keys `"label"`, `"color"`, `"freqs"`, `"mags"`,
`"peaks"`, `"guitar_type"` (no `"snapshot"` key).

In `load_comparison()` entries have keys `"label"`, `"color"`, `"freqs"`,
`"mags"`, `"snapshot"`, `"peaks"`, `"guitar_type"`.

Code that reads `_comparison_data` and assumes a `"snapshot"` key will fail
during multi-tap comparison overlays. This includes any code in
`ComparisonResultsView` or the export path that reads
`entry.get("snapshot")`.

---

## 18. `TapToneMeasurement` — `tap_entries` codec round-trip

**Severity:** 🔵 Structural
**File (Swift):** `TapToneMeasurement.swift` — custom `encode(to:)` / `init(from:)`
**File (Python):** `models/tap_tone_measurement.py` — `to_dict()` / `from_dict()`

Both implementations encode `tapEntries` / `tap_entries` and decode it with
`decodeIfPresent` / dict fallback, preserving backward compatibility.

**Confirmed consistent:** ✅ No deviation in encode/decode logic.

---

## 19. `MultiTapComparisonResultsView` — `labelColumnWidth` and `columnWidth`

**Severity:** 🟡 Normative (visual sizing)
**File (Swift):** `MultiTapComparisonResultsView.swift:138–139`

```swift
private var labelColumnWidth: CGFloat { 110 }
private var columnWidth: CGFloat { 72 }
```

**Python `ComparisonResultsView`** (which would be reused or mirrored):
```python
_COLUMN_WIDTH = 80   # pixels — Swift 72pt
_LABEL_WIDTH  = 130  # pixels — Swift 110pt
```
The Python column widths are wider than Swift's pt values. This is expected
because Qt px ≈ CSS px and HiDPI/platform differences exist, but the label
column (130 vs 110) is notably wider. When the new
`MultiTapComparisonResultsView` is created it should use widths calibrated to
the Qt environment, matching the visual proportion of the Swift view.

---

## 20. `processMultipleTaps()` — `tapProgress = 1.0` placement

**Severity:** ✅ Consistent
**File (Swift):** `TapToneAnalyzer+SpectrumCapture.swift:828`
**File (Python):** `models/tap_tone_analyzer_spectrum_capture.py:1008`

**Swift:**
```swift
statusMessage = "Analysis complete! …"
tapProgress = 1.0
```
`tapProgress` is set immediately after the status message, before building
`tapEntries`.

**Python:**
```python
self._set_status_message("Analysis complete! …")
self.tap_progress = 1.0
```
Same ordering. ✅ Consistent.

---

## 21. `applyMultiTapComparisonOverlays(enabled: false)` — disable path differences

**Severity:** 🔵 Structural
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:929–934`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:731–736`

**Swift:**
```swift
guard enabled else {
    comparisonSpectra = []
    comparisonSnapshots = []
    displayMode = .frozen
    return
}
```

**Python:**
```python
if not enabled:
    self._comparison_data = []
    self.comparison_labels = []        # ← Python-only
    self.comparison_snapshots = []
    self._display_mode = AnalysisDisplayMode.FROZEN
    self.comparisonChanged.emit(False) # ← Python-only
    return
```

Two Python-only lines have no Swift counterpart, both for structural reasons:

- **`self.comparison_labels = []`** — `comparison_labels` is a Python-only list of
  `(label, color)` tuples consumed by `fft_canvas.py:1382` for legend rendering.
  Swift stores label and color directly inside the `comparisonSpectra` tuple elements,
  so no separate list exists. Clearing it here keeps the two parallel lists in sync.
- **`self.comparisonChanged.emit(False)`** — explicit Qt signal notification. Swift
  achieves the equivalent implicitly: setting `comparisonSpectra = []` on a
  `@Published` property automatically notifies all SwiftUI observers.

The core logic — restoring `displayMode` to `.frozen` and clearing the overlay arrays
— is consistent. ✅ No behavioural deviation.

The existence of `comparison_labels` as a separate field is a symptom of the root
structural divergence described in **item 27** (`_comparison_data` vs `comparisonSpectra`).
Fixing item 27 eliminates `comparison_labels` entirely, which in turn removes the
Python-only line from this disable path.

---

## 22. `resetForNewSequence()` / `startTapSequence()` — `tapEntries` and `showingMultiTapComparison` cleared

**Severity:** ✅ Consistent
**File (Swift):** `TapToneAnalyzer+Control.swift` (confirmed in previous session)
**File (Python):** `models/tap_tone_analyzer_control.py`

Both implementations clear `tapEntries = []` and reset
`showingMultiTapComparison = false` in `reset()`, `cancelTapSequence()`, and
`startTapSequence()`.

---

## 23. `saveMeasurement()` — `tapEntries` included only for guitar

**Severity:** 🔵 Structural
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:311`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:303–307`

**Swift:**
```swift
tapEntries: measurementType.isGuitar && !tapEntries.isEmpty ? tapEntries : nil
```

**Python:**
```python
tap_entries_to_save = (
    list(self.tap_entries)
    if mt.is_guitar and getattr(self, "tap_entries", [])
    else None
)
```

The logic is equivalent — both save `tapEntries` only when the measurement is guitar and the array is non-empty — but the Python form has two structural differences from Swift:

1. **`getattr(self, "tap_entries", [])` defensive fallback** — unnecessary if `tap_entries` is always initialised (which it is, in `__init__`). Swift accesses `tapEntries` directly with no fallback because the property is guaranteed to exist. The `getattr` form is a maintenance smell: if the attribute ever moves or is renamed, the fallback silently produces `None` instead of raising an `AttributeError`.

2. **`list(self.tap_entries)` copy** — Swift passes the array directly; Python makes a shallow copy. The copy is harmless but unnecessary if `tap_entries` is not mutated during the save path.

**Required fix:** Replace with an explicit form matching Swift:
```python
tap_entries_to_save = self.tap_entries if mt.is_guitar and self.tap_entries else None
```

---

## 24. `loadMeasurement()` — `showLoadedSettingsWarning` placement

**Severity:** ✅ Consistent
**File (Swift):** `TapToneAnalyzer+MeasurementManagement.swift:729`
**File (Python):** `models/tap_tone_analyzer_measurement_management.py:674`

**Swift:** `showLoadedSettingsWarning = true` is set before restoring `tapEntries`.
**Python:** `self.show_loaded_settings_warning = True` is set at line 674, also before `tap_entries` (at line 691). ✅ Same order.

---

## 25. `ComparisonResultsView` — `_rebuild` called with `entry.get("peaks", [])` vs. pre-filtered selected peaks

**Severity:** 🔵 Structural
**File (Python):** `views/comparison_results_view.py:123`

```python
peaks = entry.get("peaks", [])
```

In Swift, `MultiTapComparisonResultsView` and `ComparisonResultsView` are two
distinct typed views — each receives strongly-typed data (named tuples /
`TapEntry` structs) with no dict key lookups. In Python, both the
saved-measurement comparison path and the multi-tap comparison path route through
the same `ComparisonResultsView` widget using untyped dict entries with
`entry.get("peaks", [])`, `entry.get("color", …)`, etc.

The peak-filtering outcome is currently equivalent — both paths pre-filter peaks
to `selected_peaks` before storing in `_comparison_data` — so there is no
behavioural deviation today. However, the mechanism is structurally different from
Swift: Python relies on dict key conventions and pre-filtering discipline at the
call site, while Swift enforces correct data at the type level.

This is a symptom of the root structural divergence in **item 27**
(`_comparison_data` untyped dicts vs `comparisonSpectra` typed named-tuple array).
Fixing item 27 (typed `ComparisonSpectrumEntry` dataclass) and item 8
(`MultiTapComparisonResultsView`) would eliminate the dict key dependency and
align Python with Swift's type-safe approach.

---

## 26. `help_view.py` — Multi-Tap Comparison section

**Severity:** ✅ Consistent
The help view has had the Multi-Tap Comparison section added (noted in previous
session). Not re-verified here but assumed consistent.

---

## 27. `_comparison_data` vs `comparisonSpectra` — naming and container type

**Severity:** 🔵 Structural (requires fix)
**File (Swift):** `TapToneAnalyzer.swift:688`
**File (Python):** `models/tap_tone_analyzer.py:339`

These are the same concept — the list of overlay spectra consumed by the chart
renderer when `displayMode == .comparison` — but they differ in name and container
type, creating an ongoing maintenance burden.

**Swift:**
```swift
@Published var comparisonSpectra: [(magnitudes: [Float], frequencies: [Float],
    color: Color, label: String, peaks: [ResonantPeak], guitarType: GuitarType?)] = []
```
A typed named-tuple array. All fields (including `label` and `color`) live in one
place. The chart's `materialSpectra` computed property maps it down to the 4-field
subset it needs.

**Python:**
```python
self._comparison_data: list = []      # list of dicts: {label, color, freqs, mags, peaks, guitar_type}
self.comparison_labels: list = []     # parallel list of (label, color) tuples — for fft_canvas legend
```
An untyped list of dicts plus a separate parallel list. The parallel `comparison_labels`
list exists *because* the dict design doesn't give `fft_canvas.py`'s legend renderer
direct typed access to label/color without a second scan of `_comparison_data`.

**Required fix:** Rename `_comparison_data` → `comparison_spectra` (matching Swift's
`comparisonSpectra`) and convert each entry from an untyped dict to a typed
`ComparisonSpectrumEntry` dataclass (or `NamedTuple`) with fields matching Swift's
tuple: `magnitudes`, `frequencies`, `color`, `label`, `peaks`, `guitar_type`.
This eliminates the need for the separate `comparison_labels` list, since label and
color are directly accessible on the typed entry. All sites that currently use string
keys (`entry["label"]`, `entry.get("color", …)`, etc.) would be updated to attribute
access (`entry.label`, `entry.color`, etc.).

**Scope:** `tap_tone_analyzer.py` (definition), `tap_tone_analyzer_measurement_management.py`
(~10 sites), `fft_canvas.py` (~4 sites), `tap_tone_analysis_view.py` (~6 sites),
`comparison_results_view.py` (~3 sites).

---

## Summary Table

| # | Area | Severity | Description |
|---|------|----------|-------------|
| 1 | Status message on load | 🔴 | Wrong wording: "Resume" + ASCII quotes vs. typographic 'New Tap' |
| 2 | Status bar comparison text | 🔴 | Must branch on `showing_multi_tap_comparison` using correct counts |
| 3 | Selection buttons hidden | 🔴 | All/Clear/Auto buttons must be suppressed during multi-tap comparison |
| 4 | `captured_taps` cleared timing | 🔴 | Python clears inside `process_multiple_taps`; Swift clears on reset only |
| 5 | `set_measurement_complete` ordering | 🔴 | Python emits `measurementComplete` before peaks are set |
| 6 | `loaded_measurement_peaks` clear ordering | 🔴 | Cleared after `peaksChanged` in Python; before in Swift |
| 7 | `applyMultiTapComparisonOverlays` displayMode | ✅ | Consistent |
| 8 | `MultiTapComparisonResultsView` | ⚪ | No Python equivalent widget exists |
| 9 | Taps toggle button | ⚪ | Not confirmed present in Python results panel |
| 10 | `guitarAnalysisSummary` footer during multi-tap | 🔴 | Must not be suppressed when `showing_multi_tap_comparison == True` |
| 11 | "Comparison" badge suppression | 🔴 | Badge must not show during multi-tap comparison |
| 12 | `sortedPeaksWithModes` guard | 🔴 | Must return averaged peaks during multi-tap comparison |
| 13 | `load_comparison()` dB axis | 🟡 | Python only updates freq axis, not dB range |
| 14 | `_restore_comparison_from_entries` dB axis | 🟡 | Same omission |
| 15 | Top-level `measurement_type` field | 🔵 | Python-only field; safe for round-trips |
| 16 | `avg_snap` missing fields | 🟡 | Averaged snapshot missing `show_unknown_modes`, `guitar_type`, etc. |
| 17 | `_comparison_data` `"snapshot"` key missing | 🔵 | Multi-tap path lacks `"snapshot"`; OK for current consumers |
| 18 | `TapToneMeasurement` codec | ✅ | Consistent |
| 19 | Column widths | 🟡 | Python widths larger than Swift pt values (platform-appropriate) |
| 20 | `tapProgress` placement | ✅ | Consistent (was mislabelled 🔵) |
| 21 | `displayMode` reset on disable | 🔵 | Python-only `comparison_labels` clear + `comparisonChanged` signal; core logic consistent |
| 22 | `tapEntries` reset on new sequence | ✅ | Consistent (was mislabelled 🔵) |
| 23 | `tapEntries` in save | 🔵 | `getattr` fallback + unnecessary copy; fix to direct attribute access |
| 24 | `showLoadedSettingsWarning` ordering | ✅ | Consistent (was mislabelled 🔵) |
| 25 | `ComparisonResultsView` peak filtering | 🔵 | Untyped dict lookup vs Swift typed views; safe today, fixed by items 27 + 8 |
| 26 | Help view | ✅ | Consistent (assumed) |
| 27 | `_comparison_data` vs `comparisonSpectra` | 🔵 | Rename + retype to typed dataclass; eliminates parallel `comparison_labels` list |

---

## Priority Order for Fixes

1. **Item 1** — Status message wording: single-line change, high user-visibility
2. **Item 8** — `MultiTapComparisonResultsView` widget: core missing feature
3. **Item 9** — Taps toggle button in results panel
4. **Items 10, 11, 12** — Results panel conditional guards
5. **Item 3** — Selection buttons suppression
6. **Items 2** — Status bar text branching
7. **Item 5** — `measurementComplete` emit ordering (subtle but correctness risk)
8. **Items 13, 14** — dB axis restoration on comparison load
9. **Item 16** — `avg_snap` missing fields
10. **Items 4, 6** — `captured_taps` timing and peak clear ordering (low risk)
11. **Item 23** — `tap_entries_to_save`: remove `getattr` fallback and `list()` copy; one-line fix
12. **Item 27** — `_comparison_data` rename + retype: significant refactor but eliminates `comparison_labels` parallel list and prevents future sync bugs
