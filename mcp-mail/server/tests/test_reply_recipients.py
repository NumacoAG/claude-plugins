"""Tests for adding NEW cc/bcc recipients to a threaded ``mail_reply``.

``mail_reply`` grew explicit ``cc`` / ``bcc`` on top of ``reply_all``. Those
extra addresses are ADDED to the reply (they don't replace reply_all's copy of
the original recipients), deduped case-insensitively, and never include the
account itself or the original sender (who is already the primary To). Threading
must be preserved in every adapter.

Everything here is offline: each adapter's HTTP client / SMTP / message-fetch is
stubbed, so no network or Keychain is touched. Three layers are pinned:

1. Graph -- the FULL recipient set is composed client-side (mirroring Gmail /
   IMAP) and the reply ACTION body carries toRecipients / ccRecipients /
   bccRecipients on the single-shot, threading ``/reply`` endpoint. Graph's
   ``/replyAll`` action would REPLACE the collection with extras-only and drop
   the original cc, so it is never used.
2. Gmail + IMAP -- the built MIME's Cc/Bcc headers carry the extras, deduped,
   with self + the To excluded, threading headers intact.
3. The server handler -- cc/bcc flow through to ``adapter.reply`` and the reply
   signature step still runs.
"""

from __future__ import annotations

import asyncio
import base64
import email
import json
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters._recipients import _extra_recipients
from mcp_mail.adapters.gmail import GmailAdapter
from mcp_mail.adapters.graph import GraphAdapter
from mcp_mail.adapters.imap import IMAPAdapter


# ---- shared stubs -----------------------------------------------------------


class _Acct:
    id = "acct"
    address = "me@example.com"
    auto_write = True
    mailbox = None


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any] | None = None) -> None:
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


# ---- Graph ------------------------------------------------------------------


class _GraphClient:
    """Answers the read() GET with a fixed message and records reply POSTs.

    The original message can carry its own To / Cc recipients so tests can
    assert reply-all composes the FULL recipient set client-side (rather than
    letting Graph's /replyAll action overwrite it with extras only).
    """

    def __init__(
        self,
        sender: str,
        to: list[str] | None = None,
        cc: list[str] | None = None,
    ) -> None:
        self._sender = sender
        self._to = to or []
        self._cc = cc or []
        self.gets: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.gets.append({"url": url})
        return _FakeResponse(
            {
                "id": "m1",
                "from": {"emailAddress": {"address": self._sender}},
                "toRecipients": [
                    {"emailAddress": {"address": a}} for a in self._to
                ],
                "ccRecipients": [
                    {"emailAddress": {"address": a}} for a in self._cc
                ],
                "hasAttachments": False,
                "body": {"contentType": "html", "content": "orig"},
            }
        )

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({})


@pytest.fixture
def make_graph(monkeypatch: pytest.MonkeyPatch):
    def _make(
        sender: str = "sender@example.org",
        to: list[str] | None = None,
        cc: list[str] | None = None,
    ) -> tuple[GraphAdapter, _GraphClient]:
        adapter = GraphAdapter(_Acct())  # type: ignore[arg-type]
        client = _GraphClient(sender, to=to, cc=cc)
        adapter._client = client  # type: ignore[assignment]
        monkeypatch.setattr(
            adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer t"}
        )
        return adapter, client

    return _make


def _graph_addrs(recipients: list[dict]) -> list[str]:
    return [r["emailAddress"]["address"] for r in recipients]


def test_graph_reply_adds_cc_bcc_and_excludes_self_and_sender(make_graph) -> None:
    adapter, client = make_graph(sender="sender@example.org")

    adapter.reply(
        "m1",
        body_html="<p>hi</p>",
        reply_all=False,
        cc=["Colleague@Example.com", "me@EXAMPLE.com", "SENDER@example.org", "colleague@example.com"],
        bcc=["boss@example.com"],
    )

    # read() was consulted to learn the original sender.
    assert client.gets, "expected read() GET to resolve the original sender"

    post = client.posts[-1]
    # Threaded /reply action, NOT /replyAll (reply_all was False).
    assert post["url"].endswith("/reply")
    assert not post["url"].endswith("/replyAll")

    message = post["json"]["message"]
    # Self + original sender dropped; duplicate collapsed case-insensitively.
    assert _graph_addrs(message["ccRecipients"]) == ["Colleague@Example.com"]
    assert _graph_addrs(message["bccRecipients"]) == ["boss@example.com"]


def test_graph_reply_all_still_threads_and_adds_cc(make_graph) -> None:
    # Original HAS existing To + Cc. reply-all must preserve every original CC
    # recipient AND add the new extra. Graph's /replyAll action REPLACES the
    # recipient collection, so an extras-only body would silently drop the
    # original CCs — this test fails against that (pre-fix) behaviour and passes
    # only once the full set is composed client-side on the /reply action.
    adapter, client = make_graph(
        sender="sender@example.org",
        to=["boss@example.com"],
        cc=["watcher1@example.com", "watcher2@example.com"],
    )

    adapter.reply("m1", body_html="<p>hi</p>", reply_all=True, cc=["new@example.com"])

    post = client.posts[-1]
    # Threads via the single-shot /reply action (NOT /replyAll).
    assert post["url"].endswith("/reply")
    assert not post["url"].endswith("/replyAll")

    message = post["json"]["message"]
    # To resolves to the original sender.
    assert _graph_addrs(message["toRecipients"]) == ["sender@example.org"]

    cc_addrs = [a.lower() for a in _graph_addrs(message["ccRecipients"])]
    # BOTH original CC recipients are preserved (nothing dropped) ...
    assert "watcher1@example.com" in cc_addrs
    assert "watcher2@example.com" in cc_addrs
    # ... the original To is folded into cc by reply-all ...
    assert "boss@example.com" in cc_addrs
    # ... and the new extra is added.
    assert "new@example.com" in cc_addrs
    # No original CC recipient is dropped or duplicated; self never appears.
    assert cc_addrs.count("watcher1@example.com") == 1
    assert cc_addrs.count("watcher2@example.com") == 1
    assert "me@example.com" not in cc_addrs


def test_graph_reply_all_with_bcc_dedupes_against_cc(make_graph) -> None:
    # reply-all resolves watcher into cc; passing it again as bcc must not
    # produce a duplicate blind copy. A genuinely new bcc still lands.
    adapter, client = make_graph(
        sender="sender@example.org",
        to=["boss@example.com"],
        cc=["watcher@example.com"],
    )

    adapter.reply(
        "m1",
        body_html="<p>hi</p>",
        reply_all=True,
        bcc=["secret@example.com", "watcher@EXAMPLE.com"],
    )

    message = client.posts[-1]["json"]["message"]
    bcc_addrs = [a.lower() for a in _graph_addrs(message["bccRecipients"])]
    assert bcc_addrs == ["secret@example.com"]
    # watcher stayed in cc, not bcc.
    cc_addrs = [a.lower() for a in _graph_addrs(message["ccRecipients"])]
    assert "watcher@example.com" in cc_addrs


def test_graph_reply_normalizes_display_name_extra(make_graph) -> None:
    # A display-name-form extra whose address is the account itself must be
    # dropped; a display-name-form extra whose address duplicates the original
    # sender must be dropped; only genuinely new addresses survive, stored as
    # their bare form.
    adapter, client = make_graph(sender="sender@example.org")

    adapter.reply(
        "m1",
        body_html="<p>hi</p>",
        reply_all=False,
        cc=[
            "Me <me@example.com>",  # self, display-name form -> dropped
            "The Sender <sender@example.org>",  # original sender -> dropped
            "Carol <carol@example.net>",  # new -> kept as bare
            "carol@example.net",  # dup of Carol -> dropped
        ],
    )

    message = client.posts[-1]["json"]["message"]
    assert _graph_addrs(message["ccRecipients"]) == ["carol@example.net"]


def test_graph_reply_without_extras_omits_recipient_keys(make_graph) -> None:
    adapter, client = make_graph()

    adapter.reply("m1", body_html="<p>hi</p>", reply_all=False)

    # No extras -> no read() and no cc/bcc keys added to the action body.
    assert client.gets == []
    message = client.posts[-1]["json"]["message"]
    assert "ccRecipients" not in message
    assert "bccRecipients" not in message


# ---- Gmail ------------------------------------------------------------------


class _SendClient:
    """Records the send POST (raw MIME + threadId)."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({"id": "sent"})


def _gmail_original(subject: str, frm: str, to: str, cc: str, msgid: str) -> dict:
    return {
        "threadId": "T1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": frm},
                {"name": "To", "value": to},
                {"name": "Cc", "value": cc},
                {"name": "Message-ID", "value": msgid},
            ]
        },
    }


@pytest.fixture
def make_gmail(monkeypatch: pytest.MonkeyPatch):
    def _make(original: dict) -> tuple[GmailAdapter, _SendClient]:
        adapter = GmailAdapter(_Acct())  # type: ignore[arg-type]
        client = _SendClient()
        adapter._client = client  # type: ignore[assignment]
        monkeypatch.setattr(
            adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer t"}
        )
        monkeypatch.setattr(adapter, "_get_message", lambda *a, **k: original)
        return adapter, client

    return _make


def _mime_from_post(post: dict) -> email.message.Message:
    raw = base64.urlsafe_b64decode(post["json"]["raw"])
    return email.message_from_bytes(raw)


def _header_addrs(msg: email.message.Message, name: str) -> list[str]:
    value = msg[name]
    if not value:
        return []
    return [a.strip() for a in value.split(",") if a.strip()]


def test_gmail_reply_adds_cc_bcc_dedupes_and_excludes_self(make_gmail) -> None:
    original = _gmail_original(
        subject="Hello",
        frm="Sender <sender@example.org>",
        to="me@example.com",
        cc="",
        msgid="<orig@example.org>",
    )
    adapter, client = make_gmail(original)

    adapter.reply(
        "m1",
        body_text="thanks",
        reply_all=False,
        cc=["Colleague@example.com", "me@example.com", "colleague@EXAMPLE.com", "sender@example.org"],
        bcc=["boss@example.com", "boss@example.com"],
    )

    post = client.posts[-1]
    # Threading preserved via threadId.
    assert post["json"]["threadId"] == "T1"

    msg = _mime_from_post(post)
    cc_addrs = _header_addrs(msg, "Cc")
    bcc_addrs = _header_addrs(msg, "Bcc")

    assert cc_addrs == ["Colleague@example.com"]  # self + sender + dup dropped
    assert bcc_addrs == ["boss@example.com"]  # dup collapsed
    # In-Reply-To threading header carried.
    assert msg["In-Reply-To"] == "<orig@example.org>"


def test_gmail_reply_all_plus_extra_cc_merges_both(make_gmail) -> None:
    original = _gmail_original(
        subject="Hello",
        frm="Sender <sender@example.org>",
        to="me@example.com, teammate@example.com",
        cc="watcher@example.com",
        msgid="<orig@example.org>",
    )
    adapter, client = make_gmail(original)

    adapter.reply(
        "m1",
        body_text="thanks",
        reply_all=True,
        # watcher already comes from reply_all; new@example.com is genuinely new;
        # me@example.com is self and must drop.
        cc=["new@example.com", "watcher@EXAMPLE.com", "me@example.com"],
    )

    msg = _mime_from_post(client.posts[-1])
    cc_addrs = [a.lower() for a in _header_addrs(msg, "Cc")]

    # reply_all's teammate + watcher, plus the new address; watcher not doubled;
    # self excluded.
    assert "teammate@example.com" in cc_addrs
    assert "watcher@example.com" in cc_addrs
    assert "new@example.com" in cc_addrs
    assert "me@example.com" not in cc_addrs
    assert cc_addrs.count("watcher@example.com") == 1


def test_gmail_reply_all_dedupes_address_in_both_to_and_cc(make_gmail) -> None:
    # dup@example.com is present in BOTH the original To and Cc. reply_all must list
    # it EXACTLY ONCE in the reply Cc (the base set is now routed through the
    # shared helper, which collapses the self-duplicate). An extra cc is still
    # added; self and the original sender are excluded.
    original = _gmail_original(
        subject="Hello",
        frm="Sender <sender@example.org>",
        to="dup@example.com, me@example.com",
        cc="dup@example.com, watcher@example.com",
        msgid="<orig@example.org>",
    )
    adapter, client = make_gmail(original)

    adapter.reply(
        "m1",
        body_text="thanks",
        reply_all=True,
        cc=["extra@example.com"],
    )

    msg = _mime_from_post(client.posts[-1])
    cc_addrs = [a.lower() for a in _header_addrs(msg, "Cc")]

    # The address in both To and Cc appears exactly once.
    assert cc_addrs.count("dup@example.com") == 1
    # Other original recipient preserved; the extra cc added.
    assert "watcher@example.com" in cc_addrs
    assert "extra@example.com" in cc_addrs
    # Self + original sender excluded.
    assert "me@example.com" not in cc_addrs
    assert "sender@example.org" not in cc_addrs


# ---- IMAP -------------------------------------------------------------------


class _FakeSMTP:
    def __init__(self, sink: list) -> None:
        self._sink = sink

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def send_message(self, msg) -> None:
        self._sink.append(msg)


@pytest.fixture
def make_imap(monkeypatch: pytest.MonkeyPatch):
    def _make(original: dict) -> tuple[IMAPAdapter, list]:
        adapter = IMAPAdapter(_Acct())  # type: ignore[arg-type]
        sent: list = []
        monkeypatch.setattr(adapter, "read", lambda message_id: original)
        monkeypatch.setattr(adapter, "_smtp", lambda: _FakeSMTP(sent))
        monkeypatch.setattr(adapter, "_append_to_sent", lambda msg: None)
        return adapter, sent

    return _make


def test_imap_reply_adds_cc_bcc_dedupes_and_excludes_self(make_imap) -> None:
    original = {
        "subject": "Hello",
        "from": "sender@example.org",
        "to": ["me@example.com"],
        "cc": [],
        "internetMessageId": "<orig@example.org>",
    }
    adapter, sent = make_imap(original)

    adapter.reply(
        "m1",
        body_text="thanks",
        reply_all=False,
        cc=["Colleague@example.com", "me@example.com", "colleague@EXAMPLE.com", "sender@example.org"],
        bcc=["boss@example.com", "BOSS@example.com"],
    )

    assert len(sent) == 1
    msg = sent[0]
    cc_addrs = [a.strip() for a in (msg["Cc"] or "").split(",") if a.strip()]
    bcc_addrs = [a.strip() for a in (msg["Bcc"] or "").split(",") if a.strip()]

    assert cc_addrs == ["Colleague@example.com"]
    assert bcc_addrs == ["boss@example.com"]
    assert msg["In-Reply-To"] == "<orig@example.org>"


def test_imap_reply_all_plus_extra_cc_merges_both(make_imap) -> None:
    original = {
        "subject": "Hello",
        "from": "sender@example.org",
        "to": ["me@example.com", "teammate@example.com"],
        "cc": ["watcher@example.com"],
        "internetMessageId": "<orig@example.org>",
    }
    adapter, sent = make_imap(original)

    adapter.reply(
        "m1",
        body_text="thanks",
        reply_all=True,
        cc=["new@example.com", "watcher@EXAMPLE.com", "me@example.com"],
    )

    msg = sent[0]
    cc_addrs = [a.strip().lower() for a in (msg["Cc"] or "").split(",") if a.strip()]

    assert "teammate@example.com" in cc_addrs
    assert "watcher@example.com" in cc_addrs
    assert "new@example.com" in cc_addrs
    assert "me@example.com" not in cc_addrs
    assert cc_addrs.count("watcher@example.com") == 1


def test_imap_reply_all_dedupes_address_in_both_to_and_cc(make_imap) -> None:
    # dup@example.com is present in BOTH the original To and Cc; reply_all must list
    # it exactly once. An extra cc is still added; self and the original sender
    # are excluded.
    original = {
        "subject": "Hello",
        "from": "sender@example.org",
        "to": ["dup@example.com", "me@example.com"],
        "cc": ["dup@example.com", "watcher@example.com"],
        "internetMessageId": "<orig@example.org>",
    }
    adapter, sent = make_imap(original)

    adapter.reply("m1", body_text="thanks", reply_all=True, cc=["extra@example.com"])

    msg = sent[0]
    cc_addrs = [a.strip().lower() for a in (msg["Cc"] or "").split(",") if a.strip()]

    assert cc_addrs.count("dup@example.com") == 1
    assert "watcher@example.com" in cc_addrs
    assert "extra@example.com" in cc_addrs
    assert "me@example.com" not in cc_addrs
    assert "sender@example.org" not in cc_addrs


# ---- server handler ---------------------------------------------------------


class _CapturingAdapter:
    def __init__(self) -> None:
        self.reply_kwargs: dict[str, Any] | None = None

    def reply(self, **kwargs: Any) -> None:
        self.reply_kwargs = kwargs


def _call(name: str, arguments: dict[str, Any]) -> dict:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


def test_handler_flows_cc_bcc_and_applies_reply_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (_Acct(), fake))

    captured: dict[str, Any] = {}

    def _spy_sig(acct, *, body_text, body_html, attachments, is_reply, append_signature):
        captured["is_reply"] = is_reply
        captured["append_signature"] = append_signature
        return ("SIGNED::" + (body_html or body_text or ""), attachments)

    monkeypatch.setattr(srv, "_apply_signature", _spy_sig)

    out = _call(
        "mail_reply",
        {
            "account": "acct",
            "message_id": "m1",
            "body_html": "Hi",
            "reply_all": True,
            "cc": ["colleague@example.com"],
            "bcc": ["boss@example.com"],
        },
    )

    assert out["ok"] is True
    # Signature step still runs on replies (is_reply=True).
    assert captured["is_reply"] is True
    # cc/bcc reach the adapter, and the signed body is what gets sent.
    assert fake.reply_kwargs is not None
    assert fake.reply_kwargs["cc"] == ["colleague@example.com"]
    assert fake.reply_kwargs["bcc"] == ["boss@example.com"]
    assert fake.reply_kwargs["reply_all"] is True
    assert fake.reply_kwargs["body_html"] == "SIGNED::Hi"


# ---- shared _extra_recipients helper ----------------------------------------


def test_extra_recipients_normalizes_display_name_forms() -> None:
    # Display-name form dedupes against the same bare address (kept as bare).
    assert _extra_recipients(
        ["Carol <carol@example.net>", "carol@example.net"], exclude=set()
    ) == ["carol@example.net"]

    # Display-name form of an excluded address (e.g. self) is dropped even
    # though the whole "Name <addr>" string is not itself in `exclude`.
    assert _extra_recipients(
        ["Owner <self@example.com>", "New <new@example.net>"],
        exclude={"self@example.com"},
    ) == ["new@example.net"]

    # Display-name form dedupes against a bare address already present.
    assert _extra_recipients(
        ["Dave <dave@example.net>"], exclude=set(), already={"dave@example.net"}
    ) == []

    # Case-insensitive dedupe / exclusion, order preserved.
    assert _extra_recipients(
        ["A <a@example.net>", "a@Example.net", "B <b@example.net>"],
        exclude=set(),
    ) == ["a@example.net", "b@example.net"]
