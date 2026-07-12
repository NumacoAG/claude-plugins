---
description: Register a markdown doc as a tier 1 file synced between laptop and mobile vaults
argument-hint: <relpath.md> [more.md ...]
---

Register one or more markdown docs (the paths in `$ARGUMENTS`, relative to the
project root) as tier 1 files to keep synced between the laptop vault and the
mobile (iCloud Obsidian) vault.

Determine the current project from the git top-level folder name of the working
directory, then:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py track "<project>" $ARGUMENTS
```

Tracking auto-initializes the project and runs an immediate reconcile, so a
brand-new laptop doc is created on mobile right away. Confirm to the user which files
are now tracked and the result of the initial sync.
