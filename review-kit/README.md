# review-kit

A Claude Code plugin that bundles a markdown review trio together with a
folded-in dual-vault-sync engine (there is no separate dual-vault-sync plugin;
its engine, commands, and reconcile hooks live here).

## What it bundles

- **obsidian-versioned-review** (skill): the green-mark versioned-review regime
  for co-authoring a vault doc over multiple rounds (a `**vN.y**` version line,
  inline color spans for deltas, plain `>` review comments, a lock procedure).
- **qa-audit** (skill): the post-release QA workflow. It writes a slim
  `qa-log.md` release entry (pill, feature bullets, dual-emoji checklist),
  carries unchecked items forward, and archives locked entries on lock.
- **dual-vault-sync** (folded-in engine + skill + commands): reconciles a small
  "tier 1" set of markdown docs between the laptop (wherever a doc lives on the
  Mac) and the mobile iCloud Obsidian vault. Reconcile runs automatically on the
  plugin's `SessionStart` and `Stop` hooks (union merge on divergence, a
  cross-process lock for parallel sessions).
- **mobile rolling-window prune**: keeps the phone vault tiny by removing stale
  mobile copies once the laptop copy is provably authoritative, without ever
  touching the laptop or OneDrive copy. A `SessionStart` wrapper runs it once per
  calendar day in DRY-RUN (log-only); real deletion is opt-in via `--apply`.

The two review skills are verbatim copies of their canonical originals (persona
references neutralized). The prune, pin, and reconcile capabilities all come from
the one bundled engine at `scripts/dvsync.py`.

## dual-vault-sync is optional and dormant by default

Nothing syncs until you register a doc. With no config and no tracked docs, every
hook is a silent no-op that exits 0: the plugin sits dormant. The moment you track
your first doc, the reconcile hooks and the prune sweep start acting on that doc
(and only the docs you track); everything else in both vaults is never read,
written, or deleted.

Register or inspect docs with the three slash commands:

- `/dvsync-track <relpath.md> [more.md ...]` : register a doc as a tier 1 synced
  file (auto-initializes the project and runs an immediate reconcile).
- `/dvsync-untrack <relpath.md>` : stop syncing a doc (both copies stay in place).
- `/dvsync-status` : read-only report of what the next reconcile would do.

For a doc inside a `~/Code/<project>` git repo the mobile mapping derives
automatically; for a doc anywhere else, pass explicit `--laptop` and `--mobile`
roots (see the dual-vault-sync skill).

## Layout

```
review-kit/
  .claude-plugin/
    plugin.json                 plugin manifest (registers the hooks)
  hooks/
    hooks.json                  SessionStart -> session-start.sh; Stop -> dvsync-stop.sh
    session-start.sh            wrapper: daily DRY-RUN prune, then the dvsync reconcile
    dvsync-session-start.sh     folded-in dvsync session-start reconcile
    dvsync-stop.sh              folded-in dvsync stop reconcile
  commands/
    dvsync-track.md             /dvsync-track
    dvsync-untrack.md           /dvsync-untrack
    dvsync-status.md            /dvsync-status
  scripts/
    dvsync.py                   the sync + prune engine (Python stdlib only)
  skills/
    review-kit/SKILL.md                    orientation for the trio (start here)
    obsidian-versioned-review/SKILL.md     verbatim copy
    qa-audit/SKILL.md                      verbatim copy
    dual-vault-sync/SKILL.md               when to track a doc; reconcile semantics
  README.md
```

State (roots, tracked set, base snapshots, prune log, the daily prune stamp)
lives at `~/.claude/dvsync/`, outside both vaults.

## Hooks

`hooks/hooks.json` wires two events, both to plugin-root paths:

- **SessionStart** runs `session-start.sh`, a wrapper that does two things in
  order: (1) the daily DRY-RUN mobile rolling-window prune (stamp-gated to once
  per calendar day, no deletions), then (2) the dvsync session-start reconcile
  (`dvsync-session-start.sh`), which pulls any out-of-band phone edits into the
  laptop copies before work begins.
- **Stop** runs `dvsync-stop.sh` at the end of each turn: it mirrors laptop edits
  out to mobile and pulls phone edits back. Silent unless it moved bytes.

Every hook is best effort and always exits 0; none block a session. To enable
real pruning automatically, add `--apply` to the `prune-all` invocation inside
`session-start.sh` (review a dry-run's `prune.log` first).

## Prune, pin, and reconcile commands (via the bundled engine)

```bash
DV=${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py

python3 "$DV" track   <project> <relpath.md>   # register + initial reconcile
python3 "$DV" untrack <project> <relpath.md>   # stop syncing (files left in place)
python3 "$DV" status  <project>                # read-only diff report (no lock)
python3 "$DV" sync-all                         # reconcile every configured project
python3 "$DV" prune <project>                  # DRY-RUN one project (default)
python3 "$DV" prune-all                        # DRY-RUN every project
python3 "$DV" prune-all --window-days 60       # custom rolling window
python3 "$DV" prune-all --apply                # ACTUALLY delete stale mobile copies
python3 "$DV" pin   <project> <relpath.md>     # exempt a doc from prune
python3 "$DV" unpin <project> <relpath.md>     # remove the exemption
```

Prune is DRY-RUN by default: it deletes nothing unless `--apply` is passed, and it
never touches the laptop or OneDrive copy (only the mobile copy is ever removed).
Every prune and would-prune event is logged to `~/.claude/dvsync/prune.log`.

## Runtime dependency

Python 3.9 or newer on `PATH` as `python3` (standard library only; no third-party
packages). The engine also shells out to `git merge-file` for union merges, which
ships with any git install. If `python3` is absent, the hooks detect it and exit 0
without acting, so the plugin degrades to a no-op rather than erroring.
