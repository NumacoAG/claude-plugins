---
name: tier-1-contract
description: >-
  Write, split, identify, and gate a project's Tier 1 product contract: one
  specification per coherent component plus one Definition of Done, every
  requirement carrying a stable identifier that traces to an acceptance journey,
  a frozen identifier registry, and a crosswalk gate that fails closed. Use
  whenever the user says "write the spec", "draft the specification", "split
  this into components", "write the definition of done", "add a requirement",
  "what identifier does this get", "renumber these", "run the contract gate",
  "the crosswalk is failing", "set up the contract folder", "/contract-init" or
  "/contract-check". Use it also when working in any folder holding files named
  spec-NN-something.md, a definition-of-done.md, or machine-readable/id-map.json,
  and on any document whose bullets carry identifiers shaped UR-XX-nn with a
  journey tag such as (DJ-04). Covers the component split, the specification
  anatomy, the acceptance journeys, clause splitting to one testable
  proposition, identifier immutability, and every gate check. Does not cover the
  review round, the green marking, the comment channels, or the lock procedure:
  those belong to the obsidian-versioned-review skill in review-kit.
status: stable
version: "1.0 (2026-08-02 initial)"
---

# The Tier 1 contract

A Tier 1 contract is the set of documents a product is specified against, plus the gate that proves the set is whole. This skill governs what those documents may say, how a project splits into them, how every promise earns a stable identifier tracing to the day that proves it, and what the gate reports before a lock.

One sentence carries the regime: **if a promise is not in these documents, the product does not make it.**

## When to trigger

- Drafting or editing any specification, including any file named `spec-NN-something.md`.
- Splitting a project into components, or arguing about where a boundary sits.
- Writing or amending the Definition of Done, or adding a journey.
- Adding, changing, splitting, or retiring a requirement, or asking which identifier it gets.
- Any gate result other than clean: a build that will not complete, an unclaimed identifier, an orphaned journey.

The negative case matters as much. A round that changes no requirement and no registry entry belongs to review-kit alone.

## What Tier 1 is, and what it is not

Exactly two kinds of document qualify, and nothing else does.

1. **Specifications.** One per coherent component. Each states only observable product behaviour or a quality constraint the product owner owns.
2. **One Definition of Done.** Complete operator journeys, not technical tests.

The set is closed: the front door README names every document that binds and says nothing else is Tier 1.

The content test is a question the product owner answers unaided: **could the person who signs this watch it be true or false?** If the answer needs an engineer to translate it, the sentence is Tier 2 in a Tier 1 costume.

Forbidden by class, not by vendor: persistence (fields, tables, schema), transport (routes, endpoints, payloads), language types, infrastructure, test implementation, deployment. Naming one stack's nouns dates the rule and lets the next stack through; naming the class does not.

One escape hatch is licensed, and its power is its scarcity. Where a rule genuinely needs an algorithm, state the outcome, name the guarantee, and hand the algorithm down a tier by name. Once or twice in a contract it is a pressure valve; used often it is a loophole and the rule stops holding.

Everything else is Tier 2: architecture, schema, walkthroughs, infrastructure, harnesses, fixtures, build notes, audits. Tier 2 is maintained directly and never enters this review.

## The golden rule

**Every document reads as if it were the only version ever written.** No development history, no superseded notes, no reverted decisions, no "as previously agreed", no changelog prose in a body or a lock footer. Provenance lives in git, the crosswalk, and the registry, built to hold it.

A document carrying its own history invites the reader to relitigate settled clauses, and a lock is worthless if the text still argues with itself.

```markdown
Before, and forbidden:
- **UR-QP-06** (DJ-04) After the v2 review we reverted the earlier decision, so
  the product now blocks a below cost quote (previously it only warned). The
  operator must type the confession string agreed in the July session.

After, and correct:
- **UR-QP-06** (DJ-04) A below cost quote is refused. The only way past the
  refusal is a typed confession naming the loss, recorded against the operator
  and the deal.
```

One exception is bounded: the "why this matters" section may open on a time anchor from a closed set, `Today`, `Until now`, `Before this product`. That anchor is the only sentence permitted to age, and it is swept mechanically once the pain it names is fixed.

## Bootstrapping the component split

Invert the obvious order: **days first, components second.** A new project has no clauses to cluster, but it has days, and a day is cheap to elicit and hard to fake.

Two identities hold for any business product: `journeys = 7 fixed + one per value chain face`, and `components = 3 fixed + one per commercial face`.

Seven fixed days: a machine joins; people and permissions change; nothing falls through (the human clock); nobody touches the keyboard (the machine clock); the product is attacked; disaster strikes; it feels like one product. Three fixed components: platform and access; unattended work and its visible half; production constraints. Drop a fixed slot with no real day behind it.

Three gates, in order, each cheaper than the next: approve the day list, titles only; approve the component manifest, names and essence lines and scope and expected journeys, no identifiers; then lock each document. Falsify every candidate against five tests before gate two.

| Test | Passes when |
|---|---|
| Essence | one sentence, one pivot mark, 17 to 31 words, no second promise |
| Journey fan | 2 to 6 journeys; 7 or more is a split signal |
| Mass | 10 to 25 requirements; below 10, merge |
| Closure | every owned noun lives here or goes to one named sibling; one declared shared at most |
| Blast radius | deleting it forces edits in 2 to 4 siblings; fewer is a section, more is cross cutting |

Resolve overlaps in this order, first rule that fires wins.

1. **Chain rule.** A rule holding unchanged across a chain belongs to the later document; the earlier cites it.
2. **Visible half rule.** The visible surface belongs to the component whose day shows it; the machinery to production constraints.
3. **Choice rule.** The behaviour belongs here; how much of it ships belongs to production constraints.
4. **Declared shared**, once per component at most.
5. **A cite bullet**, when none of the above fits.

Renumbering is free before the first lock and impossible after, which is why both approvals precede the first minted identifier. The harvest procedure, its input whitelist and bans, and the split health tripwires are in [bootstrap.md](../../reference/bootstrap.md).

## Writing one specification

```markdown
# Territory as a bare noun phrase, three or four parts

**v1.0** 🔒 · component N of M · Tier 1 specification

*One sentence, present indicative, one pivot mark, ending on the invariant that breaks first.*

## Why this matters

Two moves in one paragraph. Move one: three named containers holding today's truth in
the wrong place, then one sentence naming the consequence. Move two, opened with
"Running well,": the same work as actors and verbs, ending on this component's hardest
guarantee stated as an impossibility.

## Scope

What this owns, as a verbless noun phrase inventory. What it hands off, one clause each,
naming the sibling by its human title and linking it by bare relative filename. A because
clause wherever the split is arguable.

**Exclusion.** Optional. What the product will not do, plus who does it instead, or what
class of request a future ask would be. Never a bare "out of scope".

## A moment in the working day, or a gerund, or a stated invariant

- **UR-XX-01**\* (DJ-nn) Full sentences. Observable behaviour only.
- **UR-XX-02** (DJ-nn, DJ-mm) Full sentences.

Optional interstitial paragraph: define a term, or state the consequence of the bullets
around it. Never a new obligation, never an identifier.

## Next section

- **UR-XX-03** (constraint) Only where no operator journey can prove it.

---

Traceability: UR-XX-01 to UR-XX-nn → DJ-aa, DJ-bb.

🔒 **Locked: v1.0 (YYYY-MM-DD).**
```

Four rules carry the weight.

**The essence line.** One pivot mark splits claim from proof: the left half is the abstract promise, the right half its enumerated, checkable version. It ends on the invariant that breaks first if the component is built badly, usually stated negatively. It must compress to a table cell in the README; a line that will not compress is doing the work of two components.

**Why this matters.** Move one names three concrete containers and one consequence, never a general complaint and never a person to blame. Move two ends on the component's hardest guarantee stated as an impossibility, and that clause must reappear as a numbered requirement. If it does not, the guarantee has no owner or the sentence overclaims.

**Scope.** The `because` clause settles boundary disputes without a meeting: it gives the principle, not the decision, so a third writer can re-derive the split alone. Link siblings by bare relative filename, so moving a document breaks no citation.

**The size budget.** About 1,000 body words per specification, roughly three rendered pages at 400 words per page. The page figure is reported and never asserted, because measuring rendered pages needs a renderer and a renderer is the one dependency an offline gate must not acquire. The binding constraint is the requirement count, 10 to 25, so the only way to relieve pressure is to split the component: packing clauses makes the median and maximum bullet checks worse rather than better, which is the incentive the budget exists to produce.

**The requirement bullet, character by character.** A hyphen and a space at column 1, the bold identifier, the optional inheritance marker, one space, the parenthesised tag, one space, then full sentences. The line anchor is the reason rather than a preference: the gate matches at the start of a line, so a bullet not at the start of its own line does not exist to the machine.

Conventions across a set. Headings are sentences, never numbered, because numbering lives in the identifiers. Bold has four jobs, identifiers, frame strings, an `**Exclusion.**` lead in, and a term at its point of definition or a signed number; emphasis is not one. A coined term is glossed once in the set, then used bare. Requirements cite each other by identifier and never restate the cited rule, so every rule has one editable home. An interstitial paragraph defines a term or states a consequence, never an obligation. Numbers carry unit, statistic, and adjustability in one breath. Measured bands and heading moods are in [specification-anatomy.md](../../reference/specification-anatomy.md).

## Writing the Definition of Done

The skeleton: title, version line, a four sentence framing paragraph, `## Release rule`, a heading counting the journeys, then one `### DJ-nn. The day …` per journey with four to five checkboxes and no prose before the first box.

The Release rule is a fixed checklist with five jobs: coverage across both tiers with reproducible evidence; artefact identity and determinism, the exact release that goes live, twice from clean, agreeing; verdict integrity, every cheat enumerated in one sentence so none reads as separately negotiable (failure, skip, flake, stale result, placeholder, waiver, coverage gap, broken harness); scope closure, the single exclusion stated in full and the set then closed; and a named human who completes acceptance. It sits above the journeys: a reader meeting them first would conclude that N ticks equals release, and every cheat listed produces N ticks. The integrity bullet shrinks under editing pressure, which is why it stays a checklist.

A journey title passes one admission test: a real day exists where one person experiences it as one continuous stretch. No component name, spec code, role name, technology, feature, screen, number, or modal verb appears in a title. Checkbox grammar: third person present indicative, capability joined to its bound in one sentence, the bound a refusal an operator would witness, zero modal verbs.

Then the deliberate absence, with its number. A previous attempt built the evidence ledger before the contract was testable: 1,467 acceptance rows, 98 percent carrying placeholder fixtures, beside roughly 2,621 real checks the ledger could not see. A contract carrying a fixture column becomes a schema for a ledger, and a schema invites rows. So fixtures, negative controls, evidence paths, and lane rules are absent here: a location decision, not a deletion, since each exists one tier down. Detail in [definition-of-done-anatomy.md](../../reference/definition-of-done-anatomy.md).

## Identifiers and the registry

An identifier names its kind and its home: a kind prefix, a component segment, a fixed width number. It is self locating when read alone on a phone. The tag that follows names the journey that proves it.

`(constraint)` replaces the journey list and is never combined with one. It is licensed only when all four properties hold: no operator performs it, it is true continuously rather than at an instant, its verifier is not a screen, and it constrains the build rather than the product's behaviour. The test is stageability, not ownership: a rule the owner signed personally still takes a journey when a day can stage it. Keep it near two percent. There is no empty parenthesis and no third option.

The registry at `machine-readable/id-map.json` lists every live identifier, and it is what makes the gate possible. Six blocks: `components` (each code, its file, its state), `sources` (declared ancestors), `requirements`, `journeys`, `withdrawn` (every burned number and why), and `locks` (per document version, date, and digest, written by the tool and never by hand).

Greenfield: `sources` is empty, every entry is self keyed, and any inheritance marker in the prose is a hard failure, because the character has no referent. Inherited: each source declares its own marker, origin sentence, and expected count. Prose shows one marker, the registry holds all ancestry.

Three immutability rules, absolute after a freeze. Mint at the end of a component's range and never insert. Never reuse a withdrawn number. Never renumber; before a lock, a renumber needs the product owner's explicit say so.

All of it rests on one decoupling: **document order is narrative, identifier order is birth order.** Without it, readability and immutability fight and readability wins. Acquiring a prior contract is in [identifiers-and-registry.md](../../reference/identifiers-and-registry.md).

## Clause splitting

One testable proposition per clause, before lock. The arithmetic is the argument: a paragraph packing ten expectations produces ten atoms either way. The only choice is whether they are visible where the product owner locks them, or discovered later where nobody looks.

The seam test: can you imagine a build where this half holds and that half does not? If yes, they are two propositions.

The procedure. Enumerate the propositions. Sort them by owning component; one that leaves moves to the owning specification as a new identifier there. Keep the parent identifier on the largest survivor. Mint at the end of the range for every other piece and register each. Give each its own journey tag and place it under the heading whose narrative it belongs to; a piece fitting no heading means the heading set or the split is wrong. Re-run the gate.

The stopping rule: split until a further split would produce a fragment no operator would recognise as a promise.

The tool may count seams and propose a split in chat. It may never write one, because a generator minting identifiers without human intent is exactly the hazard the registry exists to prevent.

## The action glyph

Optional, declared per project in `action_glyph`, empty by default; a project with no autonomous behaviour declares none. When declared, one character (a gear is usual) marks one cross cutting property and is defined exactly once, in an interstitial paragraph, in that project's terms.

Three parts, all needed. It attaches at the verb or its object, at the exact word where the untriggered step occurs, never as a badge on the line. It marks only a step the product takes with nobody triggering it then. And only a nameable, individually governable type, never a standing property or an envelope guarantee, even when the mechanism behind it runs unattended. The third part is what a careful reader gets wrong: a component of pure invariants and operator acts carries none.

Never in a title, version line, heading, or footer, and never in the lock glyph's territory. No gate can judge a missing glyph, so it lists every occurrence into the artifact and requires the count restated at lock, so the governable set never changes by accident.

## The gate, declared against present

**A gate that only compares what is present to what is present will always pass.**

Two failures make the point.

A deleted newline glued one requirement bullet onto the end of the previous line. The bullet anchor stopped matching, so the requirement was parsed by nothing, never entered the owners map, and vanished out of the crosswalk. Every check starting from the documents passed, and the generator reported complete.

A skill file was edited in a commit that bumped a different plugin's version. Installed copies compared the same number against itself, concluded they were current, and served the old text for weeks. The manifest check stayed green: it asserted only that two manifests agreed, and both were wrong together.

Neither is a regex bug, and neither is cured by a better regex. Both are one shape: the check started from what was on the page, and what was missing had no voice. So the gate starts from the frozen registry, asserts that every declared identifier is claimed by exactly one document, and only then checks the documents against themselves. Treat declared but missing as a class of defect in its own right: a registry entry with no bullet, a component with no file, a journey no requirement reaches.

Three verbs: `build` runs every check and writes the crosswalk; `check` writes nothing and also fails on a stale committed artifact; `status` prints the one line the round message carries. Three exit codes: 0 clean; 1 the contract violated, with the artifact written **before** the failing exit so a blocked run leaves no stale success on disk; 2 the engine could not run, a configuration or input problem and never a contract problem.

One rider on the review loop: a round that adds, removes, merges, or splits a requirement re-runs `build` in that round. A non zero exit means the round does not ship, and the failure is reported in chat before the document is surfaced. Never relax a check to make a build green. Every check is in [gate-checks.md](../../reference/gate-checks.md).

## Review and lock belong to review-kit

Every Tier 1 document is under the green mark versioned review regime. Load the `obsidian-versioned-review` skill from the review-kit plugin by name, and follow it verbatim for the version line, the green spans, the two comment channels (`>>` call to action, `>?` discussion), the purple and red form, the diff as instruction rule, and the lock. This skill restates none of it. Load it by name rather than by path: each plugin installs to its own versioned directory, so no relative path reaches a sibling plugin.

Four riders, because the review skill cannot know they exist. A call to action touching requirements regenerates the crosswalk in the same round. One that would breach the budget is answered with a split proposal, never a silent squeeze. A discussion comment changes nothing, including the machine readable layer. A lock has downstream effects, so `contract.py lock` runs at the same moment to freeze identifiers, record the digest, and restate the glyph count.

Only Tier 1 enters the regime. review-kit owns the wording of the lock footer; this gate asserts only that a locked document carries one and that it names a version and a date. The `lock` verb writes the form in `lock_footer`, which exists so the tool has something to type, not so this plugin can overrule review-kit.

## The proving layer, reserved

Named, empty, and not yet proven. What will live there: interface contracts and mockups, a seeded fixture corpus, golden documents, per journey staging pages, an executable acceptance harness. Five anchors are reserved so folding it in later changes no structure: a skill directory, a config block, an artifact key, a project directory, and this section.

It is empty because the process above has been run end to end and this has not: shipping an unproven layer beside a proven one teaches a reader that neither is load bearing. The gate reports `"proving": {"status": "RESERVED"}`, and a non empty `proving` block exits 2 rather than being ignored. See [proving-layer-seat.md](../../reference/proving-layer-seat.md).

## Handoffs

- **Folder placement, bucket taxonomy, vault migration**: a separate skill owns them. Reference it by behaviour and never vendor a copy here.
- **Every review round and every lock**: review-kit's `obsidian-versioned-review`.
- **The release QA log**: review-kit's `qa-audit`.
- **Mirroring a locked document to a phone**: review-kit's `/dvsync-track`, one document at a time, never in bulk.

Use the comment channels of the current review regime, never an older one inherited from a borrowed template.

## Per round checklist

1. Every new identifier minted at the end of its component range and registered.
2. Every new requirement carries a journey tag, or the constraint tag with all four properties holding.
3. No identifier renumbered, reused, or inserted into a sequence.
4. Traceability footers recomputed, range endpoints and journey set both.
5. `contract.py build` exits 0, and the artifact on disk matches.
6. Every budget finding fixed or answered with a split proposal.
7. The glyph count restated if it moved.
8. No document reads as a version of itself: no history, no supersession, no reopen reason.
9. The review-kit round steps done, and the document surfaced per that skill.
10. The `contract.py status` line in the message that ships the round.
