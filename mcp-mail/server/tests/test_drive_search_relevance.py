"""Tests that ``drive_search`` is name-first, relevance-ordered, and deduped.

Root cause pinned here: the old ``search`` ran a single ``files.list`` pass with
``orderBy="modifiedTime desc"`` capped at ``limit``, so a document that matched
by NAME but was last modified a while ago (proven cases: a 2023 "SI Q2 2026
strategy" and a "Quarterly Idea Gathering Meeting Template") never surfaced,
buried under hundreds of newer full-text hits. The fix runs two passes (a
``name contains`` pass, then a ``fullText contains`` pass), merges them name
first, dedups by id, truncates to ``limit``, and drops the forced recency order
so Drive ranks by relevance within each pass.

The adapter's HTTP client is stubbed with a recorder that returns DIFFERENT
canned payloads per pass (branching on whether the ``q`` param contains
``"name contains"`` vs ``"fullText contains"``), so the two passes are
distinguishable. No network or Keychain is touched. Flag assertions stay
agnostic about the bool-vs-string representation, accepting ``True`` or
``"true"``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_mail.adapters.gdrive import GoogleDriveAdapter


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


class _TwoPassClient:
    """Returns a different file list per pass, keyed on the ``q`` param.

    A ``name contains`` query yields ``name_files``; a ``fullText contains``
    query yields ``text_files``. Every outgoing request is recorded so a test can
    inspect the params each pass sent.
    """

    def __init__(
        self, name_files: list[dict[str, Any]], text_files: list[dict[str, Any]]
    ) -> None:
        self._name_files = name_files
        self._text_files = text_files
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        params = kwargs.get("params") or {}
        self.calls.append({"method": "GET", "url": url, "params": params})
        q = str(params.get("q", ""))
        if "name contains" in q:
            return _FakeResponse({"files": self._name_files})
        if "fullText contains" in q:
            return _FakeResponse({"files": self._text_files})
        return _FakeResponse({"files": []})


def _truthy(value: Any) -> bool:
    """Accept either a Python ``True`` or the literal Google string ``"true"``."""
    return value is True or value == "true"


def _file(file_id: str, name: str) -> dict[str, Any]:
    return {"id": file_id, "name": name, "mimeType": "application/pdf", "parents": ["p1"]}


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch,
    name_files: list[dict[str, Any]],
    text_files: list[dict[str, Any]],
) -> tuple[GoogleDriveAdapter, _TwoPassClient]:
    adapter = GoogleDriveAdapter(_FakeAccount())  # type: ignore[arg-type]
    client = _TwoPassClient(name_files, text_files)
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching the Keychain / google-auth refresh in ``_headers``.
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter, client


def test_name_match_ranks_before_fulltext_only_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The name pass returns a doc the full-text pass never sees; it must lead.
    adapter, _ = _make_adapter(
        monkeypatch,
        name_files=[_file("name-hit", "SI Q2 2026 strategy")],
        text_files=[_file("text-hit", "Some other doc mentioning the query")],
    )
    results = adapter.search("Q2 2026 strategy")
    ids = [r["id"] for r in results]
    assert ids.index("name-hit") < ids.index("text-hit")


def test_document_in_both_passes_appears_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A doc returned by BOTH passes must be deduped to a single entry.
    shared = _file("shared", "Quarterly Idea Gathering Meeting Template")
    adapter, _ = _make_adapter(
        monkeypatch,
        name_files=[shared],
        text_files=[shared, _file("text-only", "another match")],
    )
    results = adapter.search("Quarterly Idea Gathering")
    ids = [r["id"] for r in results]
    assert ids.count("shared") == 1
    assert ids == ["shared", "text-only"]


def test_result_length_never_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name_files = [_file(f"n{i}", f"name doc {i}") for i in range(8)]
    text_files = [_file(f"t{i}", f"text doc {i}") for i in range(8)]
    adapter, _ = _make_adapter(monkeypatch, name_files, text_files)
    results = adapter.search("doc", limit=5)
    assert len(results) == 5
    # Name-pass hits fill the truncated list first.
    assert [r["id"] for r in results] == ["n0", "n1", "n2", "n3", "n4"]


def test_neither_pass_forces_recency_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, client = _make_adapter(
        monkeypatch,
        name_files=[_file("n", "n")],
        text_files=[_file("t", "t")],
    )
    adapter.search("anything")
    gets = [c for c in client.calls if c["method"] == "GET"]
    assert len(gets) == 2  # exactly two passes
    for call in gets:
        assert call["params"].get("orderBy") != "modifiedTime desc"
        # The forced recency ordering is gone entirely.
        assert "orderBy" not in call["params"]


def test_both_passes_span_all_drives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, client = _make_adapter(
        monkeypatch,
        name_files=[_file("n", "n")],
        text_files=[_file("t", "t")],
    )
    adapter.search("anything")
    gets = [c for c in client.calls if c["method"] == "GET"]
    assert len(gets) == 2
    queries = [str(c["params"].get("q", "")) for c in gets]
    assert any("name contains" in q for q in queries)
    assert any("fullText contains" in q for q in queries)
    for call in gets:
        params = call["params"]
        assert params.get("corpora") == "allDrives"
        assert _truthy(params.get("supportsAllDrives"))
        assert _truthy(params.get("includeItemsFromAllDrives"))
