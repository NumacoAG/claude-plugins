#!/usr/bin/env bash
# Install the local pre-commit publish gate. Run once per clone:
#
#   ./scripts/install-hooks.sh
#
# The hook refuses any commit that would put private data into this repo. It
# reads your site-specific terms (your name, your customers) from
# ~/.config/numaco-publish-gate/terms.txt, which is never committed. CI runs the
# same script with only the generic rules, so the local hook is strictly the
# stronger of the two: keep it installed.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hook="$repo_root/.git/hooks/pre-commit"

cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"

# Scan what is about to be committed, not the whole working tree, so unrelated
# local scratch files cannot block an otherwise clean commit.
staged="$(mktemp -d)"
trap 'rm -rf "$staged"' EXIT
git diff --cached --name-only --diff-filter=ACM -z \
  | while IFS= read -r -d '' f; do
      mkdir -p "$staged/$(dirname "$f")"
      git show ":$f" > "$staged/$f" 2>/dev/null || true
    done

# The baseline must travel with the staged copy or every known-safe match fires.
[ -f "$repo_root/.publish-allow" ] && cp "$repo_root/.publish-allow" "$staged/" || true

if ! python3 "$repo_root/scripts/publish_gate.py" "$staged"; then
  echo
  echo "pre-commit: refusing to commit private data (see the hits above)."
  echo "If a match is genuinely safe, add it to .publish-allow with a reason."
  echo "To bypass in a real emergency: git commit --no-verify"
  exit 1
fi
HOOK

chmod +x "$hook"
echo "installed $hook"

terms="${NUMACO_GATE_TERMS:-$HOME/.config/numaco-publish-gate/terms.txt}"
if [ ! -f "$terms" ]; then
  echo
  echo "WARNING: no site-specific terms file at $terms"
  echo "The hook will run generic rules only (emails, GUIDs, home paths, private keys)."
  echo "Add one regex per line (your name, your customers) to catch the rest."
fi
