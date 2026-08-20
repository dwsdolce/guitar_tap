"""
Release-readiness guard — refuses to run or build against a stale release identity.

The rule this enforces: **any development after a release must roll the version
number AND roll the release notes.** Until both are done, the code in the tree
claims to be a release that has already shipped, so anything it produces — a
window title, an About box, a screenshot, a bug report, an installer — is
mislabelled. The later that is caught, the more confusion it has already caused,
so this fires at the FIRST moment it becomes true rather than at packaging time.

Two conditions, both checked and both reported together (fix them in one pass):

  1. STALE VERSION — 'version' names a release that is already TAGGED in git and
     HEAD has moved past that tag. Building or running now labels newer code as
     the already-published release.
  2. UN-ROLLED RELEASE NOTES — the newest tag has no frozen "## Version <tag> "
     history entry in docs/ReleaseNotes.md, so the top {{placeholder}} section
     still holds that shipped release's notes and the next release would
     generate its notes from stale content.

Both clear the moment you bump 'version' and roll the notes, and neither can be
true again until the next release is tagged — so this gates the start of each
release cycle exactly once, not every build.

DEVELOPMENT CHECKOUTS ONLY. A shipped build has no git repository and no tags,
and its version is correct by construction; the guard silently allows anything
it cannot evaluate (frozen bundle, no git, no tags) so a released app can never
refuse to start over this.

Used two ways, one implementation:
  - imported by __main__.py, so `python -m guitar_tap` fails before the UI opens;
  - run as a script by every platform build — `python3 src/guitar_tap/_release_guard.py`
    (stdlib only, no PYTHONPATH needed, identical on Windows).
"""

import os
import subprocess
import sys

NOTES_PATH = os.path.join("docs", "ReleaseNotes.md")


def _repo_root() -> str:
    """Return the project root — this file is <root>/src/guitar_tap/_release_guard.py."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _git(root: str, *args: str) -> str | None:
    """Run a git command in `root`, returning stripped stdout or None on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _read_version(root: str) -> str | None:
    """Return the marketing version from src/guitar_tap/version, or None."""
    try:
        with open(os.path.join(root, "src", "guitar_tap", "version"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _check_version_fresh(root: str, version: str) -> str | None:
    """Fail when `version` is already tagged and HEAD has moved past that tag."""
    # Not tagged yet — the normal state once the version has been bumped for the
    # next release. Nothing to be stale against.
    if _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{version}") is None:
        return None

    ahead = _git(root, "rev-list", "--count", f"{version}..HEAD")
    if ahead is None or ahead == "0":
        # HEAD is exactly the tagged commit: a legitimate rebuild of that release.
        return None

    return (
        f"STALE VERSION NUMBER\n"
        f"\n"
        f"  src/guitar_tap/version says {version}, which is already released\n"
        f"  (git tag '{version}' exists), but HEAD is {ahead} commit(s) newer.\n"
        f"\n"
        f"  This code would be labelled as the released {version} everywhere it\n"
        f"  appears — About box, window title, installer, bug reports.\n"
        f"\n"
        f"  FIX: bump src/guitar_tap/version to the next release number.\n"
        f"       Tag the new version only at release time."
    )


def _check_notes_rolled(root: str) -> str | None:
    """Fail when the newest tag has no frozen history entry in the release notes."""
    latest_tag = _git(root, "describe", "--tags", "--abbrev=0")
    if latest_tag is None:
        # Nothing released yet — there is no shipped section to freeze.
        return None

    # Nothing has happened since that release yet. Rolling the notes is what you
    # do when development RESUMES, not the instant a tag lands — at the tag
    # itself the notes are correct as generated, and demanding the roll-over
    # here would block legitimate work on the release you just cut: rebuilding
    # it, re-notarising it, or building the remaining platforms. Same trigger as
    # the version check, so the pair fires exactly once, on the first commit
    # after a release.
    ahead = _git(root, "rev-list", "--count", f"{latest_tag}..HEAD")
    if ahead is None or ahead == "0":
        return None

    notes = os.path.join(root, NOTES_PATH)
    try:
        with open(notes, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return (
            f"RELEASE NOTES MISSING\n"
            f"\n"
            f"  {NOTES_PATH} could not be read, so the roll-over after\n"
            f"  {latest_tag} cannot be verified."
        )

    # A frozen entry always reads "## Version <tag> · Build <n>". Requiring the
    # trailing space keeps 1.0.2 from matching 1.0.20.
    if f"\n## Version {latest_tag} " in f"\n{content}":
        return None

    return (
        f"RELEASE NOTES NOT ROLLED OVER after {latest_tag}\n"
        f"\n"
        f"  {NOTES_PATH} has no frozen '## Version {latest_tag}' history entry,\n"
        f"  so its top {{{{placeholder}}}} section still holds {latest_tag}'s own\n"
        f"  notes — already shipped. The next release would generate its notes\n"
        f"  from that stale content.\n"
        f"\n"
        f"  FIX (see the generate_release_notes.sh header):\n"
        f"    1. Freeze the current top section — replace {{{{version}}}}/{{{{build}}}}/{{{{since}}}}\n"
        f"       with the literals {latest_tag} shipped as, giving a\n"
        f"       '## Version {latest_tag} · Build <n>' history entry.\n"
        f"    2. Add a fresh top section with {{{{placeholders}}}} for the new release."
    )


def failures() -> list[str]:
    """Return every unmet release-readiness condition; empty means good to go.

    Returns empty (allow) for anything that cannot be evaluated — a frozen
    bundle, a tree with no git repository, or a repository with no tags.
    """
    # A shipped PyInstaller build carries no repository and its version is fixed
    # at build time; there is nothing to check and everything to lose.
    if getattr(sys, "_MEIPASS", None):
        return []

    # Not a git work tree — nothing to compare a version against. Note this must
    # ask git rather than look for a .git DIRECTORY: in a git worktree .git is a
    # file pointing at the main repository, and a worktree is a checkout the
    # guard must still cover.
    root = _repo_root()
    if _git(root, "rev-parse", "--git-dir") is None:
        return []

    # Only enforce against something that is actually this source checkout, so a
    # copy of the package sitting inside some unrelated repository is ignored.
    if not os.path.isfile(os.path.join(root, NOTES_PATH)):
        return []

    version = _read_version(root)
    if version is None:
        return ["src/guitar_tap/version is missing or empty."]

    found = [_check_version_fresh(root, version), _check_notes_rolled(root)]
    return [f for f in found if f]


def enforce() -> None:
    """Print every unmet condition and exit non-zero, or return if all are met."""
    found = failures()
    if not found:
        return

    bar = "=" * 70
    print(bar, file=sys.stderr)
    print("BLOCKED — this tree is not ready for development after a release.", file=sys.stderr)
    for message in found:
        print("", file=sys.stderr)
        print(message, file=sys.stderr)
    print(bar, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    enforce()
