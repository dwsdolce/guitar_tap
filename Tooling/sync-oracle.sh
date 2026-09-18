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
#   ORACLE_SRC   a local hub checkout path or file — used while the hub is private
#   ORACLE_URL   a raw URL — the long-term source once the hub is public (#11)
#
# The oracle is GENERATED in the canonical Swift repo (GenerateParityOracle) and
# published into the hub; every other repo pulls. Only Swift publishes, because only
# Swift mints: a tracking edition minting the oracle would make the oracle record
# what the tracking edition does, which is precisely backwards.

set -euo pipefail

ORACLE_URL="${ORACLE_URL:-https://raw.githubusercontent.com/dwsdolce/guitar-tap-project/main/tooling/parity/parity-oracle.json}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
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

fetch_canonical() {
  if [[ -n "${ORACLE_SRC:-}" ]]; then
    local src="$ORACLE_SRC"
    [[ -d "$src" ]] && src="$src/tooling/parity/parity-oracle.json"
    if [[ ! -f "$src" ]]; then
      echo "ERROR: ORACLE_SRC given but no oracle at $src" >&2
      exit 2
    fi
    cp "$src" "$tmp"
    CANONICAL_DESC="$src"
  else
    if ! curl -fsSL "$ORACLE_URL" -o "$tmp"; then
      echo "ERROR: could not fetch canonical oracle from $ORACLE_URL" >&2
      echo "       While the hub is private this will 404 — set ORACLE_SRC to a local" >&2
      echo "       hub checkout instead: ORACLE_SRC=~/src/guitar-tap-project $0 $*" >&2
      exit 2
    fi
    CANONICAL_DESC="$ORACLE_URL"
  fi
}

case "${1:-}" in
  --publish)
    # Swift-only: push this repo's freshly generated oracle back to the hub.
    if [[ -z "${ORACLE_SRC:-}" ]]; then
      echo "ERROR: --publish needs ORACLE_SRC=<hub checkout> (the destination)." >&2
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
      echo "✅ parity-oracle.json is in sync with canonical ($CANONICAL_DESC)"
    else
      echo "❌ DRIFT: local parity-oracle.json differs from canonical." >&2
      echo "   Canonical: $CANONICAL_DESC" >&2
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
