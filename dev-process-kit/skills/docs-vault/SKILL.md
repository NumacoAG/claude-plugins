---
name: docs-vault
description: >-
  Stand up OR migrate a project's docs/ markdown vault into the canonical
  five-bucket structure (reference, specs, project, verification, process), with
  the tier 1 and tier 2 split, a templated front-door README carrying a
  session-start reading order, and explicit handoffs to the skills that own
  individual buckets (tier-1-contract, project-plan, qa-audit,
  obsidian-versioned-review). TWO MODES. Mode A scaffolds the structure
  greenfield. Mode B migrates an existing, messy vault into the system:
  inventory every file, then produce an approval-gated keep-checklist, one
  tappable checkbox per file, reviewed through obsidian-versioned-review.
  Checked keeps a doc as tier 1 in its bucket; unchecked drops it (demoted to
  tier 2 only if still operationally useful, else deleted), biased aggressively
  toward deletion since docs are cheap to recreate from the repo. On lock,
  moves run through git mv so history survives, and only unchecked files are
  pruned. Use whenever the user says "scaffold the docs", "set up the docs vault
  or structure", "give this project the standard docs" (Mode A), or "migrate the
  docs", "reorganise the vault", "restructure the docs", "clean up the docs",
  "get rid of irrelevant docs", "make this vault conform" (Mode B). The skill
  owns the bucket taxonomy, the tier model, the README template, the project
  stub templates, and the migration safety regime. It shapes structure; it never
  writes product content.
status: stable
version: "1.0 (2026-08-06, folded in from the standalone docs-scaffold skill; five buckets, machine-readable docs absorbed into specs/tier-2)"
---

# docs-vault, the canonical project docs tree

One `docs/` markdown vault per project, organised by **audience and purpose**, so any thread in any repo navigates and maintains it the same way.

This skill **shapes the structure**. It does not write product content: it creates or relocates the buckets, the front-door README, and the tier 1 stubs, then hands each bucket to the skill that owns it. The most consequential handoff is `specs/tier-1/`, which belongs to [tier-1-contract](../tier-1-contract/SKILL.md) and is governed by the identifier registry and the gate.

## The tier model, one definition

**Tier is a property of the document, not of a folder.**

- **Tier 1** is human owned. It is reviewed and locked through the `obsidian-versioned-review` regime, carries a version line, and code cites it by locked version. Its most rigorous instance is the product contract under `specs/tier-1/`: one specification per component plus the Definition of Done, every promise carrying an identifier. Tier 1 also covers the project docs, the process docs, and the acceptance plans, which are reviewed the same way without carrying identifiers.
- **Tier 2** is maintained by Claude and needs no review mechanism. No version line, no lock, no green marking. Build notes with code, trait, and schema detail; the identifier registry and generated crosswalk; the cold-pickup handoff; per-feature walkthroughs.

`specs/` is the one bucket where both tiers sit side by side, so it names them as folders: `specs/tier-1/` and `specs/tier-2/`. Everywhere else a doc's tier is read off its version line.

**Tier 2 is not a comfortable middle.** A doc is either a tier 1 keeper the user owns, or it is tier 2, which means demoted to `specs/tier-2/` or deleted. Default toward deletion: docs are cheap to recreate and the repo is always readable, so **keeping a file needs a reason**.

## Two modes

- **Mode A, scaffold a new vault.** A repo with no docs, or a thin ad-hoc one, gets the skeleton laid greenfield.
- **Mode B, migrate an existing vault.** A repo with a real but messy pile of markdown gets reorganised into the system: every file inventoried, classified, an approval-gated plan surfaced, then executed with history preserved. Pruning happens here and only on the locked plan.

Both modes target the same taxonomy, tier model, README template, and conventions. Pick by starting state: an empty or near-empty `docs/` means Mode A, a populated one means Mode B.

Do **not** invoke this skill to *write* a vision, a specification, or a status doc. That is the owning skill's job. This skill stops once the structure stands or the migration is executed and verified.

## What it produces

```
docs/
├── README.md                   front door: the tree, the tier split, the session-start reading order
├── reference/                  external / immutable source + gathered research
│   └── research/               research dossiers (tier 2)
├── specs/                      the product and system design
│   ├── tier-1/                 the contract: spec-NN-*.md, definition-of-done.md, README.md
│   └── tier-2/                 tool written and Claude maintained
│       ├── machine-readable/   id-map.json (the registry) + contract-crosswalk.json
│       ├── walkthroughs/       per-feature operational prose
│       ├── architect-handoff.md   the cold-pickup state
│       └── proving/            reserved seat, created by /contract-init
├── project/                    goals, plan, deliverables, live state (tier 1)
│   ├── vision.md               the product bet
│   ├── roadmap.md              the phase plan
│   ├── project-status.md       the rolling snapshot (owned by project-plan)
│   └── open-decisions.md       the pending-clarification inbox
├── verification/               how we check it is right
│   ├── acceptance/             acceptance tests and plans (tier 1)
│   └── qa/                     qa-log (live) + qa-audit-archive (owned by qa-audit)
└── process/                    how we build and collaborate (tier 1)
    └── working-mode.md         the review and lock protocol
```

Sub-folders inside a bucket (`architecture/`, `decisions/`, `algorithms/`, `ux/`) are **examples, not a fixed set**. Create the five top-level buckets every time; create sub-folders only when the project needs them. A small project may start with the five buckets, a README, and the four `project/` stubs.

## The five buckets

- **`reference/`**: external or immutable **source**, plus gathered research. Material the project *cites* but did not design: rulebooks, standards, vendor specifications, research dossiers under `research/`. Tier 2, or immutable source.
- **`specs/`**: the **product and system design**. `tier-1/` holds the contract governed by `tier-1-contract`; `tier-2/` holds everything a tool writes or Claude maintains about how the thing is built.
- **`project/`**: the **goals, plan, deliverables, and live state**: vision, roadmap, the rolling status snapshot, the open-decisions inbox. Tier 1, with status running at high churn.
- **`verification/`**: **how we check it is right**: acceptance plans (`acceptance/`, tier 1) and the QA release logs (`qa/`, tier 2, live).
- **`process/`**: **how we build and collaborate**: the review and lock protocol, engineering practices. Tier 1, often project agnostic and shared across repos.

**Carve-outs** that keep their bucket regardless, being neither human authored nor Claude recreatable: external immutable source in `reference/`, and the live `verification/qa/` log owned by qa-audit. Neither is run through the prune.

> `CLAUDE.md` and the repo `README.md` stay at the **repo root**, platform convention. Per-component contract READMEs stay **next to the code** (`src/*/README.md`). Disposable build briefs live in a gitignored briefs folder, never under `docs/`.

## Mode A, scaffolding a new vault

1. **Resolve the docs root.** Use `docs/`; honour an existing `Docs/` casing if the repo already uses it. A docs path named in the repo's root `CLAUDE.md` wins.
2. **Create the five buckets** plus `reference/research/`, `specs/tier-1/`, `specs/tier-2/machine-readable/`, `specs/tier-2/walkthroughs/`, `verification/acceptance/`, and `verification/qa/`. Drop a `.gitkeep` in any folder left empty so git tracks it.
3. **Write `docs/README.md`** from the template below, substituting the project name and trimming lines the project does not use. This is the single most important artifact: it is the front door every thread reads first.
4. **Stub the docs.** Stub the four `project/` docs and `process/working-mode.md` as **tier 1**, each with a version line. Stub `specs/tier-2/architect-handoff.md` as tier 2. Leave `specs/tier-1/` to `/contract-init`, which writes the contract folder, its README, the registry, and the reserved proving seat.
5. **Wire the reading order** into the README, and add a one-line pointer in the repo's root `CLAUDE.md`: *"Read `docs/README.md` first, the docs index."*
6. **Register tier 1 docs for mobile review** one at a time with `/dvsync-track` as they are created. Never bulk-track; track a doc the first time it becomes tier 1.
7. **Hand off** each bucket to its owning skill. Do not write contract, status, or QA content here.
8. **Surface the README** with a runnable open command so the user can read it in one click.

## Front-door README template

Substitute `<Project>` and trim any line the project does not use.

````markdown
# <Project> — documentation index

The map of `docs/`. Five top-level folders, organised by **audience and purpose**:

- **`reference/`**: external or immutable source, plus gathered research. Material the project cites but did not design.
- **`specs/`**: the **product and system design**. `tier-1/` is the reviewed contract (one specification per component plus the Definition of Done); `tier-2/` is the tool-written and Claude-maintained layer beneath it.
- **`project/`**: the **goals, plan, deliverables, and live state**: the vision, the roadmap, the rolling `project-status.md`, and the `open-decisions.md` inbox.
- **`verification/`**: **how we check it is right**: the acceptance plans and the QA release logs.
- **`process/`**: **how we build and collaborate**: the working-mode protocol and the engineering practices.

## Tiers (who reviews what)

**Tier 1** is human owned: reviewed and locked through the versioned-review loop, carrying a `**Version:** N.0 (locked)` line, cited by code at its locked version. It spans `specs/tier-1/`, `project/`, `process/`, and `verification/acceptance/`.

**Tier 2** is maintained by Claude and carries no review mechanism at all: `specs/tier-2/` (build notes, the identifier registry, the generated crosswalk, the walkthroughs, the cold-pickup handoff), the `reference/research/` dossiers, and the live `verification/qa/` log.

> `CLAUDE.md` and the repo `README.md` stay at the **repo root**. Per-component contract READMEs stay **next to the code** (`src/*/README.md`, tier 2). Disposable build briefs live in the gitignored briefs folder.

## Session-start reading order

1. **`specs/tier-2/architect-handoff.md`**: the live cold-pickup state ("Resume here" names the next concrete action). **Read first.**
2. This index.
3. **`project/`**: vision, roadmap, `project-status.md`, `open-decisions.md`.
4. **`specs/tier-1/`** as the task needs: the contract front door, then the specification for the component in hand.
5. **`process/working-mode.md`**: the review protocol, before writing any code.
6. `reference/` for source and research.

## The tree

```
docs/
├── README.md                   you are here
├── reference/
│   └── research/               research dossiers (tier 2)
├── specs/
│   ├── tier-1/                 the reviewed contract
│   └── tier-2/                 registry, crosswalk, walkthroughs, handoff
├── project/                    vision, roadmap, project-status, open-decisions
├── verification/
│   ├── acceptance/
│   └── qa/                     qa-log + qa-audit-archive
└── process/
    └── working-mode.md
```

## Conventions

- **Tier 1 edits** go through the annotate-then-lock loop (`process/working-mode.md`, via `obsidian-versioned-review`); never edit a locked tier 1 doc without a re-review. **Tier 2** Claude maintains autonomously.
- Code cites a specification by its **filename and locked version** (`// Implements: spec-03-ingest.md v2.0`), never by folder path, so moving a file between folders does not break the citation.
- Tier 1 docs reviewed on mobile are tracked one at a time with `/dvsync-track`.
````

## Project stub templates

Each tier 1 stub opens with its H1 and a version line, so it is born under the lock regime. Keep them short; the owning skill fills the real content.

**`project/vision.md`**

```markdown
# <Project> — Vision

**Version:** 0.1 (draft)

> [One-line working description of what this is.]

## Pitch

[The product bet in two or three sentences.]

## Why now

[The opening, or the underserved need.]
```

**`project/roadmap.md`**

```markdown
# <Project> — Roadmap

**Version:** 0.1 (draft)

[The phase plan. Each phase: a deliverable, an expected duration, a checkpoint.]
```

**`project/project-status.md`**, then hand to **project-plan**

```markdown
# Project Status: <Project>

**v0.1**

> Updated: <YYYY-MM-DD>

## Table of contents

- [[#Status]]
- [[#Project plan]]
- [[#Deep dives]]

## Status

[One paragraph: where it stands and the immediate next step.]

## Project plan

[Milestones, Deliverables, Decision points, maintained by the project-plan skill.]
```

**`project/open-decisions.md`**

```markdown
# <Project> — Open Decisions (review inbox)

*One place for every call blocking a lock or an implementation step. Answer inline with a review comment. Each carries a recommendation marked **R:**; reply to take it, or override.*

## A · Open calls

[None yet.]
```

**`specs/tier-2/architect-handoff.md`** (tier 2)

```markdown
# <Project> — Architect handoff (cold-pickup state)

> Claude only. Keep it current; it is the first thing the next session reads.

## Resume here

[The single next concrete action.]

## State

[What is locked, what is in flight, what is blocked.]
```

> The `—` and `·` glyphs inside the template blocks above are house style for those specific doc titles and formats, reproduced so a new repo's docs match the originals. This skill's own instructional prose stays free of them.

## Mode B, migrating an existing vault

The high-value mode: take a real but disordered pile of markdown and reorganise it into the system, pruning dead weight on the way. Moves and deletions are destructive, so this runs as a strict three-beat regime: **propose, approve, execute**. Nothing moves, merges, or is deleted before the plan is signed off.

### Cardinal rules (binding)

- **Aggressive by default, never auto-delete.** Deletion and demotion happen only on the **locked** plan. The default is aggressive (an unchecked doc drops), but the act of dropping waits for the lock, and a file whose content **contradicts** its apparent role, looking droppable yet cited by live code, is surfaced and pre-checked, never silently cut.
- **Work on a branch, in git.** Cut a migration branch first. Every move is `git mv` (history preserved). Every deletion is `git rm` (recoverable), never a raw `rm`. The whole operation is one reviewable diff, fully reversible until merged.
- **The approval gate is a document, not a chat table.** The migration plan is a versioned markdown doc reviewed through **obsidian-versioned-review**. Per-file annotation in a rendered doc, including on a phone, beats replying to chat line by line. No destructive step precedes the lock.
- **Citations move safely, renames do not.** Code cites specifications by *filename and locked version*, so moving a file between buckets is safe. **Renaming** a cited file breaks the citation: prefer move without rename; if a rename is unavoidable, record it in the plan and fix the citing code in the same branch.

### The procedure

1. **Branch and snapshot.** Cut a `docs-migration` branch. Confirm the working tree is clean first; if not, surface it and stop.
2. **Inventory.** Walk the existing docs and any stray markdown pointed at. For each file capture path, size, last git-touch date, and a one-line "what it actually is" read from its **content**, not its name.
3. **Classify with an aggressive-prune bias.** Every file gets a proposed disposition. A file is a **keeper** (pre-checked, tier 1) only with a reason; otherwise it **drops**:
   - **Keepers**: `MOVE → <bucket>/<path>`, `RENAME → <bucket>/<newname>` (flags a citation check), or `MERGE → <target.md>` (fold in, then remove the source).
   - **Drops**: `DELETE` (stale, superseded, duplicate, empty stub, dead scratch) or `DEMOTE → specs/tier-2/` (no longer human facing but still operationally useful). Default to DELETE; demote only for real residual value.
   - `KEEP-IN-PLACE`: the root `README.md`, `CLAUDE.md`, and `src/*/README.md` are not part of the prune.
   - Safety: a file that looks droppable but whose content contradicts its apparent role is surfaced and **pre-checked with the contradiction noted**.
4. **Produce the keep-checklist** as a review doc at a non-dotted path (`docs/migration-plan.md`) carrying a `**v0.1**` line, in the format below, with recommended keepers pre-checked. Put it under **obsidian-versioned-review**, track it for mobile, surface it, and **stop for review**. The **lock** is the go signal.
5. **Execute, only after the lock.** Lay any missing buckets. Apply MOVE and RENAME via `git mv`; apply MERGE (append into target, then `git rm` the source); stamp version lines on new tier 1 docs; rebuild `docs/README.md` from the template to reflect the *actual* migrated tree.
6. **Prune and demote.** For every **unchecked** doc: `git rm` the DELETEs, `git mv` the DEMOTEs into `specs/tier-2/`. The checked docs are the tier 1 keepers; nothing else survives in the visible tree.
7. **Reconcile.** Track newly tier 1 docs for mobile, untrack removed ones. Grep the code for `Implements: <oldname>` on any RENAME and fix or flag the citation. Hand each bucket to its owning skill.
8. **Verify and surface.** Confirm the tree matches the README, the diff is clean, and nothing outside the approved set was touched. Surface the branch diff and the rebuilt README; merge per the repo's gate.

### The bar is "why keep it?"

The default is to drop. A file earns a tier 1 keep only when it is **load-bearing** (cited by code, a live contract, the current plan or status, the vision) or it is **external source** that cannot be recreated from the repo. Everything else goes.

Clear drop signals: **superseded** by a newer doc, **duplicate** of a canonical copy, **empty or stub-only**, **dead scratch**, or **recreatable** by reading the code.

The one brake is the **contradiction check** described above. Aggression is the default; the silent loss of a load-bearing doc is the only thing guarded against.

### Keep-checklist format

One **tappable checkbox per file**, each line carrying the summary and the proposed home, so the review is a scan and a few taps.

````markdown
# <Project> — docs migration plan

**v0.1**

> Branch: `docs-migration`. Nothing here is executed until this doc is locked.
> **Check = keep as tier 1.** Unchecked = I move it to `specs/tier-2/` or delete it
> (the fate is noted on the line; I default to delete). I have pre-checked what I
> judge worth keeping; flip any box, add a review comment to override a fate, then lock.

**Summary:** N files · keeping K as tier 1 · demoting D · deleting X

## Keep?  (checked = tier 1 keeper)

- [x] **`docs/arch.md`** → `specs/tier-1/spec-01-architecture.md` · core design contract, cited by code
- [x] **`docs/vision.md`** → `project/vision.md` · the product bet
- [ ] **`docs/notes-may.md`** · scratch notes, superseded by the roadmap · *fate: DELETE*
- [ ] **`docs/feature-x-walkthrough.md`** · per-feature operational prose · *fate: DEMOTE → specs/tier-2/walkthroughs/*
- [x] **`docs/weird.md`** · titled "deprecated" but cited by live code, surfaced for your call · *pre-checked to be safe*

## Post-migration tree

[the five-bucket tree as it will look once executed]
````

After the plan locks and the migration merges, the plan doc is transient: untrack it and remove it (it survives in branch history), or demote it to `specs/tier-2/` if a record is wanted.

## Handoffs

Once the structure stands or the migration lands, defer each bucket to its owner. Do not duplicate their work here.

- **`specs/tier-1/`** goes to **tier-1-contract**, which owns the component split, the specification anatomy, the Definition of Done, the identifier registry, and the gate. This skill only creates the folder; `/contract-init` populates it.
- **`project/project-status.md`** goes to **project-plan**, which owns the status schema, the create-versus-amend flows, and the mobile tracking for that doc.
- **`verification/qa/`** goes to **qa-audit**, which owns the release entries, the review loop, and the archive. Create the empty folder here.
- **Any tier 1 doc** goes through **obsidian-versioned-review** for the annotate-then-lock loop. This skill only *stubs* tier 1 docs with their version line; the lock regime governs every later edit. The Mode B migration plan is reviewed through the same loop, and its lock is the go signal.

## Per-repo configuration (optional)

To pin choices, add a block to the repo's root `CLAUDE.md`:

```markdown
## Docs-vault configuration

- **Docs root**: docs/            (or Docs/)
- **Open command**: `open -a "Obsidian"`
```

Optional. With no block the defaults apply: `docs/`, Obsidian.

## Adapting per project

- **Always** create the five buckets and the front-door README. They are the spine that makes every repo navigable the same way.
- **Vary** the sub-folders freely. A backend service grows `specs/tier-2/api/`; a research repo leans on `reference/research/`. Create a sub-folder only when a doc needs it.
- **Drop** a bucket only when the project genuinely has no use for it, which is rare. Prefer an empty bucket with a `.gitkeep`: the empty slot tells the next thread where that material will go.
