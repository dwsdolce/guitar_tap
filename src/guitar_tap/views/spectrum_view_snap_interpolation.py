"""
Spectrum cursor snap-to-peak interpolation.

Mirrors Swift's SpectrumView+SnapInterpolation.swift — logic to snap the
cursor readout to the nearest peak bin using parabolic interpolation.

The Python equivalent in FftCanvas (views/fft_canvas.py) provides a basic
nearest-bin snap via pyqtgraph's crosshair proxy.  Full parabolic
interpolation matching the Swift implementation is marked as a gap in
VIEWS_STRUCTURE.md.

Pending: extract / implement snap interpolation logic from fft_canvas.py and
extend it to match the Swift SpectrumView+SnapInterpolation behaviour.
"""
