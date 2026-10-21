# @parity view/spectrum-gestures
"""
Spectrum chart gesture handlers.

Mirrors Swift's SpectrumView+GestureHandlers.swift — mouse press/move/scroll
event handlers that drive pan, zoom, and peak-selection interactions.

In Python, all gesture handling is implemented inside FftCanvas
(views/fft_canvas.py) as overridden Qt event methods:

  FftCanvas.wheelEvent          → scroll by region; ⌘/Ctrl+scroll zoom around the cursor; Shift / Alt+scroll pan
  FftCanvas.viewportEvent       → a trackpad pinch (macOS), by region
  FftCanvas._pointer_region     → where a point is: the plot, the frequency axis, the magnitude axis, outside
  FftCanvas.contextMenuEvent    → right-click: the chart menu
  FftCanvas._on_mouse_moved     → the cursor's shape, the crosshair and the frequency readout

Pending: if gesture handling is extracted into a separate class or event
filter, the implementation would move here.
"""
