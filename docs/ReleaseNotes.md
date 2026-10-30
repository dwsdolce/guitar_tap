# GuitarTap Release Notes

---

## Version {{version}} · Build {{build}}
### What's New Since Build {{since}}

<!-- Notes reviewed through commit 4c7d28b (2026-10-30). The next update reads only `git log 4c7d28b..HEAD`, then moves this line to the newest commit it covered. -->

---

## New Features

### Measurement Type Beside New Tap

- A new button beside **New Tap** shows the current measurement type (Generic, Acoustic, Classical, Flamenco, Plate or Brace). Choose another from its menu and Guitar Tap switches to it and starts a new tap of it, just as choosing it in Settings does — without opening Settings. It always shows the same type as Settings, and is disabled only while a file plays.

### Sort, Filter and Delete in Saved Measurements

- A new **Sort & Filter** menu sorts the list as added, by date, name or type (choose the same again to reverse it), or shows one type only — comparisons included. Your choice is remembered. **Delete All** is now a **Delete** menu: **All**, **Duplicates** (every later copy of a measurement, keeping the first) or **Selected** (tick the measurements to delete). The list itself always keeps the order the measurements were added.

### Export Selected, and Importing Several Files

- Saved Measurements' **Export** menu exports all your measurements (**Export All…**) or only the ones you select (**Export Selected…**), as one `.guitartap` file.
- **Import…** takes several files at once, with one message for all of them. A single measurement is loaded, as before; several are added to the list.
- Analysis Results has one **Export** button in place of Export Spectrum and Export PDF; its menu has **Export Spectrum…** and **Export PDF Report…**.
- Every menu item that opens a dialog ends in "…", and the Delete menu's items have icons.

### Chart Menu for a Comparison

- While a comparison is shown, the chart's menu resets either or both axes to the comparison range — the span of the compared measurements, where the comparison opened — in place of Saved and Defaults, which mean nothing for measurements of many guitars.

### Appearance: Light, Dark or System

- A new **Appearance** setting (Settings → Advanced → Display Settings, the first row) chooses **System** (the default — it follows your operating system and changes when it does), **Light** or **Dark**. The whole app follows it: the chart, peak cards, Analysis Results, toolbar, status bar, Settings, the measurement list and every dialog. Exported images and PDF reports are always drawn light, so they print the same whichever you work in. On Linux desktops that report no preference, System shows Light.

### Capture Audio: a Saved Notice, and No Lost Recordings

- With **Dump Capture Audio** on, the status bar now names the file just written ("Capture audio saved: …") until you dismiss it or start a new measurement.
- If the capture folder has been moved or deleted by the time a measurement finishes, the recording is kept and you are asked to choose a new location, turn saving off, or cancel — it is never silently lost. The folder button is now **Open Folder**, and opens the folder itself.
- A measurement is recorded when the setting is on as it starts, or is turned on before its first tap; turned on after that, it takes effect from the next measurement.

### Microphone Unavailable

- If a microphone you choose in Settings, plug in, or that a loaded measurement asks for cannot be opened, Guitar Tap keeps the input you were using and tells you so, instead of leaving a dead device selected.
- With no input device, or one that cannot be started, Guitar Tap still opens and works: you can load, import, compare and export; Play File needs the input running. The chart and status bar read "Audio input unavailable" (or "Starting..." while the input starts), and New Tap stays disabled until there is input. If the input stops and cannot be restarted, the status bar says so, and Guitar Tap keeps watching for it to come back.
- If Guitar Tap is not allowed to use the microphone (macOS Privacy & Security, or Windows' microphone privacy settings), it says so in a **Microphone Access Required** message, and the status bar says so too. Restart Guitar Tap after allowing access.

---

## Improvements

### System Requirements

- Guitar Tap on a Mac now needs macOS 15 Sequoia or later.

### Linux: AppImage, .deb and .rpm

- The AppImage now runs on Ubuntu 22.04 and later (and other distributions of that age) and needs nothing installed — not libfuse2, PortAudio or libxcb-cursor0. It uses your system's own sound setup (PipeWire or PulseAudio), and its file dialogs show network and remote places.
- Guitar Tap starts even on a system with no sound server, and reports the audio input as unavailable.
- Besides the AppImage, each release on GitHub has a `.deb` (Ubuntu, Debian, Linux Mint) and an `.rpm` (Fedora), which install Guitar Tap into the applications menu; the User Manual's §2.1 says how. Each release also lists every file's SHA-256 checksum (`SHA256SUMS`).

### Windows: Taps No Longer Suppressed by Audio Enhancements

- Guitar Tap now opens the microphone without Windows' audio effects — "Audio enhancements", Voice Clarity and vendor noise suppression — which were treating taps as noise and could cost a laptop's built-in microphone around 70 dB. A device that refuses this falls back to its normal mode.
- Plugging in a microphone (for example a UMIK-1) while Guitar Tap is running now switches to it reliably.

### A Cleaner, Consistent Look

- **Settings** is redesigned: each section is a titled box with one row per setting and its control at the right; the dropdowns, check boxes and buttons have one consistent style; Advanced is a single row that opens and closes.
- **Analysis Results**: peak cards show the full mode name and the pitch as "G2 (-10 ¢)"; plate and brace sections, the Ring-Out / Tap Ratio box and the export footer have one layout; a highlighted peak card takes its mode's colour. The toolbar and panels use one outline icon set.
- **Measurement Details** shows peaks with the same cards as the Results panel (read-only), with a plate or brace peak's fL / fC / fLC badge.
- **Saved Measurements**: plain rows with a line between them, a mark beside the date for a measurement with a spectrum or a comparison, and clearer selection circles in compare mode.
- **Save Measurement** and **Play Audio File** put a bold title above each field; Save and Play are highlighted only when they can act.
- **The status bar** matches the other editions, and its indicators follow detection exactly.
- **Done** buttons follow one rule: a Done that applies changes (Settings) is highlighted; one that only closes a window is plain.
- Dialogs use your system's own buttons. The tap count is a stepper whose label greys with it during a measurement, the Peak Min value sits on a small chip, peak dots are solid, menu icons stay visible on a highlighted item, and a saved measurement's menu button appears when the pointer is over its row. No overlay covers the window while exporting or starting, and warning signs are drawn as plain text, no longer as colour emoji on Windows.

### Quick Start Guide

- Brought in line with the other editions: the same sections, wording and icons, the current section's title stays at the top as you scroll, and it describes the new Appearance setting.

### The Chart

- The chart's range now changes only when you move it, when you load a measurement (its saved range), when a newly found plate or brace peak would fall off the chart (it widens to show it), or when you change the measurement type. New Tap or Play File after a load returns to your saved view unless you had moved the chart.
- Reset to Saved no longer makes a completed plate's peaks vanish, and a comparison's range is no longer cut short.
- The 0 and −100 dB labels are drawn, the lines are smooth on high-resolution screens, and the tick spacing matches the other editions.
- A peak's label sits 14 dB above its peak unless you drag it, and stays where you put it as you zoom or pan. A label stays with its peak when you pan the peak off the chart, and labels and mode chips are cut at the chart's edges rather than squeezed inside.
- A comparison of saved measurements shows no mode lines, on screen or in its exports; a multi-tap comparison keeps them. A comparison opens at a range spanning all its measurements, and a saved comparison remembers its own range.
- The legend of a comparison, of a multi-tap measurement's taps and of a plate's or brace's phases sits in the plot's upper-right corner and wraps onto as many lines as it needs. With many measurements it no longer runs off the chart's left edge.
- The crosshair follows the curve smoothly between points, and keeps to the curve it is on until you move clearly closer to another.
- The chart's help button lists the gestures for your computer: Ctrl+Scroll (Command+Scroll on macOS) zooms around the pointer, a trackpad pinch on macOS zooms, and scrolling outside the plot pans. The pointer shows what a drag will do: a crosshair over the plot, arrows over each axis, a hand over a label.
- The grid lies beneath the curves and labels, and "No peaks detected in visible range" shows when the chart's range holds none.

### Exports

- Exported images and PDF reports use the same layout as the other editions; the report's footer reads "Generated by GuitarTap Python …" with the export time, and long comparison names wrap instead of being cut off.
- A saved comparison's image and report are labelled **Comparison**, titled "FFT Peaks — *name*", and the report lists the frequency range — from the main window and from the measurement list alike.
- An exported image draws the same legend on the chart in place of the "Measurements:" row under it, which left out the names that did not fit.
- A comparison report's Frequency Range is the chart's range: the view on screen, or the range saved with the comparison. Page 2 of a multi-tap report uses the measurement's own range, as on screen.
- A plate's report shows all of its peaks, and exported reports show the Upper Modes band.
- On Linux, exports use a bundled font, so they lay out the same as on macOS and Windows.
- The default export folder is Documents/GuitarTap wherever Windows keeps Documents, including OneDrive.
- If the chart cannot be drawn, the export stops with **Export Failed** rather than saving a file without the chart.
- Export Spectrum and Export PDF Report give the same file from the main window and from Saved Measurements. A multi-tap measurement's image is its averaged spectrum, also while the Taps view is on.
- The report's peak table and the summary under an exported chart are titled **Selected Peaks** and list the selected peaks in view, whatever the annotation setting; "Detected Peaks: N" counts the peaks at or above Peak Min in view. Measurement Details' peak list is titled Selected Peaks too.

### Microphones

- On launch, the microphone you chose is used if it is connected; otherwise the system default, then the first device. A virtual device such as BlackHole no longer replaces your chosen microphone after a relaunch, and on Windows the correct system default is used.
- Loading a measurement switches to the microphone it was recorded with, and its warnings now say what they mean: **Microphone Not Found** names both microphones (a measurement from another computer or OS usually won't find its own); **Recording Setup Differs** lists each calibration or sample-rate difference. The warning appears once the load has finished.
- Importing measurements no longer raises microphone warnings; importing a single measurement loads it, with one combined message.
- The selected calibration's details in Settings update as you pick one.

### Play Audio File

- While a file plays, Cancel stops it and returns to the live microphone, and Pause and New Tap are disabled; changing the measurement type stops it. The file's name stays on the chart until a new measurement starts, and its result shows "Microphone: unknown".
- Playback timing follows the audio itself, so a slow or busy computer gives the same results as a fast one.

### Measurements

- Guitar taps are analysed from the tap's onset, as in the other editions, so the same recording gives the same peaks everywhere — wherever the tap falls in the audio stream.
- Ring-out is measured from the tap itself, to a fraction of a millisecond rather than in steps of about 21 ms, so the same tap reads the same ring-out in every edition. Expect ring-out values to differ slightly from earlier versions. A ring-out longer than about 1.2 s is not measured.
- With a microphone calibration loaded, its corrections are applied at each frequency exactly, as in the other editions (an Air peak could read 88.3 Hz instead of 88.4).
- Re-analyze keeps the names and label positions of the peaks it finds again.
- In Settings, Done after changing the measurement type or Measure FLC starts a new tap of the new kind; changing between guitar types re-labels the current peaks.
- Plate and brace measurements no longer end with "Missing Dimensions" or "Calculation Error" pop-ups; the properties appear once the dimensions are entered in the Results panel.
- **Generic Guitar** is the default measurement type for a new installation.
- The Ring-Out / Tap Ratio box shows a placeholder until there is a value, and "Unknown" for an invalid one.
- Every value is shown at the same precision as the other editions; sample rate and bandwidth read in whole hertz; digital silence reads "−∞"; a note exactly halfway between two pitches is named the same way everywhere.
- Mode colours match the other editions, so Upper Modes and Unknown are no longer the same grey.

### Faster

- The window does far less work while listening, a guitar measurement appears in a fraction of the time it did, and the chart draws only the range on screen.
- Resizing, zooming and panning a large comparison is much faster: the chart draws only the part of each curve in view.

### Quitting

- Quitting is clean: no warnings, Ctrl+C in a terminal closes the app like the close button, and a quit while audio is still stopping no longer crashes.

### Saved Measurements and Files

- If one measurement in your saved list cannot be read when Guitar Tap starts, only that one is left out: the rest load, a copy of the original file is kept beside it, and Guitar Tap tells you where. If the file cannot be read at all, it is renamed beside itself — correct it and rename it back to restore it. Your saved measurements are never written over.
- Importing a file with an unreadable measurement imports the rest and tells you which were skipped.
- A measurement file is read the same way by every edition: its ids may be in upper or lower case. A measurement with a missing or malformed id, or with no spectrum, is not opened.

---

## Bug Fixes

- **macOS: Guitar Tap now asks for the microphone.** It could report that microphone access was required without ever asking, and without appearing in System Settings' Microphone list.
- **A silent microphone is now noticed.** If the input keeps running but delivers no signal (an unplugged hub, a muted device, input volume at zero, after sleep), the status bar says "No audio input — check the microphone connection" and Guitar Tap recovers once the microphone is back.
- **A microphone change no longer wipes a finished measurement.**
- **Unplugging a microphone** could leave the app on the wrong device or freeze it, and a microphone connected afterwards could stay invisible.
- **Status no longer sticks** on "Audio device changed – reinitializing…" after quick unplug and replug cycles, and New Tap stays disabled while a new device settles.
- **A plate's status was replaced by the guitar prompt** after a device change; the plate prompt now reads "Ready for fL tap". An odd "Waiting for settle…" message after each guitar tap is gone.
- **A loaded comparison could be overwritten** by live taps behind it.
- **Save, Export Spectrum and Export PDF** are enabled only when there is a completed measurement or a comparison.
- **The Ring-Out box stopped updating live**, and clipping and no-input warnings could stop appearing after audio restarted.
- **A peak with no musical pitch** now reads "no pitch".
- **A stray peak in the Top / Back overlap, or a brace fL near 220 Hz, was labelled Top**; it is now unknown.
- **Measurement Details could show an out-of-date mode name** read from the file.
- **Edit Name & Notes offered Save when nothing had changed** if the notes had spaces at either end.
- **Play File could, rarely, freeze Guitar Tap** — and hold up the microphone for other apps until it was quit.
- **Exporting a measurement saved by Guitar Tap 1.0.x** put its dragged labels back in their default positions.
- **Opening a menu or pop-up during a measurement** — in Settings, Saved Measurements or the main window — could close it as the peaks appeared.
- **A sound during the warm-up could end a measurement on the room's noise** that followed.
- **New Tap could stay disabled** if the microphone restarted again while settling after a device change.
- **After the input restarted, choosing a microphone could open a different one.** Guitar Tap now checks the device it opened.
- **On macOS, a microphone that failed to start at the first attempt** is now tried once more before an error is shown; on Windows, duplicate "WDM-KS" inputs are no longer listed.
- **A selected peak below Peak Min appeared in a measurement's image and PDF report** exported from Saved Measurements, though not on screen.
- **A plate's or brace's exported image read "Comparing N measurements"** under its header.
- **After a comparison, switching to Plate or Brace showed an empty guitar peak list** in Analysis Results, pushing the plate's rows to the bottom.

---

## Known Limitations

### Microphone Hot-Plugging (Linux)

- On Linux, a microphone connected or disconnected **while Guitar Tap is running** is not
  detected automatically. The list of input devices is built when the app starts. To use a
  microphone you plugged in afterwards, open **Settings → Audio Input** and select it, or
  restart Guitar Tap.
- This affects the Linux build only. On macOS and Windows, microphones hot-plug
  automatically.
- The reason is that Linux audio servers such as PipeWire open and release the sound cards
  on their own, so a device can enter and leave the list without anything being plugged in
  or unplugged. Switching automatically on those changes would mean occasionally selecting
  a microphone you did not choose — and remembering it for next time — so Guitar Tap leaves
  the choice to you.

---

## Version 1.0.2 · Build 482
### What's New Since Build 378

---

## New Features

### Set a Plate or Brace's Dimensions in the Results

- You now enter a sample's dimensions where you read its results. After tapping, the Analysis Results panel has editable **Sample Dimensions** (length, width, thickness, mass) and — for a plate — **Body Dimensions** (body length, lower bout width, and panel stiffness); every property and the Gore target thickness recompute as you type. You no longer have to fill the numbers into Settings before you start: the Settings dimension fields are now just the defaults for a new measurement, and each measurement keeps its own values. Tap first, then enter or correct the exact dimensions afterward.

### Update Check

- Guitar Tap now tells you when a newer release is available. On start-up it checks this project's public release list on GitHub and shows a dismissible banner if there is something newer than the version you are running. You can also check on demand from **Check for Updates…** in the App menu (macOS) or the Help menu (Windows / Linux).
- The check is off-switchable, unobtrusive and private. It runs at most once a day, can be turned off entirely in **Settings → About & Help → Check for updates at startup**, and lets you skip a particular release. It never blocks start-up, and it never shows an error if you are offline. No audio, no measurements and no personal data are sent — it reads a public list of releases and nothing else.

### Export All / Import

- **Export All** writes every saved measurement to a single file, and **Import** brings a set back in — on the same machine or another one. Useful for backing up a session's work, or moving your measurements to a different device.

---

## Improvements

### Material (Plate & Brace) Results

- The Analysis Results panel now fills in **as you tap**. The Longitudinal (fL), Cross-grain (fC), and Diagonal (fLC) rows appear straight away as dashed placeholders and are completed as each phase finishes; the calculated properties appear only once the whole measurement is done. Previously the panel stayed empty until the very end, which gave no sense of progress.
- Peak selection for each material phase now uses the **averaged** spectrum of that phase's taps rather than the last tap alone.

### Clearer Tap-Mode Names

- The three material taps are now labelled consistently everywhere — **Longitudinal (fL)**, **Cross-grain (fC)**, and **Diagonal (fLC)** — on the chart, in the results, and on the report. The Settings option for the third tap is now **Measure Diagonal (fLC) Tap**.

### More Panel-Stiffness Presets

- The Gore target-thickness calculation adds **Classical Top** and **Classical Back** to the existing Steel String Top, Steel String Back, and Custom presets.

### Peak Min

- A saved guitar measurement now keeps **every detected peak down to -100 dB** (the lowest Peak Min can be set), not only those above the Peak Min in effect when it was saved. Lowering Peak Min on a loaded measurement now reveals fainter peaks — including a low Air resonance — exactly as it does during a live measurement. Measurements saved before this update keep only the peaks that were above their Peak Min at the time; use **Re-analyze** to re-derive the full set from the spectrum, then Save.
- Peak Min is now purely a **display** control: raising or lowering it only shows or hides peaks — it never changes which peaks are selected, how they are classified, or the identified modes. Those are properties of the measurement itself.

### Peaks & Modes

- **Reclassifying an unknown peak.** A peak classified as unknown — one in no known mode range — that you manually reclassify as another mode (an existing mode or a user-defined one) is no longer unknown, so Show Unknown Modes no longer hides it.
- **One definitive Air, Top, and Back.** Each of these modes now resolves to a single definitive peak — the selected peak whose (possibly overridden) mode matches. The **Select All Peaks** control has been removed; selection is per-peak, and the identified modes follow from it.
- **Derived values follow your selection and overrides.** The tap-tone ratio and other derived figures are now computed from the definitive peaks, so they reflect your peak selection and any mode overrides you have applied rather than the raw strongest peak.
- **Multi-tap Taps table honours overrides.** When you override a mode in a multi-tap measurement, the averaged **Taps** table row now shows the peak you chose (marked in *italics with an asterisk*), matching page 1 of the PDF report, instead of the algorithm's automatic pick.
- **Comparisons are self-describing.** Saved comparison measurements now record which peak carries each mode, so a reloaded comparison — its table and PDF — reflects the mode overrides that were in effect when it was saved.
- **Changing guitar type is a clean slate.** Changing the guitar type on a measurement re-runs classification and peak selection and clears any manual mode overrides, so the identified modes match the new type. (A display-only settings change — Peak Min or the display ranges — leaves peaks, modes, and selection untouched.)
- **A new tap sequence starts clean.** Starting a fresh measurement now clears any peak selection, mode overrides, and moved annotations from the previous one.

### Re-analyze

- **Re-analyze** is now offered for any completed guitar measurement, not only one loaded from a file, and it no longer disables itself after a single press.
- It is a reset: it re-derives the peaks from the spectrum using your current settings, re-classifies the modes from scratch, and returns peak selection to automatic. Custom mode names you have assigned are kept — but the peak carrying one may be deselected, so re-select it to see the label again.
- It is not offered for Plate or Brace measurements, where it does not apply.

### Tap Sequence Controls

- **Cancel** now restarts the tap sequence rather than leaving it half-finished, and **New Tap** is available whenever a measurement isn't actively being captured, so you can always start a fresh one.
- The **Taps** (multi-tap comparison) toggle is now enabled and disabled in place instead of appearing and disappearing.
- The **Adjust** button is now labelled **Redo**, which is clearer about what it does.

### Status Messages

- The status line stays quiet during the brief warm-up at start-up instead of reporting a state that isn't meaningful yet.
- Plate and brace measurements now show the phase guidance — "Tap the plate along the long axis", and so on — which was previously being hidden.

### Analysis Results Panel

- The **Select None** button now shows its icon. It was present and working, but drawing blank on macOS.
- Peak **Q factor** is shown to one decimal place, matching the other editions.
- The **Export PDF Report** button is now simply **Export PDF**.

### Spectrum Chart

- The **Peak Min** threshold line is now dashed with a right-aligned label, matching the other editions.

### Measurements

- The **Measurement Details** pane now shows the same information in the same order across every edition of Guitar Tap.
- Dates and times are displayed consistently throughout the app.
- The display frequency range is now remembered **per measurement type**, so guitar, plate and brace each keep their own view.
- The **Analysis Frequency Range** setting has been removed from Settings; the analysis range is now a fixed 30–2000 Hz. The separate *display* range you pan and zoom on the chart is unaffected.

### Entering Numbers

- Numeric fields now keep a **consistent precision**. Each field accepts only as many decimal places as it actually uses — plate and brace dimensions to 0.01 mm, mass to 0.1 g, and body dimensions, the display frequency range, and the magnitude range to whole units — and declines an extra digit as you type. The value you enter is therefore exactly what is stored and what appears in Settings, the measurement, and the report. Previously a field could show more decimals than it kept, so a saved value could read back a hair different from what you typed.

### Saving

- Saving a measurement now **requires a name**, so every measurement is identifiable at a glance in the list and in exports. The **Save** button stays disabled until you enter one; notes remain optional.

### Recording

- **Dump Capture Audio** previously wrote both a WAV for every tap and a continuous recording of the whole session. It now writes only the continuous session recording, which already contains every approved tap in capture order — the per-tap files were redundant.
- With **Dump Capture Audio** on, you can now see and change **where** the WAV files are saved. A folder row appears with **Open Folder / Change… / Use Default**; the default is your **Documents** folder plus `GuitarTap` (honouring a redirected or OneDrive Documents location). If you rename, move, or delete that folder, Guitar Tap asks you to fix it (Change Location / Turn Off Saving / Cancel) before the measurement starts, so a capture is never written to a missing folder.

### Exporting

- Exported file names are now **consistent across macOS, the Python build, and the web**, and names with accented or non-Latin characters (for example *Ramírez*) are preserved correctly instead of being stripped.

### Documentation

- Help now covers Export All, resetting peak selection to automatic, the Cancel-as-restart behaviour, the required measurement name, the settable capture-audio folder, when New Tap is available, and the lead-in a recording needs before the first tap when playing a Plate or Brace measurement from a file.

---

## Bug Fixes

- **A duplicate peak could appear in the analysis results.** Every guitar measurement quietly included one extra peak — a duplicate of a real resonance in the Top/Back overlap region — which showed as a repeated row in the Analysis Results and in the exported spectrum. It is no longer produced, and any existing measurement is corrected automatically when it is opened.
- **Flamenco:** the Top and Back resonances could be identified in reverse. The frequency windows for the two flamenco modes were set the wrong way round, so the stronger, lower resonance could be labelled Back and the higher one Top. The windows are corrected, so both modes are now identified correctly.

- **The microphone could silently stop delivering audio** — most often because another app took it, or the device reconfigured itself — and Guitar Tap would sit there looking like it was listening while receiving nothing. It now detects this and restarts the input automatically.
- **Status bar:** during a plate or brace measurement the tap count restarted at each phase, the progress bar blinked in and out, and the label could freeze at 0/N. The bar now appears with the first tap and stays for the whole sequence, counting every tap across all phases.
- **Brace measurements** labelled the status "Phase 1/1"; they now read "Tap X/N" like every other measurement.
- **Microphone hot-plugging (Windows).** On Windows, hot-plugging was not detected and switching input devices could crash the app. Disconnecting the active microphone now falls back automatically to the built-in device, and switching devices no longer crashes. Because of a limitation in the Windows audio layer, a microphone **connected after the app is running** cannot be switched to automatically; as a work-around, open the **Settings** panel and select it there and the app switches to it without a restart. This affects the Windows build only — on macOS, microphones hot-plug automatically.
- Switching from a material measurement back to a guitar measurement could leave the capture stranded in the previous state.
- **New Tap could get stuck disabled.** If you cancelled the capture-folder prompt — or launched with a chosen folder that was no longer reachable — the app could end up with every tap control disabled and no way to start. New Tap is now available whenever the detector is idle, so you can always begin again.
- **Ring-out (decay time) could be misreported.** It was sampled on too coarse a cadence and timed with the wall clock, so a busy computer could skew the number; the "Good" threshold was also wrong for acoustic and generic guitars. It is now sampled once per audio chunk and timed on the audio clock — staying accurate under load — with the correct thresholds.
- Material peak selection used the last tap rather than the averaged spectrum of the phase.
- Microphone **calibration files** were not reading the reference-SPL / sensitivity-factor precedence the same way as the other editions, which could shift the level.
- **Playing a measurement from a file** did not detect taps the same way a live measurement does. It used a fixed threshold rather than tracking the noise floor, and its warm-up was timed on the clock rather than on the audio, so the warm-up expired before any audio had arrived. File playback now behaves exactly like a live measurement — which also means a recording needs a short lead-in before its first tap (see Help).
- During a plate capture, the identified peaks were not annotated on the chart until the whole measurement finished. They now appear at the completion of each phase (Longitudinal, then Cross, then FLC).

---

---

## Version 1.0.1 · Build 378
### What's New Since Build 376

---

## Improvements

### Spectrum Chart Controls

- Added a **Chart Options** button to the spectrum chart that opens the same reset/options menu as right-clicking the chart.

### Measurements List

- The actions button on each measurement row now opens a menu with the same actions as right-click.

### Measurement Provenance

- Saved `.guitartap` files now record the **capture sample rate**. On load, the app warns if the current microphone's calibration or sample rate differs from what was recorded. This keeps the format in step with the GuitarTap Apple app, so files remain fully interchangeable.

### Documentation

- The Quick-Start Guide has been refreshed.

---

## Bug Fixes

- Fixed a loaded guitar measurement showing a **blank spectrum** when the app was restarted while the previously loaded measurement was a Plate or Brace (material) measurement.

---

---

## Version 1.0 · Build 376
### What's New Since Build 375

---

## Improvements

### Cross-Platform File Compatibility

- Measurement files (`.guitartap`) written by the Python build now match the iOS/macOS Swift app exactly for the same measurement. Numeric precision, field names, and the encoding of peak mode-label overrides and annotation positions have all been aligned with the Swift format, so files round-trip cleanly in both directions.

---

## Bug Fixes

- Fixed user-assigned peak **mode-label overrides** being written in a layout the Swift app could not read, which prevented those measurement files from opening in the iOS/macOS app. Overrides are now written in the shared format; both the new and the previous layouts are still read on import.
- Fixed the minimum-peak-threshold value being saved under a legacy field name, so it is now preserved when a file is opened in the Swift app.
- Aligned saved numeric precision — peak frequencies, magnitudes, Q, thresholds, and material dimensions — with the Swift build so values match exactly across platforms.

---

---

## Version 1.0 · Build 375
### What's New Since Build 368

---

## New Features

### Linux AppImage Distribution

- GuitarTap now ships as an **AppImage** for Linux — a single self-contained executable that requires no system package installation. The AppImage bundles Python, Qt, and all dependencies; download, mark executable, and run.

### User Manual

- A comprehensive **User Manual** is now available, covering all three measurement modes (Guitar, Plate, Brace), the spectrum chart, saving and exporting measurements, a complete settings reference, a controls reference, and tips and troubleshooting. Eleven chapters plus appendices for keyboard shortcuts and file formats. The manual is published separately as HTML and PDF. The manual can be opened from the Help in the menu bar or from the Settings dialog.

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
