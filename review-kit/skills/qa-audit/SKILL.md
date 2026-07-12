---
name: qa-audit
description: Run the post-release QA audit workflow — write a slim release-notes entry to a project's live qa-log file (pill + feature bullets + checklist), iterate with the user via green-marked review comments per the obsidian-versioned-review convention, dispatch fixes between rounds, carry unchecked items forward to the next release, and archive locked entries to qa-audit-archive. Trigger when the user asks to "write the qa-log", "do a release", "release notes", "qa audit", "lock the audit", "archive this release", or otherwise references the release-QA workflow. Also auto-applies after a fan-out wave's final merge lands so the orchestrator surfaces the new release for verification.
status: stable
version: 1.4 (2026-05-30 — the user's review comments are plain `>`, found by diff; `**MP**` marker retired)
---

# qa-audit — release QA workflow

Post-release QA workflow: orchestrator writes a SLIM release-notes
entry, user reviews + tests + comments in Obsidian, orchestrator
dispatches fix rounds between iterations, locked entries archive
cleanly with their verification history, and **unchecked items
carry forward** to the next release until explicitly dismissed or
passed.

## When to invoke

Trigger phrases (be generous):

- "write the qa-log" / "release notes" / "do a release"
- "qa audit" / "qa cycle" / "ready to read"
- "lock the audit" / "close this release" / "archive this release"
- "carry forward" / "what's still open"
- After a fan-out wave's final Janus merge — auto-apply if the
  project has a qa-audit configuration in its CLAUDE.md.

## Configuration — lives in the project's root `CLAUDE.md`

Look for a block like:

```markdown
## QA audit configuration

- **Live qa-log**: qa-log.md
- **Archive**: qa-audit-archive.md
- **Open command**: `open -a "Obsidian"`
```

Default paths: `qa-log.md` and `qa-audit-archive.md` at the project
root. Tracked in git (release history is durable).

## Invariants

1. **`qa-log.md` ALWAYS holds at most one release entry** at a time.
   Before writing a new release entry, any existing entry must
   already be locked + archived.
2. **`qa-audit-archive.md` is reverse-chronological** — newest
   locked release at top.
3. **The live entry is SLIM**: pill + brief feature-bullet list +
   checklist. No verbose summaries, no narrative "what changed"
   sections, no per-version archeology. The archive carries that
   detail; the live entry stays focused on "what to verify, now."
4. **Unchecked items carry forward** to the next release entry
   automatically. They appear in a "Pending — carries into next
   release" section in the slim live qa-log between releases, and
   the next release entry's checklist folds them in. Items are only
   removed when (a) the user ticks them as passed, or (b) the user
   explicitly dismisses them in chat.
5. **the user's review notes are plain `>` blockquotes — found by diff, no marker.**
   The user just writes `> their comment` anywhere in the entry (and deletes the
   `✅`/`❌` marker that doesn't apply). The orchestrator identifies the user's
   additions by **diffing the live file against the version it last
   committed** — every blockquote / edit / deletion the user made since is their
   instruction. Do NOT rely on a tag; `**MP**` and `>mp` markers are
   retired. Keep a copy/memory of the committed version so the diff is
   computable. **Strip-and-reapply** (see §Version + change-mark
   conventions): the orchestrator removes the user's `>` notes when it
   processes the round.
6. **Pass/fail markers — DUAL-EMOJI convention (v1.3 — adopted 2026-05-29):**
   The orchestrator writes each assertion with BOTH `✅` and `❌`
   pre-typed. The user reviews by **deleting the marker that doesn't
   apply**. Easier than typing checkbox states.
   - `- ✅ ❌ <assertion>` = both markers present → **NOT yet reviewed**.
   - `- ✅ <assertion>` = the user deleted the ❌ → **PASSED**.
   - `- ❌ <assertion>` = the user deleted the ✅ → **FAILED** (the user adds a
     `>` note explaining what failed).
   - **Round transitions**: items the user kept as `✅` carry forward as
     passed. Items the user marked `❌` and the orchestrator addressed in
     a fix wave: reset to `- ✅ ❌` (awaiting re-verification) with a
     note like "fixed in v1.x — please re-verify".
   - **Historical note**: prior to v1.3 the convention was checkboxes
     (`- [ ]` unchecked, `- [x]` passed, `- [x] ❌` failed). When
     migrating an existing qa-log, replace `- [ ]` with `- ✅ ❌`
     verbatim; `- [x]` becomes `- ✅` (just the pass marker).
7. **Lock allowed even with failing checks** — failing items + new
   findings carry forward; the audit itself locks. On lock, all
   green/orange marks are stripped and the entry archives verbatim.
8. **Every round bumps the entry's minor version** — whether the
   fix is code, doc-only, or just "ack and re-plan". See §Version +
   change-mark conventions.

## The SLIM live-entry format (v1.1 — adopted 2026-05-29)

The live `qa-log.md` carries ONLY:

1. Top-of-file working-agreement blockquote (project-stable).
2. Either an open release entry (active QA) OR a "Pending — carries
   into next release" section (between releases).
3. NO verbose summaries. NO per-version narrative ("v1.1 fix wave
   for X..."). That goes to the archive on lock.

### Release entry template (slim)

```markdown
## Release `<PILL>` — <YYYY-MM-DD>

**v1.x** *(orange-wrapped while in flux; default colour between rounds)*

- **HEAD SHA**: `<sha>`
- **PRs in this release**: <#a>, <#b>, ...
- **Launch**: <one line>

### New in this release

- <succinct bullet per feature / fix>
- <succinct bullet>
- <succinct bullet>

### What to check

#### A. <Area> (<round-names>)
- ✅ ❌ <concrete assertion>
- ✅ ❌ <concrete assertion>

#### B. <Area>
- ✅ ❌ <concrete assertion>

### Carried over from previous release(s)

(Items from prior unchecked checks + open bugs/features still
applicable. Pulled from the "Pending" section that lived in the
qa-log between releases.)

- ✅ ❌ <carried assertion>
- **B<n>** — <one-line bug description> (carries from <previous pill>).
- **F<n>** — <one-line feature description> (carries from <previous pill>).

### Verification log

<!-- the user comments with plain `>` blockquotes (no marker). The orchestrator
     finds them by diffing against its last committed version, and strips
     them on the next round. -->
```

### "Pending" between-release template

When a release is locked + archived but no new release has shipped
yet, the live qa-log looks like:

```markdown
# QA log — <project name>

> <working agreement>

(No live release. Previous release `<pill>` locked + archived to
`qa-audit-archive.md` on <date>.)

---

## Pending — carries into next release

Items still open from `<previous pill>` (the user's QA pass found these
unresolved). The next release entry will fold them into its
checklist unless explicitly dismissed.

### Bugs
- **B<n>** — <description>.

### UX fixes
- **F<n>** — <description>.

### Features
- **F<n>** — <description>.

### Algorithm
- **F<n>** — <description>.

### Carried-over unchecked items (from <previous pill>'s checklist)
- ✅ ❌ <verbatim assertion that was unchecked>
- ✅ ❌ <another>
```

## Version + change-mark conventions

Adapted from the `obsidian-versioned-review` skill for live project
files. The qa-log uses inline HTML spans (no vault CSS snippet
needed) — they render cleanly in Obsidian's default view.

### Per-round version bumps

Every time the user provides feedback and the orchestrator does a round in
response (whether code, doc-only, or "ack and re-plan"), bump the
entry's minor version (v1.0 → v1.1 → v1.2 …). Each round produces one
immutable point in the entry's history.

- **v1.0** is the orchestrator's initial write of the release entry.
- **v1.x for x ≥ 1** means "after round x of the user review + orchestrator
  response".

### Strip-and-reapply the user's comments

When the orchestrator processes a round of the user's feedback, **all of
The user's notes from the previous round are removed** from the live
qa-log entry (their `>` blockquotes, embedded `![[...]]` screenshot
references, and any free-form annotations). The orchestrator locates
them by diffing the live file against the version it last committed.

- Comments are NEVER lost — they're captured implicitly in the new
  round's marker-state changes (✅/❌ remaining vs reset) + green-marked
  "fixed in v1.x" notes, and in git history of the qa-log file.
- The live entry reflects the CURRENT STATE of the audit, not its
  cumulative history. The narrative of "what changed in v1.x" lives in
  the archive on lock (as preserved git history) and in the next-round
  commit message — not as verbose prose in the live qa-log.

### Green = net-new, orange = modified

- **Green** (`<span style="color:#4ade80">…</span>`) marks **net-new**
  content added in the current revision — new assertions, new
  carried-over items, "fixed in v1.x" annotations on items that just
  got addressed.
- **Orange** (`<span style="color:#fb923c">…</span>`) marks **modified**
  content — existing items substantively rewritten in this round.
- The current revision's marks are stripped at the START of the next
  revision and reapplied for that revision's deltas only. At any
  moment, the colors show what changed in the **most recent round** —
  never cumulative history.
- Trivial mechanical edits (renames, whitespace, single-word
  substitutions) are not coloured.
- Deletions are not coloured — they are absent.

### Version line treatment

The `**v1.x**` line directly under the pill header can be wrapped in
the orange span while "in flux" (orchestrator has feedback in hand but
hasn't yet finished processing it), and stripped back to default once
the round is processed. In practice rounds are processed in one shot,
so the orange version line state is brief.

## Workflow steps

### Step 1 — Orchestrator writes the slim entry

After a fan-out wave merges + .app rebuilt:

1. Read existing `qa-log.md`. If it holds an open release entry,
   ask the user whether to lock-archive or bump-version with the new
   work folded in.
2. If qa-log shows only "Pending" + previous-release reference, the
   new release ENTRY is fresh. Build it using the slim template.
   Fold pending items into "Carried over from previous release(s)"
   section.
3. Surface to the user with `open -a "Obsidian" "<absolute-path>"`.
4. Send the user a tight chat message: pill, headline, "comment inline,
   ping when ready."

### Step 2 — The user reviews + tests

The user launches the .app, deletes the `✅`/`❌` marker that doesn't apply,
adds `>` notes on failures. Pings the orchestrator when done with a
batch ("ready to read").

### Step 3 — Orchestrator reads + iterates

1. Read qa-log.md in full.
2. Enumerate passed / failed / new asks.
3. Decide:
   - Doc-only edits → apply + ping.
   - Code changes → dispatch fan-out rounds, plan merge wave, then
     write the NEXT release entry (with carry-forward).
   - Audit complete → ask the user to lock.

### Step 4 — Iterate

Steps 2-3 repeat. Each cycle that ships code → next release entry.
Between releases, the qa-log shows "Pending".

### Step 5 — Lock + archive

When the user instructs ("lock", "close this release", "archive"):

1. Append the entry's verbatim content to the TOP of
   `qa-audit-archive.md`.
2. Annotate `**LOCKED** YYYY-MM-DD — <disposition>` at the top of
   the archived entry. Disposition examples:
   - `all checks passed`
   - `9/14 passed, 5 items carried forward`
   - `locked with B<n> unresolved — see <next-release> notes`
3. **Reset `qa-log.md`** to the between-release format: working
   agreement + "Pending" section listing all unchecked items + open
   bugs/features that carry forward.
4. Commit both files in one commit:
   `chore(qa-audit): archive <pill> + reset live log`
5. Push.

## Carry-forward rules

- **Default**: every unchecked `- [ ]` item AND every open `B<n>` /
  `F<n>` from the locked release moves into the live qa-log's
  "Pending" section. When the next release ships, those items get
  folded into the new release entry's checklist.
- **Dismissal**: The user explicitly says "drop B<n>" / "dismiss F<n>"
  / "don't carry that forward". Orchestrator removes from Pending,
  notes the dismissal in the next archive entry's disposition.
- **Resolution**: if a `B<n>` was the target of a fix wave and the
  next release's check items pass for it, the bug is resolved — it
  doesn't carry further. Annotate "**B<n>** — RESOLVED in
  <new-pill>" in that release's checklist.
- **Re-numbering**: don't re-number B/F items across releases. B3
  stays B3 forever. Sequential numbers, no reuse, no gaps when
  resolved (they just don't carry).

## Edge cases

- **The user wants to add a new ask mid-audit that's outside the current
  release's scope**: capture as a new B/F item; if it doesn't tie
  to the current release's checks, dispatch a fix wave; otherwise
  add to "What to check" as a new sub-section.
- **A fix wave introduces its own bugs**: track in the next release
  entry as a new B<n>.
- **Project has no `qa-log.md` yet**: write the skeleton file before
  the release entry. Files are tracked in git (NOT gitignored).
- **The archive file gets very long**: that's expected; reverse-
  chrono means the user sees the most recent locked release at the top
  without scrolling. Skill never trims the archive.

## What NOT to do

- **Don't write multiple release entries to `qa-log.md`.** One at a
  time, always.
- **Don't keep verbose narrative summaries in the live qa-log.**
  Slim format. Detail goes to the archive on lock.
- **Don't drop unchecked items without explicit dismissal.** The
  carry-forward is the safety net for things that didn't get
  checked OR didn't pass.
- **Don't archive prematurely.** Only on explicit lock instruction
  from the user.
- **Don't trim the archive** ever.
- **Don't put orchestrator opinion in the verification log** — the
  log is for the user.
- **Don't gitignore the qa-log files.** They're tracked artifacts.

## Related skills

- `obsidian-versioned-review` — source of the green-marking +
  diff-based comment-detection conventions. This skill adapts them for
  project-repo files (no CSS snippet needed; the user writes plain `>`
  comments, found by diff against the committed version).
- `agent-fanout` — used by step 3 when dispatching fix rounds.

## Version history

- **v1.2 (2026-05-29)** — per-round version bumps explicit; strip-and-
  reapply the user's comments on each new round; green/orange change-mark
  conventions adapted from `obsidian-versioned-review`.
- **v1.1 (2026-05-29)** — slim live-entry format (no verbose
  summaries / per-version narratives); carry-forward rule for
  unchecked items + open bugs/features; explicit dismissal protocol.
- **v1.0 (2026-05-28)** — initial release.
