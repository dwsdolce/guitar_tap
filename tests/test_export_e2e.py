"""
Export regression: drive the real main window as a user does.

Each case is imported through Saved Measurements → Import, then exported as the spectrum image
and the PDF report from both places the app offers them: the main window, with the import loaded,
and the row's menu in Saved Measurements. Only the edges are replaced — the open and save file
dialogs return a path, message boxes are answered, and there is no microphone, as on a CI runner.
Everything between the click and the file is the app's own code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sounddevice
from PySide6 import QtCore, QtTest, QtWidgets

FIXTURES = Path(__file__).parent

# The fixtures are Swift's, since Swift's exports are the expected ones.
CASES = [
    ("guitar", "dws-2024-umik-1-swift-mac-1784225155.guitartap"),
    ("multi-tap", "dws-2024-umik-1-3-tap-swift-mac-1785359425.guitartap"),
    ("plate", "plate-umik-1-swift-mac-1785359486.guitartap"),
    ("brace", "brace-umik-1-swift-mac-1785359411.guitartap"),
    ("comparison", "5-guitar-comparison-1776708138.guitartap"),
]


class _Edges:
    """The replaced edges: what the open dialog returns, where saves land, the messages shown."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.open_path = ""
        self.prefix = ""
        self.saved: list[Path] = []
        self.messages: list[tuple[str, str]] = []

    def get_open(self, *_args, **_kwargs):
        return self.open_path, ""

    def get_save(self, _parent=None, _caption="", directory="", *_args, **_kwargs):
        path = self.out_dir / f"{self.prefix}{Path(directory).name}"
        self.saved.append(path)
        return str(path), ""

    def message(self, _parent, title, text, *_args, **_kwargs):
        self.messages.append((title, text))
        return QtWidgets.QMessageBox.StandardButton.Ok


@pytest.fixture
def edges(monkeypatch, tmp_path) -> _Edges:
    e = _Edges(tmp_path)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(e.get_open))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", staticmethod(e.get_save))
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(e.message))

    # No microphone: no input devices, and opening a stream fails as PortAudio does without one.
    def no_stream(*_args, **_kwargs):
        raise sounddevice.PortAudioError("no input device")

    def no_devices(*args, **_kwargs):
        if args:
            raise sounddevice.PortAudioError("no input device")
        return []

    monkeypatch.setattr(sounddevice, "InputStream", no_stream)
    monkeypatch.setattr(sounddevice, "query_devices", no_devices)
    return e


@pytest.fixture
def window(qtbot, edges):
    from guitar_tap.models.settings_scope import measurements_dir
    from guitar_tap.views.tap_tone_analysis_view import MainWindow

    # Each test starts with an empty library, so the list's one row is the measurement it imported.
    library = Path(measurements_dir("")) / "saved_measurements.json"
    library.unlink(missing_ok=True)

    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    # The canvas and the analyzer are built on the first event-loop pass after the window shows.
    qtbot.waitUntil(lambda: hasattr(w, "fft_canvas"), timeout=20_000)
    # With no microphone the app starts and reports it, as Swift's view does.
    assert any(title == "Audio Engine Error" for title, _ in edges.messages), edges.messages
    yield w
    # Delete the window, not just close it: in the app, closing it quits, but here the process
    # goes on and a closed window's handlers would still answer app-wide signals (a scheme change)
    # for the tests that follow.
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _when(qtbot, find, act, timeout_ms: int = 10_000) -> None:
    """Run ``act(widget)`` once ``find()`` returns a widget — for a modal dialog or menu, which
    opens its own event loop, so the test's next step is scheduled before the click opening it."""
    deadline = QtCore.QDeadlineTimer(timeout_ms)

    def poll() -> None:
        widget = find()
        if widget is not None:
            act(widget)
        elif not deadline.hasExpired():
            QtCore.QTimer.singleShot(20, poll)

    QtCore.QTimer.singleShot(0, poll)


def _modal_list():
    w = QtWidgets.QApplication.activeModalWidget()
    return w if w is not None and w.isVisible() and _button(w, "Import") is not None else None


def _menu():
    w = QtWidgets.QApplication.activePopupWidget()
    return w if isinstance(w, QtWidgets.QMenu) and w.isVisible() else None


def _button(parent: QtWidgets.QWidget, text: str) -> QtWidgets.QAbstractButton | None:
    for b in parent.findChildren(QtWidgets.QAbstractButton):
        if b.text().replace("&", "") == text and b.isVisible():
            return b
    return None


def _click(widget: QtWidgets.QWidget | None) -> None:
    # Qt aborts the process on a click at no widget, so a missing control fails here instead.
    assert widget is not None, "control not found"
    QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)


def _choose(menu: QtWidgets.QMenu, text: str) -> None:
    action = next(a for a in menu.actions() if a.text().replace("&&", "&") == text)
    pos = menu.actionGeometry(action).center()
    QtTest.QTest.mouseClick(menu, QtCore.Qt.MouseButton.LeftButton, pos=pos)


def _close_list(dlg: QtWidgets.QWidget) -> None:
    for text in ("Done", "Close"):
        b = _button(dlg, text)
        if b is not None:
            _click(b)
            return
    dlg.close()


def _import(qtbot, window, edges: _Edges, fixture: str) -> None:
    """Saved Measurements → Import the fixture, then close the list."""
    edges.open_path = str(FIXTURES / fixture)

    def in_list(dlg: QtWidgets.QWidget) -> None:
        _click(_button(dlg, "Import"))
        _close_list(dlg)

    _when(qtbot, _modal_list, in_list)
    _click(window.open_measurements_btn)
    assert any(title == "Import Successful" for title, _ in edges.messages), edges.messages


def _row_menu_export(qtbot, window, edges: _Edges, item: str) -> None:
    """Saved Measurements → the only row's ⋯ menu → ``item``, then close the list."""

    def in_list(dlg: QtWidgets.QWidget) -> None:
        def in_menu(menu: QtWidgets.QMenu) -> None:
            _choose(menu, item)
            QtCore.QTimer.singleShot(0, lambda: _close_list(dlg))

        _when(qtbot, _menu, in_menu)
        _click(_button(dlg, "⋯"))

    _when(qtbot, _modal_list, in_list)
    _click(window.open_measurements_btn)


def _saved_once(edges: _Edges, before: int, suffix: str) -> Path:
    new = edges.saved[before:]
    assert len(new) == 1, f"expected one save, got {new}; messages: {edges.messages}"
    path = new[0]
    assert path.suffix == suffix and path.is_file() and path.stat().st_size > 0, path
    return path


@pytest.mark.parametrize(("name", "fixture"), CASES, ids=[c[0] for c in CASES])
def test_export_from_main_window(qtbot, window, edges, name, fixture):
    _import(qtbot, window, edges, fixture)
    edges.prefix = "main-"

    qtbot.waitUntil(window.export_spectrum_btn.isEnabled, timeout=10_000)
    before = len(edges.saved)
    _click(window.export_spectrum_btn)
    _saved_once(edges, before, ".png")

    before = len(edges.saved)
    _click(window.export_pdf_btn)
    _saved_once(edges, before, ".pdf")


@pytest.mark.parametrize(("name", "fixture"), CASES, ids=[c[0] for c in CASES])
def test_export_from_saved_measurements(qtbot, window, edges, name, fixture):
    _import(qtbot, window, edges, fixture)
    edges.prefix = "saved-"

    stem = Path(fixture).stem
    before = len(edges.saved)
    _row_menu_export(qtbot, window, edges, "Export Spectrum")
    assert _saved_once(edges, before, ".png").stem == f"saved-{stem}"

    before = len(edges.saved)
    _row_menu_export(qtbot, window, edges, "Export PDF Report")
    assert _saved_once(edges, before, ".pdf").stem == f"saved-{stem}"
