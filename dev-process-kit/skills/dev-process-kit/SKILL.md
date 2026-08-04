---
name: dev-process-kit
description: >-
  Orientation for the Tier 1 contract process, the product specification and
  acceptance regime this plugin packages. Read when the user asks "what is
  dev-process-kit", "how does the spec process work", "what is a Tier 1
  document", "what do these UR identifiers mean", "why does the contract have a
  gate", or arrives from numaco-setup wanting to know what this plugin does and
  what it needs configured. Names the three parts (the contract architecture
  this plugin owns, the fail closed crosswalk gate, and the review and lock loop
  that review-kit owns), says what the plugin writes into a project and what it
  never touches, and routes to the tier-1-contract skill for the actual work.
status: stable
version: "1.0 (2026-08-02 initial)"
---

# dev-process-kit, the Tier 1 contract process

This plugin packages the product specification and acceptance process a project is specified against: one specification per coherent component, one Definition of Done written as complete operator journeys, every promise carrying a stable identifier that traces to the day that proves it, and a gate that fails closed when a promise loses its owner. It owns the contract architecture and the machine gate. It owns none of the review mechanics, which belong to review-kit and are delegated rather than restated.

## What a project gets

`/contract-init` writes four things into the project you point it at, and nothing anywhere else:

- a contract folder, by default `docs/specs/tier-1/`, with a front door README that states the closure clause and lists the components;
- `contract.config.json` at the project root, holding that project's identifier prefixes, budgets, and inherited sources;
- an empty identifier registry at `machine-readable/id-map.json` inside the contract folder;
- a reserved, empty `docs/specs/tier-2/proving/` directory with a stub saying what will live there.

Nothing is configured on the machine. There is no account, no key, no hook, and no state outside the project. `init` refuses to overwrite a config or a registry that already exists.

## The three parts, and who owns each

| Part | Owner | What it covers |
|---|---|---|
| Contract architecture | this plugin, the `tier-1-contract` skill | the component split, the specification anatomy, the identifier and journey scheme, clause splitting to one testable proposition, the Definition of Done |
| The gate | this plugin, `scripts/contract.py` | declared against present: every identifier in the frozen registry is claimed by exactly one document, and only then are the documents checked against themselves |
| Review and lock | review-kit, the `obsidian-versioned-review` skill (load it by name) | the version line, green marking, the two comment channels, the purple and red form, the lock procedure |

This plugin restates none of the third part. Where the process needs a review round, it names the skill that runs it and stops.

## Where the rules live

The working skill is `tier-1-contract`. Load it for any actual contract work. It carries the rules a writer must hold while typing a requirement bullet, and points at the reference directory (`${CLAUDE_PLUGIN_ROOT}/reference/`) for material that is consulted rather than remembered:

- [bootstrap.md](../../reference/bootstrap.md): how a project with no clauses finds its days, then its components.
- [specification-anatomy.md](../../reference/specification-anatomy.md): the measured detail of one specification, element by element.
- [definition-of-done-anatomy.md](../../reference/definition-of-done-anatomy.md): the acceptance document, part by part.
- [identifiers-and-registry.md](../../reference/identifiers-and-registry.md): the registry schema, minting, freezing, and acquiring a prior contract.
- [gate-checks.md](../../reference/gate-checks.md): every config field, every check, every message.
- [worked-example.md](../../reference/worked-example.md): one real contract, quoted and labelled as an example.
- [proving-layer-seat.md](../../reference/proving-layer-seat.md): the named empty seat and where it attaches.

## What this plugin is not

It does not decide where documents live in a vault or how a docs tree is organised; a separate skill owns folder placement and bucket taxonomy. It does not write code, tests, fixtures, or harnesses. It does not grade whether the product does what the contract says, because coverage is a property of the test suite and a tool that grades its own contract proves nothing.

## Changing this plugin

Any edit to any file under `dev-process-kit/` bumps `version` in two places in the same commit: `dev-process-kit/.claude-plugin/plugin.json` and the `dev-process-kit` entry in `.claude-plugin/marketplace.json`, byte identical. Installed copies are keyed by version, so a changed file under an unchanged version serves the old text forever and every check still passes. The plugin README's `## Changing this plugin` section carries the full rule and what the publish gate does and does not catch.
