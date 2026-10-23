# @parity view/peak-annotations
"""
    Annotations displayed on the FFT canvas plot.

    Each annotation consists of:
      • A styled label badge  — HTML content with mode name, pitch, frequency, magnitude
      • A dashed connection line  — from peak marker to label, in the mode colour

    The label is draggable.  Right-clicking it shows a "Reset Position" context
    menu action (matches Swift DraggablePeakAnnotation behaviour).

    The default label position is placed a fixed data-space offset above the peak.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models import field_precision as fp
from guitar_tap.models import guitar_mode as gm
from guitar_tap.models import pitch as pitch_c

# The label rule, from the module that keeps the analyzer's dragged positions: it imports no views,
# where the analyzer's own module does, so importing it here makes no cycle.
from guitar_tap.models.tap_tone_analyzer_annotation_management import (
    TapToneAnalyzerAnnotationManagementMixin as _LabelRule,
)
from guitar_tap.views import chart_menu
from guitar_tap.views.utilities import chart_style, palette, view_update
from guitar_tap.views.utilities.extensions import formatted_as_frequency

#: A plate's or brace's label names its phase, in that phase's colour.
MATERIAL_LABEL_ROLES: dict[str, palette.Role] = {
    "Longitudinal": palette.Role.MATERIAL_LONGITUDINAL,
    "Cross-grain":  palette.Role.MATERIAL_CROSS,
    "Diagonal":     palette.Role.MATERIAL_FLC,
    "Peak":         palette.Role.MATERIAL_UNSELECTED,
}

_PITCH = pitch_c.Pitch(440)


def label_html(freq: float, mag: float, mode: str, is_override: bool = False) -> str:
    """A peak label's text, as Swift's ``PeakAnnotationLabel``, top to bottom: the mode name —
    bold, in the mode's colour (italic with a trailing " *" when it is the user's own); the pitch
    and cents (guitar only); the frequency; the magnitude."""
    rows: list[str] = []
    if mode in MATERIAL_LABEL_ROLES:
        # Plate / brace: label by phase (no pitch row — not meaningful for material)
        r, g, b = palette.rgb(MATERIAL_LABEL_ROLES[mode])
        rows.append(f'<b style="color:rgb({r},{g},{b});">{mode}</b>')
    else:
        # Guitar: the mode's colour and display name; a freeform label of the user's in its own
        # colour.
        guitar_mode = gm.GuitarMode.from_display_name(mode)
        if guitar_mode is None and mode:
            r, g, b = palette.rgb(palette.Role.MODE_USER_DEFINED)
        else:
            r, g, b = palette.rgb(palette.mode_role(guitar_mode or gm.GuitarMode.UNKNOWN))
        display = gm.mode_display_name(mode) or ""
        if display:
            if is_override:
                rows.append(f'<b style="color:rgb({r},{g},{b});"><i>{display} *</i></b>')
            else:
                rows.append(f'<b style="color:rgb({r},{g},{b});">{display}</b>')
        note = _PITCH.note(freq)
        cents = _PITCH.cents(freq)
        pitch_color = palette.qss(palette.Role.PEAK_PITCH)
        cents_color = palette.qss(palette.Role.PEAK_PITCH, palette.Opacity.PEAK_PITCH_CENTS)
        rows.append(
            f'<span style="color:{pitch_color};">&#9834; {note}</span>&nbsp;&nbsp;'
            f'<span style="color:{cents_color};">{cents:+.0f}&#162;</span>'
        )
    freq_color = palette.qss(palette.Role.CHART_TITLE)
    db_color = palette.qss(palette.Role.CHART_AXIS)
    rows.append(f'<span style="color:{freq_color};">{formatted_as_frequency(freq)}</span>')
    db_text = f"{fp.string(mag, fp.PEAK_MAGNITUDE_DB)} dB"
    rows.append(f'<span style="color:{db_color};">{db_text}</span>')
    return '<center>' + '<br/>'.join(rows) + '</center>'


def peak_label(analyzer, peak) -> tuple[str, bool]:
    """A peak label's mode name and whether it is the user's own: a plate's or brace's phase by the
    analyzer's effective L / C / FLC peak, else "Peak"; a guitar's ``effective_mode_label``. Mirrors
    Swift ``DraggablePeakAnnotation``'s ``modeLabel`` and override check."""
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    if not TapDisplaySettings.measurement_type().is_guitar:
        if peak.id == analyzer.effective_longitudinal_peak_id:
            return "Longitudinal", False
        if peak.id == analyzer.effective_cross_peak_id:
            return "Cross-grain", False
        if peak.id == analyzer.effective_flc_peak_id:
            return "Diagonal", False
        return "Peak", False
    return analyzer.effective_mode_label(peak), analyzer.has_manual_override(peak.id)

# The chart's stacking: the curves and dots at 0, the mode labels over them, the peak labels over those.
MODE_LABEL_Z = 1
PEAK_LABEL_Z = 2

# Type alias for the annotation dict stored in FftAnnotations.annotations
_AnnDict = dict[str, Any]


# ── draggable, resettable annotation label ────────────────────────────────────

class DraggableTextItem(pg.TextItem):
    """Styled annotation badge that can be dragged and reset via RMB menu."""

    # Corner radius in pixels — mirrors Swift RoundedRectangle(cornerRadius: 6)
    _CORNER_RADIUS: float = 6.0

    def __init__(
        self,
        anchor: tuple[float, float] = (0.5, 0.5),
        fill: QtGui.QBrush | None = None,
        border: QtGui.QPen | None = None,
    ) -> None:
        # Pass fill but NOT border to the parent — we draw the rounded border ourselves
        # in paint() so pyqtgraph doesn't draw a square one on top of ours.
        super().__init__(html="", anchor=anchor, fill=fill, border=None)
        self._border_pen: QtGui.QPen = border or QtGui.QPen(QtCore.Qt.PenStyle.NoPen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        self._arrow_line: pg.PlotDataItem | None = None
        self._peak_freq: float = 0.0
        self._peak_mag: float = 0.0
        self._default_pos: QtCore.QPointF | None = None
        self._peak_id: str = ""
        self._analyzer = None

    def mousePressEvent(self, ev) -> None:
        # The closed hand while the label is dragged, as Swift's — held over the canvas's own cursor.
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            self._holds_cursor = True
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if getattr(self, "_holds_cursor", False):
            QtWidgets.QApplication.restoreOverrideCursor()
            self._holds_cursor = False
        super().mouseReleaseEvent(ev)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        """Draw the rounded-rectangle background and border, then the text.

        We draw the background and border ourselves (rounded corners), then
        paint the inner QGraphicsTextItem directly — bypassing pg.TextItem.paint()
        which would draw a square background on top.  Calling super().paint()
        with mutated self.fill/self.border is unsafe under PySide6/Shiboken and
        causes a SIGSEGV via re-entrant virtual dispatch.
        """
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        br = self.boundingRect()
        # Draw rounded background fill
        if self.fill is not None:
            painter.setBrush(self.fill)
        else:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(self._border_pen)
        painter.drawRoundedRect(br, self._CORNER_RADIUS, self._CORNER_RADIUS)
        # Paint just the text by delegating to the inner QGraphicsTextItem.
        # pg.TextItem stores the text as self.textItem (a QGraphicsTextItem child).
        # We translate the painter to the textItem's position and paint it directly.
        painter.save()
        text_pos = self.textItem.pos()
        painter.translate(text_pos)
        self.textItem.paint(painter, option, widget)
        painter.restore()

    # ── HTML content ──────────────────────────────────────────────────────────

    def set_html(self, html: str) -> None:
        """Update the label content and reflow the text bounding rect."""
        # The label's size follows its text; Qt must be told before it changes, or it repaints only the old area
        # and what was under the new part (a leader, the curve) stays on screen over the label.
        self.prepareGeometryChange()
        self.textItem.setHtml(html)
        # Qt only centres text when the document has a fixed width; set it to
        # the natural (widest-line) width so text-align:center is honoured. The width is cleared first: Qt
        # measures the ideal width within the width already set, so a label given longer text would keep the
        # old, narrower width and wrap.
        doc = self.textItem.document()
        doc.setTextWidth(-1)
        doc.setTextWidth(doc.idealWidth())
        self.updateTextPos()

    def restyle(self, mode_color: tuple[int, int, int]) -> None:
        """Update fill and border colours when the mode changes.

        Mirrors Swift PeakAnnotationLabel: the chart's readout background with a coloured border.
        """
        r, g, b = mode_color
        self.fill        = pg.mkBrush(palette.color(palette.Role.CHART_READOUT_BACKGROUND))
        self._border_pen = chart_style.pen((r, g, b), chart_style.SCREEN.label_border_width)
        self.update()

    # ── arrow line ────────────────────────────────────────────────────────────

    def connect_arrow(
        self,
        line: pg.PlotDataItem,
        freq: float,
        mag: float,
        default_pos: tuple[float, float],
        peak_id: str = "",
        analyzer=None,
    ) -> None:
        """Associate the dashed connection line and record where the label sits undragged.

        `default_pos` is the peak plus the default offset, ignoring any stored position — where
        "Reset Position" returns the label. `peak_id`/`analyzer` let "Reset Position" clear the
        stored position (Swift `resetAnnotationOffset(for:)`).
        """
        self._arrow_line  = line
        self._peak_freq   = freq
        self._peak_mag    = mag
        self._default_pos = QtCore.QPointF(default_pos[0], default_pos[1])
        self._peak_id     = peak_id
        self._analyzer    = analyzer

    def _update_arrow(self) -> None:
        if self._arrow_line is None:
            return
        pos = self.pos()
        self._arrow_line.setData(
            [self._peak_freq, pos.x()],
            [self._peak_mag,  pos.y()],
        )

    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._update_arrow()
        return super().itemChange(change, value)

    def _show_context_menu(self, screen_pos: QtCore.QPoint) -> None:
        """RMB menu — matches Swift DraggablePeakAnnotation context menu.

        "moved" = the label has a stored position (Swift `isMoved`). Reset clears it via the
        analyzer (Swift `resetAnnotationOffset(for:)`) and returns the label to its peak plus the
        default offset (`_default_pos`).
        """
        has_moved = (self._analyzer is not None and bool(self._peak_id)
                     and self._peak_id in self._analyzer.peak_annotation_offsets)
        menu = QtWidgets.QMenu()
        entry = chart_menu.LABEL_MENU[0]
        reset_action = palette.add_menu_item(menu, f"mdi.{entry.mdi}", entry.title)
        reset_action.setEnabled(has_moved)
        chosen = menu.exec(screen_pos)
        if chosen is reset_action and self._default_pos is not None:
            if self._analyzer is not None and self._peak_id:
                self._analyzer.reset_annotation_offset(self._peak_id)
            self.setPos(self._default_pos)
            self._update_arrow()


# ── annotation manager ────────────────────────────────────────────────────────

class FftAnnotations(QtCore.QObject):
    """
    Manages the set of peak annotation badges on the FFT plot.

    Each entry in ``annotations`` stores:
        freq, mag, html, mode_str, xytext,
        annotation (DraggableTextItem | None),
        arrow_line (PlotDataItem | None)
    """

    restoreFocus: QtCore.Signal = QtCore.Signal()

    def __init__(self, plot_widget: pg.PlotWidget, analyzer=None):
        # Owned by the chart, so it is deleted with it and its connections go too.
        super().__init__(plot_widget)
        self.plot_item = plot_widget.getPlotItem()
        self.annotations: list[_AnnDict] = []
        # The labels of the last refresh, kept on the chart until the next one has taken what it can reuse —
        # Qt cannot afford SwiftUI's recreating every label whose peak got a new id (a live frame's).
        self._retiring: list[_AnnDict] = []
        self._retire_due = False
        # Reference to the TapToneAnalyzer — used to persist dragged annotation
        # offsets across pan/zoom rebuilds (mirrors Swift peakAnnotationOffsets).
        self._analyzer = analyzer
        # Intercept QContextMenuEvent at the widget level so we can show our own
        # annotation menu before QGraphicsView::contextMenuEvent delivers to the
        # scene (where it would reach the ViewBox instead of our annotation items).
        self._plot_view = plot_widget
        plot_widget.installEventFilter(self)
        plot_widget.viewport().installEventFilter(self)
        # The chart's labels are the analyzer's to decide (chart_annotation_peaks), read once per
        # event-loop turn however many changes came — as Swift's chart reads
        # tap.chartAnnotationPeaks.
        self._labels = view_update.Invalidator(self, self._refresh_labels)

    # ── the labels, from the analyzer ─────────────────────────────────────

    def attach(self, analyzer) -> None:
        """Take the analyzer whose peaks are labelled, and follow it: a change to its peaks, their
        selection or labels, the display mode, the plate / brace phases, or a load brings the labels
        up to date. Mirrors Swift's ``SpectrumView`` observing the analyzer."""
        self._analyzer = analyzer
        for signal in (analyzer.peaksChanged, analyzer.displayModeChanged,
                       analyzer.comparisonChanged, analyzer.selectedLongitudinalPeakChanged,
                       analyzer.selectedCrossPeakChanged, analyzer.selectedFlcPeakChanged,
                       analyzer.measurementLoaded):
            signal.connect(self.invalidate_labels)
        # To this object's own slot, so the connections end with it.
        palette.notifier().scheme_changed.connect(self.invalidate_labels)
        self._labels.invalidate()

    def invalidate_labels(self, *_args: object) -> None:
        """Bring the labels up to date at the end of this event-loop turn — for a change the
        analyzer does not announce (its annotation visibility, a setting)."""
        self._labels.invalidate()

    def _refresh_labels(self) -> None:
        """The labels for the analyzer's ``chart_annotation_peaks`` — none while a comparison is
        shown — each from its peak: its mode name, pitch and override mark from the analyzer, its
        place by ``annotation_centre_from``. Labels whose peak is kept are reused in place."""
        analyzer = self._analyzer
        peaks = (analyzer.chart_annotation_peaks or []) if analyzer is not None else []
        self.clear_annotations()
        for peak in peaks:
            mode, is_override = peak_label(analyzer, peak)
            html = label_html(peak.frequency, peak.magnitude, mode, is_override)
            self.update_annotation(peak.id, peak.frequency, peak.magnitude, html, mode)
        self.refresh_display()

    # ── widget-level context menu interception ────────────────────────────────

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Intercept QContextMenuEvent on the PlotWidget before the ViewBox sees it.

        If the RMB click position maps to any annotation label, show our menu
        and consume the event.  Otherwise let the normal ViewBox menu appear.
        """
        if event.type() == QtCore.QEvent.Type.ContextMenu:
            view = self._plot_view
            # Map widget-local click pos → scene coordinates
            widget_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_pos = view.mapToScene(widget_pos)
            for ann_dict in self.annotations:
                ann = ann_dict["annotation"]
                if ann is None:
                    continue
                local_pos = ann.mapFromScene(scene_pos)
                if ann.boundingRect().contains(local_pos):
                    ann._show_context_menu(event.globalPosition().toPoint()
                                           if hasattr(event, "globalPosition")
                                           else event.globalPos())
                    return True   # consumed — ViewBox never sees it
        return False

    # ── item factories ────────────────────────────────────────────────────────

    def _mode_color(self, mode_str: str) -> tuple[int, int, int]:
        # Plate/brace material labels — mirrors Swift DraggablePeakAnnotation.modeColor
        # which checks measurementType.isGuitar before using guitar colours.
        from guitar_tap.views.shared.peaks_model import PeaksModel
        mat = PeaksModel._MATERIAL_MODE_ROLES.get(mode_str)
        if mat is not None:
            return palette.rgb(mat)
        resolved = gm.GuitarMode.from_display_name(mode_str)
        if resolved is None and mode_str:
            # Freeform user-defined label → distinct teal color.
            return palette.rgb(palette.Role.MODE_USER_DEFINED)
        return palette.rgb(palette.mode_role(resolved or gm.GuitarMode.UNKNOWN))

    def _make_text_item(
        self,
        html: str,
        xy_text: tuple[float, float],
        mode_color: tuple[int, int, int],
    ) -> DraggableTextItem:
        r, g, b = mode_color
        item = DraggableTextItem(
            anchor=(0.5, 0.5),
            fill=pg.mkBrush(palette.color(palette.Role.CHART_READOUT_BACKGROUND)),
            border=chart_style.pen((r, g, b), chart_style.SCREEN.label_border_width),
        )
        item.set_html(html)
        item.setPos(xy_text[0], xy_text[1])
        return item

    def _make_arrow_line(
        self,
        freq: float,
        mag: float,
        xy_text: tuple[float, float],
        mode_color: tuple[int, int, int],
    ) -> pg.PlotDataItem:
        r, g, b = mode_color
        return pg.PlotDataItem(
            [freq, xy_text[0]],
            [mag,  xy_text[1]],
            pen=chart_style.pen(
                (r, g, b), chart_style.SCREEN.leader_width, chart_style.SCREEN.leader_dash,
                chart_style.SCREEN.leader_opacity),
            antialias=True,
        )

    # ── annotation lifecycle ──────────────────────────────────────────────────

    def create_annotation(
        self,
        freq: float,
        mag: float,
        html: str,
        mode_str: str,
        xy_text: tuple[float, float],
        peak_id: str = "",
    ) -> tuple[DraggableTextItem, pg.PlotDataItem]:
        """Create and add annotation items to the plot; return (text_item, arrow_line)."""
        color = self._mode_color(mode_str)
        text_item  = self._make_text_item(html, xy_text, color)
        arrow_line = self._make_arrow_line(freq, mag, xy_text, color)
        # Over the mode labels, as Swift's peak labels.
        arrow_line.setZValue(PEAK_LABEL_Z)
        text_item.setZValue(PEAK_LABEL_Z)
        self.plot_item.addItem(arrow_line)
        self.plot_item.addItem(text_item)
        # `_default_pos` is where the label sits undragged — its peak plus the default offset,
        # ignoring any stored position — where "Reset Position" returns it. The label is at
        # xy_text.
        default_pos = _LabelRule.annotation_centre_from(
            SimpleNamespace(id=peak_id, frequency=freq, magnitude=mag), None)
        text_item.connect_arrow(arrow_line, freq, mag, default_pos, peak_id, self._analyzer)
        return text_item, arrow_line

    def update_annotation(
        self, peak_id: str, freq: float, mag: float, html: str, mode_str: str
    ) -> None:
        """Create a new annotation or update an existing one for *freq*."""
        idx = self.find_annotation_index(freq)

        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                ann_dict["html"] = html
                ann_dict["mode_str"] = mode_str
                ann_dict["peak_id"] = peak_id
                xy_text = ann_dict["xytext"]
                ann, arrow_line = self.create_annotation(
                    freq, mag, html, mode_str, xy_text, peak_id
                )
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line
            else:
                self._refit(ann_dict, peak_id, freq, mag, html, mode_str, ann_dict["xytext"])
            return
        # The label's centre: where the user dragged it (the analyzer's stored positions, keyed by
        # peak id), else its peak plus the default offset — Swift's
        # annotationCentre(for:offsets:).
        xy_text = _LabelRule.annotation_centre_from(
            SimpleNamespace(id=peak_id, frequency=freq, magnitude=mag),
            self._analyzer.peak_annotation_offsets if self._analyzer is not None else None)
        reused = self._take_retired(peak_id, freq)
        if reused is not None:
            self._refit(reused, peak_id, freq, mag, html, mode_str, xy_text)
            self.annotations.append(reused)
            return
        ann, arrow_line = self.create_annotation(freq, mag, html, mode_str, xy_text, peak_id)
        self.annotations.append(
            {
                "peak_id":    peak_id,
                "freq":       freq,
                "annotation": ann,
                "arrow_line": arrow_line,
                "mag":        mag,
                "html":       html,
                "mode_str":   mode_str,
                "xytext":     xy_text,
                "style_key":  self._style_key(mode_str),
            }
        )

    def _style_key(self, mode_str: str) -> tuple:
        return (self._mode_color(mode_str), palette.rgb(palette.Role.CHART_READOUT_BACKGROUND))

    def _take_retired(self, peak_id: str, freq: float) -> "_AnnDict | None":
        """A label of the last refresh to show this peak: its own, else the nearest in frequency left — so it goes on
        showing much what it showed, and little about it changes."""
        shown = [d for d in self._retiring if d["annotation"] is not None]
        for d in shown:
            if peak_id and d["peak_id"] == peak_id:
                self._retiring.remove(d)
                return d
        if shown:
            nearest = min(shown, key=lambda d: abs(d["freq"] - freq))
            self._retiring.remove(nearest)
            return nearest
        return None

    def _refit(self, ann_dict: "_AnnDict", peak_id: str, freq: float, mag: float, html: str, mode_str: str,
               xy_text: tuple[float, float]) -> None:
        """Show this peak on an existing label, changing only what differs."""
        text_item = ann_dict["annotation"]
        arrow_line = ann_dict["arrow_line"]
        if html != ann_dict["html"]:
            text_item.set_html(html)
        style_key = self._style_key(mode_str)
        if ann_dict.get("style_key") != style_key:
            color = style_key[0]
            text_item.restyle(color)
            arrow_line.setPen(chart_style.pen(
                color, chart_style.SCREEN.leader_width, chart_style.SCREEN.leader_dash,
                chart_style.SCREEN.leader_opacity))
        default_pos = _LabelRule.annotation_centre_from(
            SimpleNamespace(id=peak_id, frequency=freq, magnitude=mag), None)
        text_item.connect_arrow(arrow_line, freq, mag, default_pos, peak_id, self._analyzer)
        text_item.setPos(xy_text[0], xy_text[1])
        text_item._update_arrow()
        ann_dict.update(peak_id=peak_id, freq=freq, mag=mag, html=html, mode_str=mode_str, xytext=xy_text,
                        style_key=style_key)

    def _drop_retired(self) -> None:
        """Remove the labels of the last refresh that the new one did not take."""
        self._retire_due = False
        for ann_dict in self._retiring:
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
        self._retiring = []

    # ── selection helpers ─────────────────────────────────────────────────────

    def select_annotation(self, item: object) -> bool:
        """Return True if *item* is one of the annotation text items."""
        return any(d["annotation"] is item for d in self.annotations)

    def find_annotation_index(self, freq: float) -> int:
        """Return the index of the annotation for *freq*, or -1."""
        return next(
            (i for i, item in enumerate(self.annotations) if item["freq"] == freq),
            -1,
        )

    # ── show / hide ───────────────────────────────────────────────────────────

    def clear_annotations(self) -> None:
        """Clear the list. Its labels stay on the chart until the refresh that follows has reused what it can
        (``update_annotation``); the rest go when it ends (``refresh_display``), or at the end of this event-loop
        turn if no refresh follows."""
        self._retiring.extend(self.annotations)
        self.annotations = []
        if not self._retire_due:
            self._retire_due = True
            QtCore.QTimer.singleShot(0, self, self._drop_retired)

    def refresh_display(self) -> None:
        """A refresh's labels are all in: remove the old ones it did not reuse, and repaint."""
        self._drop_retired()
        self.plot_item.vb.update()

    # ── drag completion ───────────────────────────────────────────────────────

    def annotation_moved(self, _event: object = None) -> None:
        """Persist updated xytext for all annotations after a drag completes.

        Also writes back to the analyzer's peak_annotation_offsets so that
        positions survive pan/zoom annotation rebuilds (mirrors Swift
        ``updateAnnotationOffset(for:offset:)`` called from the drag gesture).
        """
        for ann_dict in self.annotations:
            ann = ann_dict["annotation"]
            if ann is not None:
                pos = ann.pos()
                x, y = pos.x(), pos.y()
                ann_dict["xytext"] = (x, y)
                if self._analyzer is not None:
                    self._analyzer.update_annotation_offset(ann_dict["peak_id"], (x, y))
        self.restoreFocus.emit()

    # ── label reset ───────────────────────────────────────────────────────────

    @property
    def has_moved_annotations(self) -> bool:
        """True if any label has a stored position — what Reset Labels clears. Mirrors Swift's
        ``!peakAnnotationOffsets.isEmpty``."""
        return self._analyzer is not None and bool(self._analyzer.peak_annotation_offsets)

    def reset_all_positions(self) -> None:
        """Reset every visible annotation label to its default (auto-placed) position.

        Also clears the analyzer's saved offsets so the reset positions persist
        across subsequent pan/zoom rebuilds.
        """
        for ann_dict in self.annotations:
            ann = ann_dict["annotation"]
            if ann is not None and ann._default_pos is not None:
                ann.setPos(ann._default_pos)
                ann._update_arrow()
                ann_dict["xytext"] = (ann._default_pos.x(), ann._default_pos.y())
        if self._analyzer is not None:
            self._analyzer.reset_all_annotation_offsets()
        self.restoreFocus.emit()
