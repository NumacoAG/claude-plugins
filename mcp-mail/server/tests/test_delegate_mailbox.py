"""Tests for delegated shared-mailbox support in the M365 (Graph) adapter.

A delegate account carries ``mailbox=<other user's UPN/SMTP>``. The adapter then
targets ``/users/{mailbox}`` (not ``/me``) for every mailbox-content call and
authenticates with the delegated shared-mailbox token (``acquire_shared_token``,
not ``acquire_token``). Only reads and drafts are permitted: ``send()`` and
``reply()`` are guarded off because this build does not request
``Mail.Send.Shared``. Every test here is offline: the HTTP client and both token
functions are stubbed, so no network or Keychain is touched.

Pinned invariants:

1. Delegate  -- create_draft POSTs to /users/{mailbox}/messages and _headers
   mints its token via acquire_shared_token.
2. Regression -- a normal account (no mailbox) still POSTs to /me/messages and
   mints its token via acquire_token.
3. Guard     -- send() and reply() on a delegate raise RuntimeError and issue NO
   HTTP call at all.
4. Config    -- load_accounts parses the `mailbox` field onto M365Account, and a
   normal m365 account leaves it None.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import mcp_mail.adapters.graph as graph_mod
from mcp_mail.adapters.graph import GraphAdapter
from mcp_mail.config import M365Account, load_accounts

DELEGATE = "colleague@example.com"


# ---- stubs ------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any] | None = None) -> None:
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


class _RecordingClient:
    """Records every HTTP verb; answers create/read the way Graph would."""

    def __init__(self, sender: str = "sender@example.org") -> None:
        self._sender = sender
        self.posts: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.gets.append({"url": url})
        return _FakeResponse(
            {
                "id": "m1",
                "from": {"emailAddress": {"address": self._sender}},
                "toRecipients": [],
                "ccRecipients": [],
                "hasAttachments": False,
                "body": {"contentType": "html", "content": "orig"},
            }
        )

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, "json": kwargs.get("json")})
        if url.endswith("/createReply"):
            return _FakeResponse({"id": "draft-99", "webLink": "https://outlook/draft-99"})
        return _FakeResponse(
            {"id": "draft-1", "webLink": "https://outlook/draft-1", "isDraft": True}
        )

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.patches.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({"id": "draft-1"})

    def delete(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.deletes.append({"url": url})
        return _FakeResponse({})


class _Acct:
    """Minimal M365-account stand-in; `mailbox` toggles delegate mode."""

    id = "acct"
    auto_write = True
    signature = None

    def __init__(self, mailbox: str | None = None, address: str = "me@example.com") -> None:
        self.mailbox = mailbox
        self.address = address


@pytest.fixture
def make_graph(monkeypatch: pytest.MonkeyPatch):
    """Build a GraphAdapter whose _headers runs FOR REAL (so it exercises the
    token selection) against stubbed module-level token functions, and whose HTTP
    client records every call."""
    calls = {"mail": 0, "shared": 0}

    def _fake_mail_token(acct: Any) -> str:
        calls["mail"] += 1
        return "mail-token"

    def _fake_shared_token(acct: Any) -> str:
        calls["shared"] += 1
        return "shared-token"

    monkeypatch.setattr(graph_mod, "acquire_token", _fake_mail_token)
    monkeypatch.setattr(graph_mod, "acquire_shared_token", _fake_shared_token)

    def _make(
        mailbox: str | None = None, **client_kwargs: Any
    ) -> tuple[GraphAdapter, _RecordingClient, dict[str, int]]:
        adapter = GraphAdapter(_Acct(mailbox=mailbox))  # type: ignore[arg-type]
        client = _RecordingClient(**client_kwargs)
        adapter._client = client  # type: ignore[assignment]
        return adapter, client, calls

    return _make


# ---- delegate: routing + token ----------------------------------------------


def test_delegate_create_draft_targets_users_mailbox_and_uses_shared_token(
    make_graph,
) -> None:
    adapter, client, calls = make_graph(mailbox=DELEGATE)

    out = adapter.create_draft(to=["dest@example.org"], subject="Hi", body_html="<p>hi</p>")

    # POST goes to the delegated mailbox, not /me.
    assert len(client.posts) == 1
    assert client.posts[0]["url"] == f"/users/{DELEGATE}/messages"
    # The token came from the delegated shared-mailbox flow only.
    assert calls["shared"] == 1
    assert calls["mail"] == 0
    assert out["id"] == "draft-1"


# ---- regression: a normal account is unchanged ------------------------------


def test_normal_account_create_draft_targets_me_and_uses_mail_token(
    make_graph,
) -> None:
    adapter, client, calls = make_graph(mailbox=None)

    adapter.create_draft(to=["dest@example.org"], subject="Hi", body_html="<p>hi</p>")

    assert client.posts[0]["url"] == "/me/messages"
    assert calls["mail"] == 1
    assert calls["shared"] == 0


# ---- guard: no sending from a delegate mailbox ------------------------------


def test_delegate_send_raises_guard_and_makes_no_http_call(make_graph) -> None:
    adapter, client, _ = make_graph(mailbox=DELEGATE)

    with pytest.raises(RuntimeError, match="delegated mailbox"):
        adapter.send(to=["dest@example.org"], subject="Hi", body_text="hi")

    # The guard fires before any transport, so nothing left the process.
    assert client.posts == []
    assert client.patches == []
    assert client.gets == []


def test_delegate_reply_raises_guard_and_makes_no_http_call(make_graph) -> None:
    adapter, client, _ = make_graph(mailbox=DELEGATE)

    with pytest.raises(RuntimeError, match="delegated mailbox"):
        adapter.reply("m1", body_text="hi", reply_all=True)

    # reply_all would normally read the original first; the guard precedes it.
    assert client.posts == []
    assert client.patches == []
    assert client.gets == []


# ---- config parsing ---------------------------------------------------------


_DELEGATE_CONFIG = """
[[account]]
id = "colleague-shared"
provider = "m365"
address = "colleague@example.com"
mailbox = "colleague@example.com"
client_id = "app"
tenant_id = "tenant"
keychain_service = "mcp-mail"
keychain_user = "work-m365"
auto_send = false
capabilities = ["mail"]

[[account]]
id = "plain-m365"
provider = "m365"
address = "you@example.com"
client_id = "app"
tenant_id = "tenant"
auto_send = false
"""


def test_load_accounts_parses_mailbox_field(tmp_path: Path) -> None:
    p = tmp_path / "accounts.toml"
    p.write_text(_DELEGATE_CONFIG)
    accounts = {a.id: a for a in load_accounts(p)}

    delegate = accounts["colleague-shared"]
    assert isinstance(delegate, M365Account)
    assert delegate.mailbox == "colleague@example.com"

    # A normal m365 account leaves mailbox unset (None).
    plain = accounts["plain-m365"]
    assert isinstance(plain, M365Account)
    assert plain.mailbox is None
