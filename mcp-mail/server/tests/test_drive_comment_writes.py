"""Tests for the write side of Google Drive comments.

Two layers are pinned here, both without touching the network or the Keychain
(the adapter's HTTP client and ``_headers`` are stubbed):

1. Adapter request shape + projection. ``add_comment`` POSTs to
   ``.../files/{id}/comments`` with the text in the JSON body; ``reply_comment``
   POSTs to ``.../comments/{cid}/replies``; ``resolve_comment`` /
   ``reopen_comment`` post an action reply whose body carries
   ``action == "resolve"`` / ``"reopen"`` and omits ``content`` entirely when no
   note is given. None of these send ``supportsAllDrives`` (not valid on the
   comments endpoints).
2. The server-side outward-facing gate. ``drive_comment_add`` and
   ``drive_comment_reply`` refuse without ``confirmed=true`` and proceed with it
   (mirroring the calendar attendee gate); ``drive_comment_resolve`` /
   ``drive_comment_reopen`` are state toggles and proceed with no confirm gate.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters.gdrive import GoogleDriveAdapter
from mcp_mail.core import audit


class _FakeAccount:
    id = "g"
    auto_write = True


class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` the adapter consumes."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


class _RecordingClient:
    """Records every outgoing request (url, params, json body) for inspection."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({
            "method": "POST",
            "url": url,
            "params": kwargs.get("params") or {},
            "json": kwargs.get("json"),
        })
        return _FakeResponse(self._json)


# ---- adapter-level: request shape + projection ------------------------------


@pytest.fixture
def make_drive(monkeypatch: pytest.MonkeyPatch):
    """Factory: build a stubbed adapter whose client returns the given response."""

    def _make(json_data: dict[str, Any]) -> tuple[GoogleDriveAdapter, _RecordingClient]:
        adapter = GoogleDriveAdapter(_FakeAccount())  # type: ignore[arg-type]
        client = _RecordingClient(json_data)
        adapter._client = client  # type: ignore[assignment]
        # Avoid touching the Keychain / google-auth refresh in ``_headers``.
        monkeypatch.setattr(
            adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
        )
        return adapter, client

    return _make


def test_add_comment_posts_and_projects(make_drive) -> None:
    adapter, client = make_drive({
        "id": "c-new",
        "author": {"displayName": "Ada", "emailAddress": "ada@example.com"},
        "content": "Tighten this.",
        "createdTime": "2026-06-27T10:00:00Z",
        "resolved": False,
    })
    result = adapter.add_comment("f1", "Tighten this.")

    call = client.calls[-1]
    assert call["method"] == "POST"
    assert call["url"].endswith("/files/f1/comments")
    # The content rides in the JSON body, not the query.
    assert call["json"] == {"content": "Tighten this."}
    assert call["params"].get("fields")
    # supportsAllDrives is not valid on the comments endpoints.
    assert "supportsAllDrives" not in call["params"]

    # Projected through _project_comment.
    assert result["id"] == "c-new"
    assert result["author"] == "Ada"
    assert result["authorEmail"] == "ada@example.com"
    assert result["content"] == "Tighten this."
    assert result["resolved"] is False


def test_reply_comment_posts_to_replies(make_drive) -> None:
    adapter, client = make_drive({
        "id": "r-new",
        "author": {"displayName": "Alan"},
        "content": "Done.",
        "createdTime": "2026-06-27T11:00:00Z",
        "action": None,
    })
    result = adapter.reply_comment("f1", "c1", "Done.")

    call = client.calls[-1]
    assert call["url"].endswith("/files/f1/comments/c1/replies")
    assert call["json"] == {"content": "Done."}
    assert call["params"].get("fields")
    assert "supportsAllDrives" not in call["params"]

    assert result["id"] == "r-new"
    assert result["author"] == "Alan"
    assert result["content"] == "Done."


def test_resolve_comment_without_content_omits_content_key(make_drive) -> None:
    adapter, client = make_drive({"id": "r1", "action": "resolve"})
    result = adapter.resolve_comment("f1", "c1")

    call = client.calls[-1]
    assert call["url"].endswith("/files/f1/comments/c1/replies")
    assert call["json"]["action"] == "resolve"
    # No content arg -> the body must not carry a content key at all.
    assert "content" not in call["json"]
    assert result["action"] == "resolve"


def test_resolve_comment_with_content_sends_content(make_drive) -> None:
    adapter, client = make_drive({"id": "r1", "action": "resolve", "content": "Addressed."})
    adapter.resolve_comment("f1", "c1", "Addressed.")

    call = client.calls[-1]
    assert call["json"]["action"] == "resolve"
    assert call["json"]["content"] == "Addressed."


def test_reopen_comment_posts_action_reopen(make_drive) -> None:
    adapter, client = make_drive({"id": "r1", "action": "reopen"})
    adapter.reopen_comment("f1", "c1")

    call = client.calls[-1]
    assert call["url"].endswith("/files/f1/comments/c1/replies")
    assert call["json"]["action"] == "reopen"
    assert "content" not in call["json"]


@pytest.mark.parametrize("action", ["resolve", "reopen"])
def test_action_reply_fields_omit_resolved(make_drive, action: str) -> None:
    """The action reply must not ask Drive for a ``resolved`` field.

    A Drive *reply* resource has no ``resolved`` field (only the parent comment
    does); requesting it makes the live API return 400 Bad Request. Guard the
    ``fields`` projection against re-introducing it, while still pinning the
    body's ``action``.
    """
    adapter, client = make_drive({"id": "r1", "action": action})
    getattr(adapter, f"{action}_comment")("f1", "c1")

    call = client.calls[-1]
    assert call["json"]["action"] == action
    fields = call["params"]["fields"]
    assert "resolved" not in fields


# ---- server-level: the outward-facing confirm gate --------------------------


class _FakeDriveAdapter(GoogleDriveAdapter):
    """A GoogleDriveAdapter whose comment writes are recorded, never networked.

    Subclassing keeps ``isinstance(.., GoogleDriveAdapter)`` true so the
    ``_require_google_drive_comments`` guard passes; the overridden ``__init__``
    skips the httpx client so no network is set up.
    """

    def __init__(self) -> None:  # intentionally skips super().__init__ (no client)
        self.added: list[dict] = []
        self.replied: list[dict] = []
        self.resolved: list[dict] = []
        self.reopened: list[dict] = []

    def add_comment(self, ref: str, content: str) -> dict:
        self.added.append({"ref": ref, "content": content})
        return {"id": "c-new", "content": content}

    def reply_comment(self, ref: str, comment_id: str, content: str) -> dict:
        self.replied.append({"ref": ref, "comment_id": comment_id, "content": content})
        return {"id": "r-new", "content": content}

    def resolve_comment(self, ref: str, comment_id: str, content: str | None = None) -> dict:
        self.resolved.append({"ref": ref, "comment_id": comment_id, "content": content})
        return {"id": "r-res", "action": "resolve"}

    def reopen_comment(self, ref: str, comment_id: str, content: str | None = None) -> dict:
        self.reopened.append({"ref": ref, "comment_id": comment_id, "content": content})
        return {"id": "r-reo", "action": "reopen"}


def _call(name: str, arguments: dict[str, Any]) -> dict:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


@pytest.fixture
def patch_drive(monkeypatch: pytest.MonkeyPatch, tmp_path):
    # Keep the audit log out of the real home dir during tests.
    monkeypatch.setattr(audit, "DEFAULT_AUDIT_PATH", tmp_path / "audit.log")

    def _install(fake: _FakeDriveAdapter) -> _FakeDriveAdapter:
        monkeypatch.setattr(
            srv, "_get_drive_adapter", lambda account_id: (_FakeAccount(), fake)
        )
        return fake

    return _install


def test_comment_add_refused_without_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call("drive_comment_add", {"account": "g", "ref": "f1", "content": "Hi"})
    assert out["gated"] is True
    assert out["ok"] is False
    assert not fake.added  # no write happened


def test_comment_add_proceeds_with_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call(
        "drive_comment_add",
        {"account": "g", "ref": "f1", "content": "Hi", "confirmed": True},
    )
    assert out["id"] == "c-new"
    assert len(fake.added) == 1
    assert fake.added[0]["content"] == "Hi"


def test_comment_reply_refused_without_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call(
        "drive_comment_reply",
        {"account": "g", "ref": "f1", "comment_id": "c1", "content": "Yo"},
    )
    assert out["gated"] is True
    assert not fake.replied


def test_comment_reply_proceeds_with_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call(
        "drive_comment_reply",
        {"account": "g", "ref": "f1", "comment_id": "c1", "content": "Yo", "confirmed": True},
    )
    assert out["id"] == "r-new"
    assert len(fake.replied) == 1
    assert fake.replied[0]["comment_id"] == "c1"


def test_comment_resolve_needs_no_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call("drive_comment_resolve", {"account": "g", "ref": "f1", "comment_id": "c1"})
    assert out["action"] == "resolve"
    assert len(fake.resolved) == 1
    assert fake.resolved[0]["content"] is None


def test_comment_reopen_needs_no_confirm(patch_drive) -> None:
    fake = patch_drive(_FakeDriveAdapter())
    out = _call(
        "drive_comment_reopen",
        {"account": "g", "ref": "f1", "comment_id": "c1", "content": "back"},
    )
    assert out["action"] == "reopen"
    assert len(fake.reopened) == 1
    assert fake.reopened[0]["content"] == "back"
