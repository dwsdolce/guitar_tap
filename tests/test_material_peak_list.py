# @parity none — Qt widgets reused across updates, and a hidden Qt widget kept from rebuilding; SwiftUI builds the
# plate / brace rows only when they are shown and has no reuse to test.
"""The plate / brace peak list: refreshed once per event-loop turn, only while shown, its rows updated in place."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.views import tap_tone_analysis_view as view


def _peaks(freqs):
    return [ResonantPeak(frequency=f, magnitude=-40.0 - i, quality=20.0, bandwidth=f / 20.0)
            for i, f in enumerate(freqs)]


def _settle(qapp):
    for _ in range(3):
        qapp.processEvents()
        qapp.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)


def _rows(widget):
    return [r for r in widget.findChildren(view._MaterialPeakRow)]


def _count_constructions(monkeypatch):
    made = []
    real = view._MaterialPeakRow.__init__

    def counting(self, *args, **kwargs):
        made.append(self)
        real(self, *args, **kwargs)

    monkeypatch.setattr(view._MaterialPeakRow, "__init__", counting)
    return made


def _complete_list(qapp, freqs):
    widget = view.MaterialPeakListWidget()
    widget.show()
    widget.set_complete(True)
    widget.update_peaks(_peaks(freqs))
    _settle(qapp)
    return widget


def test_a_hidden_list_builds_no_rows_until_it_is_shown(qapp, monkeypatch):
    made = _count_constructions(monkeypatch)
    widget = view.MaterialPeakListWidget()
    widget.set_complete(True)
    widget.update_peaks(_peaks([100.0, 200.0, 300.0]))
    widget.set_assignment(100.0, 200.0)
    _settle(qapp)
    assert made == []
    widget.show()
    _settle(qapp)
    assert len(made) == 3 and len(_rows(widget)) == 3


def test_changes_in_one_turn_refresh_once(qapp, monkeypatch):
    widget = view.MaterialPeakListWidget()
    widget.show()
    _settle(qapp)
    refreshes = []
    real = widget._refresh_rows
    monkeypatch.setattr(widget._refresh, "_refresh", lambda: (refreshes.append(1), real()))
    widget.set_complete(True)
    widget.update_peaks(_peaks([100.0, 200.0]))
    widget.set_assignment(100.0, 200.0)
    _settle(qapp)
    assert refreshes == [1]


def test_an_assignment_updates_the_rows_in_place(qapp, monkeypatch):
    widget = _complete_list(qapp, [100.0, 200.0, 300.0])
    rows = _rows(widget)
    made = _count_constructions(monkeypatch)
    widget.set_assignment(200.0, 300.0)
    _settle(qapp)
    assert made == [] and _rows(widget) == rows
    by_freq = {r.key[1]: r for r in rows}
    assert by_freq[200.0]._state[0] and by_freq[300.0]._state[0] and not by_freq[100.0]._state[0]


def test_fewer_peaks_remove_the_rows_left_over(qapp):
    widget = _complete_list(qapp, [100.0, 200.0, 300.0])
    widget.update_peaks(_peaks([200.0]))
    _settle(qapp)
    assert [r.key for r in _rows(widget)] == [("peak", 200.0)]


def test_a_mode_change_rebuilds_the_rows_with_its_badges(qapp):
    widget = view.MaterialPeakListWidget()
    widget.show()
    widget.set_mode(True, False)
    _settle(qapp)
    assert [len(r.roles) for r in _rows(widget)] == [2, 2]
    widget.set_mode(False, False)
    _settle(qapp)
    assert [len(r.roles) for r in _rows(widget)] == [1]
    assert all(isinstance(r, QtWidgets.QWidget) for r in _rows(widget))
