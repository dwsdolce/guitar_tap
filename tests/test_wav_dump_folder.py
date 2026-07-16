# @parity test/wav-dump-folder
"""Pin the shared WAV-dump-folder logic (FILE-PATHS-AND-NAMES-SPEC §4b).

Default folder, no-custom reachability, and the acquire/release write helper. The picker is manual
run-review. Two-way with Swift WavDumpFolderTests.swift (the web has no counterpart — a page can
only download to Downloads).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PySide6 import QtWidgets

from guitar_tap.models.wav_dump_folder import WavDumpFolder


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _clean_slate():
    """No custom folder, so the shared assertions are deterministic (pytest already isolates the
    QSettings suite via the PYTEST_CURRENT_TEST redirect)."""
    WavDumpFolder.use_default_folder()
    yield
    WavDumpFolder.use_default_folder()


def test_default_folder_ends_in_guitartap():
    assert WavDumpFolder.default_folder().name == "GuitarTap"


def test_no_custom_folder_is_reachable_and_current_is_default():
    assert WavDumpFolder.is_reachable() is True
    assert WavDumpFolder.current_folder() == WavDumpFolder.default_folder()


def test_has_custom_folder_false_by_default():
    assert WavDumpFolder.has_custom_folder() is False


def test_acquire_with_no_custom_folder_returns_the_default():
    acquired = WavDumpFolder.acquire_dump_folder()
    assert acquired is not None
    folder, release = acquired
    assert folder.name == "GuitarTap"
    release()  # no-op with no custom folder; must not raise


def test_gone_custom_folder_is_unreachable_and_acquire_skips():
    # A custom folder that no longer exists (renamed / moved / deleted): must be unreachable, and
    # acquire must skip (None) rather than silently fall back to the default. Python stores a plain
    # path, so this is the "folder must be where you put it" rule (Swift enforces it via the bookmark
    # path-comparison; that round-trip is manual run-review).
    from PySide6 import QtCore

    QtCore.QSettings("Dolcesfogato.tests", "guitar_tap").setValue("dump/folder", "/nonexistent/GuitarCaptures")
    assert WavDumpFolder.has_custom_folder() is True
    assert WavDumpFolder.is_reachable() is False
    assert WavDumpFolder.acquire_dump_folder() is None