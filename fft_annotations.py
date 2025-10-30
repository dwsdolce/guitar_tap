"""
    Annotations are used to display text and an arrow on the FFT Canvas plot.
"""

import matplotlib
from matplotlib import pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
import pitch as pitch_c

from PyQt6 import QtCore


class FftAnnotations(QtCore.QObject):
    """
    The annotations are a list of annotation dictionaries that contain the
    freq, magnitude, text, text location and the axes annotation object.
    These are kept from one accept sample to the next so they can be
    hidden or shown as desired.
    """

    restoreFocus: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(self, fig: FigureCanvasQTAgg, axes: list[plt.Axes], note_axis: plt.Axes):
        super().__init__()
        self.fft_axes = axes
        self.note_axis = note_axis
        self.fig: FigureCanvasQTAgg = fig
        self.pitch: pitch_c.Pitch = pitch_c.Pitch(440)

        self.selected_annotation = -1
        # An array of dictionaries where each dictionary
        # has all the information required to re-create an
        # annotation
        self.annotations = []

    def update_note_axis(self, create: bool, lower_freq: float, upper_freq: float, lower_note: str, upper_note: str):
        """Update the secondary x-axis with note labels."""
        # Get the current ticks and labels
        ticks = self.note_axis.get_xticks().tolist()
        labels = self.note_axis.get_xticklabels()

        if create:
            # Find the lower and upper freq ticks if they exist
            if lower_freq not in ticks:
                ticks.append(lower_freq)
                labels.append(f"{lower_note}")
            if upper_freq not in ticks:
                ticks.append(upper_freq)
                labels.append(f"{upper_note}")
        else:
            # Remove the lower and upper freq ticks if they exist
            if lower_freq in ticks:
                idx = ticks.index(lower_freq)
                ticks.pop(idx)
                labels.pop(idx)
            if upper_freq in ticks:
                idx = ticks.index(upper_freq)
                ticks.pop(idx)
                labels.pop(idx)

        # Reset the ticks and labels
        self.note_axis.set_xticks(ticks)
        self.note_axis.set_xticklabels(labels)

    def create_annotation(
        self, freq: float, mag: float, text: str, xy_text: tuple[float, float]
    ):
        """Create an annotation"""
        ann = self.fft_axes.annotate(
            text,
            xy=(freq, mag),
            xycoords="data",
            xytext=xy_text,
            textcoords="data",
            horizontalalignment="center",
            fontsize="large",
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3"),
        )
        ann.draggable()

        # Create Upper and Lower notes for the annotation range
        upper_freq, lower_freq = self.pitch.pitch_range(freq)
        upper_note = self.pitch.note(upper_freq)
        lower_note = self.pitch.note(lower_freq)
        upper_line = self.fft_axes.axvline(
            upper_freq, color="red", linestyle="--")
        lower_line = self.fft_axes.axvline(
            lower_freq, color="red", linestyle="--")

        self.update_note_axis(True, lower_freq, upper_freq,
                              lower_note, upper_note)

        return ann, dict(upper_line=upper_line, upper_freq=upper_freq, upper_note=upper_note, lower_line=lower_line, lower_freq=lower_freq, lower_note=lower_note)

    def update_annotation(self, freq: float, mag: float, text: str) -> None:
        """Update an annotation by creating a new one or updating an existing one.
        If the annotation dictionary exists then update the text in it.
        """
        # print("FftCanvas: add_annotation")
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                xy_text = self.annotations[idx]["xytext"]
                ann, ann_range = self.create_annotation(
                    freq, mag, text, xy_text)
                self.annotations[idx]["text"] = text
                self.annotations[idx]["annotation"] = ann
                self.annotations[idx]["annotation_range"] = ann_range
            else:
                self.annotations[idx]["text"] = text
                self.annotations[idx]["annotation"].set_text(text)
        else:
            xy_text = (freq + 10.0, mag + 10.0)
            ann, ann_range = self.create_annotation(freq, mag, text, xy_text)
            ann_element = {
                "freq": freq,
                "annotation": ann,
                "annotation_range": ann_range,
                "mag": mag,
                "text": text,
                "xytext": xy_text,
            }
            self.annotations.append(ann_element)
        self.fig.canvas.draw()

    def select_annotation(self, artist: matplotlib.artist) -> bool:
        """Set the selected_annotation to the artist otherwise clear
        the selected_annotation.
        """
        ann_index = next(
            (
                i
                for i, item in enumerate(self.annotations)
                if item["annotation"] == artist
            ),
            -1,
        )
        if ann_index >= 0:
            self.selected_annotation = ann_index
            return True
        self.selected_annotation = -1
        return False

    def find_annotation_index(self, freq: float) -> None:
        """Find an annotation from an index."""
        # print("FftCanvas: find_annotation")
        return next(
            (i for i, item in enumerate(self.annotations)
             if item["freq"] == freq), -1
        )

    def show_annotation(self, freq: float) -> None:
        """Show an annotation index from freq."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            if ann_dict["annotation"] is None:
                mag = self.annotations[idx]["mag"]
                text = self.annotations[idx]["text"]
                xy_text = self.annotations[idx]["xytext"]
                ann, ann_range = self.create_annotation(
                    freq, mag, text, xy_text)
                self.annotations[idx]["annotation"] = ann
                self.annotations[idx]["annotation_range"] = ann_range

    def hide_annotation(self, freq: float) -> None:
        """Hide an annotation."""
        idx = self.find_annotation_index(freq)
        if idx >= 0:
            ann_dict = self.annotations[idx]
            ann = ann_dict["annotation"]
            if ann is not None:
                ann.remove()
                ann_dict["annotation"] = None
                self.fig.canvas.draw()
            ann_range = ann_dict["annotation_range"]
            if ann_range is not None:
                ann_range["upper_line"].remove()
                ann_range["lower_line"].remove()

                # Remove upper and lower note ticks from secondary axis
                self.update_note_axis(
                    False, ann_range["lower_freq"], ann_range["upper_freq"], ann_range["lower_note"], ann_range["upper_note"])
                ann_dict["annotation_range"] = None
                self.fig.canvas.draw()

    def hide_annotations(self) -> None:
        """Hide all annotations."""
        # print(f"FftCanvas: hide_annotations")
        for ann_dict in self.annotations:
            # print(f"FftCanvas: hide_annotations: ann: freq: {ann_dict['freq']}")
            ann = ann_dict["annotation"]
            if ann is not None:
                ann.remove()
                ann_dict["annotation"] = None
            if ann_dict["annotation_range"] is not None:
                ann_range = ann_dict["annotation_range"]
                ann_range["upper_line"].remove()
                ann_range["lower_line"].remove()
                # Remove upper and lower note ticks from secondary axis
                self.update_note_axis(
                    False, ann_range["lower_freq"], ann_range["upper_freq"], ann_range["lower_note"], ann_range["upper_note"])
                ann_dict["annotation_range"] = None
        self.fig.canvas.draw()

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        # print("FftCanvas: clear_annotations")
        for ann_dict in self.annotations:
            ann_dict["annotation"].remove()
            if ann_dict["annotation_range"] is not None:
                ann_range = ann_dict["annotation_range"]
                ann_range["upper_line"].remove()
                ann_range["lower_line"].remove()
                self.update_note_axis(
                    False, ann_range["lower_freq"], ann_range["upper_freq"], ann_range["lower_note"], ann_range["upper_note"])

                # Remove upper and lower note ticks from secondary axis
                # TBD
        self.annotations = []
        self.fig.canvas.draw()

    def annotation_moved(self, _event) -> None:
        """Process the event for mouse release - i.e. completion of annotation moved."""
        # print(f"FftCanvas: annotation_moved: xdata, ydata: {event.xdata}, {event.ydata}")
        if self.selected_annotation >= 0:
            ann = self.annotations[self.selected_annotation]["annotation"]
            # print(f"annotation_moved: xyann: {ann.xyann}")
            self.annotations[self.selected_annotation]["xytext"] = ann.xyann

            self.selected_annotation = -1
        self.restoreFocus.emit()
