"""
Single-row widget for the measurements list.

Mirrors Swift's MeasurementRowView.swift — a full-width clickable widget
that displays one TapToneMeasurement with three lines of metadata.

  Line 1 : [bold measurementName/"Measurement"] ··· [waveform?] [HH:MM] [›]
  Line 2 : [N peaks] [• Ratio: X.XX] [• Decay: X.XXs]
  Line 3 : [notes, word-wrapped]   (optional)

Shows PointingHandCursor on hover.  Emits clicked() on left-button release
and doubleClicked() on left-button double-click.  In normal mode the list
view connects doubleClicked to load the measurement; in compare mode
clicked toggles the selection circle.
"""

# @parity view/measurements-list

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models import TapToneMeasurement
from guitar_tap.models import field_precision as fp
from guitar_tap.utilities.date_format import format_display_datetime
from guitar_tap.views.utilities import palette


# ── Helper ────────────────────────────────────────────────────────────────────

def _draw_compare_circle(label: QtWidgets.QLabel, selected: bool) -> None:
    """The compare-mode mark — Swift's circle / checkmark.circle.fill: an empty circle in the
    secondary colour, or the accent with a check."""
    if selected:
        palette.set_icon(label, "mdi.check-circle", palette.Role.ACCENT_TEXT, 18)
    else:
        palette.set_icon(
            label, "mdi.checkbox-blank-circle-outline", palette.Role.TEXT_SECONDARY, 18)


# ── Widget ────────────────────────────────────────────────────────────────────

class MeasurementRowView(QtWidgets.QWidget):
    """
    Full-row clickable widget (matches .contentShape(Rectangle()) in Swift).

    Emits clicked() when the left mouse button is released inside the widget.
    """

    clicked: QtCore.Signal = QtCore.Signal()
    doubleClicked: QtCore.Signal = QtCore.Signal()
    # Emitted with a global QPoint when the "⋯" button is clicked, so the list view can
    # show the per-row action menu there (same menu as right-click).
    menuRequested: QtCore.Signal = QtCore.Signal(QtCore.QPoint)

    def __init__(
        self,
        m: TapToneMeasurement,
        compare_mode: bool = False,
        compare_selected: bool = False,
        compare_eligible: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pressed = False
        # A line under the row, in the separator role — Swift's list row separators.
        self.setObjectName("measurement_row")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#measurement_row { border-bottom-width: 1px; border-bottom-style: solid; }")
        palette.tag(self, border=palette.Role.SEPARATOR)

        if not compare_mode:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Compare-mode circle icon + content in an HBox
        top_hbox = QtWidgets.QHBoxLayout()
        top_hbox.setSpacing(8)

        self._compare_circle: QtWidgets.QLabel | None = None
        self._compare_eligible = compare_eligible
        if compare_mode:
            circle = QtWidgets.QLabel()
            _draw_compare_circle(circle, compare_selected)
            circle.setFixedWidth(22)
            top_hbox.addWidget(circle)
            self._compare_circle = circle

        content = QtWidgets.QVBoxLayout()
        content.setSpacing(3)

        # Line 1: measurement name + icon + date/time + chevron
        line1 = QtWidgets.QHBoxLayout()
        line1.setSpacing(6)

        loc = QtWidgets.QLabel(m.measurement_name or ("Comparison" if m.is_comparison else "Measurement"))
        loc.setStyleSheet("font-weight: bold; font-size: 13px;")
        loc.setWordWrap(True)
        # The name takes the free width, so it wraps only when the row has no room for it — as
        # Swift's Text beside a Spacer.
        line1.addWidget(loc, 1)

        if m.is_comparison:
            # Swift's chart.bar.doc.horizontal, in the accent.
            chart_icon = QtWidgets.QLabel()
            palette.set_icon(chart_icon, "mdi.file-chart-outline", palette.Role.ACCENT_TEXT, 12)
            chart_icon.setToolTip("Comparison record")
            line1.addWidget(chart_icon)
        elif m.spectrum_snapshot is not None:
            # Swift's waveform, in status.complete.
            wave = QtWidgets.QLabel()
            palette.set_icon(wave, "mdi.waveform", palette.Role.STATUS_COMPLETE, 12)
            wave.setToolTip("Has spectrum snapshot")
            line1.addWidget(wave)

        time_lbl = QtWidgets.QLabel(format_display_datetime(m.timestamp))
        time_lbl.setStyleSheet("font-size: 10px;")
        palette.tag(time_lbl, color=palette.Role.TEXT_SECONDARY)
        line1.addWidget(time_lbl)

        # Disclosure chevron — matches Image(systemName: "chevron.right") in Swift, which keeps it
        # in compare mode too.
        chevron = QtWidgets.QLabel("›")
        chevron.setStyleSheet("font-size: 13px;")
        palette.tag(chevron, color=palette.Role.TEXT_SECONDARY)
        line1.addWidget(chevron)

        if not compare_mode:
            # The row's ⋯: an icon button shown while the row is under the pointer, keeping its space when hidden
            # (no layout shift) — Swift's ellipsis.circle Menu at .opacity(isHovered ? 1 : 0). It opens the row's
            # action menu, as a right-click on the row does.
            self._ellipsis_btn = QtWidgets.QToolButton()
            self._ellipsis_btn.setText("⋯")  # its name; a tool button shows only its icon
            palette.tag(self._ellipsis_btn, icon=True)
            palette.set_icon(self._ellipsis_btn, "mdi.dots-horizontal-circle-outline", palette.Role.TEXT_SECONDARY)
            self._ellipsis_btn.setIconSize(QtCore.QSize(13, 13))
            self._ellipsis_btn.setToolTip("Actions")
            keep_space = self._ellipsis_btn.sizePolicy()
            keep_space.setRetainSizeWhenHidden(True)
            self._ellipsis_btn.setSizePolicy(keep_space)
            self._ellipsis_btn.setVisible(False)
            self._ellipsis_btn.clicked.connect(self._on_ellipsis_clicked)
            line1.addWidget(self._ellipsis_btn)
        else:
            self._ellipsis_btn = None

        content.addLayout(line1)

        # Line 2: for comparison records show spectrum count; for regular show peaks/ratio/decay
        if m.is_comparison:
            n = len(m.comparison_entries) if m.comparison_entries else 0
            meta = QtWidgets.QLabel(f"{n} spectra compared")
        else:
            count = len(m.peaks)
            parts: list[str] = [f"{count} {'peak' if count == 1 else 'peaks'}"]
            ratio = m.tap_tone_ratio
            if ratio is not None:
                parts.append(f"Ratio: {fp.string(ratio, fp.DECAY_RATIO)}")
            if m.decay_time is not None:
                parts.append(f"Decay: {fp.string(m.decay_time, fp.DECAY_TIME_S)}s")
            meta = QtWidgets.QLabel("  •  ".join(parts))
        meta.setStyleSheet("font-size: 10px;")
        palette.tag(meta, color=palette.Role.TEXT_SECONDARY)
        content.addWidget(meta)

        # Line 3: notes (word-wrapped, expands to fit)
        if m.notes:
            notes_lbl = QtWidgets.QLabel(m.notes)
            notes_lbl.setStyleSheet("font-size: 10px;")
            palette.tag(notes_lbl, color=palette.Role.TEXT_SECONDARY)
            notes_lbl.setWordWrap(True)
            content.addWidget(notes_lbl)

        top_hbox.addLayout(content)
        layout.addLayout(top_hbox)

        if compare_mode and not compare_eligible:
            eff = QtWidgets.QGraphicsOpacityEffect(self)
            eff.setOpacity(palette.opacity(palette.Opacity.CONTROL_NOT_APPLICABLE))
            self.setGraphicsEffect(eff)

    def setCompareSelected(self, selected: bool) -> None:
        """Update the compare-mode circle indicator in place (no rebuild)."""
        if self._compare_circle is None:
            return
        _draw_compare_circle(self._compare_circle, selected)

    # The row handles its own left clicks and does not pass them up: the list would make the row its current item,
    # which some styles (Linux desktop themes) paint in the system's highlight colour. Swift's rows show nothing
    # on a click.
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._pressed and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit()
            event.accept()
            return
        self._pressed = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _on_ellipsis_clicked(self) -> None:
        """Open the per-row action menu just below the ⋯ button (same menu as RMB)."""
        btn = self._ellipsis_btn
        if btn is not None:
            self.menuRequested.emit(btn.mapToGlobal(btn.rect().bottomLeft()))

    def enterEvent(self, event) -> None:
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), palette.color(palette.Role.BACKGROUND_SUBTLE))
        self.setPalette(p)
        if self._ellipsis_btn is not None:
            self._ellipsis_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._pressed = False
        self.setAutoFillBackground(False)
        if self._ellipsis_btn is not None:
            self._ellipsis_btn.setVisible(False)
        super().leaveEvent(event)
