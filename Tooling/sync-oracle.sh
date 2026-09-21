#!/usr/bin/env bash
# sync-oracle.sh — vendor the canonical parity oracle into a consuming repo.
#
# CANONICAL COPY OF THIS SCRIPT. It lives in the hub (guitar-tap-project/tooling/)
# and is copied verbatim into each consuming repo's tooling/ directory. The repo it
# is copied into declares its own vendored path in tooling/oracle-dest.txt, so this
# file itself is identical everywhere and carries no per-repo knowledge.
#
#   ./tooling/sync-oracle.sh           # refresh the local copy from canonical
#   ./tooling/sync-oracle.sh --check   # CI mode: non-zero exit if local != canonical
#   ./tooling/sync-oracle.sh --publish # canonical <- local (Swift repo only; see below)
#
# Sources, in the order tried:
#   ORACLE_SRC       a hub working copy (directory or file), when set explicitly — always wins
#   ../guitar-tap-project   the hub directory beside this repo, read only if it is there
#   ORACLE_URL       a raw URL — the long-term source once the hub is public (#11)
#
# The middle rung was added in #17. Before it, a machine with the hub sitting right next to the
# repo still fell through to the URL, which 404s while the hub is private — so the staleness
# check skipped everywhere and the vendored oracle was never actually checked for drift.
#
# --publish deliberately does NOT use the middle rung: it WRITES, and inferring a destination is
# a different risk from inferring a source. Publishing stays explicit about where it is going.
#
# The oracle is GENERATED in the canonical Swift repo (GenerateParityOracle) and
# published into the hub; every other repo pulls. Only Swift publishes, because only
# Swift mints: a tracking edition minting the oracle would make the oracle record
# what the tracking edition does, which is precisely backwards.

set -euo pipefail

ORACLE_URL="${ORACLE_URL:-https://raw.githubusercontent.com/dwsdolce/guitar-tap-project/main/tooling/parity/parity-oracle.json}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# The hub directory as a sibling of this repo — the standard developer layout, and the one the
# rest of the toolchain already assumes (gen_parity_map.py resolves the code repos the same way).
# Read only if present; never fetched, never created.
SIBLING_ORACLE="$REPO_ROOT/../guitar-tap-project/tooling/parity/parity-oracle.json"
# Beside the script, not at a hardcoded tooling/ — the Python repo spells it Tooling/,
# and a case-sensitive filesystem would not forgive the assumption.
DEST_DECL="$SCRIPT_DIR/oracle-dest.txt"

if [[ ! -f "$DEST_DECL" ]]; then
  echo "ERROR: $DEST_DECL not found." >&2
  echo "       Create it containing this repo's vendored oracle path, relative to the" >&2
  echo "       repo root, e.g.: test/fixtures/parity-oracle.json" >&2
  exit 2
fi
LOCAL="$REPO_ROOT/$(grep -vE '^\s*(#|$)' "$DEST_DECL" | head -1 | tr -d '[:space:]')"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

# Canonical comes from the first of these that is available:
#   1. ORACLE_SRC, when set explicitly — always wins.
#   2. The hub directory sitting beside this repo. Nothing is fetched or checked out: if that
#      file is there it is read, and if it is not, this rung is skipped. The rest of the
#      toolchain already resolves the repos this way (gen_parity_map.py: "the code repos are
#      siblings of the hub").
#   3. The published URL, for a working copy with no hub beside it.
#
# Rung 2 was missing until #17. Without it the staleness check fell straight through to a URL
# that 404s while the hub is private, so it skipped on every machine that had the hub sitting
# right next to it — the vendored oracle was never actually checked for drift anywhere.
#
# Rungs 1 and 2 read a WORKING COPY, not a published artifact, so what they compare against is
# whatever is on disk — including edits nobody has committed yet. That is usually what you want
# (mint-oracle.sh --publish writes into the hub, and a repo that has not synced should report
# drift straight away) but it is not the same claim as matching a published file. So the result
# says which kind of source it used, and a reader can judge it: a pass against a working copy is
# a statement about this machine, a pass against the URL is a statement about the project.
fetch_canonical() {
  local src=""
  if [[ -n "${ORACLE_SRC:-}" ]]; then
    src="$ORACLE_SRC"
    [[ -d "$src" ]] && src="$src/tooling/parity/parity-oracle.json"
    if [[ ! -f "$src" ]]; then
      echo "ERROR: ORACLE_SRC given but no oracle at $src" >&2
      exit 2
    fi
    CANONICAL_KIND="local working copy, via ORACLE_SRC"
  elif [[ -f "$SIBLING_ORACLE" ]]; then
    src="$SIBLING_ORACLE"
    CANONICAL_KIND="local working copy, the hub beside this repo"
  fi

  if [[ -n "$src" ]]; then
    cp "$src" "$tmp"
    CANONICAL_DESC="$src"
    return
  fi

  if ! curl -fsSL "$ORACLE_URL" -o "$tmp"; then
    echo "ERROR: could not fetch canonical oracle from $ORACLE_URL" >&2
    echo "       No hub directory beside this repo either ($SIBLING_ORACLE)." >&2
    echo "       Point ORACLE_SRC at a hub working copy: ORACLE_SRC=~/src/guitar-tap-project $0 $*" >&2
    exit 2
  fi
  CANONICAL_DESC="$ORACLE_URL"
  CANONICAL_KIND="published"
}

case "${1:-}" in
  --publish)
    # Swift-only: push this repo's freshly generated oracle back to the hub.
    if [[ -z "${ORACLE_SRC:-}" ]]; then
      echo "ERROR: --publish needs ORACLE_SRC=<hub working copy> (the destination)." >&2
      exit 2
    fi
    hub="$ORACLE_SRC"; [[ -d "$hub" ]] && hub="$hub/tooling/parity/parity-oracle.json"
    cp "$LOCAL" "$hub"
    echo "✅ Published $LOCAL → $hub"
    echo "   Commit it in the hub, then run sync-oracle.sh in the other repos."
    ;;
  --check)
    fetch_canonical
    if diff -q "$tmp" "$LOCAL" >/dev/null 2>&1; then
      echo "✅ parity-oracle.json is in sync with canonical"
      echo "   Compared against: $CANONICAL_DESC"
      echo "   Source:           $CANONICAL_KIND"
    else
      echo "❌ DRIFT: local parity-oracle.json differs from canonical." >&2
      echo "   Canonical: $CANONICAL_DESC" >&2
      echo "   Source:    $CANONICAL_KIND" >&2
      echo "   Local:     $LOCAL" >&2
      echo "   The Swift algorithm/oracle changed without re-syncing this repo." >&2
      echo "   Run: ./tooling/sync-oracle.sh" >&2
      diff -u "$LOCAL" "$tmp" >&2 || true
      exit 1
    fi
    ;;
  "")
    fetch_canonical
    cp "$tmp" "$LOCAL"
    echo "✅ Updated $LOCAL from $CANONICAL_DESC"
    ;;
  *)
    echo "usage: $0 [--check|--publish]" >&2
    exit 2
    ;;
esac
