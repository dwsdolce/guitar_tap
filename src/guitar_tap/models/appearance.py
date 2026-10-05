# @parity model/appearance tests=test/theme
"""The Appearance setting — follow the operating system, or always Light, or always Dark — and the
scheme it resolves to. Every colour the app draws is chosen by the resolved scheme. Mirrors Swift
``Appearance``."""

from __future__ import annotations

from enum import Enum


class Scheme(Enum):
    """The colour scheme the app is drawn in."""

    LIGHT = "light"
    DARK = "dark"


class Appearance(Enum):
    """The user's Appearance setting."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @property
    def label(self) -> str:
        """The label shown in Settings."""
        return {
            Appearance.SYSTEM: "System", Appearance.LIGHT: "Light", Appearance.DARK: "Dark",
        }[self]

    def resolved(self, os: Scheme | None) -> Scheme:
        """The scheme drawn when the operating system reports ``os`` (``None`` when it reports
        none): the setting when Light or Dark, else the operating system's, with none taken as
        Light."""
        if self is Appearance.LIGHT:
            return Scheme.LIGHT
        if self is Appearance.DARK:
            return Scheme.DARK
        return os or Scheme.LIGHT
