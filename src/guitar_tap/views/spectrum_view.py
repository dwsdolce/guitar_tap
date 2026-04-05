"""
Spectrum chart view — chart content and axis configuration.

Mirrors Swift's SpectrumView.swift + SpectrumView+ChartContent.swift.

In Python, this responsibility is handled by FftCanvas (views/fft_canvas.py),
which is a pyqtgraph PlotWidget subclass.  This stub documents the mapping:

  FftCanvas             → SpectrumView (chart host + axis setup)
  FftCanvas.update_axis → SpectrumView axis range updates
  FftCanvas.set_draw_data → SpectrumView chart content rendering

Pending: if the spectrum view is ever decoupled from the processing thread
coordination, chart-only drawing methods could be extracted here.
"""

# The implementation lives in views/fft_canvas.py — FftCanvas class.
from views.fft_canvas import FftCanvas

__all__ = ["FftCanvas"]
