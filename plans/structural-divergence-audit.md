# Structural Divergence Remediation Plan

## Scope
Audit all uncommitted Swift changes (9 files) and verify each change is present in the
corresponding Python file with the same architecture, ownership layer, and structure.

---

## Swift → Python File Mapping

| Swift File | Python File |
|-----------|-------------|
| `RealtimeFFTAnalyzer.swift` | `realtime_fft_analyzer.py` |
| `RealtimeFFTAnalyzer+EngineControl.swift` | `realtime_fft_analyzer_engine_control.py` |
| `TapToneAnalyzer+Control.swift` | `tap_tone_analyzer_control.py` |
| `TapToneAnalysisView+Actions.swift` | `tap_tone_analysis_view.py` (actions section) |
| `TapToneAnalysisView+Controls.swift` | `tap_tone_analysis_view.py` (controls section) |
| `TapToneAnalysisView+Layouts.swift` | `tap_tone_analysis_view.py` (layouts section) |
| `TapToneAnalysisView+SpectrumViews.swift` | `fft_canvas.py` |
| `TapToneAnalysisView.swift` | `tap_tone_analysis_view.py` |
| `GuitarTapApp.swift` | `tap_tone_analysis_view.py` (menu setup) |

---

## Per-Change Audit

### 1. `RealtimeFFTAnalyzer.swift` — new properties
**Swift adds:** `playerNode`, `isPlayingFile`, `playingFileName` to the class body.
**Python:** `is_playing_file`, `playing_file_name`, `_file_playback_thread`, `_on_playback_finished` in `__init__` of `realtime_fft_analyzer.py`.
**Verdict: CORRECT.** (`playerNode` has no Python equivalent — PortAudio uses a thread, not a node.)

---

### 2. `RealtimeFFTAnalyzer+EngineControl.swift` — new method `startFromFile`
**Swift adds:** `startFromFile(_ url:, completion:)` to `RealtimeFFTAnalyzer+EngineControl.swift`.
**Python:** `start_from_file(path)` is in `realtime_fft_analyzer.py` — **NOT** in `realtime_fft_analyzer_engine_control.py`.
**Verdict: WRONG FILE.** This is the one structural defect. `realtime_fft_analyzer_engine_control.py` exists and mirrors `+EngineControl.swift` but contains only documentation prose. The method must move there.

---

### 3. `RealtimeFFTAnalyzer+EngineControl.swift` — modified `stop()`
**Swift adds:** Player node cleanup + `isPlayingFile = false` + `playingFileName = nil` to `stop()` in `+EngineControl.swift`.
**Python:** `stop()` (along with `start()`, `new_frame()`, `get_frames()`, `close()`) all live in `realtime_fft_analyzer.py` — **NOT** in `realtime_fft_analyzer_engine_control.py`.
**Verdict: WRONG FILE.** `stop()`, `start()`, `new_frame()`, `get_frames()`, and `close()` all belong in `realtime_fft_analyzer_engine_control.py` as part of `RealtimeFFTAnalyzerEngineControlMixin`. This is the same structural gap as #2 — the engine-control file exists but contains only documentation prose with no executable code. All of these methods, including `start_from_file`, must move there.

---

### 4. `TapToneAnalyzer+Control.swift` — `startTapSequence(skipWarmup:)`
**Swift adds:** `skipWarmup: Bool = false` parameter, sets `analyzerStartTime` in the past when true.
**Python:** `start_tap_sequence(skip_warmup: bool = False)` in `tap_tone_analyzer_control.py` with identical logic.
**Verdict: CORRECT** — right file, right name, right structure.

---

### 5. `TapToneAnalysisView+Actions.swift` — new method `openAudioFile(_:)`
**Swift adds:** `openAudioFile(_ url: URL)` to `TapToneAnalysisView+Actions.swift`. Sequences: security-scoped access → `fft.startFromFile(url, completion:)` → `tapToneAnalyzer.startTapSequence(skipWarmup: true)`.
**Python:** `_open_audio_file()` in `tap_tone_analysis_view.py`. Sequences: `QFileDialog` → `analyzer.start_from_file(path, on_finished:)` → `analyzer.start_tap_sequence(skip_warmup=True)`.
**Verdict: CORRECT** — right file, same layer ownership (view sequences across model layers).

---

### 6. `TapToneAnalysisView+Controls.swift` — `macosPlayFileButton()` + iPad button
**Swift adds:** `macosPlayFileButton(iconOnly:)` ViewBuilder + Play File button in `ipadHeaderButtons`.
**Python:** `_play_file_btn = QPushButton(...)` created inline in toolbar setup.
**Verdict: ACCEPTABLE DIVERGENCE.** Qt has no equivalent of the "icon-only vs labeled" rendering duality that drives the ViewBuilder helper. A single `QPushButton` is the correct Qt equivalent.

---

### 7. `TapToneAnalysisView+Layouts.swift` — Play File button in toolbar groups
**Swift adds:** Play File button to 4 separate `ToolbarItemGroup` placements (iPad horizontal, phone landscape, iPhone compact, iPad standard).
**Python:** Single `_play_file_btn` added once to the single flat toolbar.
**Verdict: ACCEPTABLE DIVERGENCE.** Python has one toolbar; Swift needs 4 placements for its per-idiom layout system.

---

### 8. `TapToneAnalysisView+SpectrumViews.swift` — `chartTitle`
**Swift changes:** `chartTitle: String` from `tap.loadedMeasurementName ?? "New"` to `fft.playingFileName ?? tap.loadedMeasurementName ?? "New"`.
**Python counterpart file:** `fft_canvas.py` (mirrors `+SpectrumViews.swift`).
**Python:** `chart_title` property in `fft_canvas.py` returns `playing or loaded or "New"`.
**Verdict: CORRECT** — right file, right name, same logic.

---

### 9. `TapToneAnalysisView.swift` — `showingFilePicker` + `.fileImporter`
**Swift adds:** `@State var showingFilePicker = false` + `.fileImporter(...)` modifier.
**Python:** `QFileDialog.getOpenFileName(...)` called inline in `_open_audio_file()`. No state variable needed.
**Verdict: ACCEPTABLE DIVERGENCE.** Qt modal dialogs are synchronous/blocking; no "is showing" state variable is needed or appropriate.

---

### 10. `TapToneAnalysisView.swift` — `bindMenuActions()`
**Swift adds:** `menuActions.openAudioFile = { showingFilePicker = true }` to `bindMenuActions()`.
**Python:** `play_file_action.triggered.connect(self._open_audio_file)` wired in menu setup.
**Verdict: CORRECT** — same file, equivalent architecture.

---

### 11. `GuitarTapApp.swift` — `MenuActions.openAudioFile` + `AppCommands`
**Swift adds:** `var openAudioFile: (() -> Void)?` on `MenuActions`; `Button("Play Audio File…")` with `⌘⌥O` in `AppCommands`.
**Python:** `QAction("Play Audio File…")` with `Ctrl+Alt+O` shortcut added to File menu in `tap_tone_analysis_view.py`.
**Verdict: CORRECT** — Qt menus are imperative and live on the main window; no separate `MenuActions` class is needed.

---

### 12. `tap_tone_analyzer.py` — `playingFileNameChanged` signal (Python-only)
**Swift:** No equivalent signal on `TapToneAnalyzer`. Swift uses `@Published var playingFileName` on `RealtimeFFTAnalyzer` observed directly by the view.
**Python:** `playingFileNameChanged` on `TapToneAnalyzer` (and forwarded through `FftCanvas`) is an **architecturally necessary bridge** — `Microphone` (`RealtimeFFTAnalyzer`) is not a `QObject` and cannot carry Qt signals.
**Verdict: NECESSARY BRIDGE** — not a defect.

---

## Result: Two Fixes Required

| Change | Verdict |
|--------|---------|
| `RealtimeFFTAnalyzer.swift` — properties | CORRECT |
| **`+EngineControl.swift` — `startFromFile`** | **WRONG FILE → fix** |
| **`+EngineControl.swift` — `stop()` (+ `start()`, `new_frame()`, `get_frames()`, `close()`)** | **WRONG FILE → fix** |
| `+Control.swift` — `startTapSequence(skipWarmup:)` | CORRECT |
| `+Actions.swift` — `openAudioFile` | CORRECT |
| `+Controls.swift` — Play File button | Acceptable divergence |
| `+Layouts.swift` — Play File in toolbars | Acceptable divergence |
| `+SpectrumViews.swift` — `chartTitle` | CORRECT |
| `TapToneAnalysisView.swift` — file picker state | Acceptable divergence |
| `TapToneAnalysisView.swift` — `bindMenuActions` | CORRECT |
| `GuitarTapApp.swift` — menu command | CORRECT |
| `tap_tone_analyzer.py` — bridge signal | Necessary |

---

## The Fix: Populate `realtime_fft_analyzer_engine_control.py` with `RealtimeFFTAnalyzerEngineControlMixin`

### Pattern
`realtime_fft_analyzer_device_management.py` is the established pattern:
- Defines `RealtimeFFTAnalyzerDeviceManagementMixin` with all device methods
- `RealtimeFFTAnalyzer` inherits from it
- `realtime_fft_analyzer.py` imports it and lists it as a base class

`realtime_fft_analyzer_engine_control.py` must follow the exact same pattern.

### Methods to move from `realtime_fft_analyzer.py` → mixin in `realtime_fft_analyzer_engine_control.py`

| Method | Swift counterpart |
|--------|------------------|
| `new_frame()` | AVAudioInputNode tap callback (`processAudioBuffer`) |
| `get_frames()` | `rawSampleHandler` / `inputBuffer` access |
| `start()` | `start()` in `+EngineControl.swift` |
| `stop()` | `stop()` in `+EngineControl.swift` |
| `start_from_file()` + inner `_playback_worker` | `startFromFile(_:completion:)` in `+EngineControl.swift` |
| `close()` | `deinit` / `close()` in `+EngineControl.swift` |

### Step 1 — `realtime_fft_analyzer_engine_control.py`
Replace the documentation-only prose with a real module:
- Retain the existing prose as the module docstring (update to note methods now live here)
- Define `class RealtimeFFTAnalyzerEngineControlMixin` containing all six methods above, moved verbatim from `realtime_fft_analyzer.py`

### Step 2 — `realtime_fft_analyzer.py`
- Add import: `from .realtime_fft_analyzer_engine_control import RealtimeFFTAnalyzerEngineControlMixin`
- Add `RealtimeFFTAnalyzerEngineControlMixin` to `RealtimeFFTAnalyzer`'s base class list (alongside `RealtimeFFTAnalyzerDeviceManagementMixin`)
- Remove all six moved methods
- Keep all `__init__` properties in `realtime_fft_analyzer.py` — stored properties declared in `__init__` mirror Swift where properties are declared in the main class file and methods live in the extension file
- Update the module-level docstring mapping table

### Files changed
| File | Change |
|------|--------|
| `realtime_fft_analyzer_engine_control.py` | Replace docs-only with `RealtimeFFTAnalyzerEngineControlMixin` containing `new_frame`, `get_frames`, `start`, `stop`, `start_from_file`, `close` |
| `realtime_fft_analyzer.py` | Remove those six methods, add mixin import + base class, update docstring |

### No functional changes
Pure structural move. All logic, imports, and runtime behaviour are identical.
