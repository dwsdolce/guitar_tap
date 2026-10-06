"""
Full-screen dimmed loading overlay with a spinner and message label.

Mirrors Swift LoadingOverlay.swift (Views/Shared/LoadingOverlay.swift).

Place an instance as a child of any QWidget by passing it the widget you want
to cover, then call show(message) / hide() as needed.  The overlay resizes
itself to fill its parent whenever the parent is resized.

Usage::

    overlay = LoadingOverlay(parent_widget)
    overlay.show_message("Generating PDF report…")
    # … do work …
    overlay.hide()
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.views.utilities import palette


class LoadingOverlay(QtWidgets.QWidget):
    """A semi-transparent full-parent-size overlay with a centred spinner card.

    Mirrors Swift LoadingOverlay struct (LoadingOverlay.swift).

    The overlay:
      - Fills its parent widget completely (resizes on parent resize events).
      - Shows the scrim over the parent (mirrors Palette.color(.scrim)).
      - Displays a centred rounded card containing a QMovie spinner and a
        message label (mirrors VStack { ProgressView() · Text(message) }).
      - Blocks all mouse/keyboard events from reaching widgets beneath it.
    """

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)

        # Cover the full parent and block interaction.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(QtCore.Qt.WindowType.Widget)

        # ── Card ──────────────────────────────────────────────────────────────
        card = QtWidgets.QFrame(self)
        card.setObjectName("loadingCard")
        card.setStyleSheet("#loadingCard { border-radius: 12px; }")
        palette.tag(card, background=palette.Role.OVERLAY_CARD)

        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(16)
        card_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Spinner (indeterminate progress indicator)
        self._spinner = QtWidgets.QProgressBar()
        self._spinner.setRange(0, 0)          # indeterminate / bouncing
        self._spinner.setTextVisible(False)
        self._spinner.setFixedHeight(6)
        self._spinner.setMinimumWidth(160)
        palette.tag(self._spinner, tint=palette.Role.TEXT_ON_COLOR)
        card_layout.addWidget(self._spinner, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        # Message label
        self._label = QtWidgets.QLabel()
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = self._label.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self._label.setFont(font)
        palette.tag(self._label, color=palette.Role.TEXT_ON_COLOR)
        card_layout.addWidget(self._label)

        # ── Center the card ───────────────────────────────────────────────────
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        row.addWidget(card)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch()

        self._card = card
        self.hide()

        # Install an event filter on the parent so we can resize ourselves.
        parent.installEventFilter(self)

    # ── Public API ────────────────────────────────────────────────────────────

    def show_message(self, message: str) -> None:
        """Show the overlay with the given message.

        Mirrors the Swift pattern of setting isGeneratingReport / isExportingSpectrum
        to True, which makes LoadingOverlay appear with the appropriate message string.
        """
        self._label.setText(message)
        self._fit_to_parent()
        self.raise_()
        self.show()
        # Force an immediate repaint so the overlay is visible before the
        # blocking operation starts.
        QtWidgets.QApplication.processEvents()

    # ── Resize tracking ───────────────────────────────────────────────────────

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is self.parent() and event.type() == QtCore.QEvent.Type.Resize:
            self._fit_to_parent()
        return super().eventFilter(obj, event)

    def _fit_to_parent(self) -> None:
        parent = self.parent()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())

    # ── Painting — the scrim ──────────────────────────────────────────────────

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), palette.color(palette.Role.SCRIM))
        painter.end()
