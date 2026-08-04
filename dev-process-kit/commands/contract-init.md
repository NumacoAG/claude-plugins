---
description: Stand up a Tier 1 contract folder in this project (config, registry, front door, templates)
argument-hint: "[contract-dir]"
---

Stand up the Tier 1 contract for the project in the working directory. Load the
`tier-1-contract` skill first and follow it; this command is only the entry point.

Before writing anything, ask the user four questions and wait for the answers:

1. Where the contract folder should live (`$ARGUMENTS` if given, otherwise
   propose `docs/specs/tier-1`).
2. The requirement and journey identifier prefixes (propose `UR` and `DJ`).
3. Whether any prior contract is being inherited, and if so where it lives.
4. Whether the project has autonomous behaviour worth marking with an action
   glyph, and which character to use. Empty is a valid and common answer.

Then run the initialiser, carrying every answer through. Pass `--action-glyph` when
answer 4 named a character, and omit the flag when it did not:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/contract.py init \
  --contract-dir "<dir>" --requirement-prefix "<UR>" --journey-prefix "<DJ>" \
  --action-glyph "<glyph>"
```

It writes `contract.config.json` at the project root, an empty registry, the
contract folder with its front door README, and the reserved
`docs/specs/tier-2/proving/` directory. It refuses to overwrite anything that
already exists.

Answer 3 has no flag, deliberately: a project starts greenfield and acquires an
ancestor as a separate recorded act. When a prior contract is being inherited, tell
the user that the next step is `contract.py acquire`, which registers the source and
its expected count, and that until it runs, an inheritance marker in the prose is a
hard failure because the character has no referent.

Confirm to the user which files were created, then start the bootstrap: the day
census comes before the component split, and no identifier is minted until both
are approved.
