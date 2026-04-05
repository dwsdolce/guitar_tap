"""
Empty state placeholder widget.

Mirrors Swift's EmptyStateView.swift — a centred label shown when a list
has no items, with a title and an optional subtitle.

Usage::

    empty = EmptyStateView(
        title="No Saved Measurements",
        subtitle="Tap the guitar and click Save to store measurements for comparison.",
    )
    layout.addWidget(empty)
    empty.setVisible(not has_items)
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class EmptyStateView(QtWidgets.QWidget):
    """Centred placeholder shown when a list is empty."""

    def __init__(
        self,
        title: str = "No Items",
        subtitle: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        text = title
        if subtitle:
            text = f"{title}\n\n{subtitle}"

        label = QtWidgets.QLabel(text)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #888888;")
        layout.addWidget(label)
