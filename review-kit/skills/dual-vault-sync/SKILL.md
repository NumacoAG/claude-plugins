---
name: dual-vault-sync
description: >-
  Keep a small "tier 1" set of markdown docs reconciled between the user's laptop (wherever a doc lives on the Mac: a ~/Code git repo, the personal Obsidian vault, the Numaco BOK, anywhere) and their mobile iCloud Obsidian vault rooted at iCloud~md~obsidian/Documents/Code. Use whenever the user authors or reviews any markdown doc they will also read or correct on their phone, or says "put this on mobile", "track this for mobile", "is this synced to my phone", "pull my phone edits", "reconcile the vaults", "sync both vaults". For a doc inside a ~/Code project the mobile mapping derives automatically; for a doc anywhere else, ASK how to scaffold it on the mobile vault (which Code/<project> folder and filename) before tracking, always offering a do-not-sync option. Only registered files are ever synced; nothing else in either vault is read, written, or deleted. The plugin's SessionStart and Stop hooks reconcile every configured doc automatically (with a cross-process lock for parallel sessions); this skill covers when to register a doc and how the reconcile behaves.
status: stable
version: 0.2 (2026-06-13 — works for any doc location; ask-to-scaffold for non-Code; sync-all + lock)
---

# dual-vault-sync

The user reviews and corrects markdown on their Mac and also on their phone, and wants both
sides kept in sync without ever saying which device they used.

- **Laptop side**: wherever the doc canonically lives on the Mac. A `~/Code/<project>`
  git repo, a personal Obsidian vault at `~/Obsidian/MyVault/`,
  a body of knowledge in OneDrive, anywhere.
- **Mobile side**: one iCloud Obsidian vault rooted at
  `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Code`. Every mobile doc
  lives under a `<project>` subfolder of that `Code` root (one subfolder per
  project).

For a `~/Code` project the two folder names match and the mapping derives itself.
For a doc that lives anywhere else, you choose the mobile `<project>` folder and
filename with the user (see "When to register").

## The one rule that shapes everything: only tier 1 docs sync

The laptop tree has thousands of markdown files (node_modules, vendored docs).
The mobile vault must stay tiny: only the handful of docs the user actually reads and
reviews on their phone. So the sync operates on an **explicit registered set**, not
on "all markdown". A file is synced only after it is tracked. Everything else in
both vaults is invisible to the tool: never read, written, mirrored, or deleted.

## When to register (track) a doc

Track a doc the moment the user authors or reviews it and will also read it on the
phone, or when they say so ("put this on mobile", "track this"). Two cases:

**Case A: the doc is inside a `~/Code/<project>` git repo.** Track it directly;
the project name and mobile mapping derive automatically:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py track <project> <relpath.md>
```

`<relpath>` is relative to the repo root and is identical on both sides. Tracking
auto-initializes the project (laptop root from the git top-level, mobile root from
the iCloud base) and reconciles immediately, so a brand-new laptop doc is created
on mobile right away.

**Case B: the doc lives anywhere else** (personal vault, BOK, an arbitrary
folder). Before tracking, **ask the user how to scaffold it on the mobile vault** with
`AskUserQuestion`:

1. Which `<project>` folder under the mobile `Code` root to use. Suggest one from
   the doc's topic and offer the existing folders (`dvsync` has no "list projects"
   surface yet; read `~/.claude/dvsync/` to see what exists).
2. Confirm the filename or relpath it should take under that folder.
3. **Always include a "do not sync this doc" option** so private notes can opt out.

Then create the mapping and track in one call:

```bash
DV=${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py
python3 "$DV" track <project> <relpath.md> --laptop "<laptop-root-dir>" --mobile "<absolute .../Documents/Code/<project>>"
```

`<laptop-root-dir>` is the Mac folder that `<relpath.md>` is relative to (usually
the doc's own folder, with relpath equal to the filename). The roots are saved, so
later docs for the same `<project>` only need the plain `track` form.

Do **not** bulk-track. Add docs one at a time as they become tier 1.

## How reconcile behaves (the `sync` operation)

For each tracked file the tool compares laptop (L), mobile (M), and a stored base
snapshot (B = last synced content), then:

- **L equals M**: in sync (base refreshed if both moved together).
- **only L changed** since base: mirror L to mobile.
- **only M changed** since base: mirror M to laptop.
- **both changed** (L differs from M): **union merge** (base, L, M) with
  `git merge-file --union`, so both sides' lines survive with no conflict
  markers, then write the merged result to both vaults.
- **new on one side only**: create the counterpart from the side that has it.
- **deleted on one side**: reported, never auto-applied. Surface it to the user and
  let them decide.

`pull`, `push`, and `sync` are the same operation (the algorithm is symmetric and
base-driven). `status` is a read-only dry run.

## Automatic operation (the hooks)

This skill ships in a plugin whose hooks do the routine work, so the user never has to
say which device they edited on. Both hooks run `dvsync sync-all`, which reconciles
**every** configured project regardless of where the session's working directory
is (so it covers personal-vault and BOK docs, not just `~/Code`):

- **SessionStart**: reconciles all tracked docs when a session opens. Out-of-band
  phone edits land in the laptop copies before work begins. If anything moved, the
  summary is surfaced to you; relay it to the user.
- **Stop**: at the end of each turn, reconciles again (mirror laptop edits out,
  pull phone edits back). Silent when nothing moved.

**Concurrency:** the user runs parallel sessions, so a cross-process lock serialises
reconciles. The Stop/SessionStart hooks take the lock non-blocking: if another
session (or a manual `sync`) is mid-reconcile, this pass skips silently rather than
racing. Never assume you exclusively own a tracked doc; if you see one being edited
live by another session, surface it instead of fighting over it.

You usually do not need to call `sync` by hand. Call it explicitly only to (a)
register a new doc via `track`, (b) show the user a `status` (read-only, no lock), or
(c) force an immediate reconcile mid-turn before opening a doc for them.

## Pairing with obsidian-versioned-review

The two skills are orthogonal: `obsidian-versioned-review` governs *how* a doc is
marked, versioned, and locked; `dual-vault-sync` governs *where the bytes live*.
Whenever you review a tier 1 doc, regardless of where it lives:

1. Track it (once) so it is in the synced set. For a non-`~/Code` doc, run the
   scaffold ask first (see "When to register").
2. SessionStart has already pulled any phone edits into the laptop copy; iterate
   on that reconciled copy per the review regime.
3. For a `~/Code` doc, edit in the **main checkout**, not a detached worktree, so
   the doc lives at the configured laptop path the hook reconciles. (Worktree
   edits only sync once merged back to the canonical path.)
4. Open the doc for the user as usual; they can read it on the phone, mark it there, and
   their marks reconcile back on the next session.

## Commands

```bash
DV=${CLAUDE_PLUGIN_ROOT}/scripts/dvsync.py
python3 "$DV" track   <project> <relpath.md> [more.md ...]   # register + initial sync
python3 "$DV" untrack <project> <relpath.md>                 # stop syncing (files left in place)
python3 "$DV" list    <project>                              # show roots + tracked set
python3 "$DV" status  <project>                              # read-only diff report
python3 "$DV" sync    <project>                              # reconcile now (alias: pull / push)
```

## Edge cases

- **iCloud not downloaded**: a mobile file that is still an iCloud placeholder
  (`.name.md.icloud`) is detected and skipped (quiet in hooks, shown in `status`),
  never treated as empty or deleted. Ask the user to open it on the Mac once to force a
  download.
- **Parallel sessions / offline storage**: a cross-process lock serialises
  reconciles; a project whose laptop and mobile roots are both missing (drive or
  iCloud offline) is skipped silently rather than reported as deleted.
- **First-time track of a doc that already differs on both sides**: there is no
  base yet, so the union may duplicate identical lines. Tell the user to skim the
  result once; subsequent rounds have a clean base and merge precisely.
- **New project**: tracking a file whose project has no mobile folder yet creates
  the counterpart subfolder under `.../Documents/Code/<project>`.
- **State location**: roots, tracked set, and base snapshots live at
  `~/.claude/dvsync/<project>/`, outside both vaults (touches neither git nor
  iCloud).
