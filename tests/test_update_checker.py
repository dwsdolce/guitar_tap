# @parity none — exercises the Python-only GitHub update check in
# models/update_checker.py, which is itself platform-only. The Apple edition updates
# via the App Store and the Web edition is always current, so there is no behavioural
# contract for a Swift/Web test to mirror. Justified platform-only.
#
# (Do not restate the tag keyword anywhere below the line above — the generator's
# regex would match it a second time and emit a duplicate map entry.)
"""
Tests for the GitHub release update checker (models/update_checker.py).

No real HTTP is performed: the network reply is faked so the parsing, version
comparison, throttle, and skip-version logic are all exercised offline.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest
from PySide6 import QtWidgets
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from guitar_tap.models.update_checker import (
    UpdateChecker,
    _app_settings,
    is_newer,
    parse_version,
)

# Resolve AppSettings through the checker's own accessor so the tests drive the
# exact same class (and therefore the same QSettings store) the checker reads.
AppSettings = _app_settings()

# The project does not use pytest-qt; Qt objects need a live QApplication, so
# create one once per session (matching tests/test_annotation_state.py).
_APP: "QtWidgets.QApplication | None" = None


@pytest.fixture(scope="session", autouse=True)
def _qt_app():
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


# ---------------------------------------------------------------------- #
# parse_version / is_newer — pure logic
# ---------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0.2", (1, 0, 2)),
        ("v1.0.2", (1, 0, 2)),
        ("V1.0.2", (1, 0, 2)),
        ("  1.0.2  ", (1, 0, 2)),
        ("1.0", (1, 0)),
        ("1", (1,)),
        ("1.0.2-beta1", (1, 0, 2)),   # pre-release suffix discarded
        ("1.0.2+build9", (1, 0, 2)),  # build metadata discarded
        ("", None),
        ("not-a-version", None),
        ("1.x.3", None),
    ],
)
def test_parse_version(raw, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    "current,latest,expected",
    [
        ("1.0.2", "1.0.3", True),    # patch bump
        ("1.0.2", "1.1.0", True),    # minor bump
        ("1.0.2", "2.0.0", True),    # major bump
        ("1.0.2", "1.0.2", False),   # identical
        ("1.0.3", "1.0.2", False),   # latest is older
        ("1.0.2", "v1.0.3", True),   # tolerate a v prefix
        # A string compare would wrongly rank 1.0.10 below 1.0.2 — int tuples must not.
        ("1.0.2", "1.0.10", True),
        ("1.0.10", "1.0.2", False),
        # Unequal segment counts zero-pad, so these are equal, not newer.
        ("1.0", "1.0.0", False),
        ("1.0.0", "1.0", False),
        ("1.0", "1.0.1", True),
        # Unparseable input must never nag the user.
        ("1.0.2", "", False),
        ("", "1.0.3", False),
        ("1.0.2", "garbage", False),
    ],
)
def test_is_newer(current, latest, expected):
    assert is_newer(current, latest) is expected


# ---------------------------------------------------------------------- #
# Fake reply plumbing
# ---------------------------------------------------------------------- #

class _FakeReply:
    """Stands in for QNetworkReply — only the bits _handle_reply touches."""

    def __init__(self, payload=None, error=QNetworkReply.NetworkError.NoError,
                 status=200, error_string="boom"):
        self._payload = payload
        self._error = error
        self._status = status
        self._error_string = error_string

    def error(self):
        return self._error

    def errorString(self):
        return self._error_string

    def deleteLater(self):
        """_on_finished always disposes of the reply; the double must allow it."""

    def attribute(self, attr):
        if attr == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self._status
        return None

    def readAll(self):
        body = json.dumps(self._payload).encode() if self._payload is not None else b"{"

        class _Data:
            def data(self_inner):
                return body

        return _Data()


def _release(tag="1.0.3", draft=False, prerelease=False,
             url="https://github.com/dwsdolce/guitar_tap/releases/tag/1.0.3"):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
            "html_url": url, "body": "notes"}


@pytest.fixture
def checker(monkeypatch):
    c = UpdateChecker()
    monkeypatch.setattr(c, "current_version", lambda: "1.0.2")
    return c


def _drive(checker, reply, forced=False):
    """Run _handle_reply and collect whichever signal fired."""
    fired = {}
    checker.updateAvailable.connect(
        lambda v, u, n: fired.update(kind="available", version=v, url=u)
    )
    checker.upToDate.connect(lambda v: fired.update(kind="uptodate", version=v))
    checker.checkFailed.connect(lambda r: fired.update(kind="failed", reason=r))
    checker._forced = forced
    checker._handle_reply(reply)
    return fired


# ---------------------------------------------------------------------- #
# Reply handling
# ---------------------------------------------------------------------- #

def test_newer_release_emits_update_available(checker):
    fired = _drive(checker, _FakeReply(_release("1.0.3")))
    assert fired["kind"] == "available"
    assert fired["version"] == "1.0.3"
    assert "releases/tag/1.0.3" in fired["url"]


def test_same_version_emits_up_to_date(checker):
    fired = _drive(checker, _FakeReply(_release("1.0.2")))
    assert fired["kind"] == "uptodate"


def test_older_release_emits_up_to_date(checker):
    fired = _drive(checker, _FakeReply(_release("1.0.1")))
    assert fired["kind"] == "uptodate"


def test_draft_and_prerelease_are_ignored(checker):
    assert _drive(checker, _FakeReply(_release("2.0.0", draft=True)))["kind"] == "uptodate"
    assert _drive(checker, _FakeReply(_release("2.0.0", prerelease=True)))["kind"] == "uptodate"


def test_404_no_releases_is_not_an_error(checker):
    reply = _FakeReply(error=QNetworkReply.NetworkError.ContentNotFoundError, status=404)
    assert _drive(checker, reply)["kind"] == "uptodate"


def test_rate_limit_reports_failure(checker):
    reply = _FakeReply(error=QNetworkReply.NetworkError.UnknownContentError, status=403)
    fired = _drive(checker, reply)
    assert fired["kind"] == "failed"
    assert "rate limit" in fired["reason"].lower()


def test_network_error_reports_failure(checker):
    reply = _FakeReply(
        error=QNetworkReply.NetworkError.HostNotFoundError,
        status=None,
        error_string="Host not found",
    )
    fired = _drive(checker, reply)
    assert fired["kind"] == "failed"


def test_malformed_json_does_not_raise(checker):
    """A corrupt body must surface as checkFailed, never as an exception."""
    reply = _FakeReply(payload=None)  # readAll returns b"{" — invalid JSON
    fired = {}
    checker.checkFailed.connect(lambda r: fired.update(kind="failed"))
    checker._reply = reply
    checker._on_finished()  # the wrapper that guarantees nothing escapes
    assert fired["kind"] == "failed"


# ---------------------------------------------------------------------- #
# Skip-this-version
# ---------------------------------------------------------------------- #

def test_skipped_version_suppresses_the_startup_banner(checker):
    AppSettings.set_skipped_update_version("1.0.3")
    try:
        fired = _drive(checker, _FakeReply(_release("1.0.3")), forced=False)
        assert fired == {}, "a skipped version must not notify on the startup path"
    finally:
        AppSettings.set_skipped_update_version("")


def test_check_now_reports_even_a_skipped_version(checker):
    AppSettings.set_skipped_update_version("1.0.3")
    try:
        fired = _drive(checker, _FakeReply(_release("1.0.3")), forced=True)
        assert fired["kind"] == "available"
    finally:
        AppSettings.set_skipped_update_version("")


def test_a_newer_release_than_the_skipped_one_still_notifies(checker):
    AppSettings.set_skipped_update_version("1.0.3")
    try:
        fired = _drive(checker, _FakeReply(_release("1.0.4")), forced=False)
        assert fired["kind"] == "available"
        assert fired["version"] == "1.0.4"
    finally:
        AppSettings.set_skipped_update_version("")


# ---------------------------------------------------------------------- #
# Throttle
# ---------------------------------------------------------------------- #

def test_startup_check_is_skipped_when_disabled(checker):
    AppSettings.set_check_updates_at_startup(False)
    try:
        assert checker.should_check_on_startup() is False
    finally:
        AppSettings.set_check_updates_at_startup(True)


def test_startup_check_runs_when_never_checked(checker):
    AppSettings.set_check_updates_at_startup(True)
    AppSettings.set_last_update_check("")
    assert checker.should_check_on_startup() is True


def test_startup_check_is_throttled_within_24h(checker):
    AppSettings.set_check_updates_at_startup(True)
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    AppSettings.set_last_update_check(recent)
    try:
        assert checker.should_check_on_startup() is False
    finally:
        AppSettings.set_last_update_check("")


def test_startup_check_runs_again_after_24h(checker):
    AppSettings.set_check_updates_at_startup(True)
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    AppSettings.set_last_update_check(stale)
    try:
        assert checker.should_check_on_startup() is True
    finally:
        AppSettings.set_last_update_check("")


def test_corrupt_last_check_timestamp_does_not_raise(checker):
    AppSettings.set_check_updates_at_startup(True)
    AppSettings.set_last_update_check("not-a-timestamp")
    try:
        assert checker.should_check_on_startup() is True
    finally:
        AppSettings.set_last_update_check("")


# ---------------------------------------------------------------------- #
# Cached pending update — the banner must survive a restart
#
# Regression guard: a completed check stamps the 24h throttle even when it
# FOUND an update, so the next launch skips the network check.  Without the
# cache the banner would silently vanish while the update was still pending.
# ---------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_update_cache():
    AppSettings.set_available_update_version("")
    AppSettings.set_available_update_url("")
    yield
    AppSettings.set_available_update_version("")
    AppSettings.set_available_update_url("")


def test_finding_an_update_caches_it(checker):
    _drive(checker, _FakeReply(_release("1.0.3")))
    assert AppSettings.available_update_version() == "1.0.3"
    assert "1.0.3" in AppSettings.available_update_url()


def test_pending_update_is_returned_without_any_network_call(checker):
    """This is what repaints the banner on the next launch while throttled."""
    _drive(checker, _FakeReply(_release("1.0.3")))
    assert checker.pending_update() == (
        "1.0.3",
        "https://github.com/dwsdolce/guitar_tap/releases/tag/1.0.3",
    )


def test_being_up_to_date_clears_the_cache(checker):
    _drive(checker, _FakeReply(_release("1.0.3")))
    assert checker.pending_update() is not None
    _drive(checker, _FakeReply(_release("1.0.2")))  # now current
    assert checker.pending_update() is None
    assert AppSettings.available_update_version() == ""


def test_pending_update_is_dropped_once_the_user_upgrades(checker, monkeypatch):
    _drive(checker, _FakeReply(_release("1.0.3")))
    monkeypatch.setattr(checker, "current_version", lambda: "1.0.3")  # user upgraded
    assert checker.pending_update() is None


def test_pending_update_respects_skip(checker):
    _drive(checker, _FakeReply(_release("1.0.3")))
    AppSettings.set_skipped_update_version("1.0.3")
    try:
        assert checker.pending_update() is None
    finally:
        AppSettings.set_skipped_update_version("")


def test_no_pending_update_when_nothing_cached(checker):
    assert checker.pending_update() is None