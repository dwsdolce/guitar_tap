# GuitarTap Migration Plan: Swift → Python

Comparison of `/Users/dws/src/GuitarTap/GuitarTap` (Swift/SwiftUI) and
`/Users/dws/src/guitar_tap` (Python/PyQt6/pyqtgraph). macOS only.

---

## Features Python MUST Preserve (not in Swift)

| Feature | Details |
|---|---|
| Frame-level spectrum averaging | Swift has tap-level averaging; Python's N-frame running average is a distinct and useful mode — keep both |
| Rich mode string taxonomy | `T(1,1)_1/2/3`, `T(2,1)`, `T(1,2)`, `T(2,2)`, `T(3,1)` — richer than Swift's 6 auto-classified modes |
| Per-row Show/Hide toggle | Peaks table Show column (on/off per row); Swift uses an All/Selected/None cycle — Python's is more granular |
| Upper/lower pitch boundary lines | Red `InfiniteLine` pairs on the spectrum at pitch boundaries; not present in Swift |
| Note axis labels | Top axis ticks at pitch boundary frequencies; not in Swift |
| CSV peak export | "Save Peaks" → Excel-compatible CSV; Swift has no CSV export |
| ThresholdSlider amplitude fill | Custom slider painting showing live amplitude in the groove |

---

## Migration Priorities

### Priority 1 — Foundation (everything else depends on these)

| ID | Feature | Implementation Notes |
|---|---|---|
| A1 | **Persistent settings** | Use `QSettings("Dolcesfogato", "GuitarTap")`. Cover: display freq range, dB range, analysis freq range, peak threshold, tap threshold, guitar type, measurement type, device name, window geometry. Create an `AppSettings` class with typed accessors. |
| D1 | **Interactive device selection** | Make the existing devices dialog rows selectable. On selection, tear down and re-create `sd.InputStream` with the chosen device index. Persist device name via `QSettings`. |
| G1 | **Non-blocking mic permission** | Replace `while not self.access_set: time.sleep(1)` in `mac_access.py` with a `QTimer` polling `self.access_set` at 100 ms. Fixes GUI thread hang. |
| A3 | **Tap detector with hysteresis** | New `TapDetector` class. Rising-edge detection with configurable `tapDetectionThreshold`, `hysteresisMargin`, `warmupPeriod` (0.5 s), `tapCooldown` (0.5 s). For guitar mode use FFT peak magnitude; for plate/brace use fast RMS level. Drives auto Hold Results. |
| A5 | **Spectrum freeze + New Tap button** | Add `isSpectrumFrozen` flag to `FftCanvas`. When frozen, display `saved_mag_y_db` regardless of new audio. Add "New Tap" button to clear frozen state and restart detection. |

### Priority 2 — Core Analysis

| ID | Feature | Implementation Notes |
|---|---|---|
| B2 | **Auto guitar mode classification** | Add `GuitarMode` enum (Air/Top/Back/Dipole/Ring/Upper/Unknown) and `GuitarType` enum (Classical/Flamenco/Acoustic) with per-type frequency band ranges. Classify each peak automatically; allow user override via the existing combo delegate. |
| A2 | **Measurement type selector** | Add `MeasurementType` enum (Guitar/Plate/Brace). Add a combo box or radio group to the controls panel. Gate different analysis pipelines behind this setting. |
| B1 | **Q factor** | In `freq_anal.py`: after parabolic interpolation walk outward from peak bin until magnitude drops below `peak_mag − 3 dB` on each side; `Q = freq / (upper_hz − lower_hz)`. Add Q column to peaks table and model. |
| B3 | **Ring-out decay time** | Track fast RMS (at audio callback rate) after each confirmed tap. Record time from tap peak to first crossing of `peak_level − decayThreshold` (15 dB default). Add quality label (Very Short/Short/Moderate/Good/Excellent) per guitar type. |
| A4 | **Tap-level multi-tap averaging** | Add `numberOfTaps` setting (1–N). On each confirmed tap, capture current spectrum and accumulate. After N taps, average and freeze. Distinct from the existing frame-level averaging — keep both. |

### Priority 3 — Calibration & Device Quality

| ID | Feature | Implementation Notes |
|---|---|---|
| C1 | **Mic calibration import** | Add `MicrophoneCalibration` dataclass. Parse UMIK-1/REW `.cal` format (skip `"` and `*` header lines; split freq/correction pairs). Pre-interpolate corrections to FFT bin frequencies using `numpy.interp`. Apply as `mag_db += calibration_corrections` before peak detection. Add import button (use `QFileDialog`). Persist path via `QSettings`. |
| D2 | **Hot-plug detection** | Poll `sd.query_devices()` on a 2 s `QTimer`. Compare against cached list. Refresh device combo box on change. |
| D3 | **Restore device on launch** | Load device name from `QSettings` and re-select it automatically at startup. |
| C2 | **Per-device calibration mapping** | Store a `QSettings` dict mapping device name → calibration file path. Auto-load calibration when device changes. |

### Priority 4 — Visualization Enhancements

| ID | Feature | Implementation Notes |
|---|---|---|
| E1 | **Mode band overlays** | Add `pg.LinearRegionItem` coloured regions for each guitar mode's frequency range. Toggle visibility based on measurement type and guitar type. Update ranges when guitar type changes. |
| E2 | **Tap detection threshold line** | Add a second horizontal `pg.InfiniteLine` for `tapDetectionThreshold`. The existing threshold slider controls peak detection; add a separate control (slider or spin box) for the tap detection level. |
| E4 | **Auto-scale dB** | Compute `np.min(mag_y_db[mag_y_db > -99])` and call `setYRange(floor − 5, 0)` when auto-scale is enabled. Add a toggle button. |
| E3 | **Hover cursor readout** | Connect `scene().sigMouseMoved` on the `ViewBox`. Use `mapToView` to convert to data coords. Snap to nearest spectrum bin via `numpy.searchsorted`. Display freq + magnitude in a `pg.TextItem` overlay or status label. |

### Priority 5 — Persistence & Export

| ID | Feature | Implementation Notes |
|---|---|---|
| F1 | **Measurement save/load (JSON)** | Define a `PeakMeasurement` dataclass (timestamp, peaks with freq/mag/Q/note/cents/mode, display settings, decay time, notes, location). Serialize with `json.dumps`. Save to `~/Documents/GuitarTap/measurements/`. Provide a measurements list dialog (list, load, delete). |
| F2 | **Measurement import** | File picker (`QFileDialog`); restore peaks, settings, and annotation positions. |
| F3 | **PDF report** | Spectrum PNG (from pyqtgraph `ImageExporter`) + peaks table + metadata. Use `reportlab` or `matplotlib.backends.backend_pdf`. Single US Letter page. |

### Priority 6 — Material Analysis (large, complex)

| ID | Feature | Implementation Notes |
|---|---|---|
| B4 | **Plate/Brace pipeline** | Phase state machine (`notStarted → capturingL → waitingForC → capturingC → [waitingForFLC →] complete`). 200 ms pre-roll ring buffer. 400 ms gated FFT (Hann window, up to 32768 samples, zero-padded, via scipy). Material property calculations: Young's modulus (beam formula + Gore plate formula), shear modulus, speed of sound, specific modulus, radiation ratio, anisotropy ratios, wood quality rating, Gore target thickness (Gore Eq. 4.5-7). Add plate/brace dimension inputs (settings or dedicated dialog). |
| B5 | **HPS auto-peak selection** | Harmonic Product Spectrum in numpy: downsample spectrum by integer factors 2, 3, 4 and multiply; find global peak of the product. Used to auto-select dominant fundamental from plate/brace gated spectra. |
| B6 | **Tap tone ratio** | Compute and display guitar mode tap tone ratio in results panel. |

### Priority 7 — Polish

| ID | Feature | Implementation Notes |
|---|---|---|
| G2 | **Improved mic-denied dialog** | Update dialog text to "System Settings > Privacy & Security > Microphone". Add a button that runs `subprocess.run(['open', 'x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Microphone'])`. |
| H1 | **Help window** | `QDialog` or secondary `QMainWindow` with `QTextBrowser` displaying HTML help content. Open via Cmd+? using a `QMenuBar` action. |
| G3 | **Debug log redirection** | Redirect `stdout`/`stderr` to `~/Library/Logs/GuitarTap-debug.log` when not running under a debugger. |

---

## Parity Check: Features in Both (verify these match)

| Feature | Python status | Swift status | Notes |
|---|---|---|---|
| Parabolic peak interpolation | `freq_anal.peak_interp` | `TapToneAnalyzer+PeakAnalysis` | Identical algorithm |
| Pitch (note + cents) | `pitch.py` Pitch class | `Models/Pitch.swift` | Direct port; both use A4=440 |
| FFT size | 65536 | 65536 (default) | Same |
| Sample rate | 48000 Hz | 48000 Hz | Same |
| Window (live path) | Boxcar/rectangular | Rectangular | Equivalent |
| dB scale | `20 * log10(abs_fft)` | `vDSP_vdbcon` (20 log10) | Equivalent |
| Peak scatter display | `pg.ScatterPlotItem` | `PointMark` in Swift Charts | Conceptually equivalent |
| Selected peak highlight | Red scatter point | Vertical rule + readout | Python is more visual |
| Annotation drag | `DraggableTextItem` + `itemChange` | `CGPoint` offset dict | Both draggable; different mechanism |
| Image export | `pg.exporters.ImageExporter` | `ImageRenderer` | Both present |
| macOS mic permission | PyObjC AVFoundation (buggy — see G1) | Native AVCaptureDevice (robust) | Python needs fix |

---

## Key Files

| File | Role in Migration |
|---|---|
| `guitar_tap.py` | Entry point: add settings persistence, measurement type selector, device plumbing, New Tap button |
| `fft_canvas.py` | Core: tap detector, spectrum freeze, calibration apply, mode classification calls, Q-factor calls, band overlays |
| `freq_anal.py` | Signal processing: Q-factor calc, HPS function, gated FFT (new) |
| `peaks_model.py` | Data model: add Q column, auto-mode column, decay time column |
| `peaks_controls.py` | Controls panel: measurement type picker, guitar type, tap threshold, N-tap spinner, New Tap/Cancel buttons, device combo |
| `mac_access.py` | Fix blocking permission check (G1) |
| `fft_annotations.py` | Mostly done; may need mode-band colour coordination |
