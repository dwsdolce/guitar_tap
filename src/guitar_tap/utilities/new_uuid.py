"""Single source of truth for minting UUID strings.

**Uppercase**, because Swift's ``UUID().uuidString`` is uppercase and the web mints with
``crypto.randomUUID().toUpperCase()`` to match it. This edition minted lowercase, so the same
measurement exported from here and from Swift differed by case in ``id`` — a field that identifies
a dataset, and that an editor comparing ids as strings would read as two different things. Swift
uppercases any UUID it decodes; the ports preserve what the file holds, so nothing normalised it
back. See SLUG-SWEEP.md F22.

Case has never affected correctness *within* a file — the references inside one file agree with its
own ids whatever their case — so existing files stay valid and are not rewritten.
"""

from __future__ import annotations

import uuid


def new_uuid() -> str:
    """A fresh v4 UUID as an uppercase string, matching Swift and the web."""
    return str(uuid.uuid4()).upper()
