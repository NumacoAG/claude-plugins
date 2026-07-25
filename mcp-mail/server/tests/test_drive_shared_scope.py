"""Tests that the Drive v3 calls carry the Shared Drive (Team Drive) params.

Root cause being pinned here: the Drive ``files.list`` / ``files.get`` (and the
write-side ``files`` / ``permissions`` calls) defaulted to the ``user`` corpus
and omitted ``supportsAllDrives``, so ``drive_search`` never returned Shared
Drive files and ``drive_get_metadata`` / ``drive_read`` 404'd on them. The fix
adds ``includeItemsFromAllDrives`` + ``supportsAllDrives`` + ``corpora=allDrives``
to the listing calls and ``supportsAllDrives`` to every other Drive files /
permissions call.

The adapter's HTTP client is stubbed with a recorder so no network or Keychain
is touched; each test inspects the captured request params. Assertions stay
agnostic about the bool-vs-string representation of the flags, accepting either
``True`` or ``"true"``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_mail.adapters.gdrive import GoogleDriveAdapter
from mcp_mail.core import native_format as nf


class _FakeAccount:
    id = "g"


class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` the adapter consumes."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data
        self.content = b"bytes"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


class _RecordingClient:
    """Captures every outgoing request so a test can inspect the params sent."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data
        self.calls: list[dict[str, Any]] = []

    def _record(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "params": kwargs.get("params") or {}})
        return _FakeResponse(self._json)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("PUT", url, **kwargs)


# A canned Drive file the adapter can project / route on. The binary mime keeps
# ``read`` on the ``alt=media`` byte path and ``update`` byte-writable.
_FILE = {
    "id": "f1",
    "name": "file.pdf",
    "mimeType": "application/pdf",
    "parents": ["p1"],
}


def _truthy(value: Any) -> bool:
    """Accept either a Python ``True`` or the literal Google string ``"true"``."""
    return value is True or value == "true"


@pytest.fixture
def drive(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GoogleDriveAdapter, _RecordingClient]:
    adapter = GoogleDriveAdapter(_FakeAccount())  # type: ignore[arg-type]
    client = _RecordingClient(_FILE)
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching the Keychain / google-auth refresh in ``_headers``.
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter, client


def _last_params(client: _RecordingClient, method: str) -> dict[str, Any]:
    matching = [c for c in client.calls if c["method"] == method]
    assert matching, f"no {method} request was recorded"
    return matching[-1]["params"]


# ---- listing calls span all drives -----------------------------------------


def test_search_spans_all_drives(drive: tuple[GoogleDriveAdapter, _RecordingClient]) -> None:
    adapter, client = drive
    adapter.search("hello")
    params = _last_params(client, "GET")
    assert params.get("corpora") == "allDrives"
    assert _truthy(params.get("includeItemsFromAllDrives"))
    assert _truthy(params.get("supportsAllDrives"))


def test_list_spans_all_drives(drive: tuple[GoogleDriveAdapter, _RecordingClient]) -> None:
    adapter, client = drive
    adapter.list()
    params = _last_params(client, "GET")
    assert params.get("corpora") == "allDrives"
    assert _truthy(params.get("includeItemsFromAllDrives"))
    assert _truthy(params.get("supportsAllDrives"))


# ---- every other file / permission call supports all drives -----------------


def test_get_metadata_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.get_metadata("f1")
    assert _truthy(_last_params(client, "GET").get("supportsAllDrives"))


def test_read_supports_all_drives_on_every_get(
    drive: tuple[GoogleDriveAdapter, _RecordingClient], tmp_path
) -> None:
    adapter, client = drive
    adapter.read("f1", target_dir=str(tmp_path))
    gets = [c for c in client.calls if c["method"] == "GET"]
    # Both the metadata fetch and the alt=media byte fetch must carry the flag.
    assert len(gets) >= 2
    for call in gets:
        assert _truthy(call["params"].get("supportsAllDrives"))


def test_create_multipart_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.create("note.txt", content="hi", mime="text/plain")
    assert _truthy(_last_params(client, "POST").get("supportsAllDrives"))


def test_create_metadata_only_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.create("folder", mime=nf.GOOGLE_FOLDER)
    assert _truthy(_last_params(client, "POST").get("supportsAllDrives"))


def test_update_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.update("f1", "new content")
    assert _truthy(_last_params(client, "PATCH").get("supportsAllDrives"))


def test_move_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.move("f1", "newparent/new name")
    assert _truthy(_last_params(client, "PATCH").get("supportsAllDrives"))


def test_copy_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.copy("f1", "parent/copy name")
    assert _truthy(_last_params(client, "POST").get("supportsAllDrives"))


def test_delete_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.delete("f1")
    assert _truthy(_last_params(client, "PATCH").get("supportsAllDrives"))


def test_share_supports_all_drives(
    drive: tuple[GoogleDriveAdapter, _RecordingClient],
) -> None:
    adapter, client = drive
    adapter.share("f1", "a@b.c", "reader")
    assert _truthy(_last_params(client, "POST").get("supportsAllDrives"))
