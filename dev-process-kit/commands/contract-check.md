---
description: Run the contract gate over this project and report every problem, writing nothing
argument-hint: "[--config path-to-contract.config.json]"
---

Run the contract gate read only over the project in the working directory. With no
argument the gate finds `contract.config.json` by walking up from the working
directory; pass `--config <path>` to point it at one explicitly.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/contract.py check $ARGUMENTS
```

Exit 0 means the contract is whole. Exit 1 means it is violated and every
problem is printed, one per line, classified structural, budget, or lint. Exit 2
means the gate could not run at all, which is a configuration or input problem
and never a contract problem.

Report the result to the user in full. Never summarise a structural problem away
and never propose relaxing a check to make a build green. If a problem needs a
document edit, say which document and which identifier, and remember that a
change to a requirement means regenerating the crosswalk in the same round.
