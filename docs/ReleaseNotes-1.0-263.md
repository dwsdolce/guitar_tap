# GuitarTap Beta Release Notes

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
