---
name: numaco-update
description: Update the installed Numaco plugin packet in Codex and verify that all six plugins are enabled. Use when the user asks to update Numaco plugins or invokes numaco-update.
---

# Update the Numaco packet in Codex

Resolve the root of this installed plugin and run with an available Python:

```text
python "<hub-root>/scripts/codex_packet.py" --update
```

The helper fetches the marketplace's configured Git ref and fast-forwards only
a clean checkout. It then installs changed, missing, or disabled plugins and
verifies their versions and enabled state. Unchanged enabled packages are left
alone, including running MCP servers and local cache edits. For a local
marketplace it uses local files without fetching. Report this distinction.

Do not substitute `codex plugin marketplace upgrade`: that command can replace
unchanged caches, lose local cache edits, and fail on running Windows MCP servers.

If local edits, local commits, missing source metadata, or a source mismatch
block the refresh, preserve the checkout and report the cause. Do not reset,
discard changes, or silently switch source/ref. If installing a changed plugin
hits a Windows lock, report it and ask the user to close the affected tool before
retrying; do not kill processes or force-delete caches.
Do not promise Claude's automatic updates or reload commands in Codex.

Start a new Codex task after updates to load changed skills and MCP tools.
