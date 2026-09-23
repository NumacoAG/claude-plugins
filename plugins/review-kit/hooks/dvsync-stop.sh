#!/usr/bin/env bash
# dvsync Stop hook (folded into review-kit).
# At the end of each assistant turn, reconcile EVERY configured tier 1 doc
# (across all projects, wherever they live): mirror any laptop edits out to
# mobile and pull back any out-of-band phone edits. Silent unless it actually
# moved bytes. Dormant (silent no-op) until the user tracks a doc. Always exits
# 0; never blocks.
set -uo pipefail

cat >/dev/null 2>&1 || true   # drain and ignore the hook's stdin JSON

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DV="$PLUGIN_ROOT/scripts/dvsync.py"

if command -v python3 >/dev/null 2>&1 && [ -f "$DV" ]; then
  python3 "$DV" sync-all --quiet 2>&1 || true
fi
exit 0
