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
from typing import Any

import pyqtgraph as pg
from models import guitar_mode as gm

from PySide6 import QtCore, QtGui, QtWidgets

# Type alias for the annotation dict stored in FftAnnotations.annotations
_AnnDict = dict[str, Any]


# ── draggable, resettable annotation label ────────────────────────────────────

class DraggableTextItem(pg.TextItem):
    """Styled annotation badge that can be dragged and reset via RMB menu."""

    def __init__(
        self,
        anchor: tuple[float, float] = (0.5, 0.5),
        fill: QtGui.QBrush | None = None,
        border: QtGui.QPen | None = None,
    ) -> None:
        super().__init__(html="", anchor=anchor, fill=fill, border=border)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        self._arrow_line: pg.PlotDataItem | None = None
        self._peak_freq: float = 0.0
        self._peak_mag: float = 0.0
        self._default_pos: QtCore.QPointF | None = None

    # ── HTML content ──────────────────────────────────────────────────────────

    def set_html(self, html: str) -> None:
        """Update the label content and reflow the text bounding rect."""
        self.textItem.setHtml(html)
        # Qt only centres text when the document has a fixed width; set it to
        # the natural (widest-line) width so text-align:center is honoured.
        doc = self.textItem.document()
        doc.setTextWidth(doc.idealWidth())
        self.updateTextPos()

    def restyle(self, mode_color: tuple[int, int, int]) -> None:
        """Update fill and border colours when the mode changes."""
        r, g, b = mode_color
        self.fill   = pg.mkBrush(r, g, b, 25)
        self.border = pg.mkPen((r, g, b, 180), width=1.5)
        self.update()

    # ── arrow line ────────────────────────────────────────────────────────────

    def connect_arrow(
        self,
        line: pg.PlotDataItem,
        freq: float,
        mag: float,
        default_pos: tuple[float, float],
    ) -> None:
        """Associate the dashed connection line and record the default position."""
        self._arrow_line  = line
        self._peak_freq   = freq
        self._peak_mag    = mag
        self._default_pos = QtCore.QPointF(default_pos[0], default_pos[1])

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
        """RMB menu — matches Swift DraggablePeakAnnotation context menu."""
        has_moved = (
            self._default_pos is not None
            and (
                abs(self.pos().x() - self._default_pos.x()) > 1e-6
                or abs(self.pos().y() - self._default_pos.y()) > 1e-6
            )
        )
        menu = QtWidgets.QMenu()
        reset_action = menu.addAction("Reset Position")
        reset_action.setEnabled(has_moved)
        chosen = menu.exec(screen_pos)
        if chosen is reset_action and self._default_pos is not None:
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

    # Vertical offset (in dB) from peak to default label position.
    _LABEL_OFFSET_DB: float = 14.0

    def __init__(self, plot_widget: pg.PlotWidget, analyzer=None):
        super().__init__()
        self.plot_item = plot_widget.getPlotItem()
        self.annotations: list[_AnnDict] = []
        # Reference to the TapToneAnalyzer — used to persist dragged annotation
        # offsets across pan/zoom rebuilds (mirrors Swift peakAnnotationOffsets).
        self._analyzer = analyzer
        # Intercept QContextMenuEvent at the widget level so we can show our own
        # annotation menu before QGraphicsView::contextMenuEvent delivers to the
        # scene (where it would reach the ViewBox instead of our annotation items).
        self._plot_view = plot_widget
        plot_widget.installEventFilter(self)
        plot_widget.viewport().installEventFilter(self)

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
        return gm.GuitarMode.from_mode_string(mode_str).color

    def _make_text_item(
        self,
        html: str,
        xy_text: tuple[float, float],
        mode_color: tuple[int, int, int],
    ) -> DraggableTextItem:
        r, g, b = mode_color
        item = DraggableTextItem(
            anchor=(0.5, 0.5),
            fill=pg.mkBrush(r, g, b, 25),
            border=pg.mkPen((r, g, b, 180), width=1.5),
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
            pen=pg.mkPen(
                (r, g, b, 100),
                width=1.5,
                style=QtCore.Qt.PenStyle.DashLine,
            ),
        )

    # ── annotation lifecycle ──────────────────────────────────────────────────

    def create_annotation(
        self,
        freq: float,
        mag: float,
        html: str,
        mode_str: str,
        xy_text: tuple[float, float],
    ) -> tuple[DraggableTextItem, pg.PlotDataItem]:
        """Create and add annotation items to the plot; return (text_item, arrow_line)."""
        color = self._mode_color(mode_str)
        text_item  = self._make_text_item(html, xy_text, color)
        arrow_line = self._make_arrow_line(freq, mag, xy_text, color)
        self.plot_item.addItem(arrow_line)
        self.plot_item.addItem(text_item)
        text_item.connect_arrow(arrow_line, freq, mag, xy_text)
        return text_item, arrow_line

    def update_annotation(
        self, peak_id: str, freq: float, mag: float, html: str, mode_str: str
    ) -> None:
        """Create a new annotation or update an existing one for *freq*."""
        idx = self.find_annotation_index(freq)
        color = self._mode_color(mode_str)

        if idx >= 0:
            ann_dict = self.annotations[idx]
            ann_dict["html"]     = html
            ann_dict["mode_str"] = mode_str
            ann_dict["peak_id"]  = peak_id

            if ann_dict["annotation"] is None:
                xy_text = ann_dict["xytext"]
                ann, arrow_line = self.create_annotation(
                    freq, mag, html, mode_str, xy_text
                )
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line
            else:
                ann_dict["annotation"].set_html(html)
                ann_dict["annotation"].restyle(color)
                r, g, b = color
                ann_dict["arrow_line"].setPen(
                    pg.mkPen((r, g, b, 100), width=1.5,
                             style=QtCore.Qt.PenStyle.DashLine)
                )
        else:
            # Restore saved offset from the analyzer if the user previously dragged
            # this annotation — keyed by peak_id (UUID), mirrors Swift peakAnnotationOffsets.
            saved = (
                self._analyzer.peak_annotation_offsets.get(peak_id)
                if self._analyzer is not None and peak_id
                else None
            )
            xy_text = saved if saved is not None else (freq, mag + self._LABEL_OFFSET_DB)
            ann, arrow_line = self.create_annotation(
                freq, mag, html, mode_str, xy_text
            )
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
                }
            )

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

    def show_annotation(self, freq: float) -> None:
        """Show a previously hidden annotation."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                ann, arrow_line = self.create_annotation(
                    freq,
                    ann_dict["mag"],
                    ann_dict["html"],
                    ann_dict["mode_str"],
                    ann_dict["xytext"],
                )
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line

    def hide_annotation(self, freq: float) -> None:
        """Hide the annotation for *freq* without removing it from the list."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
                ann_dict["annotation"] = None
                ann_dict["arrow_line"] = None

    def hide_annotations(self) -> None:
        """Hide all annotations."""
        for ann_dict in self.annotations:
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
                ann_dict["annotation"] = None
                ann_dict["arrow_line"] = None

    def show_all_annotations(self) -> None:
        """Re-add all hidden annotations to the plot (inverse of hide_annotations)."""
        for ann_dict in self.annotations:
            if ann_dict["annotation"] is None:
                ann, arrow_line = self.create_annotation(
                    ann_dict["freq"],
                    ann_dict["mag"],
                    ann_dict["html"],
                    ann_dict["mode_str"],
                    ann_dict["xytext"],
                )
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line

    def clear_annotations(self) -> None:
        """Remove all annotations from the plot and clear the list."""
        for ann_dict in self.annotations:
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
        self.annotations = []

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
        """True if any visible annotation label has been dragged from its default position."""
        for ann_dict in self.annotations:
            ann = ann_dict["annotation"]
            if ann is None or ann._default_pos is None:
                continue
            dp = ann._default_pos
            pos = ann.pos()
            if abs(pos.x() - dp.x()) > 1e-6 or abs(pos.y() - dp.y()) > 1e-6:
                return True
        return False

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
            self._analyzer.clear_annotation_offsets()
        self.restoreFocus.emit()
