# How we develop

**v0.1**

*A product is specified once, in documents its owner can judge true or false unaided, and nothing is built until every promise names the day that will prove it.*

This document is the arc: what the process produces, in what order, and why each rule is there. It is authoritative on nothing. [skills/tier-1-contract/SKILL.md](skills/tier-1-contract/SKILL.md) is the authority on every rule, and where the two ever disagree the skill is right and this document is wrong.

## Why this matters

Today the specification is a pile that grew: a requirements document nobody has read end to end, a decision buried in a thread, a test suite that agreed with an older version of the truth. The pile has no edge, so no one can say what the product promises, and the honest answer to "are we done" is a shrug. When the pile is finally audited the damage is not a missing feature, it is a thousand acceptance rows that assert nothing, sitting beside real checks nobody mapped to a promise.

Running well, the owner reads twelve short documents in an afternoon, signs them, and from that moment every line of work traces to a numbered promise and every promise traces to a day that proves it. A build either satisfies the whole contract or names exactly which promise it broke. Nobody argues about scope, because scope is a file, and nobody discovers a forgotten requirement late, because a requirement cannot go missing without the gate refusing to build.
>>no the real goal here is to set up a dev process which is as much ai autonomous as possible. Ideally the user does specs + mockups + anything else needed that we still do not know, and then lets ai loose for a few days, and ai comes back woth a fully e2e tested peoduct that can go to production (or at least qa in the confidence that most of what is built will be working as per specs)
## What the process produces

| Outcome             | What it looks like                                                                                                  | What makes it true                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| A closed contract   | one specification per component, plus one Definition of Done, and a front door that names every document that binds | the front door says nothing else is Tier 1, so a promise outside the set is not a promise |
| A checkable promise | `UR-QP-06 (DJ-04)`, a numbered requirement naming the journey that proves it                                        | the owner can watch that journey and say true or false without an engineer translating    |
| A stable name       | an identifier that never moves, never repeats, never renumbers after a lock                                         | the registry holds every live and every burned number, with the reason                    |
| A machine verdict   | one command, three exit codes, no network                                                                           | the gate starts from the registry and proves every declared promise is still on the page  |
| A signed baseline   | a locked document carrying its version, its date, and its digest                                                    | the lock is recorded by the tool, so nobody has to remember what was agreed               |

## The arc

**One. The day census.** Before anything is written, list the days the product must survive. A day is a stretch one person lives through as one continuous experience: the day a new machine joins, the day the money reconciles, the day disaster strikes. You have the census when the owner approves the list of titles and nothing else, because a title is cheap to change and a document is not.

**Two. The component manifest.** Only now does the product split. Each candidate component gets a name, one essence line, a scope, and the days it expects to serve, and each is falsified against five tests: does the essence compress to one sentence, does it serve between two and six days, does it carry between ten and twenty five promises, does every noun it owns live here or go to one named sibling, and does deleting it disturb two to four siblings rather than one or twenty. You have the manifest when the owner approves it. No identifier exists yet, deliberately: renumbering is free before the first lock and impossible after it.

**Three. The documents.** Each component gets one specification of at most three rendered pages, opening on an italic essence line and a short "Why this matters" grounded in the real pain today. The Definition of Done gets the day census turned into journeys, each carrying four or five checkboxes an operator could witness. Every requirement is reduced to one testable proposition and given the journey that proves it, or declared a standing constraint where no day can stage it.

**Four. The gate.** The crosswalk runs on every round that touches a requirement. It reads the frozen registry first and demands that every declared identifier is claimed by exactly one document, then checks the documents against themselves: no identifier claimed twice, none tracing to a journey that does not exist, no journey nothing reaches. A non zero exit means the round does not ship.

**Five. The lock.** The owner locks document by document. At the lock the identifiers freeze, the digest is recorded, and the text stops arguing with itself. From here a change is a new version of a locked contract, not an edit to a draft.

**Six. The build.** Work is ordered against the locked contract, and the contract is the only authority on what "done" means. A promise with no executable proof and a proof with no promise both block a release, in both directions.

## The rules that carry the weight

**Two kinds of document, and nothing else.** Specifications and one Definition of Done. Everything else, architecture, schema, harnesses, fixtures, build notes, is a tier down and never enters this review. The test for a Tier 1 sentence is a question the owner answers alone: could the person who signs this watch it be true or false?

**Every document reads as if it were the only version ever written.** No development history, no superseded notes, no reverted decisions, no "as previously agreed". A document carrying its own history invites the reader to reopen settled clauses, and a lock is worthless if the text still argues with itself. Provenance lives in git, the crosswalk, and the registry, which were built to hold it.

**One testable proposition per clause.** A paragraph promising ten things produces ten atoms either way. The only choice is whether they are visible where the owner signs them, or discovered later where nobody looks. Split until a further split would produce a fragment no operator would recognise as a promise.

**Identifiers are immutable after a freeze.** Mint at the end of a component's range, never insert, never reuse a burned number, never renumber. This rests on one decoupling: document order is narrative, identifier order is birth order. Without it, readability and immutability fight and readability always wins.

**Declared against present.** A check that only compares what is present to what is present will always pass. A deleted newline once glued one requirement onto the previous line; the parser stopped seeing it, the requirement vanished from the crosswalk, and the gate still reported complete. This is why the gate starts from the registry rather than from the page, and why "declared but missing" is treated as a class of defect in its own right.

## How one round goes

The owner reads the document and answers in review-kit's two comment channels, `>>` and `>?`. What each channel means, the version line, the green marking, the purple and red form, and the lock all belong to the `obsidian-versioned-review` skill in review-kit, which is the only authority on them and is not restated here.

Four things are added by this process on top of that round. A call to action touching requirements regenerates the crosswalk in the same round. One that would push a document past its budget is answered with a split proposal rather than a silent squeeze. A discussion comment changes nothing, including the machine readable layer. A lock freezes identifiers and records the digest at the same moment.

## What we deliberately leave out

The Definition of Done carries no fixtures, no negative controls, no evidence paths, and no lane rules. This is a location decision rather than a deletion: each of those exists one tier down, where engineering owns it. A contract carrying a fixture column becomes a schema for a ledger, and a schema invites rows. The last attempt that did it produced 1,467 acceptance rows, 98 percent of them holding placeholder fixtures, beside roughly 2,621 real checks the ledger could not see.

Specifications name no field, table, route, type, cloud resource, test, or deployment command. The ban is by class rather than by vendor, because naming one stack's nouns dates the rule and lets the next stack through.

## What is reserved

The proving layer is named, empty, and not yet proven: interface contracts and mockups, a seeded fixture corpus, golden documents, per journey staging pages, and an executable acceptance harness. Five anchors hold its place so that folding it in later changes no structure. It ships empty because the process above has been run end to end and this has not, and shipping an unproven layer beside a proven one would teach the reader that neither is load bearing.

## Where the detail lives

- [README.md](README.md): what the plugin ships, the three gate verbs, and the layout.
- [skills/tier-1-contract/SKILL.md](skills/tier-1-contract/SKILL.md): the working instructions while writing.
- [reference/bootstrap.md](reference/bootstrap.md): the day census and the component split in full.
- [reference/worked-example.md](reference/worked-example.md): one real contract, labelled as an example.
