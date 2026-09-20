"""
pytest configuration for GuitarTap test suite.

Mirrors the Swift test-sandbox pattern (TapDisplaySettings.swift): QSettings and the saved
measurements file are redirected somewhere disposable so a run never touches real user data.
Both destinations come from ``guitar_tap.models.settings_scope`` — the single place that decides
where persistent state lives.

The sandbox is PER PROCESS (``GT_TEST_SANDBOX``, set below before anything reads settings). It was
a fixed name until 2026-09-20, which meant one shared settings file and one shared temp directory
for every pytest process on the machine — and since this fixture CLEARS them at session start,
launching a second run wiped the settings of a run already in flight. The victim carried on with
default settings: a different guitar type, so different mode bands, so different peak
classification. See settings_scope.py for the flake that cost.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the guitar_tap package is importable before any test modules load.
# Only src/ goes on the path: adding src/guitar_tap as well would make models/ and
# views/ importable as TOP-LEVEL packages too, giving every module two identities
# (`models.x` and `guitar_tap.models.x`) with distinct class objects.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# Claim this process's sandbox BEFORE any test module imports code that reads settings. A fixture
# would be too late: collection imports test modules, and those import the analyzer.
os.environ.setdefault("GT_TEST_SANDBOX", str(os.getpid()))


@pytest.fixture(scope="session", autouse=True)
def _clear_test_sandbox():
    """Clear this process's isolated QSettings and measurements file, then remove them after.

    Mirrors Swift's ``isolated.removePersistentDomain(forName: suiteName)`` so every test run
    starts with factory defaults. Scoped to THIS process (see the module docstring), so clearing
    can no longer disturb a concurrently running suite.
    """
    from guitar_tap.models.settings_scope import APP, measurements_dir, settings_org

    org = settings_org()

    # QSettings — wipe this process's suite, and reap any left by runs that died before teardown.
    from PySide6 import QtCore

    from guitar_tap.models.settings_scope import reap_stale_sandboxes

    isolated = QtCore.QSettings(org, APP)
    own_file = isolated.fileName()
    isolated.clear()
    isolated.sync()
    reap_stale_sandboxes(own_file)

    # Measurements file — delete the isolated JSON if it exists.
    test_dir = measurements_dir("")
    test_file = os.path.join(test_dir, "saved_measurements.json")
    if os.path.exists(test_file):
        os.remove(test_file)

    yield

    # Teardown — the sandbox is per-process now, so it would otherwise accumulate one QSettings
    # file (and temp directory) per run, forever. Clearing a suite only empties it; the file has to
    # be removed explicitly.
    #
    # This is BEST EFFORT and often does not stick: QSettings flushes again when the object is
    # destroyed, which happens after this fixture, so the file reappears. The reap at session start
    # is what actually collects it — along with anything left by a run that crashed or was killed.
    # Do not "fix" this by trying harder here; cleanup that depends on a clean exit is the thing
    # that failed in the first place.
    isolated = QtCore.QSettings(org, APP)
    isolated.clear()
    isolated.sync()
    if own_file and os.path.exists(own_file):
        try:
            os.remove(own_file)
        except OSError:
            pass
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
