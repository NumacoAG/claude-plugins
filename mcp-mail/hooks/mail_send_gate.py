#!/usr/bin/env python3
"""PreToolUse gate for the mcp-mail plugin's outbound send tools.

Hard-blocks the outbound-send tools (``mail_send``, ``mail_reply``) unless the
user has JUST authorized this exact send by
selecting "Send email" in an AskUserQuestion box that offered exactly the three
options "Send email" / "Save as draft" / "Do not send". This is enforcement, not
instruction: the model cannot talk its way past it.

Contract (Claude Code PreToolUse hooks, verified against the docs and a live
capture):

* stdin is a single JSON object with (at least) ``session_id``,
  ``transcript_path``, ``tool_name``, ``tool_input``.
* ALLOW = exit 0 with a JSON ``hookSpecificOutput`` on stdout whose
  ``permissionDecision`` is ``"allow"`` (auto-approves, suppressing the prompt).
* DENY = exit 2 with a human-readable reason on stderr (the unambiguous block
  path: only exit 2 blocks; stdout is ignored). This blocks in every permission
  mode.
* Any OTHER nonzero exit is NON-blocking (fail-open). This script therefore only
  ever exits 0 (allow) or 2 (deny); a shell wrapper (mail_send_gate.sh) converts
  any crash / missing-interpreter exit into a blocking 2 as a second backstop.

The gate is DEFAULT-DENY: any missing/unreadable/empty/malformed transcript, any
parse ambiguity, any non-"Send email" answer, an already-consumed authorization,
or an inability to guarantee single-use all resolve to DENY.

Two independent layers cover each other's blind spots (a send is allowed only if
BOTH pass):

* Layer 1 (transcript governance): the LATEST AskUserQuestion answer in the main
  thread must be exactly {"Send email"} AND come from the canonical three-option
  box, and no send tool may already be persisted at or after that answer
  (cross-turn replay backstop, counting sub-agent sends too). The current send and
  any same-message sibling are NOT yet in the transcript at PreToolUse, so this
  never misfires on the legitimate first send.
* Layer 2 (single-use ledger): the answer's box id is consumed exactly once under
  an exclusive OS lock, so a single "Send email" click cannot authorize two
  parallel sends batched into one assistant message.

One narrow, opt-in exception (UNATTENDED SELF-SEND): ``mail_send`` (never
``mail_reply``) is allowed without the box when the account in ``tool_input``
sets ``unattended_self_send = true`` in accounts.toml, the message goes to
exactly one recipient equal to that account's own configured ``address``
(case-insensitive, bare address only), ``cc`` and ``bcc`` are absent or empty,
and the account's per local calendar day cap (default 50, overridable with
``unattended_self_send_daily_cap``) is not yet reached. Any failed condition or
any error while evaluating it means the exception does not apply and the gate
above runs unchanged; it can never turn an error into an allow.

Stdlib only; no third-party imports (``tomllib`` is stdlib on Python 3.11+; on
an older interpreter the self-send exception is simply unavailable).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time

try:  # stdlib on Python 3.11+; without it the self-send exception never applies
    import tomllib
except Exception:  # pragma: no cover - depends on the running interpreter
    tomllib = None  # type: ignore[assignment]

# ---- fully-qualified send tool names (must match the hooks.json matcher) -----

SEND_TOOL_NAMES = frozenset(
    {
        "mcp__plugin_mcp-mail_mail__mail_send",
        "mcp__plugin_mcp-mail_mail__mail_reply",
    }
)

ASK_TOOL_NAME = "AskUserQuestion"
AUTHORIZING_LABELS = frozenset({"Send email"})
# The one shape of AskUserQuestion box that may authorize a send: a single,
# non-multiSelect question whose options are EXACTLY these three labels. A box
# that offers only "Send email", relabels an unrelated choice, or bundles extra
# options cannot authorize (HARDENING A: bind the authorization to the canonical
# box, not merely to the selected label).
CANONICAL_OPTIONS = frozenset({"Send email", "Save as draft", "Do not send"})

ALLOW_REASON = (
    "User selected 'Send email' in the confirmation box; authorizing this single send."
)
DENY_REASON = (
    "Blocked: outbound mail is gated. Before any outbound send (mail_send or mail_reply) "
    "you MUST ask the user via AskUserQuestion with one question and "
    "exactly these three options: 'Send email', 'Save as draft', 'Do not send'. Proceed "
    "only after the user selects 'Send email'. For 'Save as draft' use the plugin's native "
    "draft tool (mail_draft for a new message, mail_reply_draft for a reply) instead; for "
    "'Do not send' stop."
)

_SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# ---- unattended self-send exception (opt in, mail_send only) -----------------

SELF_SEND_TOOL_NAME = "mcp__plugin_mcp-mail_mail__mail_send"
SELF_SEND_FLAG = "unattended_self_send"
SELF_SEND_CAP_KEY = "unattended_self_send_daily_cap"
SELF_SEND_DEFAULT_CAP = 50
SELF_SEND_LEDGER = "selfsend-ledger.json"
SELF_SEND_LOCK = "selfsend.lock"
# Providers that can actually send mail. localfs has no mailbox.
SELF_SEND_PROVIDERS = frozenset({"m365", "gmail", "imap"})


# ---- output helpers ---------------------------------------------------------


def _allow(reason: str = ALLOW_REASON) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.stdout.flush()
    sys.exit(0)


def _deny(detail: str | None = None) -> None:
    msg = DENY_REASON if not detail else f"{DENY_REASON} ({detail})"
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    sys.exit(2)


# ---- label extraction -------------------------------------------------------


def _labels_from_answers(answers: object) -> set[str]:
    """Collect selected option labels from a toolUseResult.answers map.

    ``answers`` maps question text -> selected label (a string for single-select,
    a list for multiSelect). Flatten list values to their string elements.
    """
    labels: set[str] = set()
    if isinstance(answers, dict):
        for v in answers.values():
            if isinstance(v, list):
                labels.update(x for x in v if isinstance(x, str))
            elif isinstance(v, str):
                labels.add(v)
    return labels


def _box_option_labels(box_input: object) -> set[str] | None:
    """Return the option label set of a single-question, non-multiSelect
    AskUserQuestion box, or None if the box is not a well-formed single question.

    This reads the ORIGINATING tool_use INPUT of the AskUserQuestion box (not any
    model-authored content string): the ``questions`` array the harness rendered.
    """
    if not isinstance(box_input, dict):
        return None
    questions = box_input.get("questions")
    if not isinstance(questions, list) or len(questions) != 1:
        return None
    q = questions[0]
    if not isinstance(q, dict):
        return None
    # Reject any truthy multiSelect value, not only the literal ``True``: a
    # transcript could carry 1 / "true" and a strict ``is True`` check would let
    # a multi-select box authorize a send.
    if q.get("multiSelect"):
        return None
    options = q.get("options")
    if not isinstance(options, list):
        return None
    labels: set[str] = set()
    for opt in options:
        if isinstance(opt, dict):
            lab = opt.get("label")
            if not isinstance(lab, str):
                return None
            labels.add(lab)
        elif isinstance(opt, str):
            labels.add(opt)
        else:
            return None
    return labels


def _is_canonical_box(box_input: object) -> bool:
    """True only for the canonical single-question send box: exactly the three
    options {'Send email','Save as draft','Do not send'}, multiSelect false."""
    return _box_option_labels(box_input) == set(CANONICAL_OPTIONS)


# ---- Layer 1: transcript governance -----------------------------------------


def _evaluate_layer1(transcript_path: str) -> tuple[bool, str | None, str | None]:
    """Scan the transcript. Return (ok, box_id, deny_detail).

    ``ok`` True only when the latest main-thread AskUserQuestion answer is exactly
    {"Send email"}, that answer's originating box is the canonical three-option box,
    and no send tool is persisted at or after it.
    """
    try:
        if not os.path.isfile(transcript_path) or os.path.getsize(transcript_path) == 0:
            return False, None, "no transcript"
    except OSError:
        return False, None, "transcript unreadable"

    id2name: dict[str, str] = {}
    # AskUserQuestion box id -> its tool_use input (the rendered questions/options).
    id2input: dict[str, object] = {}
    # Candidate answers: (line_index, box_id, labels).
    answers: list[tuple[int, str, set[str]]] = []
    send_indices: list[int] = []

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line_index, raw in enumerate(f):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except (ValueError, TypeError):
                    # Malformed line: never treat it as an answer; skip it.
                    continue
                if not isinstance(obj, dict):
                    continue

                # A sub-agent (Task) box cannot AUTHORIZE a main-thread send, so
                # its answers are excluded below. A sub-agent SEND, however, still
                # counts toward the replay backstop (HARDENING B): collect send
                # indices regardless of isSidechain.
                is_sidechain = obj.get("isSidechain") is True

                msg = obj.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                mtype = obj.get("type")

                if mtype == "assistant" and isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "tool_use":
                            tid = item.get("id")
                            tname = item.get("name")
                            if isinstance(tid, str) and isinstance(tname, str):
                                id2name[tid] = tname
                                if tname == ASK_TOOL_NAME:
                                    id2input[tid] = item.get("input")
                            if tname in SEND_TOOL_NAMES:
                                send_indices.append(line_index)

                elif mtype == "user" and isinstance(content, list):
                    if is_sidechain:
                        # Sub-agent answers never authorize a main-thread send.
                        continue
                    line_labels = _labels_from_answers(
                        obj.get("toolUseResult", {}).get("answers")
                        if isinstance(obj.get("toolUseResult"), dict)
                        else None
                    )
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") != "tool_result":
                            continue
                        box_id = item.get("tool_use_id")
                        if not isinstance(box_id, str):
                            continue
                        # Resolve only against AskUserQuestion boxes seen so far
                        # (the box always precedes its answer in the file).
                        if id2name.get(box_id) != ASK_TOOL_NAME:
                            continue
                        # Authorization is derived SOLELY from the structured
                        # toolUseResult.answers map. When answers is absent, empty,
                        # or malformed, ``line_labels`` is empty and this answer
                        # cannot satisfy the exact-{'Send email'} check below. No
                        # model-controllable free text (question/content strings)
                        # ever feeds the authorization decision.
                        answers.append((line_index, box_id, line_labels))
    except Exception:
        # Fail closed independently of the shell wrapper: any error while
        # opening / reading / iterating the transcript (an OSError, or a
        # UnicodeDecodeError from a non-UTF-8 transcript, or anything else)
        # must DENY rather than escape this layer.
        return False, None, "transcript read error"

    if not answers:
        return False, None, "no AskUserQuestion answer"

    # The latest answer (greatest line index) governs.
    last_line, box_id, labels = max(answers, key=lambda a: a[0])

    # HARDENING A: bind the authorization to the canonical box. The originating
    # AskUserQuestion box must have offered EXACTLY the three canonical options
    # (single question, multiSelect false). A coercive box that offers only
    # 'Send email' or relabels an unrelated choice cannot authorize.
    if not _is_canonical_box(id2input.get(box_id)):
        return False, None, "authorizing box is not the canonical three-option send box"

    if labels != set(AUTHORIZING_LABELS):
        return False, None, "latest answer is not exactly 'Send email'"

    # Cross-turn replay backstop: a send persisted at or after the authorizing
    # answer means this authorization was already used by an earlier turn's send.
    if any(idx >= last_line for idx in send_indices):
        return False, None, "a send already occurred after this authorization"

    return True, box_id, None


# ---- Layer 2: single-use consumption ledger ---------------------------------


def _state_dir() -> str:
    override = os.environ.get("MCP_MAIL_SENDGATE_DIR")
    if override:
        return override
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "mcp-mail", "sendgate")


def _consume_box(box_id: str, session_id: str) -> bool:
    """Consume ``box_id`` exactly once for this session under an exclusive lock.

    Returns True if it was newly consumed (allow); False if it was already
    consumed OR the ledger cannot be safely written (deny — if single-use cannot
    be guaranteed, refuse).
    """
    if not _SESSION_RE.match(session_id):
        return False
    state_dir = _state_dir()
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        return False
    lock_path = os.path.join(state_dir, f"{session_id}.lock")
    ledger_path = os.path.join(state_dir, f"{session_id}.consumed")

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return False
    try:
        # Acquire an exclusive lock with a short bound.
        acquired = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(0.05)
        if not acquired:
            return False
        try:
            consumed: set[str] = set()
            try:
                with open(ledger_path, encoding="utf-8") as f:
                    consumed = {ln.strip() for ln in f if ln.strip()}
            except FileNotFoundError:
                pass
            except OSError:
                return False
            if box_id in consumed:
                return False
            try:
                with open(ledger_path, "a", encoding="utf-8") as f:
                    f.write(box_id + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                return False
            return True
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


# ---- unattended self-send exception -----------------------------------------


def _accounts_path() -> str:
    """The accounts.toml the server reads.

    Mirrors ``mcp_mail.config.DEFAULT_CONFIG_PATH`` exactly
    (``Path.home() / ".config" / "mcp-mail" / "accounts.toml"``). The server has
    no environment override for this path, so neither does the hook: the two
    must always read the same file. ``Path.home()`` and ``expanduser("~")``
    resolve identically (``$HOME``, else the password database).
    """
    return os.path.join(os.path.expanduser("~"), ".config", "mcp-mail", "accounts.toml")


def _today() -> str:
    """The local calendar day the daily cap is counted against (ISO date)."""
    return time.strftime("%Y-%m-%d", time.localtime())


def _self_send_account(account_id: str) -> dict | None:
    """Return the single accounts.toml entry whose ``id`` is ``account_id``.

    None when tomllib is unavailable, or the id is absent or ambiguous
    (duplicated). A missing, unreadable or malformed file raises; the caller
    treats any exception as "the exception does not apply".
    """
    if tomllib is None:
        return None
    with open(_accounts_path(), "rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        return None
    entries = data.get("account")
    if not isinstance(entries, list):
        return None
    matches = [e for e in entries if isinstance(e, dict) and e.get("id") == account_id]
    if len(matches) != 1:
        return None
    return matches[0]


def _self_send_cap(entry: dict) -> int:
    """The account's daily cap: a positive integer override, else the default."""
    raw = entry.get(SELF_SEND_CAP_KEY)
    # bool is an int subclass; ``true`` must not read as a cap of 1.
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return SELF_SEND_DEFAULT_CAP


def _empty_recipients(value: object) -> bool:
    """True only for an absent / null / empty-list ``cc`` or ``bcc``."""
    return value is None or (isinstance(value, list) and len(value) == 0)


def _self_send_candidate(obj: dict) -> tuple[str, int] | None:
    """Check every static condition of the self-send exception.

    Return (account_id, daily_cap) when the call is an eligible self-send, or
    None. May raise on a broken accounts.toml; the caller guards it.
    """
    if obj.get("tool_name") != SELF_SEND_TOOL_NAME:
        return None
    tool_input = obj.get("tool_input")
    if not isinstance(tool_input, dict):
        return None

    account_id = tool_input.get("account")
    if not isinstance(account_id, str) or not account_id:
        return None

    to = tool_input.get("to")
    if not isinstance(to, list) or len(to) != 1 or not isinstance(to[0], str):
        return None
    if not _empty_recipients(tool_input.get("cc")):
        return None
    if not _empty_recipients(tool_input.get("bcc")):
        return None

    entry = _self_send_account(account_id)
    if entry is None:
        return None
    # Opt in must be the literal boolean true; a string or number does not count.
    if entry.get(SELF_SEND_FLAG) is not True:
        return None
    if entry.get("provider") not in SELF_SEND_PROVIDERS:
        return None
    # A delegate view of someone else's mailbox is never "self".
    if entry.get("mailbox"):
        return None

    address = entry.get("address")
    if not isinstance(address, str):
        return None
    own = address.strip().casefold()
    recipient = to[0].strip().casefold()
    # Bare ASCII addresses only: this rules out the display-name form and any
    # Unicode casefold collision with a different address.
    if not own or "@" not in own or not own.isascii() or not recipient.isascii():
        return None
    if recipient != own:
        return None

    return account_id, _self_send_cap(entry)


def _count_self_send(account_id: str, cap: int, *, record: bool) -> int | None:
    """Count one self-send against today's cap under an exclusive lock.

    Returns the new count (1-based) when the send fits under ``cap``, else None
    (cap reached, or the ledger cannot be safely read or written). With
    ``record`` False the cap is checked but nothing is written.
    """
    state_dir = _state_dir()
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        return None
    lock_path = os.path.join(state_dir, SELF_SEND_LOCK)
    ledger_path = os.path.join(state_dir, SELF_SEND_LEDGER)

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None
    try:
        acquired = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(0.05)
        if not acquired:
            return None
        try:
            today = _today()
            counts: dict = {}
            try:
                with open(ledger_path, encoding="utf-8") as f:
                    ledger = json.load(f)
            except FileNotFoundError:
                ledger = None
            # A corrupt ledger (bad JSON, bad shape) cannot vouch for the cap:
            # the exception stays off until the file is fixed or removed.
            if ledger is not None:
                if not isinstance(ledger, dict):
                    return None
                stored = ledger.get("counts")
                if not isinstance(stored, dict):
                    return None
                if ledger.get("date") == today:
                    counts = stored
            used = counts.get(account_id, 0)
            if not isinstance(used, int) or isinstance(used, bool) or used < 0:
                return None
            if used >= cap:
                return None
            new_count = used + 1
            if not record:
                return new_count
            updated = dict(counts)
            updated[account_id] = new_count
            tmp_path = ledger_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "counts": updated}, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, ledger_path)
            return new_count
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _self_send_exemption(obj: dict, *, record: bool = True) -> str | None:
    """Return the allow reason when the unattended self-send exception applies.

    None means "does not apply" and the normal gate decides. Every error is
    swallowed into None, so this path can only ever add an allow for a fully
    qualifying send, never turn a failure into one.
    """
    try:
        candidate = _self_send_candidate(obj)
        if candidate is None:
            return None
        account_id, cap = candidate
        count = _count_self_send(account_id, cap, record=record)
        if count is None:
            return None
        return (
            "Unattended self-send to the account's own address "
            f"({count} of {cap} today)"
        )
    except Exception:
        return None


# ---- orchestration ----------------------------------------------------------


def decide(obj: dict, *, consume: bool = True) -> tuple[str, str | None]:
    """Return ("allow", reason) or ("deny", detail) for a parsed stdin object.

    ``reason`` is None for the normal confirmation-box allow (the caller then
    uses ALLOW_REASON), and the self-send reason when that exception applied.
    ``consume`` gates the ledger writes (box consumption and the self-send
    counter); tests set it False to check the decision without side effects.
    """
    self_send_reason = _self_send_exemption(obj, record=consume)
    if self_send_reason is not None:
        return "allow", self_send_reason

    transcript_path = obj.get("transcript_path")
    session_id = obj.get("session_id")
    if not isinstance(transcript_path, str) or not transcript_path:
        return "deny", "missing transcript_path"

    ok, box_id, detail = _evaluate_layer1(transcript_path)
    if not ok or box_id is None:
        return "deny", detail

    if consume:
        if not isinstance(session_id, str) or not session_id:
            return "deny", "missing session_id"
        if not _consume_box(box_id, session_id):
            return "deny", "authorization already consumed"

    return "allow", None


def main() -> None:
    try:
        data = sys.stdin.read()
    except Exception:
        _deny("stdin unreadable")
        return
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        _deny("stdin is not JSON")
        return
    if not isinstance(obj, dict):
        _deny("stdin is not a JSON object")
        return

    decision, detail = decide(obj)
    if decision == "allow":
        _allow(detail or ALLOW_REASON)
    else:
        _deny()


if __name__ == "__main__":
    main()
