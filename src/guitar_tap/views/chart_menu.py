# @parity view/chart-menu tests=test/chart-menu
"""
The chart's menu — from its ⋯ and from a right-click — and a peak label's own menu: what each item does, says
and shows. The views build their menus from these lists; the same lists are in every edition and in the shared
chart-menu.json. Mirrors Swift ``ChartMenu`` (Views/ChartMenu.swift).
"""

from __future__ import annotations

from typing import NamedTuple


class ChartMenuEntry(NamedTuple):
    """One item of the chart's menu, or of a peak label's. Mirrors Swift ``ChartMenuEntry``."""

    action: str
    title: str
    mdi: str  # the Material Design icon, as qtawesome names it without "mdi." — Swift's SF Symbol's nearest


# The chart's menu, in the groups a separator divides. "Reset Labels" can act only while a label has been moved.
GROUPS: list[list[ChartMenuEntry]] = [
    [
        ChartMenuEntry("resetBothToSaved", "Reset Both Axes to Saved", "restore"),
        ChartMenuEntry("resetFrequencyToSaved", "Reset Frequency Axis to Saved", "restore"),
        ChartMenuEntry("resetMagnitudeToSaved", "Reset Magnitude Axis to Saved", "restore"),
    ],
    [
        ChartMenuEntry("resetBothToDefaults", "Reset Both Axes to Defaults", "backup-restore"),
        ChartMenuEntry("resetFrequencyToDefaults", "Reset Frequency Axis to Defaults", "backup-restore"),
        ChartMenuEntry("resetMagnitudeToDefaults", "Reset Magnitude Axis to Defaults", "backup-restore"),
    ],
    [
        ChartMenuEntry("resetLabels", "Reset Labels", "undo"),
    ],
]

# The chart's menu while a comparison measurement is shown, in place of GROUPS: Settings' range and the app's
# defaults mean nothing for measurements of many guitars, so it resets to the comparison range — the span of the
# compared measurements' saved views, the range a comparison opens at. Mirrors Swift ``comparisonGroups``.
COMPARISON_GROUPS: list[list[ChartMenuEntry]] = [
    [
        ChartMenuEntry("resetBothToComparison", "Reset Both Axes to Comparison Range", "restore"),
        ChartMenuEntry("resetFrequencyToComparison", "Reset Frequency Axis to Comparison Range", "restore"),
        ChartMenuEntry("resetMagnitudeToComparison", "Reset Magnitude Axis to Comparison Range", "restore"),
    ],
]

# A peak label's menu: it can act only while the label has been moved.
LABEL_MENU: list[ChartMenuEntry] = [
    ChartMenuEntry("resetPosition", "Reset Position", "restore"),
]
