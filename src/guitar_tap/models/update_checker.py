# @parity none — GitHub release update check. Python/open-source edition only: the
# Apple edition is distributed through the App Store, which owns updating, and the
# Web edition is always current the moment it loads. Neither has — or should have —
# a counterpart, so there is no cross-platform contract to mirror. Justified
# platform-only.
"""
GitHub release update checker.

Python edition only — the Apple (App Store) and browser editions do not make
this request.  On startup the app asks the GitHub REST API for the latest
published release of dwsdolce/guitar_tap and, when that release is newer than
the running version, emits ``updateAvailable`` so the main window can show a
non-modal banner.

Design constraints:

- **Never blocks startup.**  The request runs asynchronously through Qt's
  ``QNetworkAccessManager`` (part of PySide6 — no extra dependency) and is
  fired on a timer *after* the window is on screen.
- **Never breaks the app.**  Every failure mode — offline, DNS failure,
  timeout, HTTP 404 (no releases yet), HTTP 403 (rate limited), malformed
  JSON — is caught, logged, and reported via ``checkFailed``.  Nothing raises,
  and the startup path never shows an error dialog.
- **Respects the user.**  The startup check is opt-out
  (``AppSettings.check_updates_at_startup``), throttled to once per
  ``CHECK_INTERVAL_HOURS``, and honours a "skip this version" choice.

No personal data, measurement data, or telemetry is transmitted; this is a
plain unauthenticated GET of a public release list.  See the Network use
section of the published privacy policy.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from PySide6 import QtCore
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from guitar_tap.utilities.logging import gt_log

#: Public, unauthenticated GitHub REST endpoint for the newest published release.
GITHUB_RELEASES_API = "https://api.github.com/repos/dwsdolce/guitar_tap/releases/latest"

#: Human-facing releases page, used as a fallback when the API omits html_url.
GITHUB_RELEASES_PAGE = "https://github.com/dwsdolce/guitar_tap/releases"

#: Minimum hours between automatic startup checks ("Check Now" bypasses this).
CHECK_INTERVAL_HOURS = 24

#: Abort the request after this long so a hung connection never lingers.
REQUEST_TIMEOUT_MS = 5000


def _app_settings():
    """Lazy import of AppSettings to avoid a models -> views import cycle.

    Uses the bare ``views.`` form, exactly as TapDisplaySettings does.  The
    fully-qualified ``guitar_tap.views.`` form would bind a *second* module
    identity and, because views/__init__.py imports MainWindow, would drag in a
    duplicate copy of the whole view tree on the first update check.
    """
    from views.utilities.tap_settings_view import AppSettings  # noqa: PLC0415
    return AppSettings


# ---------------------------------------------------------------------- #
# Version comparison (pure — unit-tested directly)
# ---------------------------------------------------------------------- #

def parse_version(v: str) -> tuple[int, ...] | None:
    """Parse a release string into a comparable tuple of ints.

    Accepts the repo's bare-semver tags ("1.0.1") and tolerates a leading "v"
    in case future tags adopt one.  Any pre-release/build suffix is discarded
    ("1.0.2-beta1" -> (1, 0, 2)).  Returns None when the string cannot be
    parsed, which callers treat as "not newer" rather than as an error.
    """
    if not v:
        return None
    s = str(v).strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    for sep in ("-", "+"):
        if sep in s:
            s = s.split(sep, 1)[0]
    parts = [p for p in s.split(".") if p != ""]
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(current: str, latest: str) -> bool:
    """True when `latest` is a strictly newer release than `current`.

    Compares as tuples of ints, not as strings — a string compare would rank
    "1.0.10" below "1.0.2".  Shorter versions are zero-padded so "1.0" and
    "1.0.0" compare equal.  Unparseable input yields False: we would rather
    stay quiet than nag the user on a version string we do not understand.
    """
    cur = parse_version(current)
    new = parse_version(latest)
    if cur is None or new is None:
        return False
    width = max(len(cur), len(new))
    cur = cur + (0,) * (width - len(cur))
    new = new + (0,) * (width - len(new))
    return new > cur


# ---------------------------------------------------------------------- #
# UpdateChecker
# ---------------------------------------------------------------------- #

class UpdateChecker(QtCore.QObject):
    """Asynchronously asks GitHub whether a newer release exists.

    Signals:
        updateAvailable(version, url, notes): a newer release was published.
        upToDate(current_version): the running version is current.
        checkFailed(reason): the check could not be completed (never fatal).
    """

    updateAvailable = QtCore.Signal(str, str, str)  # version, url, release notes
    upToDate = QtCore.Signal(str)                   # current version
    checkFailed = QtCore.Signal(str)                # human-readable reason

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._forced = False
        self._timeout = QtCore.QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(REQUEST_TIMEOUT_MS)
        self._timeout.timeout.connect(self._on_timeout)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def current_version(self) -> str:
        """The running app's marketing version (e.g. "1.0.2")."""
        from _version import __version__  # noqa: PLC0415
        return str(__version__)

    def pending_update(self) -> "tuple[str, str] | None":
        """An already-discovered update that still applies, read from cache.

        Returns (version, url), or None.  This is what lets the banner reappear
        on every launch while an update is outstanding: without it, the once-a-
        day throttle would suppress the check on the next start and the banner
        would silently vanish even though the update was still pending.

        Costs no network request.  Returns None once the user has upgraded past
        the cached release, or chose to skip it.
        """
        s = _app_settings()
        version = s.available_update_version()
        if not version:
            return None
        if version == s.skipped_update_version():
            return None
        if not is_newer(self.current_version(), version):
            return None  # already upgraded past it
        return version, (s.available_update_url() or GITHUB_RELEASES_PAGE)

    def should_check_on_startup(self) -> bool:
        """Whether the automatic startup check should run right now.

        False when the user turned the check off, or when the last check was
        less than CHECK_INTERVAL_HOURS ago.  "Check Now" does not consult this.
        """
        s = _app_settings()
        if not s.check_updates_at_startup():
            return False
        last = s.last_update_check()
        if not last:
            return True
        try:
            when = datetime.fromisoformat(last)
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - when >= timedelta(hours=CHECK_INTERVAL_HOURS)

    def check(self, force: bool = False) -> None:
        """Start a check.  `force=True` (the "Check Now" button) skips the
        throttle and ignores a previously skipped version.

        Returns immediately; the result arrives on one of the three signals.
        """
        if self._reply is not None:
            return  # A check is already in flight.
        if not force and not self.should_check_on_startup():
            return

        self._forced = force
        try:
            req = QNetworkRequest(QtCore.QUrl(GITHUB_RELEASES_API))
            req.setRawHeader(b"Accept", b"application/vnd.github+json")
            req.setRawHeader(b"User-Agent", f"guitar_tap/{self.current_version()}".encode())
            req.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            self._reply = self._nam.get(req)
            self._reply.finished.connect(self._on_finished)
            self._timeout.start()
            gt_log("\U0001f504 Update check: querying GitHub for the latest release")
        except Exception as exc:  # noqa: BLE001 — a check must never be fatal
            self._finish_failure(f"Could not start the update check: {exc}")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _on_timeout(self) -> None:
        """The request took too long — abort it (this triggers _on_finished)."""
        if self._reply is not None:
            self._reply.abort()

    def _on_finished(self) -> None:
        """Handle the reply.  Wrapped so no failure can escape into the GUI."""
        self._timeout.stop()
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            self._handle_reply(reply)
        except Exception as exc:  # noqa: BLE001 — a check must never be fatal
            self._finish_failure(f"Could not read the update information: {exc}")
        finally:
            reply.deleteLater()

    def _handle_reply(self, reply: QNetworkReply) -> None:
        # Record the attempt regardless of outcome, so a persistent failure
        # (e.g. permanently offline) does not retry on every single launch.
        self._stamp_check_time()

        if reply.error() != QNetworkReply.NetworkError.NoError:
            status = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute
            )
            if status == 404:
                # No releases published yet — not an error worth reporting.
                gt_log("\U0001f504 Update check: no releases published yet")
                self._clear_cached_update()
                self.upToDate.emit(self.current_version())
                return
            if status == 403:
                self._finish_failure("GitHub rate limit reached — try again later.")
                return
            self._finish_failure(reply.errorString())
            return

        raw = bytes(reply.readAll().data())
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            self._finish_failure("Unexpected response from GitHub.")
            return

        # Ignore drafts and pre-releases — only stable releases are offered.
        if data.get("draft") or data.get("prerelease"):
            gt_log("\U0001f504 Update check: latest release is a draft/pre-release — ignoring")
            self._clear_cached_update()
            self.upToDate.emit(self.current_version())
            return

        latest = str(data.get("tag_name") or "").strip()
        current = self.current_version()
        if not is_newer(current, latest):
            gt_log(f"\U0001f504 Update check: up to date (running {current}, latest {latest or 'unknown'})")
            self._clear_cached_update()
            self.upToDate.emit(current)
            return

        # A newer release exists.  Cache it first, so the banner survives a
        # restart even though the next startup check will be throttled.
        url = str(data.get("html_url") or GITHUB_RELEASES_PAGE)
        notes = str(data.get("body") or "").strip()
        self._cache_update(latest, url)

        # On the automatic path, honour a version the user explicitly chose to
        # skip; an explicit "Check Now" always reports.
        if not self._forced and latest == _app_settings().skipped_update_version():
            gt_log(f"\U0001f504 Update check: {latest} available but skipped by the user")
            return

        gt_log(f"\U0001f195 Update available: {latest} (running {current})")
        self.updateAvailable.emit(latest, url, notes)

    def _cache_update(self, version: str, url: str) -> None:
        """Remember a discovered update so the banner survives a restart."""
        try:
            s = _app_settings()
            s.set_available_update_version(version)
            s.set_available_update_url(url)
        except Exception:  # noqa: BLE001 — settings failure must not break the check
            pass

    def _clear_cached_update(self) -> None:
        """Forget any cached update — we are current, so the banner must stop."""
        try:
            s = _app_settings()
            s.set_available_update_version("")
            s.set_available_update_url("")
        except Exception:  # noqa: BLE001
            pass

    def _stamp_check_time(self) -> None:
        try:
            _app_settings().set_last_update_check(
                datetime.now(timezone.utc).isoformat()
            )
        except Exception:  # noqa: BLE001 — settings failure must not break the check
            pass

    def _finish_failure(self, reason: str) -> None:
        gt_log(f"⚠️ Update check failed: {reason}")
        self.checkFailed.emit(reason)