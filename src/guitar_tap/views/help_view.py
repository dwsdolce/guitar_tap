"""
    Help window — QDialog with QTextBrowser showing HTML reference content.

    _HELP_HTML is built once on first import, embedding qtawesome icons as
    inline base64 PNG data-URIs so the same icons used in the app appear in
    the help text.
"""

from __future__ import annotations

from PySide6 import QtWidgets, QtCore, QtGui
import qtawesome as qta


# ---------------------------------------------------------------------------
# Icon-to-HTML helpers
# ---------------------------------------------------------------------------

def _icon_img(name: str, size: int = 14, color: str = "#444444") -> str:
    """Render a qtawesome icon and return an inline <img> data-URI tag."""
    pixmap = qta.icon(name, color=color).pixmap(size, size)
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    b64 = ba.toBase64().data().decode()
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'width="{size}" height="{size}" style="vertical-align:middle; margin-right:2px">'
    )


def _h2(icon_name: str, title: str) -> str:
    """Section header with icon."""
    return f'<h2>{_icon_img(icon_name, 16, "#555555")}&nbsp;{title}</h2>\n'


def _row(title: str, body: str, icons: list[str] | None = None) -> str:
    """Help row: bold title (optionally preceded by icons) + gray body."""
    icon_html = "".join(_icon_img(i, 13, "#0066CC") for i in (icons or []))
    if icon_html:
        icon_html += "&nbsp;"
    return (
        f'<div class="row">'
        f'<p class="row-title">{icon_html}{title}</p>'
        f'<p class="row-body">{body}</p>'
        f'</div>\n'
    )


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _build_help_html() -> str:
    CSS = """\
<style>
  body       { font-size: 13px; margin: 16px; }
  h1         { font-size: 18px; margin-bottom: 4px; }
  h2         { font-size: 14px; margin-top: 20px; margin-bottom: 6px;
               border-bottom: 1px solid #ccc; padding-bottom: 3px; color: #333; }
  .row       { margin-bottom: 10px; }
  .row-title { font-weight: bold; font-size: 13px; margin: 0 0 2px 0; }
  .row-body  { color: #555; margin: 0; line-height: 1.5; }
  p, li      { margin: 4px 0; line-height: 1.5; }
  ul         { margin: 4px 0; padding-left: 20px; }
</style>"""

    parts: list[str] = [
        "<!DOCTYPE html><html><head>", CSS, "</head><body>\n",
        f'<h1>{_icon_img("mdi.waveform", 18, "#333")}&nbsp;Quick-Start Guide</h1>\n',
    ]

    # ── What Guitar Tap Does ──────────────────────────────────────────────
    parts.append(_h2("mdi.waveform", "What Guitar Tap Does"))
    parts.append(
        "<p>Guitar Tap uses your device's microphone to capture the brief ring-out after "
        "you tap a guitar or wood sample. A 65,536-point FFT (&asymp;0.67&nbsp;Hz "
        "resolution) reveals the resonant peaks that carry information about structural "
        "modes and material stiffness.</p>\n"
        "<p>Three main workflows are supported:<br>"
        "&bull; <b>Guitar mode</b> &mdash; classify resonant modes of a completed instrument.<br>"
        "&bull; <b>Plate mode</b> &mdash; measure Young&rsquo;s modulus and quality of a raw tonewood plate.<br>"
        "&bull; <b>Brace mode</b> &mdash; measure Young&rsquo;s modulus and quality of a brace strip "
        "(single longitudinal tap).</p>\n"
    )

    # ── First-Time Setup ──────────────────────────────────────────────────
    parts.append(_h2("mdi.wrench", "First-Time Setup"))
    parts.append(_row(
        "Grant Microphone Access",
        "The first time the app launches it will ask for microphone permission. "
        "Without it the analyzer cannot run."
    ))
    parts.append(_row(
        "Select Audio Input",
        "Open Settings. The Audio Input &amp; Calibration section appears at the top. "
        "Choose your microphone or audio interface here. If you have a calibration file "
        "for your measurement mic, import it in this section too."
    ))
    parts.append(_row(
        "Choose a Measurement Type",
        "In Settings, the Measurement Type section is directly below Audio Input. "
        "Pick Generic Guitar (the default, with broad ranges covering all types), "
        "Classical Guitar, Flamenco, Steel String, Material (Plate), or Material (Brace). "
        "The right choice determines which mode-frequency ranges are used and which "
        "measurements are calculated."
    ))
    parts.append(_row(
        "Advanced Settings",
        "Display range, analysis range, and FFT processing options are grouped under the "
        "Advanced section at the bottom of Settings. These rarely need changing after "
        "initial setup &mdash; expand the section by clicking the Advanced row."
    ))
    parts.append(_row(
        "Quiet Environment",
        "Background noise raises the noise floor. A quiet workbench with the device "
        "resting on a folded cloth a few centimetres from the tap point gives the most "
        "repeatable results."
    ))

    # ── Guitar Mode ───────────────────────────────────────────────────────
    parts.append(_h2("mdi.music", "Guitar Mode"))
    parts.append(_row(
        "Overview",
        "Guitar mode identifies the key structural resonances of a completed body: "
        "Air (Helmholtz cavity resonance), Top (main top-plate resonance), Back, "
        "Dipole, Ring Mode, and Upper Modes."
    ))
    parts.append(_row(
        "Step 1 &mdash; Configure",
        "In Settings choose the guitar type (Generic Guitar by default, or Classical, "
        "Flamenco, Acoustic/Steel String) in the Measurement Type section. Each type has "
        "calibrated frequency windows for each mode, shown there. Generic Guitar uses broad "
        "ranges that cover all guitar types. The Show Unknown Modes toggle is in the Advanced section."
    ))
    parts.append(_row(
        "Step 2 &mdash; Position the Microphone",
        "The spectrum updates in real time as soon as the app opens. Set the device "
        "microphone 5&ndash;15&nbsp;cm from the guitar, aimed at the sound hole or tap point."
    ))
    parts.append(_row(
        "Step 3 &mdash; Tap New Tap",
        "Click the New Tap button to arm the detector, then give the guitar top (or back, "
        "side, etc.) a firm knuckle rap. The spectrum freezes automatically when a tap is detected."
    ))
    parts.append(_row(
        "Step 4 &mdash; Inspect Peaks",
        "Coloured markers label each resonant peak with its mode, frequency, and pitch. "
        "In guitar mode, one peak per mode is auto-selected based on the strongest peak in "
        "each frequency range, working lowest-to-highest so overlapping ranges resolve in "
        "favour of the lower mode. Use the Annotations button to cycle through "
        "All / Selected / None label modes. The reset button in the Results panel resets "
        "selections back to automatic if you have made manual changes."
    ))
    parts.append(_row(
        "Step 5 &mdash; Read the Results",
        "The results panel shows the peak list with frequency, magnitude, Q factor, "
        "bandwidth, and pitch. Decay time (ring-out in seconds) and Tap Tone Ratio "
        "(Top &divide; Air) are shown when applicable. Typical top/air ratios range from "
        "1.8 to 2.4 for quality instruments."
    ))
    parts.append(_row(
        "Multi-Tap Averaging",
        "Setting the tap count to 2&ndash;10 averages multiple taps together, reducing "
        "noise from finger squeaks and ambient sounds. Progress is shown in the status bar. "
        "Use Pause between taps to let the ring-out decay."
    ))
    parts.append(_row(
        "Overriding Mode Classification",
        "If a peak is labelled Unknown, or misclassified, click it in the Results list "
        "and assign the correct mode manually. Your override is saved with the measurement."
    ))
    parts.append(_row(
        "Step 6 &mdash; Save",
        "Click Save. Enter a location (e.g. &ldquo;Upper Bout&rdquo; or &ldquo;Treble Side&rdquo;) "
        "and any notes. The measurement is stored with all peaks, the spectrum snapshot, "
        "and a chart image."
    ))

    # ── Plate Mode ────────────────────────────────────────────────────────
    parts.append(_h2("mdi.layers", "Plate Mode"))
    parts.append(_row(
        "Overview",
        "Plate material mode measures the stiffness of a rectangular tonewood sample using "
        "three free-free beam bending taps: Longitudinal (along grain), Cross-grain, and "
        "optionally FLC (diagonal/torsional). From the tap frequencies it derives Young&rsquo;s "
        "modulus, speed of sound, specific modulus, radiation ratio, and a quality rating."
    ))
    parts.append(_row(
        "Prepare the Sample",
        "Cut or plane a rectangular blank. Measure length (along grain), width (cross grain), "
        "thickness, and mass precisely &mdash; accuracy here directly affects the calculated "
        "moduli. A kitchen scale accurate to 0.1&nbsp;g is adequate for most samples."
    ))
    parts.append(_row(
        "Enter Dimensions in Settings",
        "Open Settings &rarr; Measurement Type &rarr; Material. Enter Length (along grain), "
        "Width (cross grain), Thickness, and Mass. The app instantly shows the calculated "
        "density so you can catch data-entry errors before tapping."
    ))
    parts.append(_row(
        "Suspension Technique",
        "Hold the plate at one point 22% from one end along the dimension being measured, "
        "positioned near one edge in the other dimension (not on that dimension&rsquo;s nodal "
        "line). This damps the unwanted resonance while approximating the free-free boundary "
        "condition. The other hand taps."
    ))
    parts.append(_row(
        "Tap 1 &mdash; Longitudinal",
        "With the grain running left&ndash;right, hold the plate at one point 22% from one "
        "end along the length, near one long edge (not at the width nodal line &mdash; this "
        "damps the cross-grain resonance). Tap center. Click New Tap and follow the on-screen "
        "prompt &ldquo;Capturing Longitudinal&rdquo;. The app selects the strongest peak as "
        "the longitudinal frequency."
    ))
    parts.append(_row(
        "Tap 2 &mdash; Cross-Grain",
        "Rotate the plate 90&deg; so the grain runs front&ndash;back. Hold at one point 22% "
        "from one end along the width, near one short edge (not at the length nodal line &mdash; "
        "this damps the longitudinal resonance). Tap center. The app prompts "
        "&ldquo;Capturing Cross-Grain&rdquo; automatically after the longitudinal tap is accepted."
    ))
    parts.append(_row(
        "Tap 3 &mdash; FLC (Optional)",
        "Enable Measure FLC in Settings. Hold the plate at the midpoint of one long edge "
        "and tap near the opposite corner (~22% from both the end and the side). This adds "
        "a shear modulus measurement used in the Gore target-thickness calculation. "
        "Omitting it over-estimates target thickness by roughly 5&ndash;7%."
    ))
    parts.append(_row(
        "Reading the Results",
        "After all taps, view Results to see:<br>"
        "&bull; E_L / E_C &mdash; Young&rsquo;s modulus along and across grain (GPa)<br>"
        "&bull; c_L / c_C &mdash; Speed of sound in each direction (m/s)<br>"
        "&bull; Specific modulus E/&rho; &mdash; The primary quality metric (GPa per g/cm&sup3;)<br>"
        "&bull; Radiation ratio &mdash; Sound radiation efficiency<br>"
        "&bull; Cross/Long ratio &mdash; Anisotropy (spruce: typically 0.04&ndash;0.08)<br>"
        "&bull; Quality rating &mdash; Excellent / Very Good / Good / Fair / Poor (spruce scale)<br>"
        "&bull; Gore target thickness &mdash; Recommended finished plate thickness for a guitar "
        "of your specified body dimensions (requires FLC or uses an approximation)"
    ))
    parts.append(_row(
        "Spruce Quality Scale",
        "Specific modulus (longitudinal): &ge;&nbsp;25 &rarr; Excellent (Master grade); "
        "&ge;&nbsp;22 &rarr; Very Good (AAA); &ge;&nbsp;19 &rarr; Good (AA); "
        "&ge;&nbsp;16 &rarr; Fair (A); &lt;&nbsp;16 &rarr; Poor."
    ))
    parts.append(_row(
        "Gore Target Thickness",
        "Enter the finished guitar body length and lower bout width in Settings (Material "
        "section). Choose the plate stiffness preset: Steel String Top (f_vs 75), "
        "Steel String Back (55), Classical (50), or Custom. The result is the plate thickness "
        "that hits the preset vibrational stiffness after bracing is factored in &mdash; a "
        "direct implementation of Gore Equation 4.5-7."
    ))

    # ── Brace Mode ────────────────────────────────────────────────────────
    parts.append(_h2("mdi.minus-box-outline", "Brace Mode"))
    parts.append(_row(
        "Overview",
        "Brace mode is a fast single-tap variant of Plate mode designed for brace strips. "
        "Only a longitudinal tap is needed; cross-grain and FLC are skipped."
    ))
    parts.append(_row(
        "Brace Orientation",
        "In Settings &rarr; Brace Dimensions, Height is the dimension in the tap direction "
        "(the brace standing upright on the bench). This is the t value in the stiffness "
        "formula. Length is along the grain."
    ))
    parts.append(_row(
        "Technique",
        "Hold the brace at one point 22% from one end along the length, near one edge in "
        "the width direction (not on the width nodal line). Tap the top face at the center. "
        "The same one-point hold technique as Plate mode."
    ))
    parts.append(_row(
        "Results",
        "E_L, c_L, specific modulus, and a spruce quality rating are reported. "
        "No cross-grain or Gore thickness calculation is available in Brace mode."
    ))

    # ── Controls Reference ────────────────────────────────────────────────
    parts.append(_h2("mdi.gesture-tap", "Controls Reference"))
    parts.append(_row(
        "New Tap",
        "Arms the detector for the next tap (or begins a plate measurement sequence). "
        "A green indicator shows when a tap has been registered.",
        ["mdi.gesture-tap"]
    ))
    parts.append(_row(
        "Pause / Resume",
        "Temporarily suspends tap detection while keeping the spectrum live. "
        "Useful between taps in a multi-tap sequence.",
        ["fa5.pause-circle", "fa5.play-circle"]
    ))
    parts.append(_row(
        "Cancel",
        "Aborts a multi-tap or plate measurement sequence and discards the partial data.",
        ["fa5.times-circle"]
    ))
    parts.append(_row(
        "Auto dB",
        "Scales the magnitude axis to fit the current signal. "
        "Click it after each measurement to keep peaks visible.",
        ["mdi.swap-vertical-circle-outline"]
    ))
    parts.append(_row(
        "Annotations",
        "Cycles through three label modes: All peaks annotated, Selected peaks only, or None.",
        ["fa5.eye", "fa5.star", "fa5.eye-slash"]
    ))
    parts.append(_row(
        "Peak Labels",
        "Drag any peak label to reposition it and avoid overlaps. "
        "To reset an individual label: right-click it and choose &ldquo;Reset Position&rdquo;. "
        "To reset all labels at once: right-click the chart area (not a label) and choose "
        "&ldquo;Reset Labels&rdquo;."
    ))
    parts.append(_row(
        "Play Audio File",
        "Feeds a WAV or audio file through the FFT pipeline instead of the microphone. "
        "The file&rsquo;s tap is analysed exactly as a live microphone tap &mdash; tap "
        "detection fires automatically, peaks are found, and results appear in the panel. "
        "The chart title shows the filename while the file plays. After playback the "
        "microphone restarts automatically. Access via File menu &rarr; "
        "Play Audio File&hellip; (Ctrl+Alt+O).",
        ["fa5.play-circle"]
    ))
    parts.append(_row(
        "Save",
        "Saves the current measurement &mdash; enabled only when the spectrum is frozen "
        "and peaks have been detected. Enter a location label and optional notes.",
        ["fa5.save"]
    ))
    parts.append(_row(
        "Measurements",
        "Lists all saved measurements. Right-click a row to access: Load into View, "
        "View Details, Export Measurement, Save Measurement to Disk, Export Spectrum, "
        "Export PDF Report, or Delete. Use Import Measurement to load a file from disk. "
        "Use Compare to enter multi-select mode and overlay 2&ndash;5 saved guitar "
        "measurements on the main chart for side-by-side comparison.",
        ["fa5s.clipboard-list"]
    ))
    parts.append(_row(
        "Compare Measurements",
        "In the Measurements list, click Compare to enter selection mode. "
        "Select 2&ndash;5 saved guitar measurements (plate and brace measurements cannot "
        "be compared). Click Compare Selected to overlay all selected spectra on the main "
        "chart as colour-coded curves with a legend. Press New Tap to exit comparison and "
        "return to single-measurement mode.",
        ["mdi.waveform"]
    ))
    parts.append(_row(
        "Metrics",
        "Shows FFT engine statistics: frame rate, bin width (Hz/bin), sample rate, "
        "and buffer size.",
        ["fa5.chart-bar"]
    ))
    parts.append(_row(
        "Menu Bar",
        "The menu bar has four menus:<br><br>"
        "<b>GuitarTap menu:</b><br>"
        "&bull; <b>About Guitar Tap…</b> &mdash; shows app description<br>"
        "&bull; <b>Settings…</b> &mdash; Ctrl+, (⌘, on macOS)<br>"
        "On macOS these items are automatically moved to the system Application menu.<br><br>"
        "<b>File menu:</b><br>"
        "&bull; <b>Close</b> &mdash; Ctrl+W (⌘W on macOS) &mdash; closes the window<br>"
        "&bull; <b>Play Audio File…</b> &mdash; Ctrl+Alt+O &mdash; feeds a WAV or audio file through the FFT pipeline instead of the microphone<br>"
        "&bull; <b>Save Measurement…</b> &mdash; Ctrl+S<br>"
        "&bull; <b>Export Spectrum Image…</b> &mdash; Ctrl+E<br>"
        "&bull; <b>Export PDF Report…</b> &mdash; Ctrl+Shift+E<br>"
        "Save and Export items are disabled until a measurement is complete.<br><br>"
        "<b>View menu:</b><br>"
        "&bull; <b>Auto dB</b> &mdash; Ctrl+0 &mdash; toggles auto-scaling of the dB axis<br>"
        "&bull; <b>Cycle Annotations</b> &mdash; Ctrl+` &mdash; cycles Selected → None → All<br>"
        "&bull; <b>Show Metrics</b> &mdash; Ctrl+M &mdash; opens the FFT diagnostics panel<br>"
        "&bull; <b>Show Measurements</b> &mdash; Ctrl+L &mdash; opens the saved measurements browser<br><br>"
        "<b>Help menu:</b><br>"
        "&bull; <b>Guitar Tap Help</b> &mdash; F1 (⌘? on macOS) &mdash; opens this window"
    ))
    parts.append(_row(
        "Zoom &amp; Pan Help",
        "Scroll over the chart to zoom &mdash; the axis depends on where the pointer is: "
        "over the plot area it zooms both axes; over the frequency axis (bottom) it zooms "
        "frequency only; over the magnitude axis (left) it zooms magnitude only. "
        "Drag to pan the same way. Modifier keys: Shift+Scroll &mdash; pan frequency; "
        "Alt+Scroll &mdash; pan magnitude; Cmd/Ctrl+Scroll &mdash; zoom both axes. "
        "To reset the axes, right-click anywhere inside the chart.",
        ["mdi.information"]
    ))

    # ── Tap Controls ─────────────────────────────────────────────────────
    parts.append(_h2("mdi.tune", "Tap Controls"))
    parts.append(_row(
        "Taps (stepper)",
        "How many taps to average together (1&ndash;10). Averaging reduces noise from "
        "tap-position variability and ambient sound. Values of 3&ndash;5 are a good "
        "starting point for material work."
    ))
    parts.append(_row(
        "Threshold (slider)",
        "The signal level that triggers tap detection. If taps are being missed, move the "
        "slider left (lower). If ambient noise triggers false detections, move it right "
        "(higher). Displayed in dB."
    ))
    parts.append(_row(
        "Peak Min (slider)",
        "Minimum magnitude a spectral peak must reach to be annotated on the spectrum chart. "
        "In guitar mode, a peak must also clear this threshold to be reported; adjusting it "
        "on a frozen spectrum re-runs peak finding and updates auto-selections (or carries "
        "forward manual selections if you have changed them). In brace/plate mode, the tap "
        "capture uses its own adaptive noise floor &mdash; Peak Min only affects what is "
        "visible on the chart, not which peaks are selected. Move the slider left to show "
        "quieter peaks; right to suppress noise. Displayed in dB."
    ))
    parts.append(_row(
        "Reset arrows",
        "Each slider has a small reset button that resets it to the factory default value."
    ))

    # ── Settings Reference ────────────────────────────────────────────────
    parts.append(_h2("fa5s.cog", "Settings Reference"))
    parts.append(_row(
        "Audio Input &amp; Calibration",
        "Shown at the top of Settings. Select your microphone or audio interface here. "
        "Import a frequency-response calibration file (.txt/.cal) to compensate for "
        "microphone coloration; calibrations are automatically associated with each device. "
        "Audio input and calibration changes take effect immediately and are not affected by Cancel."
    ))
    parts.append(_row(
        "Measurement Type",
        "Shown below Audio Input. Choose Generic Guitar (the default), Classical Guitar, "
        "Flamenco, Acoustic/Steel String, Material (Plate), or Material (Brace). "
        "Determines which mode frequency windows are applied and which calculations appear in Results."
    ))
    parts.append(_row(
        "Advanced (collapsed section)",
        "Click the Advanced row to expand Display Settings, Analysis Settings, and FFT "
        "Processing. These options rarely need changing after initial setup."
    ))
    parts.append(_row(
        "Show Unknown Modes",
        "Guitar mode only &mdash; found in Advanced &rarr; Analysis Settings. When off, "
        "peaks outside the known mode frequency windows are hidden, reducing clutter."
    ))
    parts.append(_row(
        "Display Frequency Range",
        "Advanced &rarr; Display Settings. Sets the horizontal zoom of the spectrum chart. "
        "Narrow the range to zoom in on a region of interest."
    ))
    parts.append(_row(
        "Display Magnitude Range",
        "Advanced &rarr; Display Settings. Sets the vertical scale (dB). Use Auto dB in "
        "the main view for a quick fit, or set explicit Min/Max here."
    ))
    parts.append(_row(
        "Analysis Frequency Range",
        "Advanced &rarr; Analysis Settings. Peaks outside this window are ignored during "
        "detection. Narrow it to exclude spurious low-frequency rumble or high-frequency noise."
    ))
    parts.append(_row(
        "Peak Min",
        "Advanced &rarr; Analysis Settings. Sets the minimum magnitude (dB) for a peak to "
        "be annotated on the spectrum chart. In guitar mode this also gates which peaks are "
        "reported; adjusting it on a frozen spectrum re-runs peak finding and updates "
        "selections. In brace/plate mode it only affects what is annotated on the live chart. "
        "Typical useful range: &minus;60 to &minus;40 dB."
    ))
    parts.append(_row(
        "Hysteresis Margin",
        "Advanced &rarr; Analysis Settings. How far the signal must drop below the detection "
        "threshold before the detector resets and is ready for the next tap. A higher value "
        "prevents a single loud tap from triggering multiple detections. "
        "Range: 1&ndash;10 dB; default is 6 dB."
    ))
    parts.append(_row(
        "Maximum Peaks",
        "Advanced &rarr; Analysis Settings. Caps the number of peaks reported. Set to All "
        "to include every peak above the threshold. Fewer peaks reduces visual clutter when "
        "testing assembled guitars."
    ))
    # ── Tips & Technique ─────────────────────────────────────────────────
    parts.append(_h2("mdi.lightbulb-outline", "Tips &amp; Technique"))
    parts.append(_row(
        "Tap Technique",
        "Use a short, crisp knuckle, fingertip tap, or a bouncy ball on a stick. "
        "A slow, pressing contact excites fewer overtones and produces a cleaner fundamental. "
        "Avoid tapping near the edges &mdash; aim for the centre of the plate or brace in "
        "Plate and Brace modes and near the bridge area for guitar-body mode surveys."
    ))
    parts.append(_row(
        "Consistent Mic Position",
        "Keep the microphone at the same distance and angle between measurements for the "
        "most comparable magnitude values. Frequency readings are position-independent, "
        "but relative magnitudes are not."
    ))
    parts.append(_row(
        "Damping Check with Decay Time",
        "The decay time (ring-out) appears in Results. A longer decay on the top plate "
        "typically correlates with lower internal damping &mdash; desirable in a soundboard. "
        "Compare braced vs. unbraced sections this way."
    ))
    parts.append(_row(
        "Air Mode for Setup",
        "The Helmholtz air resonance is easily produced by holding the assembled body near "
        "the microphone and clapping your palm over the sound hole. "
        "It does not require tapping the wood itself."
    ))
    parts.append(_row(
        "Comparing Guitar Measurements",
        "Save a measurement for each build stage or tap location with a descriptive label. "
        "Use the Measurements list Compare button to overlay 2&ndash;5 saved guitar "
        "measurements as colour-coded spectra on the main chart &mdash; ideal for tracking "
        "how bracing or finishing changes the resonant modes over time."
    ))
    parts.append(_row(
        "PDF Reports",
        "Each saved measurement can generate a PDF report containing the spectrum chart, "
        "peak table, and analysis summary. Open Measurements, select a measurement, then "
        "use the PDF export button."
    ))
    parts.append(_row(
        "Zooming the Spectrum",
        "Scroll over the chart to zoom &mdash; the axis depends on where the pointer is: "
        "over the plot area it zooms both axes; over the frequency axis (bottom) it zooms "
        "frequency only; over the magnitude axis (left) it zooms magnitude only. "
        "Drag to pan the same way. Modifier keys: Shift+Scroll &mdash; pan frequency; "
        "Alt+Scroll &mdash; pan magnitude; Cmd/Ctrl+Scroll &mdash; zoom both axes. "
        "To reset the axes, right-click anywhere inside the chart.",
        ["mdi.information"]
    ))

    # ── Glossary ──────────────────────────────────────────────────────────
    parts.append(_h2("mdi.book-open-outline", "Glossary"))
    parts.append(_row("Air (Helmholtz) mode",
        "The resonance of the air mass in the sound hole, analogous to blowing across a "
        "bottle. Typically 80&ndash;130&nbsp;Hz for classical guitar."))
    parts.append(_row("Top / Back mode",
        "The fundamental bending resonance of the top or back plate. The relationship "
        "between these and the Air mode strongly influences the low-frequency response "
        "of the instrument."))
    parts.append(_row("Q Factor",
        "Sharpness of a resonance peak. Q = frequency &divide; &minus;3&nbsp;dB bandwidth. "
        "A higher Q means lower internal damping and a longer, purer ring-out."))
    parts.append(_row("Specific Modulus (E/&rho;)",
        "Young&rsquo;s modulus divided by density. The single best predictor of tonewood "
        "quality because it determines how fast sound travels through the wood relative to "
        "its weight. Higher is better for soundboards."))
    parts.append(_row("Young&rsquo;s Modulus (E)",
        "A measure of how stiff the wood is along a given direction. E_L is along the "
        "grain; E_C is across. Reported in GPa."))
    parts.append(_row("Speed of Sound (c)",
        "How fast longitudinal sound waves travel through the wood: c = &radic;(E/&rho;). "
        "Sitka spruce averages &asymp;5500&nbsp;m/s along the grain."))
    parts.append(_row("Radiation Ratio (R)",
        "Sound radiation efficiency: R = c/&rho;. A higher value means the plate radiates "
        "sound more efficiently for its weight."))
    parts.append(_row("Cross/Long Ratio",
        "E_C &divide; E_L. A measure of wood anisotropy. For spruce guitar tops this "
        "typically falls between 0.04 and 0.08; lower values indicate stronger grain structure."))
    parts.append(_row("Tap Tone Ratio",
        "Top mode frequency &divide; Air mode frequency. A rough structural quality indicator "
        "for assembled guitars; values between 1.8 and 2.4 are typical for well-made instruments."))
    parts.append(_row("Gore Target Thickness",
        "A plate thickness prediction based on Gore Equation 4.5-7, derived from E_L, E_C, "
        "shear modulus G_LC, the wood density, and the guitar body dimensions. It targets a "
        "specified vibrational stiffness (f_vs) preset."))
    parts.append(_row("FLC Tap",
        "A diagonal-mode tap that excites the torsional resonance of the plate. Used to "
        "calculate the shear modulus G_LC for the Gore thickness formula. Hold the plate at "
        "the midpoint of one long edge and tap near the opposite corner "
        "(~22% from both the end and the side)."))
    parts.append(_row("Free-Free Beam",
        "The boundary condition assumed by the tap-tone formula. The plate ends are "
        "unsupported (free), which is approximated by holding the sample at one nodal point "
        "(22% from one end along the dimension being measured). The formula constant 22.37 "
        "comes from the first mode shape of a free-free Euler&ndash;Bernoulli beam."))
    parts.append(_row("FFT (Fast Fourier Transform)",
        "The algorithm that converts a time-domain audio signal into a frequency-domain "
        "spectrum. Guitar Tap uses a 65,536-point windowed FFT (Hann window) giving a "
        "frequency resolution of approximately 0.67&nbsp;Hz per bin at a 44.1&nbsp;kHz "
        "sample rate."))

    parts.append("</body></html>")
    return "".join(parts)


_HELP_HTML: str | None = None  # built lazily on first call to get_help_html()


def get_help_html() -> str:
    """Return the help HTML, building it on first call (requires QApplication)."""
    global _HELP_HTML
    if _HELP_HTML is None:
        _HELP_HTML = _build_help_html()
    return _HELP_HTML


class HelpDialog(QtWidgets.QDialog):
    """Non-modal help window with scrollable HTML content."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.Tool)
        self.setWindowTitle("Guitar Tap Help")
        self.resize(640, 700)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)

        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(get_help_html())
        layout.addWidget(browser)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
