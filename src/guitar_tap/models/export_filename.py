"""Single source of truth for exported-artifact filenames.

See FILE-PATHS-AND-NAMES-SPEC.md §2b. Mirrors Swift ``ExportFilename.stem``.
"""

# @parity model/export-filename

from __future__ import annotations


def export_stem(name: "str | None", epoch_seconds: int, unnamed: str) -> str:
    """The filename stem shared by every exported artifact — ``.guitartap``, PDF, spectrum PNG.

    Rule::

        stem = <measurement name, slugged  OR  the artifact's own default word> - <unix seconds>

    - The name is slugged: spaces and ``/`` become ``-``, then lowercased.
    - ``epoch_seconds`` is a **discriminator**, not part of the name — two measurements may share a
      name — and is always integer seconds.
    - ``unnamed`` is the per-artifact default word, used only when there is no name (empty or None):
      ``"measurement"`` for ``.guitartap``, ``"report"`` for PDF, ``"spectrum"`` for PNG. It is a
      default **name**, never an infix.

    Replaces four hand-rolled copies of the same slug logic that had drifted (wrong default words,
    some sites not slugging ``/``).
    """
    slug = (name or "").replace(" ", "-").replace("/", "-").lower()
    return f"{slug or unnamed}-{epoch_seconds}"