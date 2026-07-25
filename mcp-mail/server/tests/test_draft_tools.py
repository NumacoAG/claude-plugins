"""Tests for the native draft-creation tools (mail_draft / mail_reply_draft).

These tools are the destination for the user's "Save as draft" choice in the
send-confirmation box. They must build the SAME payload/MIME that send() builds
(recipients, cc/bcc, signature) but write it to Drafts and NEVER send. Every test
here is offline: each adapter's HTTP client / IMAP / message-fetch is stubbed, so
no network or Keychain is touched.

Pinned invariants:

1. Graph  -- create_draft POSTs to /me/messages (createDraft) with cc/bcc and
   attachments; create_reply_draft uses /createReply + PATCH and composes the
   full recipient set. NEITHER hits /sendMail or the /reply send action.
2. Gmail  -- create_draft / create_reply_draft POST to users.drafts.create with
   the built MIME (cc/bcc headers, threading), never users.messages.send.
3. IMAP   -- create_draft / create_reply_draft APPEND the built MIME to Drafts
   with the \\Draft flag and open NO SMTP connection.
4. Server -- the mail_draft / mail_reply_draft handlers apply the account
   signature and route to create_draft / create_reply_draft (not send/reply).
"""

from __future__ import annotations

import asyncio
import base64
import email
import json
from pathlib import Path
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters.gmail import GmailAdapter
from mcp_mail.adapters.graph import GraphAdapter
from mcp_mail.adapters.imap import IMAPAdapter
from mcp_mail.config import Signature

# ---- shared stubs -----------------------------------------------------------


class _Acct:
    id = "acct"
    address = "me@example.com"
    auto_write = True
    signature = None
    mailbox = None


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any] | None = None) -> None:
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


def _write_attachment(tmp_path: Path) -> str:
    p = tmp_path / "note.txt"
    p.write_text("hello attachment")
    return str(p)


# ---- Graph ------------------------------------------------------------------


class _GraphDraftClient:
    """Records every HTTP verb the draft path issues; answers reads/creates."""

    def __init__(
        self,
        sender: str = "sender@example.org",
        to: list[str] | None = None,
        cc: list[str] | None = None,
    ) -> None:
        self._sender = sender
        self._to = to or []
        self._cc = cc or []
        self.posts: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.gets.append({"url": url})
        return _FakeResponse(
            {
                "id": "m1",
                "from": {"emailAddress": {"address": self._sender}},
                "toRecipients": [{"emailAddress": {"address": a}} for a in self._to],
                "ccRecipients": [{"emailAddress": {"address": a}} for a in self._cc],
                "hasAttachments": False,
                "body": {"contentType": "html", "content": "orig"},
            }
        )

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, "json": kwargs.get("json")})
        # createReply returns a draft resource with an id + webLink.
        if url.endswith("/createReply"):
            return _FakeResponse({"id": "draft-99", "webLink": "https://outlook/draft-99"})
        # createDraft (POST /me/messages) returns the created draft.
        return _FakeResponse(
            {"id": "draft-1", "webLink": "https://outlook/draft-1", "isDraft": True}
        )

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.patches.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({"id": "draft-99"})


@pytest.fixture
def make_graph(monkeypatch: pytest.MonkeyPatch):
    def _make(**client_kwargs: Any) -> tuple[GraphAdapter, _GraphDraftClient]:
        adapter = GraphAdapter(_Acct())  # type: ignore[arg-type]
        client = _GraphDraftClient(**client_kwargs)
        adapter._client = client  # type: ignore[assignment]
        monkeypatch.setattr(
            adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer t"}
        )
        return adapter, client

    return _make


def _graph_addrs(recipients: list[dict]) -> list[str]:
    return [r["emailAddress"]["address"] for r in recipients]


def test_graph_create_draft_writes_draft_with_cc_bcc_and_is_not_sent(
    make_graph, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write_attachment(tmp_path)

    out = adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_html="<p>hi</p>",
        cc=["carbon@example.com"],
        bcc=["blind@example.com"],
        attachments=[att],
    )

    # Exactly one POST, to the createDraft endpoint; never /sendMail.
    assert len(client.posts) == 1
    post = client.posts[0]
    assert post["url"] == "/me/messages"
    assert not any("sendMail" in p["url"] for p in client.posts)

    message = post["json"]
    assert _graph_addrs(message["toRecipients"]) == ["dest@example.org"]
    assert _graph_addrs(message["ccRecipients"]) == ["carbon@example.com"]
    assert _graph_addrs(message["bccRecipients"]) == ["blind@example.com"]
    assert message["attachments"][0]["name"] == "note.txt"

    assert out["id"] == "draft-1"
    assert out["webLink"] == "https://outlook/draft-1"


def test_graph_create_reply_draft_composes_recipients_and_never_sends(
    make_graph,
) -> None:
    adapter, client = make_graph(
        sender="sender@example.org",
        to=["boss@example.com"],
        cc=["watcher@example.com"],
    )

    out = adapter.create_reply_draft(
        "m1",
        body_html="<p>reply</p>",
        reply_all=True,
        cc=["new@example.com"],
    )

    # createReply was used; the message was never sent.
    assert any(p["url"].endswith("/createReply") for p in client.posts)
    assert not any(p["url"].endswith("/reply") for p in client.posts)
    assert not any("sendMail" in p["url"] for p in client.posts)

    # The draft body + recipients were PATCHed onto the created draft.
    assert client.patches, "expected a PATCH to set the draft body/recipients"
    patch = client.patches[-1]["json"]
    assert _graph_addrs(patch["toRecipients"]) == ["sender@example.org"]
    cc_addrs = [a.lower() for a in _graph_addrs(patch["ccRecipients"])]
    assert "boss@example.com" in cc_addrs      # reply_all folds original To -> cc
    assert "watcher@example.com" in cc_addrs   # original cc preserved
    assert "new@example.com" in cc_addrs       # extra cc added
    assert "me@example.com" not in cc_addrs    # self excluded
    assert out["id"] == "draft-99"


# ---- Gmail ------------------------------------------------------------------


class _GmailDraftClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({"id": "draft-g", "message": {"id": "mg", "threadId": "T1"}})


@pytest.fixture
def make_gmail(monkeypatch: pytest.MonkeyPatch):
    def _make(original: dict | None = None) -> tuple[GmailAdapter, _GmailDraftClient]:
        adapter = GmailAdapter(_Acct())  # type: ignore[arg-type]
        client = _GmailDraftClient()
        adapter._client = client  # type: ignore[assignment]
        monkeypatch.setattr(
            adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer t"}
        )
        if original is not None:
            monkeypatch.setattr(adapter, "_get_message", lambda *a, **k: original)
        return adapter, client

    return _make


def _gmail_mime_from_post(post: dict) -> email.message.Message:
    raw = base64.urlsafe_b64decode(post["json"]["message"]["raw"])
    return email.message_from_bytes(raw)


def test_gmail_create_draft_posts_to_drafts_not_send(make_gmail, tmp_path: Path) -> None:
    adapter, client = make_gmail()
    att = _write_attachment(tmp_path)

    out = adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_text="plain",
        body_html="<p>hi</p>",
        cc=["carbon@example.com"],
        bcc=["blind@example.com"],
        attachments=[att],
    )

    assert len(client.posts) == 1
    post = client.posts[0]
    # Drafts endpoint, never the send endpoint.
    assert post["url"] == "/users/me/drafts"
    assert "send" not in post["url"]

    msg = _gmail_mime_from_post(post)
    assert [a.strip() for a in msg["To"].split(",")] == ["dest@example.org"]
    assert [a.strip() for a in msg["Cc"].split(",")] == ["carbon@example.com"]
    assert [a.strip() for a in msg["Bcc"].split(",")] == ["blind@example.com"]
    # Attachment carried in the MIME.
    assert any(part.get_filename() == "note.txt" for part in msg.walk())
    assert out["id"] == "draft-g"


def test_gmail_create_reply_draft_threads_and_never_sends(make_gmail) -> None:
    original = {
        "threadId": "T1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "Sender <sender@example.org>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Cc", "value": ""},
                {"name": "Message-ID", "value": "<orig@example.org>"},
            ]
        },
    }
    adapter, client = make_gmail(original)

    adapter.create_reply_draft("m1", body_text="thanks", reply_all=False)

    post = client.posts[-1]
    # Draft written to Drafts, threaded via threadId; not sent.
    assert post["url"] == "/users/me/drafts"
    assert post["json"]["message"]["threadId"] == "T1"

    msg = _gmail_mime_from_post(post)
    assert [a.strip() for a in msg["To"].split(",")] == ["sender@example.org"]
    assert msg["In-Reply-To"] == "<orig@example.org>"
    assert msg["Subject"] == "Re: Hello"


# ---- IMAP -------------------------------------------------------------------


class _FakeIMAPAppend:
    def __init__(self) -> None:
        self.appends: list[dict[str, Any]] = []

    def append(self, mailbox: str, flags: str, date: Any, message: bytes) -> None:
        self.appends.append(
            {"mailbox": mailbox, "flags": flags, "message": message}
        )

    def logout(self) -> None:
        return None


@pytest.fixture
def make_imap(monkeypatch: pytest.MonkeyPatch):
    def _make(original: dict | None = None) -> tuple[IMAPAdapter, _FakeIMAPAppend]:
        adapter = IMAPAdapter(_Acct())  # type: ignore[arg-type]
        fake = _FakeIMAPAppend()
        monkeypatch.setattr(adapter, "_imap", lambda: fake)
        monkeypatch.setattr(adapter, "_resolve_folder", lambda name: "Drafts")

        def _no_smtp() -> None:
            raise AssertionError("draft creation must not open an SMTP connection")

        monkeypatch.setattr(adapter, "_smtp", _no_smtp)
        if original is not None:
            monkeypatch.setattr(adapter, "read", lambda message_id: original)
        return adapter, fake

    return _make


def _imap_msg_from_append(entry: dict) -> email.message.Message:
    return email.message_from_bytes(entry["message"])


def test_imap_create_draft_appends_to_drafts_with_flag_no_smtp(
    make_imap, tmp_path: Path
) -> None:
    adapter, fake = make_imap()
    att = _write_attachment(tmp_path)

    out = adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_text="plain body",
        cc=["carbon@example.com"],
        bcc=["blind@example.com"],
        attachments=[att],
    )

    assert len(fake.appends) == 1
    entry = fake.appends[0]
    assert entry["mailbox"] == '"Drafts"'
    assert "\\Draft" in entry["flags"]

    msg = _imap_msg_from_append(entry)
    assert [a.strip() for a in msg["To"].split(",")] == ["dest@example.org"]
    assert [a.strip() for a in msg["Cc"].split(",")] == ["carbon@example.com"]
    assert [a.strip() for a in msg["Bcc"].split(",")] == ["blind@example.com"]
    assert any(part.get_filename() == "note.txt" for part in msg.walk())
    assert out["folder"] == "Drafts"
    assert out["isDraft"] is True


def test_imap_create_reply_draft_threads_and_never_sends(make_imap) -> None:
    original = {
        "subject": "Hello",
        "from": "sender@example.org",
        "to": ["me@example.com"],
        "cc": [],
        "internetMessageId": "<orig@example.org>",
    }
    adapter, fake = make_imap(original)

    adapter.create_reply_draft("INBOX/5", body_text="thanks", reply_all=False)

    assert len(fake.appends) == 1
    entry = fake.appends[0]
    assert "\\Draft" in entry["flags"]
    msg = _imap_msg_from_append(entry)
    assert [a.strip() for a in msg["To"].split(",")] == ["sender@example.org"]
    assert msg["In-Reply-To"] == "<orig@example.org>"
    assert msg["Subject"] == "Re: Hello"


def test_imap_create_draft_propagates_append_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _append_to_drafts deliberately does NOT swallow APPEND failures: a draft's
    # ONLY persistence is that APPEND, so a failure must surface to the caller
    # rather than let create_draft return a false "saved" result. Monkeypatch the
    # IMAP append to raise and assert the error propagates out of create_draft.
    adapter = IMAPAdapter(_Acct())  # type: ignore[arg-type]

    class _FailingIMAP:
        def append(self, mailbox: Any, flags: Any, date: Any, message: bytes) -> None:
            raise OSError("APPEND rejected by server")

        def logout(self) -> None:
            return None

    monkeypatch.setattr(adapter, "_imap", lambda: _FailingIMAP())
    monkeypatch.setattr(adapter, "_resolve_folder", lambda name: "Drafts")

    with pytest.raises(OSError, match="APPEND rejected"):
        adapter.create_draft(to=["dest@example.org"], subject="Hi", body_text="body")


# ---- server handlers --------------------------------------------------------


class _CapturingDraftAdapter:
    """Records create_draft / create_reply_draft; raises if a send is attempted."""

    def __init__(self) -> None:
        self.draft_kwargs: dict[str, Any] | None = None
        self.reply_draft_kwargs: dict[str, Any] | None = None

    def create_draft(self, **kwargs: Any) -> dict:
        self.draft_kwargs = kwargs
        return {"id": "d1", "provider": "test"}

    def create_reply_draft(self, **kwargs: Any) -> dict:
        self.reply_draft_kwargs = kwargs
        return {"id": "d2", "provider": "test"}

    def send(self, *a: Any, **k: Any) -> None:
        raise AssertionError("mail_draft must never send")

    def reply(self, *a: Any, **k: Any) -> None:
        raise AssertionError("mail_reply_draft must never send")


def _call(name: str, arguments: dict[str, Any]) -> dict:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


class _SigAcct:
    id = "acct"
    address = "me@example.com"
    auto_write = True

    def __init__(self, signature: Signature | None) -> None:
        self.signature = signature


def test_mail_draft_applies_signature_and_does_not_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sig_path = tmp_path / "sig.html"
    sig_path.write_text('<div data-mcpmail-sig>-- Example Co</div>')
    acct = _SigAcct(Signature(html_path=sig_path, inline_images=(), on_reply=True))
    fake = _CapturingDraftAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (acct, fake))

    out = _call(
        "mail_draft",
        {
            "account": "acct",
            "to": ["dest@example.org"],
            "subject": "Hi",
            "body_html": "<p>hi</p>",
            "cc": ["carbon@example.com"],
            "bcc": ["blind@example.com"],
        },
    )

    assert out["ok"] is True
    assert out["draft"]["id"] == "d1"
    assert fake.draft_kwargs is not None
    # Signature appended to the HTML body handed to the adapter.
    assert "data-mcpmail-sig" in fake.draft_kwargs["body_html"]
    assert "Example Co" in fake.draft_kwargs["body_html"]
    # cc/bcc flow through unchanged.
    assert fake.draft_kwargs["cc"] == ["carbon@example.com"]
    assert fake.draft_kwargs["bcc"] == ["blind@example.com"]


def test_mail_reply_draft_applies_reply_signature_and_does_not_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sig_path = tmp_path / "sig.html"
    sig_path.write_text('<div data-mcpmail-sig>-- Example Co</div>')
    acct = _SigAcct(Signature(html_path=sig_path, inline_images=(), on_reply=True))
    fake = _CapturingDraftAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (acct, fake))

    out = _call(
        "mail_reply_draft",
        {
            "account": "acct",
            "message_id": "m1",
            "body_html": "Hi",
            "reply_all": True,
            "cc": ["colleague@example.com"],
        },
    )

    assert out["ok"] is True
    assert out["draft"]["id"] == "d2"
    assert fake.reply_draft_kwargs is not None
    assert "Example Co" in fake.reply_draft_kwargs["body_html"]
    assert fake.reply_draft_kwargs["reply_all"] is True
    assert fake.reply_draft_kwargs["cc"] == ["colleague@example.com"]


def test_mail_reply_draft_signature_suppressed_when_on_reply_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sig_path = tmp_path / "sig.html"
    sig_path.write_text('<div data-mcpmail-sig>-- Example Co</div>')
    # on_reply=False -> the reply draft must NOT carry the signature.
    acct = _SigAcct(Signature(html_path=sig_path, inline_images=(), on_reply=False))
    fake = _CapturingDraftAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (acct, fake))

    _call(
        "mail_reply_draft",
        {"account": "acct", "message_id": "m1", "body_html": "Hi"},
    )

    assert fake.reply_draft_kwargs is not None
    assert "Example Co" not in (fake.reply_draft_kwargs["body_html"] or "")
