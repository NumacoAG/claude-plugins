# The proving layer, a reserved seat

The contract says what the product must do and what must be shown working. It
does not say how a journey is staged, what a screen looks like before it exists,
or which fixture corpus a run reads. That work is real, it has a name and a
place, and it is **not implemented in this version**.

## What will live there

User interface contracts and mockups; a seeded fixture corpus; golden documents;
one staging page per journey naming the starting state, the operator actions,
and the observation; and an executable acceptance harness that runs them.

## The five anchors, reserved now

Folding the layer in later must change no structure, so the seat is cut today.

| Anchor | Reserved form today | What arrives later |
|---|---|---|
| A skill directory | `skills/proving-layer/` is a reserved name and is not created | the skill that writes interface contracts, the fixture corpus, and the harness brief |
| A configuration block | `"proving": {}` in the project's configuration, schema declared, must be empty; a non empty block exits 2 | the layer's paths, its budgets, and its per journey staging rules |
| An artifact key | `"proving": {"status": "RESERVED"}` in the crosswalk | staged journey counts, golden document digests, harness scenario budgets |
| A project directory | `docs/specs/tier-2/proving/` created empty by `init`, with a stub saying what it will hold | the staging pages, the fixture corpus, the golden documents, the interface contracts |
| A skill section | the reserved section in the working skill | a pointer to the proving layer skill, one paragraph, no restatement |

A non empty `proving` block exits 2 rather than being quietly ignored, because a
configuration key that accepts data and does nothing with it is worse than an
absent key: it reads as implemented.

## The one design constraint the layer must honour

**The unit is the file, never the row.**

Fourteen journeys become fourteen staging pages. They cannot become fourteen
hundred placeholder rows, because the schema has no row. This is not a
preference. The failure the Definition of Done exists to prevent is exactly the
one a proving layer is most likely to re-enact: an evidence ledger built before
the behaviour exists, filling with placeholders, where a placeholder is
indistinguishable from a pass at a glance. One project produced 1,467 such rows,
98 percent of them carrying placeholder fixtures, beside roughly 2,621 real
executable checks the ledger could not see.

A page carries a starting state, a list of operator actions, and an observation.
The gate counts files and fields and nothing else. It never derives a verdict,
because a tool that grades its own contract is the same failure with a nicer
schema.

## Why the seat is empty

The process this plugin ships has been run end to end on a real product. The
proving layer has not. Shipping an unproven layer beside a proven one teaches a
reader that neither is load bearing, and that lesson is expensive to unlearn.

The plugin therefore names the layer, reserves its five anchors, states its one
constraint, and stops. When the layer has been run end to end it lands at the
reserved skill directory, the configuration block starts accepting data, the
artifact key starts carrying counts, and the reserved section in the working
skill becomes one paragraph pointing at the new skill. Nothing else moves.

## What it is not

It is not a coverage register, a gap register, or a status ledger of any kind.
Coverage is a property of the test suite: derive it there or do not claim it. A
contract that acquires a status column it then has to chase is the failure this
design exists to prevent, wearing the costume of the fix.
