---
name: dev-process-kit
description: >-
  Orientation for the development process this plugin packages: how a project's
  docs tree is organised, how the product is specified against a Tier 1
  contract, how the plan is kept, and how the gate proves the set is whole. Read
  when the user asks "what is dev-process-kit", "how does the spec process
  work", "what is a Tier 1 document", "what is the difference between tier 1 and
  tier 2", "what do these UR identifiers mean", "why does the contract have a
  gate", "how should the docs folder be structured", or arrives from
  numaco-setup wanting to know what this plugin does and what it needs
  configured. Names the parts and their owners, says what the plugin writes into
  a project and what it never touches, and routes to docs-vault,
  tier-1-contract, or project-plan for the actual work.
status: stable
version: "1.1 (2026-08-06, docs-vault and project-plan folded in; one tier definition across the plugin)"
---

# dev-process-kit, the development process

This plugin packages the process a product is developed against: a docs tree organised the same way in every repo, one specification per coherent component, one Definition of Done written as complete operator journeys, a living plan of what is still ahead, every promise carrying a stable identifier that traces to the day that proves it, and a gate that fails closed when a promise loses its owner. It owns the structure, the contract architecture, the plan, and the machine gate. It owns none of the review mechanics, which belong to review-kit and are delegated rather than restated.

## What a project gets

`/contract-init` writes four things into the project you point it at, and nothing anywhere else:

- a contract folder, by default `docs/specs/tier-1/`, with a front door README that states the closure clause and lists the components;
- `contract.config.json` at the project root, holding that project's identifier prefixes, budgets, and inherited sources;
- an empty identifier registry at `docs/specs/tier-2/machine-readable/id-map.json`, outside the contract folder because a tool writes it and no one reviews it;
- a reserved, empty `docs/specs/tier-2/proving/` directory with a stub saying what will live there.

Nothing is configured on the machine. There is no account, no key, no hook, and no state outside the project. `init` refuses to overwrite a config or a registry that already exists.

## The parts, and who owns each

| Part | Owner | What it covers |
|---|---|---|
| The docs tree | this plugin, the `docs-vault` skill | the five buckets, the tier 1 and tier 2 split, the front-door README, the migration regime for an existing vault |
| Contract architecture | this plugin, the `tier-1-contract` skill | the component split, the specification anatomy, the identifier and journey scheme, clause splitting to one testable proposition, the Definition of Done |
| The plan | this plugin, the `project-plan` skill | the living Project Status doc: Milestones, Deliverables, and the single Decision point, future only and nearest first |
| The gate | this plugin, `scripts/contract.py` | declared against present: every identifier in the frozen registry is claimed by exactly one document, and only then are the documents checked against themselves |
| Review and lock | review-kit, the `obsidian-versioned-review` skill (load it by name) | the version line, green marking, the two comment channels, the purple and red form, the lock procedure |

This plugin restates none of the last part. Where the process needs a review round, it names the skill that runs it and stops.

## Tier 1 and tier 2, one definition across the plugin

**Tier is a property of the document, not of a folder.** Tier 1 is human owned: reviewed and locked through the review-kit regime, carrying a version line, cited by code at that version. Tier 2 is maintained by Claude and carries no review mechanism at all.

`specs/` is the one bucket holding both, so it names them as folders: `specs/tier-1/` is the contract this plugin governs, `specs/tier-2/` is the tool-written and Claude-maintained layer beneath it, including the identifier registry and the generated crosswalk. Everywhere else in the tree a doc's tier is read off its version line. `docs-vault` owns that model; `tier-1-contract` applies its strictest instance.

## Which skill to load

- **[docs-vault](../docs-vault/SKILL.md)** when the question is *where a document lives*: standing up a docs tree, migrating a messy one, or deciding which bucket something belongs in. Run it before the contract on a greenfield project, so `/contract-init` has a tree to write into.
- **[tier-1-contract](../tier-1-contract/SKILL.md)** when the question is *what the product must do*: splitting components, writing a specification or the Definition of Done, minting an identifier, running the gate.
- **[project-plan](../project-plan/SKILL.md)** when the question is *what happens next*: the living Project Status doc, its Milestones, Deliverables, and the single Decision point.

The plan points at what gets built; the contract specifies what it must do; the vault says where both live.

## Where the contract rules live

`tier-1-contract` carries the rules a writer must hold while typing a requirement bullet, and points at the reference directory (`${CLAUDE_PLUGIN_ROOT}/reference/`) for material that is consulted rather than remembered:

- [bootstrap.md](../../reference/bootstrap.md): how a project with no clauses finds its days, then its components.
- [specification-anatomy.md](../../reference/specification-anatomy.md): the measured detail of one specification, element by element.
- [definition-of-done-anatomy.md](../../reference/definition-of-done-anatomy.md): the acceptance document, part by part.
- [identifiers-and-registry.md](../../reference/identifiers-and-registry.md): the registry schema, minting, freezing, and acquiring a prior contract.
- [gate-checks.md](../../reference/gate-checks.md): every config field, every check, every message.
- [worked-example.md](../../reference/worked-example.md): one real contract, quoted and labelled as an example.
- [proving-layer-seat.md](../../reference/proving-layer-seat.md): the named empty seat and where it attaches.

## What this plugin is not

It does not write code, tests, fixtures, or harnesses. It does not grade whether the product does what the contract says, because coverage is a property of the test suite and a tool that grades its own contract proves nothing.

## Changing this plugin

Any edit to any file under `dev-process-kit/` bumps `version` in two places in the same commit: `dev-process-kit/.claude-plugin/plugin.json` and the `dev-process-kit` entry in `.claude-plugin/marketplace.json`, byte identical. Installed copies are keyed by version, so a changed file under an unchanged version serves the old text forever and every check still passes. The plugin README's `## Changing this plugin` section carries the full rule and what the publish gate does and does not catch.
