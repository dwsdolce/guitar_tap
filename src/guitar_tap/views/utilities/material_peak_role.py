# @parity view/material-peak-role
"""The role an identified plate or brace peak plays — its name, colour and badge wherever a peak is
shown by its role: the results panel's fL / fC / fLC badges and Measurement Details.

Mirrors Swift MaterialPeakRole."""

from __future__ import annotations

from enum import Enum

from PySide6 import QtGui, QtWidgets

from guitar_tap.views.utilities import palette


class MaterialPeakRole(Enum):
    LONGITUDINAL = "Longitudinal"
    CROSS = "Cross-grain"
    FLC = "Diagonal"

    @property
    def display_name(self) -> str:
        return self.value

    @property
    def badge_label(self) -> str:
        """The badge's text — the frequency the role measures."""
        return {
            MaterialPeakRole.LONGITUDINAL: "fL",
            MaterialPeakRole.CROSS: "fC",
            MaterialPeakRole.FLC: "fLC",
        }[self]

    @property
    def badge_width(self) -> int:
        """fLC is wider for its third letter."""
        return 42 if self is MaterialPeakRole.FLC else 36

    @property
    def palette_role(self) -> palette.Role:
        return {
            MaterialPeakRole.LONGITUDINAL: palette.Role.MATERIAL_LONGITUDINAL,
            MaterialPeakRole.CROSS: palette.Role.MATERIAL_CROSS,
            MaterialPeakRole.FLC: palette.Role.MATERIAL_FLC,
        }[self]

    @classmethod
    def from_display_name(cls, name: str) -> "MaterialPeakRole | None":
        return next((r for r in cls if r.value == name), None)


def phase_badge(role: MaterialPeakRole, active: bool = True) -> QtWidgets.QPushButton:
    """A role's badge: filled in its colour with white text when active, grey otherwise. Mirrors
    Swift MaterialPhaseBadge."""
    btn = QtWidgets.QPushButton(role.badge_label)
    fnt = QtGui.QFont()
    fnt.setBold(True)
    fnt.setPointSize(8)
    btn.setFont(fnt)
    btn.setFixedSize(role.badge_width, 32)
    btn.setStyleSheet("QPushButton {border-radius: 6px; border: none;}")
    palette.tag(
        btn,
        color=palette.Role.TEXT_ON_COLOR if active else palette.Role.TEXT_PRIMARY,
        background=role.palette_role if active else palette.Role.MATERIAL_PHASE_INACTIVE,
    )
    return btn
