"""
FFT analysis metrics display.

Mirrors Swift's FFTAnalysisMetricsView.swift — a compact overlay or panel
showing real-time performance metrics: FPS, processing dt, sample rate, and
buffer occupancy.

In Python, these metrics are reported via the FftProcessingThread signals
(fftFrameReady carries fps, sample_dt, processing_dt) and displayed in a
small dialog (MainWindow._show_metrics_dialog) rather than as an overlay.

Pending: extract the metrics dialog and its update logic from
tap_tone_analysis_view.MainWindow into this module.
"""
