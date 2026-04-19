"""
FFTAnalysisMetricsView — full-detail FFT analysis metrics and performance
diagnostics panel.

Mirrors Swift's FFTAnalysisMetricsView.swift.

Presented as a non-modal QDialog on demand from the Metrics toolbar button
in MainWindow. Organised into four QGroupBox sections:

| Section               | Metrics                                              |
|-----------------------|------------------------------------------------------|
| Analysis Configuration| Frequency resolution (Hz/bin), bin count, sample     |
|                       | rate (Hz), bandwidth, sample length, frame rate      |
| Performance           | Processing time (last frame), average processing     |
|                       | (30-frame), CPU usage                                |
| Peak Detection        | Dominant frequency (Hz), magnitude (dB)              |
| Status                | Running / Stopped indicator                          |

All dynamic values are updated via update() which is called from the
framerateUpdate signal emitted by FftCanvas (mirrors @ObservedObject binding
that keeps the SwiftUI view live while the analyzer is running).

- SeeAlso: ``CompactFFTMetricsOverlay`` (Swift-only Preview helper, not ported)
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from views.fft_canvas import FftCanvas


# ---------------------------------------------------------------------------
# MetricRow — reusable row component (mirrors Swift MetricRow)
# ---------------------------------------------------------------------------

class MetricRow:
    """A reusable row displaying a labelled metric value.

    Mirrors Swift ``MetricRow`` — label + subtitle on the left, monospaced
    value on the right.  Returns the layout and the value label so callers
    can update the value label reactively.
    """

    def __init__(
        self,
        label: str,
        subtitle: str,
        value: str = "—",
        sub_font: QtGui.QFont | None = None,
        mono_font: QtGui.QFont | None = None,
    ) -> None:
        self._layout = QtWidgets.QHBoxLayout()
        self._layout.setContentsMargins(0, 2, 0, 2)

        # Left side: label (subheadline) + subtitle (caption, secondary colour)
        lv = QtWidgets.QVBoxLayout()
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(1)
        lv.addWidget(QtWidgets.QLabel(label))
        sub = QtWidgets.QLabel(subtitle)
        if sub_font:
            sub.setFont(sub_font)
        sub.setStyleSheet("color: gray")
        lv.addWidget(sub)
        self._layout.addLayout(lv)
        self._layout.addStretch()

        # Right side: monospaced bold value
        self.value_label = QtWidgets.QLabel(value)
        if mono_font:
            self.value_label.setFont(mono_font)
        self.value_label.setStyleSheet("font-weight: bold")
        self._layout.addWidget(self.value_label)

    @property
    def layout(self) -> QtWidgets.QHBoxLayout:
        return self._layout

    def set_value(self, text: str, color: str = "") -> None:
        """Update the displayed value and optional colour."""
        self.value_label.setText(text)
        style = "font-weight: bold"
        if color:
            style += f"; color: {color}"
        self.value_label.setStyleSheet(style)


# ---------------------------------------------------------------------------
# FFTAnalysisMetricsView — mirrors Swift FFTAnalysisMetricsView
# ---------------------------------------------------------------------------

class FFTAnalysisMetricsView(QtWidgets.QDialog):
    """Full-detail FFT analysis metrics and performance diagnostics panel.

    Mirrors Swift ``FFTAnalysisMetricsView``.

    In Python the view is a non-modal QDialog rather than a SwiftUI sheet.
    Dynamic values are updated by calling ``update_metrics()`` from the
    ``framerateUpdate`` signal handler in MainWindow, mirroring the reactive
    @ObservedObject binding in the Swift implementation.
    """

    def __init__(self, canvas: "FftCanvas", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas

        # Rolling 30-frame average of processing time (mirrors Swift avgProcessingTimeMs)
        self._proc_times: deque[float] = deque(maxlen=30)

        self.setWindowTitle("FFT Analysis Metrics")
        self.setMinimumWidth(380)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        # Sub-fonts (mirrors SwiftUI .caption / .system(.body, design: .monospaced))
        self._sub_font = QtGui.QFont(self.font())
        self._sub_font.setPointSize(max(8, self._sub_font.pointSize() - 2))
        self._mono_font = QtGui.QFont(self.font())
        self._mono_font.setFamily("Courier New")
        self._mono_font.setStyleHint(QtGui.QFont.StyleHint.Monospace)

        self._build_ui()

    # MARK: - UI Construction

    def _build_ui(self) -> None:
        """Construct the dialog layout, mirroring Swift body."""
        sr       = float(self._canvas.analyzer.mic.rate)    # mirrors Swift RealtimeFFTAnalyzer.sampleRate
        fft_size = self._canvas.analyzer.mic.fft_size       # mirrors Swift RealtimeFFTAnalyzer.fftSize
        spectral_res = sr / fft_size             # mirrors Swift frequencyResolution = sampleRate / fftSize
        bandwidth    = sr / 2                    # mirrors Swift bandwidth (0 Hz to Nyquist)
        sample_len   = fft_size / sr             # mirrors Swift sampleLengthSeconds = fftSize / sampleRate
        bin_count    = fft_size // 2             # mirrors Swift frequencies.count = fftSize / 2

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # ── Analysis Configuration ─────────────────────────────────────────
        # Mirrors Swift GroupBox("Analysis Configuration") { ... }
        self._row_freq_res   = MetricRow("Frequency Resolution", "Hz per bin",
                                         self._fmt_freq(spectral_res),
                                         self._sub_font, self._mono_font)
        self._row_bin_count  = MetricRow("Bin Count", "FFT output bins (guitar mode only)",
                                         f"{bin_count:,}",
                                         self._sub_font, self._mono_font)
        self._row_sample_rate = MetricRow("Sample Rate", "Hardware capture rate",
                                          f"{sr:,.0f} Hz",
                                          self._sub_font, self._mono_font)
        self._row_bandwidth  = MetricRow("Bandwidth", "0 Hz to Nyquist",
                                         self._fmt_freq(bandwidth),
                                         self._sub_font, self._mono_font)
        self._row_sample_len = MetricRow("Sample Length", "Time window duration",
                                         f"{sample_len:.2f} s",
                                         self._sub_font, self._mono_font)
        self._row_frame_rate = MetricRow("Frame Rate", "FFT calculations/sec",
                                         sub_font=self._sub_font, mono_font=self._mono_font)
        outer.addWidget(self._group("Analysis Configuration", [
            self._row_freq_res,
            self._row_bin_count,
            self._row_sample_rate,
            self._row_bandwidth,
            self._row_sample_len,
            self._row_frame_rate,
        ]))

        # ── Performance ────────────────────────────────────────────────────
        # Mirrors Swift GroupBox("Performance") { ... }
        self._row_proc_time = MetricRow("Processing Time", "Last frame",
                                        sub_font=self._sub_font, mono_font=self._mono_font)
        self._row_avg_proc  = MetricRow("Average Processing", "30-frame average",
                                        sub_font=self._sub_font, mono_font=self._mono_font)
        self._row_cpu       = MetricRow("CPU Usage", "Of available frame time",
                                        sub_font=self._sub_font, mono_font=self._mono_font)
        outer.addWidget(self._group("Performance", [
            self._row_proc_time,
            self._row_avg_proc,
            self._row_cpu,
        ]))

        # ── Peak Detection ─────────────────────────────────────────────────
        # Mirrors Swift GroupBox("Peak Detection") { ... }
        self._row_peak_freq = MetricRow("Peak Frequency", "Dominant frequency",
                                        sub_font=self._sub_font, mono_font=self._mono_font)
        self._row_peak_mag  = MetricRow("Peak Magnitude", "Signal strength",
                                        sub_font=self._sub_font, mono_font=self._mono_font)
        outer.addWidget(self._group("Peak Detection", [
            self._row_peak_freq,
            self._row_peak_mag,
        ]))

        # ── Status indicator ───────────────────────────────────────────────
        # Mirrors Swift HStack { Circle().fill(isRunning ? .green : .gray) ... }
        status_row = QtWidgets.QHBoxLayout()
        self._status_dot = QtWidgets.QLabel("●")
        self._status_dot.setFont(self._sub_font)
        status_row.addWidget(self._status_dot)
        self._status_label = QtWidgets.QLabel("Stopped")
        self._status_label.setFont(self._sub_font)
        self._status_label.setStyleSheet("color: gray")
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        outer.addLayout(status_row)

        close_btn = QtWidgets.QPushButton("Done")
        close_btn.clicked.connect(self.accept)
        outer.addWidget(close_btn)

    def _group(self, title: str, rows: list[MetricRow]) -> QtWidgets.QGroupBox:
        """Build a titled QGroupBox from a list of MetricRows with dividers.

        Mirrors Swift GroupBox(title) { VStack { ... Divider() ... } }.
        """
        grp = QtWidgets.QGroupBox(title)
        vl = QtWidgets.QVBoxLayout(grp)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(4)
        for i, row in enumerate(rows):
            vl.addLayout(row.layout)
            if i < len(rows) - 1:
                div = QtWidgets.QFrame()
                div.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                div.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
                vl.addWidget(div)
        return grp

    # MARK: - Helper Functions

    def _fmt_freq(self, hz: float) -> str:
        """Format a frequency value with appropriate units (Hz or kHz).

        Mirrors Swift ``formatFrequency(_:)``.
        """
        if hz >= 1000:
            return f"{hz / 1000:.2f} kHz"
        return f"{hz:.1f} Hz"

    def _processing_time_color(self, time_ms: float, frame_time_ms: float) -> str:
        """Return a CSS colour string indicating processing time health.

        Mirrors Swift ``processingTimeColor(_:)``::

            Green  — fast   (< 50 % of frame time)
            Yellow — moderate (50–80 %)
            Orange — high   (80–95 %)
            Red    — critical (> 95 %)
        """
        ratio = time_ms / frame_time_ms if frame_time_ms > 0 else 0
        if ratio < 0.5:
            return "green"
        if ratio < 0.8:
            return "orange"
        if ratio < 0.95:
            return "darkorange"
        return "red"

    def _cpu_usage_color(self, usage: float) -> str:
        """Return a CSS colour string indicating CPU usage level.

        Mirrors Swift ``cpuUsageColor(_:)``.
        """
        if usage < 50:
            return "green"
        if usage < 80:
            return "orange"
        if usage < 95:
            return "darkorange"
        return "red"

    # MARK: - Reactive Update

    def update_metrics(
        self,
        framerate: float,
        processing_time: float,
        is_running: bool,
        peaks: "np.ndarray",
    ) -> None:
        """Refresh all dynamic metric values.

        Called from the ``framerateUpdate`` signal handler, mirroring the
        automatic re-render triggered by @ObservedObject in SwiftUI.

        Args:
            framerate:       Current FFT frame rate in Hz.
                             Mirrors Swift ``analyzer.frameRate``.
            processing_time: Last-frame processing time in seconds.
                             Mirrors Swift ``analyzer.processingTimeMs / 1000``.
            is_running:      Whether the analyzer is currently capturing.
                             Mirrors Swift ``analyzer.isRunning``.
            peaks:           Current peaks array (N×3: freq, mag, Q).
                             Used to derive peakFrequency / peakMagnitude,
                             mirroring Swift ``analyzer.peakFrequency`` /
                             ``analyzer.peakMagnitude``.
        """
        if not self.isVisible():
            return

        # Maintain rolling 30-frame average (mirrors Swift avgProcessingTimeMs)
        proc_ms = processing_time * 1000
        self._proc_times.append(proc_ms)
        avg_ms = sum(self._proc_times) / len(self._proc_times)

        frame_time_ms = (1000.0 / framerate) if framerate > 0 else 100.0

        # CPU headroom (mirrors Swift let cpuUsage = avgProcessingTimeMs / frameTimeMs * 100)
        cpu_pct = (avg_ms / frame_time_ms) * 100

        # ── Analysis Configuration (dynamic row only) ──────────────────────
        self._row_frame_rate.set_value(f"{framerate:.1f} Hz")

        # ── Performance ────────────────────────────────────────────────────
        proc_color = self._processing_time_color(proc_ms, frame_time_ms)
        avg_color  = self._processing_time_color(avg_ms, frame_time_ms)
        cpu_color  = self._cpu_usage_color(cpu_pct)

        self._row_proc_time.set_value(f"{proc_ms:.3f} ms", proc_color)
        self._row_avg_proc.set_value(f"{avg_ms:.3f} ms", avg_color)
        self._row_cpu.set_value(f"{cpu_pct:.1f}%", cpu_color)

        # ── Peak Detection ─────────────────────────────────────────────────
        # Derives peakFrequency / peakMagnitude from peaks array.
        # Mirrors Swift analyzer.peakFrequency / analyzer.peakMagnitude.
        if peaks.ndim == 2 and peaks.shape[0] > 0:
            best = int(np.argmax(peaks[:, 1]))
            self._row_peak_freq.set_value(f"{peaks[best, 0]:.1f} Hz")
            self._row_peak_mag.set_value(f"{peaks[best, 1]:.1f} dB")
        else:
            self._row_peak_freq.set_value("—")
            self._row_peak_mag.set_value("—")

        # ── Status indicator ───────────────────────────────────────────────
        # Mirrors Swift Circle().fill(analyzer.isRunning ? .green : .gray)
        if is_running:
            self._status_dot.setStyleSheet("color: green")
            self._status_label.setText("Analyzing")
        else:
            self._status_dot.setStyleSheet("color: gray")
            self._status_label.setText("Stopped")
