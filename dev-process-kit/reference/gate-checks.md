# The gate, check by check

**A gate that only compares what is present to what is present will always
pass.** Every check below exists because of that sentence, and the first one in
the structural table is the reason this plugin exists. Seed configuration:
[contract.config.json](../templates/contract.config.json).

## Configuration

The configuration lives in the project being specified, at its repository root,
named `contract.config.json`. One resolution rule, no discovery order: the path
given on the command line, otherwise `contract.config.json` in the working
directory, otherwise exit 2 naming the path that was tried. Every path inside is
relative to the file's own directory.

It lives in the project because it records facts about that project's contract:
its prefixes, its inherited sources, its pinned baselines, its budgets. Those
facts must travel with the repository, be reviewable in a pull request, and not
change when the plugin updates.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `config_version` | integer, must be 1 | 1 | Any other value exits 2. |
| `project` | string | the config directory's basename | Copied into the artifact. |
| `strictness` | `report`, `warn`, `fail` | `report` | `report` writes the artifact and always exits 0, for bootstrap. `warn` fails on structural findings only. `fail` fails on everything. **Structural findings are never downgraded.** |
| `contract_dir` | string | `docs/specs/tier-1` | |
| `spec_glob` | string | `spec-*.md` | Inside `contract_dir`. Directories and non files are skipped, never crashed on. `README.md` is always excluded. |
| `acceptance_doc` | string or null | `definition-of-done.md` | `null` skips every journey check and records the skip. |
| `registry` | string | `machine-readable/id-map.json` | Created empty by `init`, never null. |
| `output` | string | `machine-readable/contract-crosswalk.json` | |
| `requirement.prefix` | string | `UR` | |
| `requirement.component` | regex, or null for a flat scheme | `[A-Z]{2}` | Any regex; two letters is only the default. |
| `requirement.digits` | integer | 2 | Exact width. Any other width is a problem, never a silent skip. |
| `journey` | object or null | as seeded | `null` when there is no acceptance document. |
| `constraint_tag` | string | `constraint` | The exact trimmed tag admitting a requirement with no journey. No empty parenthesis, no third option. |
| `action_glyph` | string | empty | Empty skips every glyph check. |
| `retired` | array of regexes | empty | Pre adoption families that must never reappear. |
| `budget` | object | as seeded | See below. |
| `lock_footer` | string with `{version}` and `{date}` | the colon form | The form the `lock` verb writes. review-kit owns the wording of a lock footer; the gate asserts only that one exists and names a version and a date. |
| `locked_baselines` | array of `{name, path, version, sha256}` | empty | Independent of inheritance. A pinned Tier 2 document is not an ancestor. |
| `clause_harvests` | array of `{name, path, pattern}` | empty | Witness only. Uniqueness is asserted; nothing else is. |
| `allow` | array of `{rule, id or file, reason}` | empty | One exception, one rule, one target. A missing `reason` exits 2. |
| `proving` | object | empty | **Reserved.** A non empty block exits 2. See [proving-layer-seat.md](proving-layer-seat.md). |

**Refused deliberately.** Per check booleans, because a fail closed tool whose
checks are individually switchable is a fail open tool with more surface, and a
stuck build then goes green with a one line diff nobody reviews. Regex overrides
for the bullet, identifier, and heading patterns, because an override that
compiles but names its groups wrongly fails silently and produces an empty owner
set with no problems at all. A configurable word count, because a number two
projects cannot compare is not a ceiling. An expression language for extra
counts. Renameable registry fields, which would make every error message
unquotable. A multi step discovery order.

## Structural checks, never downgraded

| id | Fails when | Fix |
|---|---|---|
| `registry-unclaimed` | an identifier in the registry is stated by no document | State it, or retire it. **This runs first.** |
| `unregistered-id` | a document states an identifier the registry does not hold | Register it with `mint`, never by hand. |
| `duplicate-claim` | two documents claim the same identifier | One owner; cite it from the other. |
| `duplicate-registry-target` | two registry entries map to the same identifier | Withdraw one, mint a fresh number. |
| `missing-tag` | a requirement bullet states no parenthesised tag | Add the journey, or the constraint tag. |
| `journey-or-constraint` | a requirement names no journey and is not the constraint tag | Name the day that proves it. |
| `unknown-journey` | a requirement names a journey with no heading | Fix the tag, or add the journey. |
| `orphan-journey` | a journey heading is reached by no requirement | Requirements are missing, or the day is not a day. |
| `duplicate-journey-heading` | two headings declare the same journey | Renumber; journey numbers burn like requirement numbers. |
| `malformed-number` | a number is not exactly the declared digit width | Pad it. A silent skip in a fail closed tool is a bug in the tool. |
| `marker-missing` | an inherited entry's identifier carries no source marker | Add the marker that source declares. |
| `marker-spurious` | a locally born identifier carries a source marker | Remove it; the marker is provenance, not emphasis. |
| `marker-forbidden` | any marker appears while the registry declares no sources | Remove it; the character has no referent. |
| `retired-identifier` | a bullet states an identifier from a retired family | Replace it with its current identifier. |
| `withdrawn-reappears` | a bullet states a withdrawn number | Mint a fresh one. Burned numbers stay burned. |
| `frozen-changed` | a frozen entry's target moved or vanished | Revert. A frozen identifier is immutable. |
| `lock-drift` | a locked document's bytes moved without its version line bumping | Re-review and re-lock, or revert. |
| `baseline-drift` | a pinned baseline no longer matches its digest | Re-pin deliberately, or restore the baseline. |
| `component-file-binding` | an identifier lives in a file its component code is not registered to | Move it back, or record a `home`. |
| `traceability-footer` | a footer's range endpoints or journey set differ from the computed values | Recompute the footer. |
| `frame` | the H1 is not on line 1, the version line is not on line 3 or does not match the declared shape, no italic essence line sits on line 5, `## Why this matters` or `## Scope` is absent, there is not exactly one horizontal rule, or a lock glyph appears without a lock footer or the reverse | Restore the frame from the template. |
| `lock-hygiene` | a locked document still carries a green, purple, or red span, or its lock footer names no version and date | Complete the lock procedure. |
| `rendering` | the markup breaks one of the rendering rules in review-kit's `obsidian-versioned-review`, which owns and explains every one of them | Fix the markup per that skill. |

## Budget checks

Printed at `warn`, failing at `fail`. The binding constraint is deliberately the
**count**, not a total word figure, so the only way to relieve pressure is to
split the component. Packing clauses makes the median and maximum checks worse
rather than better, which is the incentive reversal the budget exists to
produce.

| id | Fails when |
|---|---|
| `requirements-per-spec` | the count is outside the declared band |
| `words-per-requirement-max` | a bullet is above the maximum |
| `words-per-requirement-median` | the document's median is above the declared median |
| `acceptance-doc-words` | above `acceptance_base_words + words_per_journey × journeys` |
| `journey-fan` | a document's distinct journey count reaches the suspect threshold |

## Lint checks

Printed at `warn` and at `fail`, and never blocking at any strictness: `seam-count` (four
or more conjunction seams, or ninety or more words, in one bullet);
`automation-without-glyph` (automation vocabulary in a bullet carrying no glyph,
only when a glyph is declared); `dash-punctuation`; and `constraint-density`
above five percent.

## Exit codes

| Code | Meaning | Artifact |
|---|---|---|
| 0 | Clean. Status `COMPLETE`. | written by `build`, unchanged by `check` |
| 1 | The contract is violated. Status `BLOCKED`. | **written before the failing exit**, so the failure is recorded on disk |
| 2 | The engine could not run: a missing or invalid configuration, an unreadable input, a regex that will not compile, a non empty proving block. | never written |

Splitting 2 from 1 is deliberate. A tool returning the same code for a violated
contract and for its own crash makes a red build say nothing. Any gate treating
non zero as failure is unaffected.

`build` writes atomically, so an interrupted run never leaves a truncated
artifact. The artifact carries no timestamp and no absolute path, so a clean run
is byte identical to the committed file, which is how `check` detects a **stale
committed artifact**, a defect no other check can see.

## Word count normalisation

Fixed in code and not configurable. It strips frontmatter and fenced code
blocks; keeps the inner text of HTML spans while dropping the tags, so a
document's measured size does not change when the review spans come off at lock;
reduces links to their visible text; strips table pipes and separator rows, list
bullets, heading hashes, blockquote markers, emphasis markers, and escaped
asterisks; drops the version line and the lock footer; and counts whitespace
separated tokens containing at least one alphanumeric character. Identifiers
count as one word each, because they are read as a token.

`pages = ceil(words / words_per_page)` is **reported and never asserted**.
Measuring rendered pages needs a renderer, and a renderer is the one dependency
an offline gate must not acquire.

## The artifact

| Key | Contents |
|---|---|
| `schema_version`, `generated_by`, `engine_version`, `project`, `id_scheme`, `strictness` | what produced this artifact and under which settings |
| `status` | `COMPLETE`, `INCOMPLETE`, or `BLOCKED`. `BLOCKED` means a finding blocks at this strictness; `INCOMPLETE` means a structural finding stands and does not block, which is what `report` mode produces |
| `problems` | per finding: class, identifier or file, check id, message |
| `suppressed` | every finding an `allow` entry silenced, with its check, subject, reason, and message |
| `counts` | requirements, journeys, components (declared, drafted, locked), standing constraints, inherited per source, born, and `skipped_checks` |
| `rows` | per identifier: document, journeys, source, disposition |
| `documents` | per document: words, requirement count, median and maximum bullet words, journey fan, derived pages, glyph count, locked |
| `sha256` | the digest of each contract document as read |
| `actions` | `glyph`, `occurrences`, `in_requirements`, `by_file`, `by_id` |
| `clause_harvests`, `locked_baselines` | each harvest and its identifiers; each pinned baseline as declared |
| `proving` | `{"status": "RESERVED"}` |

**`counts.skipped_checks` is the honest half of the design.** A check that cannot run,
because the project declares no acceptance document or no inherited source, is
recorded as skipped rather than silently passed, so a reader can never mistake
the absence of a failure for the presence of proof.

The **allow list** works the same way: one entry silences one rule for one
identifier or one file, never a whole rule, so a new violation inside an already
excepted file still fails. Every entry carries a reason, and a missing reason
exits 2.

## What the tool refuses to check

- **Rendered page count.** It needs a renderer. Words are the gate.
- **Glyph correctness.** Semantic in all three of its parts. The gate lists every
  occurrence and requires the count to be restated at lock, so the governable set
  cannot change by accident, but it never returns a verdict.
- **One testable proposition.** Same reason. The seam lint counts seams and a
  human reads the top decile.
- **Prose quality**: the essence line, the two move shape, heading voice,
  negative density. A checker for these produces false failures and teaches
  authors to game it. Only positional and countable frame rules are enforced.
- **Auto splitting a packed clause.** A generator that mints identifiers without
  human intent is exactly the hazard the registry exists to prevent. The tool may
  count seams and propose a split in chat; it may never write one.
- **Whether the product does what the contract says.** That is the test suite's
  job. A tool grading its own contract is the placeholder ledger failure with a
  nicer schema.
