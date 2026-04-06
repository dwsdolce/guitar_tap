# Test Parity Analysis: Swift ↔ Python

Comparison of `GuitarTapTests/` (Swift) and `guitar_tap/tests/` (Python).
Written 2026-04-06.

---

## Overall Count

| | Swift | Python |
|---|---|---|
| Test files | 15 | 11 |
| Test suites/classes | 30+ | 40+ |
| Approximate test methods | ~97 | ~80 |

---

## File-by-File Status

| Swift file | Python file | Status |
|---|---|---|
| `TapDetectionTests.swift` (T1–T9) | `test_tap_detection.py` | ✅ Parity |
| `DecayTrackingTests.swift` (DK1–DK7) | `test_decay_tracking.py` | ✅ Parity |
| `DSPTests.swift` (F1–F9) | `test_dsp.py` | ✅ Parity |
| `PeakFindingTests.swift` (F10–F16, A1–A5) | `test_peak_finding.py` | ✅ Parity |
| `MeasurementCodableTests.swift` | `test_measurement_codable.py` | ✅ Parity |
| `PitchTests.swift` | `test_pitch.py` | ✅ Parity |
| `GuitarModeTests.swift` | `test_guitar_mode.py` | ✅ Parity |
| `ComparisonModeTests.swift` (CP-U1–U8) | `test_comparison_mode.py` | ✅ Parity |
| `PlatePropertiesTests.swift` + `BracePropertiesTests.swift` | `test_material_properties.py` | ✅ Python more thorough |
| `FrozenPeakRecalculationTests.swift` (PR1–PR7) | `test_frozen_peak_recalculation.py` | ✅ Python more thorough |
| `AnnotationStateTests.swift` (D1–D10, PS1–PS6) | `test_annotation_state.py` | ⚠️ Gap — see below |
| `ImportPersistenceTests.swift` (IP1–IP3) | **missing** | ❌ Not ported |
| `SpectrumViewGestureTests.swift` (C1–C8) | N/A | — Platform-specific (SwiftUI/Qt differ) |

---

## Detailed Gap Analysis

### 1. `AnnotationStateTests.swift` vs `test_annotation_state.py` — ⚠️ Structural mismatch

The Swift tests drive `TapToneAnalyzer` state directly (live properties on the
analyzer instance). The Python tests drive `TapToneMeasurement` data structures
(serialisation and round-trip). Both are valid but they test different things.

**Tests in Swift with no Python equivalent:**

| Swift test | Suite | What it tests |
|---|---|---|
| `togglePeakSelection_insertsThenRemoves` | `PeakSelection` | `togglePeakSelection()` on analyzer |
| `selectAllPeaks_selectsAllCurrentPeaks` | `PeakSelection` | `selectAllPeaks()` on analyzer |
| `selectNoPeaks_clearsAll` | `PeakSelection` | `selectNoPeaks()` on analyzer |
| `togglePeakSelection_setsModifiedFlag` | `UserModifiedPeakSelectionFlag` | `userHasModifiedPeakSelection` flag |
| `selectAllPeaks_setsModifiedFlag` | `UserModifiedPeakSelectionFlag` | flag set by `selectAllPeaks()` |
| `selectNoPeaks_setsModifiedFlag` | `UserModifiedPeakSelectionFlag` | flag set by `selectNoPeaks()` |
| `resetToAutoSelection_clearsFlagAndSelectsBestPerMode` | `UserModifiedPeakSelectionFlag` | `resetToAutoSelection()` |
| `resetToAutoSelection_emptyPeaks_isNoop` | `UserModifiedPeakSelectionFlag` | guard on empty peaks |
| `allMode_returnsAllCurrentPeaks` | `VisiblePeaks` | `visiblePeaks` computed property |
| `selectedMode_filtersToSelectedPeaks` | `VisiblePeaks` | `visiblePeaks` in `.selected` mode |
| `noneMode_returnsEmpty` | `VisiblePeaks` | `visiblePeaks` in `.none` mode |
| `noOverride_returnsAutoLabel` | `ModeOverrides` | `effectiveModeLabel(for:)` |
| `assignedOverride_returnsCustomLabel` | `ModeOverrides` | `effectiveModeLabel` with override |
| `hasManualOverride_trueForAssigned` | `ModeOverrides` | `hasManualOverride(for:)` |
| `clearOverride_revertsToAutoLabel` | `ModeOverrides` | clearing override |
| `cycleAnnotationVisibility_traversesAllModes` | `AnnotationVisibilityCycle` | `cycleAnnotationVisibility()` |

These tests require that `TapToneAnalyzer` have the following methods/properties,
which are present in Swift but their Python counterparts have not been verified:
- `toggle_peak_selection(id)`
- `select_all_peaks()` / `select_no_peaks()`
- `user_has_modified_peak_selection: bool`
- `reset_to_auto_selection()`
- `visible_peaks: list[ResonantPeak]`
- `effective_mode_label(for peak)`
- `has_manual_override(for id)`
- `set_mode_override(mode, for id)`
- `cycle_annotation_visibility()`

**Tests in Python with no Swift equivalent:**

Python `test_annotation_state.py` tests JSON round-trip behaviour of
`TapToneMeasurement` fields (`annotation_offsets`, `selected_peak_ids`,
`selected_peak_frequencies`, `peak_mode_overrides`, `annotation_visibility_mode`).
Swift serialisation is covered by `MeasurementCodableTests.swift` instead.
These Python tests are correct and should be kept.

**Recommendation for Python:** Add a new `TestAnnotationStateLive` class that
drives `TapToneAnalyzer` state directly, porting the 16 missing Swift tests.
Keep the existing `TapToneMeasurement` round-trip tests unchanged.

**Recommendation for Swift:** No changes needed — Swift tests are thorough.

---

### 2. `ImportPersistenceTests.swift` — ❌ Entirely missing from Python

Swift has three tests (IP1–IP3) that verify:
- `importMeasurements(json:)` returns true and persists to disk (IP1)
- `importMeasurements(from:)` persists to disk (IP2)
- Successive imports append rather than overwrite (IP3)

The Python equivalent methods would be on `TapToneAnalyzer`:
- `import_measurements(json_str)` → returns bool, appends to `saved_measurements`, writes to disk
- `import_measurements_from_data(data)` → same from bytes

Python's persistence path goes through `_persist_measurements()` →
`tap_analysis_results_view.save_all_measurements()`. The test needs to mock
or redirect the file write to a temp path (as the Swift test does via the
`XCTestConfigurationFilePath` environment variable redirect).

**Recommendation for Python:** Add `tests/test_import_persistence.py` porting
IP1–IP3. Use `tmp_path` (pytest fixture) to redirect the file write. Will
require verifying that `import_measurements` exists on `TapToneAnalyzer` and
calls `_persist_measurements()`.

**Recommendation for Swift:** No changes needed.

---

### 3. `FrozenPeakRecalculationTests.swift` vs `test_frozen_peak_recalculation.py` — Python more thorough

Swift has richer tests for the _live-tap path_ and _state remapping_ than Python.
Python's new `TestRecalculateFrozenPeaksIfNeeded` class (PR-A1–A5) covers the
integration entry point, but several Swift tests have no Python counterpart:

| Swift test | Coverage gap in Python |
|---|---|
| `isLoadingMeasurement_suppressesRecalculation` (PR1) | Python has no `is_loading_measurement` guard |
| `afterLoadingCompletes_recalculationRuns` (PR1b) | Same |
| `loadedPeaks_allBelowThreshold_clearsBothCollections` (PR2b) | Python doesn't test `identified_modes` being cleared |
| `loadedPath_usesSavedPeaks_notFrozenSpectrum` (PR2c) | Not tested in Python |
| `loadedPath_annotationOffset_remappedByFrequency` (PR3a) | Python tests helper logic, not on-analyzer remapping |
| `loadedPath_offsetForFilteredOutPeak_isDropped` (PR3b) | Same |
| `loadedPath_modeOverride_remappedByFrequency` (PR4) | Same |
| `loadedPath_overrideForFilteredOutPeak_isDropped` (PR4b) | Same |
| `loadedPath_manualSelection_carriedForwardByFrequency` (PR5a) | Python has no `user_has_modified_peak_selection` |
| `loadedPath_autoSelection_reRunsWhenNotModified` (PR5b) | Same |
| `liveTapPath_emptyPeaks_preservesSelectedPeakIDs` (PR6) | Python guard test doesn't verify `selected_peak_ids` preserved |
| `liveTapPath_annotationOffset_remappedByFrequency` (PR7) | Python tests remap helper, not live-tap path on analyzer |

Note: Some of these gaps exist because the Python `recalculate_frozen_peaks_if_needed()`
implementation does not yet perform annotation offset/override/selection remapping
(it only filters by threshold). The Swift implementation does full remapping.
This is a production code gap, not only a test gap.

**Recommendation for Python:** Close the production code gap in
`tap_tone_analyzer_analysis_helpers.py` first (add offset/override/selection
remapping to `recalculate_frozen_peaks_if_needed()`), then add the missing tests.

**Recommendation for Swift:** Add PR-A-style integration tests to
`FrozenPeakRecalculationTests.swift`. Python's `TestRecalculateFrozenPeaksIfNeeded`
(PR-A1–A5) tests `recalculateFrozenPeaksIfNeeded()` as a unified entry point —
constructing real spectra with `findPeaks` and verifying `currentPeaks` results
end-to-end. Swift currently tests lower-level frozen-peak and remapping logic but
has no equivalent integration test that calls `recalculateFrozenPeaksIfNeeded()`
directly with a synthetic spectrum. Add a `RecalculateFrozenPeaksIntegration`
suite mirroring PR-A1–A5.

---

### 4. `PlatePropertiesTests.swift` + `BracePropertiesTests.swift` vs `test_material_properties.py` — Python more thorough

Python adds `TestPlateAnisotropyRatios` (cross_long_ratio, long_cross_ratio) and
`TestWoodQuality` (enum values, colors, threshold evaluation) with no Swift
counterpart. These are pure Python extensions and are correct additions.

**Recommendation for Swift:** Add `AnisotropyRatioTests` and `WoodQualityTests`
suites to `PlatePropertiesTests.swift` (or a new `MaterialPropertiesExtendedTests.swift`)
to match Python's coverage. Verify that `PlateAnisotropyRatios` and `WoodQuality`
types exist in Swift (they almost certainly do given the Python port), then port
Python's ratio tests (cross/long ratio computation) and `WoodQuality` tests
(enum values, color associations, threshold evaluation) directly.

---

### 5. `SpectrumViewGestureTests.swift` — Intentionally absent from Python

The Swift gesture tests (C1–C8: frequency zoom, magnitude zoom, pan clamping)
test SwiftUI gesture math in `SpectrumView+GestureHandlers.swift`. The Python
UI uses Qt and has different zoom/pan mechanics. These tests are correctly absent
from Python.

---

## Summary of Work Required

### Python changes

| Priority | Work | File(s) |
|---|---|---|
| High | Add `TestAnnotationStateLive` class — 16 tests porting Swift D3/D3b/D4–D6/D7–D8/CI5 driving `TapToneAnalyzer` directly | `tests/test_annotation_state.py` (new class) |
| High | Verify/add missing methods on Python `TapToneAnalyzer`: `toggle_peak_selection`, `select_all_peaks`, `select_no_peaks`, `user_has_modified_peak_selection`, `reset_to_auto_selection`, `visible_peaks`, `effective_mode_label`, `has_manual_override`, `set_mode_override`, `cycle_annotation_visibility` | `models/tap_tone_analyzer_annotation_management.py`, `models/tap_tone_analyzer_mode_override_management.py` |
| High | Add `tests/test_import_persistence.py` — 3 tests porting Swift IP1–IP3 | New file |
| Medium | Extend `recalculate_frozen_peaks_if_needed()` to remap annotation offsets, mode overrides, and selection by frequency proximity (currently only threshold-filters) | `models/tap_tone_analyzer_analysis_helpers.py` |
| Medium | Add PR1–PR7 direct ports to `test_frozen_peak_recalculation.py` using `TapToneAnalyzer` state (offset/override/selection remapping) | `tests/test_frozen_peak_recalculation.py` |

### Swift changes

| Priority | Work | File(s) |
|---|---|---|
| Medium | Add `RecalculateFrozenPeaksIntegration` suite — 5 tests mirroring Python PR-A1–A5 (end-to-end `recalculateFrozenPeaksIfNeeded()` with synthetic spectra) | `FrozenPeakRecalculationTests.swift` |
| Medium | Add `AnisotropyRatioTests` and `WoodQualityTests` suites matching Python's `TestPlateAnisotropyRatios` and `TestWoodQuality` | `PlatePropertiesTests.swift` or new `MaterialPropertiesExtendedTests.swift` |

---

## Implementation Order

1. **Verify Python `TapToneAnalyzer` has the missing annotation methods** — read
   `tap_tone_analyzer_annotation_management.py` and `tap_tone_analyzer_mode_override_management.py`
   to confirm `toggle_peak_selection`, `visible_peaks`, `effective_mode_label`, etc. exist
   (some may already be present under different names).

2. **Add `TestAnnotationStateLive`** to `test_annotation_state.py` — these require
   only existing methods and no production code changes if the methods exist.

3. **Add `test_import_persistence.py`** — requires verifying that
   `TapToneAnalyzer.import_measurements()` exists and calls `_persist_measurements()`.

4. **Extend `recalculate_frozen_peaks_if_needed()`** to perform full Swift-parity
   remapping (offsets, overrides, selection). This is the highest-complexity item
   and should be done after the annotation method verification in step 1.

5. **Add PR1–PR7 direct-port tests** to `test_frozen_peak_recalculation.py`
   once step 4 is complete.

6. **Add `RecalculateFrozenPeaksIntegration` suite to Swift** — add 5 integration
   tests to `FrozenPeakRecalculationTests.swift` mirroring Python PR-A1–A5: construct
   a `TapToneAnalyzer`, set `frozenMagnitudes` / `freq` with a synthetic spectrum
   containing a known peak, call `recalculateFrozenPeaksIfNeeded()`, and assert on
   `currentPeaks`. One test per path: frozen-spectrum detects peak, threshold raise
   removes weak peak, loaded-measurement path filters by threshold, all-below-threshold
   yields empty, empty spectrum does not crash.

7. **Add `AnisotropyRatioTests` and `WoodQualityTests` to Swift** — read
   `MaterialProperties.swift` to confirm `PlateAnisotropyRatios` and `WoodQuality`
   exist, then add tests to `PlatePropertiesTests.swift` (or a new
   `MaterialPropertiesExtendedTests.swift`) matching Python's
   `TestPlateAnisotropyRatios` (cross/long ratio computation) and `TestWoodQuality`
   (enum values, color associations, threshold evaluation).
