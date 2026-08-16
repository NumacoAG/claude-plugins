"""HTTP and schema tests for native Google Drive event attachments."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters.gcalendar import GoogleCalendarAdapter


class _FakeAccount:
    id = "g"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingClient:
    def __init__(self, stored_event: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stored_event = stored_event or {"id": "evt-1"}

    def _record(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        call = {
            "method": method,
            "url": url,
            "params": kwargs.get("params") or {},
            "json": kwargs.get("json"),
        }
        self.calls.append(call)
        if method == "GET":
            return _FakeResponse(self.stored_event)
        payload = {"id": "evt-1", **(call["json"] or {})}
        return _FakeResponse(payload)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("PATCH", url, **kwargs)


class _FakeDrive:
    def __init__(self, metadata: dict[str, dict[str, Any]]) -> None:
        self.metadata = metadata
        self.calls: list[str] = []

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        self.calls.append(file_id)
        return self.metadata[file_id]


def _attachment_metadata(file_id: str, name: str = "Brief") -> dict[str, str]:
    return {
        "id": file_id,
        "name": name,
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
    }


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stored_event: dict[str, Any] | None = None,
    metadata: dict[str, dict[str, Any]] | None = None,
) -> tuple[GoogleCalendarAdapter, _RecordingClient, _FakeDrive]:
    adapter = GoogleCalendarAdapter(_FakeAccount())  # type: ignore[arg-type]
    client = _RecordingClient(stored_event)
    drive = _FakeDrive(metadata or {})
    adapter._client = client  # type: ignore[assignment]
    adapter._drive = drive  # type: ignore[assignment]
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter, client, drive


def _last(client: _RecordingClient, method: str) -> dict[str, Any]:
    calls = [call for call in client.calls if call["method"] == method]
    assert calls, f"no {method} request was recorded"
    return calls[-1]


def test_calendar_tool_schemas_accept_drive_file_ids() -> None:
    tools = {tool.name: tool for tool in asyncio.run(srv.list_tools())}
    for name in ("cal_create_event", "cal_update_event"):
        field = tools[name].inputSchema["properties"]["drive_file_ids"]
        assert field["type"] == "array"
        assert field["maxItems"] == 25


def test_create_event_adds_native_drive_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, client, drive = _make_adapter(
        monkeypatch,
        metadata={"doc-1": _attachment_metadata("doc-1", "Kickoff brief")},
    )

    out = adapter.create_event(
        summary="Kickoff",
        start="2026-08-17T16:35:00+02:00",
        end="2026-08-17T17:00:00+02:00",
        drive_file_ids=["doc-1", "doc-1"],
    )

    call = _last(client, "POST")
    assert call["params"] == {"sendUpdates": "none", "supportsAttachments": True}
    assert call["json"]["attachments"] == [
        {
            "fileUrl": "https://docs.google.com/document/d/doc-1/edit",
            "title": "Kickoff brief",
            "mimeType": "application/vnd.google-apps.document",
        }
    ]
    assert drive.calls == ["doc-1"]
    assert out["attachments"][0]["title"] == "Kickoff brief"


def test_update_preserves_existing_attachments_and_notifies_guests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = {
        "fileId": "old-1",
        "fileUrl": "https://drive.google.com/open?id=old-1",
        "title": "Existing notes",
        "mimeType": "application/pdf",
        "iconLink": "https://example.com/icon.png",
    }
    adapter, client, _ = _make_adapter(
        monkeypatch,
        stored_event={"id": "evt-1", "attachments": [existing]},
        metadata={"doc-2": _attachment_metadata("doc-2")},
    )

    adapter.update_event(
        "evt-1",
        notify=True,
        description="Read this first",
        drive_file_ids=["doc-2"],
    )

    call = _last(client, "PATCH")
    assert call["params"] == {"sendUpdates": "all", "supportsAttachments": True}
    assert call["json"]["description"] == "Read this first"
    assert call["json"]["attachments"][0] == existing
    assert call["json"]["attachments"][1]["fileUrl"].endswith("/doc-2/edit")


def test_update_is_idempotent_for_an_existing_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_url = "https://drive.google.com/open?id=doc-1"
    adapter, client, _ = _make_adapter(
        monkeypatch,
        stored_event={
            "id": "evt-1",
            "attachments": [
                {
                    "fileId": "doc-1",
                    "fileUrl": file_url,
                    "title": "Brief",
                    "mimeType": "application/vnd.google-apps.document",
                }
            ],
        },
        metadata={"doc-1": _attachment_metadata("doc-1")},
    )

    adapter.update_event("evt-1", drive_file_ids=["doc-1"])

    attachments = _last(client, "PATCH")["json"]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["fileUrl"] == file_url


def test_update_rejects_more_than_twenty_five_total_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {
        "id": "evt-1",
        "attachments": [
            {
                "fileId": f"old-{i}",
                "fileUrl": f"https://drive.google.com/open?id=old-{i}",
            }
            for i in range(25)
        ],
    }
    adapter, client, _ = _make_adapter(
        monkeypatch,
        stored_event=stored,
        metadata={"new-1": _attachment_metadata("new-1")},
    )

    with pytest.raises(ValueError, match="at most 25"):
        adapter.update_event("evt-1", drive_file_ids=["new-1"])
    assert not [call for call in client.calls if call["method"] == "PATCH"]


def test_ordinary_update_does_not_enable_attachment_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, client, _ = _make_adapter(monkeypatch)

    adapter.update_event("evt-1", description="No attachment change")

    assert not [call for call in client.calls if call["method"] == "GET"]
    call = _last(client, "PATCH")
    assert call["params"] == {"sendUpdates": "none"}
    assert "attachments" not in call["json"]
