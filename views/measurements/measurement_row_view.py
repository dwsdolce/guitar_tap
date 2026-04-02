"""
Single-row widget for the measurements list.

Mirrors Swift's MeasurementRowView.swift — a full-width clickable widget
that displays one TapToneMeasurement with three lines of metadata.

  Line 1 : [bold location/"Measurement"] ··· [waveform?] [HH:MM] [›]
  Line 2 : [N peaks] [• Ratio: X.XX] [• Decay: X.XXs]
  Line 3 : [notes, word-wrapped]   (optional)

Shows PointingHandCursor on hover and emits clicked() on left-button release.
In compare mode the chevron is replaced with a filled/empty circle that
reflects the current selection state.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6 import QtCore, QtGui, QtWidgets

from models import TapToneMeasurement
from models import guitar_mode as GM
from models import guitar_type as GT


# ── Helper ────────────────────────────────────────────────────────────────────

def _resolve_guitar_type(s: str | None) -> GT.GuitarType:
    if s:
        try:
            return GT.GuitarType(s)
        except ValueError:
            pass
    return GT.GuitarType.CLASSICAL


def tap_tone_ratio(m: TapToneMeasurement) -> float | None:
    """Compute the AIR:TOP frequency ratio for a measurement, or None."""
    if not m.peaks:
        return None
    try:
        gt = _resolve_guitar_type(m.guitar_type)
        pairs = [(p.frequency, p.magnitude) for p in m.peaks]
        idx_map = GM.GuitarMode.classify_all(pairs, gt)
        air = next(
            (m.peaks[i].frequency for i, mode in idx_map.items()
             if mode.normalized == GM.GuitarMode.AIR),
            None,
        )
        top = next(
            (m.peaks[i].frequency for i, mode in idx_map.items()
             if mode.normalized == GM.GuitarMode.TOP),
            None,
        )
        if air and top and air > 0:
            return top / air
    except Exception:
        pass
    return None


# ── Widget ────────────────────────────────────────────────────────────────────

class MeasurementRowView(QtWidgets.QWidget):
    """
    Full-row clickable widget (matches .contentShape(Rectangle()) in Swift).

    Emits clicked() when the left mouse button is released inside the widget.
    """

    clicked: QtCore.pyqtSignal = QtCore.pyqtSignal()

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

        if not compare_mode:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Compare-mode circle icon + content in an HBox
        top_hbox = QtWidgets.QHBoxLayout()
        top_hbox.setSpacing(8)

        if compare_mode:
            circle = QtWidgets.QLabel("●" if compare_selected else "○")
            color = "#3478f6" if compare_selected else (
                "#888888" if compare_eligible else "#cccccc"
            )
            circle.setStyleSheet(f"color: {color}; font-size: 18px;")
            circle.setFixedWidth(22)
            top_hbox.addWidget(circle)

        content = QtWidgets.QVBoxLayout()
        content.setSpacing(3)

        # Line 1: location + waveform + time + chevron
        line1 = QtWidgets.QHBoxLayout()
        line1.setSpacing(6)

        loc = QtWidgets.QLabel(m.tap_location or "Measurement")
        loc.setStyleSheet("font-weight: bold; font-size: 13px;")
        loc.setWordWrap(True)
        line1.addWidget(loc)
        line1.addStretch()

        if m.spectrum_snapshot is not None:
            wave = QtWidgets.QLabel("〜")
            wave.setStyleSheet("color: #28a028; font-size: 11px;")
            wave.setToolTip("Has spectrum snapshot")
            line1.addWidget(wave)

        try:
            dt = datetime.fromisoformat(m.timestamp).astimezone()
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = m.timestamp[11:16] if len(m.timestamp) >= 16 else ""
        time_lbl = QtWidgets.QLabel(time_str)
        time_lbl.setStyleSheet("color: #888888; font-size: 10px;")
        line1.addWidget(time_lbl)

        # Disclosure chevron — matches Image(systemName: "chevron.right") in Swift
        if not compare_mode:
            chevron = QtWidgets.QLabel("›")
            chevron.setStyleSheet("color: #888888; font-size: 13px;")
            line1.addWidget(chevron)

            # Ellipsis hint — transparent when idle, visible on hover to signal RMB menu
            # Matches Image(systemName: "ellipsis.circle").opacity(isHovered ? 1 : 0) in Swift
            # Always occupies space (no layout shift) — only color alpha changes.
            self._ellipsis_lbl = QtWidgets.QLabel("⋯")
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,0); font-size: 11px;")
            line1.addWidget(self._ellipsis_lbl)
        else:
            self._ellipsis_lbl = None

        content.addLayout(line1)

        # Line 2: peaks • ratio • decay
        parts: list[str] = [f"{len(m.peaks)} peaks"]
        ratio = tap_tone_ratio(m)
        if ratio is not None:
            parts.append(f"Ratio: {ratio:.2f}")
        if m.decay_time is not None:
            parts.append(f"Decay: {m.decay_time:.2f}s")
        meta = QtWidgets.QLabel("  •  ".join(parts))
        meta.setStyleSheet("color: #888888; font-size: 10px;")
        content.addWidget(meta)

        # Line 3: notes (word-wrapped, expands to fit)
        if m.notes:
            notes_lbl = QtWidgets.QLabel(m.notes)
            notes_lbl.setStyleSheet("color: #888888; font-size: 10px;")
            notes_lbl.setWordWrap(True)
            content.addWidget(notes_lbl)

        top_hbox.addLayout(content)
        layout.addLayout(top_hbox)

        if compare_mode and not compare_eligible:
            eff = QtWidgets.QGraphicsOpacityEffect(self)
            eff.setOpacity(0.4)
            self.setGraphicsEffect(eff)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._pressed and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        else:
            self._pressed = False
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 10))
        self.setPalette(p)
        if self._ellipsis_lbl is not None:
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,255); font-size: 11px;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._pressed = False
        self.setAutoFillBackground(False)
        if self._ellipsis_lbl is not None:
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,0); font-size: 11px;")
        super().leaveEvent(event)
