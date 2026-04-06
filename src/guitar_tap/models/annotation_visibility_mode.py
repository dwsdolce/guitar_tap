"""AnnotationVisibilityMode — Python mirror of Swift's AnnotationVisibilityMode enum.

Swift definition (AnnotationVisibilityMode.swift):

    enum AnnotationVisibilityMode: String, Codable, CaseIterable {
        case all
        case selected
        case none
        var next: AnnotationVisibilityMode { ... }
        var iconName: String { ... }
        var label: String { ... }
    }

The raw string values ('all', 'selected', 'none') are the canonical serialized
form and match what Swift writes to JSON via Codable.

Using ``str, Enum`` means instances compare equal to their raw string values,
so existing code that tests ``mode == "selected"`` continues to work without
changes.
"""

from __future__ import annotations

from enum import Enum


class AnnotationVisibilityMode(str, Enum):
    """Controls which peak annotations are rendered on the spectrum chart.

    Mirrors Swift ``AnnotationVisibilityMode``.

    Raw values match the Swift Codable serialization ('all', 'selected', 'none')
    so JSON round-trips require no conversion.
    """

    ALL = "all"
    SELECTED = "selected"
    NONE = "none"

    @property
    def next(self) -> "AnnotationVisibilityMode":
        """Advance the visibility cycle: all → selected → none → all.

        Mirrors Swift ``AnnotationVisibilityMode.next``.
        """
        _cycle = [
            AnnotationVisibilityMode.ALL,
            AnnotationVisibilityMode.SELECTED,
            AnnotationVisibilityMode.NONE,
        ]
        return _cycle[(_cycle.index(self) + 1) % len(_cycle)]

    @property
    def icon_name(self) -> str:
        """QtAwesome icon name for this mode. Mirrors Swift ``iconName`` (SF Symbols → fa5).

        Swift uses SF Symbols: "eye", "star.fill", "eye.slash".
        Python maps to QtAwesome fa5 equivalents.
        """
        _map = {
            AnnotationVisibilityMode.ALL:      "fa5.eye",
            AnnotationVisibilityMode.SELECTED: "fa5.star",
            AnnotationVisibilityMode.NONE:     "fa5.eye-slash",
        }
        return _map[self]

    @property
    def label(self) -> str:
        """Short display label. Mirrors Swift ``label``.

        Returns 'All', 'Selected', or 'None'.
        """
        return self.value.capitalize()

    @classmethod
    def from_string(cls, value: str | None) -> "AnnotationVisibilityMode":
        """Parse any casing of the mode name, defaulting to SELECTED.

        Accepts: 'all', 'All', 'ALL', 'selected', 'Selected', 'none', 'None', None.
        Returns SELECTED for unrecognised values.
        """
        if value is None:
            return cls.SELECTED
        try:
            return cls(value.lower())
        except ValueError:
            return cls.SELECTED
