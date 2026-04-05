"""
Spectrum chart gesture handlers.

Mirrors Swift's SpectrumView+GestureHandlers.swift — mouse press/move/scroll
event handlers that drive pan, zoom, and peak-selection interactions.

In Python, all gesture handling is implemented inside FftCanvas
(views/fft_canvas.py) as overridden Qt event methods:

  FftCanvas.wheelEvent          → Ctrl+scroll zoom, Shift+scroll pan
  FftCanvas.contextMenuEvent    → right-click: zoom-reset menu
  FftCanvas._on_mouse_moved     → cursor crosshair / frequency readout

Pending: if gesture handling is extracted into a separate class or event
filter, the implementation would move here.
"""
