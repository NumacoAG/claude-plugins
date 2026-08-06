---
name: project-plan
description: >-
  Create and maintain a software project's living "Project Status" doc
  (project-status.md in the repo's docs folder): a lean, future-only plan of
  Milestones, Deliverables, and Decision points, plus a brief status overview and
  linked deep dives. Use whenever the user says "use the project-plan skill",
  "create or update the project plan", "write or refresh the project status",
  "add a milestone, deliverable, or decision point", "what is the plan for
  <project>", or otherwise asks to create or maintain the planning doc for a
  software project. Also load it when opening any file named project-status.md.
  The skill owns the doc's schema and invariants (chronological, nearest first,
  future only, at most one decision point, ruthless trim, three to four sentence
  cap), the create versus amend flows, the table of contents plus bidirectional
  deep-dive links, mobile tracking, and the rule that defining new milestones,
  deliverables, or decision points goes through the obsidian-versioned-review
  regime while routine maintenance is a direct edit.
status: stable
version: "1.1 (2026-08-06, folded in from the standalone personal skill; generic phrasing, dvsync via the review-kit command)"
---

# project-plan, the living Project Status doc

The artifact through which a product owner follows AI-native software development on one project. It is **maintained by Claude and consumed by the owner**. Its sole purpose: give them, at any moment, an overview of where the project stands, the immediate next step, and the next deliverable goal and decision point. It is trimmed ruthlessly so it stays lean and never costs the reader focus.

One doc per project. It lives **in the project repo**, so the thread doing the work owns it in place, and it is mirrored to mobile for review.

It is a **tier 1** document in the [docs-vault](../docs-vault/SKILL.md) sense: human owned, versioned, reviewed. It is not part of the `specs/tier-1/` contract, carries no identifiers, and is not seen by the contract gate.

## When to invoke

Be generous. Trigger on:

- "use the project-plan skill", "create the project plan", "amend or update the project plan"
- "write or refresh the project status", "what is the status or plan for `<project>`"
- "add a milestone, deliverable, or decision point", "re-plan", "the demo is done, replan"
- After a milestone or deliverable lands and the plan needs to advance.
- Opening any file named `project-status.md` in a repo's docs folder.

## The doc: where it lives, how it is named

- **One file per project**, named `project-status.md`, in the repo's docs folder, under `project/` in a docs-vault tree.
- **Resolve the path** in this order:
  1. A `## Project-plan configuration` block in the repo's root `CLAUDE.md`, authoritative.
  2. Else `docs/project/project-status.md`, or `docs/project-status.md` in a repo with no bucket structure, honouring an existing `Docs/` casing.
  3. Else create the folder and put it there.
- **Tracked in git.** The project's history *is* the record of completed work, per invariant 1. Never gitignored.
- **Registered for mobile review** once, on create, with the review-kit command:
  ```
  /dvsync-track
  ```
  Tracking is idempotent. A doc inside a `~/Code/<project>` repo derives its mobile mapping automatically.

### Configuration, optional, in the project's root `CLAUDE.md`

```markdown
## Project-plan configuration

- **Doc path**: docs/project/project-status.md
- **Open command**: `open -a "Obsidian"`
```

## Core model, pinned (this is not textbook project management)

These definitions invert the textbook ones. Encode **these**, never the standard meanings.

- **Milestone = a thing to _do_**, an action, the immediate next step toward a Deliverable. *Implement the art for the game assets.* Textbook PM calls this a task; here it is a Milestone.
- **Deliverable = a value _state_ to reach**, an outcome that delivers real value, either product value for the end user or genuine progress for the project. It is **not** a thing to do; it is a state worth achieving. *A full level is playable by a stranger and they enjoy it.*
- **Decision point = a fork in the plan**, where assessing a deliverable or an external factor redoes the plan one way or the other. *The publisher runs the demo and decides whether to fund: if funded, build full scope; if not, cut or kill.*

## Invariants (hard rules)

1. **Future only.** The plan holds only what is still ahead. The moment a Milestone is done or a Deliverable is achieved, it **leaves the plan**. Its essence collapses into at most one line of **Status**; its detail survives in **git history**, not in the doc. There is no "Done" section.
2. **Chronological, nearest first.** The element closest in the future sits at the top.
3. **At most one Decision point** at a time. If a second starts to form, surface it rather than writing it in.
4. **Lean.** Status at most half a page. Every plan element explained in **three to four sentences**. Overflow goes to a deep dive, never into the plan entry.
5. **The taxonomy above is pinned.** Do not silently reinterpret Milestone or Deliverable.
6. **Deep dives are bidirectional and disposable.** An important plan element may link to a deep dive; the deep dive links back. When the element leaves the plan, **its deep dive leaves with it**. No orphans.
7. **Table of contents and internal links stay in sync** on every edit.
8. **Reviewed-change rule.** Defining new or re-scoped **Milestones, Deliverables, or Decision points** goes through the `obsidian-versioned-review` regime and bumps the version line. **Routine maintenance is a direct edit** and does not bump the version.
9. **Durable and mobile.** Committed to git, registered for mobile review. Never gitignored.

## The doc template

```markdown
# Project Status: <Project name>

**v1.0**

> Updated: <YYYY-MM-DD>

## Table of contents

- [[#Status]]
- [[#Project plan]]
- [[#Deep dives]]

## Status

<At most half a page. Where the project stands, what has been achieved in brief,
and the single next goal. A rolling brief, not a log. Trim ruthlessly: the detail
of past work lives in git history.>

## Project plan

> Chronological, nearest first, future only. **Milestone** = a thing to do.
> **Deliverable** = a value state to reach. At most one **Decision point**.

### Deliverable: <name>

<Three to four sentences: the value state this reaches and why it matters.> See [[#<Deep dive name>]].

- **Milestone:** <name>. <Three to four sentences: the action to take.>
- **Milestone:** <name>. <Three to four sentences.>

### Decision point: <name>

<Three to four sentences: the fork, what it depends on, the branches it opens.>

## Deep dives

### <Deep dive name>

<The longer detail for an important plan element that did not fit.>

Back to [[#Deliverable: <name>]].
```

## Structure and navigation

- **Group by Deliverable.** Each near-future Deliverable is a `### Deliverable: <name>` heading; the Milestones laddering up to it sit beneath, in order. The sequence of Deliverables is itself nearest first, so chronology holds while the ladder stays visible. The single Decision point sits at its chronological slot, usually right after the Deliverable feeding it.
- **Links are wikilink heading links** (`[[#Heading]]`). They render clickable on desktop and mobile, which is the review surface. Use them for the table of contents and both directions of every plan and deep-dive pair. Headings must be unique so links resolve.
- **Deep dives are opt-in and rare.** Typically only the next Deliverable earns one. An element that fits in three to four sentences gets none.
- **One H1 only.** Sections are H2; plan elements and deep dives are H3.

## Review regime, direct edit by default

The versioned-review regime applies **only when defining new Milestones, Deliverables, or Decision points**. Everything else is a direct edit.

**Direct edit (no green marking, no version bump):** advancing Status; trimming a completed Milestone or achieved Deliverable out of the plan; re-sorting nearest first; wording polish, fixing a link, refreshing the `Updated` date; syncing a deep dive to its already-agreed plan element. Just edit, commit, let the sync hooks reconcile to mobile. No ceremony.

**Versioned review (follow `obsidian-versioned-review`):** adding or re-scoping a Milestone, Deliverable, or Decision point.

Adapted for a repo doc (inline colour spans, no CSS snippet; review comments are found by diffing against the last committed version):

1. Make the change, green-mark **only** the new or changed planning text, bump `y` on the `**vN.y**` line, refresh `Updated`.
2. Open the doc with a one-click command; ask the reviewer to read the green parts.
3. Incorporate their comments and edits, remove the prior round's green, green the new round, bump `y`. Repeat.
4. On acceptance: strip all green (keep the text), bump to the next integer (`v1.x → v2.0`), commit. The doc keeps living; there is no permanent lock, the version simply records the last reviewed planning baseline.

The `**vN.y**` line advances **only** on a completed planning review, so a version bump always means a planning change was reviewed.

## Create flow

1. Resolve project and doc path. If the doc exists, switch to **Amend**.
2. Gather the initial picture: read the repo (README, root `CLAUDE.md`, recent commits, open issues), and ask for the current status, the nearest Deliverables, the Milestones reaching the first one, and any single Decision point.
3. Scaffold from the template. The initial draft is `**v0.1**` and is written **plain; do not blanket-green an all-new doc**. Creating the doc is itself a planning act, so it goes through review: iterate on comments, then bump to `**v1.0**` on acceptance.
4. Register for mobile review once.
5. Commit, and open the doc with a one-click command.

## Amend flow (the maintenance contract, the heart of the skill)

1. **Read the current doc in full.**
2. **Classify the change**: maintenance or planning change.
3. **Run the garbage-collection pass every time, in either mode:**
   - Remove every element now in the past. Collapse each achieved Deliverable into **at most one line** of Status.
   - Remove the deep dive of any element that left the plan.
   - **Re-sort** nearest first.
   - Enforce **at most one Decision point**; flag it if a second is forming.
   - **Rebuild the table of contents**; verify every plan and deep-dive link resolves **both ways**.
   - Refresh the `Updated` date.
4. **Run the checklist below.**
5. **Commit.** If it was a reviewed planning change, open the doc for review.

## Per-amend checklist

- [ ] Plan contains **only future** items.
- [ ] **Nearest-first** ordering holds.
- [ ] **At most one Decision point.**
- [ ] **Status at most half a page.**
- [ ] Every plan element **at most three to four sentences**.
- [ ] Every deep dive links back to its plan element, and the element links to it.
- [ ] **Table of contents** matches the current headings.
- [ ] Achieved Deliverables **collapsed into Status**; their deep dives removed.
- [ ] Version bumped and greened **only** if this was a planning change.
- [ ] `Updated` date refreshed.
- [ ] Doc is tracked for mobile review.

## Rendering gotchas

Follow `obsidian-versioned-review` verbatim. The ones that bite here:

- **Green-mark with inline spans only**, never callouts or blockquote-prefixed blocks.
- **Escape `&lt;` and `&gt;`** for any literal angle bracket inside a span, or placeholders get swallowed.
- A link wrapped in a green span will not render as a link. Keep links outside the span; acceptance strips the green anyway.
- Cross-references are **always** clickable `[[#Heading]]` links, never bare prose.

## What NOT to do

- **Do not keep completed items "for the record".** Git history is the record.
- **Do not let the plan hold anything but future, nearest-first work.**
- **Do not use textbook definitions.** Milestone is an action, Deliverable is a value state.
- **Do not blanket-green an all-new doc.** `v0.1` is plain.
- **Do not run the review cycle for routine maintenance.** That is friction with no return.
- **Do not accumulate orphan deep dives.** A deep dive dies with its plan element.
- **Do not add a second Decision point** without surfacing it first.
- **Do not gitignore the doc**, and do not forget to track it on create.

## Related

- [docs-vault](../docs-vault/SKILL.md): owns the tree this doc sits in, and stubs `project-status.md` for this skill to fill.
- [tier-1-contract](../tier-1-contract/SKILL.md): owns the `specs/tier-1/` contract. The plan points at what gets built; the contract specifies what it must do.
- `obsidian-versioned-review` (review-kit): the source of the green-mark and comment-by-diff conventions used for planning reviews.
- `qa-audit` (review-kit): the sibling pattern, a slim live per-project repo doc with the same adapted review conventions.
