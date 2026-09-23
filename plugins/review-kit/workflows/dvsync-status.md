---
description: Show the dual-vault sync status (read-only) for the current ~/Code project
---

Determine the current project from the git top-level folder name of the working
directory. Then run a read-only dual-vault status report:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py status "<project>"
```

Report to the user, per tracked file, what would happen on the next reconcile: in
sync, mirror direction, union, new, or a deletion that needs their decision. Do not
write anything; this is a dry run.
