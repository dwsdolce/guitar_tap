"""
AnalysisDisplayMode — authoritative display-mode enum for the main spectrum view.

Mirrors Swift AnalysisDisplayMode defined at file scope in TapToneAnalyzer.swift.

In Swift, AnalysisDisplayMode is declared at the top of TapToneAnalyzer.swift
(before the class).  In Python it lives here in its own file because:

  - tap_tone_analyzer.py imports its mixin modules
  - Those mixin modules need AnalysisDisplayMode
  - If AnalysisDisplayMode were defined in tap_tone_analyzer.py, the mixins
    could not import it without creating a circular dependency.

Python consumers should import from here directly:
    from models.analysis_display_mode import AnalysisDisplayMode
or via the tap_tone_analyzer module which re-exports it:
    from models.tap_tone_analyzer import AnalysisDisplayMode
"""

from __future__ import annotations

from enum import Enum, auto


class AnalysisDisplayMode(Enum):
    """Authoritative display mode for the main spectrum view.

    All UI sections and analyzer methods that differ between live, frozen,
    and comparison modes switch on this value rather than checking
    _comparison_data or similar derived state directly.

    Mirrors Swift AnalysisDisplayMode (TapToneAnalyzer.swift).
    """

    # MARK: - Cases

    # Live FFT; tap detection is active or waiting for a tap.
    # Mirrors Swift AnalysisDisplayMode.live.
    LIVE = auto()

    # A single frozen or loaded measurement is displayed; tap detection is idle.
    # Mirrors Swift AnalysisDisplayMode.frozen.
    FROZEN = auto()

    # Two or more saved measurements are overlaid for comparison.
    # Tap detection is idle.
    # Mirrors Swift AnalysisDisplayMode.comparison.
    COMPARISON = auto()
