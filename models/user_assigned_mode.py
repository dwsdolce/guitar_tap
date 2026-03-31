"""
User-assigned mode override for a resonant peak.

Mirrors Swift UserAssignedMode (UserAssignedMode.swift).

Controls whether a peak's displayed mode label comes from the automatic
GuitarMode classifier (.auto) or from a user-supplied string (.assigned).

The underlying GuitarMode classification — which governs the peak's colour,
icon, and in-range indicator — is never altered by a UserAssignedMode override;
only the text shown in the annotation and results table is changed.

JSON format:
  .auto     → {"type": "auto"}
  .assigned → {"type": "assigned", "label": "<user string>"}

Label stability:
  .assigned labels are literal strings and survive app updates unchanged.
  .auto labels are re-evaluated at display time by GuitarMode.classify(), so
  they may change if classification boundaries shift in a future release.
  Peaks near a boundary carry the highest risk of reclassification; prefer
  .assigned for long-term stability.
"""

from __future__ import annotations

from typing import Any


class UserAssignedMode:
    """
    Represents whether a peak's mode label is auto-detected or manually overridden.

    Mirrors Swift ``UserAssignedMode`` enum (UserAssignedMode.swift).

    Python does not have enums with associated values, so this is implemented
    as a small class with factory class-methods that mirror Swift's enum cases:

      UserAssignedMode.auto()           ↔  Swift .auto
      UserAssignedMode.assigned(label)  ↔  Swift .assigned(String)
    """

    def __init__(self, *, _type: str, _label: str | None = None) -> None:
        self._type = _type
        self._label = _label

    # ── Factory methods (mirrors Swift enum cases) ─────────────────────────────

    @classmethod
    def auto(cls) -> "UserAssignedMode":
        """Use the auto-detected label produced by GuitarMode.classify() at display time.

        Mirrors Swift UserAssignedMode.auto.
        """
        return cls(_type="auto")

    @classmethod
    def assigned(cls, label: str) -> "UserAssignedMode":
        """Display the user-supplied string instead of the auto-detected label.

        The string is stored verbatim in the JSON measurement file and is fully
        stable across app versions.

        Mirrors Swift UserAssignedMode.assigned(_:).
        """
        return cls(_type="assigned", _label=label)

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def is_auto(self) -> bool:
        """True when using the auto-detected label."""
        return self._type == "auto"

    @property
    def label(self) -> str | None:
        """The user-supplied label string, or None when is_auto is True."""
        return self._label

    # ── Codable ────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Encode as ``{"type":"auto"}`` or ``{"type":"assigned","label":"..."}``.

        Mirrors Swift UserAssignedMode.encode(to:).
        """
        if self._type == "assigned" and self._label:
            return {"type": "assigned", "label": self._label}
        return {"type": "auto"}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UserAssignedMode":
        """Decode from the keyed JSON format.

        Unknown ``type`` values are treated as ``.auto`` for forward compatibility.
        Mirrors Swift UserAssignedMode.init(from:).
        """
        if d.get("type") == "assigned":
            label = d.get("label", "")
            if label:
                return cls.assigned(label)
        return cls.auto()

    # ── Suggestion Lists (mirrors Swift static properties) ─────────────────────

    @staticmethod
    def guitar_tap_modes() -> list[str]:
        """Standard guitar tap-tone mode label strings from GuitarMode.current_cases.

        Mirrors Swift UserAssignedMode.guitarTapModes.
        Presented as the primary choices in the mode-override picker.
        """
        from .guitar_mode import GuitarMode
        return [m.display_name for m in GuitarMode.current_cases
                if m is not GuitarMode.UNKNOWN]

    @staticmethod
    def additional_modes() -> list[str]:
        """Extended mode label strings using acoustical physics T(m,n) notation.

        Mirrors Swift UserAssignedMode.additionalModes.
        Presented as secondary choices in the mode-override picker.
        """
        from .guitar_mode import GuitarMode
        return list(GuitarMode.additional_mode_labels)

    @classmethod
    def all_suggestions(cls) -> list[str]:
        """All suggestion strings: guitar_tap_modes + additional_modes.

        Mirrors Swift UserAssignedMode.allSuggestions.
        """
        return cls.guitar_tap_modes() + cls.additional_modes()

    @classmethod
    def longest_predefined_label(cls) -> str:
        """The longest predefined label string, used to size the mode label column.

        Mirrors Swift UserAssignedMode.longestPredefinedLabel.
        """
        suggestions = cls.all_suggestions()
        return max(suggestions, key=len) if suggestions else "Air (Helmholtz)"

    # ── Equality and hashing ───────────────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UserAssignedMode):
            return NotImplemented
        return self._type == other._type and self._label == other._label

    def __hash__(self) -> int:
        return hash((self._type, self._label))

    def __repr__(self) -> str:
        if self._type == "assigned":
            return f"UserAssignedMode.assigned({self._label!r})"
        return "UserAssignedMode.auto()"
