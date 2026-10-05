# @parity view/palette tests=test/theme,test/analysis-quality
"""Every colour the app draws itself, as a functional role.

A role names what the colour is for (secondary text, the fL curve, the Peak Min line) and has one light value and
one dark value; two roles may share a value without being linked. The values are pinned rather than taken from a
platform palette, so every edition shows the same colours on every OS. The colour only tells values apart; the exact
shade does not matter, but it must be the same everywhere. Exports are drawn on white, so they use the light values.
Mirrors Swift ``Palette``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6 import QtGui, QtWidgets


@dataclass(frozen=True)
class ColorPair:
    """A colour's two values, as "#RRGGBB", or "#RRGGBBAA" when the role has an opacity."""

    light: str
    dark: str

    def on(self, widget: QtWidgets.QWidget) -> str:
        """The value for the background ``widget`` is drawn on: dark when its window is dark."""
        window = widget.palette().color(QtGui.QPalette.ColorRole.Window)
        return self.dark if window.lightness() < 128 else self.light


class Role(Enum):
    """A colour's purpose. The value is the role's name in the theme table."""

    BACKGROUND_WINDOW = "background.window"
    BACKGROUND_PANEL = "background.panel"
    BACKGROUND_CONTROL = "background.control"
    BACKGROUND_SUBTLE = "background.subtle"
    SEPARATOR = "separator"
    TEXT_PRIMARY = "text.primary"
    TEXT_SECONDARY = "text.secondary"
    ACCENT = "accent"
    ACCENT_TEXT = "accent.text"
    SCRIM = "scrim"
    CHART_BACKGROUND = "chart.background"
    CHART_GRID = "chart.grid"
    CHART_BORDER = "chart.border"
    CHART_AXIS = "chart.axis"
    CHART_TITLE = "chart.title"
    CHART_SPECTRUM = "chart.spectrum"
    CHART_CROSSHAIR_LINE = "chart.crosshair.line"
    CHART_CROSSHAIR_FREQUENCY = "chart.crosshair.frequency"
    CHART_READOUT_BACKGROUND = "chart.readout.background"
    CHART_PEAK_MIN = "chart.peakMin"
    CHART_HIGHLIGHTED_PEAK = "chart.highlightedPeak"
    MODE_AIR = "mode.air"
    MODE_TOP = "mode.top"
    MODE_BACK = "mode.back"
    MODE_DIPOLE = "mode.dipole"
    MODE_RING = "mode.ring"
    MODE_UPPER = "mode.upper"
    MODE_UNKNOWN = "mode.unknown"
    MODE_USER_DEFINED = "mode.userDefined"
    MATERIAL_LONGITUDINAL = "material.longitudinal"
    MATERIAL_CROSS = "material.cross"
    MATERIAL_FLC = "material.flc"
    MATERIAL_UNSELECTED = "material.unselected"
    PHASE_NOT_STARTED = "phase.notStarted"
    PHASE_COMPLETE = "phase.complete"
    PEAK_MAGNITUDE_STRONG = "peak.magnitude.strong"
    PEAK_MAGNITUDE_MODERATE = "peak.magnitude.moderate"
    PEAK_MAGNITUDE_WEAK = "peak.magnitude.weak"
    PEAK_MAGNITUDE_FAINT = "peak.magnitude.faint"
    PEAK_PITCH = "peak.pitch"
    PEAK_SELECTED_STAR = "peak.selectedStar"
    PEAK_UNSELECTED_STAR = "peak.unselectedStar"
    PEAK_IN_RANGE = "peak.inRange"
    PEAK_OUT_OF_RANGE = "peak.outOfRange"
    QUALITY_GRAY = "quality.gray"
    QUALITY_ORANGE = "quality.orange"
    QUALITY_YELLOW = "quality.yellow"
    QUALITY_GREEN = "quality.green"
    QUALITY_BLUE = "quality.blue"
    QUALITY_RED = "quality.red"
    WOOD_EXCELLENT = "wood.excellent"
    WOOD_VERY_GOOD = "wood.veryGood"
    WOOD_GOOD = "wood.good"
    WOOD_FAIR = "wood.fair"
    WOOD_POOR = "wood.poor"
    SERIES_1 = "series.1"
    SERIES_2 = "series.2"
    SERIES_3 = "series.3"
    SERIES_4 = "series.4"
    SERIES_5 = "series.5"
    SERIES_6 = "series.6"
    SERIES_7 = "series.7"
    SERIES_8 = "series.8"
    SERIES_9 = "series.9"
    SERIES_10 = "series.10"
    SERIES_AVERAGE = "series.average"
    STATUS_RUNNING = "status.running"
    STATUS_TAP_DETECTED = "status.tapDetected"
    STATUS_COMPLETE = "status.complete"
    STATUS_STOPPED = "status.stopped"
    STATUS_IDLE = "status.idle"
    STATUS_PAUSED = "status.paused"
    STATUS_FROZEN = "status.frozen"
    STATUS_WARNING = "status.warning"
    STATUS_PLAYING_FILE = "status.playingFile"
    STATUS_INFO = "status.info"
    STATUS_SAVED = "status.saved"
    STATUS_PROGRESS = "status.progress"
    STATUS_TAP_COUNT = "status.tapCount"
    STATUS_PEAK_READOUT = "status.peakReadout"
    STATUS_ERROR = "status.error"
    METER_GROOVE = "meter.groove"
    METER_GROOVE_BORDER = "meter.grooveBorder"
    METER_LEVEL_TOP = "meter.levelTop"
    METER_LEVEL_MIDDLE = "meter.levelMiddle"
    METER_LEVEL_BOTTOM = "meter.levelBottom"
    METER_CLIP = "meter.clip"
    METER_TICKS = "meter.ticks"
    METER_PEAK_HOLD = "meter.peakHold"
    METER_THRESHOLD_HANDLE = "meter.thresholdHandle"
    METER_THRESHOLD_HANDLE_BORDER = "meter.thresholdHandleBorder"
    METRIC_GOOD = "metric.good"
    METRIC_FAIR = "metric.fair"
    METRIC_HIGH = "metric.high"
    METRIC_OVERLOAD = "metric.overload"
    PDF_ACCENT = "pdf.accent"
    PDF_TEXT = "pdf.text"
    PDF_SECONDARY = "pdf.secondary"
    PDF_DIVIDER = "pdf.divider"
    PDF_BOX = "pdf.box"
    PDF_PILL = "pdf.pill"
    PDF_GORE_BOX = "pdf.goreBox"
    PDF_CHART_MATTE = "pdf.chartMatte"


class Opacity(Enum):
    """An opacity applied to another role's colour (the peak-row tint over its mode colour)."""

    PEAK_ROW_TINT = "peak.rowTint"
    STATUS_MESSAGE_BACKGROUND = "status.messageBackground"


PAIRS: dict[Role, ColorPair] = {
    Role.BACKGROUND_WINDOW: ColorPair("#F2F2F7", "#0B0E13"),
    Role.BACKGROUND_PANEL: ColorPair("#FFFFFF", "#141A22"),
    Role.BACKGROUND_CONTROL: ColorPair("#FFFFFF", "#11161D"),
    Role.BACKGROUND_SUBTLE: ColorPair("#8E8E9314", "#8E8E931A"),
    Role.SEPARATOR: ColorPair("#D8DEE6", "#222A33"),
    Role.TEXT_PRIMARY: ColorPair("#1A2330", "#E7EBF0"),
    Role.TEXT_SECONDARY: ColorPair("#6B7785", "#8A96A5"),
    Role.ACCENT: ColorPair("#007AFF", "#0A84FF"),
    Role.ACCENT_TEXT: ColorPair("#007AFF", "#409CFF"),
    Role.SCRIM: ColorPair("#0000004D", "#00000080"),
    Role.CHART_BACKGROUND: ColorPair("#FFFFFF", "#0E1116"),
    Role.CHART_GRID: ColorPair("#E3E8EE", "#1C242E"),
    Role.CHART_BORDER: ColorPair("#C2CAD4", "#2A3543"),
    Role.CHART_AXIS: ColorPair("#6B7785", "#8A97A6"),
    Role.CHART_TITLE: ColorPair("#1A2330", "#DFE4EA"),
    Role.CHART_SPECTRUM: ColorPair("#FF3B30", "#FF453A"),
    Role.CHART_CROSSHAIR_LINE: ColorPair("#5A646E80", "#96A0AA8C"),
    Role.CHART_CROSSHAIR_FREQUENCY: ColorPair("#FF3B30", "#FF453A"),
    Role.CHART_READOUT_BACKGROUND: ColorPair("#FFFFFFF5", "#141921EB"),
    Role.CHART_PEAK_MIN: ColorPair("#34C759", "#30D158"),
    Role.CHART_HIGHLIGHTED_PEAK: ColorPair("#FF3B30", "#FF453A"),
    Role.MODE_AIR: ColorPair("#00B0DC", "#64D2FF"),
    Role.MODE_TOP: ColorPair("#269342", "#30D158"),
    Role.MODE_BACK: ColorPair("#BB6D00", "#FF9F0A"),
    Role.MODE_DIPOLE: ColorPair("#FF3B30", "#FF453A"),
    Role.MODE_RING: ColorPair("#AF52DE", "#BF5AF2"),
    Role.MODE_UPPER: ColorPair("#A2845E", "#AC8E68"),
    Role.MODE_UNKNOWN: ColorPair("#8E8E93", "#8E8E93"),
    Role.MODE_USER_DEFINED: ColorPair("#5856D6", "#7D7AFF"),
    Role.MATERIAL_LONGITUDINAL: ColorPair("#007AFF", "#0A84FF"),
    Role.MATERIAL_CROSS: ColorPair("#FF9500", "#FF9F0A"),
    Role.MATERIAL_FLC: ColorPair("#AF52DE", "#BF5AF2"),
    Role.MATERIAL_UNSELECTED: ColorPair("#6B7785", "#8A96A5"),
    Role.PHASE_NOT_STARTED: ColorPair("#8E8E93", "#8E8E93"),
    Role.PHASE_COMPLETE: ColorPair("#34C759", "#30D158"),
    Role.PEAK_MAGNITUDE_STRONG: ColorPair("#34C759", "#30D158"),
    Role.PEAK_MAGNITUDE_MODERATE: ColorPair("#007AFF", "#0A84FF"),
    Role.PEAK_MAGNITUDE_WEAK: ColorPair("#FF9500", "#FF9F0A"),
    Role.PEAK_MAGNITUDE_FAINT: ColorPair("#FF3B30", "#FF453A"),
    Role.PEAK_PITCH: ColorPair("#AF52DE", "#BF5AF2"),
    Role.PEAK_SELECTED_STAR: ColorPair("#007AFF", "#0A84FF"),
    Role.PEAK_UNSELECTED_STAR: ColorPair("#6B7785", "#8A96A5"),
    Role.PEAK_IN_RANGE: ColorPair("#34C759", "#30D158"),
    Role.PEAK_OUT_OF_RANGE: ColorPair("#FF9500", "#FF9F0A"),
    Role.QUALITY_GRAY: ColorPair("#8E8E93", "#8E8E93"),
    Role.QUALITY_ORANGE: ColorPair("#FF9500", "#FF9F0A"),
    Role.QUALITY_YELLOW: ColorPair("#FFCC00", "#FFD60A"),
    Role.QUALITY_GREEN: ColorPair("#34C759", "#30D158"),
    Role.QUALITY_BLUE: ColorPair("#007AFF", "#0A84FF"),
    Role.QUALITY_RED: ColorPair("#FF3B30", "#FF453A"),
    Role.WOOD_EXCELLENT: ColorPair("#34C759", "#30D158"),
    Role.WOOD_VERY_GOOD: ColorPair("#00C7BE", "#63E6E2"),
    Role.WOOD_GOOD: ColorPair("#007AFF", "#0A84FF"),
    Role.WOOD_FAIR: ColorPair("#FF9500", "#FF9F0A"),
    Role.WOOD_POOR: ColorPair("#FF3B30", "#FF453A"),
    Role.SERIES_1: ColorPair("#007AFF", "#0A84FF"),
    Role.SERIES_2: ColorPair("#E07800", "#FF9F0A"),
    Role.SERIES_3: ColorPair("#269342", "#30D158"),
    Role.SERIES_4: ColorPair("#AF52DE", "#BF5AF2"),
    Role.SERIES_5: ColorPair("#0090B0", "#64D2FF"),
    Role.SERIES_6: ColorPair("#E0302A", "#FF453A"),
    Role.SERIES_7: ColorPair("#D6177A", "#FF6FB5"),
    Role.SERIES_8: ColorPair("#8B6A42", "#C29A6B"),
    Role.SERIES_9: ColorPair("#7A8A00", "#B8D430"),
    Role.SERIES_10: ColorPair("#5E6B7A", "#A8B4C2"),
    Role.SERIES_AVERAGE: ColorPair("#EBC300", "#FFD900"),
    Role.STATUS_RUNNING: ColorPair("#34C759", "#30D158"),
    Role.STATUS_TAP_DETECTED: ColorPair("#34C759", "#30D158"),
    Role.STATUS_COMPLETE: ColorPair("#34C759", "#30D158"),
    Role.STATUS_STOPPED: ColorPair("#8E8E93", "#8E8E93"),
    Role.STATUS_IDLE: ColorPair("#8E8E93", "#8E8E93"),
    Role.STATUS_PAUSED: ColorPair("#FF9500", "#FF9F0A"),
    Role.STATUS_FROZEN: ColorPair("#FF9500", "#FF9F0A"),
    Role.STATUS_WARNING: ColorPair("#FF9500", "#FF9F0A"),
    Role.STATUS_PLAYING_FILE: ColorPair("#FF9500", "#FF9F0A"),
    Role.STATUS_INFO: ColorPair("#007AFF", "#0A84FF"),
    Role.STATUS_SAVED: ColorPair("#007AFF", "#0A84FF"),
    Role.STATUS_PROGRESS: ColorPair("#007AFF", "#0A84FF"),
    Role.STATUS_TAP_COUNT: ColorPair("#007AFF", "#0A84FF"),
    Role.STATUS_PEAK_READOUT: ColorPair("#007AFF", "#0A84FF"),
    Role.STATUS_ERROR: ColorPair("#FF3B30", "#FF453A"),
    Role.METER_GROOVE: ColorPair("#EBEBEB", "#0A0D12"),
    Role.METER_GROOVE_BORDER: ColorPair("#8E8E9399", "#8E8E9373"),
    Role.METER_LEVEL_TOP: ColorPair("#66CCFF", "#66CCFF"),
    Role.METER_LEVEL_MIDDLE: ColorPair("#0066CC", "#0066CC"),
    Role.METER_LEVEL_BOTTOM: ColorPair("#001E50", "#001E50"),
    Role.METER_CLIP: ColorPair("#FF3B30D9", "#FF453AD9"),
    Role.METER_TICKS: ColorPair("#3D8C3DB3", "#3D8C3DB3"),
    Role.METER_PEAK_HOLD: ColorPair("#FFD900", "#FFD900"),
    Role.METER_THRESHOLD_HANDLE: ColorPair("#FF3B30", "#FF453A"),
    Role.METER_THRESHOLD_HANDLE_BORDER: ColorPair("#800000", "#800000"),
    Role.METRIC_GOOD: ColorPair("#34C759", "#30D158"),
    Role.METRIC_FAIR: ColorPair("#FFCC00", "#FFD60A"),
    Role.METRIC_HIGH: ColorPair("#FF9500", "#FF9F0A"),
    Role.METRIC_OVERLOAD: ColorPair("#FF3B30", "#FF453A"),
    Role.PDF_ACCENT: ColorPair("#2659BF", "#2659BF"),
    Role.PDF_TEXT: ColorPair("#1C1C1E", "#1C1C1E"),
    Role.PDF_SECONDARY: ColorPair("#787880", "#787880"),
    Role.PDF_DIVIDER: ColorPair("#D2D2D4", "#D2D2D4"),
    Role.PDF_BOX: ColorPair("#F2F2F4", "#F2F2F4"),
    Role.PDF_PILL: ColorPair("#ECECEE", "#ECECEE"),
    Role.PDF_GORE_BOX: ColorPair("#F7F9FD", "#F7F9FD"),
    Role.PDF_CHART_MATTE: ColorPair("#0D0D0D", "#0D0D0D"),
}

OPACITIES: dict[Opacity, tuple[float, float]] = {
    Opacity.PEAK_ROW_TINT: (0.10, 0.20),
    Opacity.STATUS_MESSAGE_BACKGROUND: (0.12, 0.12),
}


def pair(role: Role) -> ColorPair:
    """The light and dark values of ``role``."""
    return PAIRS[role]


GRAY = PAIRS[Role.QUALITY_GRAY]
ORANGE = PAIRS[Role.QUALITY_ORANGE]
YELLOW = PAIRS[Role.QUALITY_YELLOW]
GREEN = PAIRS[Role.QUALITY_GREEN]
BLUE = PAIRS[Role.QUALITY_BLUE]
RED = PAIRS[Role.QUALITY_RED]
