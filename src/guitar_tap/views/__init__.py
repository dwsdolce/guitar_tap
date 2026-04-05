"""
Views package — mirrors Swift GuitarTap/Views/.

Sub-packages:
  shared/       → Views/Shared/   — reusable widgets
  measurements/ → Views/Measurements/ — measurement list / detail / export
  utilities/    → Views/Utilities/    — settings, file I/O, display constants
"""
from .tap_tone_analysis_view import MainWindow

__all__ = ["MainWindow"]
