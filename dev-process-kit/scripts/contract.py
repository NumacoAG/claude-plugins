#!/usr/bin/env python3
"""contract.py, the Tier 1 contract gate.

A gate that only compares what is present to what is present will always pass.

This engine therefore starts from the frozen identifier registry and asserts that
every declared identifier is claimed by exactly one document, and only then checks
the documents against themselves. A requirement is recognised only at the start of
its own line, so a single lost newline can hide a bullet from every check that walks
the prose. Walking the registry is what catches it.

Nothing about any one project is compiled in. Every fact lives in a declarative
config file (contract.config.json, at the root of the project being specified) and in
the project's own registry (machine readable/id-map.json inside the contract folder).

Standard library only, Python 3.9 or newer.

Exit codes, three and only three:

  0  clean, status COMPLETE
  1  the contract is violated, status BLOCKED, artifact written before the exit
  2  the engine could not run (config missing or invalid, unreadable input,
     a regex that will not compile, a non empty proving block). Nothing written.
"""

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_VERSION = "1.0"
ARTIFACT_SCHEMA_VERSION = 1
REGISTRY_SCHEMA_VERSION = 1
CONFIG_VERSION = 1

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent

LOCK_GLYPH = "\U0001f512"
FREEZE_GLYPH = "⏳"

# The marker a legacy registry implies when it carries the boolean "inherited" and
# declares no sources of its own. It matches a literal backslash followed by a
# literal asterisk, which is how an escaped asterisk is written in markdown.
LEGACY_MARKER = r"\\\*"

CLASS_ORDER = {"structural": 0, "budget": 1, "lint": 2}

REVIEW_SPAN_COLOURS = ("mediumseagreen", "mediumpurple", "crimson")

AUTOMATION_VOCABULARY = (
    "automatically",
    "on a schedule",
    "without a person",
    "unattended",
    "runs even when",
    "scheduled",
)


class EngineError(Exception):
    """The engine could not run. Always exit 2, never write an artifact."""


class Finding(object):
    __slots__ = ("cls", "subject", "check", "message")

    def __init__(self, cls, subject, check, message):
        self.cls = cls
        self.subject = subject
        self.check = check
        self.message = message

    def as_dict(self):
        return {
            "class": self.cls,
            "subject": self.subject,
            "check": self.check,
            "message": self.message,
        }

    def sort_key(self):
        return (CLASS_ORDER.get(self.cls, 9), self.check, str(self.subject))


# ----------------------------------------------------------------- small helpers


def read_text(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EngineError("cannot read %s (%s)" % (path, exc.strerror or exc))
    text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256_of(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EngineError("cannot hash %s (%s)" % (path, exc.strerror or exc))


def load_json(path, what):
    if not path.exists():
        raise EngineError("%s not found at %s" % (what, path))
    try:
        return json.loads(read_text(path))
    except ValueError as exc:
        raise EngineError("%s at %s is not valid JSON (%s)" % (what, path, exc))


def dump_json(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".contract-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def compile_regex(pattern, what):
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise EngineError("%s is not a valid regular expression: %s (%s)" % (what, pattern, exc))


def resolve_path(base, value):
    candidate = Path(str(value)).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def id_sort_key(identifier):
    match = re.search(r"([0-9]+)\s*$", identifier)
    number = int(match.group(1)) if match else 0
    stem = identifier[: match.start(1)] if match else identifier
    return (stem, number)


# ----------------------------------------------------------------- word counting

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HTML_TAG_RE = re.compile(r"<[^>\n]*>")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)\n]*\)")
WIKILINK_RE = re.compile(r"\[\[([^\]|]*)(?:\|[^\]]*)?\]\]")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
VERSION_LINE_RE = re.compile(r"^\*\*v[0-9]")
WORD_RE = re.compile(r"[0-9A-Za-z]")


def word_count(text):
    """The normalisation is fixed in code and is not configurable.

    A number two projects cannot compare is not a ceiling. It strips frontmatter and
    fenced code blocks, keeps the inner text of HTML spans while dropping the tags
    (so a document's measured size does not change when it locks), reduces links to
    their visible text, strips table pipes and separator rows, strips list bullets,
    heading hashes, blockquote markers, emphasis markers and escaped asterisks,
    drops the version line and the lock footer, and counts whitespace separated
    tokens carrying at least one alphanumeric character.
    """
    text = FRONTMATTER_RE.sub("", text)
    words = 0
    in_fence = False
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if VERSION_LINE_RE.match(line.strip()):
            continue
        if LOCK_GLYPH in line and "**Locked" in line:
            continue
        if TABLE_SEPARATOR_RE.match(line) and "-" in line:
            continue
        cleaned = HTML_TAG_RE.sub("", line)
        cleaned = MD_LINK_RE.sub(r"\1", cleaned)
        cleaned = WIKILINK_RE.sub(r"\1", cleaned)
        cleaned = cleaned.replace("|", " ")
        cleaned = re.sub(r"^\s*#{1,6}\s+", "", cleaned)
        cleaned = re.sub(r"^\s*>+\s?", "", cleaned)
        cleaned = re.sub(r"^\s*[-*+]\s+(\[[ xX]\]\s+)?", "", cleaned)
        cleaned = re.sub(r"^\s*[0-9]+\.\s+", "", cleaned)
        cleaned = cleaned.replace("\\*", " ")
        cleaned = cleaned.replace("**", " ").replace("*", " ").replace("`", " ")
        cleaned = cleaned.replace("~~", " ")
        for token in cleaned.split():
            if WORD_RE.search(token):
                words += 1
    return words


# ----------------------------------------------------------------- configuration

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "project": "",
    "strictness": "report",
    "contract_dir": "docs/specs/tier-1",
    "spec_glob": "spec-*.md",
    "acceptance_doc": "definition-of-done.md",
    "registry": "machine-readable/id-map.json",
    "output": "machine-readable/contract-crosswalk.json",
    "requirement": {"prefix": "UR", "component": "[A-Z]{2}", "digits": 2},
    "journey": {"prefix": "DJ", "digits": 2, "heading_level": 3},
    "constraint_tag": "constraint",
    "action_glyph": "",
    "retired": [],
    "budget": {
        "requirements_per_spec": [10, 25],
        "words_per_requirement": {"median": 55, "max": 110},
        "journey_fan_suspect_at": 7,
        "words_per_journey": 120,
        "acceptance_base_words": 200,
        "words_per_page": 400,
    },
    "lock_footer": LOCK_GLYPH + " **Locked: {version} ({date}).**",
    "locked_baselines": [],
    "clause_harvests": [],
    "allow": [],
    "proving": {},
}

STRICTNESS_VALUES = ("report", "warn", "fail")


def deep_default(value, default):
    if isinstance(default, dict) and isinstance(value, dict):
        merged = dict(default)
        for key, item in value.items():
            merged[key] = deep_default(item, default.get(key))
        return merged
    return default if value is None else value


def find_config(explicit):
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise EngineError("no config at %s" % path)
        return path.resolve()
    path = Path.cwd() / "contract.config.json"
    if not path.is_file():
        raise EngineError(
            "no contract.config.json in the working directory (looked at %s). "
            "Pass --config PATH, or run contract.py init to create one." % path
        )
    return path.resolve()


class Config(object):
    def __init__(self, path, data):
        self.path = path
        self.root = path.parent
        self.data = data

        if data.get("config_version") != CONFIG_VERSION:
            raise EngineError(
                "config_version is %r, this engine only reads %d"
                % (data.get("config_version"), CONFIG_VERSION)
            )
        if data.get("proving"):
            raise EngineError(
                "the proving layer is reserved and not implemented in this version; "
                'the "proving" block in %s must be empty' % path
            )

        merged = deep_default(data, DEFAULT_CONFIG)
        self.project = merged["project"] or self.root.name
        self.strictness = merged["strictness"]
        if self.strictness not in STRICTNESS_VALUES:
            raise EngineError(
                "strictness is %r, expected one of %s"
                % (self.strictness, ", ".join(STRICTNESS_VALUES))
            )

        self.contract_dir = resolve_path(self.root, merged["contract_dir"])
        self.contract_dir_label = str(merged["contract_dir"])
        self.spec_glob = merged["spec_glob"]
        self.acceptance_doc_name = merged["acceptance_doc"]
        self.registry_path = resolve_path(self.contract_dir, merged["registry"])
        self.output_path = resolve_path(self.contract_dir, merged["output"])

        self.req_prefix = merged["requirement"]["prefix"]
        self.req_component = merged["requirement"]["component"]
        self.req_digits = int(merged["requirement"]["digits"])
        if self.req_digits < 1:
            raise EngineError("requirement.digits must be one or more")

        self.journey_cfg = merged["journey"]
        self.constraint_tag = merged["constraint_tag"]
        self.action_glyph = merged["action_glyph"] or ""
        self.retired = list(merged["retired"] or [])
        self.budget = merged["budget"]
        self.lock_footer = merged["lock_footer"]
        self.locked_baselines = list(merged["locked_baselines"] or [])
        self.clause_harvests = list(merged["clause_harvests"] or [])
        self.allow = list(merged["allow"] or [])

        for entry in self.allow:
            if not entry.get("rule") or not entry.get("reason"):
                raise EngineError(
                    'every "allow" entry needs a "rule" and a "reason"; found %s' % json.dumps(entry)
                )
            if not entry.get("id") and not entry.get("file"):
                # One exception, one rule, one target. An entry with no target would
                # silence a whole check for the whole contract, which is the fail open
                # switch this tool refuses to have: the gate would report a clean
                # contract while a declared identifier was missing from every document.
                raise EngineError(
                    'the "allow" entry %s names a rule and no target; add an "id" or a "file" so '
                    "it silences one finding rather than a whole check" % json.dumps(entry)
                )

        # Composed patterns. Numeric classes are written [0-9] rather than \\d so
        # that an ASCII contract cannot be satisfied by a Unicode digit.
        digits = "[0-9]{%d}" % self.req_digits
        if self.req_component:
            self.req_id_pattern = "%s-(?:%s)-%s" % (
                re.escape(self.req_prefix),
                self.req_component,
                digits,
            )
            self.req_loose_pattern = "%s-[A-Za-z0-9]+-[0-9]+" % re.escape(self.req_prefix)
        else:
            self.req_id_pattern = "%s-%s" % (re.escape(self.req_prefix), digits)
            self.req_loose_pattern = "%s-[0-9]+" % re.escape(self.req_prefix)

        self.req_id_re = compile_regex("\\A(?:%s)\\Z" % self.req_id_pattern, "the requirement identifier")
        self.req_loose_re = compile_regex("\\A(?:%s)\\Z" % self.req_loose_pattern, "the loose requirement identifier")
        self.bullet_re = compile_regex(
            r"\A- \*\*(?P<id>%s)\*\*(?P<mark>[^\s(\n]{0,4}) \((?P<tags>[^)\n]*)\)"
            % self.req_id_pattern,
            "the requirement bullet",
        )
        self.bold_head_re = compile_regex(r"\A- \*\*(?P<token>[^*\n]+)\*\*", "the bullet head")
        self.retired_res = [
            compile_regex("\\A(?:%s)\\Z" % pattern, "a retired identifier family")
            for pattern in self.retired
        ]

        if self.journey_cfg:
            jdigits = "[0-9]{%d}" % int(self.journey_cfg.get("digits", 2))
            self.journey_prefix = self.journey_cfg.get("prefix", "DJ")
            self.journey_id_pattern = "%s-%s" % (re.escape(self.journey_prefix), jdigits)
            self.journey_tag_re = compile_regex(self.journey_id_pattern, "the journey tag")
            level = int(self.journey_cfg.get("heading_level", 3))
            self.journey_heading_re = compile_regex(
                r"\A%s (?P<id>%s)\." % ("#" * level, self.journey_id_pattern),
                "the journey heading",
            )
        else:
            self.journey_prefix = None
            self.journey_id_pattern = None
            self.journey_tag_re = None
            self.journey_heading_re = None

    def id_scheme(self):
        parts = ["%s identifiers shaped %s" % (self.req_prefix, self.example_id())]
        if self.journey_prefix:
            parts.append(
                "journeys shaped %s-%s"
                % (self.journey_prefix, "0" * int(self.journey_cfg.get("digits", 2)))
            )
        parts.append('the tag "(%s)" admits a requirement that reaches no journey' % self.constraint_tag)
        return "; ".join(parts)

    def example_id(self):
        number = "0" * (self.req_digits - 1) + "1"
        if self.req_component:
            return "%s-XX-%s" % (self.req_prefix, number)
        return "%s-%s" % (self.req_prefix, number)

    def lock_footer_re(self):
        # review-kit owns the wording of the lock footer, so this gate asserts only
        # what it can own: a footer exists, and it names a version and a date. Pinning
        # the exact string here would make this a second authority on review-kit's
        # regime, and a document locked exactly as that skill instructs would fail.
        # `lock_footer` stays in the config as the form the `lock` verb writes.
        return compile_regex(
            r"\A%s\s*\*\*Locked\b.*?v[0-9]+\.[0-9]+.*?[0-9]{4}-[0-9]{2}-[0-9]{2}.*\*\*\Z" % LOCK_GLYPH,
            "the lock footer",
        )


def load_config(explicit):
    path = find_config(explicit)
    data = load_json(path, "the contract config")
    if not isinstance(data, dict):
        raise EngineError("the contract config at %s must be a JSON object" % path)
    return Config(path, data)


# ----------------------------------------------------------------- the registry


class Registry(object):
    """The authoritative list of every live identifier.

    Two shapes are read. The current shape keys an entry by its own identifier and
    names an inheritance source by name. The legacy shape keys an entry by the
    identifier of a prior contract and carries a boolean called inherited. The
    legacy shape admits exactly one ancestor by construction, so it is normalised
    into a single synthesised source on read and is never written back.
    """

    def __init__(self, path, data):
        self.path = path
        self.raw = data
        self.legacy = False

        components = {}
        block = data.get("components") or {}
        for code, value in block.items():
            if isinstance(value, dict):
                components[code] = {
                    "file": value.get("file"),
                    "state": value.get("state", "draft"),
                }
            else:
                components[code] = {"file": value, "state": "draft"}
        for code, value in (data.get("component_codes") or {}).items():
            self.legacy = True
            components.setdefault(code, {"file": value, "state": "draft"})
        self.components = components

        self.sources = []
        for entry in data.get("sources") or []:
            if not entry.get("name") or not entry.get("marker"):
                raise EngineError(
                    "every registry source needs a name and a marker; found %s" % json.dumps(entry)
                )
            compile_regex(entry["marker"], "the marker of source %s" % entry["name"])
            self.sources.append(entry)

        self.requirements = {}
        self.duplicate_targets = []
        seen_targets = {}
        for key, value in (data.get("requirements") or {}).items():
            if isinstance(value, dict):
                target = value.get("new") or key
                source = value.get("source")
                if source is None and "inherited" in value:
                    self.legacy = True
                    source = "__legacy__" if value.get("inherited") else None
                entry = {
                    "key": key,
                    "target": target,
                    "source": source,
                    "frozen_at": value.get("frozen_at"),
                    "frozen_file": value.get("frozen_file"),
                    "home": value.get("home"),
                }
            else:
                target = value or key
                entry = {
                    "key": key,
                    "target": target,
                    "source": None,
                    "frozen_at": None,
                    "frozen_file": None,
                    "home": None,
                }
            if target in seen_targets:
                self.duplicate_targets.append((target, seen_targets[target], key))
            else:
                seen_targets[target] = key
            self.requirements[target] = entry

        if any(e["source"] == "__legacy__" for e in self.requirements.values()):
            if self.sources:
                inherited_name = self.sources[0]["name"]
                for entry in self.requirements.values():
                    if entry["source"] == "__legacy__":
                        entry["source"] = inherited_name
            else:
                self.sources.append(
                    {
                        "name": "__legacy__",
                        "marker": LEGACY_MARKER,
                        "disposition": "RETAINED",
                        "origin": "a prior locked contract",
                        "expected_requirements": None,
                        "expected_journeys": None,
                        "baseline": None,
                    }
                )

        self.source_by_name = dict((s["name"], s) for s in self.sources)
        self.source_marker_re = dict(
            (s["name"], compile_regex("\\A(?:%s)\\Z" % s["marker"], "the marker of source %s" % s["name"]))
            for s in self.sources
        )

        self.journeys = dict(data.get("journeys") or {})
        self.withdrawn = dict(data.get("withdrawn") or {})
        self.locks = dict(data.get("locks") or {})

    def declared_ids(self):
        return sorted(self.requirements.keys(), key=id_sort_key)

    def expected_file(self, target):
        entry = self.requirements.get(target) or {}
        if entry.get("home"):
            return entry["home"]
        component = component_of(target)
        if component and component in self.components:
            return self.components[component]["file"]
        return None


def component_of(identifier):
    parts = identifier.split("-")
    if len(parts) >= 3:
        return parts[-2]
    return None


def load_registry(path):
    if not path.exists():
        raise EngineError(
            "no registry at %s. Every identifier lives there, so the gate cannot run "
            "without it. Run contract.py init to create an empty one." % path
        )
    data = load_json(path, "the registry")
    if not isinstance(data, dict):
        raise EngineError("the registry at %s must be a JSON object" % path)
    return Registry(path, data)


def seed_registry(adopted):
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "adopted": adopted,
        "note": (
            "Authoritative identifier registry. Every live identifier appears here. "
            "Entries whose key equals their target were born in this project."
        ),
        "components": {},
        "sources": [],
        "requirements": {},
        "journeys": {},
        "withdrawn": {},
        "locks": {},
    }


def save_registry(registry_path, data):
    write_atomic(registry_path, dump_json(data))


# ----------------------------------------------------------------- parsing


class Bullet(object):
    __slots__ = ("identifier", "file", "line", "journeys", "constraint", "mark", "tags", "text", "words", "glyphs")

    def __init__(self, identifier, file, line, journeys, constraint, mark, tags, text, words, glyphs):
        self.identifier = identifier
        self.file = file
        self.line = line
        self.journeys = journeys
        self.constraint = constraint
        self.mark = mark
        self.tags = tags
        self.text = text
        self.words = words
        self.glyphs = glyphs


def bullet_body(lines, index):
    """A bullet is one logical line, so the body is the bullet line plus any
    continuation lines that are indented under it."""
    body = [lines[index]]
    cursor = index + 1
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip():
            break
        if line.startswith("- ") or line.startswith("#") or line.startswith("|"):
            break
        if not line.startswith(" ") and not line.startswith("\t"):
            break
        body.append(line)
        cursor += 1
    return "\n".join(body)


def parse_document(cfg, name, text, findings, allow_filter):
    """Return the bullets a document states, recording every line that looks like a
    requirement and is not one."""
    bullets = []
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not line.startswith("- **"):
            continue
        head = cfg.bold_head_re.match(line)
        if head is None:
            continue
        token = head.group("token")
        match = cfg.bullet_re.match(line)
        if match is not None and cfg.req_id_re.match(token or ""):
            body = bullet_body(lines, index)
            tags = match.group("tags")
            journeys = []
            if cfg.journey_tag_re is not None:
                journeys = cfg.journey_tag_re.findall(tags)
            constraint = tags.strip() == cfg.constraint_tag
            rest = body[match.end():]
            bullets.append(
                Bullet(
                    identifier=match.group("id"),
                    file=name,
                    line=index + 1,
                    journeys=journeys,
                    constraint=constraint,
                    mark=match.group("mark"),
                    tags=tags,
                    text=rest.strip(),
                    words=word_count(rest),
                    glyphs=(body.count(cfg.action_glyph) if cfg.action_glyph else 0),
                )
            )
            continue

        # The line opens like a requirement and did not parse as one. Say why.
        if cfg.req_id_re.match(token or ""):
            allow_filter(
                findings,
                Finding(
                    "structural",
                    token,
                    "missing-tag",
                    "%s line %d states no parenthesised tag; every requirement names a journey "
                    'such as "(%s-01)" or the standing constraint tag "(%s)"; fix by adding the '
                    "tag between the closing bold marker and the sentence"
                    % (name, index + 1, cfg.journey_prefix or "DJ", cfg.constraint_tag),
                ),
            )
            continue
        for pattern, compiled in zip(cfg.retired, cfg.retired_res):
            if compiled.match(token or ""):
                allow_filter(
                    findings,
                    Finding(
                        "structural",
                        token,
                        "retired-identifier",
                        "%s line %d still uses the retired identifier family %s; fix by replacing it "
                        "with the identifier the registry maps it to"
                        % (name, index + 1, pattern),
                    ),
                )
                break
        else:
            if cfg.req_loose_re.match(token or ""):
                allow_filter(
                    findings,
                    Finding(
                        "structural",
                        token,
                        "malformed-number",
                        "%s line %d states %s, whose number is not exactly %d digits; a silent skip in "
                        "a gate that fails closed is a bug in the gate, so fix the width to %s"
                        % (name, index + 1, token, cfg.req_digits, cfg.example_id()),
                    ),
                )
    return bullets


def parse_journeys(cfg, text):
    headings = []
    if cfg.journey_heading_re is None:
        return headings
    for index, line in enumerate(text.split("\n")):
        match = cfg.journey_heading_re.match(line)
        if match is not None:
            headings.append((match.group("id"), index + 1))
    return headings


# ----------------------------------------------------------------- the gate


class Gate(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.findings = []
        self.skipped = []
        self.suppressed = []
        self.registry = load_registry(cfg.registry_path)

        if not cfg.contract_dir.is_dir():
            raise EngineError(
                "no contract folder at %s. Run contract.py init to create one." % cfg.contract_dir
            )

        self.spec_names = []
        for entry in sorted(cfg.contract_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_file():
                continue
            if entry.name == "README.md":
                continue
            if fnmatch.fnmatch(entry.name, cfg.spec_glob):
                self.spec_names.append(entry.name)

        self.texts = {}
        for name in self.spec_names:
            self.texts[name] = read_text(cfg.contract_dir / name)

        self.acceptance_name = None
        self.acceptance_text = None
        if cfg.acceptance_doc_name:
            path = cfg.contract_dir / cfg.acceptance_doc_name
            if path.is_file():
                self.acceptance_name = cfg.acceptance_doc_name
                self.acceptance_text = read_text(path)
            else:
                self.skipped.extend(
                    ["unknown-journey", "orphan-journey", "journey-or-constraint", "duplicate-journey-heading"]
                )
        else:
            self.skipped.extend(
                ["unknown-journey", "orphan-journey", "journey-or-constraint", "duplicate-journey-heading"]
            )

        self.bullets = []
        self.owners = {}
        self.duplicate_claims = []
        self.journeys = []
        self.journey_lines = {}
        self.harvests = {}
        self.run()

    # ---- finding plumbing

    def add(self, cls, subject, check, message):
        self.record(self.findings, Finding(cls, subject, check, message))

    def record(self, bucket, finding):
        for rule in self.cfg.allow:
            if rule.get("rule") != finding.check:
                continue
            target = rule.get("id") or rule.get("file")
            if target == finding.subject:
                # A suppressed finding is still a finding. It leaves the blocking set
                # and enters the artifact by name, because an exception nobody can see
                # is indistinguishable from a check that never ran.
                self.suppressed.append(
                    {
                        "check": finding.check,
                        "subject": finding.subject,
                        "reason": rule.get("reason", ""),
                        "message": finding.message,
                    }
                )
                return
        bucket.append(finding)

    def allow_filter(self, bucket, finding):
        self.record(bucket, finding)

    # ---- the run

    def run(self):
        cfg = self.cfg
        for name in self.spec_names:
            self.bullets.extend(
                parse_document(cfg, name, self.texts[name], self.findings, self.allow_filter)
            )

        for bullet in self.bullets:
            if bullet.identifier in self.owners:
                first = self.owners[bullet.identifier]
                self.duplicate_claims.append((bullet.identifier, first.file, bullet.file))
                self.add(
                    "structural",
                    bullet.identifier,
                    "duplicate-claim",
                    "claimed by %s line %d and by %s line %d; exactly one document owns a promise, "
                    "so delete one bullet or mint a fresh identifier for the second with "
                    "contract.py mint"
                    % (first.file, first.line, bullet.file, bullet.line),
                )
            else:
                self.owners[bullet.identifier] = bullet

        if self.acceptance_text is not None:
            seen = {}
            for identifier, line in parse_journeys(self.cfg, self.acceptance_text):
                if identifier in seen:
                    self.add(
                        "structural",
                        identifier,
                        "duplicate-journey-heading",
                        "%s declares %s twice, at line %d and line %d; a journey is one day and one "
                        "heading, so merge the two sections"
                        % (self.acceptance_name, identifier, seen[identifier], line),
                    )
                else:
                    seen[identifier] = line
                    self.journeys.append(identifier)
                    self.journey_lines[identifier] = line

        self.check_registry_unclaimed()
        self.check_registry_journeys()
        self.check_unregistered()
        self.check_duplicate_registry_targets()
        self.check_tags_and_journeys()
        self.check_markers()
        self.check_withdrawn()
        self.check_frozen()
        self.check_component_binding()
        self.check_source_counts()
        self.check_locks()
        self.check_baselines()
        self.check_traceability_footers()
        self.check_frames()
        self.check_lock_hygiene()
        self.check_rendering()
        self.run_harvests()
        self.check_budgets()
        self.check_lints()

    # ---- structural checks

    def check_registry_unclaimed(self):
        """The check this engine exists for.

        Every other check walks the documents and compares what it finds against
        what it finds. This one walks the declared registry and demands that each
        entry be found. A requirement that stops being parsed, because a newline was
        deleted and its bullet was glued onto the end of the previous line, because a
        bold marker broke, or because its file was renamed, is invisible to every
        other check and the gate would still report COMPLETE.
        """
        for target in self.registry.declared_ids():
            if target in self.owners:
                continue
            expected = self.registry.expected_file(target)
            where = "expected in %s" % expected if expected else "no owning file is registered for it"
            self.add(
                "structural",
                target,
                "registry-unclaimed",
                "declared in the registry but stated by no document (silently lost); %s; a bullet "
                "counts only at the start of its own line, so look for a lost newline gluing it onto "
                "the previous line, a broken bold marker, or a renamed file; fix by restoring "
                '"- **%s** (%s-nn) ..." at column 1 of its own line, or retire the identifier with '
                "contract.py retire %s --reason ..."
                % (where, target, self.cfg.journey_prefix or "DJ", target),
            )

    def check_registry_journeys(self):
        if self.acceptance_text is None:
            if self.registry.journeys:
                self.skipped.append("journey-registry-unclaimed")
            return
        for key, target in sorted(self.registry.journeys.items()):
            if not target:
                self.add(
                    "structural",
                    key,
                    "journey-registry-unclaimed",
                    "the registry maps journey %s to nothing; fix by giving it its %s identifier or "
                    "removing the entry" % (key, self.cfg.journey_prefix or "DJ"),
                )
                continue
            if target not in self.journeys:
                self.add(
                    "structural",
                    target,
                    "journey-registry-unclaimed",
                    "declared in the registry (as %s) but %s carries no heading for it; fix by "
                    'restoring the "%s %s. The day ..." heading, or removing the registry entry'
                    % (
                        key,
                        self.acceptance_name,
                        "#" * int(self.cfg.journey_cfg.get("heading_level", 3)),
                        target,
                    ),
                )

    def check_unregistered(self):
        for identifier, bullet in sorted(self.owners.items(), key=lambda kv: id_sort_key(kv[0])):
            if identifier not in self.registry.requirements:
                self.add(
                    "structural",
                    identifier,
                    "unregistered-id",
                    "%s line %d states it, and the registry does not hold it; every live identifier "
                    "is registered, so fix by minting it with contract.py mint %s"
                    % (bullet.file, bullet.line, component_of(identifier) or ""),
                )

    def check_duplicate_registry_targets(self):
        for target, first, second in self.registry.duplicate_targets:
            self.add(
                "structural",
                target,
                "duplicate-registry-target",
                "the registry maps both %s and %s onto it, so one of the two mappings is silently "
                "lost; fix by giving the second its own identifier in %s"
                % (first, second, self.registry.path.name),
            )

    def check_tags_and_journeys(self):
        for identifier, bullet in sorted(self.owners.items(), key=lambda kv: id_sort_key(kv[0])):
            if self.acceptance_text is None:
                continue
            for journey in bullet.journeys:
                if journey not in self.journeys:
                    self.add(
                        "structural",
                        identifier,
                        "unknown-journey",
                        "%s line %d traces to %s, and %s carries no heading for it; fix by tagging a "
                        "journey that exists or by adding the missing day"
                        % (bullet.file, bullet.line, journey, self.acceptance_name),
                    )
            if not bullet.journeys and not bullet.constraint:
                self.add(
                    "structural",
                    identifier,
                    "journey-or-constraint",
                    '%s line %d names no journey and is not tagged "(%s)"; every promise is proven by '
                    "a day or is a declared standing constraint, so fix by naming the day that proves it"
                    % (bullet.file, bullet.line, self.cfg.constraint_tag),
                )
        if self.acceptance_text is None:
            return
        reached = set()
        for bullet in self.owners.values():
            reached.update(bullet.journeys)
        for journey in self.journeys:
            if journey not in reached:
                self.add(
                    "structural",
                    journey,
                    "orphan-journey",
                    "%s line %d declares it and no requirement traces to it, so this day proves "
                    "nothing anyone asked for; fix by tagging the requirements it proves or by "
                    "removing the journey"
                    % (self.acceptance_name, self.journey_lines.get(journey, 0)),
                )

    def check_markers(self):
        sources = self.registry.sources
        for identifier, bullet in sorted(self.owners.items(), key=lambda kv: id_sort_key(kv[0])):
            entry = self.registry.requirements.get(identifier)
            mark = bullet.mark or ""
            if not sources:
                if mark:
                    self.add(
                        "structural",
                        identifier,
                        "marker-forbidden",
                        "%s line %d carries the marker %r and the registry declares no inheritance "
                        "sources, so the character has no referent; fix by deleting it"
                        % (bullet.file, bullet.line, mark),
                    )
                continue
            source_name = entry.get("source") if entry else None
            if source_name:
                pattern = self.registry.source_marker_re.get(source_name)
                if pattern is None:
                    self.add(
                        "structural",
                        identifier,
                        "marker-missing",
                        "%s line %d descends from the source %r, which the registry does not declare; "
                        "fix by declaring the source with contract.py acquire"
                        % (bullet.file, bullet.line, source_name),
                    )
                elif not (mark and pattern.match(mark)):
                    self.add(
                        "structural",
                        identifier,
                        "marker-missing",
                        "%s line %d descends from %s (as %s) and carries no matching source marker; "
                        "changing inherited text is an amendment, so fix by restoring the marker "
                        "immediately after the closing bold marker"
                        % (bullet.file, bullet.line, source_name, entry.get("key")),
                    )
            elif mark:
                self.add(
                    "structural",
                    identifier,
                    "marker-spurious",
                    "%s line %d carries the marker %r and the registry says it was born in this "
                    "project; fix by deleting the marker, or by recording its source in %s"
                    % (bullet.file, bullet.line, mark, self.registry.path.name),
                )

    def check_withdrawn(self):
        for identifier in sorted(self.registry.withdrawn, key=id_sort_key):
            if identifier in self.owners:
                bullet = self.owners[identifier]
                reason = (self.registry.withdrawn[identifier] or {}).get("reason", "")
                self.add(
                    "structural",
                    identifier,
                    "withdrawn-reappears",
                    "%s line %d states a withdrawn number (%s); a burned number never resolves to a "
                    "second promise, so fix by minting a fresh identifier with contract.py mint %s"
                    % (bullet.file, bullet.line, reason or "no reason recorded", component_of(identifier) or ""),
                )

    def check_frozen(self):
        for target in self.registry.declared_ids():
            entry = self.registry.requirements[target]
            if not entry.get("frozen_at"):
                continue
            bullet = self.owners.get(target)
            if bullet is None:
                continue  # already reported as registry-unclaimed
            frozen_file = entry.get("frozen_file")
            if frozen_file and bullet.file != frozen_file:
                self.add(
                    "structural",
                    target,
                    "frozen-changed",
                    "was frozen at %s in %s and now lives in %s; a frozen identifier never moves "
                    'without a recorded component split, so fix by setting its "home" in %s or by '
                    "restoring the bullet to its own document"
                    % (entry["frozen_at"], frozen_file, bullet.file, self.registry.path.name),
                )

    def check_component_binding(self):
        if not self.registry.components:
            self.skipped.append("component-file-binding")
            return
        for identifier, bullet in sorted(self.owners.items(), key=lambda kv: id_sort_key(kv[0])):
            entry = self.registry.requirements.get(identifier) or {}
            if entry.get("home"):
                expected = entry["home"]
            else:
                component = component_of(identifier)
                if component is None or component not in self.registry.components:
                    continue
                expected = self.registry.components[component]["file"]
            if expected and bullet.file != expected:
                self.add(
                    "structural",
                    identifier,
                    "component-file-binding",
                    "%s line %d states it, and its component is registered to %s; fix by moving the "
                    'bullet home, or by recording the move with a "home" override in %s'
                    % (bullet.file, bullet.line, expected, self.registry.path.name),
                )

    def check_source_counts(self):
        for source in self.registry.sources:
            expected = source.get("expected_requirements")
            if expected is not None:
                actual = sum(
                    1 for e in self.registry.requirements.values() if e.get("source") == source["name"]
                )
                if actual != expected:
                    self.add(
                        "structural",
                        source["name"],
                        "source-count",
                        "the registry holds %d requirements from this source and the source declares "
                        "%d; fix by correcting expected_requirements in %s, or by restoring the "
                        "missing entries"
                        % (actual, expected, self.registry.path.name),
                    )
            expected_j = source.get("expected_journeys")
            if expected_j is not None and len(self.registry.journeys) != expected_j:
                self.add(
                    "structural",
                    source["name"],
                    "source-count",
                    "the registry holds %d journeys and this source declares %d; fix by correcting "
                    "expected_journeys in %s, or by restoring the missing entries"
                    % (len(self.registry.journeys), expected_j, self.registry.path.name),
                )

    def check_locks(self):
        for name, lock in sorted(self.registry.locks.items()):
            path = self.cfg.contract_dir / name
            if not path.is_file():
                self.add(
                    "structural",
                    name,
                    "lock-drift",
                    "the registry records a lock at %s and the file is gone; fix by restoring the "
                    "document, or by removing its lock entry in %s"
                    % (lock.get("version", "an unknown version"), self.registry.path.name),
                )
                continue
            actual = sha256_of(path)
            if actual == lock.get("sha256"):
                continue
            text = read_text(path)
            version = self.version_of(text)
            if version and version == lock.get("version"):
                self.add(
                    "structural",
                    name,
                    "lock-drift",
                    "was locked at %s and its bytes have moved while its version line still reads %s; "
                    "a locked document changes only through a review round, so fix by bumping the "
                    "version line and re running contract.py lock %s"
                    % (lock.get("version"), version, name),
                )

    def check_baselines(self):
        for baseline in self.cfg.locked_baselines:
            path = resolve_path(self.cfg.root, baseline.get("path", ""))
            if not path.is_file():
                self.add(
                    "structural",
                    baseline.get("name", str(path)),
                    "baseline-drift",
                    "the pinned baseline at %s is missing, so the contract is being checked against "
                    "nothing; fix by restoring the file, or by removing the pin from the config"
                    % baseline.get("path"),
                )
                continue
            actual = sha256_of(path)
            if actual != baseline.get("sha256"):
                self.add(
                    "structural",
                    baseline.get("name", str(path)),
                    "baseline-drift",
                    "the pinned baseline at %s changed (expected %s, found %s); a contract validated "
                    "against a silently edited baseline proves nothing, so fix by re reading the "
                    "document and re pinning its digest in the config"
                    % (baseline.get("path"), baseline.get("sha256"), actual),
                )

    def check_traceability_footers(self):
        for name in self.spec_names:
            ids = sorted(
                [b.identifier for b in self.bullets if b.file == name and b.identifier in self.owners],
                key=id_sort_key,
            )
            if not ids:
                continue
            footer = None
            footer_line = 0
            for index, line in enumerate(self.texts[name].split("\n")):
                if line.startswith("Traceability:"):
                    footer = line
                    footer_line = index + 1
            expected_ranges = self.expected_ranges(ids)
            expected_journeys = sorted(
                set(j for b in self.bullets if b.file == name for j in b.journeys)
            )
            expected = "Traceability: %s%s." % (
                ", ".join(expected_ranges),
                (" → " + ", ".join(expected_journeys)) if expected_journeys else "",
            )
            if footer is None:
                self.add(
                    "structural",
                    name,
                    "traceability-footer",
                    "states %d requirements and carries no traceability footer; fix by adding "
                    '"%s" above the lock footer' % (len(ids), expected),
                )
                continue
            if footer.rstrip() != expected:
                self.add(
                    "structural",
                    name,
                    "traceability-footer",
                    "line %d reads %r and the computed fan out is %r; the footer is a range so that "
                    "retiring an identifier costs nothing, so fix by replacing the line"
                    % (footer_line, footer.rstrip(), expected),
                )

    @staticmethod
    def expected_ranges(ids):
        by_component = {}
        order = []
        for identifier in ids:
            component = component_of(identifier) or ""
            if component not in by_component:
                by_component[component] = []
                order.append(component)
            by_component[component].append(identifier)
        ranges = []
        for component in order:
            group = sorted(by_component[component], key=id_sort_key)
            if len(group) == 1:
                ranges.append(group[0])
            else:
                ranges.append("%s to %s" % (group[0], group[-1]))
        return ranges

    def version_of(self, text):
        for line in text.split("\n"):
            match = re.match(r"^\*\*(v[0-9]+\.[0-9]+)", line.strip())
            if match:
                return match.group(1)
        return None

    def check_frames(self):
        for name in self.spec_names:
            self.check_frame(name, self.texts[name], is_spec=True)
        if self.acceptance_text is not None:
            self.check_frame(self.acceptance_name, self.acceptance_text, is_spec=False)

    def check_frame(self, name, text, is_spec):
        lines = text.split("\n")

        def line_at(number):
            return lines[number - 1] if len(lines) >= number else ""

        if not line_at(1).startswith("# "):
            self.add(
                "structural",
                name,
                "frame",
                "line 1 is not the H1 title; a document that is self locating when read alone opens "
                "with its own name, so fix by putting the title on line 1",
            )
        version_line = line_at(3).strip()
        version_re = re.compile(
            r"^\*\*v[0-9]+\.[0-9]+( draft)?\*\*(?: [%s%s])* · .+$" % (LOCK_GLYPH, FREEZE_GLYPH)
        )
        if not version_re.match(version_line):
            self.add(
                "structural",
                name,
                "frame",
                "line 3 reads %r and is not a version line; the shape is "
                '"**vN.n** [glyph] · <role>", and the lock glyph absent is the only draft marker; '
                "fix by writing the version line on line 3" % version_line,
            )
        if is_spec:
            essence = line_at(5).strip()
            if not (essence.startswith("*") and essence.endswith("*") and not essence.startswith("**")):
                self.add(
                    "structural",
                    name,
                    "frame",
                    "line 5 is not an italic essence line; one sentence naming the invariant that "
                    "breaks first belongs there, so fix by writing it between single asterisks",
                )
            for heading in ("## Why this matters", "## Scope"):
                if not any(line.strip() == heading for line in lines):
                    self.add(
                        "structural",
                        name,
                        "frame",
                        'no "%s" section; fix by adding it' % heading,
                    )
            rules = sum(1 for line in lines if line.strip() == "---")
            if rules != 1:
                self.add(
                    "structural",
                    name,
                    "frame",
                    "carries %d horizontal rules and the frame has exactly one, immediately above the "
                    "traceability footer; fix by deleting the others" % rules,
                )
        locked_glyph = LOCK_GLYPH in version_line
        footer_re = self.cfg.lock_footer_re()
        has_footer = any(footer_re.match(line.strip()) for line in lines)
        if locked_glyph and not has_footer:
            self.add(
                "structural",
                name,
                "frame",
                "the version line carries the lock glyph and the document has no lock footer; fix by "
                "appending the footer, or by running contract.py lock %s" % name,
            )
        if has_footer and not locked_glyph:
            self.add(
                "structural",
                name,
                "frame",
                "carries a lock footer and its version line carries no lock glyph; the two lock "
                "markers travel together, so fix by adding the glyph to line 3",
            )

    def check_lock_hygiene(self):
        footer_re = self.cfg.lock_footer_re()
        for name in list(self.spec_names) + ([self.acceptance_name] if self.acceptance_name else []):
            text = self.texts.get(name, self.acceptance_text or "")
            lines = text.split("\n")
            version_line = lines[2].strip() if len(lines) > 2 else ""
            if LOCK_GLYPH not in version_line:
                continue
            for colour in REVIEW_SPAN_COLOURS:
                if colour in text:
                    self.add(
                        "structural",
                        name,
                        "lock-hygiene",
                        "is locked and still carries a %s review span; green is unwrapped and the "
                        "question and answer pairs are deleted at lock, so fix by clearing the review "
                        "ink before locking" % colour,
                    )
            footers = [line.strip() for line in lines if line.strip().startswith(LOCK_GLYPH)]
            if footers and not footer_re.match(footers[-1]):
                self.add(
                    "structural",
                    name,
                    "lock-hygiene",
                    "the lock footer reads %r and names no version and date; a lock footer states "
                    "the locked version and the date it was locked, in the wording review-kit's "
                    "lock procedure gives it" % (footers[-1],),
                )

    def check_rendering(self):
        names = list(self.spec_names) + ([self.acceptance_name] if self.acceptance_name else [])
        for name in names:
            text = self.texts.get(name) if name in self.texts else self.acceptance_text
            for index, line in enumerate(text.split("\n")):
                number = index + 1
                stripped = line.strip()
                if stripped.startswith("> [!"):
                    self.add(
                        "structural",
                        name,
                        "rendering",
                        "line %d opens a callout block wrapper, which the review regime forbids for "
                        "marking; fix by using an inline span instead" % number,
                    )
                if "<div" in line:
                    self.add(
                        "structural",
                        name,
                        "rendering",
                        "line %d carries a div wrapper, and markdown inside a div does not render; "
                        "fix by deleting the wrapper" % number,
                    )
                if stripped.startswith("|") and not stripped.endswith("|"):
                    self.add(
                        "structural",
                        name,
                        "rendering",
                        "line %d is a hard wrapped table row; one logical line is one physical line, "
                        "so fix by joining the row" % number,
                    )
                for span in re.finditer(r"<span[^>]*>(.*?)</span>", line):
                    inner = span.group(1)
                    if "<" in inner or ">" in inner:
                        self.add(
                            "structural",
                            name,
                            "rendering",
                            "line %d holds an unescaped angle bracket inside a span, which swallows "
                            "the surrounding text; fix by writing &lt; and &gt;" % number,
                        )
                    if MD_LINK_RE.search(inner):
                        self.add(
                            "structural",
                            name,
                            "rendering",
                            "line %d holds a markdown link inside a span, which does not render as a "
                            "link; fix by moving the link outside the span" % number,
                        )

    def run_harvests(self):
        for harvest in self.cfg.clause_harvests:
            name = harvest.get("name")
            path = resolve_path(self.cfg.root, harvest.get("path", ""))
            pattern = compile_regex(harvest.get("pattern", ""), "the clause harvest %s" % name)
            if not path.is_file():
                self.add(
                    "structural",
                    name,
                    "clause-harvest",
                    "the harvest source at %s is missing; fix by restoring the document, or by "
                    "removing the harvest from the config" % harvest.get("path"),
                )
                self.harvests[name] = []
                continue
            text = read_text(path)
            found = [m.group(1) if m.groups() else m.group(0) for m in pattern.finditer(text)]
            seen = set()
            unique = []
            for item in found:
                if item in seen:
                    self.add(
                        "structural",
                        name,
                        "clause-harvest",
                        "the harvest found %s twice in %s; a clause identifier is unique, so fix by "
                        "renumbering the duplicate" % (item, harvest.get("path")),
                    )
                else:
                    seen.add(item)
                    unique.append(item)
            self.harvests[name] = unique

    # ---- budget and lint

    def spec_stats(self):
        stats = {}
        for name in self.spec_names:
            bullets = [b for b in self.bullets if b.file == name]
            words = word_count(self.texts[name])
            journeys = sorted(set(j for b in bullets for j in b.journeys))
            stats[name] = {
                "words": words,
                "pages": int(math.ceil(words / float(self.cfg.budget["words_per_page"]))) if words else 0,
                "requirements": len(bullets),
                "journeys": journeys,
                "journey_fan": len(journeys),
                "constraints": sum(1 for b in bullets if b.constraint),
                # The whole file count, because that is the number contract.py lock
                # demands be restated. The bullet scoped count is reported beside it.
                "action_glyphs": self.texts[name].count(self.cfg.action_glyph)
                if self.cfg.action_glyph
                else 0,
                "action_glyphs_in_requirements": sum(b.glyphs for b in bullets),
            }
        return stats

    def check_budgets(self):
        budget = self.cfg.budget
        low, high = budget["requirements_per_spec"]
        stats = self.spec_stats()
        for name in self.spec_names:
            info = stats[name]
            if info["requirements"] == 0:
                continue
            if info["requirements"] < low or info["requirements"] > high:
                self.add(
                    "budget",
                    name,
                    "requirements-per-spec",
                    "states %d requirements and the band is %d to %d; a document over the band is a "
                    "component that should split, one under it is a section of a sibling"
                    % (info["requirements"], low, high),
                )
            if info["journey_fan"] >= budget["journey_fan_suspect_at"]:
                self.add(
                    "budget",
                    name,
                    "journey-fan",
                    "reaches %d journeys and the suspect threshold is %d; a component that touches "
                    "most days is usually two components"
                    % (info["journey_fan"], budget["journey_fan_suspect_at"]),
                )
        maximum = budget["words_per_requirement"]["max"]
        median_band = budget["words_per_requirement"]["median"]
        for bullet in sorted(self.bullets, key=lambda b: id_sort_key(b.identifier)):
            if bullet.words > maximum:
                self.add(
                    "budget",
                    bullet.identifier,
                    "words-per-requirement-max",
                    "%s line %d runs to %d words and the maximum is %d; split it into one testable "
                    "proposition per clause before lock"
                    % (bullet.file, bullet.line, bullet.words, maximum),
                )
        lengths = sorted(b.words for b in self.bullets)
        if lengths:
            middle = lengths[len(lengths) // 2] if len(lengths) % 2 else (
                (lengths[len(lengths) // 2 - 1] + lengths[len(lengths) // 2]) / 2.0
            )
            if middle > median_band:
                self.add(
                    "budget",
                    self.cfg.contract_dir_label,
                    "words-per-requirement-median",
                    "the median requirement runs to %g words and the band is %d; the set is packing "
                    "expectations into paragraphs" % (middle, median_band),
                )
        if self.acceptance_text is not None:
            allowance = budget["acceptance_base_words"] + budget["words_per_journey"] * len(self.journeys)
            words = word_count(self.acceptance_text)
            if words > allowance:
                self.add(
                    "budget",
                    self.acceptance_name,
                    "acceptance-doc-words",
                    "runs to %d words and its derived budget for %d journeys is %d; trim a checkbox "
                    "or drop a journey" % (words, len(self.journeys), allowance),
                )

    def check_lints(self):
        for bullet in sorted(self.bullets, key=lambda b: id_sort_key(b.identifier)):
            seams = bullet.text.count(" and ")
            if seams >= 4 or bullet.words >= 90:
                self.add(
                    "lint",
                    bullet.identifier,
                    "seam-count",
                    "%s line %d carries %d conjunction seams across %d words; ask whether a build "
                    "could hold one half and break the other, and split if it could"
                    % (bullet.file, bullet.line, seams, bullet.words),
                )
            if self.cfg.action_glyph and bullet.glyphs == 0:
                lowered = bullet.text.lower()
                for phrase in AUTOMATION_VOCABULARY:
                    if phrase in lowered:
                        self.add(
                            "lint",
                            bullet.identifier,
                            "automation-without-glyph",
                            '%s line %d says "%s" and carries no action glyph; mark it if a person '
                            "does not trigger it at that moment, and leave it bare if the sentence "
                            "states a standing property"
                            % (bullet.file, bullet.line, phrase),
                        )
                        break
        names = list(self.spec_names) + ([self.acceptance_name] if self.acceptance_name else [])
        for name in names:
            text = self.texts.get(name) if name in self.texts else self.acceptance_text
            for index, line in enumerate(text.split("\n")):
                # Strip the blockquote marker before the list marker, or a quoted
                # bullet ("> - text") reads as a spaced hyphen between two words and
                # the lint fires on markup rather than on punctuation.
                body = re.sub(r"^\s*>+\s?", "", line)
                body = re.sub(r"^\s*[-*+]\s+(\[[ xX]\]\s+)?", "", body)
                if re.search(r"[—–]", body) or re.search(r"(?<=\S) -{1,2} (?=\S)", body):
                    self.add(
                        "lint",
                        name,
                        "dash-punctuation",
                        "line %d uses a dash as punctuation; replace it with a comma, a colon, a "
                        "semicolon, a period, or a pair of parentheses" % (index + 1),
                    )
        if self.owners:
            constraints = sum(1 for b in self.owners.values() if b.constraint)
            density = constraints / float(len(self.owners))
            if density > 0.05:
                self.add(
                    "lint",
                    self.cfg.contract_dir_label,
                    "constraint-density",
                    "%d of %d requirements are standing constraints (%.1f percent); every one of them "
                    "is a promise nobody can watch being kept, so the tag stays scarce"
                    % (constraints, len(self.owners), density * 100.0),
                )

    # ---- results

    def blocking(self):
        if self.cfg.strictness == "report":
            return []
        if self.cfg.strictness == "warn":
            return [f for f in self.findings if f.cls == "structural"]
        # A lint never blocks on its own at any strictness. A dash used as punctuation
        # is worth printing and is not worth refusing a build over.
        return [f for f in self.findings if f.cls in ("structural", "budget")]

    def status(self):
        # The verdict and the blocking decision are separate questions. A contract with
        # a structural finding is not complete, whatever strictness the project runs at;
        # saying COMPLETE while a declared identifier is missing is the exact lie this
        # gate exists to remove, and every greenfield project starts at "report".
        if self.blocking():
            return "BLOCKED"
        if any(f.cls == "structural" for f in self.findings):
            return "INCOMPLETE"
        return "COMPLETE"

    def counts(self):
        inherited = {}
        for entry in self.registry.requirements.values():
            if entry.get("source"):
                inherited[entry["source"]] = inherited.get(entry["source"], 0) + 1
        locked = sum(
            1
            for code, info in self.registry.components.items()
            if info.get("file") in self.registry.locks
        )
        drafted = sum(
            1
            for code, info in self.registry.components.items()
            if info.get("file") in self.spec_names
        )
        return {
            "requirements": len(self.owners),
            "journeys": len(self.journeys),
            "components": {
                "declared": len(self.registry.components),
                "drafted": drafted,
                "locked": locked,
            },
            "standing_constraints": sum(1 for b in self.owners.values() if b.constraint),
            "inherited": dict(sorted(inherited.items())),
            "born": sum(1 for e in self.registry.requirements.values() if not e.get("source")),
            "skipped_checks": sorted(set(self.skipped)),
        }

    def rows(self):
        rows = []
        for bullet in self.bullets:
            entry = self.registry.requirements.get(bullet.identifier) or {}
            source = entry.get("source")
            declared = self.registry.source_by_name.get(source) if source else None
            rows.append(
                {
                    "id": bullet.identifier,
                    "source_id": entry.get("key") if source else None,
                    "source": source,
                    "disposition": (declared or {}).get("disposition", "RETAINED") if source else "NEW",
                    "origin": (declared or {}).get("origin", "an inherited contract")
                    if source
                    else "this project",
                    "file": bullet.file,
                    "line": bullet.line,
                    "journeys": bullet.journeys,
                    "constraint": bullet.constraint,
                    "words": bullet.words,
                    "action_glyphs": bullet.glyphs,
                }
            )
        for journey in self.journeys:
            source_key = None
            for key, target in self.registry.journeys.items():
                if target == journey:
                    source_key = key
                    break
            rows.append(
                {
                    "id": journey,
                    "source_id": source_key,
                    "source": None,
                    "disposition": "JOURNEY",
                    "origin": "the acceptance contract",
                    "file": self.acceptance_name,
                    "line": self.journey_lines.get(journey, 0),
                    "journeys": [journey],
                    "constraint": False,
                    "words": 0,
                    "action_glyphs": 0,
                }
            )
        return rows

    def artifact(self):
        stats = self.spec_stats()
        documents = []
        for name in self.spec_names:
            info = stats[name]
            documents.append(
                {
                    "file": name,
                    "kind": "specification",
                    "words": info["words"],
                    "pages": info["pages"],
                    "requirements": info["requirements"],
                    "journey_fan": info["journey_fan"],
                    "action_glyphs": info["action_glyphs"],
                    "locked": name in self.registry.locks,
                }
            )
        if self.acceptance_text is not None:
            words = word_count(self.acceptance_text)
            documents.append(
                {
                    "file": self.acceptance_name,
                    "kind": "acceptance",
                    "words": words,
                    "pages": int(math.ceil(words / float(self.cfg.budget["words_per_page"]))),
                    "requirements": 0,
                    "journey_fan": len(self.journeys),
                    "action_glyphs": 0,
                    "locked": self.acceptance_name in self.registry.locks,
                }
            )
        digests = {}
        for name in self.spec_names:
            digests[name] = sha256_of(self.cfg.contract_dir / name)
        if self.acceptance_name:
            digests[self.acceptance_name] = sha256_of(self.cfg.contract_dir / self.acceptance_name)
        findings = sorted(self.findings, key=lambda f: f.sort_key())
        return {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "generated_by": "dev-process-kit contract.py",
            "engine_version": ENGINE_VERSION,
            "project": self.cfg.project,
            "id_scheme": self.cfg.id_scheme(),
            "strictness": self.cfg.strictness,
            "status": self.status(),
            "counts": self.counts(),
            "suppressed": sorted(
                self.suppressed, key=lambda s: (s["check"], s["subject"])
            ),
            "documents": documents,
            "sha256": dict(sorted(digests.items())),
            "locked_baselines": [
                {
                    "name": b.get("name"),
                    "path": b.get("path"),
                    "version": b.get("version", ""),
                    "sha256": b.get("sha256"),
                }
                for b in self.cfg.locked_baselines
            ],
            "clause_harvests": dict(sorted(self.harvests.items())),
            "actions": {
                "glyph": self.cfg.action_glyph,
                "occurrences": sum(stats[n]["action_glyphs"] for n in self.spec_names),
                "in_requirements": sum(b.glyphs for b in self.bullets),
                "by_file": dict(
                    sorted(
                        (n, stats[n]["action_glyphs"]) for n in self.spec_names if stats[n]["action_glyphs"]
                    )
                ),
                "by_id": dict(
                    sorted(
                        (b.identifier, b.glyphs) for b in self.bullets if b.glyphs
                    )
                ),
            },
            "proving": {"status": "RESERVED"},
            "problems": [f.as_dict() for f in findings],
            "rows": self.rows(),
        }


# ----------------------------------------------------------------- reporting


def print_report(gate, stream=None):
    stream = stream or sys.stdout
    status = gate.status()
    stream.write("contract: %s  (%s)\n" % (status, gate.cfg.contract_dir_label))
    findings = sorted(gate.findings, key=lambda f: f.sort_key())
    if findings:
        stream.write("\n")
        width_subject = max(len(str(f.subject)) for f in findings)
        width_check = max(len(f.check) for f in findings)
        for number, finding in enumerate(findings, start=1):
            stream.write(
                "  %d. %-10s %-*s  %-*s  %s\n"
                % (
                    number,
                    finding.cls,
                    width_subject,
                    finding.subject,
                    width_check,
                    finding.check,
                    finding.message,
                )
            )
        tally = {}
        for finding in findings:
            tally[finding.cls] = tally.get(finding.cls, 0) + 1
        stream.write(
            "\n%s\n"
            % ", ".join("%d %s" % (tally[c], c) for c in ("structural", "budget", "lint") if c in tally)
        )
        if gate.cfg.strictness == "report":
            stream.write(
                'strictness is "report", so nothing blocks and the exit code stays 0. The verdict '
                'above still reads INCOMPLETE while a structural finding stands. Move strictness to '
                '"warn" at the first lock.\n'
            )
    if gate.suppressed:
        stream.write(
            "\n%d finding(s) suppressed by an allow entry:\n" % len(gate.suppressed)
        )
        for item in gate.suppressed:
            stream.write(
                "  - %s on %s: %s\n" % (item["check"], item["subject"], item["reason"])
            )
    stream.write("\n%s\n" % dump_json(gate.counts()).rstrip())


def status_line(gate):
    counts = gate.counts()
    unlocked = sum(1 for name in gate.spec_names if name not in gate.registry.locks)
    if gate.acceptance_name and gate.acceptance_name not in gate.registry.locks:
        unlocked += 1
    parts = [
        "%d requirements" % counts["requirements"],
        "%d journeys" % counts["journeys"],
        "%d components (%d locked)" % (counts["components"]["declared"], counts["components"]["locked"]),
        "%d constraints" % counts["standing_constraints"],
        "gate %s" % gate.status(),
        "%d documents unlocked" % unlocked,
    ]
    return " · ".join(parts)


# ----------------------------------------------------------------- the verbs


def verb_build(args):
    cfg = load_config(args.config)
    gate = Gate(cfg)
    artifact = gate.artifact()
    write_atomic(cfg.output_path, dump_json(artifact))
    print_report(gate)
    return 1 if gate.blocking() else 0


def verb_check(args):
    cfg = load_config(args.config)
    gate = Gate(cfg)
    artifact = gate.artifact()
    wanted = dump_json(artifact)
    if cfg.output_path.is_file():
        committed = read_text(cfg.output_path)
    else:
        committed = None
    if committed != wanted:
        gate.add(
            "structural",
            cfg.output_path.name,
            "stale-artifact",
            "the committed crosswalk is %s; a stale artifact is a record of a run nobody made, so "
            "fix by running contract.py build and committing the result"
            % ("missing" if committed is None else "not what this contract generates"),
        )
        artifact = gate.artifact()
    if args.json:
        sys.stdout.write(dump_json(artifact))
    else:
        print_report(gate)
    return 1 if gate.blocking() else 0


def verb_status(args):
    cfg = load_config(args.config)
    gate = Gate(cfg)
    sys.stdout.write(status_line(gate) + "\n")
    return 0


def verb_init(args):
    root = Path(args.directory or Path.cwd()).expanduser().resolve()
    config_path = root / "contract.config.json"
    contract_dir = resolve_path(root, args.contract_dir)
    registry_path = contract_dir / "machine-readable" / "id-map.json"
    readme_path = contract_dir / "README.md"
    proving_dir = resolve_path(root, args.proving_dir)

    existing = [p for p in (config_path, registry_path) if p.exists()]
    if existing and not args.force:
        raise EngineError(
            "refusing to overwrite %s; pass --force only when you mean to replace it"
            % ", ".join(str(p) for p in existing)
        )

    config = json.loads(dump_json(DEFAULT_CONFIG))
    config["project"] = args.project or root.name
    config["contract_dir"] = args.contract_dir
    config["requirement"]["prefix"] = args.requirement_prefix
    config["requirement"]["component"] = args.component_pattern
    config["requirement"]["digits"] = args.digits
    config["journey"]["prefix"] = args.journey_prefix
    config["action_glyph"] = args.action_glyph or ""

    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "machine-readable").mkdir(parents=True, exist_ok=True)
    proving_dir.mkdir(parents=True, exist_ok=True)

    written = []
    write_atomic(config_path, dump_json(config))
    written.append(config_path)
    save_registry(registry_path, seed_registry(args.adopted or ""))
    written.append(registry_path)

    if not readme_path.exists() or args.force:
        template = PLUGIN_ROOT / "templates" / "contract-readme-template.md"
        if template.is_file():
            body = read_text(template)
        else:
            body = FRONT_DOOR_STUB.format(
                project=config["project"],
                example=("%s-XX-%s" % (args.requirement_prefix, "0" * (args.digits - 1) + "1")),
                journey=args.journey_prefix,
            )
        write_atomic(readme_path, body)
        written.append(readme_path)

    proving_readme = proving_dir / "README.md"
    if not proving_readme.exists() or args.force:
        write_atomic(proving_readme, PROVING_STUB)
        written.append(proving_readme)

    for path in written:
        try:
            shown = path.relative_to(root)
        except ValueError:
            shown = path
        sys.stdout.write("created %s\n" % shown)
    sys.stdout.write(
        "\nThe day census comes before the component split, and no identifier is minted until both "
        "are approved.\n"
    )
    return 0


def verb_mint(args):
    cfg = load_config(args.config)
    registry = load_registry(cfg.registry_path)
    data = registry.raw
    component = args.component
    if registry.components and component not in registry.components:
        raise EngineError(
            "component %s is not declared in %s; register it with its file before minting into it"
            % (component, cfg.registry_path)
        )
    taken = set()
    for target in list(registry.requirements) + list(registry.withdrawn):
        if component_of(target) == component:
            match = re.search(r"([0-9]+)\s*$", target)
            if match:
                taken.add(int(match.group(1)))
    minted = []
    number = max(taken) if taken else 0
    for _ in range(args.count):
        number += 1
        while number in taken:
            number += 1
        taken.add(number)
        minted.append(
            "%s-%s-%s" % (cfg.req_prefix, component, str(number).zfill(cfg.req_digits))
        )
    data.setdefault("requirements", {})
    for identifier in minted:
        data["requirements"][identifier] = {
            "new": identifier,
            "source": None,
            "frozen_at": None,
            "home": None,
        }
        if args.note:
            data["requirements"][identifier]["note"] = args.note
    save_registry(cfg.registry_path, data)
    for identifier in minted:
        sys.stdout.write(identifier + "\n")
    return 0


def verb_retire(args):
    cfg = load_config(args.config)
    registry = load_registry(cfg.registry_path)
    identifier = args.identifier
    entry = registry.requirements.get(identifier)
    if entry is None:
        raise EngineError("%s is not in the registry at %s" % (identifier, cfg.registry_path))
    gate = Gate(cfg)
    if identifier in gate.owners:
        bullet = gate.owners[identifier]
        sys.stderr.write(
            "%s is still stated by %s line %d. Remove the bullet in a review round first, then "
            "retire the number.\n" % (identifier, bullet.file, bullet.line)
        )
        return 1
    data = registry.raw
    data.setdefault("withdrawn", {})
    data["withdrawn"][identifier] = {"reason": args.reason, "withdrawn_at": args.at or None}
    data["requirements"].pop(entry["key"], None)
    save_registry(cfg.registry_path, data)
    sys.stdout.write("%s retired and its number burned\n" % identifier)
    return 0


def verb_freeze(args):
    cfg = load_config(args.config)
    gate = Gate(cfg)
    name = Path(args.spec).name
    if name not in gate.spec_names and name != gate.acceptance_name:
        raise EngineError("%s is not part of the contract folder %s" % (name, cfg.contract_dir))
    data = gate.registry.raw
    frozen = 0
    for identifier, bullet in gate.owners.items():
        if bullet.file != name:
            continue
        entry = gate.registry.requirements.get(identifier)
        if entry is None:
            continue
        record = data["requirements"].get(entry["key"])
        if not isinstance(record, dict):
            record = {"new": identifier}
            data["requirements"][entry["key"]] = record
        record["frozen_at"] = args.at or "frozen"
        record["frozen_file"] = name
        frozen += 1
    save_registry(cfg.registry_path, data)
    sys.stdout.write(
        "%d identifiers in %s stabilised. Freezing stops the numbering moving; it does not claim "
        "approval.\n" % (frozen, name)
    )
    return 0


def verb_lock(args):
    cfg = load_config(args.config)
    if cfg.strictness == "report":
        sys.stderr.write(
            'strictness is "report", so the gate blocks nothing and a lock would assert more than '
            'the gate proved. Move strictness to "warn" or "fail" in %s, then lock.\n' % cfg.path
        )
        return 1
    gate = Gate(cfg)
    if gate.blocking():
        print_report(gate, sys.stderr)
        sys.stderr.write("\nthe contract is blocked, so nothing is locked\n")
        return 1
    name = Path(args.spec).name
    path = cfg.contract_dir / name
    if not path.is_file():
        raise EngineError("no document at %s" % path)
    text = read_text(path)
    lines = text.split("\n")
    version_line = lines[2].strip() if len(lines) > 2 else ""
    if not version_line.startswith("**%s**" % args.version):
        sys.stderr.write(
            "line 3 of %s reads %r and the lock is for %s. Complete the review round first: bump "
            "the version, strip the review ink, add the lock glyph and the lock footer.\n"
            % (name, version_line, args.version)
        )
        return 1
    if LOCK_GLYPH not in version_line:
        sys.stderr.write(
            "line 3 of %s carries no lock glyph. Add it, together with the lock footer, then lock.\n"
            % name
        )
        return 1
    expected_footer = cfg.lock_footer.format(version=args.version, date=args.date)
    if not any(line.strip() == expected_footer for line in lines):
        sys.stderr.write(
            "%s carries no lock footer reading %r. Add it as the last line, then lock.\n"
            % (name, expected_footer)
        )
        return 1
    if cfg.action_glyph:
        counted = text.count(cfg.action_glyph)
        if args.actions is None:
            sys.stderr.write(
                "%s carries %d occurrences of the action glyph. Restate the count with --actions %d "
                "so the governable set cannot change by accident.\n" % (name, counted, counted)
            )
            return 1
        if args.actions != counted:
            sys.stderr.write(
                "%s carries %d occurrences of the action glyph and the lock restates %d. The "
                "governable set changed; confirm it on purpose or repair the document.\n"
                % (name, counted, args.actions)
            )
            return 1
    data = gate.registry.raw
    frozen = 0
    for identifier, bullet in gate.owners.items():
        if bullet.file != name:
            continue
        entry = gate.registry.requirements.get(identifier)
        if entry is None:
            continue
        record = data["requirements"].get(entry["key"])
        if not isinstance(record, dict):
            record = {"new": identifier}
            data["requirements"][entry["key"]] = record
        record["frozen_at"] = "%s (%s)" % (args.version, args.date)
        record["frozen_file"] = name
        frozen += 1
    data.setdefault("locks", {})
    data["locks"][name] = {
        "version": args.version,
        "date": args.date,
        "sha256": sha256_of(path),
    }
    if cfg.action_glyph:
        data["locks"][name]["action_glyphs"] = args.actions
    save_registry(cfg.registry_path, data)
    write_atomic(cfg.output_path, dump_json(Gate(cfg).artifact()))
    sys.stdout.write(
        "%s locked at %s (%s); %d identifiers frozen; the crosswalk was regenerated\n"
        % (name, args.version, args.date, frozen)
    )
    return 0


def verb_acquire(args):
    cfg = load_config(args.config)
    path = resolve_path(cfg.root, args.doc)
    if not path.is_file():
        raise EngineError("no document at %s" % path)
    text = read_text(path)
    if args.census:
        if not args.pattern:
            raise EngineError("a census needs --pattern with exactly one capturing group")
        pattern = compile_regex(args.pattern, "the census pattern")
        found = []
        seen = set()
        for match in pattern.finditer(text):
            item = match.group(1) if match.groups() else match.group(0)
            if item not in seen:
                seen.add(item)
                found.append(item)
        sys.stdout.write("%d clauses in %s\n" % (len(found), args.doc))
        packed = 0
        for line in text.split("\n"):
            hit = pattern.search(line)
            if hit is None:
                continue
            seams = line.count(" and ")
            if seams >= 4:
                packed += 1
                sys.stdout.write(
                    "  %s carries %d conjunction seams, so expect a split\n"
                    % (hit.group(1) if hit.groups() else hit.group(0), seams)
                )
        sys.stdout.write(
            "%d of %d clauses look packed. The approved number is a split estimate, not a clause "
            "count.\n" % (packed, len(found))
        )
        return 0

    compile_regex(args.marker, "the source marker")
    registry = load_registry(cfg.registry_path)
    data = registry.raw
    data.setdefault("sources", [])
    for source in data["sources"]:
        if source.get("name") == args.source:
            raise EngineError("the registry already declares a source named %s" % args.source)
        if source.get("marker") == args.marker:
            raise EngineError(
                "the marker %r already belongs to source %s; every source carries its own marker"
                % (args.marker, source.get("name"))
            )
    data["sources"].append(
        {
            "name": args.source,
            "marker": args.marker,
            "disposition": args.disposition,
            "origin": args.origin,
            "expected_requirements": args.expect,
            "expected_journeys": None,
            "baseline": {"path": args.doc, "sha256": sha256_of(path)},
        }
    )
    save_registry(cfg.registry_path, data)
    sys.stdout.write(
        "source %s registered with marker %r and its document pinned at %s\n"
        % (args.source, args.marker, sha256_of(path))
    )
    return 0


def verb_selftest(args):
    test_file = PLUGIN_ROOT / "tests" / "test_contract_gate.py"
    if not test_file.is_file():
        raise EngineError("no self test at %s" % test_file)
    spec = importlib.util.spec_from_file_location("contract_gate_selftest", test_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["contract_gate_selftest"] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


FRONT_DOOR_STUB = """# {project} Tier 1 contract

**v0.1** · contract front door

This folder is the whole product contract. The specifications say what the product
does; one Definition of Done says what must be proven working before release.
Nothing else is Tier 1. If a promise is not in these documents, the product does not
make it.

## Read in this order

1. This front door.
2. `definition-of-done.md`.
3. The specifications, in file order.

## Components

| Code | Component | Essence |
|---|---|---|
| | | |

## How to read a requirement line

Every identifier names its kind and its home. `{example}` is a requirement living in
the component whose code sits in the middle; the tag after it, such as `({journey}-01)`,
names the Definition of Done journey that proves it. `(constraint)` marks a standing
rule verified by the engineering gate and the product owner rather than by an
operator journey. A marker after an identifier records that the clause descends from
a prior locked contract; the mapping lives in `machine-readable/id-map.json`, never
in the prose.

## House rules

Requirement identifiers are immutable once locked, and a burned number is never
reused. Every requirement traces to a journey or is a declared standing constraint.
The generated crosswalk in `machine-readable/` accounts for every identifier and
fails the build if one goes missing.
"""

PROVING_STUB = """# The proving layer, reserved

This directory is named and empty. It will hold one staging page per acceptance
journey, the seeded fixture corpus, the golden documents, and the interface contracts
and mockups.

The unit here is the file, never the row. Fourteen staging pages cannot become
fourteen hundred placeholder rows, because the schema has no row.

It is empty because the contract process above has been run end to end and this has
not. A plugin that ships an unproven layer beside a proven one teaches its reader
that neither is load bearing.
"""


# ----------------------------------------------------------------- command line


def build_parser():
    parser = argparse.ArgumentParser(
        prog="contract.py",
        description="The Tier 1 contract gate. It starts from the declared registry, not from the prose.",
    )
    sub = parser.add_subparsers(dest="verb")

    init = sub.add_parser("init", help="stand up a contract folder, a config, and an empty registry")
    init.add_argument("--directory", default=None, help="the project root (default: the working directory)")
    init.add_argument("--contract-dir", default="docs/specs/tier-1")
    init.add_argument("--proving-dir", default="docs/specs/tier-2/proving")
    init.add_argument("--requirement-prefix", default="UR")
    init.add_argument("--journey-prefix", default="DJ")
    init.add_argument("--component-pattern", default="[A-Z]{2}")
    init.add_argument("--digits", type=int, default=2)
    init.add_argument("--action-glyph", default="")
    init.add_argument("--project", default=None)
    init.add_argument("--adopted", default="", help="the adoption date, YYYY-MM-DD")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=verb_init)

    build = sub.add_parser("build", help="run every check and write the crosswalk")
    build.add_argument("--config", default=None)
    build.set_defaults(func=verb_build)

    check = sub.add_parser("check", help="run every check, write nothing, and fail on a stale artifact")
    check.add_argument("--config", default=None)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=verb_check)

    status = sub.add_parser("status", help="one line summary, always exits 0")
    status.add_argument("--config", default=None)
    status.set_defaults(func=verb_status)

    mint = sub.add_parser("mint", help="take the next free numbers at the end of a component range")
    mint.add_argument("component")
    mint.add_argument("--count", type=int, default=1)
    mint.add_argument("--note", default=None)
    mint.add_argument("--config", default=None)
    mint.set_defaults(func=verb_mint)

    retire = sub.add_parser("retire", help="withdraw an identifier and burn its number")
    retire.add_argument("identifier")
    retire.add_argument("--reason", required=True)
    retire.add_argument("--at", default=None, help="the version and date the withdrawal takes effect")
    retire.add_argument("--config", default=None)
    retire.set_defaults(func=verb_retire)

    freeze = sub.add_parser("freeze", help="stabilise a document's identifiers without claiming approval")
    freeze.add_argument("spec")
    freeze.add_argument("--at", default=None)
    freeze.add_argument("--config", default=None)
    freeze.set_defaults(func=verb_freeze)

    lock = sub.add_parser("lock", help="record a lock: verify the document, freeze its identifiers, pin its bytes")
    lock.add_argument("spec")
    lock.add_argument("--version", required=True)
    lock.add_argument("--date", required=True)
    lock.add_argument("--actions", type=int, default=None)
    lock.add_argument("--config", default=None)
    lock.set_defaults(func=verb_lock)

    acquire = sub.add_parser("acquire", help="declare an inherited source, or census a document before adopting it")
    acquire.add_argument("source")
    acquire.add_argument("--doc", required=True)
    acquire.add_argument("--marker", default=LEGACY_MARKER)
    acquire.add_argument("--pattern", default=None, help="census only, one capturing group")
    acquire.add_argument("--census", action="store_true")
    acquire.add_argument("--disposition", default="RETAINED")
    acquire.add_argument("--origin", default="a prior locked contract")
    acquire.add_argument("--expect", type=int, default=None)
    acquire.add_argument("--config", default=None)
    acquire.set_defaults(func=verb_acquire)

    selftest = sub.add_parser("selftest", help="run the bundled unit tests")
    selftest.set_defaults(func=verb_selftest)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--version":
        sys.stdout.write("contract.py %s\n" % ENGINE_VERSION)
        return 0
    if argv and argv[0] == "--word-count":
        if len(argv) < 2:
            sys.stderr.write("--word-count needs a file\n")
            return 2
        path = Path(argv[1]).expanduser()
        if not path.is_file():
            sys.stderr.write("no file at %s\n" % path)
            return 2
        sys.stdout.write("%d\n" % word_count(read_text(path)))
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except EngineError as exc:
        sys.stderr.write("contract: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
