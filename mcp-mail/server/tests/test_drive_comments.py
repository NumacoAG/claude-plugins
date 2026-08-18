"""Tests for the read-only ``drive_comments`` tool (Google Drive comments).

Three things are pinned here, all without touching the network or the Keychain
(the adapter's HTTP client and ``_headers`` are stubbed):

1. Projection + pagination: ``list_comments`` follows ``nextPageToken`` across
   pages, merges every comment, surfaces anchored text and replies, tolerates a
   null author email (None, not a crash), and carries ``resolved`` through.
2. Request shape: the call hits ``.../files/{id}/comments`` with
   ``includeDeleted`` false and a ``fields`` param, and never sends
   ``supportsAllDrives`` (not a valid param for ``comments.list``).
3. The Google-only gate: ``_require_google_drive_comments`` raises for a
   non-``GoogleDriveAdapter`` and does not raise for a real one.
"""

from __future__ import annotations

from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters.gdrive import GoogleDriveAdapter


class _FakeAccount:
    id = "g"


class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` the adapter consumes."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


class _PagingClient:
    """Returns successive canned pages and records each outgoing request.

    Each ``get`` pops the next queued page, so a test can simulate a multi-page
    ``comments.list`` walk and then inspect what params were sent on every call.
    """

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, "params": kwargs.get("params") or {}})
        page = self._pages.pop(0) if self._pages else {"comments": []}
        return _FakeResponse(page)


# Page 1: an anchored, unresolved comment with a reply (author has an email).
# Page 2: a resolved comment whose author email is null (only a display name).
_PAGE_1 = {
    "comments": [
        {
            "id": "c1",
            "author": {"displayName": "Ada Lovelace", "emailAddress": "ada@example.com"},
            "content": "Tighten this paragraph.",
            "createdTime": "2026-06-01T10:00:00Z",
            "modifiedTime": "2026-06-01T10:05:00Z",
            "resolved": False,
            "anchor": "kix.native-anchor",
            "quotedFileContent": {"value": "the quick brown fox"},
            "replies": [
                {
                    "id": "r1",
                    "author": {"displayName": "Alan Turing", "emailAddress": "alan@example.com"},
                    "content": "Done.",
                    "createdTime": "2026-06-01T11:00:00Z",
                    "action": "resolve",
                }
            ],
        }
    ],
    "nextPageToken": "PAGE2",
}

_PAGE_2 = {
    "comments": [
        {
            "id": "c2",
            "author": {"displayName": "Grace Hopper", "emailAddress": None},
            "content": "Looks good now.",
            "createdTime": "2026-06-02T09:00:00Z",
            "modifiedTime": "2026-06-02T09:00:00Z",
            "resolved": True,
            "replies": [],
        }
    ],
    # No nextPageToken: pagination stops here.
}


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> tuple[GoogleDriveAdapter, _PagingClient]:
    adapter = GoogleDriveAdapter(_FakeAccount())  # type: ignore[arg-type]
    client = _PagingClient([_PAGE_1, _PAGE_2])
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching the Keychain / google-auth refresh in ``_headers``.
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter, client


# ---- projection + pagination ------------------------------------------------


def test_list_comments_merges_pages_and_projects(
    drive: tuple[GoogleDriveAdapter, _PagingClient],
) -> None:
    adapter, client = drive
    comments = adapter.list_comments("f1")

    # Both pages merged.
    assert [c["id"] for c in comments] == ["c1", "c2"]
    # Two GET calls were made (one per page), the second carrying the pageToken.
    assert len(client.calls) == 2
    assert client.calls[1]["params"].get("pageToken") == "PAGE2"

    first, second = comments
    # Anchored text surfaced from quotedFileContent.value.
    assert first["anchor"] == "kix.native-anchor"
    assert first["anchorText"] == "the quick brown fox"
    assert first["author"] == "Ada Lovelace"
    assert first["authorEmail"] == "ada@example.com"
    assert first["resolved"] is False
    # The reply is present and projected.
    assert len(first["replies"]) == 1
    reply = first["replies"][0]
    assert reply["author"] == "Alan Turing"
    assert reply["content"] == "Done."
    assert reply["action"] == "resolve"

    # Null author email tolerated (None, not a crash); resolved carried through.
    assert second["authorEmail"] is None
    assert second["author"] == "Grace Hopper"
    assert second["resolved"] is True
    assert second["anchor"] is None
    assert second["anchorText"] is None
    assert second["replies"] == []


# ---- request shape ----------------------------------------------------------


def test_list_comments_request_shape(
    drive: tuple[GoogleDriveAdapter, _PagingClient],
) -> None:
    adapter, client = drive
    adapter.list_comments("f1")
    first = client.calls[0]
    assert first["url"].endswith("/files/f1/comments")
    params = first["params"]
    # includeDeleted is sent and false; a fields projection is requested.
    assert params.get("includeDeleted") == "false"
    assert params.get("fields")
    assert "anchor" in params["fields"]
    # supportsAllDrives is NOT a valid comments.list param and must not be sent.
    assert "supportsAllDrives" not in params


# ---- Google-only gate -------------------------------------------------------


def test_gate_raises_for_non_google_adapter() -> None:
    class _Dummy:
        pass

    with pytest.raises(ValueError, match="comments surface"):
        srv._require_google_drive_comments(_Dummy(), "drive_comments")


def test_gate_allows_google_drive_adapter() -> None:
    adapter = GoogleDriveAdapter(_FakeAccount())  # type: ignore[arg-type]
    # Should not raise.
    srv._require_google_drive_comments(adapter, "drive_comments")
