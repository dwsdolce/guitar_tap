"""
Card-based peak list — replaces the QTableView-based PeakTable.

Each detected peak is displayed as a card with:
  • Star toggle     — show/hide the annotation on the FFT plot
  • Mode icon       — qtawesome icon in the mode's colour + in-range badge
  • Mode label      — clickable menu for manual override (italic when overridden)
  • Frequency       — right-aligned, bold
  • Pitch / cents   — purple, below frequency
  • Q / BW          — small grey text
  • Magnitude       — right-aligned, colour-coded (green/blue/orange/red)

Public interface is a drop-in replacement for peaks_table.PeakTable.
"""

from __future__ import annotations

import csv
import os

import numpy as np
import numpy.typing as npt

from PyQt6 import QtCore, QtGui, QtWidgets
import qtawesome as qta

from models import guitar_type as gt
from models import guitar_mode as gm
import peaks_model as pm
from models import pitch as pitch_c


def _short_mode(mode: str) -> str:
    if not mode:
        return gm.GuitarMode.UNKNOWN.display_name  # "Unknown"
    gmode = gm.GuitarMode.from_mode_string(mode)
    if gmode is not gm.GuitarMode.UNKNOWN:
        return gmode.abbreviation
    return mode  # custom label — show as-is


def _font(pt: int, bold: bool = False) -> QtGui.QFont:
    f = QtGui.QFont()
    f.setPointSize(pt)
    f.setBold(bold)
    return f


def _mag_color(mag_db: float) -> QtGui.QColor:
    if mag_db >= -40.0:
        return QtGui.QColor(40, 160, 40)
    if mag_db >= -60.0:
        return QtGui.QColor(40, 100, 210)
    if mag_db >= -80.0:
        return QtGui.QColor(200, 120, 30)
    return QtGui.QColor(200, 40, 40)


def _mode_color(mode_str: str) -> QtGui.QColor:
    r, g, b = gm.GuitarMode.from_mode_string(mode_str).color
    return QtGui.QColor(r, g, b)


# ── single peak card ─────────────────────────────────────────────────────────

class PeakCardWidget(QtWidgets.QFrame):
    """One card representing one resonant peak."""

    showChanged = QtCore.pyqtSignal(float, str)   # (freq, "on"/"off")
    modeChanged = QtCore.pyqtSignal(float, str)   # (freq, mode_string)
    modeReset  = QtCore.pyqtSignal(float)          # (freq) — reverted to auto
    cardClicked = QtCore.pyqtSignal(float)         # (freq)

    def __init__(
        self,
        freq: float,
        mag_db: float,
        q: float,
        guitar_type: gt.GuitarType,
        mode: str,
        show: str,
        is_held: bool,
        pitch_obj: pitch_c.Pitch,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._freq = freq
        self._mag_db = mag_db
        self._q = q
        self._guitar_type = guitar_type
        self._mode = mode
        self._show = show
        self._is_held = is_held
        self._pitch = pitch_obj
        self._is_selected = False
        self._is_manual = False

        self.setObjectName("PeakCard")
        self._build_ui()
        self._refresh()

    # ── layout ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(6, 5, 6, 5)
        outer.setSpacing(6)

        # Star button
        self._star_btn = QtWidgets.QToolButton()
        self._star_btn.setFixedSize(24, 24)
        self._star_btn.setFont(_font(14))
        self._star_btn.clicked.connect(self._toggle_show)
        outer.addWidget(self._star_btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        # Mode colour chip + range badge
        chip_col = QtWidgets.QVBoxLayout()
        chip_col.setSpacing(2)
        chip_col.setContentsMargins(0, 0, 0, 0)

        self._chip = QtWidgets.QLabel()
        self._chip.setFixedSize(26, 26)
        self._chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        chip_col.addWidget(self._chip, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        self._badge = QtWidgets.QLabel()
        self._badge.setFixedHeight(12)
        self._badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(_font(9))
        chip_col.addWidget(self._badge, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        outer.addLayout(chip_col)

        # Info column
        info = QtWidgets.QVBoxLayout()
        info.setSpacing(1)
        info.setContentsMargins(0, 0, 0, 0)

        # Row 1 — mode label (left) + freq (right)
        r1 = QtWidgets.QHBoxLayout()
        r1.setSpacing(4)
        self._mode_btn = QtWidgets.QToolButton()
        self._mode_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self._mode_btn.setFont(_font(10, bold=True))
        self._mode_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._mode_btn.clicked.connect(self._open_mode_menu)
        r1.addWidget(self._mode_btn, 1)

        self._freq_lbl = QtWidgets.QLabel(f"{self._freq:.1f} Hz")
        self._freq_lbl.setFont(_font(10, bold=True))
        self._freq_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        r1.addWidget(self._freq_lbl)
        info.addLayout(r1)

        # Row 2 — pitch + cents
        r2 = QtWidgets.QHBoxLayout()
        r2.setSpacing(3)
        note_icon = QtWidgets.QLabel("♪")
        note_icon.setFont(_font(9))
        note_icon.setStyleSheet("color: rgb(130,60,200);")
        r2.addWidget(note_icon)
        self._pitch_lbl = QtWidgets.QLabel()
        self._pitch_lbl.setFont(_font(9, bold=True))
        self._pitch_lbl.setStyleSheet("color: rgb(130,60,200);")
        r2.addWidget(self._pitch_lbl, 1)
        info.addLayout(r2)

        # Row 3 — Q/BW (left) + magnitude (right)
        r3 = QtWidgets.QHBoxLayout()
        r3.setSpacing(4)
        self._qbw_lbl = QtWidgets.QLabel()
        self._qbw_lbl.setFont(_font(9))
        self._qbw_lbl.setStyleSheet("color: rgb(120,120,120);")
        r3.addWidget(self._qbw_lbl, 1)
        self._mag_lbl = QtWidgets.QLabel(f"{self._mag_db:.1f} dB")
        self._mag_lbl.setFont(_font(10, bold=True))
        self._mag_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        r3.addWidget(self._mag_lbl)
        info.addLayout(r3)

        outer.addLayout(info, 1)

    # ── refresh helpers ───────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._refresh_bg()
        self._refresh_star()
        self._refresh_mode()
        self._refresh_pitch()
        self._refresh_qbw()
        self._refresh_mag()

    def _refresh_bg(self) -> None:
        color = _mode_color(self._mode)
        r, g, b = color.red(), color.green(), color.blue()
        if self._is_selected:
            border = "border: 2px solid rgba(40,100,255,200);"
        else:
            border = "border: 1px solid rgba(180,180,180,80);"
        self.setStyleSheet(
            f"QFrame#PeakCard {{"
            f"  background: rgba({r},{g},{b},20);"
            f"  {border}"
            f"  border-radius: 8px;"
            f"}}"
        )

    def _refresh_star(self) -> None:
        on = self._show == "on"
        self._star_btn.setText("★" if on else "☆")
        star_color = "rgb(30,120,255)" if on else "rgb(160,160,160)"
        self._star_btn.setStyleSheet(
            f"QToolButton {{ border: none; background: transparent; color: {star_color}; }}"
        )
        self._star_btn.setEnabled(self._is_held)

    def _refresh_mode(self) -> None:
        color = _mode_color(self._mode)
        r, g, b = color.red(), color.green(), color.blue()

        # Mode icon chip
        guitar_mode = gm.GuitarMode.from_mode_string(self._mode)
        pixmap = qta.icon(guitar_mode.icon, color=QtGui.QColor(r, g, b)).pixmap(
            QtCore.QSize(22, 22)
        )
        self._chip.setPixmap(pixmap)
        self._chip.setStyleSheet("")

        # Mode button label
        display = _short_mode(self._mode)
        italic = "italic" if self._is_manual else "normal"
        self._mode_btn.setText(display)
        self._mode_btn.setStyleSheet(
            f"QToolButton {{ border: none; background: transparent; padding: 0 2px;"
            f" color: rgb({r},{g},{b}); font-style: {italic}; }}"
        )
        self._mode_btn.setEnabled(self._is_held)

        # Range badge
        if self._mode:
            in_range = gm.in_mode_range(self._freq, self._mode, self._guitar_type)
            self._badge.setText("✓" if in_range else "⚠")
            self._badge.setStyleSheet(
                "color: rgb(40,160,40);" if in_range else "color: rgb(200,120,30);"
            )
            self._badge.setVisible(True)
        else:
            self._badge.setVisible(False)

    def _refresh_pitch(self) -> None:
        note = self._pitch.note(self._freq)
        cents = self._pitch.cents(self._freq)
        self._pitch_lbl.setText(f"{note}  {cents:+.0f}¢")

    def _refresh_qbw(self) -> None:
        if self._q > 0:
            bw = self._freq / self._q
            self._qbw_lbl.setText(f"Q: {self._q:.0f}  BW: {bw:.1f} Hz")
        else:
            self._qbw_lbl.setText("")

    def _refresh_mag(self) -> None:
        color = _mag_color(self._mag_db)
        self._mag_lbl.setText(f"{self._mag_db:.1f} dB")
        self._mag_lbl.setStyleSheet(
            f"color: rgb({color.red()},{color.green()},{color.blue()});"
        )

    # ── event handlers ────────────────────────────────────────────────────────

    def _toggle_show(self) -> None:
        if not self._is_held:
            return
        new_val = "off" if self._show == "on" else "on"
        self._show = new_val
        self._refresh_star()
        self.showChanged.emit(self._freq, new_val)

    def _open_mode_menu(self) -> None:
        if not self._is_held:
            return

        menu = QtWidgets.QMenu(self)

        # ── Reset to auto (only when a manual override is active) ─────────
        reset_action = None
        if self._is_manual:
            auto_str = gm.classify_peak(self._freq, self._guitar_type)
            auto_label = gm.mode_display_name(auto_str) or "Unknown"
            reset_action = menu.addAction(f"Reset to Auto-Detected ({auto_label})")
            menu.addSeparator()

        # ── Standard Modes (GuitarMode.current_cases) ─────────────────────
        for mode in gm.GuitarMode.current_cases:
            menu.addAction(mode.value)

        menu.addSeparator()

        # ── Extended Modes (GuitarMode.additional_mode_labels) ────────────
        for mode_str in gm.GuitarMode.additional_mode_labels:
            menu.addAction(mode_str)

        menu.addSeparator()

        # ── Custom… ───────────────────────────────────────────────────────
        custom_action = menu.addAction("Custom…")

        pos = self._mode_btn.mapToGlobal(
            QtCore.QPoint(0, self._mode_btn.height())
        )
        chosen = menu.exec(pos)
        if chosen is None:
            return

        if chosen is reset_action:
            self._mode = gm.classify_peak(self._freq, self._guitar_type)
            self._is_manual = False
            self._refresh_mode()
            self._refresh_bg()
            self.modeChanged.emit(self._freq, self._mode)
            self.modeReset.emit(self._freq)
            return

        if chosen is custom_action:
            draft = self._mode if self._is_manual else ""
            text, ok = QtWidgets.QInputDialog.getText(
                self,
                "Custom Mode Label",
                "Enter a mode label:",
                text=draft,
            )
            if not ok:
                return
            new_mode = text.strip()
        else:
            new_mode = chosen.text()

        if new_mode != self._mode:
            self._mode = new_mode
            self._is_manual = True
            self._refresh_mode()
            self._refresh_bg()
            self.modeChanged.emit(self._freq, new_mode)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.cardClicked.emit(self._freq)
        super().mousePressEvent(event)

    # ── public setters ────────────────────────────────────────────────────────

    def set_show(self, value: str) -> None:
        self._show = value
        self._refresh_star()

    def set_mode(self, mode: str, is_manual: bool = False) -> None:
        self._mode = mode
        self._is_manual = is_manual
        self._refresh_mode()
        self._refresh_bg()

    def set_held(self, held: bool) -> None:
        self._is_held = held
        self._refresh_star()
        self._refresh_mode()

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._refresh_bg()

    def set_guitar_type(self, guitar_type: gt.GuitarType) -> None:
        self._guitar_type = guitar_type
        self._refresh_mode()

    @property
    def freq(self) -> float:
        return self._freq


# ── container widget that emits clearPeaks on background clicks ───────────────

class _CardContainer(QtWidgets.QWidget):
    clearPeaks = QtCore.pyqtSignal()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        # Only fire if the click landed on the container itself (not on a child)
        child = self.childAt(event.pos())
        if child is None:
            self.clearPeaks.emit()
        super().mousePressEvent(event)


# ── list widget (public API) ──────────────────────────────────────────────────

class PeakListWidget(QtWidgets.QWidget):
    """Card-list replacement for peaks_table.PeakTable.

    Exposes the same public interface so callers need minimal changes.
    """

    clearPeaks    = QtCore.pyqtSignal()
    peakSelected  = QtCore.pyqtSignal(float)
    peakDeselected = QtCore.pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()

        self.selected_freq: float = 0.0
        self.selected_freq_index: int = -1

        data: npt.NDArray = np.vstack(([], [])).T
        self.model = pm.PeaksModel(data)
        self._pitch = pitch_c.Pitch(440)
        self._is_held = False
        self._cards: list[PeakCardWidget] = []
        self._saved_path: str = ""

        # Scroll area
        self._container = _CardContainer()
        self._container.clearPeaks.connect(self.clearPeaks)
        self._vbox = QtWidgets.QVBoxLayout(self._container)
        self._vbox.setContentsMargins(2, 2, 2, 2)
        self._vbox.setSpacing(4)
        self._vbox.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._container)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(scroll, 1)

        # Ensure the right panel is never narrower than a readable card width
        self.setMinimumWidth(240)

        # Keep cards in sync when the model changes via external calls
        # (select_all, deselect_all, set_guitar_type, auto_select, etc.)
        self.model.dataChanged.connect(self._on_model_data_changed)
        self.model.layoutChanged.connect(self._on_model_layout_changed)

    def sizeHint(self) -> QtCore.QSize:
        # Preferred width grows slightly with content but stays readable
        card_count = len(self._cards)
        w = max(240, 260 if card_count > 0 else 240)
        return QtCore.QSize(w, super().sizeHint().height())

    # ── card management ───────────────────────────────────────────────────────

    def _rebuild_cards(self, data: npt.NDArray) -> None:
        """Rebuild all cards from *data* (shape [N, 2] or [N, 3])."""
        # Remove existing cards (not the trailing stretch)
        while self._vbox.count() > 1:
            item = self._vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        if data.shape[0] == 0:
            self.updateGeometry()
            return

        # Sort by frequency ascending
        order = np.argsort(data[:, 0])
        for i in order:
            freq   = float(data[i, 0])
            mag_db = float(data[i, 1])
            q      = float(data[i, 2]) if data.shape[1] > 2 else 0.0

            src_idx = self.model.index(int(self.model.freq_index(freq)), 0)
            mode = self.model.mode_value(src_idx)
            show = self.model.show_value(src_idx)
            is_manual = freq in self.model.modes

            card = PeakCardWidget(
                freq=freq,
                mag_db=mag_db,
                q=q,
                guitar_type=self.model.guitar_type,
                mode=mode,
                show=show,
                is_held=self._is_held,
                pitch_obj=self._pitch,
                parent=self._container,
            )
            card._is_manual = is_manual
            card.showChanged.connect(self._on_show_changed)
            card.modeChanged.connect(self._on_mode_changed)
            card.modeReset.connect(self._on_mode_reset)
            card.cardClicked.connect(self._on_card_clicked)

            self._vbox.insertWidget(len(self._cards), card)
            self._cards.append(card)

        self.updateGeometry()

    def _card_for_freq(self, freq: float) -> PeakCardWidget | None:
        for card in self._cards:
            if card.freq == freq:
                return card
        return None

    # ── model change listeners ────────────────────────────────────────────────

    def _on_model_data_changed(
        self,
        top_left: QtCore.QModelIndex,
        bottom_right: QtCore.QModelIndex,
        _roles: object = None,
    ) -> None:
        """Sync card appearance when model data changes externally."""
        for row in range(top_left.row(), bottom_right.row() + 1):
            src_idx = self.model.index(row, 0)
            freq = self.model.freq_value(src_idx)
            card = self._card_for_freq(freq)
            if card is None:
                continue
            col = top_left.column()
            if col == pm.ColumnIndex.Show.value:
                card.set_show(self.model.show_value(src_idx))
            elif col == pm.ColumnIndex.Modes.value:
                mode = self.model.mode_value(src_idx)
                card.set_mode(mode, is_manual=(freq in self.model.modes))

    def _on_model_layout_changed(self) -> None:
        """Refresh mode displays when guitar_type changes."""
        for card in self._cards:
            card.set_guitar_type(self.model.guitar_type)
            row = int(self.model.freq_index(card.freq))
            if row < 0:
                continue
            src_idx = self.model.index(row, 0)
            card.set_mode(
                self.model.mode_value(src_idx),
                is_manual=(card.freq in self.model.modes),
            )

    # ── card signal handlers ──────────────────────────────────────────────────

    def _on_show_changed(self, freq: float, value: str) -> None:
        idx = self.model.freq_index(freq)
        if idx >= 0:
            self.model.setData(
                self.model.index(int(idx), pm.ColumnIndex.Show.value), value
            )

    def _on_mode_changed(self, freq: float, mode: str) -> None:
        idx = self.model.freq_index(freq)
        if idx >= 0:
            self.model.setData(
                self.model.index(int(idx), pm.ColumnIndex.Modes.value), mode
            )

    def _on_mode_reset(self, freq: float) -> None:
        idx = self.model.freq_index(freq)
        if idx >= 0:
            src_idx = self.model.index(int(idx), pm.ColumnIndex.Modes.value)
            self.model.reset_mode_value(src_idx)
            self.model.dataChanged.emit(src_idx, src_idx, [QtCore.Qt.ItemDataRole.DisplayRole])
            self.model.update_annotation(src_idx)

    def _on_card_clicked(self, freq: float) -> None:
        prev = self.selected_freq
        if prev == freq:
            # clicking the already-selected card deselects it
            card = self._card_for_freq(freq)
            if card:
                card.set_selected(False)
            self.selected_freq = 0.0
            self.selected_freq_index = -1
            self.peakDeselected.emit(freq)
            return

        # Deselect previous
        if prev:
            old_card = self._card_for_freq(prev)
            if old_card:
                old_card.set_selected(False)
            self.peakDeselected.emit(prev)

        # Select new
        card = self._card_for_freq(freq)
        if card:
            card.set_selected(True)
        self.selected_freq = freq
        idx = self.model.freq_index(freq)
        self.selected_freq_index = int(idx) if idx >= 0 else -1
        self.peakSelected.emit(freq)

    # ── public API (matches peaks_table.PeakTable) ────────────────────────────

    def update_data(self, data: npt.NDArray) -> bool:
        self.model.update_data(data)
        self._rebuild_cards(data)
        if self.selected_freq > 0:
            self.select_row(self.selected_freq)
        return True

    def save_peaks(self) -> None:
        if not self._saved_path:
            self._saved_path = os.getenv("HOME", "")
        filename, sel_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            caption="Save Peaks to CSV",
            directory=self._saved_path,
            filter="Comma Separated Values (*.csv)",
            initialFilter="Comma Separated Values (*.csv)",
        )
        if not filename or not sel_filter:
            return
        self._saved_path = os.path.dirname(filename)
        n_rows = self.model.rowCount(QtCore.QModelIndex())
        header = [
            self.model.headerData(
                col,
                QtCore.Qt.Orientation.Horizontal,
                QtCore.Qt.ItemDataRole.DisplayRole,
            )
            for col in range(self.model.columnCount(QtCore.QModelIndex()))
        ]
        try:
            with open(filename, "w", encoding="utf-8-sig") as f:
                writer = csv.writer(f, dialect="excel", lineterminator="\n")
                writer.writerow(header)
                for row in range(n_rows):
                    writer.writerow(
                        self.model.data_value(self.model.index(row, col))
                        for col in range(len(header))
                    )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Error saving peaks", f"Table was not saved\n{str(e)}"
            )

    def restore_focus(self) -> None:
        self.setFocus()

    def select_row(self, freq: float) -> None:
        # Deselect current
        if self.selected_freq and self.selected_freq != freq:
            old = self._card_for_freq(self.selected_freq)
            if old:
                old.set_selected(False)

        card = self._card_for_freq(freq)
        if card:
            card.set_selected(True)
            # Scroll the card into view
            scroll = self._find_scroll_area()
            if scroll:
                scroll.ensureWidgetVisible(card)

        self.selected_freq = freq
        idx = self.model.freq_index(freq)
        self.selected_freq_index = int(idx) if idx >= 0 else -1

    def _find_scroll_area(self) -> QtWidgets.QScrollArea | None:
        p = self.parent()
        while p:
            if isinstance(p, QtWidgets.QScrollArea):
                return p
            p = p.parent()
        # Walk children of self instead
        for child in self.findChildren(QtWidgets.QScrollArea):
            return child
        return None

    def clear_selection(self) -> None:
        if self.selected_freq:
            card = self._card_for_freq(self.selected_freq)
            if card:
                card.set_selected(False)
        self.selected_freq = 0.0
        self.selected_freq_index = -1

    def data_held(self, held: bool) -> None:
        self._is_held = held
        for card in self._cards:
            card.set_held(held)
        self.model.data_held(held)

    def new_data(self, held: bool) -> None:
        self.model.new_data(held)
        self.clear_selected_peak()

    def clear_selected_peak(self) -> None:
        self.selected_freq = 0.0
        self.selected_freq_index = -1
