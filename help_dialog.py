"""
    Help window — QDialog with QTextBrowser showing HTML reference content.
"""

from __future__ import annotations

from PyQt6 import QtWidgets, QtCore, QtGui

_HELP_HTML = """\
<!DOCTYPE html>
<html>
<head>
<style>
  body  { font-family: system-ui, sans-serif; font-size: 13px; margin: 16px; }
  h1    { font-size: 18px; margin-bottom: 4px; }
  h2    { font-size: 14px; margin-top: 16px; margin-bottom: 4px;
          border-bottom: 1px solid #ccc; padding-bottom: 2px; }
  h3    { font-size: 13px; margin-top: 12px; margin-bottom: 2px; }
  p, li { margin: 4px 0; line-height: 1.5; }
  code  { background: #f0f0f0; border-radius: 3px; padding: 1px 4px; }
  table { border-collapse: collapse; margin: 8px 0; width: 100%; }
  th    { background: #e8e8e8; text-align: left; padding: 4px 8px; }
  td    { padding: 3px 8px; border-bottom: 1px solid #eee; }
</style>
</head>
<body>

<h1>Guitar Tap — Reference</h1>
<p>Guitar Tap analyses the tap-tone resonances of acoustic guitar tops, backs,
and braces using a microphone and real-time FFT.</p>

<h2>Quick Start — Guitar Mode</h2>
<ol>
  <li>Select <b>Guitar</b> in the <em>Measurement type</em> combo.</li>
  <li>Tap the guitar body or plate firmly with a knuckle.</li>
  <li>The spectrum freezes automatically and peaks are identified.</li>
  <li>Edit the <b>Mode</b> column in the peaks table to assign labels.</li>
  <li>Click <b>New Tap</b> to release the hold and listen for the next tap.</li>
</ol>

<h2>Controls Reference</h2>

<h3>Measurement Type</h3>
<p>Selects the analysis pipeline:</p>
<ul>
  <li><b>Guitar</b> — live FFT peak detection with mode classification.</li>
  <li><b>Plate / Brace</b> — two-tap material property analysis (see below).</li>
</ul>

<h3>Hold Results</h3>
<p>Freezes the spectrum and enables table editing.  Turned on automatically
when a tap is detected.  Click <b>New Tap</b> to unfreeze.</p>

<h3>Guitar Type</h3>
<p>Controls the frequency bands used for automatic mode classification.
Choose Classical, Flamenco, or Acoustic.  Bands are displayed as coloured
regions on the spectrum when <em>Show mode bands</em> is enabled.</p>

<h3>Tap Detection Threshold</h3>
<p>Amplitude level (0–100) that triggers automatic hold.  Shown as an orange
dashed line on the spectrum.  Raise it if background noise causes false
triggers; lower it for quiet taps.</p>

<h3>Taps to Average</h3>
<p>Accumulate and average N consecutive taps before freezing.  Useful for
reducing measurement noise on very lively tops.</p>

<h3>Ring-out Time</h3>
<p>Time in seconds from the tap peak to a 15 dB drop.  A useful quality
indicator — longer ring-out generally means less damping.</p>

<h3>Spectrum Averaging</h3>
<p>Frame-level averaging over multiple FFT windows (distinct from tap-level
averaging).  Useful for steady-state signals such as speaker-driven excitation.</p>

<h3>Auto Scale dB</h3>
<p>Dynamically adjusts the Y axis so the spectrum floor sits near the bottom
of the view.</p>

<h3>Tap Tone Ratios</h3>
<p>Displays the frequency ratios between the three main corpus modes once
at least two of Helmholtz T(1,1)₁, Top T(1,1)₂, and Back T(1,1)₃ are
identified.  Ratios close to known target values indicate a well-tuned
instrument.</p>

<h2>Peaks Table</h2>
<table>
  <tr><th>Column</th><th>Meaning</th></tr>
  <tr><td>Show</td><td>Toggle annotation on the spectrum for this peak.</td></tr>
  <tr><td>Freq</td><td>Interpolated frequency (Hz).</td></tr>
  <tr><td>Mag</td><td>Magnitude at peak (dB FS).</td></tr>
  <tr><td>Q</td><td>Quality factor = f₀ / 3 dB bandwidth.  Higher = less damping.</td></tr>
  <tr><td>Pitch</td><td>Nearest MIDI note name (A4 = 440 Hz).</td></tr>
  <tr><td>Cents</td><td>Offset from nearest semiboundary (±50 = exactly between notes).</td></tr>
  <tr><td>Mode</td><td>Auto-classified guitar mode.  Click to override manually.</td></tr>
</table>

<h2>Guitar Modes</h2>
<table>
  <tr><th>Mode</th><th>Typical Range</th><th>Description</th></tr>
  <tr><td>Helmholtz T(1,1)₁</td><td>80–145 Hz</td><td>Air resonance of the body cavity.</td></tr>
  <tr><td>Top T(1,1)₂</td><td>140–260 Hz</td><td>Main top-plate bending mode.</td></tr>
  <tr><td>Back T(1,1)₃</td><td>185–325 Hz</td><td>Main back-plate bending mode.</td></tr>
  <tr><td>Cross Dipole T(2,1)</td><td>250–430 Hz</td><td>Cross-brace asymmetric mode.</td></tr>
  <tr><td>Long Dipole T(1,2)</td><td>330–540 Hz</td><td>Longitudinal bending mode.</td></tr>
  <tr><td>Quadrapole T(2,2)</td><td>430–720 Hz</td><td>Four-lobe plate mode.</td></tr>
  <tr><td>Cross Tripole T(3,1)</td><td>580–970 Hz</td><td>Three-lobe cross mode.</td></tr>
</table>
<p>Ranges are based on Trevor Gore's <em>Contemporary Acoustic Guitar Design
and Build</em> and are intentionally wide to accommodate natural variation.</p>

<h2>Microphone Calibration</h2>
<p>Guitar Tap supports UMIK-1 / REW <code>.cal</code> format calibration files.
Click <b>Import Calibration…</b> and select the file supplied with your
measurement microphone.  The calibration is stored per device and loaded
automatically on subsequent launches.</p>

<h2>Saving and Loading Measurements</h2>
<p>Click <b>Save Measurement</b> (available when results are held) to store
peaks, annotations, and display settings as a JSON file in
<code>~/Documents/GuitarTap/measurements/</code>.</p>
<p>Click <b>Measurements…</b> to browse, load, or delete saved measurements.
A measurement can also be imported from any location via the <em>Import…</em>
button in that dialog.</p>
<p>Click <b>Export PDF…</b> to generate a PDF report containing the spectrum
image and peaks table.</p>

<h2>Plate / Brace Analysis</h2>
<p>Select <b>Plate</b> or <b>Brace</b> in the Measurement type combo, then
click <b>Plate / Brace Analysis…</b> to open the analysis dialog.</p>
<ol>
  <li>Enter the specimen dimensions (L, W, T) and mass.</li>
  <li>Click <b>Start Analysis</b>.</li>
  <li>Tap the specimen along the long-grain (L) direction when prompted.</li>
  <li>When the L frequency is captured, tap the cross-grain (C) direction.</li>
  <li>Material properties are calculated and displayed automatically.</li>
</ol>
<p>The <b>target thickness</b> value shows how thick you would need to make
this wood to match the bending stiffness of a reference Sitka spruce top
at 2.7 mm.  Based on Gore Eq. 4.5-7.</p>

<h2>Keyboard Shortcuts</h2>
<table>
  <tr><th>Key</th><th>Action</th></tr>
  <tr><td>Cmd+?</td><td>Open this help window.</td></tr>
</table>

<h2>Audio Device Selection</h2>
<p>Click <b>Input Devices</b> to view all available input devices and select
one.  The selection is persisted across launches.  If your device is
disconnected while recording, a warning is shown and you can select a
replacement.</p>

</body>
</html>
"""


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
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
