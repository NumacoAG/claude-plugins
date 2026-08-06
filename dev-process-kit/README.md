# dev-process-kit

A Claude Code plugin carrying the product specification and acceptance process,
so any project can be specified the same way: one specification per coherent
component plus one Definition of Done, every requirement carrying a stable
identifier that traces to an acceptance journey, a frozen identifier registry,
and a gate that fails closed. It owns the contract architecture and the machine
gate. It owns none of the review mechanics: review-kit owns those, this plugin
depends on it, and it restates nothing that review-kit already says.

## What it gives you

- **docs-vault.** The docs tree every project shares: five buckets organised by
  audience and purpose, the tier 1 and tier 2 split, the front-door README, and
  the approval-gated regime for migrating an existing messy vault into the
  system without losing a load-bearing document.
- **tier-1-contract** (the working skill). Everything a writer needs while
  typing: what a Tier 1 document is and is not, how a project splits into
  components, the specification anatomy, the acceptance journeys, clause
  splitting to one testable proposition, the identifier scheme and its
  immutability rules, and every gate check.
- **project-plan.** The living Project Status doc: Milestones, Deliverables, and
  at most one Decision point, held future only and nearest first, so the past
  lives in git history rather than in the plan.
- A fourth skill, **dev-process-kit**, is the orientation front door for a
  colleague asking what this plugin is.
- **The contract gate** (`scripts/contract.py`). Python standard library only,
  three verbs, three exit codes, no network, no toolchain. It reads a project's
  own `contract.config.json` and writes a crosswalk that accounts for every
  identifier.
- **Templates.** A conforming specification, the Definition of Done skeleton,
  the contract folder front door, a seed config, and an empty registry. The
  initialiser writes them into the project so a contract folder is standing up
  in one command rather than being copied by hand.
- **Reference.** Seven documents the working skill points at rather than
  inlining: the bootstrap procedure, the specification anatomy in full, the
  Definition of Done anatomy, identifiers and the registry, every gate check and
  every config field, one worked example, and the reserved seat for the proving
  layer.

## Read this first if you are new to the process

[HOW-WE-DEVELOP.md](HOW-WE-DEVELOP.md) is the narrative: what the process produces, the six stages in
order, and why each rule is there. One sitting, no prior knowledge assumed. It is authoritative on
nothing, and [skills/tier-1-contract/SKILL.md](skills/tier-1-contract/SKILL.md) is the authority on
every rule.

## The one idea

**A gate that only compares what is present to what is present will always
pass.**

Here is the failure it names. A lost newline glued one requirement onto the end
of the previous line. The bullet anchor stopped matching it, so the requirement
was parsed by nothing, never entered the owners map, and vanished out of the
crosswalk while every other check still passed and the generator still reported
complete.

The cure is structural rather than a better regex. The gate starts from the
frozen registry and asserts that every declared identifier is claimed by exactly
one document, and only then checks the documents against themselves. What is
declared but missing is a first class class of defect here. The self test proves
it by deliberately hiding a requirement and requiring the gate to fail naming
that identifier.

## It acts only inside a project you point it at

Nothing is configured on your machine. No account, no key, no hook, no session
start behaviour. The plugin is inert until you run `/contract-init` inside a
project's repository, and from then on it writes only into that project: the
contract folder, the registry, and the `contract.config.json` at the project
root. `init` refuses to overwrite a config or a registry that already exists,
and says which path it found.

## Getting started

Two slash commands, both run inside the project being specified:

```
/contract-init
/contract-check
```

`/contract-init` asks where the contract folder should live, which identifier
prefixes to use, whether any prior contract is being inherited, and whether the
project declares an action glyph, then writes:

```
<project>/
├── contract.config.json                the contract's settings, reviewable in a pull request
└── docs/
    └── specs/
        ├── tier-1/                  reviewed and locked, the contract itself
        │   └── README.md               the contract front door
        └── tier-2/                  tool written, never reviewed
            ├── machine-readable/
            │   └── id-map.json         the identifier registry, empty
            └── proving/                reserved, with a stub saying what it will hold
```

Then the bootstrap starts: the day census comes before the component split, and
no identifier is minted until both are approved, because renumbering is free
before the first lock and impossible after it.

## The gate

Three verbs:

| Verb | What it does | What it writes |
|---|---|---|
| `build` | runs every check and generates the crosswalk | the artifact, including before a failing exit, so a blocked run never leaves a stale successful crosswalk on disk |
| `check` | runs every check, and additionally fails when the committed artifact is stale | nothing |
| `status` | prints one summary line for a review round message | nothing, always exits 0 |

Three exit codes, and only three:

| Code | Meaning |
|---|---|
| 0 | the contract is whole |
| 1 | the contract is violated; every problem prints on its own line, classified structural, budget, or lint |
| 2 | the gate could not run (config missing or invalid, an input unreadable, a regex that will not compile), which is a configuration problem and never a contract problem |

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/contract.py" build
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/contract.py" check
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/contract.py" status
```

Wire `check` into the project's own CI job or pre commit hook. It writes
nothing, needs no network, and catches both a violated contract and a crosswalk
that was committed stale.

## Layout

```
dev-process-kit/
├── .claude-plugin/
│   └── plugin.json                       plugin manifest
├── skills/
│   ├── dev-process-kit/SKILL.md          orientation: the parts, and who owns each
│   ├── docs-vault/SKILL.md               the docs tree: buckets, tiers, migration
│   ├── project-plan/SKILL.md             the living Project Status doc
│   └── tier-1-contract/SKILL.md          the working skill: write, split, identify, gate
├── commands/
│   ├── contract-init.md                  /contract-init, stand up a contract folder
│   └── contract-check.md                 /contract-check, run the gate read only
├── scripts/
│   └── contract.py                       the gate (Python standard library only)
├── tests/
│   └── test_contract_gate.py             proves the gate fails closed
├── templates/
│   ├── spec-template.md                  a conforming specification, ready to fill
│   ├── definition-of-done-template.md    the acceptance document skeleton
│   ├── contract-readme-template.md       the contract folder front door
│   ├── contract.config.json              seed config, written into the project
│   └── id-map.json                       seed registry, empty
├── reference/
│   ├── bootstrap.md                      days first, components second
│   ├── specification-anatomy.md          the measured detail of one specification
│   ├── definition-of-done-anatomy.md     the acceptance document in full
│   ├── identifiers-and-registry.md       minting, freezing, retiring, acquiring
│   ├── gate-checks.md                    every config field, check, and message
│   ├── worked-example.md                 one real contract, labelled as an example
│   └── proving-layer-seat.md             the reserved seat and its five anchors
├── HOW-WE-DEVELOP.md                     the process as a narrative, for a human reader
└── README.md                             this file
```

There is no `hooks/` directory, deliberately. The plugin acts only when asked and
never touches a project at session start.

## What this plugin does not own

- **The review round and the lock.** review-kit's `obsidian-versioned-review`
  owns the version line, the green marking, the two comment channels, the
  purple and red form, and the lock procedure. Load it and follow it verbatim.
- **The release QA log.** review-kit's `qa-audit`.
- **Mirroring a locked document to a phone.** review-kit's `/dvsync-track`, one
  document at a time.
- **Writing code, tests, fixtures, or harnesses.** The contract says what the
  product must do; proving it is the test suite's job.

## The proving layer, reserved

The next phase is named, empty, and explicitly not yet proven. What will live
there: user interface contracts and mockups, a seeded fixture corpus, golden
documents, per journey staging pages, and an executable acceptance harness.

It attaches at five anchors, all reserved now so folding it in later changes no
structure: a reserved skill directory name, an empty `proving` block in
`contract.config.json` (a non empty one exits 2 rather than being ignored), a
`"proving": {"status": "RESERVED"}` key in the crosswalk, an empty
`docs/specs/tier-2/proving/` directory in the project, and one section of the
working skill that a pointer will replace.

It ships empty because the process above has been run end to end and this has
not, and a plugin that ships an unproven layer beside a proven one teaches its
reader that neither is load bearing. See
[reference/proving-layer-seat.md](reference/proving-layer-seat.md).

## Changing this plugin

Any edit to any file under `dev-process-kit/` bumps `version` in two places in
the same commit: `dev-process-kit/.claude-plugin/plugin.json` and the
`dev-process-kit` entry in `.claude-plugin/marketplace.json`. The two values must
be byte identical.

Here is what happens when they do not move. Installed copies are keyed by
version. A commit that changes a file and leaves the version alone produces
installed copies comparing the same number against itself, concluding they are
current, and serving the old file forever. It has happened in this repository: an
edit to an onboarding skill shipped under an unbumped version and served stale
text for weeks, while the version agreement check stayed green throughout,
because both manifests were consistently wrong together.

The `manifests` job now carries a step named "A changed plugin must bump its own
version" that compares the changed file list against each plugin's version at the
base commit. It skips a plugin that did not exist at the base commit, so a new
plugin's first commit at `0.1.0` is clean and every later change is not.

Two things it does not catch, so they are still yours: bumping the wrong plugin's
version alongside a correct one still passes, and a version that moves backwards
passes. Read the diff.

Before committing, run the privacy gate over the plugin directory and confirm the
pre commit hook is installed, because the site specific terms run only there.

## Runtime dependency

Python 3.9 or newer on `PATH` as `python3`, standard library only, no third party
packages. Nothing else. The plugin depends on `review-kit`, which the marketplace
installs alongside it.
