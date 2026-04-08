# Structural Divergences vs. SWIFTUI_COMPAT_VIEW_LAYER_PLAN

Cross-reference of every divergence in `STRUCTURAL_DIVERGENCE_AUDIT.md` against
`SWIFTUI_COMPAT_VIEW_LAYER_PLAN.md`.

For each item the question is:

- **Fix before** — fixing it is a prerequisite or enabler for the view-layer rewrite, or
  fixing it during the rewrite would force double-churn on the same code.
- **Fix during** — the view-layer rewrite naturally rewrites the affected file(s); the
  fix belongs inside that rewrite rather than as a prior step.
- **Fix after** — independent of the view-layer plan's scope; neither a prerequisite nor
  a natural part of it.
- **Model layer** — purely in `models/`; SWIFTUI_COMPAT_VIEW_LAYER_PLAN explicitly
  excludes model files from its scope.

---

## Summary Table

| # | Divergence | Layer(s) touched | Verdict |
|---|---|---|---|
| 1 | `identified_modes` dict vs named tuple | Model | Fix after (model layer) |
| 2 | Thread safety — AnnotationManagement | Model | Fix after (model layer) |
| 3 | Thread safety — ModeOverrideManagement | Model | Fix after (model layer) |
| 4 | `saveMeasurement` parameter structure | Model / view boundary | Fix before |
| 5 | `loadMeasurement` in view vs model | Model / view boundary | Fix before |
| 6 | `loaded*` @Published properties absent | Model | Fix before |
| 7 | Material spectrum @Published absent | Model | Fix after (model layer) |
| 8 | `peakThreshold.didSet` missing side effect | Model | Fix after (model layer) |
| 9 | Settings persistence in view not model | Model / view boundary | Fix before |
| 10 | `cycleAnnotationVisibility` persistence | Model / view boundary | Fix before |
| 11 | `comparisonSpectra` structure | Model / view boundary | Fix before |
| 12 | PDF export source (live TDS vs snapshot) | View | Fix during |
| 13 | `peakModeOverrides` not forwarded in PDF | View | Fix during |
| 14 | Measurement file I/O location | Model | Fix after (model layer) |
| 15 | `exportMeasurement` absent from analyzer | Model | Fix after (model layer) |
| 16 | `delete_all_measurements` extra in Python | Model | Fix after (model layer) |
| 17 | `set_measurement_complete` extra in Python | Model | Fix after (model layer) |

---

## Detailed Rationale

---

### #1 — `identified_modes` dict vs named tuple

**Layer:** Model (`tap_tone_analyzer_peak_analysis.py`).

**SWIFTUI_COMPAT scope:** The plan explicitly states "All model-layer files (`models/`) —
What Does NOT Change."

**Verdict: Fix after.** This change is confined to the model and has no effect on the
view-layer rewrite. Fixing it first would require touching every model-layer access site
(`peak_mode`, `get_peak`, `reclassify_peaks`, `analyze_magnitudes`, etc.) with no
corresponding view-layer benefit.

---

### #2 — Thread safety, AnnotationManagement

**Layer:** Model (`tap_tone_analyzer_annotation_management.py`).

**Verdict: Fix after.** Pure model-layer concern. The view-layer plan removes explicit
signal wiring; it does not add threading guarantees. Thread safety of the model is an
independent correctness concern.

---

### #3 — Thread safety, ModeOverrideManagement

**Layer:** Model (`tap_tone_analyzer_mode_override_management.py`).

**Verdict: Fix after.** Same reasoning as #2.

---

### #4 — `saveMeasurement` parameter structure

**Layer:** Model/view boundary. Swift builds `TapToneMeasurement` inside the model
method. Python builds it in the view (`_collect_measurement()`) and passes the whole
object.

**SWIFTUI_COMPAT relevance:** The new `TapToneAnalysisView` root view (step 7 of the
migration sequence) will own `StateObject(TapToneAnalyzer)` and call model methods
directly. If `save_measurement` still takes a fully-built object, the view-layer code
will need to call `_collect_measurement()` before `save_measurement()`, which is a
view-layer responsibility that is absent from Swift. This pattern will need to be
established at write time for `tap_tone_analysis_view_actions.py`.

**Verdict: Fix before.** Moving assembly into the model aligns the call signature before
the new view files are written, so every new view file can call `analyzer.save_measurement()`
with individual parameters exactly as the Swift views do. Doing it during means the new
view action files will need to be written twice.

---

### #5 — `loadMeasurement` in view vs model

**Layer:** Model/view boundary. All measurement-restoration logic currently lives in the
view (`_restore_measurement`, ~360 lines).

**SWIFTUI_COMPAT relevance:** The plan rewrites `tap_tone_analysis_view.py` (step 7). If
`_restore_measurement` still lives in the view, its ~360 lines must be ported into the
new pyedifice view. If `load_measurement()` is on the model first, the new view simply
calls `analyzer.load_measurement(m)` — one line, mirroring Swift.

**Verdict: Fix before.** Moving `_restore_measurement` to the model as
`load_measurement()` before the view rewrite avoids porting 360 lines of imperative
widget-manipulation code into the new view layer (which would then need to be deleted
again immediately).

---

### #6 — `loaded*` @Published properties absent

**Layer:** Model (`tap_tone_analyzer.py` property declarations). SWIFTUI_COMPAT plan
states the model layer does not change — but this is the model-layer restructuring that
`PYTHON_ARCHITECTURE_RESTRUCTURING_PLAN.md` covers as a prerequisite.

**SWIFTUI_COMPAT relevance:** The plan's prerequisites section explicitly states:
"TapToneAnalyzer must already be an ObservableObject with Published properties." The 28
`loaded*` Published properties exist precisely to drive view-layer show/hide reactions
(loaded settings warnings, pre-populated UI fields). Without them, the new pyedifice
views must query measurement state imperatively rather than reactively — contradicting
the plan's architecture.

**Verdict: Fix before.** These properties must exist as Published before any view that
observes them is written.

---

### #7 — Material spectrum @Published properties absent

**Layer:** Model (`tap_tone_analyzer.py`).

**SWIFTUI_COMPAT relevance:** The material spectrum properties (`longitudinalSpectrum`,
`crossSpectrum`, `longitudinalPeaks`, `crossPeaks`, etc.) are observed by
`FFTAnalysisMetricsView` and `TapAnalysisResultsView`. Those views are rewritten in
steps 2 and 5 of the migration sequence.

**Verdict: Fix before.** These Published properties must exist before the views that
observe them are written. Without them the views cannot be ported reactively. However,
unlike #6, these are purely model declarations with no logic attached — they are low-risk
one-line additions that could be added as part of the view port for each dependent view
without sequencing risk.

**If sequencing is preferred:** add them to the model in a single pass before step 2 of
the migration sequence (leaf view ports). **If inline is preferred:** add each property
immediately before porting its first dependent view.

---

### #8 — `peakThreshold.didSet` missing side effect

**Layer:** Model (`tap_tone_analyzer.py`, `tap_tone_analyzer_peak_analysis.py`).

**SWIFTUI_COMPAT relevance:** The plan does not touch threshold-change logic. This is
purely a model side-effect gap.

**Verdict: Fix after.** Independent of the view-layer rewrite.

---

### #9 — Settings persistence in view, not model

**Layer:** Model/view boundary. Swift `@Published didSet` observers on the model persist
settings. Python persists in view-layer event handlers that will be deleted when
`_connect_signals()` is removed.

**SWIFTUI_COMPAT relevance:** The plan explicitly lists "Delete `MainWindow._connect_signals()`"
as a completion criterion. The persistence calls currently inside those signal handlers
(for `peak_threshold`, `tap_detection_threshold`, `hysteresis_margin`) will be deleted
with them. If persistence is not moved into the model first, changing these settings will
silently stop persisting.

**Verdict: Fix before.** Persistence must be in the model's Published property
change callbacks (or equivalent) before `_connect_signals()` is deleted. Otherwise a
model-layer gap is silently created by the view rewrite.

---

### #10 — `cycleAnnotationVisibility` persistence

**Layer:** Model/view boundary. The model method's docstring claims to persist; it does
not. Persistence happens in the view handler `_on_cycle_annotation_mode()`.

**SWIFTUI_COMPAT relevance:** `_on_cycle_annotation_mode()` is one of the signal-wired
view callbacks that will be removed when `_connect_signals()` is deleted. If not moved
first, annotation visibility stops persisting.

**Verdict: Fix before.** Same reasoning as #9: the view handler that carries the
persistence call will be deleted by the plan. Fix the model method to persist correctly
before that happens.

---

### #11 — `comparisonSpectra` structure (4-tuple array vs two lists)

**Layer:** Model/view boundary. The shape of `_comparison_data` and `comparison_labels`
determines how every view that renders comparison spectra is written.

**SWIFTUI_COMPAT relevance:** `SpectrumView` (step 6) and `TapAnalysisResultsView`
(step 5 area) consume comparison data. If the shape changes during the view rewrite, both
the model and the new views must be changed simultaneously. Aligning the model shape
first gives the view ports a stable contract.

**Verdict: Fix before.** Establish a single Published `comparison_spectra: list[tuple]`
on the model matching Swift's shape before the views that consume it are ported.

---

### #12 — PDF export: `guitarBodyLength/Width`, `plateStiffness` source

**Layer:** View (`tap_tone_analysis_view_export.py`, which is one of the new pyedifice
files in the migration).

**SWIFTUI_COMPAT relevance:** This divergence lives entirely within the export view,
which the plan rewrites as `views/tap_tone_analysis_view_export.py`. The fix belongs
inside that file's initial implementation — there is no prior artifact to clean up.

**Verdict: Fix during.** Write the export view to read from live `TapDisplaySettings`
(mirroring Swift) from the start.

---

### #13 — `peakModeOverrides` not forwarded in PDF

**Layer:** View (`tap_tone_analysis_view_export.py`).

**Verdict: Fix during.** Same file as #12. Pass `peak_mode_overrides` explicitly from
`analyzer.peak_mode_overrides` in `pdf_report_data_from_measurement()` when that file is
first written.

---

### #14 — Measurement file I/O location (views module vs model)

**Layer:** Model (`tap_tone_analyzer_measurement_management.py`). The plan explicitly
excludes model files.

**Verdict: Fix after.** Moving `measurementsFileURL`, `loadPersistedMeasurements()`,
and `persistMeasurements()` into the model is an independent model-layer concern that
does not affect the view-layer rewrite (the view layer calls the model regardless of
where inside the model the I/O lives).

---

### #15 — `exportMeasurement` absent from Python analyzer

**Layer:** Model.

**Verdict: Fix after.** The plan states model files do not change. Adding
`export_measurement()` to the analyzer is independent of the view rewrite.

---

### #16 — `delete_all_measurements` extra in Python

**Layer:** Model.

**Verdict: Fix after.** Model-layer only; no view-layer interaction.

---

### #17 — `set_measurement_complete` extra in Python

**Layer:** Model.

**Verdict: Fix after.** Model-layer only; no view-layer interaction.

---

## Sequencing Summary

### Fix before the SWIFTUI_COMPAT view-layer rewrite begins

These items create broken or doubled work if left until the rewrite:

| # | Divergence | Why it must precede |
|---|---|---|
| 4 | `saveMeasurement` parameter structure | New view action files call `analyzer.save_measurement()` — must match Swift signature |
| 5 | `loadMeasurement` in view vs model | Moving 360-line `_restore_measurement` to model avoids porting + immediately deleting it |
| 6 | `loaded*` @Published properties | Views that observe them cannot be written reactively without them |
| 7 | Material spectrum @Published absent | Views observing these properties cannot be written reactively without them |
| 9 | Settings persistence in view | `_connect_signals()` deletion will silently drop persistence |
| 10 | `cycleAnnotationVisibility` persistence | View handler that carries persistence will be deleted |
| 11 | `comparisonSpectra` shape | Views consuming comparison data need a stable contract |

### Fix during the SWIFTUI_COMPAT view-layer rewrite

These items live entirely in files being rewritten; fix at first-write time:

| # | Divergence | Where |
|---|---|---|
| 12 | PDF export TDS source | `tap_tone_analysis_view_export.py` initial write |
| 13 | `peakModeOverrides` not forwarded | `tap_tone_analysis_view_export.py` initial write |

### Fix after (model layer, independent of view rewrite)

These items are in model files the plan does not touch, or are independent of view
architecture:

| # | Divergence |
|---|---|
| 1 | `identified_modes` dict vs named tuple |
| 2 | Thread safety — AnnotationManagement |
| 3 | Thread safety — ModeOverrideManagement |
| 8 | `peakThreshold.didSet` missing side effect |
| 14 | Measurement file I/O location |
| 15 | `exportMeasurement` absent from analyzer |
| 16 | `delete_all_measurements` extra in Python |
| 17 | `set_measurement_complete` extra in Python |

---

## Implementation Checklist

### Phase 1 — Fix before (prerequisites for the view-layer rewrite)

- [ ] **#6** Add 28 `loaded*` Published properties to `tap_tone_analyzer.py`
- [ ] **#7** Add material spectrum Published properties to `tap_tone_analyzer.py` (`longitudinal_spectrum`, `cross_spectrum`, `longitudinal_peaks`, `cross_peaks`, `auto_selected_longitudinal_peak_id`, `selected_longitudinal_peak`, `user_selected_longitudinal_peak_id`, `auto_selected_cross_peak_id`, `selected_cross_peak`, `user_selected_cross_peak_id`, `flc_peaks`, `flc_spectrum`, `auto_selected_flc_peak_id`, `selected_flc_peak`, `user_selected_flc_peak_id`)
- [ ] **#11** Unify `_comparison_data` + `comparison_labels` into a single Published `comparison_spectra: list[tuple]` on the analyzer matching Swift's `[(magnitudes, frequencies, color, label)]` shape
- [ ] **#9** Move settings persistence (`peak_threshold`, `tap_detection_threshold`, `hysteresis_margin`) from view-layer signal handlers into model-layer Published property change callbacks
- [ ] **#10** Fix `cycle_annotation_visibility()` on the analyzer to call `TapDisplaySettings.set_annotation_visibility_mode()` directly (remove persistence from the view handler)
- [ ] **#5** Move `_restore_measurement()` (~360 lines) from the view layer into `load_measurement()` on `tap_tone_analyzer_measurement_management.py`
- [ ] **#4** Refactor `save_measurement()` to accept individual named parameters (matching Swift's 16+ parameter signature) and build `TapToneMeasurement` internally; delete view-layer `_collect_measurement()`

### Phase 2 — Fix during (at first-write time in the view-layer rewrite)

- [ ] **#12** In `tap_tone_analysis_view_export.py`: read `guitarBodyLength`, `guitarBodyWidth`, `plateStiffness`, `plateStiffnessPreset` from live `TapDisplaySettings` (not from measurement snapshot)
- [ ] **#13** In `tap_tone_analysis_view_export.py`: pass `peak_mode_overrides=analyzer.peak_mode_overrides` explicitly to `pdf_report_data_from_measurement()`

### Phase 3 — Fix after (model layer, independent of view rewrite)

- [ ] **#1** Change `identified_modes` from `list[dict]` to `list[tuple]` with named-tuple or dataclass access matching Swift's `[(peak:, mode:)]`
- [ ] **#2** Add `Thread.isMainThread` + main-thread dispatch guards to all mutating methods in `tap_tone_analyzer_annotation_management.py`
- [ ] **#3** Add main-thread dispatch guards to all three methods in `tap_tone_analyzer_mode_override_management.py`
- [ ] **#8** Add call to `recalculate_frozen_peaks_if_needed()` in the `peak_threshold` Published property change callback
- [ ] **#14** Move `measurementsFileURL`, `load_persisted_measurements()`, and `persist_measurements()` from the views module into `tap_tone_analyzer_measurement_management.py`
- [ ] **#15** Add `export_measurement()` to `tap_tone_analyzer_measurement_management.py`
- [ ] **#16** Evaluate whether `delete_all_measurements()` should be removed from the Python analyzer to match Swift
- [ ] **#17** Evaluate whether `set_measurement_complete()` should be removed from the Python analyzer to match Swift
