"""
Empty state — shown where a list has no items: an icon, a title and a message, centred.

Mirrors Swift's EmptyStateView.swift: the icon at 60 pt in text.secondary, the title semibold and larger in
text.primary, the message in text.secondary.

Usage::

    empty = EmptyStateView(
        icon="mdi.inbox-outline",
        title="No Saved Measurements",
        message="Tap the guitar and click Save to store measurements for comparison.",
    )
    layout.addWidget(empty)
    empty.setVisible(not has_items)
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from guitar_tap.views.utilities import palette


class EmptyStateView(QtWidgets.QWidget):
    """An empty list's placeholder: an icon, a title and a message. Mirrors Swift ``EmptyStateView``."""

    def __init__(self, icon: str, title: str, message: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        palette.set_icon(icon_lbl, icon, palette.Role.TEXT_SECONDARY, 60)
        layout.addWidget(icon_lbl)

        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = title_lbl.font()
        font.setPointSizeF(font.pointSizeF() + 4)  # Swift's .title2 beside .body
        font.setWeight(font.Weight.DemiBold)
        title_lbl.setFont(font)
        palette.tag(title_lbl, color=palette.Role.TEXT_PRIMARY)
        layout.addWidget(title_lbl)

        message_lbl = QtWidgets.QLabel(message)
        message_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        message_lbl.setWordWrap(True)
        message_lbl.setContentsMargins(40, 0, 40, 0)
        palette.tag(message_lbl, color=palette.Role.TEXT_SECONDARY)
        layout.addWidget(message_lbl)
