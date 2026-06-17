# GuitarTap Beta Release Notes

---

## Version 1.0 · Build 373
### What's New Since Build 368

---

## New Features

### Linux AppImage Distribution

- GuitarTap now ships as an **AppImage** for Linux — a single self-contained executable that requires no system package installation. The AppImage bundles Python, Qt, and all dependencies; download, mark executable, and run.

### User Manual

- A comprehensive **User Manual** is now available, covering all three measurement modes (Guitar, Plate, Brace), the spectrum chart, saving and exporting measurements, a complete settings reference, a controls reference, and tips and troubleshooting. Eleven chapters plus appendices for keyboard shortcuts and file formats. The manual is published separately as HTML and PDF.

---

## Improvements

### Smaller macOS Bundle

- The macOS bundle is now considerably smaller (about 70 MB, down from previous builds). Download time and disk footprint are correspondingly reduced.

### Measurement Detail View

- The detail-pane buttons (Load into View, Export Measurement, Export PDF Report) have been removed. All these actions are still available — and were always available — via the popup menu on a measurement row. The detail pane is now strictly a read-only view of the measurement with a single **Close** button.
- The Edit popup-menu item has been renamed from "Edit…" to **Edit Name & Notes** so the action is explicit about what it edits.
- The "…" ellipsis suffix has been dropped from the Export Measurement / Export Spectrum / Export PDF Report popup-menu items so the wording matches the Swift build's menu.

### Date and Time in the Measurements List

- Each measurement row now shows both the **date and time** of capture rather than time only. The display respects the current locale.

---

## Bug Fixes

- Fixed a detection-state hang reproducible after capturing a gated measurement: loading a saved plate measurement, lowering the Threshold below the room's noise floor, then changing measurement type to Generic Guitar would cause a phantom tap to fire, leaving the analyzer stuck with **Pause** enabled and **New Tap** disabled — unrecoverable without restarting the app. The fix is mirrored in the Swift build.

---

---

## Version 1.0 · Build 368
### What's New Since Build 263

---

## New Features

### Plate and Brace Measurements

- The Plate and Brace measurement modes have been overhauled and now produce correct, repeatable results on both Python and the iOS/macOS Swift app for the same captured audio.
- Each tap phase (Longitudinal, Cross-grain, FLC for plates; Longitudinal for braces) now freezes the spectrum on completion so the result can be reviewed before accepting or redoing.
- FFT processing for plate/brace was aligned bit-for-bit with the Swift implementation — frequency and magnitude readouts now match between platforms for the same input.
- Cross-grain (fC) peak selection now picks the strongest peak rather than the lowest, which avoids re-selecting the longitudinal peak when the two frequency ranges overlap.
- An optional preference makes fC always greater than fL, useful for plates where the two modes are close.
- Plate PDF report generation has been completed: results from all phases are rendered with annotations matching the live view.

### Generic Guitar Type

- A new **Generic Guitar** measurement type joins Classical, Flamenco, and Acoustic. Use it for guitars that do not fit cleanly into one of the specific body types, or for initial exploration. Generic uses broad mode-frequency ranges that cover every guitar style.

### Multi-Tap Comparison for Guitar Measurements

- When you capture a multi-tap guitar measurement, the Results panel now provides a comparison view showing each individual tap alongside the averaged result. You can switch between the averaged spectrum and per-tap spectra to identify variation across taps.
- PDF export for multi-tap guitar measurements now renders as a two-page report — the averaged spectrum on page 1 and the per-tap comparison on page 2.

### Session Recording for Replay

- Each measurement now writes a single WAV file containing the full recorded session, so the actual audio behind a result can be replayed and re-analysed later.

### Re-Analyze Button on Loaded Measurements

- Loaded measurements now have a **Re-analyze** button that re-runs the peak-detection algorithm against the stored spectrum using the current settings. Useful for trying a different peak-min threshold or guitar type on a previously-captured measurement without re-tapping.

### Magnitude Edge-Detection Trigger

- The tap-trigger has been changed from "FFT peak above threshold" to **magnitude (RMS) edge detection**. This is faster, more responsive, and far less prone to false triggers from spectral leakage. The Threshold slider continues to control the trigger level in all modes (guitar, plate, brace).

### Microphone Name on the Results Panel

- The Analysis Results panel now displays the name of the microphone used for the capture. Saved measurements record the microphone name so it appears on subsequent loads and on the PDF report.

### Pause / Resume in Guitar Mode

- Pause was previously only available in plate/brace mode. It now works in guitar mode too, letting you freeze the live display, adjust Threshold or Peak Min, and resume without an accidental measurement firing.

### Crash Visibility on Windows

- If GuitarTap fails to start on Windows (where there is no console window), a dialog now appears with the error message and the location of the crash log so the failure is no longer silent.

---

## Improvements

### Hysteresis and Max Peaks — Settings Removed

- The Hysteresis and Maximum Peaks settings have been retired. Hysteresis is now hardcoded to a sensible value (3 dB), and Maximum Peaks is "all" — every peak above the Peak-Min threshold is returned. This simplifies the settings panel and removes two knobs that needed tuning to get good results.

### Threshold Naming and Coverage

- The "Peak Threshold" setting has been renamed to **Peak Min Threshold** to make clear that it gates the minimum magnitude required for a peak to be reported. The Tap Detection Threshold remains a separate setting that controls the rising-edge tap trigger and is now active in every measurement mode (guitar, plate, and brace).
- The Peak Min slider is automatically disabled when a measurement comparison is being displayed, since the threshold cannot meaningfully apply across multiple saved results.

### Audio File Playback

- Erratic or inconsistent results when analysing a WAV file have been fixed — playback timing and FFT synchronisation are now reliable.
- The chart title correctly shows the played filename during and after playback, and resets to "New" when a fresh tap sequence is started (for example by switching measurement type to brace after playback ends).
- Tap count is correctly displayed during file playback.
- The Play File dialog's **Browse** buttons now remember the last directory used per button — opening an audio file returns you to the audio folder, opening a calibration returns you to the calibration folder.
- File reading is more robust and handles stereo input correctly.

### Microphone Handling on Windows

- A misbehaving WASAPI shared-mode stream (silently zero-sample input on some built-in microphones) is now detected and the user is informed rather than seeing a flat-line spectrum.
- Microphone hot-plug switching has been reworked: removing and inserting a USB microphone is detected reliably and the audio engine restarts on the right device.
- WASAPI is now the preferred Windows audio host API, avoiding pseudo-streams that delivered all-zero samples.

### Spectrum Image and PDF Export

- Exported spectrum images and PDFs now match the live view: same chart title, same mode-line label positions, same dragged-annotation positions, and the captured measurement type, platform, and software version are stamped on the export.
- The calibration profile used for a measurement is now included in the PDF report.
- Annotations that had been hidden in the export are now correctly suppressed; annotations that had been repositioned by dragging now export at their dragged positions.

### Saved Measurements

- Double-click a saved measurement to load it; a single click no longer triggers a load (which previously made it easy to load a measurement by accident while trying to select one for comparison).
- The Save / Save As behaviour around loaded measurements has been cleaned up so the Save button stays available in the expected states.
- A peak-comparison view no longer scrolls when a measurement row is selected.

### Settings

- The settings layout has been tidied so related controls are grouped together.
- Switching guitar type (for example, Generic to Classical) now reclassifies the displayed peaks automatically rather than requiring a fresh tap sequence.
- Switching across the guitar / material boundary (between guitar and plate / brace) correctly restarts the tap sequence and resets the chart title.

### Installation

- Dependency version requirements have been relaxed from exact to minimum versions, reducing installation conflicts when other Python packages share the environment.

### Help

- The Help view has been updated to document Play Audio File, Re-analyze, and the new measurement-type workflow.

---

## Bug Fixes

- Fixed a bug where captured guitar taps were silently discarded as "orphan captures" whenever the measurement type was Acoustic, Classical, or Flamenco. Only Generic Guitar produced results before this fix.
- Fixed boolean settings (Dump Capture Audio, Show Unknown Modes) reverting to their default state every launch on Windows because QSettings round-trips booleans as strings on that platform.
- Fixed the chart title not resetting after switching measurement type post file-playback.
- Fixed the chart title reverting from a played filename back to "New" mid-playback.
- Fixed several test WAV / icon binary files that had been corrupted in the repository by historical CRLF line-ending normalisation; the corruption is now automatically detected and prevented by `.gitattributes`.
- Fixed broken Help menu on macOS.
- Fixed scroll-wheel on macOS causing too-rapid axis updates.
- Fixed a hang in the audio engine on macOS when stopping the stream during a transient device error.
- Fixed Save button disappearing in some states.
- Fixed import error handling — failed imports now report a clear error.
- Fixed inconsistent measurement-type / guitar-type combination after editing settings.
- Fixed mode lines being drawn for the wrong guitar type on first run.
- Fixed quality-colour duplication between the PDF and the live view.
- Fixed missing tap count display in the toolbar during file playback.
- Fixed FFT frequency / magnitude values diverging between the Python and Swift implementations for the same input.
- Fixed spinner width sizing in the toolbar on some platforms.
- Fixed spurious peak detected in brace measurements.
- Fixed transition from a multi-tap comparison back to a multi-waveform comparison.

---

---

## Version 1.0 · Build 263
### What's New Since Build 251

---

## New Features

### Play Audio File — Reliability and Accuracy

- Erratic or inconsistent results when analysing from a WAV file have been fixed — playback timing and FFT synchronisation are now much more robust.
- The FFT processing stack has been aligned with the iOS/macOS Swift version so that frequency and magnitude results now match between platforms.
- The chart title correctly shows the filename during and after playback, and no longer reverts to the default title.
- Fixed a bug where the tap count display was missing during file playback.

---

## Improvements

### Crash Visibility on Windows

- Previously, if Guitar Tap failed to start on Windows (where there is no console window), the failure was completely silent. The app now detects startup errors and shows a dialog with the error message and the location of a crash log file, making it possible to diagnose problems without needing a developer build.
- The splash screen is now always dismissed before the main window starts loading, so it can no longer get stuck on screen if startup is slow or fails.

### Help

- The Help view has been updated to document the Play Audio File feature.

### Installation

- Dependency version requirements have been relaxed to minimum versions rather than exact versions, reducing installation conflicts when other Python packages are present.

---

## Bug Fixes

- Fixed the chart title reverting after loading a file for playback.
- Fixed missing tap count shown in the toolbar during file playback.
- Fixed erratic FFT results when playing back a WAV file.
- Fixed FFT frequency/magnitude values diverging from the Swift version for the same input.
- Fixed spinner width sizing in the toolbar on some platforms.

---

*Build number is generated automatically from the git commit count.*
