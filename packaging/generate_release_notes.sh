#!/bin/bash
# Generate the Guitar Tap release-notes PDF, stamped with the version + build numbers.
#
# The single source is docs/ReleaseNotes.md — a cumulative document, hand-edited each
# release. Only the NEWEST section carries the placeholders, filled here from git:
#   {{version}} = marketing version  (src/guitar_tap/version)
#   {{build}}   = git commit count at HEAD                     (this release's build)
#   {{since}}   = git commit count at the previous release tag (the "since" build)
# Every older section keeps its literal, frozen numbers. When you cut the next release you
# hand-edit this file: freeze the current top section (replace its placeholders with the
# literals it shipped as) and add a new top section with fresh placeholders.
#
# ORDERING: run this BEFORE tagging the new release. {{since}} is the commit count at the
# latest existing tag, which must still be the PREVIOUS release — this script refuses to run
# if the newest tag already equals the current version.
#
# Output: docs/ReleaseNotes-<version>-<build>.md (the stamped markdown pandoc reads) and .pdf.
#
# Prerequisites (one-time): pandoc + a LaTeX engine, e.g. `brew install pandoc` and BasicTeX.
#
# Usage:
#   packaging/generate_release_notes.sh     # from project root (also called by build_mac)

set -e

# Run from the project root regardless of where this script is invoked from.
cd "$(dirname "$0")/.."

SRC="docs/ReleaseNotes.md"
VERSION="$(cat src/guitar_tap/version)"
BUILD="$(git rev-list --count HEAD)"

LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null)" || {
    echo "generate_release_notes.sh: no git tags found — cannot derive the 'since' build." >&2
    echo "  Tag the previous release (bare version, e.g. 1.0.1) so 'What's New Since Build N' can be computed." >&2
    exit 1
}
if [ "$LAST_TAG" = "$VERSION" ]; then
    echo "generate_release_notes.sh: the latest tag ($LAST_TAG) already equals the current version." >&2
    echo "  Generate the notes BEFORE tagging this release, or the 'Since Build' number is wrong." >&2
    exit 1
fi
SINCE="$(git rev-list --count "$LAST_TAG")"

OUT_MD="docs/ReleaseNotes-${VERSION}-${BUILD}.md"
OUT_PDF="docs/ReleaseNotes-${VERSION}-${BUILD}.pdf"

# Fill the newest section's placeholders (the tokens appear only there; history is literal).
sed -e "s/{{version}}/${VERSION}/g" \
    -e "s/{{build}}/${BUILD}/g" \
    -e "s/{{since}}/${SINCE}/g" \
    "$SRC" > "$OUT_MD"

pandoc "$OUT_MD" -o "$OUT_PDF"

echo "generate_release_notes.sh: wrote $OUT_MD and $OUT_PDF"
echo "  version=${VERSION} build=${BUILD} since=${SINCE} (previous tag ${LAST_TAG})"
