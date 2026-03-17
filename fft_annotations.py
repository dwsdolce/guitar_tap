"""
    Annotations are used to display text and a line on the FFT Canvas plot.
"""

import pyqtgraph as pg
import pitch as pitch_c

from PyQt6 import QtCore, QtWidgets


class DraggableTextItem(pg.TextItem):
    """TextItem that updates its connected arrow line as it is dragged."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self._arrow_line: pg.PlotDataItem | None = None
        self._peak_freq: float = 0.0
        self._peak_mag: float = 0.0

    def connect_arrow(
        self, line: pg.PlotDataItem, freq: float, mag: float
    ) -> None:
        """Associate an arrow line and the peak coordinates it points to."""
        self._arrow_line = line
        self._peak_freq = freq
        self._peak_mag = mag

    def itemChange(self, change, value):
        if (
            change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
            and self._arrow_line is not None
        ):
            pos = self.pos()
            self._arrow_line.setData(
                [self._peak_freq, pos.x()], [self._peak_mag, pos.y()]
            )
        return super().itemChange(change, value)


class FftAnnotations(QtCore.QObject):
    """
    The annotations are a list of annotation dictionaries that contain the
    freq, magnitude, text, text location and the pyqtgraph items.
    These are kept from one accept sample to the next so they can be
    hidden or shown as desired.
    """

    restoreFocus: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(self, plot_widget: pg.PlotWidget):
        super().__init__()
        self.plot_item = plot_widget.getPlotItem()
        self.pitch: pitch_c.Pitch = pitch_c.Pitch(440)

        self.annotations = []
        self._note_ticks: list[tuple[float, str]] = []

    def _top_axis(self) -> pg.AxisItem:
        return self.plot_item.getAxis("top")

    def update_note_axis(
        self,
        create: bool,
        lower_freq: float,
        upper_freq: float,
        lower_note: str,
        upper_note: str,
    ) -> None:
        """Update the secondary x-axis (top) with note labels."""
        if create:
            if lower_freq not in [t[0] for t in self._note_ticks]:
                self._note_ticks.append((lower_freq, lower_note))
            if upper_freq not in [t[0] for t in self._note_ticks]:
                self._note_ticks.append((upper_freq, upper_note))
        else:
            self._note_ticks = [
                t
                for t in self._note_ticks
                if t[0] != lower_freq and t[0] != upper_freq
            ]

        self._top_axis().setTicks([self._note_ticks] if self._note_ticks else [[]])

    def _make_text_item(self, text: str, xy_text: tuple[float, float]) -> DraggableTextItem:
        """Create a draggable text item."""
        item = DraggableTextItem(text, anchor=(0.5, 0.5), color=(0, 0, 0))
        item.setPos(xy_text[0], xy_text[1])
        return item

    def _make_arrow_line(
        self, freq: float, mag: float, xy_text: tuple[float, float]
    ) -> pg.PlotDataItem:
        """Create a line from peak to text label."""
        return pg.PlotDataItem(
            [freq, xy_text[0]],
            [mag, xy_text[1]],
            pen=pg.mkPen("k", width=1),
        )

    def create_annotation(
        self, freq: float, mag: float, text: str, xy_text: tuple[float, float]
    ) -> tuple:
        """Create annotation items on the plot and return them."""
        text_item = self._make_text_item(text, xy_text)
        arrow_line = self._make_arrow_line(freq, mag, xy_text)

        self.plot_item.addItem(arrow_line)
        self.plot_item.addItem(text_item)
        text_item.connect_arrow(arrow_line, freq, mag)

        upper_freq, lower_freq = self.pitch.pitch_range(freq)
        upper_note = self.pitch.note(upper_freq)
        lower_note = self.pitch.note(lower_freq)

        upper_line = pg.InfiniteLine(
            pos=upper_freq,
            angle=90,
            pen=pg.mkPen("r", style=QtCore.Qt.PenStyle.DashLine),
        )
        lower_line = pg.InfiniteLine(
            pos=lower_freq,
            angle=90,
            pen=pg.mkPen("r", style=QtCore.Qt.PenStyle.DashLine),
        )
        self.plot_item.addItem(upper_line)
        self.plot_item.addItem(lower_line)

        self.update_note_axis(True, lower_freq, upper_freq, lower_note, upper_note)

        ann_range = dict(
            upper_line=upper_line,
            upper_freq=upper_freq,
            upper_note=upper_note,
            lower_line=lower_line,
            lower_freq=lower_freq,
            lower_note=lower_note,
        )
        return text_item, arrow_line, ann_range

    def update_annotation(self, freq: float, mag: float, text: str) -> None:
        """Update an annotation by creating a new one or updating an existing one."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                xy_text = ann_dict["xytext"]
                ann, arrow_line, ann_range = self.create_annotation(
                    freq, mag, text, xy_text
                )
                ann_dict["text"] = text
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line
                ann_dict["annotation_range"] = ann_range
            else:
                ann_dict["text"] = text
                ann_dict["annotation"].setText(text)
        else:
            xy_text = (freq + 10.0, mag + 10.0)
            ann, arrow_line, ann_range = self.create_annotation(
                freq, mag, text, xy_text
            )
            self.annotations.append(
                {
                    "freq": freq,
                    "annotation": ann,
                    "arrow_line": arrow_line,
                    "annotation_range": ann_range,
                    "mag": mag,
                    "text": text,
                    "xytext": xy_text,
                }
            )

    def select_annotation(self, item) -> bool:
        """Return True if item is one of the annotation text items."""
        return any(d["annotation"] is item for d in self.annotations)

    def find_annotation_index(self, freq: float) -> int:
        """Find annotation index by freq, return -1 if not found."""
        return next(
            (i for i, item in enumerate(self.annotations) if item["freq"] == freq),
            -1,
        )

    def show_annotation(self, freq: float) -> None:
        """Show an annotation for freq."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                ann, arrow_line, ann_range = self.create_annotation(
                    freq, ann_dict["mag"], ann_dict["text"], ann_dict["xytext"]
                )
                ann_dict["annotation"] = ann
                ann_dict["arrow_line"] = arrow_line
                ann_dict["annotation_range"] = ann_range

    def hide_annotation(self, freq: float) -> None:
        """Hide an annotation."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
                ann_dict["annotation"] = None
                ann_dict["arrow_line"] = None
            ann_range = ann_dict["annotation_range"]
            if ann_range is not None:
                self.plot_item.removeItem(ann_range["upper_line"])
                self.plot_item.removeItem(ann_range["lower_line"])
                self.update_note_axis(
                    False,
                    ann_range["lower_freq"],
                    ann_range["upper_freq"],
                    ann_range["lower_note"],
                    ann_range["upper_note"],
                )
                ann_dict["annotation_range"] = None

    def hide_annotations(self) -> None:
        """Hide all annotations."""
        for ann_dict in self.annotations:
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
                ann_dict["annotation"] = None
                ann_dict["arrow_line"] = None
            if ann_dict["annotation_range"] is not None:
                ann_range = ann_dict["annotation_range"]
                self.plot_item.removeItem(ann_range["upper_line"])
                self.plot_item.removeItem(ann_range["lower_line"])
                self.update_note_axis(
                    False,
                    ann_range["lower_freq"],
                    ann_range["upper_freq"],
                    ann_range["lower_note"],
                    ann_range["upper_note"],
                )
                ann_dict["annotation_range"] = None

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        for ann_dict in self.annotations:
            if ann_dict["annotation"] is not None:
                self.plot_item.removeItem(ann_dict["annotation"])
                self.plot_item.removeItem(ann_dict["arrow_line"])
            if ann_dict["annotation_range"] is not None:
                ann_range = ann_dict["annotation_range"]
                self.plot_item.removeItem(ann_range["upper_line"])
                self.plot_item.removeItem(ann_range["lower_line"])
                self.update_note_axis(
                    False,
                    ann_range["lower_freq"],
                    ann_range["upper_freq"],
                    ann_range["lower_note"],
                    ann_range["upper_note"],
                )
        self.annotations = []

    def annotation_moved(self, _event=None) -> None:
        """Update stored xytext for all annotations after a drag completes."""
        for ann_dict in self.annotations:
            ann = ann_dict["annotation"]
            if ann is not None:
                pos = ann.pos()
                ann_dict["xytext"] = (pos.x(), pos.y())
        self.restoreFocus.emit()
