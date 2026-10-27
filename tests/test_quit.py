# @parity none — PySide's teardown when the app quits; Swift and the web have no equivalent.
"""The app quits cleanly after a session — exit code 0, no crash.

At quit, ``QApplication.shutdown()`` deletes every object PySide counts as Python's, in no set order. A widget built
without a parent and then put in a layout is counted as Python's although Qt has given it a parent in the window; if
the window is deleted first, the widget is deleted twice and the process crashes (SIGSEGV or SIGABRT). Saved
Measurements and Settings, kept once opened, carry hundreds of such widgets, and on Linux about seven quits in ten
crashed after opening them; start-and-quit never did. So the session opens them, and is run several times: the crash
depends on the order PySide happens to delete in.

Each run is a real process (``quit_session.py`` drives the app through ``python -m guitar_tap``): the exit sequence
is ``__main__``'s, which no in-process test can run.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

RUNS = 5
DRIVER = os.path.join(os.path.dirname(__file__), "quit_session.py")


@pytest.mark.parametrize("run", range(1, RUNS + 1))
def test_quits_cleanly_after_a_session(run: int) -> None:
    env = dict(os.environ, GT_TEST_SANDBOX="1")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [sys.executable, DRIVER, "metrics,measurements,settings"],
        env=env, capture_output=True, text=True, timeout=90,
    )
    output = (result.stdout + result.stderr)[-4000:]
    assert result.returncode == 0, f"exit code {result.returncode}:\n{output}"
    assert "Fatal Python error" not in output, output
    assert "Traceback" not in output, output
