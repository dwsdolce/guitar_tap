"""
Combined peak row widget with inline mode selector.

Mirrors Swift's CombinedPeakModeRowView.swift — a single row that displays
peak frequency, magnitude, and an inline mode-assignment dropdown.

The Python implementation lives in peak_card_widget.py (PeakCardWidget /
PeakListWidget); this module re-exports those classes under the Swift-aligned
name for consistency with the views package structure.
"""

from views.shared.peak_card_widget import PeakCardWidget, PeakListWidget

__all__ = ["PeakCardWidget", "PeakListWidget"]
