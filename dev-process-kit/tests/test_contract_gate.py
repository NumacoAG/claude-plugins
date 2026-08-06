#!/usr/bin/env python3
"""The contract gate stays fail closed.

Every test builds a whole contract in a temporary directory from the strings below,
then breaks exactly one thing and asserts that exactly that break is named. The
fixtures and the expectations therefore sit in one reviewable place, and nothing
outside the temporary directory is ever read or written.

Run it as:

    python3 -m unittest dev-process-kit/tests/test_contract_gate.py
"""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "contract.py"
_spec = importlib.util.spec_from_file_location("contract", SCRIPT)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


SPEC_ONE = """# Arrival, access, and the shared record

**v0.1** · component 1 of 2 · Tier 1 specification

*One product, one record: every change is kept, and nothing typed is ever lost.*

## Why this matters

Today the truth lives in three mailboxes, a spreadsheet, and one person's memory.
Nobody can say who changed what. Running well, a person opens the product, sees
exactly what the role allows, and the record keeps every change forever.

## Scope

Access, roles, and the audit record. Building a price belongs to
[Pricing](spec-02-beta.md), because a price is decided after the person is known.

## A person opens the product

- **UR-XX-01** (DJ-01) A person signs in on any surface. The product names who is working.
- **UR-XX-02** (DJ-02) A role decides what a person may see. Nothing outside that role appears.

## The record never forgets

- **UR-XX-03** (DJ-01, DJ-02) Every change is kept forever with its author. No correction rewrites history.

---

Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.
"""

SPEC_TWO = """# Pricing and the customer's answer

**v0.1** · component 2 of 2 · Tier 1 specification

*A price is built from recorded cost, never guessed: a loss can only be chosen on purpose.*

## Why this matters

Today the last price sits in an old mail thread, the usual margin lives in someone's
memory, and landed cost is a guess. One forgotten charge turns a good deal into a
quiet loss. Running well, a person prices in minutes from one screen.

## Scope

Cost build up, margin, and the price decision. Who may see a price belongs to
[Access](spec-01-alpha.md), because the role rules apply everywhere.

## A customer asks for a price

- **UR-YY-01** (DJ-02) A price is built from recorded cost. The product never invents a figure.
- **UR-YY-02** (DJ-03) Pricing below cost stops for a typed confirmation. Nothing else releases it.

## The answer leaves the building

- **UR-YY-03** (DJ-03) A quotation states its validity. An expired quotation is never sent again.

---

Traceability: UR-YY-01 to UR-YY-03 → DJ-02, DJ-03.
"""

ACCEPTANCE = """# Definition of Done

**v0.1** · Tier 1 acceptance contract

The two component specifications say what the product must do. This contract says
what must be **shown working end to end** before release: three days in the life that
prove the product. When all three pass, the product is done. Fixtures, negative
controls, evidence paths, and lane rules are deliberately absent: engineering owns them.

## Release rule

The release is done only when all of these hold.

- [ ] Every Tier 1 requirement passes, with evidence that can be reproduced on demand.
- [ ] Every journey below passes on the exact release that goes live, and two runs from a clean start agree.
- [ ] No check fails, none is skipped, none passes only sometimes, no result is left over from an earlier run, no failure is waived.
- [ ] Nothing is excluded.
- [ ] The product owner completes acceptance and approves the first watched live run.

## The three days

### DJ-01. The day a person joins

- [ ] A new person signs in on every surface, then sees only what the role allows.
- [ ] Every change that person makes is kept with its author.
- [ ] A revoked role blocks the next attempt.
- [ ] Nothing typed is lost when the connection drops.

### DJ-02. The day a customer asks for a price

- [ ] A person prices from recorded cost on one screen.
- [ ] No figure appears that the product invented.
- [ ] A role without pricing rights sees no price.
- [ ] The price decision is kept with its author.

### DJ-03. The day a quotation leaves the building

- [ ] A quotation states its validity before it is sent.
- [ ] Pricing below cost stops until a person confirms in writing.
- [ ] An expired quotation is refused.
- [ ] The sent quotation is kept exactly as sent.
"""


def base_config():
    return {
        "config_version": 1,
        "project": "fixture",
        "strictness": "warn",
        "contract_dir": "tier-1",
        "spec_glob": "spec-*.md",
        "acceptance_doc": "definition-of-done.md",
        "registry": "machine-readable/id-map.json",
        "output": "machine-readable/crosswalk.json",
        "requirement": {"prefix": "UR", "component": "[A-Z]{2}", "digits": 2},
        "journey": {"prefix": "DJ", "digits": 2, "heading_level": 3},
        "constraint_tag": "constraint",
        "action_glyph": "",
        "retired": [],
        "budget": {
            "requirements_per_spec": [1, 25],
            "words_per_requirement": {"median": 55, "max": 110},
            "journey_fan_suspect_at": 7,
            "words_per_journey": 120,
            "acceptance_base_words": 200,
            "words_per_page": 400,
        },
        "lock_footer": "\U0001f512 **Locked: {version} ({date}).**",
        "locked_baselines": [],
        "clause_harvests": [],
        "allow": [],
        "proving": {},
    }


def base_registry():
    requirements = {}
    for identifier in (
        "UR-XX-01",
        "UR-XX-02",
        "UR-XX-03",
        "UR-YY-01",
        "UR-YY-02",
        "UR-YY-03",
    ):
        requirements[identifier] = {
            "new": identifier,
            "source": None,
            "frozen_at": None,
            "home": None,
        }
    return {
        "schema_version": 1,
        "adopted": "2026-01-01",
        "note": "Authoritative identifier registry.",
        "components": {
            "XX": {"file": "spec-01-alpha.md", "state": "draft"},
            "YY": {"file": "spec-02-beta.md", "state": "draft"},
        },
        "sources": [],
        "requirements": requirements,
        "journeys": {},
        "withdrawn": {},
        "locks": {},
    }


class ContractCase(unittest.TestCase):
    """One temporary contract per test, removed on teardown."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract-gate-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.config = base_config()
        self.registry = base_registry()
        self.docs = {
            "spec-01-alpha.md": SPEC_ONE,
            "spec-02-beta.md": SPEC_TWO,
            "definition-of-done.md": ACCEPTANCE,
        }

    # ---- fixture plumbing

    @property
    def config_path(self):
        return self.tmp / "contract.config.json"

    @property
    def contract_dir(self):
        return self.tmp / self.config["contract_dir"]

    @property
    def artifact_path(self):
        return self.contract_dir / self.config["output"]

    def write_tree(self):
        self.contract_dir.mkdir(parents=True, exist_ok=True)
        (self.contract_dir / "machine-readable").mkdir(parents=True, exist_ok=True)
        for name, text in self.docs.items():
            (self.contract_dir / name).write_text(text, encoding="utf-8")
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (self.contract_dir / "machine-readable" / "id-map.json").write_text(
            json.dumps(self.registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def run_engine(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = out, err
        try:
            code = contract.main(list(argv))
        finally:
            sys.stdout, sys.stderr = saved
        return code, out.getvalue(), err.getvalue()

    def build(self):
        self.write_tree()
        return self.run_engine("build", "--config", str(self.config_path))

    def artifact(self):
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))

    def problems(self):
        return self.artifact()["problems"]

    def checks_fired(self):
        return set(p["check"] for p in self.problems())

    def assert_names(self, check, subject):
        hits = [p for p in self.problems() if p["check"] == check]
        self.assertTrue(hits, "expected the %s check to fire, fired: %s" % (check, sorted(self.checks_fired())))
        self.assertIn(
            subject,
            [p["subject"] for p in hits],
            "the %s check fired without naming %s" % (check, subject),
        )


class CleanContract(ContractCase):
    def test_clean_contract_passes(self):
        code, out, err = self.build()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.problems(), [], out)
        artifact = self.artifact()
        self.assertEqual(artifact["status"], "COMPLETE")
        self.assertEqual(artifact["counts"]["requirements"], 6)
        self.assertEqual(artifact["counts"]["journeys"], 3)
        self.assertEqual(artifact["counts"]["born"], 6)
        self.assertEqual(artifact["counts"]["inherited"], {})

    def test_the_artifact_is_byte_identical_on_an_unchanged_contract(self):
        self.build()
        first = self.artifact_path.read_bytes()
        self.run_engine("build", "--config", str(self.config_path))
        self.assertEqual(first, self.artifact_path.read_bytes())

    def test_status_prints_one_line_and_always_exits_zero(self):
        self.write_tree()
        code, out, _ = self.run_engine("status", "--config", str(self.config_path))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().split("\n")), 1)
        self.assertIn("6 requirements", out)


class TheLostRequirement(ContractCase):
    """The failure this port exists to remove."""

    def test_a_requirement_hidden_by_a_lost_newline_fails_naming_it(self):
        """Delete the newline before a bullet so it is glued onto the previous line.

        The bullet anchor stops matching, the requirement is parsed by nothing, and
        every check that starts from the documents still passes. The registry check
        must catch it and must name the identifier.
        """
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "\n- **UR-XX-02**", " - **UR-XX-02**"
        )
        code, out, err = self.build()
        self.assertEqual(code, 1, out + err)
        self.assert_names("registry-unclaimed", "UR-XX-02")
        message = [p["message"] for p in self.problems() if p["subject"] == "UR-XX-02"][0]
        self.assertIn("spec-01-alpha.md", message)
        self.assertIn("start of its own line", message)
        self.assertIn("UR-XX-02", out)

    def test_a_registered_identifier_whose_file_was_renamed_fails_naming_it(self):
        moved = self.contract_dir
        self.write_tree()
        os.rename(str(moved / "spec-02-beta.md"), str(moved / "renamed-02-beta.md"))
        code, out, err = self.run_engine("build", "--config", str(self.config_path))
        self.assertEqual(code, 1, out + err)
        for identifier in ("UR-YY-01", "UR-YY-02", "UR-YY-03"):
            self.assert_names("registry-unclaimed", identifier)
        message = [p["message"] for p in self.problems() if p["subject"] == "UR-YY-01"][0]
        self.assertIn("spec-02-beta.md", message)
        self.assertIn("renamed file", message)

    def test_a_registered_identifier_whose_file_was_removed_fails_naming_it(self):
        del self.docs["spec-02-beta.md"]
        code, out, err = self.build()
        self.assertEqual(code, 1, out + err)
        self.assert_names("registry-unclaimed", "UR-YY-03")


class StructuralChecks(ContractCase):
    def test_unregistered_id(self):
        del self.registry["requirements"]["UR-XX-03"]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("unregistered-id", "UR-XX-03")

    def test_duplicate_claim(self):
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace(
            "- **UR-YY-03**", "- **UR-XX-01** (DJ-02) A duplicate claim.\n- **UR-YY-03**"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("duplicate-claim", "UR-XX-01")

    def test_duplicate_registry_target(self):
        self.registry["requirements"]["OLD-1"] = {"new": "UR-XX-01", "source": None}
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("duplicate-registry-target", "UR-XX-01")

    def test_missing_tag(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-03** (DJ-01, DJ-02)", "- **UR-XX-03**"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("missing-tag", "UR-XX-03")

    def test_journey_or_constraint(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace("(DJ-01) A person signs in", "() A person signs in")
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("journey-or-constraint", "UR-XX-01")

    def test_the_constraint_tag_admits_a_requirement_with_no_journey(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "(DJ-01) A person signs in", "(constraint) A person signs in"
        ).replace(
            "Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.",
            "Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.",
        )
        code, _, _ = self.build()
        self.assertNotIn("journey-or-constraint", self.checks_fired())

    def test_unknown_journey(self):
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace("(DJ-02) A price is built", "(DJ-09) A price is built")
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("unknown-journey", "UR-YY-01")

    def test_orphan_journey(self):
        self.docs["definition-of-done.md"] = ACCEPTANCE + (
            "\n### DJ-04. The day nobody touches the keyboard\n\n"
            "- [ ] Scheduled work runs with every client closed.\n"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("orphan-journey", "DJ-04")

    def test_duplicate_journey_heading(self):
        self.docs["definition-of-done.md"] = ACCEPTANCE + (
            "\n### DJ-03. The day a quotation leaves the building\n\n"
            "- [ ] A second heading for the same day.\n"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("duplicate-journey-heading", "DJ-03")

    def test_malformed_number(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-03**", "- **UR-XX-7** (DJ-01) A number of the wrong width.\n- **UR-XX-03**"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("malformed-number", "UR-XX-7")

    def test_greenfield_registry_forbids_any_inheritance_marker(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace("- **UR-XX-01**", "- **UR-XX-01**\\*")
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("marker-forbidden", "UR-XX-01")

    def test_marker_missing(self):
        self.registry["sources"] = [
            {
                "name": "prior",
                "marker": "\\\\\\*",
                "disposition": "RETAINED",
                "origin": "a prior locked contract",
                "expected_requirements": None,
                "expected_journeys": None,
                "baseline": None,
            }
        ]
        self.registry["requirements"]["UR-XX-01"]["source"] = "prior"
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("marker-missing", "UR-XX-01")

    def test_marker_spurious(self):
        self.registry["sources"] = [
            {
                "name": "prior",
                "marker": "\\\\\\*",
                "disposition": "RETAINED",
                "origin": "a prior locked contract",
                "expected_requirements": None,
                "expected_journeys": None,
                "baseline": None,
            }
        ]
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace("- **UR-XX-02**", "- **UR-XX-02**\\*")
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("marker-spurious", "UR-XX-02")

    def test_a_declared_marker_satisfies_its_source(self):
        self.registry["sources"] = [
            {
                "name": "prior",
                "marker": "\\\\\\*",
                "disposition": "RETAINED",
                "origin": "a prior locked contract",
                "expected_requirements": 1,
                "expected_journeys": None,
                "baseline": None,
            }
        ]
        self.registry["requirements"]["UR-XX-01"]["source"] = "prior"
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace("- **UR-XX-01**", "- **UR-XX-01**\\*")
        code, out, err = self.build()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.artifact()["counts"]["inherited"], {"prior": 1})
        self.assertEqual(self.artifact()["counts"]["born"], 5)

    def test_source_count(self):
        self.registry["sources"] = [
            {
                "name": "prior",
                "marker": "\\\\\\*",
                "disposition": "RETAINED",
                "origin": "a prior locked contract",
                "expected_requirements": 9,
                "expected_journeys": None,
                "baseline": None,
            }
        ]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("source-count", "prior")

    def test_retired_identifier(self):
        self.config["retired"] = ["URS[0-9]+\\.[0-9]+"]
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-03**", "- **URS3.10** (DJ-01) A pre adoption identifier.\n- **UR-XX-03**"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("retired-identifier", "URS3.10")

    def test_withdrawn_reappears(self):
        self.registry["withdrawn"]["UR-XX-01"] = {"reason": "merged into UR-XX-03", "withdrawn_at": "v2.0"}
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("withdrawn-reappears", "UR-XX-01")

    def test_frozen_changed(self):
        self.registry["requirements"]["UR-XX-01"]["frozen_at"] = "v1.0 (2026-01-01)"
        self.registry["requirements"]["UR-XX-01"]["frozen_file"] = "spec-02-beta.md"
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("frozen-changed", "UR-XX-01")

    def test_lock_drift(self):
        self.registry["locks"]["spec-01-alpha.md"] = {
            "version": "v0.1",
            "date": "2026-01-01",
            "sha256": "0" * 64,
        }
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("lock-drift", "spec-01-alpha.md")

    def test_baseline_drift(self):
        self.write_tree()
        (self.tmp / "baseline.md").write_text("# A pinned baseline\n", encoding="utf-8")
        self.config["locked_baselines"] = [
            {"name": "baseline", "path": "baseline.md", "version": "v0.2", "sha256": "0" * 64}
        ]
        self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
        code, _, _ = self.run_engine("build", "--config", str(self.config_path))
        self.assertEqual(code, 1)
        self.assert_names("baseline-drift", "baseline")

    def test_component_file_binding(self):
        self.registry["components"]["YY"]["file"] = "spec-03-gamma.md"
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("component-file-binding", "UR-YY-01")

    def test_traceability_footer(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.",
            "Traceability: UR-XX-01 to UR-XX-02 → DJ-01.",
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("traceability-footer", "spec-01-alpha.md")

    def test_frame_requires_the_essence_line(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "*One product, one record: every change is kept, and nothing typed is ever lost.*\n\n",
            "",
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("frame", "spec-01-alpha.md")

    def test_frame_requires_both_lock_markers_together(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "**v0.1** · component 1 of 2", "**v1.0** \U0001f512 · component 1 of 2"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("frame", "spec-01-alpha.md")

    def test_lock_hygiene(self):
        locked = SPEC_ONE.replace(
            "**v0.1** · component 1 of 2", "**v1.0** \U0001f512 · component 1 of 2"
        ).replace(
            "A person signs in on any surface.",
            '<span style="color: mediumseagreen">A person signs in on any surface.</span>',
        )
        locked += "\n\U0001f512 **Locked: v1.0 (2026-01-01).**\n"
        self.docs["spec-01-alpha.md"] = locked
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("lock-hygiene", "spec-01-alpha.md")

    def test_rendering_refuses_a_div_wrapper(self):
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace(
            "## Scope", '<div class="wrapper">\n\n## Scope'
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("rendering", "spec-02-beta.md")

    def test_rendering_refuses_a_callout_block_wrapper(self):
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace(
            "## Scope", "> [!new]\n> A callout wrapper\n\n## Scope"
        )
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("rendering", "spec-02-beta.md")

    def test_journey_registry_unclaimed(self):
        self.registry["journeys"] = {"J1": "DJ-01", "J9": "DJ-09"}
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("journey-registry-unclaimed", "DJ-09")


class BudgetAndLint(ContractCase):
    def test_the_requirement_band_is_config_driven_and_blocks_only_at_fail(self):
        self.config["budget"]["requirements_per_spec"] = [10, 25]
        code, _, _ = self.build()
        self.assertEqual(code, 0, "a budget finding must not block at warn")
        self.assertIn("requirements-per-spec", self.checks_fired())

        self.config["strictness"] = "fail"
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("requirements-per-spec", "spec-01-alpha.md")

    def test_report_strictness_blocks_nothing_and_still_records_the_problem(self):
        self.config["strictness"] = "report"
        del self.registry["requirements"]["UR-XX-03"]
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assertIn("unregistered-id", self.checks_fired())

    def test_report_strictness_never_calls_a_structural_finding_complete(self):
        # The blocking decision and the verdict are separate questions. Report mode
        # buys a project time to reach a clean contract; it does not buy the right
        # to call an incomplete one complete, which is the failure this gate exists
        # to remove and which every greenfield project would meet on day one.
        self.config["strictness"] = "report"
        del self.registry["requirements"]["UR-XX-03"]
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assertEqual(self.artifact()["status"], "INCOMPLETE")

    def test_a_clean_contract_still_reads_complete_in_report_mode(self):
        self.config["strictness"] = "report"
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assertEqual(self.artifact()["status"], "COMPLETE")

    def test_a_quoted_bullet_does_not_read_as_a_dash(self):
        # "> - text" is a blockquoted list item, not a spaced hyphen between clauses.
        # A lint that fires on markup teaches the reader to ignore lints.
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "## The record never forgets",
            "> - a quoted bullet, shown as an example\n\n## The record never forgets",
        )
        self.build()
        self.assertNotIn("dash-punctuation", self.checks_fired())

    def test_a_lint_never_blocks_even_at_fail(self):
        # gate-checks.md promises a lint is printed and never blocks on its own. A
        # dash used as punctuation must not refuse a build at any strictness.
        self.config["strictness"] = "fail"
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace(
            "Cost build up, margin, and the price decision.",
            "Cost build up, margin — and the price decision.",
        )
        code, _, _ = self.build()
        self.assertIn("dash-punctuation", self.checks_fired())
        self.assertEqual(code, 0, "a lint must never block, even at fail")

    def test_a_structural_finding_is_never_downgraded_below_warn(self):
        self.config["strictness"] = "warn"
        del self.registry["requirements"]["UR-XX-03"]
        code, _, _ = self.build()
        self.assertEqual(code, 1)

    def test_an_allow_entry_silences_one_rule_for_one_subject_only(self):
        self.registry["components"]["YY"]["file"] = "spec-03-gamma.md"
        self.config["allow"] = [
            {"rule": "component-file-binding", "id": "UR-YY-01", "reason": "moved by a recorded split"}
        ]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        subjects = [p["subject"] for p in self.problems() if p["check"] == "component-file-binding"]
        self.assertNotIn("UR-YY-01", subjects)
        self.assertIn("UR-YY-02", subjects)

    def test_an_allow_entry_without_a_reason_exits_two(self):
        self.config["allow"] = [{"rule": "component-file-binding", "id": "UR-YY-01"}]
        code, _, err = self.build()
        self.assertEqual(code, 2)
        self.assertIn("reason", err)

    def test_an_allow_entry_with_no_target_is_refused_rather_than_silencing_a_whole_check(self):
        # The fail open switch this tool refuses to have. With no target, one entry
        # would drop every finding of that rule, so a requirement declared in the
        # registry and absent from every document would pass unseen. Reproduce that
        # exact contract and require the engine to refuse the config outright.
        del self.docs["spec-01-alpha.md"]
        self.config["strictness"] = "fail"
        self.config["allow"] = [
            {"rule": "registry-unclaimed", "reason": "we will fix it next sprint"}
        ]
        code, _, err = self.build()
        self.assertEqual(code, 2, "a targetless allow entry must be a configuration error")
        self.assertIn("registry-unclaimed", err)
        self.assertIn("id", err)

    def test_a_suppressed_finding_is_named_in_the_artifact(self):
        # An exception nobody can see is indistinguishable from a check that never ran.
        self.registry["components"]["YY"]["file"] = "spec-03-gamma.md"
        self.config["allow"] = [
            {"rule": "component-file-binding", "id": "UR-YY-01", "reason": "moved by a recorded split"}
        ]
        self.build()
        suppressed = self.artifact()["suppressed"]
        entry = [s for s in suppressed if s["subject"] == "UR-YY-01"]
        self.assertEqual(len(entry), 1, "the suppression must appear in the artifact")
        self.assertEqual(entry[0]["check"], "component-file-binding")
        self.assertEqual(entry[0]["reason"], "moved by a recorded split")

    def test_the_seam_lint_flags_a_packed_bullet_without_blocking(self):
        packed = (
            "- **UR-XX-03** (DJ-01, DJ-02) The record keeps the author and the time and the "
            "reason and the prior value, and no correction rewrites history."
        )
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-03** (DJ-01, DJ-02) Every change is kept forever with its author. "
            "No correction rewrites history.",
            packed,
        )
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assert_names("seam-count", "UR-XX-03")

    def test_the_dash_lint_names_the_line(self):
        self.docs["spec-02-beta.md"] = SPEC_TWO.replace(
            "Cost build up, margin, and the price decision.",
            "Cost build up, margin — and the price decision.",
        )
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assert_names("dash-punctuation", "spec-02-beta.md")


class EngineBehaviour(ContractCase):
    def test_build_writes_the_artifact_before_a_failing_exit(self):
        del self.registry["requirements"]["UR-XX-03"]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assertTrue(self.artifact_path.is_file(), "a blocked run still records its verdict")
        self.assertEqual(self.artifact()["status"], "BLOCKED")

    def test_check_writes_nothing(self):
        self.build()
        before = self.artifact_path.read_bytes()
        path = self.contract_dir / "spec-01-alpha.md"
        path.write_text(SPEC_ONE.replace("(DJ-02) A role decides", "(DJ-09) A role decides"), encoding="utf-8")
        code, _, _ = self.run_engine("check", "--config", str(self.config_path))
        self.assertEqual(code, 1)
        self.assertEqual(before, self.artifact_path.read_bytes())

    def test_check_fails_on_a_stale_committed_artifact(self):
        self.build()
        artifact = self.artifact()
        artifact["counts"]["requirements"] = 999
        self.artifact_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        code, out, _ = self.run_engine("check", "--config", str(self.config_path))
        self.assertEqual(code, 1)
        self.assertIn("stale-artifact", out)

    def test_check_json_prints_the_artifact(self):
        self.build()
        code, out, _ = self.run_engine("check", "--config", str(self.config_path), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "COMPLETE")

    def test_a_missing_config_exits_two_not_one(self):
        self.write_tree()
        code, _, err = self.run_engine("build", "--config", str(self.tmp / "nowhere.json"))
        self.assertEqual(code, 2)
        self.assertIn("nowhere.json", err)

    def test_a_non_empty_proving_block_exits_two(self):
        self.config["proving"] = {"paths": ["docs/specs/tier-2/proving"]}
        code, _, err = self.build()
        self.assertEqual(code, 2)
        self.assertIn("reserved", err)

    def test_an_unknown_config_version_exits_two(self):
        self.config["config_version"] = 2
        code, _, err = self.build()
        self.assertEqual(code, 2)
        self.assertIn("config_version", err)

    def test_a_regex_that_will_not_compile_exits_two(self):
        self.config["retired"] = ["UR-(["]
        code, _, err = self.build()
        self.assertEqual(code, 2)
        self.assertIn("regular expression", err)

    def test_a_missing_acceptance_document_is_reported_not_crashed(self):
        del self.docs["definition-of-done.md"]
        code, out, err = self.build()
        self.assertEqual(code, 0, out + err)
        skipped = self.artifact()["counts"]["skipped_checks"]
        self.assertIn("orphan-journey", skipped)
        self.assertIn("unknown-journey", skipped)
        self.assertEqual(self.artifact()["counts"]["journeys"], 0)

    def test_a_contract_with_no_specifications_yet_is_reported_not_crashed(self):
        del self.docs["spec-01-alpha.md"]
        del self.docs["spec-02-beta.md"]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assertEqual(len([p for p in self.problems() if p["check"] == "registry-unclaimed"]), 6)

    def test_a_directory_matching_the_spec_glob_is_skipped_not_crashed(self):
        self.write_tree()
        (self.contract_dir / "spec-99-a-directory.md").mkdir()
        code, out, err = self.run_engine("build", "--config", str(self.config_path))
        self.assertEqual(code, 0, out + err)

    def test_word_count_ignores_span_markup_but_keeps_its_text(self):
        plain = 'A sentence of five words.'
        marked = '<span style="color: mediumseagreen">A sentence of five words.</span>'
        self.assertEqual(contract.word_count(plain), 5)
        self.assertEqual(contract.word_count(marked), 5)

    def test_word_count_drops_code_fences_and_the_version_line(self):
        text = "# Title\n\n**v1.0** \U0001f512 · one\n\nBody of four words\n\n```\nfenced code here\n```\n"
        # "Title" plus "Body of four words". The version line, the lock furniture and
        # the fenced block are furniture, not prose.
        self.assertEqual(contract.word_count(text), 5)

    def test_the_engine_reports_its_version(self):
        code, out, _ = self.run_engine("--version")
        self.assertEqual(code, 0)
        self.assertIn(contract.ENGINE_VERSION, out)


class RegistryOperations(ContractCase):
    def test_mint_takes_the_next_free_number_and_never_a_withdrawn_one(self):
        self.registry["withdrawn"]["UR-XX-04"] = {"reason": "withdrawn before lock", "withdrawn_at": "v0.2"}
        self.write_tree()
        code, out, err = self.run_engine("mint", "XX", "--count", "2", "--config", str(self.config_path))
        self.assertEqual(code, 0, out + err)
        minted = out.split()
        self.assertEqual(minted, ["UR-XX-05", "UR-XX-06"])
        self.assertNotIn("UR-XX-04", minted)
        registry = json.loads((self.contract_dir / "machine-readable" / "id-map.json").read_text())
        self.assertIn("UR-XX-05", registry["requirements"])

    def test_mint_refuses_an_undeclared_component(self):
        self.write_tree()
        code, _, err = self.run_engine("mint", "ZZ", "--config", str(self.config_path))
        self.assertEqual(code, 2)
        self.assertIn("ZZ", err)

    def test_retire_refuses_while_a_document_still_states_the_identifier(self):
        self.write_tree()
        code, _, err = self.run_engine(
            "retire", "UR-XX-01", "--reason", "merged", "--config", str(self.config_path)
        )
        self.assertEqual(code, 1)
        self.assertIn("spec-01-alpha.md", err)

    def test_retire_burns_the_number_once_the_bullet_is_gone(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-02** (DJ-02) A role decides what a person may see. Nothing outside that role appears.\n",
            "",
        ).replace(
            "Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.",
            "Traceability: UR-XX-01 to UR-XX-03 → DJ-01, DJ-02.",
        )
        self.write_tree()
        code, out, err = self.run_engine(
            "retire", "UR-XX-02", "--reason", "merged into UR-XX-03", "--at", "v0.2",
            "--config", str(self.config_path),
        )
        self.assertEqual(code, 0, out + err)
        registry = json.loads((self.contract_dir / "machine-readable" / "id-map.json").read_text())
        self.assertIn("UR-XX-02", registry["withdrawn"])
        self.assertNotIn("UR-XX-02", registry["requirements"])

    def test_freeze_stabilises_identifiers_without_claiming_approval(self):
        self.write_tree()
        code, out, err = self.run_engine(
            "freeze", "spec-01-alpha.md", "--at", "v0.9", "--config", str(self.config_path)
        )
        self.assertEqual(code, 0, out + err)
        registry = json.loads((self.contract_dir / "machine-readable" / "id-map.json").read_text())
        self.assertEqual(registry["requirements"]["UR-XX-01"]["frozen_at"], "v0.9")
        self.assertEqual(registry["locks"], {})

    def test_lock_refuses_while_strictness_is_report(self):
        self.config["strictness"] = "report"
        self.write_tree()
        code, _, err = self.run_engine(
            "lock", "spec-01-alpha.md", "--version", "v1.0", "--date", "2026-01-01",
            "--config", str(self.config_path),
        )
        self.assertEqual(code, 1)
        self.assertIn("report", err)

    def test_lock_refuses_a_document_that_has_not_completed_its_review_round(self):
        self.write_tree()
        code, _, err = self.run_engine(
            "lock", "spec-01-alpha.md", "--version", "v1.0", "--date", "2026-01-01",
            "--config", str(self.config_path),
        )
        self.assertEqual(code, 1)
        self.assertIn("v1.0", err)

    def test_lock_records_the_bytes_and_freezes_the_identifiers(self):
        locked = SPEC_ONE.replace(
            "**v0.1** · component 1 of 2", "**v1.0** \U0001f512 · component 1 of 2"
        )
        locked += "\n\U0001f512 **Locked: v1.0 (2026-01-01).**\n"
        self.docs["spec-01-alpha.md"] = locked
        self.write_tree()
        code, out, err = self.run_engine(
            "lock", "spec-01-alpha.md", "--version", "v1.0", "--date", "2026-01-01",
            "--config", str(self.config_path),
        )
        self.assertEqual(code, 0, out + err)
        registry = json.loads((self.contract_dir / "machine-readable" / "id-map.json").read_text())
        self.assertIn("spec-01-alpha.md", registry["locks"])
        self.assertEqual(registry["requirements"]["UR-XX-01"]["frozen_at"], "v1.0 (2026-01-01)")

        # A locked document that then moves without a version bump is drift.
        path = self.contract_dir / "spec-01-alpha.md"
        path.write_text(locked.replace("signs in on any surface", "signs in on one surface"), encoding="utf-8")
        code, _, _ = self.run_engine("build", "--config", str(self.config_path))
        self.assertEqual(code, 1)
        self.assert_names("lock-drift", "spec-01-alpha.md")

    def test_lock_requires_the_action_glyph_count_to_be_restated(self):
        self.config["action_glyph"] = "⚙"
        locked = SPEC_ONE.replace(
            "**v0.1** · component 1 of 2", "**v1.0** \U0001f512 · component 1 of 2"
        ).replace("The product names who is working.", "The product names ⚙ who is working.")
        locked += "\n\U0001f512 **Locked: v1.0 (2026-01-01).**\n"
        self.docs["spec-01-alpha.md"] = locked
        self.write_tree()
        code, _, err = self.run_engine(
            "lock", "spec-01-alpha.md", "--version", "v1.0", "--date", "2026-01-01",
            "--config", str(self.config_path),
        )
        self.assertEqual(code, 1)
        self.assertIn("--actions 1", err)
        code, out, err = self.run_engine(
            "lock", "spec-01-alpha.md", "--version", "v1.0", "--date", "2026-01-01",
            "--actions", "1", "--config", str(self.config_path),
        )
        self.assertEqual(code, 0, out + err)


class Initialisation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract-init-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def run_engine(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = out, err
        try:
            code = contract.main(list(argv))
        finally:
            sys.stdout, sys.stderr = saved
        return code, out.getvalue(), err.getvalue()

    def test_init_scaffolds_a_contract_that_the_gate_can_run_on(self):
        code, out, err = self.run_engine("init", "--directory", str(self.tmp), "--adopted", "2026-01-01")
        self.assertEqual(code, 0, out + err)
        config_path = self.tmp / "contract.config.json"
        self.assertTrue(config_path.is_file())
        registry_path = self.tmp / "docs/specs/tier-2/machine-readable/id-map.json"
        self.assertTrue(registry_path.is_file())
        self.assertTrue((self.tmp / "docs/specs/tier-1/README.md").is_file())
        self.assertTrue((self.tmp / "docs/specs/tier-2/proving/README.md").is_file())

        registry = json.loads(registry_path.read_text())
        self.assertEqual(registry["requirements"], {})
        self.assertEqual(registry["sources"], [])

        code, out, err = self.run_engine("build", "--config", str(config_path))
        self.assertEqual(code, 0, out + err)

    def test_init_refuses_to_overwrite_without_force(self):
        self.run_engine("init", "--directory", str(self.tmp))
        code, _, err = self.run_engine("init", "--directory", str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", err)

    def test_the_shipped_templates_still_match_what_init_writes(self):
        # The two JSON templates are read by people, not by the engine, so nothing
        # stops them drifting away from the seed the code actually produces. This is
        # that guard: a reader who copies a template gets what init would have given.
        self.run_engine("init", "--directory", str(self.tmp), "--adopted", "2026-01-01")
        written_config = json.loads((self.tmp / "contract.config.json").read_text())
        written_registry = json.loads(
            (self.tmp / "docs/specs/tier-2/machine-readable/id-map.json").read_text()
        )
        templates = SCRIPT.parent.parent / "templates"
        template_config = json.loads((templates / "contract.config.json").read_text())
        template_registry = json.loads((templates / "id-map.json").read_text())

        # `project` and `adopted` are filled from the project being initialised, so
        # the template carries a placeholder for each and every other key must agree.
        for key in ("project",):
            template_config.pop(key, None)
            written_config.pop(key, None)
        for key in ("adopted",):
            template_registry.pop(key, None)
            written_registry.pop(key, None)
        self.assertEqual(template_config, written_config)
        self.assertEqual(template_registry, written_registry)


class BudgetAndLintCoverage(ContractCase):
    """The budget and lint checks the structural suite does not reach."""

    def test_a_bullet_over_the_word_maximum_is_named(self):
        self.config["budget"]["words_per_requirement"] = {"median": 55, "max": 12}
        code, _, _ = self.build()
        self.assertIn("words-per-requirement-max", self.checks_fired())

    def test_a_document_over_the_median_is_named(self):
        self.config["budget"]["words_per_requirement"] = {"median": 3, "max": 500}
        code, _, _ = self.build()
        self.assertIn("words-per-requirement-median", self.checks_fired())

    def test_an_oversized_acceptance_document_is_named(self):
        self.config["budget"]["acceptance_base_words"] = 1
        self.config["budget"]["words_per_journey"] = 1
        code, _, _ = self.build()
        self.assertIn("acceptance-doc-words", self.checks_fired())

    def test_a_component_reaching_the_journey_fan_threshold_is_named(self):
        self.config["budget"]["journey_fan_suspect_at"] = 2
        code, _, _ = self.build()
        self.assertIn("journey-fan", self.checks_fired())

    def test_budget_findings_block_at_fail_and_not_at_warn(self):
        self.config["budget"]["journey_fan_suspect_at"] = 2
        self.config["strictness"] = "warn"
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.config["strictness"] = "fail"
        code, _, _ = self.build()
        self.assertEqual(code, 1)

    def test_automation_vocabulary_without_the_glyph_is_named(self):
        self.config["action_glyph"] = "⚙"
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-02** (DJ-02) A role decides what a person may see.",
            "- **UR-XX-02** (DJ-02) A role automatically decides what a person may see.",
        )
        code, _, _ = self.build()
        self.assert_names("automation-without-glyph", "UR-XX-02")

    def test_a_declared_glyph_on_the_bullet_silences_the_automation_lint(self):
        self.config["action_glyph"] = "⚙"
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace(
            "- **UR-XX-02** (DJ-02) A role decides what a person may see.",
            "- **UR-XX-02** (DJ-02) A role automatically decides ⚙ what a person may see.",
        )
        self.build()
        subjects = [p["subject"] for p in self.problems() if p["check"] == "automation-without-glyph"]
        self.assertNotIn("UR-XX-02", subjects)

    def test_too_many_standing_constraints_are_named(self):
        self.docs["spec-01-alpha.md"] = SPEC_ONE.replace("(DJ-01, DJ-02) Every change", "(constraint) Every change")
        code, _, _ = self.build()
        self.assertIn("constraint-density", self.checks_fired())

    def test_a_clause_harvest_reports_its_identifiers(self):
        harvest = self.tmp / "technical-contract.md"
        harvest.write_text("- **TPC1.1** the first clause\n- **TPC1.2** the second clause\n")
        self.config["clause_harvests"] = [
            {"name": "technical", "path": "technical-contract.md", "pattern": r"\*\*(TPC[0-9]+\.[0-9]+)\*\*"}
        ]
        code, _, _ = self.build()
        self.assertEqual(code, 0)
        self.assertEqual(self.artifact()["clause_harvests"]["technical"], ["TPC1.1", "TPC1.2"])

    def test_a_missing_harvest_source_is_a_structural_finding_not_a_silent_pass(self):
        # A harvest that cannot read its source is the declared-but-missing shape
        # again: the config declares a witness and the witness is not there.
        self.config["clause_harvests"] = [
            {"name": "technical", "path": "missing-file.md", "pattern": r"\*\*(TPC[0-9]+\.[0-9]+)\*\*"}
        ]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("clause-harvest", "technical")

    def test_a_duplicate_clause_identifier_is_named(self):
        harvest = self.tmp / "technical-contract.md"
        harvest.write_text("- **TPC1.1** the first clause\n- **TPC1.1** the same clause again\n")
        self.config["clause_harvests"] = [
            {"name": "technical", "path": "technical-contract.md", "pattern": r"\*\*(TPC[0-9]+\.[0-9]+)\*\*"}
        ]
        code, _, _ = self.build()
        self.assertEqual(code, 1)
        self.assert_names("clause-harvest", "technical")


if __name__ == "__main__":
    unittest.main(verbosity=2)
