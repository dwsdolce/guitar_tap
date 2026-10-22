"""The results list and the chart's peak labels are updated in place: a live frame (the same number of peaks, every
one with a new id) and a range change (a subset of the same peaks) build no new cards or labels; those left over
are removed."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtWidgets

from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.views import peak_annotations
from guitar_tap.views.shared import peak_card_widget


def _frame(freqs):
    """One frame's peaks: new objects, so new ids, as a live frame's."""
    return [ResonantPeak(frequency=f, magnitude=-50.0 - i, quality=20.0, bandwidth=f / 20.0)
            for i, f in enumerate(freqs)]


def _count_constructions(monkeypatch, cls):
    made = []
    real = cls.__init__

    def counting(self, *args, **kwargs):
        made.append(self)
        real(self, *args, **kwargs)

    monkeypatch.setattr(cls, "__init__", counting)
    return made


class TestCards:
    def _list(self):
        widget = peak_card_widget.PeakListWidget()
        widget.model.is_live = True
        return widget

    def test_a_live_frame_reuses_every_card(self, qapp, monkeypatch):
        widget = self._list()
        widget.update_data_with_modes([(p, GuitarMode.AIR) for p in _frame([100.0, 200.0, 300.0])])
        cards = list(widget._cards)
        made = _count_constructions(monkeypatch, peak_card_widget.PeakCardWidget)
        frame = _frame([101.0, 199.0, 302.0])
        widget.update_data_with_modes([(p, GuitarMode.AIR) for p in frame])
        assert made == []
        assert widget._cards == cards
        assert [c.peak_id for c in widget._cards] == [p.id for p in frame]
        assert [round(c.freq) for c in widget._cards] == [101, 199, 302]

    def test_a_range_change_keeps_each_peaks_card_and_removes_the_rest(self, qapp, monkeypatch):
        widget = self._list()
        peaks = _frame([100.0, 200.0, 300.0, 400.0])
        widget.update_data_with_modes([(p, GuitarMode.AIR) for p in peaks])
        by_id = {c.peak_id: c for c in widget._cards}
        made = _count_constructions(monkeypatch, peak_card_widget.PeakCardWidget)
        widget.update_data_with_modes([(p, GuitarMode.AIR) for p in peaks[1:3]])
        assert made == []
        assert widget._cards == [by_id[peaks[1].id], by_id[peaks[2].id]]


class TestLabels:
    def _labels(self):
        return peak_annotations.FftAnnotations(pg.PlotWidget())

    def _refresh(self, labels, peaks):
        """As PeaksModel's refresh: clear, one update per label, then refreshed."""
        labels.clear_annotations()
        for p in peaks:
            labels.update_annotation(p.id, p.frequency, p.magnitude, f"<b>{p.frequency:.0f}</b>", "Air (Helmholtz)")
        labels.refresh_display()

    def _on_chart(self, labels):
        return [i for i in labels.plot_item.vb.addedItems if isinstance(i, peak_annotations.DraggableTextItem)]

    def test_a_live_frame_reuses_every_label(self, qapp, monkeypatch):
        labels = self._labels()
        self._refresh(labels, _frame([100.0, 200.0, 300.0]))
        items = [d["annotation"] for d in labels.annotations]
        made = _count_constructions(monkeypatch, peak_annotations.DraggableTextItem)
        frame = _frame([101.0, 199.0, 302.0])
        self._refresh(labels, frame)
        assert made == []
        assert [d["annotation"] for d in labels.annotations] == items
        assert [d["peak_id"] for d in labels.annotations] == [p.id for p in frame]
        assert [round(i.pos().x()) for i in items] == [101, 199, 302]
        assert len(self._on_chart(labels)) == 3

    def test_fewer_peaks_remove_the_labels_left_over(self, qapp):
        labels = self._labels()
        self._refresh(labels, _frame([100.0, 200.0, 300.0]))
        self._refresh(labels, _frame([150.0]))
        assert len(labels.annotations) == 1
        assert len(self._on_chart(labels)) == 1

    def test_a_clear_with_no_refresh_after_it_removes_every_label(self, qapp):
        labels = self._labels()
        self._refresh(labels, _frame([100.0, 200.0]))
        labels.clear_annotations()
        QtWidgets.QApplication.processEvents()
        assert labels.annotations == [] and self._on_chart(labels) == []
