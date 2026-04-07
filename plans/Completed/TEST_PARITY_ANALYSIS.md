# Test Parity Plan: Swift ↔ Python

**Principle:** Python mirrors Swift — same logical tests in the same files. When a
test sits in the wrong file in either codebase, it must move. This document
identifies every misplacement and specifies where each test belongs.

Written 2026-04-06. Replaces previous analysis.

---

## Current Test Counts

| | Swift | Python |
|---|---|---|
| Test files | 15 | 12 |
| Test methods | ~234 | 255 |

---

## File Pairing (canonical)

| Swift file | Python file |
|---|---|
| `AnnotationStateTests.swift` | `test_annotation_state.py` |
| `BracePropertiesTests.swift` | `test_material_properties.py` |
| `ComparisonModeTests.swift` | `test_comparison_mode.py` |
| `DSPTests.swift` | `test_dsp.py` |
| `DecayTrackingTests.swift` | `test_decay_tracking.py` |
| `FrozenPeakRecalculationTests.swift` | `test_frozen_peak_recalculation.py` |
| `GuitarModeTests.swift` | `test_guitar_mode.py` |
| `ImportPersistenceTests.swift` | `test_import_persistence.py` |
| `MeasurementCodableTests.swift` | `test_measurement_codable.py` |
| `PeakFindingTests.swift` | `test_peak_finding.py` |
| `PitchTests.swift` | `test_pitch.py` |
| `PlatePropertiesTests.swift` | `test_material_properties.py` |
| `SpectrumViewGestureTests.swift` | N/A (platform-specific) |
| `TapDetectionTests.swift` | `test_tap_detection.py` |

---

## Problems: Tests in the Wrong File

### Problem 1 — `annotationVisibilityCycle` and `annotationVisibility_iconNames` are in `GuitarModeTests.swift`

These two tests live in `GuitarModeTests.swift` inside `GuitarModeClassificationTests`:

```
annotationVisibilityCycle_allToSelectedToNoneToAll
annotationVisibility_iconNames_nonEmpty
```

They test `AnnotationVisibilityMode` — not `GuitarMode`. Their Python counterparts
(`test_D4_visibility_mode_stored_as_string`, `test_D5_all_visibility_values_survive_round_trip`,
`test_CI5_visibility_mode_cycle`) are already in `test_annotation_state.py`.

**Fix:** Move both tests from `GuitarModeTests.swift` into `AnnotationStateTests.swift`
under the existing `@Suite("AnnotationVisibilityCycle")` suite (which currently has
only `cycleAnnotationVisibility_traversesAllModes`). The icon-name test can join as a
second member of that suite.

No Python change needed — the Python file already has these tests in the right place.

---

### Problem 2 — `UpdateMeasurementTests` is in `MeasurementCodableTests.swift`

Swift `MeasurementCodableTests.swift` contains `@Suite("UpdateMeasurement")` with 5
tests that exercise `TapToneAnalyzer.updateMeasurement(at:tapLocation:notes:)` — a
**state-mutation** operation on the live analyzer, not a JSON codable test.

```
update_byIndex_changesOnlyTargetedEntry
update_duplicateImport_onlyEditedIndexChanges
update_nilValues_clearFields
update_outOfRangeIndex_isNoOp
update_preservesIdAndOtherFields
```

`MeasurementCodableTests.swift` is paired with `test_measurement_codable.py`.
Python has no `TestUpdateMeasurement` class anywhere.

`AnnotationStateTests.swift` is the correct home for analyzer state-mutation tests
(it already contains `@Suite("AnnotationOffsets")`, `@Suite("PeakSelection")`, etc.).
The Python pair for `AnnotationStateTests.swift` is `test_annotation_state.py`.

**Fix (Swift):** Move `@Suite("UpdateMeasurement")` from `MeasurementCodableTests.swift`
into `AnnotationStateTests.swift`.

**Fix (Python):** Add a `TestUpdateMeasurement` class to `test_annotation_state.py`
with 5 tests mirroring the Swift suite:
- `test_update_by_index_changes_only_targeted_entry`
- `test_update_duplicate_import_only_edited_index_changes`
- `test_update_nil_values_clear_fields`
- `test_update_out_of_range_index_is_noop`
- `test_update_preserves_id_and_other_fields`

---

### Problem 3 — Python `test_annotation_state.py` has data-structure tests that belong in `test_measurement_codable.py`

Python's `test_annotation_state.py` contains classes that test `TapToneMeasurement`
JSON round-trips — not live analyzer state:

| Python class | What it tests | Correct file |
|---|---|---|
| `TestAnnotationOffsets` | annotation offsets survive JSON round-trip | `test_measurement_codable.py` |
| `TestPeakSelection` | selected_peak_ids stored in JSON, TapToneRatio uses selected peaks | `test_measurement_codable.py` |
| `TestAnnotationVisibilityMode` | visibility mode stored/round-trips as JSON string | `test_measurement_codable.py` |
| `TestModeOverrides` | mode overrides stored/round-trip in JSON | `test_measurement_codable.py` |
| `TestPeakSelectionTracking` | selected_peak_ids + selected_peak_frequencies JSON fields | `test_measurement_codable.py` |

Swift already covers all of these in `MeasurementCodableTests.swift`:
- `@Suite("TapToneMeasurementCodable")` — `annotationOffsets_roundTrip_preserved`
- `@Suite("TapToneRatio")` — selected peaks behavior
- Codable round-trip includes visibility mode and overrides

**Fix:** Move the five classes listed above from `test_annotation_state.py` to
`test_measurement_codable.py`. The `TestAnnotationStateLive` class and any remaining
live-analyzer tests stay in `test_annotation_state.py`.

No Swift change needed — the Swift file is already correctly structured.

---

## Target State After Changes

### `GuitarModeTests.swift` ↔ `test_guitar_mode.py`

**Remove from Swift `GuitarModeTests.swift`:**
- `annotationVisibilityCycle_allToSelectedToNoneToAll`
- `annotationVisibility_iconNames_nonEmpty`

Both codebases then contain only `GuitarMode` classification, normalization,
display names, mode ranges, and classifyAll tests.

---

### `AnnotationStateTests.swift` ↔ `test_annotation_state.py`

**Add to Swift `AnnotationStateTests.swift`** (from `MeasurementCodableTests.swift`):
- `@Suite("UpdateMeasurement")` — 5 tests

**Add to Python `test_annotation_state.py`**:
- `TestUpdateMeasurement` — 5 tests (new, mirrors Swift suite)

**Remove from Python `test_annotation_state.py`** (move to `test_measurement_codable.py`):
- `TestAnnotationOffsets` (2 tests)
- `TestPeakSelection` (3 tests)
- `TestAnnotationVisibilityMode` (4 tests)
- `TestModeOverrides` (4 tests)
- `TestPeakSelectionTracking` (6 tests)

After these changes, both files contain only live-analyzer state tests.

**Swift suites (target):**
- `AnnotationOffsets` — 3 tests (update/overwrite/apply)
- `PeakSelection` — 3 tests (toggle/selectAll/selectNone)
- `UserModifiedPeakSelectionFlag` — 5 tests
- `VisiblePeaks` — 3 tests (all/selected/none modes)
- `ModeOverrides` — 4 tests
- `AnnotationVisibilityCycle` — 2 tests (cycle + icon names, after move from GuitarMode)
- `PlatePeakSelection` — 6 tests
- `UpdateMeasurement` — 5 tests (moved from MeasurementCodable)

**Python classes (target):**
- `TestAnnotationStateLive` — 26 tests (unchanged)
- `TestUpdateMeasurement` — 5 tests (new)

---

### `MeasurementCodableTests.swift` ↔ `test_measurement_codable.py`

**Remove from Swift `MeasurementCodableTests.swift`** (moved to `AnnotationStateTests.swift`):
- `@Suite("UpdateMeasurement")` — 5 tests

**Add to Python `test_measurement_codable.py`** (moved from `test_annotation_state.py`):
- `TestAnnotationOffsets` — 2 tests
- `TestPeakSelection` — 3 tests
- `TestAnnotationVisibilityMode` — 4 tests
- `TestModeOverrides` — 4 tests
- `TestPeakSelectionTracking` — 6 tests

After these changes, both files contain only `TapToneMeasurement` data structure
and JSON codable tests.

---

## Summary of All Moves

| What | From | To | Action |
|---|---|---|---|
| `annotationVisibilityCycle_allToSelectedToNoneToAll` | `GuitarModeTests.swift` | `AnnotationStateTests.swift` | Move (Swift) |
| `annotationVisibility_iconNames_nonEmpty` | `GuitarModeTests.swift` | `AnnotationStateTests.swift` | Move (Swift) |
| `@Suite("UpdateMeasurement")` (5 tests) | `MeasurementCodableTests.swift` | `AnnotationStateTests.swift` | Move (Swift) |
| `TestAnnotationOffsets` (2 tests) | `test_annotation_state.py` | `test_measurement_codable.py` | Move (Python) |
| `TestPeakSelection` (3 tests) | `test_annotation_state.py` | `test_measurement_codable.py` | Move (Python) |
| `TestAnnotationVisibilityMode` (4 tests) | `test_annotation_state.py` | `test_measurement_codable.py` | Move (Python) |
| `TestModeOverrides` (4 tests) | `test_annotation_state.py` | `test_measurement_codable.py` | Move (Python) |
| `TestPeakSelectionTracking` (6 tests) | `test_annotation_state.py` | `test_measurement_codable.py` | Move (Python) |
| `TestUpdateMeasurement` (5 tests) | (does not exist) | `test_annotation_state.py` | Add (Python) |

---

## Files Unchanged

All other file pairs have correct placement and need no changes:

- `TapDetectionTests.swift` / `test_tap_detection.py`
- `DecayTrackingTests.swift` / `test_decay_tracking.py`
- `DSPTests.swift` / `test_dsp.py`
- `PeakFindingTests.swift` / `test_peak_finding.py`
- `PitchTests.swift` / `test_pitch.py`
- `ComparisonModeTests.swift` / `test_comparison_mode.py`
- `PlatePropertiesTests.swift` + `BracePropertiesTests.swift` / `test_material_properties.py`
- `FrozenPeakRecalculationTests.swift` / `test_frozen_peak_recalculation.py`
- `ImportPersistenceTests.swift` / `test_import_persistence.py`
- `SpectrumViewGestureTests.swift` / N/A

---

## Verification

After all changes:
1. Swift: `BuildProject` — must build cleanly with no errors
2. Python: `cd /Users/dws/src/guitar_tap && .venv/bin/pytest tests/ -q` — must show 260/260

Python count: current 255 + 5 new `TestUpdateMeasurement` tests = 260.
The 5 Python data-structure classes moving between files do not change the total count.

---

## Step Completion Checklist

### Swift
- [x] Move `annotationVisibilityCycle_allToSelectedToNoneToAll` from `GuitarModeTests.swift` to `AnnotationStateTests.swift`
- [x] Move `annotationVisibility_iconNames_nonEmpty` from `GuitarModeTests.swift` to `AnnotationStateTests.swift`
- [x] Move `@Suite("UpdateMeasurement")` (5 tests) from `MeasurementCodableTests.swift` to `AnnotationStateTests.swift`

### Python
- [x] Move `TestAnnotationOffsets` from `test_annotation_state.py` to `test_measurement_codable.py`
- [x] Move `TestPeakSelection` from `test_annotation_state.py` to `test_measurement_codable.py`
- [x] Move `TestAnnotationVisibilityMode` from `test_annotation_state.py` to `test_measurement_codable.py`
- [x] Move `TestModeOverrides` from `test_annotation_state.py` to `test_measurement_codable.py`
- [x] Move `TestPeakSelectionTracking` from `test_annotation_state.py` to `test_measurement_codable.py`
- [x] Add `TestUpdateMeasurement` (5 tests) to `test_annotation_state.py`

### Verification
- [x] Swift: `BuildProject` — clean, no errors
- [x] Python: `pytest tests/ -q` — 260/260 passing
