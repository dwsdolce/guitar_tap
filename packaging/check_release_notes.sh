#!/bin/sh
# check_release_notes.sh
#
# Catches a SKIPPED release-notes roll-over.
#
# docs/ReleaseNotes.md is cumulative: the top section carries {{placeholders}}
# and describes the release under development; every older release sits below it
# as a literal, frozen "## Version <x> · Build <n>" entry. When you cut a release
# you are meant to FREEZE the current top section into history and start a fresh
# top section for the next version (see the header of generate_release_notes.sh).
#
# If that freeze is skipped, the newest git tag (the release you just shipped)
# has NO frozen history entry, and the top {{placeholder}} section still holds
# that shipped release's notes — so the next release's notes generate from stale
# content. This script detects exactly that: the newest tag must appear as a
# frozen "## Version <tag>" header in the notes.
#
# Exit 0 = rolled over correctly (or there is no prior release to check).
# Exit 1 = roll-over missing — the build must not proceed (a "1.0.3" build would
#          otherwise ship 1.0.2's notes). Callers treat a non-zero exit as fatal.

NOTES="docs/ReleaseNotes.md"
if [ ! -f "$NOTES" ]; then
    echo "check_release_notes.sh: $NOTES not found (run from the project root)." >&2
    exit 1
fi

# The most recent release. If nothing is tagged yet there is nothing to freeze.
LATEST_TAG="$(git describe --tags --abbrev=0 2>/dev/null)" || exit 0
[ -n "$LATEST_TAG" ] || exit 0

# Escape regex metacharacters in the tag (the dots in 1.0.2) before matching.
esc_tag="$(printf '%s' "$LATEST_TAG" | sed 's/[.[\*^$]/\\&/g')"

# A frozen history entry always reads "## Version <tag> · Build <n>", so the tag
# is followed by a space. That trailing space also stops 1.0.2 matching 1.0.20.
if grep -qE "^## Version ${esc_tag} " "$NOTES"; then
    echo "check_release_notes.sh: OK — release $LATEST_TAG is frozen into $NOTES."
    exit 0
fi

echo "======================================================================" >&2
echo "BUILD BLOCKED — release notes not rolled over after $LATEST_TAG." >&2
echo "" >&2
echo "  The newest release is tagged '$LATEST_TAG', but $NOTES has no frozen" >&2
echo "  '## Version $LATEST_TAG' history entry. The top {{placeholder}} section" >&2
echo "  therefore still contains $LATEST_TAG's notes, so the NEXT release's" >&2
echo "  notes would be generated from stale, already-shipped content." >&2
echo "" >&2
echo "  Roll the notes over (see generate_release_notes.sh header):" >&2
echo "    1. Freeze the current top section — replace {{version}}/{{build}}/{{since}}" >&2
echo "       with the literals $LATEST_TAG shipped as — making it the" >&2
echo "       '## Version $LATEST_TAG · Build <n>' history entry." >&2
echo "    2. Add a fresh top section with {{placeholders}} for the new release." >&2
echo "======================================================================" >&2
exit 1
