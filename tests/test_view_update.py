"""The view-update layer (views/utilities/view_update.py): one refresh per event-loop turn, children updated in
place, styles and roles applied only when they change."""

from __future__ import annotations

import shiboken6
from PySide6 import QtCore, QtWidgets

from guitar_tap.views.utilities import palette, view_update


class _Owner(QtCore.QObject):
    pass


class TestInvalidator:
    def test_many_invalidations_in_one_turn_refresh_once(self, qapp):
        owner = _Owner()
        calls = []
        inv = view_update.Invalidator(owner, lambda: calls.append(1))
        for _ in range(5):
            inv.invalidate()
        assert calls == [] and inv.pending
        qapp.processEvents()
        assert calls == [1] and not inv.pending

    def test_a_signals_arguments_are_ignored(self, qapp):
        owner = _Owner()
        calls = []
        inv = view_update.Invalidator(owner, lambda: calls.append(1))
        inv.invalidate(1, "two", None)
        qapp.processEvents()
        assert calls == [1]

    def test_flush_refreshes_now_and_only_once(self, qapp):
        owner = _Owner()
        calls = []
        inv = view_update.Invalidator(owner, lambda: calls.append(1))
        inv.invalidate()
        inv.flush()
        assert calls == [1]
        qapp.processEvents()
        assert calls == [1]

    def test_a_refresh_due_after_its_owner_is_gone_does_not_run(self, qapp):
        owner = _Owner()
        calls = []
        inv = view_update.Invalidator(owner, lambda: calls.append(1))
        inv.invalidate()
        shiboken6.delete(owner)
        qapp.processEvents()
        assert calls == []


class _Child:
    def __init__(self, key, kind="a"):
        self.key = key
        self.kind = kind
        self.updates = 0


def _sync(children, items, made, removed, can_reuse=lambda c, i: True):
    def make(item):
        child = _Child(item[0], item[1])
        made.append(child)
        return child

    def update(child, item):
        child.key = item[0]
        child.updates += 1

    return view_update.sync_children(
        children, items, item_key=lambda i: i[0], child_key=lambda c: c.key,
        make=make, update=update, remove=removed.append, can_reuse=can_reuse)


class TestSyncChildren:
    def test_children_with_matching_keys_are_kept_and_updated(self):
        a, b, c = _Child("a"), _Child("b"), _Child("c")
        made, removed = [], []
        result = _sync([a, b, c], [("c", "a"), ("a", "a")], made, removed)
        assert result == [c, a]
        assert made == [] and removed == [b]
        assert a.updates == 1 and c.updates == 1

    def test_new_keys_reuse_the_children_left_in_order(self):
        old = [_Child("x"), _Child("y")]
        made, removed = [], []
        result = _sync(old, [("p", "a"), ("q", "a")], made, removed)
        assert result == old
        assert [c.key for c in result] == ["p", "q"]
        assert made == [] and removed == []

    def test_more_items_make_children_and_fewer_remove_them(self):
        made, removed = [], []
        one = _Child("a")
        result = _sync([one], [("a", "a"), ("b", "a"), ("c", "a")], made, removed)
        assert result[0] is one and len(made) == 2
        made2, removed2 = [], []
        result2 = _sync(result, [("b", "a")], made2, removed2)
        assert result2 == [result[1]] and len(removed2) == 2

    def test_a_child_is_reused_only_where_allowed(self):
        old = _Child("x", kind="guitar")
        made, removed = [], []
        result = _sync([old], [("p", "material")], made, removed, can_reuse=lambda c, i: c.kind == i[1])
        assert result == made and removed == [old]


class TestSyncNearest:
    def test_given_a_distance_the_nearest_child_left_is_reused(self):
        low, high = _Child(100.0), _Child(300.0)
        result = view_update.sync_children(
            [low, high], [("a", 295.0)], item_key=lambda i: i[0], child_key=lambda c: c.key,
            make=lambda i: _Child(i[1]), update=lambda c, i: None, remove=lambda c: None,
            distance=lambda c, i: abs(c.key - i[1]))
        assert result == [high]


class _CountingLabel(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.sets = 0

    def setStyleSheet(self, css):  # noqa: N802 — Qt's name
        self.sets += 1
        super().setStyleSheet(css)


class TestStyles:
    def test_a_style_sheet_is_set_only_when_it_changes(self, qapp):
        label = _CountingLabel()
        view_update.set_style_sheet(label, "color: red;")
        view_update.set_style_sheet(label, "color: red;")
        assert label.sets == 1 and label.styleSheet() == "color: red;"
        view_update.set_style_sheet(label, "color: blue;")
        assert label.sets == 2

    def test_a_role_is_applied_only_when_it_changes(self, qapp, monkeypatch):
        calls = []
        real = palette.tag
        monkeypatch.setattr(palette, "tag", lambda w, **r: (calls.append(r), real(w, **r)))
        label = QtWidgets.QLabel()
        view_update.tag(label, color=palette.Role.TEXT_SECONDARY)
        view_update.tag(label, color=palette.Role.TEXT_SECONDARY)
        assert len(calls) == 1
        view_update.tag(label, color=palette.Role.TEXT_PRIMARY)
        assert len(calls) == 2
