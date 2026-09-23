---
description: Stop syncing a doc between the vaults (leaves the files in place)
argument-hint: <relpath.md> [more.md ...]
---

Remove one or more markdown docs (the paths in `$ARGUMENTS`, relative to the
project root) from the tier 1 synced set. The files themselves stay in both
vaults untouched; they simply stop being reconciled.

Determine the current project from the git top-level folder name of the working
directory, then:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py untrack "<project>" $ARGUMENTS
```

Confirm to the user which files are no longer tracked.
