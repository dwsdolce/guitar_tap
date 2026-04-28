# Multi-Tap PDF — Swift/Python Divergence Audit

This document records all 12 structural and algorithmic divergences identified during the
review of the multi-tap PDF export implementation.
Status: **Fixed** = corrected during this session. **Open** = remains as-is (with rationale).

---

## Divergence 1 — Chart title fallback in `render_spectrum_image_for_multi_tap`
**Status: Fixed**

| | Detail |
|---|---|
| Swift | `"Tap Comparison — Multi-Tap"` as the fallback title in `renderSpectrumImageForMultiTap` |
| Python (before fix) | `"Tap Comparison"` (missing the `"— Multi-Tap"` suffix) |
| Fix | Changed Python fallback to `"Tap Comparison — Multi-Tap"` |

---

## Divergence 2 — Live comparison chart title missing `loadedMeasurementName` fallback
**Status: Fixed**

| | Detail |
|---|---|
| Swift | Title built as `loc ?? tap.loadedMeasurementName ?? "Multi-Tap"` |
| Python (before fix) | Used only `loc or "Multi-Tap"`, skipping the `loaded_measurement_name` intermediate fallback |
| Fix | Changed to `loc or analyzer.loaded_measurement_name or "Multi-Tap"` |

---

## Divergence 3 — `entries=[]` passed to `ComparisonPDFReportData` (both live and saved paths)
**Status: Fixed**

| | Detail |
|---|---|
| Swift | Passes `entries: cmpEntries` (the full list of `ComparisonEntry` objects) |
| Python (before fix) | Hardcoded `entries=[]` in both live `_on_export_multi_tap_pdf` and saved `_export_multi_tap_pdf`, suppressing the frequency-range metadata row on page 2 |
| Fix | Changed to `entries=list(tap_entries)` in both paths |

---

## Divergence 4 — `plate_properties` hardcoded to `None` vs Swift's computed `plateProps`/`braceProps`
**Status: Fixed**

| | Detail |
|---|---|
| Swift | Derives `plateProps` and `braceProps` from live `TapDisplaySettings` dimensions + effective peak IDs, conditioned on `measurementType == .plate/.brace` |
| Python (before fix) | Hardcoded `plate_properties=None, brace_properties=None` in `_on_export_multi_tap_pdf`, unconditionally |
| Fix | Added the same `if mt == PLATE / elif mt == BRACE` derivation block (copied from the single-tap live path) into `_on_export_multi_tap_pdf`, before the `PDFReportData` construction. `plate_properties=plate_props, brace_properties=brace_props` now passed instead of `None`. |

---

## Divergence 5 — `guitar_type_str` source expression
**Status: Open — not fixable (language constraint)**

| | Detail |
|---|---|
| Swift | `TapDisplaySettings.guitarType` — a `static var` computed property; accessed without parentheses |
| Python | `TDS.guitar_type()` — a `@classmethod`; must be called with `()` |
| Note | Python has no class-level computed property equivalent to Swift's `static var`. A `@classmethod` called with `()` is the canonical Python idiom for the same pattern. The getter logic (check `measurementType` first, fall back to stored key, default to `.generic`) is identical in both languages. This divergence cannot be eliminated without changing the Python language. |

---

## Divergence 6 — `materialSpectra` passed in Swift's averaged spectrum render but not in Python
**Status: Fixed**

| | Detail |
|---|---|
| Swift | `createAveragedSpectrumView()` passes `materialSpectra: materialSpectra` to the export chart helper |
| Python (before fix) | `_on_export_multi_tap_pdf` omitted `material_spectra` from the `make_exportable_spectrum_view` call entirely |
| Fix | Added the same `_material_spectra` build block (from the single-tap `_on_export_pdf` path) into `_on_export_multi_tap_pdf`, guarded by `if not is_guitar`. Changed the render guard from `if freqs:` to `if freqs or _material_spectra:` and added `material_spectra=_material_spectra` to the call — matching the single-tap path exactly. |

---

## Divergence 7 — `measurement_type_str` / `measurementType` in `renderSpectrumImageForMultiTap`
**Status: Fixed**

| | Detail |
|---|---|
| Swift | Passes `measurementType: .classical` explicitly to `makeExportableSpectrumView` in both the saved (`renderSpectrumImageForMultiTap`) and live (`createMultiTapComparisonSpectrumView`) paths |
| Python (before fix) | Omitted `measurement_type_str` entirely (defaulting to `None`) in both `render_spectrum_image_for_multi_tap` and the comparison PNG call in `_on_export_multi_tap_pdf` |
| Fix | Added `measurement_type_str="classical"` to both call sites, matching Swift exactly. |

---

## Divergence 8 — Color representation: Swift `Color` objects vs Python `(r, g, b)` tuples
**Status: Open — language difference**

| | Detail |
|---|---|
| Swift | Palette entries and entry colors are typed as `Color` (SwiftUI / UIKit `Color` values) |
| Python | Palette entries and entry colors are `(r, g, b)` integer tuples (e.g. `(0, 122, 255)`) |
| Note | This is a fundamental difference in the type systems of the two languages/frameworks. The numeric color values are identical; only the container type differs. No algorithmic divergence. |

---

## Divergence 9 — `guitar_type_str` passed in averaged PNG render (Python only)
**Status: Fixed**

| | Detail |
|---|---|
| Swift | `makeExportableSpectrumView` receives `measurementType: MeasurementType`. Swift's `MeasurementType` carries both `is_guitar` and `guitarType` as computed properties, so a single parameter implicitly provides both. |
| Python (before fix) | `make_exportable_spectrum_view` had two separate parameters — `measurement_type_str` (for `is_guitar`) and `guitar_type_str` (for mode classification) — requiring callers to pass both explicitly. |
| Fix | `ExportableSpectrumChart.__init__` now derives `guitar_type_str` from `measurement_type_str` when `guitar_type_str` is not explicitly provided, mirroring Swift's `MeasurementType.guitarType` computed property. Callers pass only `measurement_type_str=mt.value`; the chart derives the guitar type internally. The redundant `guitar_type_str=gt_str` argument was removed from the multi-tap averaged PNG call. Additionally, Python had `measurement_type_str=mt.value if not is_guitar else None` — suppressing the value for guitar measurements — which was corrected to `measurement_type_str=mt.value` unconditionally, matching Swift which always passes `TapDisplaySettings.measurementType` without any guitar/non-guitar conditional. |

---

## Divergence 10 — `ComparisonEntry` model objects (Swift) vs plain `mode_frequencies` tuples (Python)
**Status: Fixed**

| | Detail |
|---|---|
| Swift | Builds a list of `ComparisonEntry` structs (`colorComponents`, `snapshot`, `peaks`, `guitarType`) and passes them to `ComparisonPDFReportData(entries: cmpEntries)` |
| Python (before fix) | Constructed `mode_frequencies` directly as a list of `(label, air, top, back, color)` tuples inline in `_export_multi_tap_pdf` / `_on_export_multi_tap_pdf`, without an intermediate model object |
| Fix | Both `_on_export_multi_tap_pdf` (live) and `_export_multi_tap_pdf` (saved) now follow the same two-step pattern as Swift: Step 1 builds `cmp_entries: list[ComparisonEntry]` (colors stored as RGBA 0.0–1.0 in `color_components`, matching Swift's `colorComponents: [Double]`); Step 2 maps `cmp_entries` → `mode_frequencies` tuples (converting colors back to `(r,g,b)` 0–255 for the PDF renderer, which is the Python equivalent of Swift's `Color(red:green:blue:opacity:)` reconstruction). `cmp_entries` is also passed as `entries=cmp_entries` to `ComparisonPDFReportData`, replacing the previous `list(tap_entries)` / `list(m.tap_entries)`. |

---

## Divergence 11 — Palette definition: shared constant (Swift) vs inline re-definition (Python)
**Status: Fixed**

| | Detail |
|---|---|
| Swift | References `TapToneAnalyzer.comparisonPalette` — a single shared array defined once on the analyzer |
| Python (before fix) | Re-defined the palette inline as a literal in each of the three export functions (`_on_export_multi_tap_pdf`, `_export_multi_tap_pdf`, `render_spectrum_image_for_multi_tap`) |
| Fix | **Palette:** Swift `private static let multiTapPalette` on `TapToneAnalyzer`; Python `_MULTI_TAP_PALETTE` on `TapToneAnalyzerMeasurementManagementMixin`, re-exported as `MULTI_TAP_PALETTE` from `tap_analysis_results_view.py`. **Averaged color:** Swift `static let multiTapAvgColor: Color` on `TapToneAnalyzer`; Python `_MULTI_TAP_AVG_COLOR: tuple[int, int, int] = (255, 217, 0)` on the mixin, re-exported as `MULTI_TAP_AVG_COLOR`. Both constants are defined alongside each other on their respective analyzer types. The only difference is the `_MULTI_TAP_` scoping prefix in Python (unavoidable — Python class attributes share a flat namespace). |

---

## Divergence 12 — Optional/nil handling: Swift `guard let` vs Python truthy check
**Status: Open — language difference**

| | Detail |
|---|---|
| Swift | Uses `guard let tapEntries = measurement.tapEntries, !tapEntries.isEmpty else { return }` — explicit optional binding that distinguishes `nil` from an empty array |
| Python | Uses `if not tap_entries: return None` — a truthy check that treats `None` and `[]` identically |
| Note | In practice, `tap_entries` in Python is never `None` (the model initialises it to `[]`), so the truthy check is correct. This is a language-idiomatic difference rather than a semantic divergence, but it does mean the Python code would silently accept a `None` where Swift would catch a programmer error at the type level. |

---

## Summary Table

| # | Description | Status |
|---|---|---|
| 1 | Chart title fallback (`"Tap Comparison"` vs `"Tap Comparison — Multi-Tap"`) | Fixed |
| 2 | Live comparison chart title missing `loaded_measurement_name` fallback | Fixed |
| 3 | `entries=[]` passed to `ComparisonPDFReportData` | Fixed |
| 4 | `plate_properties=None` vs computed `plateProps`/`braceProps` | Fixed |
| 5 | `TDS.guitar_type()` method call vs `TapDisplaySettings.guitarType` property | Open — not fixable (language constraint) |
| 6 | `materialSpectra` not passed in averaged render | Fixed |
| 7 | `measurement_type_str=None` vs `.classical` | Fixed |
| 8 | Python `(r,g,b)` tuples vs Swift `Color` objects | Open — language difference |
| 9 | `guitar_type_str` injected explicitly in Python vs read from environment in Swift | Fixed |
| 10 | Inline `mode_frequencies` tuples vs `ComparisonEntry` model objects | Fixed |
| 11 | Palette defined inline per-function vs shared `comparisonPalette` constant | Fixed |
| 12 | Truthy check `if not tap_entries` vs `guard let` optional binding | Open — language difference |
