"""Where persistent state lives: the user's real scope, or a PER-PROCESS test sandbox.

Mirrors Swift's ``XCTestConfigurationFilePath`` redirect — under test, QSettings and the saved
measurements file move somewhere disposable so a run never touches real preferences.

**The sandbox name carries the process id, and that is the point.** It used to be the fixed
``Dolcesfogato.tests`` / ``com.guitartap.tests``: one settings file and one directory shared by
every process on the machine. ``conftest`` clears both at session start "so every test run starts
with factory defaults", so starting a second pytest run wiped the settings of one already in
flight. The victim kept running with defaults — which meant a different GUITAR TYPE, hence
different mode bands, hence different peak classification.

That surfaced as `test_file_playback_regression.py` REG-G2 intermittently reporting the wrong
averaged Top (201.56 Hz instead of 164.05 Hz) with the DSP numbers untouched — the peak set was
byte-identical, only the bands had moved. It cost a long investigation because it reproduces only
when two pytest processes overlap: never in isolation, never under load, and independent of test
order. Keep the id.

Not an application concern: a real app is one process with its own domain.
"""

from __future__ import annotations

import os
import re
import tempfile

ORG = "Dolcesfogato"
APP = "guitar_tap"


def sandbox_id() -> str | None:
    """The sandbox discriminator, or None when running as the real app.

    ``GT_TEST_SANDBOX`` is set by ``tests/conftest.py`` at session start so the value is stable and
    available outside a test too (session fixtures, collection). ``PYTEST_CURRENT_TEST`` is the
    fallback for code imported by a test that never went through that conftest.
    """
    explicit = os.environ.get("GT_TEST_SANDBOX")
    if explicit:
        return explicit
    if "PYTEST_CURRENT_TEST" in os.environ:
        return str(os.getpid())
    return None


def settings_org(base: str = ORG) -> str:
    """QSettings organisation: ``<base>`` normally, ``<base>.tests.<pid>`` under test."""
    sid = sandbox_id()
    return f"{base}.tests.{sid}" if sid else base


def reap_stale_sandboxes(own_settings_file: str) -> None:
    """Delete sandbox settings files left by test processes that are no longer running.

    Per-process names fix the wiping, but they would otherwise leave one file per run forever.
    Clearing a QSettings suite empties it without removing the file — the backing store is flushed
    lazily — so cleanup cannot rely on a teardown hook either: a crashed or killed run leaves its
    file behind. Every run therefore reaps its dead predecessors, which is self-healing.

    *own_settings_file* is ``QSettings.fileName()`` for this process. On platforms where that is not
    a real path (Windows uses the registry) the directory scan finds nothing and this is a no-op.
    """
    sid = sandbox_id()
    if sid is None:
        return
    directory, mine = os.path.split(own_settings_file)
    if not os.path.isdir(directory) or sid not in mine:
        return
    # Turn THIS process's filename into a pattern by swapping our id for a capture group, rather
    # than hard-coding Qt's org-to-filename mangling (dots become dashes, platform-specific).
    pattern = re.compile("^" + re.escape(mine).replace(re.escape(sid), r"(\d+)") + "$")
    for entry in os.listdir(directory):
        match = pattern.match(entry)
        if not match or match.group(1) == sid:
            continue
        try:
            os.kill(int(match.group(1)), 0)   # succeeds only while that process still exists
        except (OSError, ValueError):
            try:
                os.remove(os.path.join(directory, entry))
            except OSError:
                pass


def measurements_dir(real_dir: str) -> str:
    """Directory for the saved-measurements JSON — *real_dir*, or a per-process temp dir."""
    sid = sandbox_id()
    if sid is None:
        return real_dir
    return os.path.join(tempfile.gettempdir(), f"com.guitartap.tests.{sid}")
