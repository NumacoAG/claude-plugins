# Identifiers and the registry

The registry is the authoritative list of every live identifier. It is the only
check that starts from what the documents **should** contain rather than from
what they do contain, which is why every other invariant can pass while a
requirement has silently vanished. Seed file:
[id-map.json](../templates/id-map.json).

## The schema, every block filled

```json
{
  "schema_version": 1,
  "adopted": "2026-01-15",
  "note": "Authoritative identifier registry. Every live identifier appears here.",

  "components": {
    "PO": { "file": "spec-01-platform.md", "state": "locked" },
    "XX": { "file": "spec-12-new-component.md", "state": "planned" }
  },

  "sources": [
    {
      "name": "urs-v6",
      "marker": "\\\\\\*",
      "disposition": "RETAINED",
      "origin": "the original requirement specification",
      "expected_requirements": 82,
      "expected_journeys": 14,
      "baseline": null
    }
  ],

  "requirements": {
    "UR-PO-01": { "new": "UR-PO-01", "source": null, "frozen_at": "v1.0 (2026-02-03)", "home": null },
    "URS7.17":  { "new": "UR-PO-02", "source": "urs-v6", "frozen_at": null, "home": null }
  },

  "journeys": { "J1": "DJ-01" },

  "withdrawn": {
    "UR-OC-10": { "reason": "merged into UR-OC-04 before lock", "withdrawn_at": "v2.0 (2026-03-11)" }
  },

  "locks": {
    "spec-01-platform.md": { "version": "v1.0", "date": "2026-02-03", "sha256": "the 64 character digest" }
  }
}
```

**`components`** reserves a code and gives the artifact a declared denominator,
so completeness is measured against a plan rather than against whatever happens
to be on disk. A `planned` component's code cannot be taken by another
component, and a bullet using it before the file exists is an error naming the
file that should exist. A journey reached only by planned components is reported
separately, so nobody mistakes a plan for coverage.

**`sources`** is an array because a boolean cannot express two ancestors. Each
source carries its **own unique marker**, its own origin sentence, and its own
expected counts. When the array is empty the project is greenfield and any
inheritance marker anywhere is a hard failure, because the character has no
referent.

**`requirements`** is keyed by the ancestor identifier where one exists and by
the identifier itself where none does. **Self keyed means born here.** One code
path serves both cases.

**`withdrawn`** is what makes a burned number machine real instead of a
convention. Without it, nothing stops a later session reusing a retired number,
and the range form traceability footer would absorb the reuse silently.

**`locks`** is written by the tool and never by hand. It is the single highest
value invariant in the engine: a locked document whose bytes moved without its
version line bumping is a contract that changed after it was signed.

## Freezing, and what it is not

Freezing is **per identifier, at the lock of the document that states it**, not
per project at adoption.

- **Before that document's first lock** the identifier is mutable. This is the
  only window in which renumbering is legal, and it needs the product owner's
  explicit say so.
- **At `lock`** every identifier in the document gets its `frozen_at` stamp, the
  file digest goes to `locks`, and from that instant the identifier can be
  withdrawn but never renumbered, never reassigned, and never reused.

`freeze` exists for the case where the review stalls. It writes `frozen_at` and
stabilises the identifier space **without claiming approval**, and it touches no
document: the version line keeps whatever review-kit's regime gives it, and a frozen
document is still an unlocked one carrying no lock glyph. Numbering stops moving
on day one of a long review; approval arrives whenever it arrives. Conflating
the two would destabilise the identifier space for no reason every time a
reviewer is slow.

## Mint, retire, renumber

**Mint at the end of the component's range**, never inserted into the sequence,
never reusing a withdrawn number, never renumbering a neighbour to make room.
Use `mint` rather than picking numbers by eye, so a session cannot take a number
the registry has already burned.

**Retire** moves the entry to `withdrawn` with a reason and a version stamp, and
burns the number. The gate then fails if that number reappears in any bullet.

**Never renumber after a freeze.** Code, tests, and cross citations reference
identifiers; renumbering silently invalidates every citation, and reuse makes a
retired number resolve to the wrong promise.

**The decoupling that makes all of this possible: document order is narrative,
identifier order is birth order.** A well written document routinely opens on
its highest number and scatters late births among early ones. Without that
decoupling, immutability and readability are in direct conflict and readability
wins.

## Component operations

A contract that cannot split a component after a lock will simply never split
one, which is how a document stays over budget forever. Three operations are
recorded rather than improvised.

**Split.** A hand edit of the registry, in one recorded commit. Add the new component
to `components`, then set `home` on each moved entry to the new file. Moved
identifiers **keep their identifiers** and change file: the component to file binding
check consults `home` when present and the component code otherwise, so the move needs
no renumbering. The cost is honest: the moved identifier lives in its new file forever,
exactly the way an inheritance marker carries lineage. There is no `split-component`
verb, deliberately. A tool that rewrites the registry in bulk is a tool that can move
sixty identifiers on a typo, and this is the one file where a careful diff is worth
more than a command.

**Merge.** Two codes point at one file. That file's traceability footer carries
two ranges, and the footer check accepts them:
`Traceability: UR-WS-01 to UR-WS-23, UR-XX-01 to UR-XX-06 → DJ-05, DJ-06.`

**Retire a component.** Its code stays reserved, its identifiers are withdrawn
one by one with reasons, and the code is never reissued.

## The cite bullet

For a requirement that legitimately serves two components. It is a line form the
gate understands and does not treat as a claim:

```
- ↪ **UR-OC-04** (owned by [Order to cash](spec-05-order-to-cash.md)) Carriage terms reach the packing floor unchanged.
```

The link names a file of the example project; in a real contract it resolves to the sibling document.

Gate rules: the cited identifier must exist and be claimed elsewhere; a cite
carries no journey tag and mints no identifier; at most three cites per
document, so the pressure stays toward real ownership. The one sentence of
context may not state an obligation, exactly like an interstitial paragraph. The
artifact emits the cite, so the true fan out is readable.

The alternative is worse in both directions: duplicating the sentence under two
identifiers produces two promises that diverge at the next edit, and picking one
home silently omits a rule the second document's readers need.

## Acquiring a prior contract

`acquire <source-name> --doc <path> --marker <regex>` runs six steps, and
renumbers nothing.

1. **Register the source** with a unique marker, and pin the acquired document
   as a locked baseline with its digest. An acquired contract is immutable
   input.
2. **Census.** Harvest the acquired clause identifiers and report the count.
   **No mapping yet.** The count is the size of the work, and it is what the
   product owner approves.
3. **Disposition, one per acquired clause.**
   - **ADOPTED**: an existing requirement already says it. Map the acquired
     identifier to the existing one. No mint, no renumber.
   - **PARTIAL**: an existing requirement says part of it. Map to the existing
     identifier **and** mint one new identifier at the end of that component's
     range for the remainder. Both carry the source.
   - **NEW**: mint at the end of the range.
4. Nothing is renumbered, because the registry is keyed acquired identifier to
   existing identifier, which is the direction it already runs.
5. **Prose markers land at the next review round** of each affected document.
6. The inheritance checks now run for that source, with the expected count set
   to the census figure from step 2.

**The seam count in the census is what turns a clause count into a split
estimate.** Report, per acquired clause, the number of conjunction seams and
independent verbs. A clause above four seams is flagged **before** the owner
approves, because a body of clauses that packs ten expectations into one
paragraph produces the same atoms either way. One project without this step
watched 82 parents explode into 782 atoms after approval.

## The patch lock

Step 5 would otherwise force a version bump on every affected document, for a
change that alters no promise. Ceremony on that scale gets skipped, and a
skipped step becomes a lie in the prose.

So a marker only acquisition is locked as a patch, by hand: run `lock <file>` with the
next minor version and today's date, and state in the commit message that the only
change is the inheritance markers. The rule that makes it safe is one a reviewer
enforces on the diff, not the tool: **the document must be byte identical once every
inheritance marker is stripped**. If the diff shows one changed word beyond a marker,
it is a content change and takes a full review round and a major lock. The owner
approves the acquisition once rather than once per document.

## Two ancestors

An entry may carry more than one source. **Prose shows the first registered
source's marker only**, because two markers on one line would break the bullet
grammar, and the line anchor is the contract. The registry holds all ancestry
and the artifact emits it, so the second lineage is visible to a reader and to
any downstream tool. The trade is stated plainly: prose shows one ancestor, the
registry holds all.
