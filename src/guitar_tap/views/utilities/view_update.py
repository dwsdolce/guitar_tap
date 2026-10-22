# @parity none — the part of SwiftUI's and React's view updating that Qt Widgets leaves to the app:
# gathering the
# changes of one moment into one refresh, updating a list's children in place, and applying a style only when it
# changes. Swift and the web get it from their frameworks, so there is no counterpart to mirror. Justified
# platform-only.
"""
Python's view-update layer: Swift's view contract on Qt Widgets.

In Swift a model change marks a view out of date; its ``body`` runs at most once per screen update and derives
everything from the model's state; ``ForEach(items, id:)`` adds, removes and updates rows by id; modifiers style it.
SwiftUI does the comparing and the batching. Qt does neither — every signal runs its slots at once, and a view that
rebuilds its widgets pays for every one — so this module does that part, once, for every view:

- :class:`Invalidator` — a model's signals only invalidate a view; the view's one ``refresh()`` runs once, at the
  end of the current event-loop turn, however many signals came.
- :func:`sync_children` — a list's children updated in place by key, as ``ForEach``: the child whose key matches is
  kept and updated, the rest added or removed. A list whose items get new keys every time (a live frame's peaks)
  reuses its leftover children in order, which Qt needs and SwiftUI does not.
- :func:`set_style_sheet` and :func:`tag` — a style or a role applied only when it differs from the last.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TypeVar

from PySide6 import QtCore, QtWidgets

from guitar_tap.views.utilities import palette

Child = TypeVar("Child")
Item = TypeVar("Item")


class Invalidator:
    """One refresh per event-loop turn for a view: ``invalidate()`` as often as signals come; ``refresh`` runs once,
    after the current event, on the main thread. ``owner`` bounds its life — a refresh due after the owner is gone
    does not run."""

    def __init__(self, owner: QtCore.QObject, refresh: Callable[[], None]) -> None:
        self._owner = owner
        self._refresh = refresh
        self._pending = False

    @property
    def pending(self) -> bool:
        """A refresh is due."""
        return self._pending

    def invalidate(self, *_args: object) -> None:
        """Mark the view out of date. Takes and ignores any signal's arguments, so it can be connected directly."""
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._owner, self._run)

    def flush(self) -> None:
        """Run a due refresh now — when a caller needs the view current before the turn ends."""
        if self._pending:
            self._run()

    def _run(self) -> None:
        if not self._pending:
            return
        self._pending = False
        self._refresh()


def sync_children(
    children: Sequence[Child],
    items: Sequence[Item],
    *,
    item_key: Callable[[Item], Hashable],
    child_key: Callable[[Child], Hashable],
    make: Callable[[Item], Child],
    update: Callable[[Child, Item], None],
    remove: Callable[[Child], None],
    can_reuse: Callable[[Child, Item], bool] = lambda _c, _i: True,
    distance: Callable[[Child, Item], float] | None = None,
) -> list[Child]:
    """The children for ``items``, in their order, reusing what can be reused — ``ForEach(items, id:)``.

    1. A child whose key is an item's key is kept for that item and updated.
    2. The items left get the children left, where ``can_reuse`` allows — each updated to its item: in order, or,
       given ``distance``, the nearest child left, so a child goes on showing much what it showed (a live frame's
       peak near the one it had) and little about it changes.
    3. Any item still without a child gets a new one (``make``); any child still unused is removed (``remove``).

    ``update`` is called for every kept or reused child; it should change only what differs. Returns the children in
    the items' order; placing them in that order is the caller's.
    """
    by_key: dict[Hashable, list[Child]] = {}
    for child in children:
        by_key.setdefault(child_key(child), []).append(child)

    result: list[Child | None] = [None] * len(items)
    used: set[int] = set()
    for i, item in enumerate(items):
        matches = by_key.get(item_key(item))
        if matches:
            child = matches.pop(0)
            used.add(id(child))
            update(child, item)
            result[i] = child

    leftovers = [c for c in children if id(c) not in used]
    for i, item in enumerate(items):
        if result[i] is not None:
            continue
        usable = [j for j, child in enumerate(leftovers) if can_reuse(child, item)]
        if usable:
            j = min(usable, key=lambda k: distance(leftovers[k], item)) if distance is not None else usable[0]
            child = leftovers.pop(j)
            update(child, item)
            result[i] = child
        else:
            result[i] = make(item)

    for child in leftovers:
        remove(child)
    return [c for c in result if c is not None]


_STYLE_PROPERTY = "_viewUpdateStyle"


def set_style_sheet(widget: QtWidgets.QWidget, css: str) -> None:
    """``widget.setStyleSheet(css)``, skipped when ``css`` is what the widget was last given — Qt parses a style
    sheet and re-styles the widget and its children on every set."""
    if widget.property(_STYLE_PROPERTY) == css:
        return
    widget.setProperty(_STYLE_PROPERTY, css)
    widget.setStyleSheet(css)


def tag(widget: QtWidgets.QWidget, **roles: object) -> None:
    """:func:`palette.tag`, skipped when the widget already carries these roles — ``palette.tag`` re-polishes the
    widget on every call."""
    key = tuple(sorted((name, getattr(value, "value", value)) for name, value in roles.items()))
    if widget.property("_viewUpdateRoles") == repr(key):
        return
    widget.setProperty("_viewUpdateRoles", repr(key))
    palette.tag(widget, **roles)
