---
name: numaco-update
description: Update the installed Numaco plugin packet in Codex and verify that all six plugins are enabled. Use when the user asks to update Numaco plugins or invokes numaco-update.
---

# Update the Numaco packet in Codex

Resolve the root of this installed plugin and run with an available Python:

```text
python "<hub-root>/scripts/codex_packet.py" --update
```

The helper refreshes a Git marketplace only when its checkout is clean, then
installs changed, missing, or disabled plugins and verifies all six. Unchanged
enabled packages are left alone. For a local marketplace it uses the local
files without fetching upstream. Report this distinction accurately.

If local edits block a Git refresh, preserve them and report the affected paths.
Do not reset or discard changes. Do not switch marketplace sources silently.
Do not promise Claude's automatic updates or reload commands in Codex.

Start a new Codex task after updates to load changed skills and MCP tools.
