"""Single source of truth for user-facing date/time display.

Locale-aware, in the user's local time: medium date + short time
(e.g. en-US "Jun 25, 2026, 2:34 PM"; de-DE "25.06.2026, 14:34"). Mirrors the web's
``Intl`` medium/short and Swift's ``DateFormatter`` .medium/.short. See
DATE-TIME-FORMAT-CONSISTENCY.md.

DISPLAY only — the .guitartap ``timestamp`` stays ISO-8601 UTC and export filenames keep
their ``<slug>-<unix>`` form; neither goes through here.
"""

from __future__ import annotations

from datetime import datetime

from babel import Locale, default_locale
from babel.dates import format_date, format_skeleton, format_time, get_datetime_format


def _to_local(value: "str | datetime") -> "datetime | None":
    """Parse an ISO-8601 string (or accept a datetime) and convert to local time."""
    if isinstance(value, datetime):
        dt = value
    else:
        # `fromisoformat` < 3.11 doesn't accept a trailing 'Z' (used by the Swift/web writers).
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    try:
        return dt.astimezone()  # aware -> local; naive is assumed local (no shift)
    except (ValueError, OSError):
        return dt


def _locale() -> Locale:
    """Resolve the display locale — the Qt system locale when available, else env, else en_US."""
    try:
        from PySide6.QtCore import QLocale

        name = QLocale().name()  # e.g. "en_US"
        if name:
            return Locale.parse(name)
    except Exception:
        pass
    try:
        return Locale.parse(default_locale("LC_TIME") or "en_US")
    except Exception:
        return Locale("en", "US")


def _combine(date_str: str, time_str: str, loc: Locale) -> str:
    return (
        get_datetime_format("medium", locale=loc)
        .replace("{1}", date_str)
        .replace("{0}", time_str)
    )


def format_display_datetime(value: "str | datetime") -> str:
    """Locale-aware medium date + short time, local tz (e.g. 'Jun 25, 2026, 2:34 PM')."""
    dt = _to_local(value)
    if dt is None:
        return str(value)
    loc = _locale()
    return _combine(
        format_date(dt, format="medium", locale=loc),
        format_time(dt, format="short", locale=loc),
        loc,
    )


def format_display_datetime_compact(value: "str | datetime") -> str:
    """Compact (no year) variant for tight spots like chart titles / legends
    (e.g. 'Jun 25, 2:34 PM')."""
    dt = _to_local(value)
    if dt is None:
        return str(value)
    loc = _locale()
    return _combine(
        format_skeleton("MMMd", dt, locale=loc),
        format_time(dt, format="short", locale=loc),
        loc,
    )