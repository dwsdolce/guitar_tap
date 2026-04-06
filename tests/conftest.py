"""
pytest configuration for GuitarTap test suite.

Mirrors the Swift test-sandbox pattern (TapDisplaySettings.swift):
  - QSettings are redirected to an isolated "Dolcesfogato.tests/GuitarTap" suite
    (controlled by the PYTEST_CURRENT_TEST env-var check in AppSettings._s()).
  - The measurements file is redirected to $TMPDIR/com.guitartap.tests/
    (controlled by the PYTEST_CURRENT_TEST env-var check in measurements_file()).

This session-scoped fixture clears both at the start of every test run so
tests begin with a clean slate and never pollute the user's real preferences
or saved measurements.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure src/guitar_tap is importable before any test modules load.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))


@pytest.fixture(scope="session", autouse=True)
def _clear_test_sandbox():
    """Clear isolated QSettings and measurements file before the test session.

    Mirrors Swift's ``isolated.removePersistentDomain(forName: suiteName)``
    so every test run starts with factory defaults.
    """
    # QSettings — wipe the isolated suite.
    from PySide6 import QtCore
    isolated = QtCore.QSettings("Dolcesfogato.tests", "GuitarTap")
    isolated.clear()
    isolated.sync()

    # Measurements file — delete the isolated JSON if it exists.
    import tempfile
    test_file = os.path.join(
        tempfile.gettempdir(), "com.guitartap.tests", "saved_measurements.json"
    )
    if os.path.exists(test_file):
        os.remove(test_file)

    yield
    # No teardown needed; the isolated storage is separate from real user data.
