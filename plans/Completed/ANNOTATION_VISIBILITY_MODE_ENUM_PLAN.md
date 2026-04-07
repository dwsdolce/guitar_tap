# Plan: AnnotationVisibilityMode Enum (Swift + Python)

**Goal:** Replace raw strings for `annotation_visibility_mode` with a proper enum in both
Swift and Python, keeping the two codebases structurally identical.

**Principle:** Python mirrors Swift — not the other way around. If Swift structure is wrong,
fix Swift first, then make Python match.

---

## Summary

The `annotation_visibility_mode` field is used as a raw string throughout both codebases.
Swift already has a typed enum (`AnnotationVisibilityMode`) but it is embedded inside
`TapToneAnalyzer.swift` rather than in its own file like every other model enum. Python
uses raw strings with no type safety at all, and had two inconsistent casing conventions
(`"Selected"` from QSettings vs `"selected"` in the model) requiring repeated `.lower()`
normalization calls.

This plan:
1. Moves the Swift enum to its own file (matching the project convention).
2. Creates a Python `AnnotationVisibilityMode` enum matching Swift's interface exactly
   (same cases, same `next` cycle, equivalent `icon_name`/`label` properties).
3. Propagates the enum through the Python model and view layers, eliminating all raw-string
   comparisons and the `.lower()` normalization workarounds.

---

## Step Completion Checklist

- [x] **Step 1** — Swift: Create `AnnotationVisibilityMode.swift`; remove enum from `TapToneAnalyzer.swift`
- [x] **Step 2** — Python: Add `icon_name` and `label` to `annotation_visibility_mode.py`
- [x] **Step 3** — Python: `models/tap_display_settings.py` updated (import, typed return, `.value` setter)
- [x] **Step 4** — Python: `models/tap_tone_analyzer.py` (import, typed `Published` default, `from_string` in init)
- [x] **Step 5** — Python: `models/tap_tone_analyzer_annotation_management.py` (enum in `visible_peaks` + `cycle_annotation_visibility`)
- [x] **Step 6** — Python: `views/tap_tone_analysis_view.py` (`_ANN_MODES` → enum, all use sites)
- [x] **Step 7** — Python: `views/exportable_spectrum_chart.py` (`from_string` + enum comparisons)
- [x] **Verify** — Swift build clean; Python `pytest tests/ -q` shows 255/255

---

## Current State (Problem)

Swift defines `AnnotationVisibilityMode` **inside** `TapToneAnalyzer.swift` (lines 73–118),
not in its own file. Every other model enum in Swift has its own file
(`GuitarMode.swift`, `GuitarType.swift`, `MeasurementType.swift`, etc.).

Python already has `annotation_visibility_mode.py` (partially created), correctly
following the one-enum-per-file convention — but Swift did not yet match.

The Python `annotation_visibility_mode.py` has `next` and `from_string`, but is missing
the `icon_name` and `label` properties that Swift's enum also exposes (used by the view).

---

## Swift Enum (complete, from TapToneAnalyzer.swift lines 75–118)

```swift
enum AnnotationVisibilityMode: String, Codable, CaseIterable {
    case all
    case selected
    case none

    var next: AnnotationVisibilityMode { ... }     // all→selected→none→all
    var iconName: String { ... }                   // "eye" / "star.fill" / "eye.slash"
    var label: String { ... }                      // "All" / "Selected" / "None"
}
```

---

## Changes Required

### Step 1 — Swift: Move enum to its own file ✅ DONE

**Created** `GuitarTap/GuitarTap/Models/AnnotationVisibilityMode.swift` with the full
enum definition (doc comment, cases, `next`, `iconName`, `label`).

**Removed** the `// MARK: - AnnotationVisibilityMode` block (lines 73–118) from
`TapToneAnalyzer.swift`.

### Step 2 — Python: Add missing properties to `annotation_visibility_mode.py`

The file already exists with `ALL`, `SELECTED`, `NONE`, `next`, and `from_string`.
Add `icon_name` and `label` properties to match Swift:

```python
@property
def icon_name(self) -> str:
    """QtAwesome icon name. Mirrors Swift iconName (SF Symbols → fa5 equivalents)."""
    _map = {
        AnnotationVisibilityMode.ALL:      "fa5.eye",
        AnnotationVisibilityMode.SELECTED: "fa5.star",
        AnnotationVisibilityMode.NONE:     "fa5.eye-slash",
    }
    return _map[self]

@property
def label(self) -> str:
    """Short display label. Mirrors Swift label."""
    return self.value.capitalize()   # "all"→"All", "selected"→"Selected", "none"→"None"
```

### Step 3 — Python: `models/tap_display_settings.py` ✅ DONE

Already updated: import, typed return (`AnnotationVisibilityMode`), `.value` on setter.

### Step 4 — Python: `models/tap_tone_analyzer.py`

- Import `AnnotationVisibilityMode`
- Change `Published` default: `"selected"` → `AnnotationVisibilityMode.SELECTED`
- Change init: `self.annotation_visibility_mode = AnnotationVisibilityMode.from_string(_tds.annotation_visibility_mode())`
  (removes the manual `.lower()` added in the quick-fix pass)

### Step 5 — Python: `models/tap_tone_analyzer_annotation_management.py`

- Import `AnnotationVisibilityMode`
- `visible_peaks`: replace `.lower()` string comparisons with enum identity:
  ```python
  mode = self.annotation_visibility_mode
  if mode == AnnotationVisibilityMode.ALL:
      return list(self.current_peaks)
  if mode == AnnotationVisibilityMode.SELECTED:
      return [p for p in self.current_peaks if p.id in self.selected_peak_ids]
  return []
  ```
- `cycle_annotation_visibility()`: replace dict + `.lower()` with `mode.next`:
  ```python
  self.annotation_visibility_mode = self.annotation_visibility_mode.next
  ```

### Step 6 — Python: `views/tap_tone_analysis_view.py`

- Import `AnnotationVisibilityMode`
- Replace `_ANN_MODES` tuple (title-case strings + icon names) with enum values;
  derive `icon_name` and `label` from the enum:
  ```python
  _ANN_MODES: tuple[AnnotationVisibilityMode, ...] = (
      AnnotationVisibilityMode.SELECTED,
      AnnotationVisibilityMode.NONE,
      AnnotationVisibilityMode.ALL,
  )
  ```
  All `name` references become `mode.label`, all icon references become `mode.icon_name`.
- Init (load saved mode): `TDS.annotation_visibility_mode()` now returns the enum; find
  `_saved_idx` by comparing enum values.
- `_on_cycle_annotation_mode()`: call `TDS.set_annotation_visibility_mode(next_mode)`
  directly (accepts enum); tooltip uses `next_mode.label`.
- `_apply_annotation_mode()`: passes enum to `peak_widget.model.annotation_mode`
  (or `.value` if the widget still needs a string — check at implementation time).
- Load measurement: replace `_mode_name_map` + `.lower()` with
  `AnnotationVisibilityMode.from_string(m.annotation_visibility_mode)`.
- Export path: same `from_string` replacement.

### Step 7 — Python: `views/exportable_spectrum_chart.py`

- Import `AnnotationVisibilityMode`
- Replace `.lower()` string switching with `from_string` + enum comparisons.

---

## What Does NOT Change

- `views/utilities/tap_settings_view.py` — QSettings boundary; keeps raw `str` I/O
- `models/tap_tone_measurement.py` — JSON data bag; field stays `str | None`
- JSON key `"annotationVisibilityMode"` and values `"all"`, `"selected"`, `"none"`
- All existing tests — `str, Enum` means `mode == "selected"` still passes

---

## Files Changed Summary

| File | Change |
|---|---|
| `GuitarTap/GuitarTap/Models/AnnotationVisibilityMode.swift` | **NEW** ✅ — enum extracted from TapToneAnalyzer.swift |
| `GuitarTap/GuitarTap/Models/TapToneAnalyzer.swift` | Lines 73–118 removed ✅ |
| `src/guitar_tap/models/annotation_visibility_mode.py` | Add `icon_name` and `label` properties |
| `src/guitar_tap/models/tap_display_settings.py` | Already updated ✅ |
| `src/guitar_tap/models/tap_tone_analyzer.py` | Import + typed Published default |
| `src/guitar_tap/models/tap_tone_analyzer_annotation_management.py` | Use enum in `visible_peaks` + `cycle_annotation_visibility` |
| `src/guitar_tap/views/tap_tone_analysis_view.py` | Replace `_ANN_MODES` strings with enum |
| `src/guitar_tap/views/exportable_spectrum_chart.py` | Use `from_string` + enum comparisons |

---

## Verification

1. Swift: `BuildProject` — must build cleanly with no errors
2. Python: `cd /Users/dws/src/guitar_tap && .venv/bin/pytest tests/ -q` — must show 255/255
