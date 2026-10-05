# @parity view/palette tests=test/theme,test/analysis-quality,test/mode-colors,test/quality-colors
"""Every colour the app draws itself, as a functional role.

A role names what the colour is for (secondary text, the fL curve, the Peak Min line) and has one
light value and one dark value; two roles may share a value without being linked. The values are
pinned rather than taken from a platform palette, so every edition shows the same colours on every
OS. The colour only tells values apart; the exact shade does not matter, but it must be the same
everywhere. Exports are drawn on white, so they use the light values. Mirrors Swift ``Palette``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models.appearance import Appearance, Scheme
from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.models.material_properties import WoodQuality


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


_MODE_ROLES: dict[GuitarMode, Role] = {
    GuitarMode.AIR: Role.MODE_AIR,
    GuitarMode.TOP: Role.MODE_TOP,
    GuitarMode.BACK: Role.MODE_BACK,
    GuitarMode.DIPOLE: Role.MODE_DIPOLE,
    GuitarMode.RING_MODE: Role.MODE_RING,
    GuitarMode.UPPER_MODES: Role.MODE_UPPER,
    GuitarMode.UNKNOWN: Role.MODE_UNKNOWN,
}

_QUALITY_ROLES: dict[WoodQuality, Role] = {
    WoodQuality.EXCELLENT: Role.WOOD_EXCELLENT,
    WoodQuality.VERY_GOOD: Role.WOOD_VERY_GOOD,
    WoodQuality.GOOD: Role.WOOD_GOOD,
    WoodQuality.FAIR: Role.WOOD_FAIR,
    WoodQuality.POOR: Role.WOOD_POOR,
}


def mode_role(mode: GuitarMode) -> Role:
    """The role of a guitar mode's colour. Mirrors Swift ``Palette.role(_: GuitarMode)``."""
    return _MODE_ROLES[mode]


def quality_role(quality: WoodQuality) -> Role:
    """The role of a wood-quality grade's colour. Mirrors Swift ``Palette.role(_: WoodQuality)``."""
    return _QUALITY_ROLES[quality]


# --------------------------------------------------------------------------------------------------
# The resolved scheme. Swift's palette colours resolve themselves when drawn; Qt's stylesheets and
# pyqtgraph items do not, so everything this edition draws itself connects to ``scheme_changed`` and
# redraws from the palette.
# --------------------------------------------------------------------------------------------------


class _SchemeNotifier(QtCore.QObject):
    """Emits ``scheme_changed(Scheme)`` when the resolved scheme changes — the one signal every
    redraw follows."""

    scheme_changed = QtCore.Signal(object)


_notifier: _SchemeNotifier | None = None
_appearance = Appearance.SYSTEM
_scheme = Scheme.LIGHT
_following_os = False
_native_style: str | None = None


def notifier() -> _SchemeNotifier:
    """The object whose ``scheme_changed`` signal fires on every change of the resolved scheme."""
    global _notifier
    if _notifier is None:
        _notifier = _SchemeNotifier()
    return _notifier


def scheme() -> Scheme:
    """The scheme the app is drawn in."""
    return _scheme


def os_scheme() -> Scheme | None:
    """The scheme the operating system reports, or ``None`` when it reports none (Qt's Unknown)."""
    app = QtGui.QGuiApplication.instance()
    if app is None:
        return None
    return {QtCore.Qt.ColorScheme.Light: Scheme.LIGHT, QtCore.Qt.ColorScheme.Dark: Scheme.DARK}.get(
        app.styleHints().colorScheme())


def apply(appearance: Appearance) -> None:
    """Draw the app — its windows, controls and the palette's colours — in the scheme ``appearance``
    resolves to: the operating system's own for System. Mirrors Swift ``Palette.apply``."""
    global _appearance, _following_os
    _appearance = appearance
    app = QtWidgets.QApplication.instance()
    if app is not None:
        hints = app.styleHints()
        if not _following_os:
            hints.colorSchemeChanged.connect(_on_os_scheme_changed)
            _following_os = True
        if appearance is Appearance.SYSTEM:
            hints.unsetColorScheme()
        else:
            scheme_ = QtCore.Qt.ColorScheme
            dark = appearance is Appearance.DARK
            hints.setColorScheme(scheme_.Dark if dark else scheme_.Light)
        _apply_linux_fallback(app, appearance)
    _update()


def _on_os_scheme_changed(_scheme: QtCore.Qt.ColorScheme) -> None:
    if _appearance is Appearance.SYSTEM:
        _update()


def _update() -> None:
    """Re-resolve the scheme; announce it when it changed."""
    global _scheme
    resolved = _appearance.resolved(os_scheme() if _appearance is Appearance.SYSTEM else None)
    if resolved is not _scheme:
        _scheme = resolved
        notifier().scheme_changed.emit(resolved)


def _apply_linux_fallback(app: QtWidgets.QApplication, appearance: Appearance) -> None:
    """On a Linux desktop that ignores Qt's scheme request, draw the widgets with the Fusion style
    and a palette built from the role table, so they follow the setting too; back to the native
    style for System."""
    global _native_style
    if not sys.platform.startswith("linux"):
        return
    requested = {Appearance.LIGHT: QtCore.Qt.ColorScheme.Light,
                 Appearance.DARK: QtCore.Qt.ColorScheme.Dark}.get(appearance)
    if requested is not None and app.styleHints().colorScheme() != requested:
        if _native_style is None:
            _native_style = app.style().name()
        app.setStyle("Fusion")
        dark = appearance is Appearance.DARK
        app.setPalette(_widget_palette(Scheme.DARK if dark else Scheme.LIGHT))
    elif _native_style is not None:
        app.setStyle(_native_style)
        _native_style = None
        app.setPalette(app.style().standardPalette())


def _widget_palette(s: Scheme) -> QtGui.QPalette:
    """A Qt widget palette for scheme ``s``, from the role table."""
    def c(role: Role) -> QtGui.QColor:
        return _qcolor(getattr(PAIRS[role], s.value))
    R = QtGui.QPalette.ColorRole
    p = QtGui.QPalette()
    for qt_role, role in (
        (R.Window, Role.BACKGROUND_WINDOW), (R.WindowText, Role.TEXT_PRIMARY),
        (R.Base, Role.BACKGROUND_CONTROL), (R.AlternateBase, Role.BACKGROUND_PANEL),
        (R.ToolTipBase, Role.BACKGROUND_PANEL), (R.ToolTipText, Role.TEXT_PRIMARY),
        (R.PlaceholderText, Role.TEXT_SECONDARY), (R.Text, Role.TEXT_PRIMARY),
        (R.Button, Role.BACKGROUND_CONTROL), (R.ButtonText, Role.TEXT_PRIMARY),
        (R.Highlight, Role.ACCENT), (R.Link, Role.ACCENT_TEXT),
        (R.Mid, Role.SEPARATOR), (R.Midlight, Role.SEPARATOR), (R.Dark, Role.SEPARATOR),
        (R.Light, Role.BACKGROUND_PANEL), (R.Shadow, Role.SEPARATOR),
    ):
        p.setColor(qt_role, c(role))
    p.setColor(R.HighlightedText, _qcolor(PAIRS[Role.BACKGROUND_PANEL].light))
    for qt_role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, qt_role, c(Role.TEXT_SECONDARY))
    return p


def _qcolor(hex_: str) -> QtGui.QColor:
    """``"#RRGGBB"`` or ``"#RRGGBBAA"`` as a QColor (Qt reads eight digits as ``#AARRGGBB``)."""
    color = QtGui.QColor(hex_[:7])
    if len(hex_) == 9:
        color.setAlpha(int(hex_[7:], 16))
    return color


def color(
    role: Role, opacity: Opacity | None = None, in_scheme: Scheme | None = None,
) -> QtGui.QColor:
    """The colour of ``role`` in the scheme the app is drawn in (or ``in_scheme`` — an export
    passes light), at that scheme's ``opacity`` when given."""
    s = in_scheme or _scheme
    result = _qcolor(getattr(PAIRS[role], s.value))
    if opacity is not None:
        light, dark = OPACITIES[opacity]
        result.setAlphaF(result.alphaF() * (dark if s is Scheme.DARK else light))
    return result


def rgb(role: Role, in_scheme: Scheme | None = None) -> tuple[int, int, int]:
    """``color(role)`` as an (r, g, b) tuple, for the pyqtgraph and painter calls."""
    c = color(role, in_scheme=in_scheme)
    return (c.red(), c.green(), c.blue())


def qss(role: Role, opacity: Opacity | None = None) -> str:
    """``color(role, opacity)`` written for a Qt stylesheet."""
    c = color(role, opacity)
    if c.alpha() == 255:
        return c.name()
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"


GRAY = PAIRS[Role.QUALITY_GRAY]
ORANGE = PAIRS[Role.QUALITY_ORANGE]
YELLOW = PAIRS[Role.QUALITY_YELLOW]
GREEN = PAIRS[Role.QUALITY_GREEN]
BLUE = PAIRS[Role.QUALITY_BLUE]
RED = PAIRS[Role.QUALITY_RED]
