# Model Parity Analysis: Python ↔ Swift

Analysis of the 7 modified Python model files against their Swift counterparts.
Written 2026-04-06. Scope: files modified since the last commit that live under
`src/guitar_tap/models/`.

**Parity Principle:** Python mirrors Swift — same structure, same declaration order,
same algorithm, same naming (snake_case ↔ camelCase). Python-only necessities
(e.g. `from_string` for QSettings normalisation, mixin base classes) are acceptable
additions; they are not parity violations.

---

## Overall Verdict

| Python file | Swift counterpart | Verdict |
|---|---|---|
| `annotation_visibility_mode.py` | `AnnotationVisibilityMode.swift` | ✅ Equivalent |
| `tap_display_settings.py` | `TapDisplaySettings.swift` | ⚠️ Minor gaps (see §2) |
| `tap_tone_analyzer_annotation_management.py` | `TapToneAnalyzer+AnnotationManagement.swift` | ⚠️ Structural extras (see §3) |
| `tap_tone_analyzer_mode_override_management.py` | `TapToneAnalyzer+ModeOverrideManagement.swift` | ⚠️ Structural extras (see §4) |
| `tap_tone_analyzer_analysis_helpers.py` | `TapToneAnalyzer+AnalysisHelpers.swift` | ❌ Wrong file — core content belongs in PeakAnalysis (see §5) |
| `tap_tone_analyzer_measurement_management.py` | `TapToneAnalyzer+MeasurementManagement.swift` | ✅ Equivalent |
| `tap_tone_analyzer_peak_analysis.py` | `TapToneAnalyzer+PeakAnalysis.swift` | ⚠️ Missing methods (see §7) |

---

## §1 — `annotation_visibility_mode.py` ↔ `AnnotationVisibilityMode.swift`

**Verdict: ✅ Equivalent**

| Aspect | Swift | Python | Notes |
|---|---|---|---|
| Cases | `all`, `selected`, `none` | `ALL="all"`, `SELECTED="selected"`, `NONE="none"` | ✅ Raw values match Codable serialization |
| Cycle order | `all→selected→none→all` | identical | ✅ |
| `iconName` / `icon_name` | SF Symbols: `"eye"`, `"star.fill"`, `"eye.slash"` | QtAwesome: `"fa5.eye"`, `"fa5.star"`, `"fa5.eye-slash"` | ✅ Platform-appropriate equivalents |
| `label` / `label` | `"All"`, `"Selected"`, `"None"` | `self.value.capitalize()` → same strings | ✅ |
| `from_string` | absent (not needed — Swift uses Codable) | present (QSettings boundary normalisation) | ✅ Acceptable Python-only addition |
| `str, Enum` base | N/A | allows `mode == "selected"` comparisons | ✅ Acceptable Python accommodation |

No issues found.

---

## §2 — `tap_display_settings.py` ↔ `TapDisplaySettings.swift`

**Verdict: ⚠️ Minor gaps**

### What matches

- All major settings groups are present in both: measurement type, plate dimensions,
  brace dimensions, gore thicknessing, display frequency range, dB range, analysis
  frequency range, peak detection, tap detection, annotation visibility mode, and
  `reset_to_defaults()` / `resetToDefaults()`.
- Default constants are numerically identical.
- `annotation_visibility_mode()` and `set_annotation_visibility_mode()` were correctly
  added; they are the primary focus of the recent work.
- `validate_frequency_range()` and `validate_magnitude_range()` correctly mirror Swift.

### Gaps identified

**Gap 1 — `plateStiffness` computed property absent in Python.**

Swift `TapDisplaySettings` exposes a `plateStiffness` computed property that resolves
the preset-or-custom logic and returns the effective numeric stiffness value. Python
has `plate_stiffness_preset()` and `custom_plate_stiffness()` but no combining
`plate_stiffness()` classmethod.

**Gap 2 — Legacy aliases block.**

Python has three legacy alias classmethods that have no Swift equivalents:
`analysis_f_min()`, `analysis_f_max()`, and `tap_threshold()`. These exist for
backward compatibility with older call sites but violate parity — Swift uses only the
canonical names `analysisMinFrequency`, `analysisMaxFrequency`, and `tapThreshold`.

### Recommendation

Add `plate_stiffness()` classmethod to `TapDisplaySettings` mirroring Swift.
`PlateStiffnessPreset` already exists in Python (`plate_stiffness_preset.py`) with a
`value` property that returns the numeric `f_vs` for each preset (returning `0` for
`CUSTOM`). The implementation is therefore straightforward:

```python
@classmethod
def plate_stiffness(cls) -> float:
    """Effective plate vibrational stiffness (f_vs): preset lookup or custom value.

    Mirrors Swift TapDisplaySettings.plateStiffness.
    """
    from guitar_tap.models.plate_stiffness_preset import PlateStiffnessPreset
    preset_str = cls.plate_stiffness_preset()   # returns raw string from QSettings
    try:
        preset = PlateStiffnessPreset(preset_str)
    except ValueError:
        preset = PlateStiffnessPreset.CUSTOM
    return cls.custom_plate_stiffness() if preset == PlateStiffnessPreset.CUSTOM else preset.value
```

---

## §3 — `tap_tone_analyzer_annotation_management.py` ↔ `TapToneAnalyzer+AnnotationManagement.swift`

**Verdict: ⚠️ Structural extras — Python mixin contains methods that live in a different Swift file**

### What matches

The annotation-offset management block maps perfectly:

| Python method | Swift method |
|---|---|
| `update_annotation_offset(peak_id, offset)` | `updateAnnotationOffset(for:offset:)` |
| `get_annotation_offset(peak_id)` | `getAnnotationOffset(for:)` |
| `reset_annotation_offset(peak_id)` | `resetAnnotationOffset(for:)` |
| `reset_all_annotation_offsets()` | `resetAllAnnotationOffsets()` |
| `apply_annotation_offsets(offsets)` | `applyAnnotationOffsets(_:)` |

Plate peak selection also maps correctly:

| Python method | Swift method |
|---|---|
| `effective_longitudinal_peak_id` | `effectiveLongitudinalPeakID` |
| `effective_cross_peak_id` | `effectiveCrossPeakID` |
| `effective_flc_peak_id` | `effectiveFlcPeakID` |
| `select_longitudinal_peak(peak_id)` | `selectLongitudinalPeak(_:)` |
| `select_cross_peak(peak_id)` | `selectCrossPeak(_:)` |
| `select_flc_peak(peak_id)` | `selectFlcPeak(_:)` |

### Structural extras

Swift places the following methods on `TapToneAnalyzer` directly (in
`TapToneAnalyzer.swift` or `TapToneAnalyzer+PeakAnalysis.swift`), not in
`TapToneAnalyzer+AnnotationManagement.swift`. Python bundles them into the
annotation management mixin for practical reasons (they need
`selected_peak_ids`), but this is a structural divergence from Swift:

| Python method (in AnnotationManagement mixin) | Swift location |
|---|---|
| `toggle_peak_selection(peak_id)` | `TapToneAnalyzer.swift` |
| `select_all_peaks()` | `TapToneAnalyzer.swift` |
| `select_no_peaks()` | `TapToneAnalyzer.swift` |
| `reset_to_auto_selection()` | `TapToneAnalyzer+PeakAnalysis.swift` |
| `visible_peaks` (computed property) | `TapToneAnalyzer.swift` |
| `cycle_annotation_visibility()` | `TapToneAnalyzer.swift` |

**Action required:** Move each misplaced method to the Python file that mirrors its
Swift file:

- `toggle_peak_selection`, `select_all_peaks`, `select_no_peaks`, `visible_peaks`,
  `cycle_annotation_visibility` → `tap_tone_analyzer.py` (main class body, mirroring
  `TapToneAnalyzer.swift`)
- `reset_to_auto_selection` → `tap_tone_analyzer_peak_analysis.py` (mirroring
  `TapToneAnalyzer+PeakAnalysis.swift`)

### Parity violation: `clear_annotation_offsets()` alias

`clear_annotation_offsets()` is a backward-compatibility alias for
`reset_all_annotation_offsets()`. It has no Swift equivalent and is a parity
violation — Swift has only `resetAllAnnotationOffsets()`.

**Action required:** Update the 3 call sites to use `reset_all_annotation_offsets()`
directly, then delete the alias method entirely.

Call sites:
- `src/guitar_tap/views/peak_annotations.py` line 398
- `src/guitar_tap/models/tap_tone_analyzer_measurement_management.py` line 147
- `src/guitar_tap/models/tap_tone_analyzer_control.py` line 224

---

## §4 — `tap_tone_analyzer_mode_override_management.py` ↔ `TapToneAnalyzer+ModeOverrideManagement.swift`

**Verdict: ⚠️ Structural extras — Python mixin contains methods from other Swift files**

### What matches (the three "pure" override management methods)

| Python method | Swift method |
|---|---|
| `apply_mode_overrides(overrides)` | `applyModeOverrides(_:)` |
| `reset_all_mode_overrides()` | `resetAllModeOverrides()` |
| `reset_mode_override(peak_id)` | `resetModeOverride(for:)` |

Algorithms are identical. Arguments match. ✅

### Structural extras

The following methods in the Python mixin live in different Swift files:

| Python method (in ModeOverrideManagement mixin) | Swift location |
|---|---|
| `set_mode_override(mode, peak_id)` | `TapToneAnalyzer.swift` (direct method) |
| `has_manual_override(peak_id)` | `TapToneAnalyzer.swift` (direct method) |
| `effective_mode_label(peak)` | `TapToneAnalyzer.swift` (direct method) |
| `set_guitar_type(guitar_type)` | `TapToneAnalyzer.swift` (direct property setter) |
| `start_plate_analysis()` | `TapToneAnalyzer+SpectrumCapture.swift` |
| `reset_plate_analysis()` | `TapToneAnalyzer+SpectrumCapture.swift` |

**Action required:** Move each misplaced method to the Python file that mirrors its
Swift file:

- `set_mode_override`, `has_manual_override`, `effective_mode_label`,
  `set_guitar_type` → `tap_tone_analyzer.py` (main class body, mirroring
  `TapToneAnalyzer.swift`)
- `start_plate_analysis`, `reset_plate_analysis` → `tap_tone_analyzer_spectrum_capture.py`
  (mirroring `TapToneAnalyzer+SpectrumCapture.swift`)

---

## §5 — `tap_tone_analyzer_analysis_helpers.py` ↔ `TapToneAnalyzer+AnalysisHelpers.swift`

**Verdict: ❌ Wrong file — core content belongs in PeakAnalysis**

This is the most significant structural parity violation found.

### What Swift's AnalysisHelpers contains

Swift `TapToneAnalyzer+AnalysisHelpers.swift` contains only **thin query methods**:

| Swift method | Description |
|---|---|
| `getPeaks(in:)` | Return peaks within a frequency range |
| `peakMode(for:)` | Context-aware mode label for a peak |
| `getPeak(for:)` | Highest-magnitude peak for a given mode |
| `calculateTapToneRatio()` | Compute f_Top / f_Air ratio |
| `compareTo(_:)` | Compare current peaks against a saved measurement |

### What Python's analysis_helpers contains

Python `tap_tone_analyzer_analysis_helpers.py` contains:

| Python method | Correct Swift location |
|---|---|
| `recalculate_frozen_peaks_if_needed()` | **`TapToneAnalyzer+PeakAnalysis.swift`** |
| `_apply_frozen_peak_state(...)` | **`TapToneAnalyzer+PeakAnalysis.swift`** |
| `_emit_loaded_peaks_at_threshold()` | **`TapToneAnalyzer+PeakAnalysis.swift`** |
| `process_averages(mag_y)` | **`TapToneAnalyzer+SpectrumCapture.swift`** |

**None of the five methods that belong in AnalysisHelpers per the Swift definition
are present in Python's analysis_helpers.py.** They are also absent from
`tap_tone_analyzer_peak_analysis.py` (see §7).

### Impact

- `recalculate_frozen_peaks_if_needed()`, `_apply_frozen_peak_state()`, and
  `_emit_loaded_peaks_at_threshold()` live in the wrong file. In Swift these are
  in `TapToneAnalyzer+PeakAnalysis.swift`.
- `process_averages()` mirrors `averageSpectra` / `processMultipleTaps` logic from
  `TapToneAnalyzer+SpectrumCapture.swift`. It is in the wrong file.
- The five Swift AnalysisHelpers query methods (`getPeaks`, `peakMode`, `getPeak`,
  `calculateTapToneRatio`, `compareTo`) have **no Python equivalents anywhere** in
  the model layer.

### Missing methods

| Swift method | Python equivalent | Status |
|---|---|---|
| `getPeaks(in range: ClosedRange<Double>)` | `get_peaks(in_range)` | ❌ Missing |
| `peakMode(for peak: ResonantPeak)` | `peak_mode(for_peak)` | ❌ Missing |
| `getPeak(for mode: GuitarMode)` | `get_peak(for_mode)` | ❌ Missing |
| `calculateTapToneRatio()` | `calculate_tap_tone_ratio()` | ❌ Missing |
| `compareTo(_ measurement: TapToneMeasurement)` | `compare_to(measurement)` | ❌ Missing |

### Recommendation

1. **Add the five missing query methods** to `tap_tone_analyzer_analysis_helpers.py`
   to match Swift's actual content.
2. **Move `recalculate_frozen_peaks_if_needed()`, `_apply_frozen_peak_state()`, and
   `_emit_loaded_peaks_at_threshold()`** to `tap_tone_analyzer_peak_analysis.py` to
   match Swift's file structure.
3. **Move `process_averages()`** to `tap_tone_analyzer_spectrum_capture.py` to match
   `TapToneAnalyzer+SpectrumCapture.swift`.

These are structural moves, not logic changes — the algorithms are correct.

---

## §6 — `tap_tone_analyzer_measurement_management.py` ↔ `TapToneAnalyzer+MeasurementManagement.swift`

**Verdict: ✅ Equivalent**

### Method mapping

| Python method | Swift method |
|---|---|
| `_persist_measurements()` | `persistMeasurements()` (called internally) |
| `import_measurements(json_str)` | `importMeasurements(json:)` |
| `import_measurements_from_data(data)` | `importMeasurements(from:)` |
| `save_measurement(measurement)` | `saveMeasurement(_:)` |
| `update_measurement(at, tap_location, notes)` | `updateMeasurement(at:tapLocation:notes:)` |
| `delete_measurement(at)` | `deleteMeasurement(at:)` |
| `delete_all_measurements()` | `deleteAllMeasurements()` |
| `set_measurement_complete(is_complete)` | `setMeasurementComplete(_:)` |
| `load_comparison(measurements)` | `loadComparison(measurements:)` |
| `clear_comparison()` | `clearComparison()` |
| `_comparison_label(m)` | `comparisonLabel(for:)` |

Algorithms are equivalent. Return types match. ✅

### Python-only additions

- Python's `load_comparison()` returns `[(label, color, freq_arr, mag_arr)]` tuples for
  PyQtGraph; Swift's returns `Void` (mutates state and uses SwiftUI binding). This
  difference is required by the Qt view layer — not a parity violation.

### Declaration order

Python matches Swift's top-to-bottom order: persistence → import → save → update →
delete → comparison. ✅

---

## §7 — `tap_tone_analyzer_peak_analysis.py` ↔ `TapToneAnalyzer+PeakAnalysis.swift`

**Verdict: ⚠️ Missing methods**

### What matches

| Python method | Swift method |
|---|---|
| `find_peaks(magnitudes, frequencies, ...)` | `findPeaks(magnitudes:frequencies:minHz:maxHz:)` |
| `remove_duplicate_peaks(peaks)` | `removeDuplicatePeaks(_:)` |
| `guitar_mode_selected_peak_ids(peaks)` | `guitarModeSelectedPeakIDs(from:)` |
| `average_spectra(from_taps)` | `averageSpectra(from:)` |
| `_make_peak(index, magnitudes, frequencies)` | `makePeak(at:magnitudes:frequencies:)` |
| `_parabolic_interpolate(magnitudes, frequencies, i)` | `parabolicInterpolate(magnitudes:frequencies:peakIndex:)` |
| `_calculate_q_factor(magnitudes, frequencies, ...)` | `calculateQFactor(magnitudes:frequencies:peakIndex:peakMagnitude:)` |

Algorithms are all equivalent. Two-pass `find_peaks` strategy matches Swift exactly:
mode-priority Pass 1, inter-mode Pass 2, assembly step. ✅

### Missing methods (live in analysis_helpers.py instead)

| Swift method | Python location | Correct Python location |
|---|---|---|
| `recalculateFrozenPeaksIfNeeded()` | `analysis_helpers.py` | should be here |
| `applyFrozenPeakState(peaks:...)` | `analysis_helpers.py` | should be here |
| `resetToAutoSelection()` | `annotation_management.py` | should be here |

### Missing methods (not ported at all)

| Swift method | Python equivalent | Status |
|---|---|---|
| `analyzeMagnitudes(_:frequencies:peakMagnitude:)` | `analyze_magnitudes(...)` | ❌ Missing |
| `reclassifyPeaks()` | `reclassify_peaks()` | ❌ Missing |

`analyzeMagnitudes` is the main live-tap entry point in Swift. In Python, equivalent
logic is distributed across `process_averages()` (in analysis_helpers.py) and direct
calls in the tap pipeline. `reclassifyPeaks()` re-runs mode classification without
re-running peak detection; Python has no direct equivalent.

### Declaration order

Python file order: `find_peaks` → `remove_duplicate_peaks` → `guitar_mode_selected_peak_ids`
→ `average_spectra` → `_make_peak` → `_parabolic_interpolate` → `_calculate_q_factor`.

Swift file order: `analyzeMagnitudes` → `recalculateFrozenPeaksIfNeeded` →
`resetToAutoSelection` → `findPeaks` → `applyFrozenPeakState` → `makePeak` →
`guitarModeSelectedPeakIDs` → `reclassifyPeaks` → `removeDuplicatePeaks` →
`parabolicInterpolate` → `calculateQFactor` → `averageSpectra`.

Python's order is broadly similar but: (a) starts with `find_peaks` rather than
`analyze_magnitudes`, (b) places `average_spectra` before the private helpers
rather than after `reclassifyPeaks`, and (c) omits the methods that live in
analysis_helpers.py. Once the structural moves in §5 are completed, the order
should be re-aligned.

---

## Summary of Issues

### Structural Issues (files in wrong place)

| Issue | Current location | Correct location | Action |
|---|---|---|---|
| `toggle_peak_selection`, `select_all_peaks`, `select_no_peaks`, `visible_peaks`, `cycle_annotation_visibility` | annotation_management.py | tap_tone_analyzer.py | Move (no logic change) |
| `reset_to_auto_selection` | annotation_management.py | peak_analysis.py | Move (no logic change) |
| `set_mode_override`, `has_manual_override`, `effective_mode_label`, `set_guitar_type` | mode_override_management.py | tap_tone_analyzer.py | Move (no logic change) |
| `start_plate_analysis`, `reset_plate_analysis` | mode_override_management.py | spectrum_capture.py | Move (no logic change) |
| `recalculate_frozen_peaks_if_needed`, `_apply_frozen_peak_state`, `_emit_loaded_peaks_at_threshold` | analysis_helpers.py | peak_analysis.py | Move (no logic change) |
| `process_averages` | analysis_helpers.py | spectrum_capture.py | Move (no logic change) |
| `clear_annotation_offsets()` alias | annotation_management.py | — (no Swift equivalent) | Delete alias; update 3 call sites to `reset_all_annotation_offsets()` |
| `analysis_f_min`, `analysis_f_max`, `tap_threshold` aliases | tap_display_settings.py | — (no Swift equivalent) | Update call sites to canonical names; delete alias block |

### Missing Methods

| Method | Swift file | Python action |
|---|---|---|
| `plate_stiffness()` computed property | `TapDisplaySettings.swift` | Add to tap_display_settings.py |
| `get_peaks(in_range)` | `TapToneAnalyzer+AnalysisHelpers.swift` | Add to analysis_helpers.py |
| `peak_mode(for_peak)` | `TapToneAnalyzer+AnalysisHelpers.swift` | Add to analysis_helpers.py |
| `get_peak(for_mode)` | `TapToneAnalyzer+AnalysisHelpers.swift` | Add to analysis_helpers.py |
| `calculate_tap_tone_ratio()` | `TapToneAnalyzer+AnalysisHelpers.swift` | Add to analysis_helpers.py |
| `compare_to(measurement)` | `TapToneAnalyzer+AnalysisHelpers.swift` | Add to analysis_helpers.py |
| `analyze_magnitudes(...)` | `TapToneAnalyzer+PeakAnalysis.swift` | Add to peak_analysis.py |
| `reclassify_peaks()` | `TapToneAnalyzer+PeakAnalysis.swift` | Add to peak_analysis.py |

### No Action Required

| File | Notes |
|---|---|
| `annotation_visibility_mode.py` | Fully equivalent ✅ |
| `tap_tone_analyzer_measurement_management.py` | Fully equivalent ✅ |
| `from_string()` in AnnotationVisibilityMode | Python-only necessity (QSettings boundary); not a violation |
| `load_comparison()` return type difference | Required by Qt view layer; not a violation |

---

## Implementation Priority

### High

- [x] Delete `clear_annotation_offsets()` alias; update 3 call sites to `reset_all_annotation_offsets()`
- [x] Delete `analysis_f_min` / `analysis_f_max` / `tap_threshold` aliases; update all call sites to canonical names
- [x] Add `plate_stiffness()` computed property to tap_display_settings.py
- [x] Add the 5 missing AnalysisHelpers query methods to analysis_helpers.py

### Medium

- [x] Move `toggle_peak_selection`, `select_all_peaks`, `select_no_peaks`, `visible_peaks`, `cycle_annotation_visibility` from annotation_management.py to tap_tone_analyzer.py
- [x] Move `set_mode_override`, `has_manual_override`, `effective_mode_label`, `set_guitar_type` from mode_override_management.py to tap_tone_analyzer.py
- [x] Move `reset_to_auto_selection` from annotation_management.py to peak_analysis.py
- [x] Move `start_plate_analysis`, `reset_plate_analysis` from mode_override_management.py to spectrum_capture.py
- [x] Move `recalculate_frozen_peaks_if_needed`, `_apply_frozen_peak_state`, `_emit_loaded_peaks_at_threshold` from analysis_helpers.py to peak_analysis.py
- [x] Move `process_averages` from analysis_helpers.py to spectrum_capture.py

### Low

- [x] Add `analyze_magnitudes()` to peak_analysis.py
- [x] Add `reclassify_peaks()` to peak_analysis.py
- [x] Re-align declaration order in peak_analysis.py after structural moves
