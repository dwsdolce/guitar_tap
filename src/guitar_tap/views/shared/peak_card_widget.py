"""
Card-based peak list.

Each detected peak is displayed as a card with:
  • Star toggle     — show/hide the annotation on the FFT plot
  • Mode icon       — qtawesome icon in the mode's colour + in-range badge
  • Mode label      — clickable menu for manual override (italic when overridden)
  • Frequency       — right-aligned, bold
  • Pitch / cents   — purple, below frequency
  • Q / BW          — small grey text
  • Magnitude       — right-aligned, colour-coded (green/blue/orange/red)
"""

from __future__ import annotations

# @parity view/peak-card
# (The `combined_peak_mode_row_view.py` shim re-exports these under the Swift-aligned
#  name; this module is the real implementation and carries the parity tag.)

import numpy as np
import numpy.typing as npt
from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models import field_precision as fp
from guitar_tap.models import guitar_mode as gm
from guitar_tap.views.utilities import palette, view_update
from guitar_tap.views.utilities.material_peak_role import MaterialPeakRole, phase_badge
from guitar_tap.models import guitar_type as gt
from guitar_tap.models import pitch as pitch_c
from guitar_tap.views.shared import peaks_model as pm


def _mode_name(mode: str) -> str:
    """The card's mode label: the mode's name ("Air (Helmholtz)"), or a custom label as written."""
    return mode or gm.GuitarMode.UNKNOWN.display_name


def _font(pt: int, bold: bool = False) -> QtGui.QFont:
    f = QtGui.QFont()
    f.setPointSize(pt)
    f.setBold(bold)
    return f


def _mode_color(mode_str: str) -> QtGui.QColor:
    # Plate/brace material labels — mirrors Swift DraggablePeakAnnotation.modeColor.
    from guitar_tap.views.shared.peaks_model import PeaksModel
    mat = PeaksModel._MATERIAL_MODE_ROLES.get(mode_str)
    if mat is not None:
        return palette.color(mat)
    resolved = gm.GuitarMode.from_display_name(mode_str)
    if resolved is None and mode_str:
        # Freeform user-defined label → distinct teal color.
        r, g, b = palette.rgb(palette.Role.MODE_USER_DEFINED)
    else:
        r, g, b = palette.rgb(palette.mode_role(resolved or gm.GuitarMode.UNKNOWN))
    return QtGui.QColor(r, g, b)


# ── single peak card ─────────────────────────────────────────────────────────

class PeakCardWidget(QtWidgets.QFrame):
    """One card representing one resonant peak."""

    # Each names the card's peak by its id: two peaks can share a frequency. As Swift's rows act on
    # the peak's id.
    showChanged = QtCore.Signal(object, str)  # (peak id, "on"/"off")
    modeChanged = QtCore.Signal(object, str)  # (peak id, mode_string)
    modeReset  = QtCore.Signal(object)        # (peak id) — reverted to auto
    cardClicked = QtCore.Signal(float)         # (freq)

    def __init__(
        self,
        freq: float,
        mag_db: float,
        q: float,
        bandwidth: float,
        guitar_type: gt.GuitarType,
        mode: str,
        auto_mode: str,
        show: str,
        is_held: bool,
        pitch_obj: pitch_c.Pitch,
        show_pitch: bool = True,
        read_only: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # A card that only shows its peak (Measurement Details): no star, no mode menu —
        # Swift's CombinedPeakModeRowView with no onToggleSelection or onSetModeOverride.
        self._read_only = read_only
        self._freq = freq
        self._mag_db = mag_db
        self._q = q
        self._bandwidth = bandwidth
        self._guitar_type = guitar_type
        self._mode = mode
        # Context-aware auto-classified mode label from the model's _auto_mode_map
        # (built by classify_all with full peak context).  Mirrors Swift's
        # analyzer.peakMode(for:) which is passed separately from the effective label.
        self._auto_mode = auto_mode
        self._show = show
        self._is_held = is_held
        self._pitch = pitch_obj
        self._show_pitch = show_pitch
        self._is_selected = False
        # Identity of the peak this card represents; frequency is not unique.
        self.peak_id = ""
        self._is_manual = False

        self._chip_key: tuple | None = None
        self._note_key: str | None = None
        self.setObjectName("PeakCard")
        self._build_ui()
        self._refresh()
        # Drawn here, not by a stylesheet: redraw in every new scheme. A bound method, so Qt
        # disconnects it when the card is destroyed.
        palette.notifier().scheme_changed.connect(self._on_scheme_changed)

    def _on_scheme_changed(self, _scheme) -> None:
        self._refresh()

    # ── layout ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QtWidgets.QHBoxLayout(self)
        # Swift's 6 × 5 padding, less the 2 px highlight border the card always reserves (Swift draws
        # its border over the row).
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(6)

        # Star button
        self._star_btn = QtWidgets.QToolButton()
        self._star_btn.setFixedSize(24, 24)
        self._star_btn.setFont(_font(14))
        self._star_btn.clicked.connect(self._toggle_show)
        # Shown only once it is in the layout: shown with no parent it is a window of its own for
        # a moment, and a window appearing closes any open popup or menu.
        outer.addWidget(self._star_btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._star_btn.setVisible(not self._read_only)

        # Mode colour chip + range badge
        chip_col = QtWidgets.QVBoxLayout()
        chip_col.setSpacing(2)
        chip_col.setContentsMargins(0, 0, 0, 0)

        self._chip = QtWidgets.QLabel()
        self._chip.setFixedSize(26, 26)
        self._chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        chip_col.addWidget(self._chip, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        # A plate / brace peak shows its role's badge in place of the mode icon — Swift's card with
        # a materialRole.
        material_role = MaterialPeakRole.from_display_name(self._mode)
        if material_role is not None:
            self._chip.setVisible(False)
            chip_col.addWidget(phase_badge(material_role), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

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
        # The name on the left, the frequency on the right — mirrors Swift's
        # HStack { label Spacer() freq }.
        self._mode_btn = QtWidgets.QToolButton()
        self._mode_btn.setFont(_font(10, bold=True))
        # As tall as its text, as Swift's label is — a tool button's own padding made the card
        # taller.
        self._mode_btn.setFixedHeight(QtGui.QFontMetrics(self._mode_btn.font()).height())
        self._mode_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._mode_btn.clicked.connect(self._open_mode_menu)
        r1.addWidget(self._mode_btn)
        r1.addStretch(1)

        self._freq_lbl = QtWidgets.QLabel(f"{fp.string(self._freq, fp.PEAK_FREQUENCY_HZ)} Hz")
        self._freq_lbl.setFont(_font(10, bold=True))
        self._freq_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        r1.addWidget(self._freq_lbl)
        info.addLayout(r1)

        # Row 2 — pitch + cents (guitar mode only — mirrors Swift measurementType.isGuitar guard)
        self._pitch_lbl = None
        self._note_icon = None
        if self._show_pitch:
            r2 = QtWidgets.QHBoxLayout()
            r2.setSpacing(3)
            # Swift's music.note symbol, as an icon in the pitch colour.
            note_icon = QtWidgets.QLabel()
            note_icon.setFixedSize(10, 12)
            self._note_icon = note_icon
            r2.addWidget(note_icon)
            self._pitch_lbl = QtWidgets.QLabel()
            self._pitch_lbl.setFont(_font(9, bold=True))
            r2.addWidget(self._pitch_lbl, 1)
            info.addLayout(r2)

        # Row 3 — Q/BW (left) + magnitude (right)
        r3 = QtWidgets.QHBoxLayout()
        r3.setSpacing(4)
        self._qbw_lbl = QtWidgets.QLabel()
        self._qbw_lbl.setFont(_font(9))
        r3.addWidget(self._qbw_lbl, 1)
        self._mag_lbl = QtWidgets.QLabel(f"{fp.string(self._mag_db, fp.PEAK_MAGNITUDE_DB)} dB")
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

    # A highlighted row's fill under its tint, and its border — mirrors Swift
    # TapAnalysisResultsView.
    _HIGHLIGHT_OPACITY = palette.opacity(palette.Opacity.PEAK_ROW_HIGHLIGHT)
    _HIGHLIGHT_BORDER_WIDTH = 2

    def _refresh_bg(self) -> None:
        """The row's tint — its mode colour at the scheme's peak-row opacity — and, when it is
        highlighted, the mode colour's border and fill under the tint. Mirrors Swift
        CombinedPeakModeRowView / TapAnalysisResultsView."""
        tint = palette.color(self._mode_role(), palette.Opacity.PEAK_ROW_TINT)
        mode = _mode_color(self._mode)
        if self._is_selected:
            under = self._HIGHLIGHT_OPACITY
            tint.setAlphaF(1 - (1 - tint.alphaF()) * (1 - under))
            border = mode.name()
        else:
            border = "transparent"
        r, g, b, a = tint.red(), tint.green(), tint.blue(), tint.alpha()
        view_update.set_style_sheet(self, 
            f"QFrame#PeakCard {{"
            f"  background: rgba({r},{g},{b},{a});"
            f"  border: {self._HIGHLIGHT_BORDER_WIDTH}px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
        )

    def _mode_role(self) -> palette.Role:
        """The role of the card's effective mode colour: a freeform label's, or its mode's."""
        from guitar_tap.views.shared.peaks_model import PeaksModel

        resolved = gm.GuitarMode.from_display_name(self._mode)
        mat = PeaksModel._MATERIAL_MODE_ROLES.get(self._mode)
        if mat is not None:
            return mat
        if resolved is None and self._mode:
            return palette.Role.MODE_USER_DEFINED
        return palette.mode_role(resolved or gm.GuitarMode.UNKNOWN)

    def _refresh_star(self) -> None:
        on = self._show == "on"
        self._star_btn.setText("★" if on else "☆")
        star_color = palette.qss(
            palette.Role.PEAK_SELECTED_STAR if on else palette.Role.PEAK_UNSELECTED_STAR)
        view_update.set_style_sheet(self._star_btn, 
            f"QToolButton {{ border: none; background: transparent; color: {star_color}; }}"
        )
        self._star_btn.setEnabled(self._is_held)

    def _refresh_mode(self) -> None:
        color = _mode_color(self._mode)
        r, g, b = color.red(), color.green(), color.blue()

        # Mode icon chip — freeform user-defined labels use a tag icon.
        guitar_mode = gm.GuitarMode.from_display_name(self._mode)
        if guitar_mode is None and self._mode:
            icon_name = gm.GuitarMode.USER_DEFINED_ICON
        else:
            icon_name = (guitar_mode or gm.GuitarMode.UNKNOWN).icon
        chip_key = (icon_name, r, g, b)
        if self._chip_key != chip_key:
            self._chip_key = chip_key
            self._chip.setPixmap(palette.icon(icon_name, QtGui.QColor(r, g, b)).pixmap(QtCore.QSize(18, 18)))

        # Mode button label — a manual override is shown italic with a trailing " *",
        # the one convention used everywhere (list, annotation, PDF, tables). No glyph:
        # at label size it was unreadable. Mirrors Swift/web.
        display = _mode_name(self._mode)
        if self._is_manual:
            display = f"{display} *"
        italic = "italic" if self._is_manual else "normal"
        self._mode_btn.setText(display)
        view_update.set_style_sheet(self._mode_btn, 
            f"QToolButton {{ border: none; background: transparent; padding: 0 2px;"
            f" color: rgb({r},{g},{b}); font-style: {italic}; }}"
        )
        self._mode_btn.setEnabled(self._is_held)

        # Classified mark — mirrors Swift: a check for a peak the analyzer classified, neither
        # Unknown nor Upper Modes, keyed off the AUTO-classified mode (analyzer.peakMode(for:) ->
        # self._auto_mode), not a manual label. A classified peak is always inside its mode's
        # range: classification assigns a mode only to a peak within it.
        auto_gmode = gm.GuitarMode.from_display_name(self._auto_mode)
        if auto_gmode not in (None, gm.GuitarMode.UNKNOWN, gm.GuitarMode.UPPER_MODES):
            self._badge.setText("✓")
            view_update.set_style_sheet(self._badge, f"color: {palette.qss(palette.Role.PEAK_IN_RANGE)};")
            self._badge.setVisible(True)
        else:
            self._badge.setVisible(False)

    def _refresh_pitch(self) -> None:
        if self._pitch_lbl is None:
            return
        note = self._pitch.note(self._freq)
        cents = self._pitch.cents(self._freq)
        # Mirrors Swift ResonantPeak.formattedPitch: "G2 (-10 ¢)".
        self._pitch_lbl.setText(f"{note} ({'+' if cents >= 0 else ''}{cents:.0f} ¢)")
        view_update.set_style_sheet(self._pitch_lbl, f"color: {palette.qss(palette.Role.PEAK_PITCH)};")
        note_key = palette.qss(palette.Role.PEAK_PITCH)
        if self._note_key != note_key:
            self._note_key = note_key
            self._note_icon.setPixmap(
                palette.icon("mdi.music-note", palette.color(palette.Role.PEAK_PITCH)).pixmap(10, 12))

    def _refresh_qbw(self) -> None:
        view_update.set_style_sheet(self._qbw_lbl, f"color: {palette.qss(palette.Role.TEXT_SECONDARY)};")
        if self._q > 0:
            # The peak's own bandwidth, as Swift and the web show it.
            self._qbw_lbl.setText(
                f"Q: {fp.string(self._q, fp.Q_FACTOR)}  "
                f"BW: {fp.string(self._bandwidth, fp.BANDWIDTH_HZ)} Hz")
        else:
            self._qbw_lbl.setText("")

    def _refresh_mag(self) -> None:
        self._mag_lbl.setText(f"{fp.string(self._mag_db, fp.PEAK_MAGNITUDE_DB)} dB")
        role = palette.magnitude_role(self._mag_db)
        view_update.set_style_sheet(self._mag_lbl, f"color: {palette.qss(role)};")
        view_update.set_style_sheet(self._freq_lbl, f"color: {palette.qss(palette.Role.TEXT_PRIMARY)};")

    # ── event handlers ────────────────────────────────────────────────────────

    def _toggle_show(self) -> None:
        if not self._is_held or self._read_only:
            return
        new_val = "off" if self._show == "on" else "on"
        self._show = new_val
        self._refresh_star()
        self.showChanged.emit(self.peak_id, new_val)

    def _open_mode_menu(self) -> None:
        if not self._is_held or self._read_only:
            return

        menu = QtWidgets.QMenu(self)

        # ── Reset to auto (only when a manual override is active) ─────────
        reset_action = None
        if self._is_manual:
            # Use self._auto_mode — the context-aware label from the model's
            # _auto_mode_map (built by classify_all with all peaks together).
            # Mirrors Swift: "Reset to Auto-Detected (\(mode.displayName))"
            # where mode = analyzer.peakMode(for: peak) (from identifiedModes/classifyAll).
            reset_action = menu.addAction(f"Reset to Auto-Detected ({self._auto_mode})")
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
            # Don't set self._mode here from a per-frequency range lookup — it can be
            # wrong in the TOP/BACK overlap zone. Instead just clear the manual flag and
            # emit modeReset; the model's
            # _on_mode_reset handler will remove the override and push the correct
            # auto-classified mode back via dataChanged → set_mode (which uses
            # _auto_mode_map built by classify_all — the claiming algorithm).
            self._is_manual = False
            self._refresh_mode()
            self._refresh_bg()
            self.modeReset.emit(self.peak_id)
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
            self.modeChanged.emit(self.peak_id, new_mode)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Emit ``cardClicked`` on a left mouse press (row selection)."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.cardClicked.emit(self._freq)
        super().mousePressEvent(event)

    # ── public setters ────────────────────────────────────────────────────────

    def set_show(self, value: str) -> None:
        """Set the star (annotation-visibility) state ("on"/"off") and refresh the star."""
        self._show = value
        self._refresh_star()

    def set_mode(self, mode: str, auto_mode: str | None = None, is_manual: bool = False) -> None:
        """Set the effective mode label (with optional auto label + manual flag) and refresh — nothing when it is
        what the card shows already."""
        if (mode, auto_mode if auto_mode is not None else self._auto_mode, is_manual) == \
                (self._mode, self._auto_mode, self._is_manual):
            return
        self._mode = mode
        if auto_mode is not None:
            self._auto_mode = auto_mode
        self._is_manual = is_manual
        self._refresh_mode()
        self._refresh_bg()

    def set_held(self, held: bool) -> None:
        """Set whether captured data is held (enables the star/menu) and refresh."""
        self._is_held = held
        self._refresh_star()
        self._refresh_mode()

    def set_selected(self, selected: bool) -> None:
        """Set the selected state (highlighted border) and refresh the background."""
        self._is_selected = selected
        self._refresh_bg()

    def set_guitar_type(self, guitar_type: gt.GuitarType) -> None:
        """Change the guitar type used for mode-range classification and refresh — nothing when it is unchanged."""
        if guitar_type == self._guitar_type:
            return
        self._guitar_type = guitar_type
        self._refresh_mode()

    def can_show(self, mode: str, show_pitch: bool, read_only: bool) -> bool:
        """Whether this card can be reused for a peak shown this way: its layout is fixed when it is built — a
        plate / brace role's badge in place of the mode icon, the pitch row, the star and menu."""
        return (MaterialPeakRole.from_display_name(self._mode) is None) == \
            (MaterialPeakRole.from_display_name(mode) is None) \
            and self._show_pitch == show_pitch and self._read_only == read_only

    def apply(self, *, peak_id: str, freq: float, mag_db: float, q: float, bandwidth: float,
              guitar_type: gt.GuitarType, mode: str, auto_mode: str, show: str, is_manual: bool,
              is_held: bool) -> None:
        """Show this peak: change only what differs from what the card shows now — the part of SwiftUI's
        updating a row that Qt leaves to the app."""
        self.peak_id = peak_id
        if freq != self._freq:
            self._freq = freq
            self._freq_lbl.setText(f"{fp.string(freq, fp.PEAK_FREQUENCY_HZ)} Hz")
            self._refresh_pitch()
        if mag_db != self._mag_db:
            self._mag_db = mag_db
            self._refresh_mag()
        if (q, bandwidth) != (self._q, self._bandwidth):
            self._q, self._bandwidth = q, bandwidth
            self._refresh_qbw()
        star = show != self._show or is_held != self._is_held
        marked = (mode, auto_mode, is_manual, is_held, guitar_type) != \
            (self._mode, self._auto_mode, self._is_manual, self._is_held, self._guitar_type)
        mode_changed = mode != self._mode
        self._show, self._mode, self._auto_mode = show, mode, auto_mode
        self._is_manual, self._is_held, self._guitar_type = is_manual, is_held, guitar_type
        if star:
            self._refresh_star()
        if marked:
            self._refresh_mode()
        if mode_changed:
            self._refresh_bg()

    @property
    def freq(self) -> float:
        """This card's peak frequency, in Hz."""
        return self._freq


# ── container widget that emits clearPeaks on background clicks ───────────────

class _CardContainer(QtWidgets.QWidget):
    clearPeaks = QtCore.Signal()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        # Only fire if the click landed on the container itself (not on a child)
        child = self.childAt(event.pos())
        if child is None:
            self.clearPeaks.emit()
        super().mousePressEvent(event)


# ── list widget (public API) ──────────────────────────────────────────────────

class PeakListWidget(QtWidgets.QWidget):
    """Card-based peak list widget."""

    clearPeaks    = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()

        # Mirrors Swift measurementType.isGuitar — controls pitch row visibility in cards.
        self._is_guitar: bool = True
        self._last_peaks: list = []  # list[ResonantPeak]
        self._last_data: "npt.NDArray | None" = None

        data: npt.NDArray = np.vstack(([], [])).T
        # Owned by this widget, so it is deleted with it and its connections go too.
        self.model = pm.PeaksModel(data, self)
        self._pitch = pitch_c.Pitch(440)
        self._is_held = False
        self._cards: list[PeakCardWidget] = []

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
        # Shown while the list is empty, at its top, as Swift's.
        self._empty_lbl = QtWidgets.QLabel("No peaks detected in visible range")
        self._empty_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setContentsMargins(0, 12, 0, 12)
        palette.tag(self._empty_lbl, color=palette.Role.TEXT_SECONDARY)
        layout.addWidget(self._empty_lbl)
        layout.addWidget(scroll, 1)

        # Ensure the right panel is never narrower than a readable card width
        self.setMinimumWidth(240)

        # Keep cards in sync when the model changes via external calls
        # (select_all, deselect_all, set_guitar_type, auto_select, etc.)
        self.model.dataChanged.connect(self._on_model_data_changed)
        self.model.layoutChanged.connect(self._on_model_layout_changed)

    def sizeHint(self) -> QtCore.QSize:
        """Preferred size — width grows slightly with content but stays readable."""
        # Preferred width grows slightly with content but stays readable
        card_count = len(self._cards)
        w = max(240, 260 if card_count > 0 else 240)
        return QtCore.QSize(w, super().sizeHint().height())

    # ── card management ───────────────────────────────────────────────────────

    def _rebuild_cards(self, data: npt.NDArray) -> None:
        """Show *data* (shape [N, 2] or [N, 3], one row per model peak): the cards updated in place, by peak id,
        as Swift's ``ForEach(sortedPeaksWithModes, id: \\.peak.id)`` — a card kept for a peak it already shows,
        others reused or added, the rest removed (``view_update.sync_children``)."""
        self._empty_lbl.setVisible(data.shape[0] == 0)

        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        _gt = _tds.guitar_type()

        def item(i: int) -> dict:
            # Resolve by ROW, never by frequency: `i` from argsort IS the model row, so this is peak identity.
            # Going through model.freq_index(freq) was a defect: it returns -1 for a non-unique frequency, and -1
            # is a VALID Python index, so both cards of a duplicated peak read _peaks[-1].
            freq = float(data[i, 0])
            q = float(data[i, 2]) if data.shape[1] > 2 else 0.0
            src_idx = self.model.index(int(i), 0)
            peak = self.model._peaks[int(i)] if int(i) < len(self.model._peaks) else None
            return dict(
                peak_id=peak.id if peak is not None else "",
                freq=freq,
                mag_db=float(data[i, 1]),
                q=q,
                bandwidth=(float(peak.bandwidth) if peak is not None else (freq / q if q > 0 else 0.0)),
                guitar_type=_gt,
                mode=self.model.mode_value(src_idx),
                auto_mode=self.model.peak_mode(src_idx),
                show=self.model.show_value(src_idx),
                is_manual=self.model.is_manual_value(src_idx),
                is_held=self._is_held,
            )

        items = [item(int(i)) for i in np.argsort(data[:, 0])] if data.shape[0] else []

        def make(it: dict) -> PeakCardWidget:
            card = PeakCardWidget(
                freq=it["freq"], mag_db=it["mag_db"], q=it["q"], bandwidth=it["bandwidth"],
                guitar_type=it["guitar_type"], mode=it["mode"], auto_mode=it["auto_mode"], show=it["show"],
                is_held=it["is_held"], pitch_obj=self._pitch, show_pitch=self._is_guitar, parent=self._container,
            )
            card._is_manual = it["is_manual"]
            if it["is_manual"]:
                card._refresh_mode()
            # Identity for later syncs — frequency is not unique.
            card.peak_id = it["peak_id"]
            card.showChanged.connect(self._on_show_changed)
            card.modeChanged.connect(self._on_mode_changed)
            card.modeReset.connect(self._on_mode_reset)
            card.cardClicked.connect(lambda _freq, c=card: self._on_card_clicked(c))
            return card

        def remove(card: PeakCardWidget) -> None:
            self._vbox.removeWidget(card)
            card.deleteLater()

        cards = view_update.sync_children(
            self._cards, items,
            item_key=lambda it: it["peak_id"],
            child_key=lambda card: card.peak_id,
            make=make,
            update=lambda card, it: card.apply(**it),
            remove=remove,
            can_reuse=lambda card, it: card.can_show(it["mode"], self._is_guitar, False),
            distance=lambda card, it: abs(card.freq - it["freq"]),
        )

        # The cards in the peaks' order, ahead of the trailing stretch; moved only when out of place.
        in_place = [self._vbox.itemAt(k) for k in range(len(cards))]
        if [item.widget() if item is not None else None for item in in_place] != cards:
            for card in cards:
                self._vbox.removeWidget(card)
            for k, card in enumerate(cards):
                self._vbox.insertWidget(k, card)
        self._cards = cards
        self.updateGeometry()

    def _card_for_freq(self, freq: float) -> PeakCardWidget | None:
        """First card at this frequency.

        Frequency is NOT unique, so prefer _card_for_peak_id wherever an id is available.
        """
        for card in self._cards:
            if card.freq == freq:
                return card
        return None

    def _card_for_peak_id(self, peak_id: str) -> PeakCardWidget | None:
        """The card for this peak, matched on identity rather than frequency."""
        if not peak_id:
            return None
        for card in self._cards:
            if getattr(card, "peak_id", "") == peak_id:
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
            peak_id = self.model._peaks[row].id if row < len(self.model._peaks) else ""
            # Match on identity: two peaks can share a frequency, and _card_for_freq would
            # return the first of them for both rows.
            card = self._card_for_peak_id(peak_id) or self._card_for_freq(freq)
            if card is None:
                continue
            col = top_left.column()
            if col == pm.ColumnIndex.Show.value:
                card.set_show(self.model.show_value(src_idx))
            elif col == pm.ColumnIndex.Modes.value:
                mode = self.model.mode_value(src_idx)
                auto_mode = self.model.peak_mode(src_idx)
                card.set_mode(mode, auto_mode=auto_mode, is_manual=self.model.is_manual_value(src_idx))

    def _on_model_layout_changed(self) -> None:
        """Refresh mode displays when guitar_type changes."""
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        _gt = _tds.guitar_type()
        for card in self._cards:
            card.set_guitar_type(_gt)
            row = self.model.row_of(card.peak_id)
            if row < 0:
                continue
            src_idx = self.model.index(row, 0)
            card.set_mode(
                self.model.mode_value(src_idx),
                auto_mode=self.model.peak_mode(src_idx),
                is_manual=self.model.is_manual_value(src_idx),
            )

    # ── card signal handlers ──────────────────────────────────────────────────

    def _on_show_changed(self, peak_id, value: str) -> None:
        idx = self.model.row_of(peak_id)
        if idx >= 0:
            self.model.setData(
                self.model.index(int(idx), pm.ColumnIndex.Show.value), value
            )

    def _on_mode_changed(self, peak_id, mode: str) -> None:
        idx = self.model.row_of(peak_id)
        if idx >= 0:
            self.model.setData(
                self.model.index(int(idx), pm.ColumnIndex.Modes.value), mode
            )

    def _on_mode_reset(self, peak_id) -> None:
        idx = self.model.row_of(peak_id)
        if idx >= 0:
            src_idx = self.model.index(int(idx), pm.ColumnIndex.Modes.value)
            self.model.reset_mode_value(src_idx)
            self.model.dataChanged.emit(src_idx, src_idx, [QtCore.Qt.ItemDataRole.DisplayRole])
            self.model.update_annotation(src_idx)

    def _on_card_clicked(self, card: "PeakCardWidget") -> None:
        """A click on a card toggles the model's highlighted peak (Swift's results-row tap)."""
        analyzer = self.model._analyzer
        if analyzer is not None and card.peak_id:
            analyzer.toggle_highlighted_peak(card.peak_id)

    def show_highlight(self, peak_id) -> None:
        """Highlight the card of the model's highlighted peak (none: no card), scrolling it into view.
        Writes no state."""
        target = self._card_for_peak_id(peak_id) if peak_id else None
        for card in self._cards:
            card.set_selected(card is target)
        if target is not None:
            scroll = self._find_scroll_area()
            if scroll:
                scroll.ensureWidgetVisible(target)

    def _show_model_highlight(self) -> None:
        analyzer = self.model._analyzer
        self.show_highlight(analyzer.highlighted_peak_id if analyzer is not None else None)

    # ── public API ────────────────────────────────────────────────────────────

    def set_is_guitar(self, is_guitar: bool) -> None:
        """Set whether this widget is displaying guitar peaks (shows pitch) or not.

        Mirrors Swift measurementType.isGuitar guard on pitch display in PeakAnnotationLabel.
        Propagates to the underlying PeaksModel so mode_value() resolves L/C/FLC labels
        for plate/brace measurements. Rebuilds cards immediately so the change takes
        effect without waiting for new data.
        """
        if self._is_guitar == is_guitar:
            return
        self._is_guitar = is_guitar
        self.model.is_guitar = is_guitar
        if self._last_data is not None:
            self._rebuild_cards(self._last_data)

    def update_data(self, peaks: list) -> bool:  # list[ResonantPeak]
        """Rebuild the cards from a new list of peaks (auto-classified modes)."""
        self._last_peaks = peaks
        if peaks:
            data = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in peaks],
                dtype=np.float64,
            )
        else:
            data = np.zeros((0, 3), dtype=np.float64)
        self._last_data = data
        self.model.update_data(peaks)
        self._rebuild_cards(data)
        self._show_model_highlight()
        return True

    def update_data_with_modes(self, peaks_with_modes: list) -> bool:  # list[(ResonantPeak, GuitarMode)]
        """Update with pre-classified (peak, mode) pairs.

        Mirrors Swift TapAnalysisResultsView.sortedPeaksWithModes (line 287–290)
        which maps each peak through analyzer.peakMode(for:).  Delegates to
        PeaksModel.update_data_with_modes so the model installs caller-supplied
        modes directly without re-running classify_all.
        """
        peaks = [p for p, _ in peaks_with_modes]
        if peaks:
            data = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in peaks],
                dtype=np.float64,
            )
        else:
            data = np.zeros((0, 3), dtype=np.float64)
        self._last_peaks = peaks
        self._last_data = data
        self.model.update_data_with_modes(peaks_with_modes)
        self._rebuild_cards(data)
        self._show_model_highlight()
        return True

    def restore_focus(self) -> None:
        """Give keyboard focus back to the list."""
        self.setFocus()

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

    def data_held(self, held: bool) -> None:
        """Set the held state on every card (enables stars/menus when held)."""
        self._is_held = held
        for card in self._cards:
            card.set_held(held)
        self.model.data_held(held)
