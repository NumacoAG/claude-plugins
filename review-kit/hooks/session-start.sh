#!/usr/bin/env bash
# review-kit SessionStart wrapper.
#
# Runs BOTH pieces the plugin owns at session start, in order:
#   1. the mobile rolling-window prune, DRY-RUN only (log-only, no --apply), at
#      most once per calendar day (stamp-gated), and
#   2. the folded-in dual-vault-sync session-start reconcile.
#
# Everything is best effort: the plugin is dormant until the user tracks a doc,
# so with no dvsync config and no tracked docs this exits 0 in silence. Always
# exits 0; never blocks the session.
set -uo pipefail

cat >/dev/null 2>&1 || true   # drain and ignore the hook's stdin JSON

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DV="$PLUGIN_ROOT/scripts/dvsync.py"

# ---------------------------------------------------------------- 1. daily prune
# DRY-RUN mobile rolling-window prune. Passes NO --apply, so it never deletes
# anything and never touches the laptop / OneDrive copy. Any summary goes to
# stdout so it lands in the session context. To enable REAL pruning, add --apply
# to the prune-all invocation below (see skills/review-kit/SKILL.md).
STAMP="$HOME/.claude/dvsync/.prune-stamp"
TODAY="$(date +%Y-%m-%d)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$TODAY" ]; then
  if command -v python3 >/dev/null 2>&1 && [ -f "$DV" ]; then
    OUT="$(python3 "$DV" prune-all --window-days 28 --quiet 2>&1 || true)"
    if [ -n "$OUT" ]; then
      printf 'review-kit mobile prune (DRY-RUN, no deletions):\n%s\n' "$OUT"
    fi
  fi
  mkdir -p "$HOME/.claude/dvsync" 2>/dev/null || true
  printf '%s' "$TODAY" > "$STAMP" 2>/dev/null || true
fi

# ---------------------------------------------------------------- 2. dvsync reconcile
# Reconcile every configured tier 1 doc on session open (union on divergence,
# pull phone edits into the laptop copy). Delegates to the folded-in dvsync
# session-start hook, which is itself a silent no-op when nothing is configured.
DV_HOOK="$PLUGIN_ROOT/hooks/dvsync-session-start.sh"
if [ -f "$DV_HOOK" ]; then
  bash "$DV_HOOK" </dev/null || true
fi

exit 0
