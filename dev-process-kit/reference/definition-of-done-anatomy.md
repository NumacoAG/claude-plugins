# The anatomy of the Definition of Done

The detail behind
[definition-of-done-template.md](../templates/definition-of-done-template.md).
Every example is quoted from the [worked example](worked-example.md).

## The skeleton, seven parts

| # | Part | Form |
|---|---|---|
| 1 | Title | `# Definition of Done`. No product name, no version, no scope words. |
| 2 | Version line | the version, a middle dot, then `Tier 1 acceptance contract`. No `component N of M`: this document is not one of a set. |
| 3 | Framing paragraph | four sentences, about 63 words, no heading above it |
| 4 | `## Release rule` | one imperative lead line, then five checkboxes |
| 5 | Container heading | `## The J days`, counting the journeys in the heading itself |
| 6 | One `### DJ-nn.` per journey | four or five checkboxes, never prose before the first one |
| 7 | Lock footer | at lock |

There is no essence line, no "Why this matters", and no "Scope". The framing
paragraph does all three jobs, because this is the only document that is about
the other documents.

## The framing paragraph, four moves

> The eleven component specifications say what the product must do. This contract says what must be **shown working end to end** before release: fourteen days in the life that prove the product. When all fourteen pass, the organisation runs on this system. Fixtures, negative controls, evidence paths, and lane rules are deliberately absent: engineering owns them.

1. **Defer to the siblings.** What the product does lives elsewhere.
2. **Define this document's job by the days metaphor**, bolding the single
   operative verb phrase.
3. **State the consequence in one clause, with no hedge.**
4. **Fence off the engineering material and name its owner.** Only this move is
   negative, and it is the last thing the reader meets before the rules begin.

## The Release rule block

Five bullets, five jobs, under the lead line *The release is done only when all
of these hold.*

1. **Coverage across both tiers**, with evidence reproducible on demand. A green
   record that cannot be regenerated is not evidence.
2. **Artefact identity plus determinism.** The tested build is the shipped
   build, nothing is rebuilt afterwards, and two runs from clean agree. This
   kills the flake that passes on the third attempt.
3. **Verdict integrity.** One sentence enumerating every cheat: a failure, a
   skip, a flake, a stale result, a placeholder standing in for a check that
   never ran, a waiver, a coverage gap, and a broken harness.
4. **Scope closure.** The single exclusion stated in full, then "Nothing else is
   excluded", which converts every future exclusion request into a contract
   change.
5. **A named human.** The product owner completes operator acceptance and
   approves the first watched live run.

**Why the block sits above the journeys.** The journeys are the content of done;
the Release rule is the arithmetic over them. A reader who met the journeys
first would reasonably conclude that J ticks equals release, and every cheat in
bullet three is a way to produce J ticks. Placing the block first leaves no
route into the journeys that bypasses the anti waiver clause, the exclusion
closure, and the human sign off.

**A warning about bullet three.** It is the longest line in the document and the
clause most likely to shrink under editing pressure, because each named cheat
reads as removable on its own. Write it as a fixed checklist rather than prose to
be redrafted each round, count the cheats before a round and after it, and treat
a drop as a defect.

## The journey heading

```
### DJ-nn. The day <subject> <present tense verb phrase>
```

A two digit zero padded number, a full stop, a space, then the title, which
always opens `The day` and continues in lower case for two to seven words.
Simple present throughout, the gnomic present of a typical day: never future,
never conditional, never a gerund.

**The admission test.** A candidate earns a slot only if a real day exists where
one person experiences it as one continuous stretch. *The day permissions are
configured* is grammatical and forbidden, because its subject is a
configuration rather than something a person lives through.

**Four permitted subject kinds, and no fifth**: a thing that arrives or moves; a
person outside the building, never an internal role; an absence, such as nothing
or nobody; and the product itself, only in the reflexive journeys.

**Never in a title**: a component name, a specification code, a role name, a
technology, a feature, a screen, a number, a modal verb, a proper noun.

## The five coverage groups

| Group | Dimension | Cardinality |
|---|---|---|
| Arrival and access | surface and role, what must be true before any business is possible | two: where you are, and who you are |
| The value chain | lifecycle, walked in the order money moves | one per irreducible commercial face |
| Tempo | time and attendance | two: the human clock, and the machine clock |
| The adversary and the disaster | failure, split by cause | two: deliberate, and undeliberate |
| Wholeness | feel | one |

**Four of the five are fixed for any product.** Only the value chain scales, and
its size is an output of the product's shape rather than an input. It also
carries the citation mass. Wholeness draws the fewest requirements, which is not
weakness: its checkboxes are irreducibly qualitative, and it exists to catch a
build that passes every other journey and still is not a product. A group with
no real day is dropped, never padded.

## Checkbox grammar

Four per journey is the target and five is the ceiling, five appearing only
where the journey carries a fifth irreducible axis. There is no journey with
three and none with six.

**Voice.** Third person, present indicative, active. The subject is an actor or
an artefact, never a component. **Zero modal verbs** appear inside any journey
checkbox, and the words `test`, `fixture`, `mock`, `assert`, `verify`, and
`endpoint` appear nowhere.

**What they assert.** The capability and its bound in one sentence: what the
product does, joined to what it cannot be made to do. The negative half is a
refusal an operator would witness, never an expected exception. Quantifiers
carry the load: *exactly once*, *never*, *only*, *at most*, *nothing*.

> - [ ] Approval creates the intended record exactly once. Rejection or discard creates nothing.

> - [ ] An operator finds or creates a product, compares real supplier offerings, sees freshness and confidence, and never receives an invented product, price, stock, or lead time.

> - [ ] The product pulls read only bank data, running the import again never duplicates a payment or a match, and manual import stays available when the connection is unavailable.

> - [ ] With every client closed, scheduled work runs at the intended local time, catches up missed work exactly once, and exposes a failed or delayed run.

> - [ ] While the recovery computer is available, a complete independent recovery set stays no more than 24 hours behind and holds everything needed to rebuild outside the hosting region.

> - [ ] The seeded complete journey runs without a developer interpreting the screen, repairing data, or intervening behind the product.

Six reasons they stay operator observable:

1. **The subject always has a body or a name a person uses.** Never a module, a
   route, a table, a queue.
2. **The verbs are what a person does or watches happen**: installs, compares,
   blocks, alerts, restores. Never asserts, validates, returns, mocks.
3. **Every number is a quantity a person experiences.** No retry counts, no
   timeouts, no queue depths, no confidence thresholds.
4. **The negative half is a refusal**, naming what the operator sees when the
   guard fires.
5. **No path, identifier, environment, fixture, or command appears anywhere.**
6. **Each line is scaled to a working hour, not a function call.** One checkbox
   collapses many assertions on purpose, and the document is silent about how
   many. That silence is what lets each atom later be proven at the cheapest
   layer that can honestly prove it.

## The deliberate absence

Fixtures, negative controls, evidence paths, and lane rules are named as absent
in the framing paragraph and appear nowhere below it.

**The causal chain, with the number.** The instant an acceptance contract
carries a fixture column, an evidence path column, and a lane column, it stops
being a statement of what done means and becomes a schema for a ledger. A schema
invites rows. Rows get generated before the behaviour exists, so they fill with
placeholders, and a placeholder is indistinguishable from a pass at a glance.
One project that did this produced **1,467 acceptance rows, 98 percent carrying
placeholder fixtures**, beside roughly **2,621 real executable checks the ledger
could not see**. Both halves are the same mistake: the contract described the
evidence machinery instead of the product.

Three further failures the absence prevents:

- **Premature layer assignment.** One assertion per atom, never one test per
  atom, each proven at the cheapest layer that can honestly prove it. A lane
  rule pre-commits every expectation before anyone knows that layer. One browser
  journey per atom would mean roughly 1,500 journeys, taking hours per run and
  flaking constantly. Nobody would run it, the gate would be waived, and the
  waiver would become the policy.
- **A contract only engineers can review.** The product owner locks these
  documents and cannot lock a fixture manifest, and a document nobody can lock
  is not a contract.
- **Harness churn invalidating the contract.** Rename a fixture and a contract
  naming fixtures needs a re-lock for a change that alters no promise.

**The absence is a location decision, not a deletion.** Every excluded item
exists one tier down. The standing rule protecting the arrangement: never weaken
an oracle, remove a negative control, lower a test count, add an exclusion, or
reinterpret a failure to make a gate green.
