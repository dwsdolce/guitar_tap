# @parity tooling/oracle-sync
"""The vendored oracle still matches canonical — when canonical can be reached.

Each repo commits its own copy of ``parity-oracle.json`` so the suite runs offline. That
convenience is also the failure mode: a copy can sit here for months, quietly stale, while
the canonical file in the hub has moved on. Nothing notices, because every test passes
against the stale copy — they are measuring agreement with yesterday.

``Tooling/sync-oracle.sh --check`` is the existing answer, and it has always had to be run
by hand. This puts it in the suite, where it runs without being remembered.

It cannot always run. While the hub is private the published URL 404s, so canonical is only
reachable through ``ORACLE_SRC`` pointing at a local hub checkout — which most machines do
not have. Rather than fail everywhere for a condition nobody can fix locally, an unreachable
canonical **skips loudly**. Once the hub is public (issue #11) the URL resolves on its own
and this starts checking everywhere with no change here.

  exit 0 → in sync            exit 1 → drift, and the diff is the message
  exit 2 → could not reach canonical → skip, or a misconfigured script → fail
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "Tooling", "sync-oracle.sh")

# Phrases fetch_canonical emits when it cannot reach canonical, as opposed to the other
# things that also exit 2 (no oracle-dest.txt, bad usage) — those are real misconfiguration
# and must fail rather than skip.
UNREACHABLE = ("could not fetch canonical oracle", "ORACLE_SRC given but no oracle")


def test_vendored_oracle_matches_canonical():
    """Fails on drift; skips when canonical is out of reach."""
    if not os.path.exists(SCRIPT):
        pytest.skip(f"no sync-oracle.sh at {SCRIPT}")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH — cannot run sync-oracle.sh (Windows without Git Bash)")

    result = subprocess.run(
        [bash, SCRIPT, "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()

    if result.returncode == 0:
        return

    if result.returncode == 2 and any(p in output for p in UNREACHABLE):
        pytest.skip(
            "CANONICAL ORACLE UNREACHABLE — the vendored copy is NOT being checked for "
            "staleness. While the hub is private this needs ORACLE_SRC=<hub checkout>. "
            f"Script said: {output.splitlines()[0] if output else '(no output)'}"
        )

    raise AssertionError(
        f"sync-oracle.sh --check failed (exit {result.returncode}):\n{output}"
    )
