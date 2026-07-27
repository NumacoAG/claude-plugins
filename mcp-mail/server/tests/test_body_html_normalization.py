"""Tests for outgoing `body_html` hygiene (`_normalize_body_html`).

`body_html` reaches the provider verbatim as contentType=HTML, so a caller that
hands it the wrong thing ships a mail whose recipient reads the raw markup,
which is exactly how a real customer received a body of literal `<p>` tags. The
server now repairs the two caller mistakes that cause it and reports the repair.

Pinned invariants:

1. Escaped markup and nothing else (`&lt;p&gt;`) is unescaped once.
2. Real markup is NEVER rewritten, including a body that deliberately shows
   escaped tags alongside real ones; that mail is correct as written.
3. Plain text handed to the HTML parameter is escaped, newlines become `<br>`,
   and the result is wrapped in the same div `_apply_signature` uses.
4. A repair is reported to the caller as a `normalized` key on the tool result;
   an untouched body adds no key.
5. Normalization runs BEFORE the signature, so the signature is appended to
   clean HTML and is never dragged through the caller's mistake.

Everything here is offline: the adapter is a capturing stub, so no network or
Keychain is touched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.config import Signature

WRAPPER_OPEN = (
    '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;color:#1a1a1a">'
)


# ---- the helper -------------------------------------------------------------


def test_escaped_markup_is_unescaped_once() -> None:
    # The shipped bug: the caller escaped its own HTML, so the recipient saw the
    # tags as text.
    html, note = srv._normalize_body_html(
        "&lt;p&gt;Hi there,&lt;/p&gt;&lt;p&gt;Thank you.&lt;/p&gt;"
    )

    assert html == "<p>Hi there,</p><p>Thank you.</p>"
    assert note is not None
    assert "escaped" in note
    # Unescaped exactly once: a second pass over the repaired body is a no-op.
    assert srv._normalize_body_html(html) == (html, None)


def test_escaped_markup_variants_are_recognized() -> None:
    for body in (
        "&lt;br&gt;",
        "&lt;/div&gt;",
        '&lt;a href="https://example.com"&gt;link&lt;/a&gt;',
        "Text first, then &lt;br&gt; a break.",
    ):
        html, note = srv._normalize_body_html(body)
        assert note is not None, body
        assert "&lt;" not in html, body


def test_real_markup_passes_through_untouched() -> None:
    for body in (
        "<p>Hi</p>",
        "<div><br></div>",
        "</div>",  # `<` followed by `/`
        "<!-- a comment -->",  # `<` followed by `!`
        '<a href="https://example.com">link</a>',
    ):
        assert srv._normalize_body_html(body) == (body, None)


def test_mixed_real_tags_and_entities_pass_through() -> None:
    # A mail that deliberately SHOWS escaped markup to the reader, inside real
    # markup. Unescaping it would corrupt a body that is already correct.
    body = "<p>Type &lt;br&gt; for a line break.</p>"

    assert srv._normalize_body_html(body) == (body, None)


def test_plain_text_is_escaped_wrapped_and_line_broken() -> None:
    html, note = srv._normalize_body_html("Hi Max\n\nTom & Jerry <3")

    assert html == (
        WRAPPER_OPEN + "Hi Max<br><br>Tom &amp; Jerry &lt;3</div>"
    )
    assert note is not None
    assert "plain text" in note
    # The repaired body is real markup, so it is stable under a second pass.
    assert srv._normalize_body_html(html) == (html, None)


def test_none_and_empty_pass_through_without_a_note() -> None:
    assert srv._normalize_body_html(None) == (None, None)
    assert srv._normalize_body_html("") == ("", None)


# ---- end to end through the writing tools -----------------------------------


class _CapturingAdapter:
    def __init__(self) -> None:
        self.reply_kwargs: dict[str, Any] | None = None

    def reply(self, **kwargs: Any) -> None:
        self.reply_kwargs = kwargs


class _Acct:
    id = "acct"
    address = "me@example.com"
    auto_write = True
    mailbox = None

    def __init__(self, signature: Signature | None = None) -> None:
        self.signature = signature


def _call(name: str, arguments: dict[str, Any]) -> dict:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


def test_mail_reply_repairs_escaped_body_and_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (_Acct(), fake))

    out = _call(
        "mail_reply",
        {
            "account": "acct",
            "message_id": "m1",
            "body_html": "&lt;p&gt;Hi there,&lt;/p&gt;&lt;p&gt;Thank you.&lt;/p&gt;",
        },
    )

    assert out["ok"] is True
    # The adapter (and so the recipient) gets real tags, not their entities.
    assert fake.reply_kwargs is not None
    assert fake.reply_kwargs["body_html"] == "<p>Hi there,</p><p>Thank you.</p>"
    # The caller is told it passed a malformed body.
    assert "escaped" in out["normalized"]


def test_mail_reply_adds_no_note_for_a_well_formed_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (_Acct(), fake))

    out = _call(
        "mail_reply",
        {"account": "acct", "message_id": "m1", "body_html": "<p>Hi</p>"},
    )

    assert fake.reply_kwargs["body_html"] == "<p>Hi</p>"
    assert "normalized" not in out


def test_signature_is_appended_to_the_repaired_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Normalization must run FIRST. Were the order reversed, the signature's real
    # markup would make the whole body look well-formed and the caller's escaped
    # text would ship as tags.
    sig_path = tmp_path / "sig.html"
    sig_path.write_text("<div data-mcpmail-sig>-- Example Co</div>")
    acct = _Acct(Signature(html_path=sig_path, inline_images=(), on_reply=True))
    fake = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (acct, fake))

    out = _call(
        "mail_reply",
        {"account": "acct", "message_id": "m1", "body_html": "&lt;p&gt;Hi&lt;/p&gt;"},
    )

    body = fake.reply_kwargs["body_html"]
    assert body.startswith("<p>Hi</p>")
    # Signature present and intact; nothing in the message stayed escaped.
    assert "<div data-mcpmail-sig>-- Example Co</div>" in body
    assert "&lt;" not in body
    assert "normalized" in out
