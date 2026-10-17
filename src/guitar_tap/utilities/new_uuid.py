# @parity util/new-id tests=test/uuid-case
"""Single source of truth for minting UUIDs, reading one, and writing one.

An id is a ``uuid.UUID`` — compared by value, so case never matters, as Swift's ``UUID`` — and is text
only in a file, where it is written uppercase (``uuid_text``).

**Uppercase**, because Swift's ``UUID().uuidString`` is uppercase and the web mints with
``crypto.randomUUID().toUpperCase()`` to match it. This edition minted lowercase, so the same
measurement exported from here and from Swift differed by case in ``id`` — a field that identifies
a dataset, and that an editor comparing ids as strings would read as two different things. Swift
uppercases any UUID it decodes; the ports preserve what the file holds, so nothing normalised it
back.

Reading follows the standard and Swift: a UUID is case-insensitive on input (RFC 9562), so every id
read is put in the canonical case; and an id that is not a UUID at all — or is missing — makes what holds
it unreadable, as Swift's decoding of a ``UUID`` does.
"""

from __future__ import annotations

import re
import uuid

# The form an id must have, as Swift's ``UUID(uuidString:)`` takes it: 36 characters, hexadecimal in
# groups of 8-4-4-4-12 joined by hyphens, either case. Stricter than ``uuid.UUID()``, which also takes
# braces, a ``urn:uuid:`` prefix and unhyphenated hex.
_UUID_FORM = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


class NoSpectrumError(ValueError):
    """A measurement in a file with no spectrum — no guitar spectrum, no plate/brace longitudinal one, or a
    comparison of fewer than two entries; a spectrum with no points is none: no edition makes one, so the
    file cannot be read. Mirrors Swift ``NoSpectrumError``."""

    def __init__(self) -> None:
        super().__init__("no spectrum")


class InvalidIdError(ValueError):
    """An id that is not a UUID: the file or record holding it cannot be read."""

    def __init__(self, value: object, field: str) -> None:
        super().__init__(f"{field} is missing" if value is None else f'"{value}" in {field} is not a UUID')
        self.value = value
        self.field = field


def new_uuid() -> uuid.UUID:
    """A fresh v4 UUID. Mirrors Swift ``UUID()``."""
    return uuid.uuid4()


def uuid_text(value: uuid.UUID) -> str:
    """*value* as a file writes it: uppercase, as Swift's ``uuidString`` and the web write it."""
    return str(value).upper()


def parse_uuid(value: object, field: str) -> uuid.UUID:
    """*value* read as a UUID, or InvalidIdError naming *field* when it is missing or not a UUID in the
    hyphenated form. Mirrors Swift decoding a ``UUID``."""
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or not _UUID_FORM.fullmatch(value):
        raise InvalidIdError(value, field)
    return uuid.UUID(value)
