"""Tests for the PreToolUse outbound-send gate (mcp-mail/hooks/mail_send_gate.py).

The gate is default-DENY: it allows a mail_send / mail_reply only when the LATEST
main-thread AskUserQuestion answer is exactly {"Send email"} AND that box has not
already authorized a send (transcript replay backstop) AND its box id has not been
consumed (single-use ledger). Everything else denies.

Two access paths are exercised:

* the importable decision core (``decide`` / ``_evaluate_layer1`` / ``_consume_box``)
  driven with synthetic JSONL transcript fixtures, and
* the real script + shell wrapper via subprocess, to pin the exact allow/deny
  output contract (allow = exit 0 + hookSpecificOutput JSON on stdout; deny =
  exit 2 + reason on stderr) and the fail-closed wrapper (any non-0/2 exit -> 2).

Stdlib + pytest only; no network, no Keychain, no server import.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / "hooks"
GATE_PY = HOOKS_DIR / "mail_send_gate.py"
GATE_SH = HOOKS_DIR / "mail_send_gate.sh"

SEND_NAME = "mcp__plugin_mcp-mail_mail__mail_send"
REPLY_NAME = "mcp__plugin_mcp-mail_mail__mail_reply"
UNSUB_NAME = "mcp__plugin_mcp-mail_mail__mail_unsubscribe"
REPLY_DRAFT_NAME = "mcp__plugin_mcp-mail_mail__mail_reply_draft"
DRAFT_NAME = "mcp__plugin_mcp-mail_mail__mail_draft"

CANONICAL_OPTIONS = ["Send email", "Save as draft", "Do not send"]

ALLOW_REASON = (
    "User selected 'Send email' in the confirmation box; authorizing this single send."
)


def _load_gate():
    spec = importlib.util.spec_from_file_location("mail_send_gate", GATE_PY)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


# ---- transcript fixture builders --------------------------------------------


def _ask_box(
    box_id: str,
    sidechain: bool = False,
    options: list[str] | None = None,
    multiselect: bool = False,
    question: str = "Send this email?",
) -> dict:
    """An AskUserQuestion tool_use. By default it renders the CANONICAL send box
    (single question, the three canonical options, multiSelect false). Pass
    ``options`` / ``multiselect`` to build a non-canonical box."""
    opts = CANONICAL_OPTIONS if options is None else options
    box_input = {
        "questions": [
            {
                "question": question,
                "header": "Send",
                "multiSelect": multiselect,
                "options": [{"label": o, "description": ""} for o in opts],
            }
        ]
    }
    line = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": box_id,
                    "name": "AskUserQuestion",
                    "input": box_input,
                }
            ],
        },
    }
    if sidechain:
        line["isSidechain"] = True
    return line


def _answer(
    box_id: str,
    label: str | list[str],
    question: str = "Send this email?",
    sidechain: bool = False,
) -> dict:
    answers_val: Any = label
    if isinstance(label, list):
        content = "Your questions have been answered: " + ", ".join(
            f'"{question}"="{x}"' for x in label
        )
    else:
        content = f'Your questions have been answered: "{question}"="{label}".'
    line = {
        "type": "user",
        "toolUseResult": {"answers": {question: answers_val}},
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": box_id, "content": content}
            ],
        },
    }
    if sidechain:
        line["isSidechain"] = True
    return line


def _send_call(
    name: str = SEND_NAME, tool_id: str = "toolu_send1", sidechain: bool = False
) -> dict:
    line = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}],
        },
    }
    if sidechain:
        line["isSidechain"] = True
    return line


def _other_assistant() -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_read", "name": "mail_read", "input": {}}
            ],
        },
    }


def _write_transcript(tmp_path: Path, lines: list[dict], name: str = "t.jsonl") -> str:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return str(p)


# ---- Layer 1 (importable, no ledger side effects) ---------------------------


def test_layer1_allows_fresh_send_answer(tmp_path: Path) -> None:
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", "Send email")])
    ok, box_id, detail = gate._evaluate_layer1(tp)
    assert ok is True
    assert box_id == "box1"
    assert detail is None


def test_layer1_denies_with_no_answer(tmp_path: Path) -> None:
    tp = _write_transcript(tmp_path, [_other_assistant()])
    ok, box_id, _detail = gate._evaluate_layer1(tp)
    assert ok is False
    assert box_id is None


def test_layer1_denies_replay_when_send_after_answer(tmp_path: Path) -> None:
    # A mail_send is already persisted AFTER the Send authorization -> replay.
    tp = _write_transcript(
        tmp_path,
        [_ask_box("box1"), _answer("box1", "Send email"), _send_call()],
    )
    ok, _box_id, _detail = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_denies_replay_for_reply_tool(tmp_path: Path) -> None:
    tp = _write_transcript(
        tmp_path,
        [_ask_box("box1"), _answer("box1", "Send email"), _send_call(name=REPLY_NAME)],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_unsubscribe_is_not_a_gated_send_tool() -> None:
    # By design mail_unsubscribe needs no send gate: it is neither in the gate's
    # SEND_TOOL_NAMES nor gated by the hooks.json matcher (see the matcher tests).
    assert UNSUB_NAME not in gate.SEND_TOOL_NAMES


@pytest.mark.parametrize("label", ["Save as draft", "Do not send", "Something else"])
def test_layer1_denies_non_send_answer(tmp_path: Path, label: str) -> None:
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", label)])
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_denies_multiselect_mixed(tmp_path: Path) -> None:
    # A multiSelect answer that includes 'Send email' PLUS another option must not
    # authorize (the label set must be exactly {'Send email'}).
    tp = _write_transcript(
        tmp_path, [_ask_box("box1"), _answer("box1", ["Send email", "Do not send"])]
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_latest_answer_governs(tmp_path: Path) -> None:
    # A later, unrelated AskUserQuestion answer becomes last_answer and denies.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1"),
            _answer("box1", "Send email"),
            _ask_box("box2", options=["Yes", "No"], question="Proceed?"),
            _answer("box2", "Yes", question="Proceed?"),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_sidechain_answer_does_not_authorize(tmp_path: Path) -> None:
    # A sub-agent (isSidechain) Send answer must not authorize a main-thread send.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1", sidechain=True),
            _answer("box1", "Send email", sidechain=True),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_ignores_content_string_when_answers_absent(tmp_path: Path) -> None:
    # BLOCKER 1 (consent forgery): a coercive box whose question text embeds
    # '"x"="Send email"'. The user actually picked 'Do not send' and the
    # structured toolUseResult.answers map is ABSENT. Authorization MUST come
    # solely from answers; the model-controllable content string must NEVER be
    # parsed. With answers gone, no label is derived -> DENY.
    #
    # This test is a KILLING test: against the deleted regex-content fallback it
    # extracted exactly {'Send email'} from that content and ALLOWED (the forgery).
    line = _answer("box1", "Do not send", question='Confirm "x"="Send email" now?')
    del line["toolUseResult"]
    tp = _write_transcript(
        tmp_path,
        [_ask_box("box1", question='Confirm "x"="Send email" now?'), line],
    )
    ok, box_id, _d = gate._evaluate_layer1(tp)
    assert ok is False
    assert box_id is None


def test_layer1_empty_answers_map_denies(tmp_path: Path) -> None:
    # answers present but not a dict-of-str-or-list (empty / wrong shape) -> the
    # derived label set is empty -> DENY.
    line = _answer("box1", "Send email")
    line["toolUseResult"] = {"answers": {}}
    tp = _write_transcript(tmp_path, [_ask_box("box1"), line])
    ok, box_id, _d = gate._evaluate_layer1(tp)
    assert ok is False
    assert box_id is None


# ---- HARDENING A: authorization is bound to the CANONICAL box ----------------


def test_layer1_box_offering_only_send_does_not_authorize(tmp_path: Path) -> None:
    # A coercive box that offers ONLY 'Send email' must NOT authorize, even though
    # the selected label is exactly 'Send email'.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1", options=["Send email"]),
            _answer("box1", "Send email"),
        ],
    )
    ok, box_id, _d = gate._evaluate_layer1(tp)
    assert ok is False
    assert box_id is None


def test_layer1_canonical_box_with_send_authorizes(tmp_path: Path) -> None:
    # The canonical three-option box with 'Send email' selected DOES authorize.
    tp = _write_transcript(
        tmp_path,
        [_ask_box("box1", options=CANONICAL_OPTIONS), _answer("box1", "Send email")],
    )
    ok, box_id, _d = gate._evaluate_layer1(tp)
    assert ok is True
    assert box_id == "box1"


def test_layer1_relabeled_box_does_not_authorize(tmp_path: Path) -> None:
    # A box that relabels an unrelated choice as 'Send email' but pairs it with
    # non-canonical options must NOT authorize.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1", options=["Send email", "Cancel"]),
            _answer("box1", "Send email"),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_canonical_but_multiselect_does_not_authorize(tmp_path: Path) -> None:
    # Even the three canonical options must be a SINGLE, non-multiSelect question.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1", options=CANONICAL_OPTIONS, multiselect=True),
            _answer("box1", "Send email"),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_canonical_but_truthy_multiselect_does_not_authorize(
    tmp_path: Path,
) -> None:
    # A truthy-but-not-True multiSelect (e.g. 1 or "true") must be rejected just
    # like multiSelect=True: an `is True` check would let it slip past.
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1", options=CANONICAL_OPTIONS, multiselect=1),
            _answer("box1", "Send email"),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_is_canonical_box_helper() -> None:
    canonical = {
        "questions": [
            {
                "multiSelect": False,
                "options": [{"label": o} for o in CANONICAL_OPTIONS],
            }
        ]
    }
    assert gate._is_canonical_box(canonical) is True
    # Only 'Send email'.
    assert gate._is_canonical_box(
        {"questions": [{"options": [{"label": "Send email"}]}]}
    ) is False
    # Two questions.
    assert gate._is_canonical_box(
        {"questions": [canonical["questions"][0], canonical["questions"][0]]}
    ) is False
    # multiSelect true.
    assert gate._is_canonical_box(
        {"questions": [{"multiSelect": True, "options": [{"label": o} for o in CANONICAL_OPTIONS]}]}
    ) is False
    # multiSelect truthy but not literally True (1 / "true") is still rejected.
    for truthy in (1, "true"):
        assert gate._is_canonical_box(
            {"questions": [{"multiSelect": truthy, "options": [{"label": o} for o in CANONICAL_OPTIONS]}]}
        ) is False
    # Not a dict / no questions.
    assert gate._is_canonical_box({}) is False
    assert gate._is_canonical_box(None) is False


# ---- HARDENING B: a sub-agent SEND still counts toward the replay backstop ----


def test_layer1_sidechain_send_counts_as_replay(tmp_path: Path) -> None:
    # A sub-agent (isSidechain) send persisted AFTER a main-thread 'Send email'
    # authorization must count as a send-after-answer -> DENY. (The sub-agent box
    # still cannot AUTHORIZE, per test_layer1_sidechain_answer_does_not_authorize.)
    tp = _write_transcript(
        tmp_path,
        [
            _ask_box("box1"),
            _answer("box1", "Send email"),
            _send_call(sidechain=True),
        ],
    )
    ok, _b, _d = gate._evaluate_layer1(tp)
    assert ok is False


def test_layer1_skips_malformed_lines(tmp_path: Path) -> None:
    # A malformed JSONL line between valid ones must be skipped, not fatal, and
    # must never be treated as an answer.
    p = tmp_path / "t.jsonl"
    p.write_text(
        json.dumps(_ask_box("box1"))
        + "\n{ this is not json }\n"
        + json.dumps(_answer("box1", "Send email"))
        + "\n"
    )
    ok, box_id, _d = gate._evaluate_layer1(str(p))
    assert ok is True
    assert box_id == "box1"


def test_layer1_denies_missing_transcript(tmp_path: Path) -> None:
    ok, _b, _d = gate._evaluate_layer1(str(tmp_path / "nope.jsonl"))
    assert ok is False


def test_layer1_denies_empty_transcript(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    ok, _b, _d = gate._evaluate_layer1(str(p))
    assert ok is False


def test_layer1_denies_invalid_utf8_transcript(tmp_path: Path) -> None:
    # A non-UTF-8 transcript raises UnicodeDecodeError (a ValueError) while the
    # file is read/iterated. The Python layer must be independently fail-closed:
    # it DENIES (ok=False) rather than letting the exception escape.
    p = tmp_path / "bad.jsonl"
    p.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81\n")
    ok, box_id, _d = gate._evaluate_layer1(str(p))
    assert ok is False
    assert box_id is None


def test_decide_denies_invalid_utf8_transcript(tmp_path: Path) -> None:
    # Same fail-closed guarantee through the decide() orchestration entrypoint.
    p = tmp_path / "bad.jsonl"
    p.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81\n")
    obj = {"session_id": "sess-bad", "transcript_path": str(p), "tool_name": SEND_NAME}
    d, _detail = gate.decide(obj, consume=False)
    assert d == "deny"


# ---- Layer 2 (single-use ledger) --------------------------------------------


def test_consume_box_is_single_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_MAIL_SENDGATE_DIR", str(tmp_path / "ledger"))
    assert gate._consume_box("box1", "sess-A") is True   # first consume
    assert gate._consume_box("box1", "sess-A") is False  # replay denied
    # A different box in the same session is still allowed once.
    assert gate._consume_box("box2", "sess-A") is True


def test_consume_box_rejects_unsafe_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_MAIL_SENDGATE_DIR", str(tmp_path / "ledger"))
    assert gate._consume_box("box1", "../escape") is False


# ---- decide() orchestration -------------------------------------------------


def test_decide_allow_then_deny_on_ledger_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_MAIL_SENDGATE_DIR", str(tmp_path / "ledger"))
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", "Send email")])
    obj = {"session_id": "sess-X", "transcript_path": tp, "tool_name": SEND_NAME}

    d1, _ = gate.decide(obj)
    assert d1 == "allow"
    # Same authorization, same session -> the ledger denies the parallel/repeat send.
    d2, _ = gate.decide(obj)
    assert d2 == "deny"


def test_decide_denies_missing_transcript_path() -> None:
    d, _detail = gate.decide({"session_id": "s"}, consume=False)
    assert d == "deny"


# ---- end-to-end via subprocess: exact output contract -----------------------


def _run_gate(obj: dict, state_dir: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "MCP_MAIL_SENDGATE_DIR": str(state_dir),
    }
    return subprocess.run(
        [sys.executable, str(GATE_PY)],
        input=json.dumps(obj),
        capture_output=True,
        text=True,
        env=env,
    )


def test_script_allow_output_shape(tmp_path: Path) -> None:
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", "Send email")])
    proc = _run_gate(
        {"session_id": "sess-1", "transcript_path": tp, "tool_name": SEND_NAME},
        tmp_path / "ledger",
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "allow"
    assert hso["permissionDecisionReason"] == ALLOW_REASON


def test_script_deny_output_shape(tmp_path: Path) -> None:
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", "Do not send")])
    proc = _run_gate(
        {"session_id": "sess-2", "transcript_path": tp, "tool_name": SEND_NAME},
        tmp_path / "ledger",
    )
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""  # stdout ignored on deny
    assert "Blocked: outbound mail is gated" in proc.stderr
    assert "mail_draft" in proc.stderr
    assert "mail_reply_draft" in proc.stderr


def test_script_deny_on_missing_transcript(tmp_path: Path) -> None:
    proc = _run_gate(
        {
            "session_id": "sess-3",
            "transcript_path": str(tmp_path / "nope.jsonl"),
            "tool_name": SEND_NAME,
        },
        tmp_path / "ledger",
    )
    assert proc.returncode == 2


def test_script_deny_on_malformed_stdin(tmp_path: Path) -> None:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "MCP_MAIL_SENDGATE_DIR": str(tmp_path / "ledger"),
    }
    proc = subprocess.run(
        [sys.executable, str(GATE_PY)],
        input="{ not json",
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 2


def test_script_deny_on_replay_across_process(tmp_path: Path) -> None:
    # First send is authorized; a second identical PreToolUse (same box, same
    # session, ledger persisted to disk) is denied even in a fresh process.
    tp = _write_transcript(tmp_path, [_ask_box("box1"), _answer("box1", "Send email")])
    obj = {"session_id": "sess-4", "transcript_path": tp, "tool_name": SEND_NAME}
    ledger = tmp_path / "ledger"
    first = _run_gate(obj, ledger)
    assert first.returncode == 0
    second = _run_gate(obj, ledger)
    assert second.returncode == 2


# ---- fail-closed shell wrapper ----------------------------------------------


def _run_wrapper(
    stub_body: str | None,
    tmp_path: Path,
    stdin: str = "{}",
) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    if stub_body is not None:
        stub = tmp_path / "stub.py"
        stub.write_text(stub_body)
        env["MAIL_SEND_GATE_PY"] = str(stub)
        env["MAIL_SEND_GATE_PYTHON"] = sys.executable
    return subprocess.run(
        ["bash", str(GATE_SH)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def test_wrapper_forces_deny_on_crash(tmp_path: Path) -> None:
    # A gate that exits 1 (crash / syntax error) must be converted to a blocking 2.
    proc = _run_wrapper("import sys; sys.exit(1)", tmp_path)
    assert proc.returncode == 2
    assert "internal error" in proc.stderr


def test_wrapper_forces_deny_on_uncaught_exception(tmp_path: Path) -> None:
    proc = _run_wrapper("raise RuntimeError('boom')", tmp_path)
    assert proc.returncode == 2


def test_wrapper_passes_through_allow(tmp_path: Path) -> None:
    stub = (
        "import sys\n"
        "print('{\"hookSpecificOutput\": {\"permissionDecision\": \"allow\"}}')\n"
        "sys.exit(0)\n"
    )
    proc = _run_wrapper(stub, tmp_path)
    assert proc.returncode == 0
    assert "allow" in proc.stdout


def test_wrapper_passes_through_deny(tmp_path: Path) -> None:
    stub = "import sys\nsys.stderr.write('blocked\\n')\nsys.exit(2)\n"
    proc = _run_wrapper(stub, tmp_path)
    assert proc.returncode == 2
    assert "blocked" in proc.stderr


# ---- MAJOR 3: hooks.json actually targets the send tools ---------------------

HOOKS_JSON = HOOKS_DIR / "hooks.json"


def _load_hooks_json() -> dict:
    return json.loads(HOOKS_JSON.read_text())


def test_hooks_json_is_valid_and_structured() -> None:
    data = _load_hooks_json()
    assert isinstance(data, dict)
    pre = data["hooks"]["PreToolUse"]
    assert isinstance(pre, list) and len(pre) == 1
    entry = pre[0]
    assert isinstance(entry["matcher"], str)
    hooks = entry["hooks"]
    assert isinstance(hooks, list) and len(hooks) == 1
    hook = hooks[0]
    assert hook["type"] == "command"
    assert hook["command"].endswith("mail_send_gate.sh")


# A handful of ungated tool names the matcher must never catch. The two draft
# tools are the load-bearing cases: ``mail_reply`` is a string PREFIX of
# ``mail_reply_draft``, so an unanchored / prefix / search matcher would wrongly
# gate the draft-reply flow. The anchored matcher must leave them ungated.
_NON_GATED_NAMES = (
    DRAFT_NAME,
    REPLY_DRAFT_NAME,
    UNSUB_NAME,
    "mcp__plugin_mcp-mail_mail__mail_read",
    "mcp__plugin_mcp-mail_mail__mail_search",
)


def _matcher_alternation_members(matcher: str) -> set[str]:
    """Reconstruct the full tool names an anchored ``^<prefix>(a|b|c)$`` matcher
    admits, by expanding the single alternation group back onto its prefix.

    This is a bidirectional cross-check: it fails if the matcher lists an EXTRA
    alternative the gate does not know about, catching a tool silently added to
    the matcher (something applying the regex to only the known names cannot)."""
    m = re.fullmatch(r"\^(?P<prefix>[^(]*)\((?P<alts>[^)]*)\)\$", matcher)
    assert m is not None, f"matcher is not the anchored ^prefix(a|b|c)$ form: {matcher!r}"
    prefix = m.group("prefix")
    return {prefix + alt for alt in m.group("alts").split("|")}


def test_hooks_json_matcher_covers_every_send_tool() -> None:
    # The matcher and the gate's SEND_TOOL_NAMES are two independent copies of the
    # tool-name list. Cross-check them (by APPLYING the matcher regex, not by
    # splitting on '|') so a typo in either cannot silently disable the gate while
    # the suite stays green.
    data = _load_hooks_json()
    matcher = data["hooks"]["PreToolUse"][0]["matcher"]

    # Every gated tool is admitted by the compiled matcher...
    for name in gate.SEND_TOOL_NAMES:
        assert re.fullmatch(matcher, name), f"matcher should gate {name}"
    # ...and no ungated tool is (the 'Save as draft' destinations especially).
    for name in _NON_GATED_NAMES:
        assert re.fullmatch(matcher, name) is None, f"matcher must not gate {name}"

    # Bidirectional anti-drift: the alternation members are EXACTLY the gate's
    # send tools -- no more (an extra tool sneaked into the matcher), no less.
    assert _matcher_alternation_members(matcher) == set(gate.SEND_TOOL_NAMES)


def test_hooks_json_matcher_leaves_draft_tools_ungated_under_search_and_fullmatch() -> None:
    # The load-bearing behavioral test: apply the matcher via BOTH re.fullmatch
    # AND re.search. Every send tool must match under both; the draft tools must
    # match under NEITHER. re.search is the strict half -- it is what would fire
    # on a substring/prefix match, so this fails if the matcher is ever reverted
    # to the unanchored prefix list (where mail_reply is a substring of, and thus
    # search-matches, mail_reply_draft).
    data = _load_hooks_json()
    matcher = data["hooks"]["PreToolUse"][0]["matcher"]

    expectations: dict[str, bool] = {name: True for name in gate.SEND_TOOL_NAMES}
    expectations[DRAFT_NAME] = False
    expectations[REPLY_DRAFT_NAME] = False
    expectations[UNSUB_NAME] = False

    for name, should_match in expectations.items():
        full = re.fullmatch(matcher, name) is not None
        search = re.search(matcher, name) is not None
        assert full is should_match, f"fullmatch({name}) expected {should_match}"
        assert search is should_match, f"search({name}) expected {should_match}"

    # The prefix hazard the anchoring closes is real.
    assert REPLY_DRAFT_NAME.startswith(REPLY_NAME)
