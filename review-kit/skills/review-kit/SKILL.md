---
name: review-kit
description: Orientation for the review trio, the markdown co-authoring and release-QA workflow plus the mobile rolling-window prune. Read when working with obsidian-versioned-review or qa-audit, when the user asks how docs stay tiny on their phone, or when they want to pin a doc, prune the mobile vault, or enable real pruning. Explains how the two review skills, the dvsync engine, and the daily dry-run prune hook fit together.
status: stable
version: 1.0 (2026-07-10 initial)
---

# review-kit — the markdown review trio

review-kit bundles the two skills the user uses to co-author and QA markdown docs, and wires them to the dual-vault-sync engine so those docs reach their phone and the phone vault stays small over time.

## The trio

1. **obsidian-versioned-review** (`skills/obsidian-versioned-review/`): the green-mark versioned-review regime for co-authoring a single vault doc over multiple rounds. A doc under the regime carries a `**vN.y**` line under its H1. Claude green-marks its deltas with inline color spans, the user reviews and comments with plain `>` blockquotes, the loop repeats until the user says "lock". This is a verbatim copy of the canonical `~/.claude/skills/obsidian-versioned-review/SKILL.md`.
2. **qa-audit** (`skills/qa-audit/`): the post-release QA workflow. It writes a slim release-notes entry (pill, feature bullets, dual-emoji checklist) to a project's live `qa-log.md`, iterates with the user via the same green-mark conventions, carries unchecked items forward, and archives locked entries to `qa-audit-archive.md`. Verbatim copy of the canonical `~/.claude/skills/qa-audit/SKILL.md`.
3. **dvsync prune / pin** (the engine at `${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py`): keeps the mobile iCloud Obsidian vault tiny by removing stale mobile copies once the laptop copy is provably authoritative, without ever touching the laptop / OneDrive file.

## Auto-track on review (idempotent)

Whenever a review skill authors or reviews a doc the user will also read on their phone, it registers the doc with dvsync so both vaults reconcile automatically:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py track <project> <relpath.md>
```

`track` is idempotent: re-tracking an already-tracked doc is a no-op. For a doc inside a `~/Code/<project>` git repo the mobile mapping derives automatically; for a doc anywhere else (personal vault, BOK) pass explicit `--laptop` / `--mobile` roots after asking the user how to scaffold it on the phone. Track docs one at a time as they become tier 1; never bulk-track.

## Mobile rolling-window prune

Tracked docs accumulate on the phone. The prune trims ones that have gone quiet, so the mobile vault reflects what the user is actively reviewing.

- **Default is DRY-RUN.** `prune` and `prune-all` only report what WOULD be pruned unless `--apply` is passed. Nothing is deleted, and the laptop / OneDrive copy is NEVER touched (only the mobile copy is ever removed, and only under `--apply`).
- **Rolling window** defaults to 28 days (`--window-days`). A doc is a prune candidate only if neither side has been modified within the window.
- **Safety gate, per doc, in order**: skip if pinned; skip if the mobile copy is an iCloud placeholder or missing (cannot confirm a real sync); skip if still fresh; reconcile the doc first and abort on a conflict or skip; confirm the laptop copy is authoritative (base snapshot bytes equal the laptop bytes); only then, and only with `--apply`, delete the mobile file and untrack the doc atomically.
- **Audit trail**: every prune (and every would-prune, in dry-run) is appended to `~/.claude/dvsync/prune.log` and printed to stdout.

Commands:

```bash
# dry-run a single project (report only, zero deletions)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py prune <project>

# dry-run every project
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py prune-all

# custom window
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py prune-all --window-days 60
```

## Pinning a doc (exempt from prune)

A doc the user wants to keep on the phone indefinitely (even when it goes quiet) gets pinned:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py pin <project> <relpath.md>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py unpin <project> <relpath.md>
```

`pin` adds the doc to a per-project `pinned` list in its config; the prune always skips pinned docs. `unpin` removes the exemption.

## The daily prune hook (DRY-RUN by default)

review-kit ships a `SessionStart` hook (`hooks/session-start.sh`) that runs the prune at most once per calendar day, gated by a stamp file at `~/.claude/dvsync/.prune-stamp`. It runs:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py prune-all --window-days 28 --quiet
```

with NO `--apply`, so it is log-only: it reports would-prune candidates into the session context and to `prune.log`, and deletes nothing. The hook always exits 0 and never blocks a session.

### Enabling real pruning

The user controls when pruning becomes real. Two ways:

- **One-off**: run `prune-all --apply` (optionally with `--window-days N`) by hand when they want the phone vault trimmed now.
- **Automatic**: edit `hooks/session-start.sh` and add `--apply` to the `prune-all` invocation. After that, each day's first session actually deletes stale mobile copies and untracks those docs (laptop / OneDrive still untouched). Review a dry-run's `prune.log` output first to confirm the candidate list before flipping this on.

## Relationship to dual-vault-sync

review-kit bundles the sync engine directly: the single `dvsync.py` at `${CLAUDE_PLUGIN_ROOT}/scripts/` is the folded-in dual-vault-sync engine (there is no separate dual-vault-sync plugin). The engine owns continuous reconciliation (its SessionStart + Stop hooks, wired through this plugin, reconcile every tracked doc every turn); the pin/prune surface and the once-a-day prune sweep sit on top. The reconcile runs on the plugin's `Stop` hook and inside the `SessionStart` wrapper; the daily DRY-RUN prune runs at the front of that same wrapper.
