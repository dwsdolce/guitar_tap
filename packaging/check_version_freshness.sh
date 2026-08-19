#!/bin/sh
# check_version_freshness.sh
#
# Guards every platform build against a STALE version number.
#
# Fails (exit 1) when src/guitar_tap/version names a release that is ALREADY
# TAGGED in git *and* the working tree (HEAD) is newer than that tag — i.e. you
# are building code that has moved past the released version without bumping the
# version file. Building in that state would stamp newer code with an old,
# already-published version string (e.g. "1.0.2 (491)" for post-1.0.2 code).
#
# Passes (exit 0) when:
#   - the version is NOT yet tagged — the normal state once you have bumped
#     src/guitar_tap/version for the next release; or
#   - HEAD is exactly the tagged release commit — a legitimate rebuild of a
#     released version.
#
# The fix when this fails is always the same: bump src/guitar_tap/version to the
# next release number before building. Tag that new version only at release time.

VERSION="$(tr -d ' \t\r\n' < src/guitar_tap/version 2>/dev/null)"
if [ -z "$VERSION" ]; then
    echo "check_version_freshness.sh: src/guitar_tap/version is missing or empty." >&2
    exit 1
fi

# No tag for this version yet → the version is fresh (bumped for the next release).
if ! git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null 2>&1; then
    exit 0
fi

# Tag exists. Count commits on HEAD that are not in the tag.
AHEAD="$(git rev-list --count "$VERSION..HEAD" 2>/dev/null || echo 0)"
if [ "${AHEAD:-0}" -gt 0 ]; then
    echo "======================================================================" >&2
    echo "BUILD BLOCKED — stale version number." >&2
    echo "" >&2
    echo "  src/guitar_tap/version says $VERSION, which is already released" >&2
    echo "  (git tag '$VERSION' exists), but HEAD is $AHEAD commit(s) newer." >&2
    echo "" >&2
    echo "  Building now would label this newer code as the released $VERSION." >&2
    echo "  Bump src/guitar_tap/version to the next release number before" >&2
    echo "  building; tag that new version only at release time." >&2
    echo "======================================================================" >&2
    exit 1
fi

# HEAD is exactly the tagged commit — a legitimate rebuild of $VERSION.
exit 0
