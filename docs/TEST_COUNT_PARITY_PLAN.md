# Plan: Test Count Parity — Swift ↔ Python

**Goal:** Bring Swift and Python test counts to parity on all paired files.
Excluded from parity: `SpectrumViewGestureTests.swift` (platform-specific, no Python
equivalent) and `TestRunner.swift` (harness, not a logical test file).

**Principle:** Remove Python tests that duplicate already-covered scenarios; add Swift
tests for genuine coverage gaps.

---

## Current Counts

| File pair | Swift | Python | Delta |
|---|---|---|---|
| AnnotationStateTests / test_annotation_state | 32 | 30 | -2 (accepted — icon-name tests are SF Symbol specific) |
| GuitarModeTests / test_guitar_mode | 35 | 35 | 0 |
| FrozenPeakRecalculationTests / test_frozen_peak_recalculation | 18 | 32 | **+14 Python** |
| MeasurementCodableTests / test_measurement_codable | 20 | 39 | **+19 Python** |
| PlatePropertiesTests + BracePropertiesTests / test_material_properties | 40 | 48 | **+8 Python** |
| DSPTests / test_dsp | 10 | 9 | **−1 Python** |
| PeakFindingTests / test_peak_finding | 12 | 13 | **+1 Python** |
| PitchTests / test_pitch | 22 | 21 | **−1 Python** |
| Others (6 pairs) | equal | equal | 0 |

---

## Gap 1 — FrozenPeakRecalculation (+14 Python)

**Root cause:** `TestAnalyzerRemapping` (12 tests) re-runs PR1–PR7 scenarios at the
full-analyzer level. The granular classes (`TestLoadingGuard`, `TestThresholdFilter`,
`TestOffsetRemap`, `TestOverrideRemap`, `TestSelectionCarryForward`,
`TestEmptyPeaksGuard`) already cover the same scenarios. There is no Swift equivalent
of this class — it is a Python-only duplicate.

`TestLiveTapPath` (2 tests) is different: it tests `TapToneMeasurement.spectrum_snapshot`
storage directly and belongs in `MeasurementCodableTests`, not the recalculation file.

**Actions:**
1. Remove `TestAnalyzerRemapping` (12 tests) from `test_frozen_peak_recalculation.py`
2. Move `TestLiveTapPath` (2 tests) from `test_frozen_peak_recalculation.py` into
   `test_measurement_codable.py`
3. Add 2 Swift tests to `MeasurementCodableTests.swift` mirroring `TestLiveTapPath`:
   - `spectrumSnapshot_newMeasurement_isNil`
   - `spectrumSnapshot_withSnapshot_stored`

Result: FrozenPeakRecalculation → 18 ↔ 18 ✓

---

## Gap 2 — MeasurementCodable (+19 Python, +2 from Gap 1 move = 21 total)

**Root cause:** Five classes testing individual JSON fields on `TapToneMeasurement`
were recently moved here from `test_annotation_state.py`. Swift only has minimal
coverage of these fields (one round-trip test, one ratio test).

Swift properties confirmed present: `youngsModulusLongGPa`, `youngsModulusCrossGPa`
(both on `PlateProperties` and `BraceProperties`).

**Action:** Add 6 new Swift suites to `MeasurementCodableTests.swift`:

| New Swift suite | Tests | Mirrors Python class |
|---|---|---|
| `AnnotationOffsetsCodable` | 1 (D1: multi-peak) | `TestAnnotationOffsets` (already have D2 equivalent) |
| `PeakSelectionOnMeasurement` | 3 (D3, D3b, nil→all) | `TestPeakSelection` |
| `AnnotationVisibilityModeCodable` | 4 (D4, D5, D6, CI5) | `TestAnnotationVisibilityMode` |
| `ModeOverridesCodable` | 4 (D7, D8, empty, auto-type) | `TestModeOverrides` |
| `PeakSelectionTrackingCodable` | 6 (PS1–PS6) | `TestPeakSelectionTracking` |
| `SpectrumSnapshotOnMeasurement` | 2 (nil, stored) | `TestLiveTapPath` (moved from FrozenPeak) |

Total new from 6 suites: **20 Swift tests**

Additionally, during verification `GetTestList` revealed `MeasurementCodableTests.swift` had 40 tests
vs Python's 41. The gap was `emptyAnnotationOffsets_roundTrip` — Python's
`test_empty_annotation_offsets_round_trip` in `TestTapToneMeasurementCodable` had no Swift mirror.
One more test was added to the existing `TapToneMeasurementCodableTests` suite:
- `emptyAnnotationOffsets_roundTrip`

Total new: **21 Swift tests** → MeasurementCodable: Swift 20+1+20=41 ↔ Python 39+2=41 ✓

---

## Gap 3 — MaterialProperties (+8 Python)

**Root cause:** Python has `TestPlateQuality` (3 tests testing `quality_long` / `overall_quality`)
and formula-verification tests that have no Swift equivalents.

Swift properties confirmed: `spruceQualityLong`, `overallQuality` (on `PlateProperties`);
`youngsModulusLongGPa`, `youngsModulusCrossGPa` on both `PlateProperties` and
`BraceProperties`; `speedOfSoundLong`.

**Actions:**

`PlatePropertiesTests.swift` — 6 new tests:
- Add to `YoungModulus` suite: `youngsModulusLong_gpaPropertyIsCorrect`, `youngsModulusCross_gpaPropertyIsCorrect`
- Add to `SpeedOfSound` suite: `speedOfSoundLong_equalsSquareRootOfEOverRho`
- New `@Suite("PlateQuality")`: `spruceQualityLong_excellent_forHighSpecificModulus`, `spruceQualityLong_returnsWoodQualityValue`, `overallQuality_usesWeightedNumericScore`

`BracePropertiesTests.swift` — 2 new tests:
- Add to `BraceYoungModulus` suite: `youngsModulusLong_gpaPropertyIsCorrect`
- Add to `BraceSpeedOfSound` suite: `speedOfSoundLong_equalsSquareRootOfEOverRho`

Result: MaterialProperties → 40+8=48 ↔ 48 ✓

---

## Gap 4 — DSP (−1 Python)

**Root cause:** Swift `ParabolicInterpolationTests` has an `F4b` test
(`edgeBinLastIndex_returnsRawValues`) that verifies `parabolicInterpolate` gracefully
handles a peak at the last array index. Python's F4 tests a different property (shift
bounded within ±0.5 bins) and has no last-index edge-case test.

**Action:** Add `test_F4b_last_bin_returns_raw_values` to `TestParabolicInterpolation`
in `test_dsp.py`.

Result: DSP → 10 ↔ 10 ✓

---

## Gap 5 — PeakFinding (+1 Python)

**Root cause:** Python has a `TestPeakInterpSanity` class (1 test:
`test_interpolated_frequency_close_to_injected`) that cross-checks `peak_interp` places
the result within 1 bin of the injected tone. There is no Swift equivalent in
`PeakFindingTests.swift`. The Swift `DSPTests` already tests interpolation accuracy
(F1–F6); this Python test duplicates that intent in the wrong file.

**Action:** Remove `TestPeakInterpSanity` (1 test) from `test_peak_finding.py`.

Result: PeakFinding → 12 ↔ 12 ✓

---

## Gap 6 — Pitch (−1 Python)

**Root cause:** Two asymmetries that net to −1:

- Swift has `eightCentsFlat_isInTune` in `TestInTune` (8 cents flat → still in tune at
  default 10-cent threshold). Python's `TestInTune` has no in-tune-when-flat case.
- Python has `test_freq0_matches_freq_formula` in `TestFreq0` — verifies `freq0(f)`
  equals `freq(note, octave)` for an arbitrary frequency. Swift has no equivalent because
  the Swift `Pitch` class does not expose a standalone `freq(note:octave:)` method in its
  public API. This is a legitimate Python-side formula-consistency test; removing it
  would lose real coverage.

**Action:** Add `test_eight_cents_flat_is_in_tune` to `TestInTune` in `test_pitch.py`.
(Keep `test_freq0_matches_freq_formula`; it covers a code path unique to Python.)

Result: Pitch → 22 ↔ 22 ✓

---

## Summary of All Changes

### Python (net −12)
| File | Change | Delta |
|---|---|---|
| `test_frozen_peak_recalculation.py` | Remove `TestAnalyzerRemapping` class | −12 |
| `test_frozen_peak_recalculation.py` | Move `TestLiveTapPath` out | −2 |
| `test_measurement_codable.py` | Receive `TestLiveTapPath` | +2 |
| `test_dsp.py` | Add `test_F4b_last_bin_returns_raw_values` | +1 |
| `test_peak_finding.py` | Remove `TestPeakInterpSanity` | −1 |
| `test_pitch.py` | Add `test_eight_cents_flat_is_in_tune` | +1 |

### Swift (+29)
| File | Change | Delta |
|---|---|---|
| `MeasurementCodableTests.swift` | 6 new suites (1+3+4+4+6+2 tests) + 1 in existing suite | +21 |
| `PlatePropertiesTests.swift` | 2 in YoungModulus, 1 in SpeedOfSound, 3 new PlateQuality | +6 |
| `BracePropertiesTests.swift` | 1 in BraceYoungModulus, 1 in BraceSpeedOfSound | +2 |

---

## Target State After Changes

| File pair | Swift | Python |
|---|---|---|
| FrozenPeakRecalculation | 18 | 18 |
| MeasurementCodable | 41 | 41 |
| PlateProperties+BraceProperties | 48 | 48 |
| DSPTests | 10 | 10 |
| PeakFindingTests | 12 | 12 |
| PitchTests | 22 | 22 |
| AnnotationState | 32 | 30 (accepted: 2 SF Symbol icon-name tests) |
| All others | unchanged | unchanged |

---

## Verification

1. **Python:** `cd /Users/dws/src/guitar_tap && .venv/bin/pytest tests/ -q` — must show **249/249** passing
   (260 − 12 removed + 1 DSP + 1 Pitch − 1 PeakFinding = 249)
2. **Swift:** `BuildProject` — must build cleanly with no errors, and `GetTestList` = **264** total
   (249 paired + 2 SF Symbol icon-name + 12 SpectrumViewGesture + 1 TestRunner = 264)

---

## Step Checklist

- [x] Remove `TestAnalyzerRemapping` from `test_frozen_peak_recalculation.py` (−12 tests)
- [x] Move `TestLiveTapPath` from `test_frozen_peak_recalculation.py` to `test_measurement_codable.py`
- [x] Add 21 Swift tests to `MeasurementCodableTests.swift` (6 new suites + 1 in existing `TapToneMeasurementCodableTests`)
- [x] Add 6 Swift tests to `PlatePropertiesTests.swift` (+2 YoungModulus, +1 SpeedOfSound, +3 new PlateQuality)
- [x] Add 2 Swift tests to `BracePropertiesTests.swift` (+1 BraceYoungModulus, +1 BraceSpeedOfSound)
- [x] Add `test_F4b_last_bin_returns_raw_values` to `test_dsp.py`
- [x] Remove `TestPeakInterpSanity` from `test_peak_finding.py`
- [x] Add `test_eight_cents_flat_is_in_tune` to `test_pitch.py`
- [x] Verify: Python 249/249 passing, Swift builds clean, `GetTestList` = 264 total (per-file parity achieved)
