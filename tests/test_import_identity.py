# @parity none
"""Every internal import is package-absolute or explicitly relative — never bare.

``__main__.py`` used to insert ``src/guitar_tap`` onto ``sys.path`` so that ``models/`` and
``views/`` resolved as TOP-LEVEL packages. That gave every module two import identities —
``models.x`` and ``guitar_tap.models.x`` — which Python treats as different modules with different
class objects, so an enum compared with ``is`` could be False for a value that was semantically
equal, depending only on which file it travelled through. Commit c74dde4 removed the hack and made
every import package-absolute.

It missed eight ``from _version import …`` sites, and the app could not start for three weeks.

Nothing caught it, and the reason is worth keeping in view: all eight were DEFERRED imports inside
functions. A bare import at module scope fails the moment anything imports the module, so the test
suite would have found it immediately. A bare import inside ``MainWindow.__init__`` fails only when
that function runs — and no test constructs MainWindow, because it needs a Qt application. The
suite stayed green at 660 the entire time.

So this scans the source rather than exercising it. An import that only resolves through a
``sys.path`` entry nobody adds any more is a static fact about the text, and can be checked as one.
This file is Python-only plumbing: neither port has an equivalent hazard, because neither ever had
the hack.
"""

from __future__ import annotations

import ast
import os

PKG = os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap")


def _internal_top_level_names() -> set[str]:
    """Everything directly under the package — the names the removed hack made importable bare."""
    names = set()
    for entry in os.listdir(PKG):
        path = os.path.join(PKG, entry)
        if entry.startswith("__"):
            continue
        if os.path.isdir(path):
            names.add(entry)
        elif entry.endswith(".py"):
            names.add(entry[:-3])
    return names


def _python_files() -> list[str]:
    out = []
    for root, _dirs, files in os.walk(PKG):
        out.extend(os.path.join(root, f) for f in files if f.endswith(".py"))
    return out


def test_no_bare_internal_imports():
    internal = _internal_top_level_names()
    assert "_version" in internal, "sanity: the module that caused this should be in the set"

    offenders: list[str] = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=path)
        rel = os.path.relpath(path, PKG)
        for node in ast.walk(tree):
            # `from X import ...` with level 0 is absolute; level > 0 is relative and fine.
            if isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    if root in internal:
                        offenders.append(f"{rel}:{node.lineno}: from {node.module} import …")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in internal:
                        offenders.append(f"{rel}:{node.lineno}: import {alias.name}")

    assert not offenders, (
        "these import an internal module by its bare name, which only resolved through the "
        "sys.path hack removed in c74dde4 — use guitar_tap.<module> or a relative import:\n  "
        + "\n  ".join(offenders)
    )
