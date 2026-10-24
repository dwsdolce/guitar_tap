# @parity model/saved-measurements-order tests=test/saved-measurements-order
"""The order Saved Measurements shows the library in: its sort, direction and type filter.

The library keeps the order measurements were added, and sorting or filtering never changes it — they decide only
which measurements the list shows and in what order, so As Added is always there to return to. And which of the
library's entries are duplicates, for Delete Duplicates.

Mirrors Swift ``SavedMeasurementsOrder.swift``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from functools import cmp_to_key

from .measurement_type import MeasurementType


class SavedMeasurementsSort(Enum):
    """How Saved Measurements is sorted. Mirrors Swift ``SavedMeasurementsSort``."""

    AS_ADDED = "asAdded"
    DATE = "date"
    NAME = "name"
    TYPE = "type"

    @property
    def title(self) -> str:
        """The menu's word for it."""
        return {"asAdded": "As Added", "date": "Date", "name": "Name", "type": "Type"}[self.value]


@dataclass(frozen=True)
class Key:
    """What the order needs of one measurement: its name, the date it was made, and the type the list shows
    (``TapToneMeasurement.measurement_type_short_name``)."""

    name: str
    date: datetime.datetime
    type: str


#: The types the filter offers: the type menu's, in its order, then Comparison.
FILTER_TYPES: list[str] = [t.short_name for t in MeasurementType] + ["Comparison"]


def parse_date(timestamp: str) -> datetime.datetime:
    """A measurement's ISO-8601 timestamp as an aware datetime (a 'Z' suffix included)."""
    d = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def keys(measurements) -> list[Key]:
    return [Key(name=m.measurement_name or "", date=parse_date(m.timestamp), type=m.measurement_type_short_name)
            for m in measurements]


def _compare(a, b) -> int:
    return -1 if a < b else (1 if a > b else 0)


def duplicates(ids: list[str]) -> list[int]:
    """The positions of the library's duplicates: each entry whose id an earlier entry already has (ids compare
    case-insensitively). The first copy of each stays. Same id means same content — an edited measurement gets a
    new id — so a duplicate is an exact copy, such as a second import of the same file.
    Mirrors Swift ``SavedMeasurementsOrder.duplicates``."""
    seen: set[str] = set()
    out: list[int] = []
    for i, ident in enumerate(ids):
        key = ident.lower()
        if key in seen:
            out.append(i)
        seen.add(key)
    return out


def shown(keys: list[Key], sort: SavedMeasurementsSort, ascending: bool, filter: str | None) -> list[int]:
    """The positions in the library to show, in order: those of the ``filter`` type (all when None), sorted by
    ``sort`` in the given direction. Ties go by date, oldest first, then by position. Names compare
    case-insensitively; type order is the filter's, then a type it does not name ("—").
    Mirrors Swift ``SavedMeasurementsOrder.shown``."""
    def rank(t: str) -> int:
        return FILTER_TYPES.index(t) if t in FILTER_TYPES else len(FILTER_TYPES)

    def primary(a: int, b: int) -> int:
        if sort is SavedMeasurementsSort.AS_ADDED:
            return _compare(a, b)
        if sort is SavedMeasurementsSort.DATE:
            return _compare(keys[a].date, keys[b].date)
        if sort is SavedMeasurementsSort.NAME:
            return _compare(keys[a].name.lower(), keys[b].name.lower())
        return _compare(rank(keys[a].type), rank(keys[b].type))

    def order(a: int, b: int) -> int:
        by_key = primary(a, b) * (1 if ascending else -1)
        if by_key:
            return by_key
        return _compare(keys[a].date, keys[b].date) or _compare(a, b)

    return sorted((i for i, k in enumerate(keys) if filter is None or k.type == filter), key=cmp_to_key(order))
