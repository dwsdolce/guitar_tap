# @parity none — Qt closes every open popup when a window is shown; SwiftUI and the browser do not.
"""
A captured tap must not open a window, or Qt closes every open popup and menu.

Qt closes popups when a window is shown. A widget made visible before it has a parent is a window
of its own for a moment, so a peak-list rebuild that did that closed any pull-down the user had
open — in Settings, Saved Measurements or the main window — every time a tap was analysed. Drives
the real main window: Settings open with a pull-down showing, a recorded tap played through Play
File, and every window shown until the measurement completes recorded.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from tests.test_export_e2e import edges, window  # noqa: F401 — fixtures

TAP = str(Path(__file__).parent / "Tap Test 2.wav")
# The capture's stall check runs this long after the last chunk; the test waits it out, so nothing
# the capture scheduled is still pending when the window is deleted.
STALL_CHECK_SECONDS = 2.0


class _WindowsShown(QtCore.QObject):
    """Records each window shown, except the ones named."""

    def __init__(self, ignore: list[QtWidgets.QWidget]) -> None:
        super().__init__()
        self.ignore = ignore
        self.shown: list[str] = []

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt's name
        if (event.type() == QtCore.QEvent.Type.Show and isinstance(obj, QtWidgets.QWidget)
                and obj.isWindow() and obj not in self.ignore):
            self.shown.append(f"{type(obj).__name__} {obj.objectName()!r}")
        return False


def test_capture_with_a_popup_open_shows_no_window(qtbot, window):  # noqa: F811
    analyzer = window.fft_canvas.analyzer
    app = QtWidgets.QApplication.instance()
    ended = threading.Event()
    state: dict[str, object] = {}
    deadline = time.monotonic() + 30

    # Each step is a short timer callback, so the capture runs in the dialog's own event loop.
    def finish_when_captured() -> None:
        if (not ended.is_set() or not analyzer.is_measurement_complete) and time.monotonic() < deadline:
            QtCore.QTimer.singleShot(20, finish_when_captured)
            return
        app.removeEventFilter(state["watcher"])
        state["complete"] = analyzer.is_measurement_complete
        state["popup"] = state["combo"].view().window().isVisible()
        state["combo"].hidePopup()
        state["dialog"].reject()

    def open_popup_and_play() -> None:
        dlg = QtWidgets.QApplication.activeModalWidget()
        if dlg is None:
            QtCore.QTimer.singleShot(20, open_popup_and_play)
            return
        combo = next(c for c in dlg.findChildren(QtWidgets.QComboBox) if c.count() > 1)
        combo.showPopup()
        watcher = _WindowsShown(ignore=[dlg, combo.view().window()])
        app.installEventFilter(watcher)
        state.update(dialog=dlg, combo=combo, watcher=watcher)
        analyzer.play_file(TAP, on_finished=ended.set)
        QtCore.QTimer.singleShot(20, finish_when_captured)

    QtCore.QTimer.singleShot(0, open_popup_and_play)
    window._show_settings()
    qtbot.waitUntil(
        lambda: time.monotonic() - analyzer.last_chunk_wall_time > STALL_CHECK_SECONDS + 0.5,
        timeout=10_000)

    assert state["complete"], "the tap was not captured"
    assert state["watcher"].shown == [], f"windows shown during the capture: {state['watcher'].shown}"
    assert state["popup"], "the pull-down closed during the capture"
