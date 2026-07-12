#!/usr/bin/env bash
# dvsync SessionStart hook (folded into review-kit; invoked by session-start.sh).
# Reconcile EVERY configured tier 1 doc (across all projects, wherever they live)
# when a session opens: union on divergence, pull phone edits into the laptop
# copy. Any summary goes to stdout so it lands in the session context and Claude
# can tell the user what was reconciled. Dormant (silent no-op) until the user
# tracks a doc. Always exits 0; never blocks the session.
set -uo pipefail

cat >/dev/null 2>&1 || true   # drain and ignore the hook's stdin JSON

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DV="$PLUGIN_ROOT/scripts/dvsync.py"

if command -v python3 >/dev/null 2>&1 && [ -f "$DV" ]; then
  OUT="$(python3 "$DV" sync-all --quiet 2>&1 || true)"
  if [ -n "$OUT" ]; then
    printf 'dual-vault-sync reconciled tier 1 docs on session start:\n%s\n' "$OUT"
  fi
fi
exit 0
