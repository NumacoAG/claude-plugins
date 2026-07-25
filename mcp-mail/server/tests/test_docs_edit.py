"""Tests for the Google Docs adapter (``doc_get`` / ``doc_insert_text`` /
``doc_append`` / ``doc_replace_text``).

Everything is pinned without touching the network or the Keychain: the adapter's
HTTP client and ``_headers`` are stubbed, exactly like the Drive tests. Covered:

1. ``get`` projects ``title`` and a plain-text rendering concatenated from each
   paragraph element's ``textRun.content`` (elements without a textRun skipped).
2. ``insert_text`` POSTs an ``insertText`` request to ``.../documents/{id}:batchUpdate``
   at the expected index and text (default index 1).
3. ``append_text`` first GETs the doc to learn the body's last ``endIndex`` then
   inserts at ``end_index - 1``.
4. ``replace_all_text`` sends a ``replaceAllText`` request carrying
   ``containsText.text``, ``matchCase`` and ``replaceText`` and returns the
   ``occurrencesChanged`` parsed from the canned response.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_mail.adapters.gdocs import GoogleDocsAdapter


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


class _RecordingClient:
    """Records every request; returns successive queued GET payloads.

    ``get`` pops the next queued page (so a test can stage a multi-GET flow such
    as append's read-then-write), falling back to the last payload once drained.
    ``post`` returns a fixed ``batchUpdate`` reply. Every call is captured for
    inspection of the URL and JSON body sent.
    """

    def __init__(
        self, get_pages: list[dict[str, Any]], post_reply: dict[str, Any] | None = None
    ) -> None:
        self._get_pages = list(get_pages)
        self._last_get = get_pages[-1] if get_pages else {}
        self._post_reply = post_reply or {}
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "json": kwargs.get("json"),
                "params": kwargs.get("params"),
            }
        )
        page = self._get_pages.pop(0) if self._get_pages else self._last_get
        return _FakeResponse(page)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "json": kwargs.get("json")})
        return _FakeResponse(self._post_reply)


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch, client: _RecordingClient
) -> GoogleDocsAdapter:
    adapter = GoogleDocsAdapter(_FakeAccount())  # type: ignore[arg-type]
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching the Keychain / google-auth refresh in ``_headers``.
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter


# A canned documents.get payload: two paragraphs, one with two text runs, plus an
# element with no textRun (an inline object) that must be skipped.
_DOC = {
    "documentId": "doc1",
    "title": "Meeting notes",
    "body": {
        "content": [
            {
                "startIndex": 1,
                "endIndex": 14,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Hello "}},
                        {"textRun": {"content": "world\n"}},
                    ]
                },
            },
            {
                "startIndex": 14,
                "endIndex": 28,
                "paragraph": {
                    "elements": [
                        {"inlineObjectElement": {"inlineObjectId": "io1"}},
                        {"textRun": {"content": "Second line\n"}},
                    ]
                },
            },
        ]
    },
}


# ---- get() projection -------------------------------------------------------


def test_get_projects_title_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([_DOC])
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.get("doc1")

    assert result["documentId"] == "doc1"
    assert result["title"] == "Meeting notes"
    # Runs concatenated in order; the inline object (no textRun) is skipped.
    assert result["text"] == "Hello world\nSecond line\n"
    # The GET hit the documents endpoint for this id.
    assert client.calls[0]["method"] == "GET"
    assert client.calls[0]["url"].endswith("/documents/doc1")


# ---- insert_text() ----------------------------------------------------------


def test_insert_text_posts_batch_update(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.insert_text("doc1", "Intro. ", index=5)

    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/documents/doc1:batchUpdate")
    req = post["json"]["requests"][0]["insertText"]
    assert req == {"location": {"index": 5}, "text": "Intro. "}
    assert result == {"documentId": "doc1", "inserted": len("Intro. "), "index": 5}


def test_insert_text_defaults_to_index_1(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.insert_text("doc1", "X")

    req = client.calls[-1]["json"]["requests"][0]["insertText"]
    assert req["location"]["index"] == 1
    assert result["index"] == 1


# ---- append_text() ----------------------------------------------------------


def test_append_text_inserts_before_final_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The body's last element endIndex is 28, so append must insert at 27.
    client = _RecordingClient([_DOC], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.append_text("doc1", "Appended.")

    # First a GET to learn the end index, then the insert POST.
    assert client.calls[0]["method"] == "GET"
    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/documents/doc1:batchUpdate")
    req = post["json"]["requests"][0]["insertText"]
    assert req["location"]["index"] == 27  # end_index (28) - 1
    assert req["text"] == "Appended."
    assert result == {"documentId": "doc1", "inserted": len("Appended."), "index": 27}


# ---- replace_all_text() -----------------------------------------------------


def test_replace_all_text_request_and_count(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"replies": [{"replaceAllText": {"occurrencesChanged": 3}}]}
    client = _RecordingClient([], post_reply=reply)
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.replace_all_text("doc1", "foo", "bar", match_case=True)

    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/documents/doc1:batchUpdate")
    req = post["json"]["requests"][0]["replaceAllText"]
    assert req["containsText"] == {"text": "foo", "matchCase": True}
    assert req["replaceText"] == "bar"
    assert result == {"documentId": "doc1", "occurrencesChanged": 3}


def test_replace_all_text_defaults_zero_when_no_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.replace_all_text("doc1", "x", "y")

    # match_case defaults to false; a reply-less response means 0 changed.
    req = client.calls[-1]["json"]["requests"][0]["replaceAllText"]
    assert req["containsText"]["matchCase"] is False
    assert result["occurrencesChanged"] == 0


# ---- get_structured() -------------------------------------------------------


def test_get_structured_passes_fields_and_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([{"documentId": "doc1", "body": {"content": []}}])
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.get_structured(
        "doc1", fields="body.content(startIndex,table)", include_tabs=True
    )

    get = client.calls[0]
    assert get["method"] == "GET"
    assert get["url"].endswith("/documents/doc1")
    # The mask and multi-tab flag ride the URL query params, not the body.
    assert get["params"] == {
        "fields": "body.content(startIndex,table)",
        "includeTabsContent": "true",
    }
    # The raw documents.get JSON is returned verbatim (not a flattened projection).
    assert result == {"documentId": "doc1", "body": {"content": []}}


def test_get_structured_no_mask_sends_no_params(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([{"documentId": "doc1"}])
    adapter = _make_adapter(monkeypatch, client)

    adapter.get_structured("doc1")

    assert client.calls[0]["params"] is None


# ---- create() ---------------------------------------------------------------


def test_create_posts_title(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"documentId": "new1", "title": "Report", "revisionId": "rev1"}
    client = _RecordingClient([], post_reply=reply)
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.create("Report")

    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/documents")
    assert post["json"] == {"title": "Report"}
    assert result == {"documentId": "new1", "title": "Report", "revisionId": "rev1"}


# ---- batch_update() (raw passthrough) ---------------------------------------


def test_batch_update_forwards_requests_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([], post_reply={"documentId": "doc1", "replies": [{}]})
    adapter = _make_adapter(monkeypatch, client)

    reqs = [
        {"insertText": {"text": "b", "location": {"index": 50}}},
        {"insertText": {"text": "a", "location": {"index": 5}}},
    ]
    adapter.batch_update("doc1", reqs, write_control={"requiredRevisionId": "R1"})

    post = client.calls[-1]
    assert post["url"].endswith("/documents/doc1:batchUpdate")
    # Passthrough must not reorder or rewrite the caller's requests.
    assert post["json"]["requests"] == reqs
    assert post["json"]["writeControl"] == {"requiredRevisionId": "R1"}


def test_batch_update_omits_write_control_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    adapter.batch_update("doc1", [{"insertPageBreak": {"location": {"index": 1}}}])

    assert "writeControl" not in client.calls[-1]["json"]


# A post-insert documents.get for a 2x2 table with known cell insertion indices
# (cell.content[0].startIndex): [0][0]=3, [0][1]=18, [1][0]=34, [1][1]=49.
def _table_2x2_tree() -> dict[str, Any]:
    def cell(idx: int, end: int) -> dict[str, Any]:
        return {"startIndex": idx - 1, "endIndex": end, "content": [{"startIndex": idx}]}

    return {
        "body": {
            "content": [
                {"startIndex": 1, "endIndex": 2, "paragraph": {"elements": []}},
                {
                    "startIndex": 2,
                    "endIndex": 64,
                    "table": {
                        "tableRows": [
                            {"tableCells": [cell(3, 18), cell(18, 33)]},
                            {"tableCells": [cell(34, 49), cell(49, 64)]},
                        ]
                    },
                },
            ]
        }
    }


# ---- create_table() ---------------------------------------------------------


def test_create_table_fills_descending(monkeypatch: pytest.MonkeyPatch) -> None:
    # before-get: no tables yet; after-get: the 2x2 tree above.
    before = {"body": {"content": []}}
    client = _RecordingClient([before, _table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.create_table("doc1", 2, 2, data=[["A", "B"], ["C", "D"]])

    # Sequence: GET(before), POST(insertTable), GET(after), POST(fills).
    methods = [c["method"] for c in client.calls]
    assert methods == ["GET", "POST", "GET", "POST"]

    insert = client.calls[1]["json"]["requests"][0]["insertTable"]
    assert insert["rows"] == 2
    assert insert["columns"] == 2
    # Default (no index) appends via an exactly-shaped endOfSegmentLocation.
    assert insert["endOfSegmentLocation"] == {"segmentId": ""}
    assert "location" not in insert

    fills = client.calls[-1]["json"]["requests"]
    indices = [f["insertText"]["location"]["index"] for f in fills]
    texts = [f["insertText"]["text"] for f in fills]
    # Highest index first so no insert invalidates a later (lower) target.
    assert indices == [49, 34, 18, 3]
    assert texts == ["D", "C", "B", "A"]
    assert result["tableStartIndex"] == 2
    assert result["cellsFilled"] == 4


def test_create_table_skips_empty_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {"body": {"content": []}}
    client = _RecordingClient([before, _table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.create_table("doc1", 2, 2, data=[["X", ""], ["", "Y"]])

    fills = client.calls[-1]["json"]["requests"]
    indices = [f["insertText"]["location"]["index"] for f in fills]
    texts = [f["insertText"]["text"] for f in fills]
    assert indices == [49, 3]  # only the two non-empty cells, still descending
    assert texts == ["Y", "X"]
    assert result["cellsFilled"] == 2


def test_create_table_no_data_inserts_only(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {"body": {"content": []}}
    client = _RecordingClient([before, _table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.create_table("doc1", 2, 2)

    # Only the insert (GET, POST, GET) — no fill batch when data is omitted.
    methods = [c["method"] for c in client.calls]
    assert methods == ["GET", "POST", "GET"]
    assert result["cellsFilled"] == 0


def test_create_table_at_index_uses_location(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {"body": {"content": []}}
    client = _RecordingClient([before, _table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    adapter.create_table("doc1", 2, 2, index=10)

    insert = client.calls[1]["json"]["requests"][0]["insertTable"]
    assert insert["location"] == {"index": 10, "segmentId": ""}


# ---- edit_cell() ------------------------------------------------------------


def test_edit_cell_clears_then_inserts(monkeypatch: pytest.MonkeyPatch) -> None:
    # cell[1][0]: content[0].startIndex=34, cell endIndex=49 -> clear 34..48.
    client = _RecordingClient([_table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.edit_cell("doc1", "New", row=1, col=0)

    reqs = client.calls[-1]["json"]["requests"]
    # Full range shape, incl. segmentId, is pinned on the delete path too.
    assert reqs[0]["deleteContentRange"]["range"] == {
        "startIndex": 34,
        "endIndex": 48,  # cell.endIndex - 1, preserving the closing newline
        "segmentId": "",
    }
    assert reqs[1]["insertText"] == {
        "text": "New",
        "location": {"index": 34, "segmentId": ""},
    }
    assert result["cleared"] is True


def test_edit_cell_empty_cell_skips_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    # A cell whose only content is the trailing newline: content start == endIndex-1.
    tree = {
        "body": {
            "content": [
                {
                    "startIndex": 2,
                    "endIndex": 20,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"endIndex": 19, "content": [{"startIndex": 18}]}
                                ]
                            }
                        ]
                    },
                }
            ]
        }
    }
    client = _RecordingClient([tree], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.edit_cell("doc1", "Val", row=0, col=0)

    reqs = client.calls[-1]["json"]["requests"]
    assert len(reqs) == 1  # no deleteContentRange for an already-empty cell
    assert reqs[0]["insertText"]["location"]["index"] == 18
    assert result["cleared"] is False


def test_edit_cell_out_of_range_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([_table_2x2_tree()], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    with pytest.raises(IndexError):
        adapter.edit_cell("doc1", "x", row=5, col=0)


# ---- format_matches() -------------------------------------------------------


def _one_run(text: str, start: int) -> dict[str, Any]:
    return {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"startIndex": start, "textRun": {"content": text}}
                        ]
                    }
                }
            ]
        }
    }


def test_format_matches_first_occurrence_derives_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([_one_run("See the Total here", 5)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    style = {
        "bold": True,
        "foregroundColor": {"color": {"rgbColor": {"red": 1.0, "green": 0.0, "blue": 0.0}}},
    }
    result = adapter.format_matches(
        "doc1", "Total", style, all_occurrences=False
    )

    req = client.calls[-1]["json"]["requests"][0]["updateTextStyle"]
    assert req["range"]["startIndex"] == 13  # 5 + len("See the ")
    assert req["range"]["endIndex"] == 18
    assert req["textStyle"] == style
    # Field mask derived from the style keys, sorted.
    assert req["fields"] == "bold,foregroundColor"
    assert result["occurrences"] == 1


def test_format_matches_all_occurrences_descending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([_one_run("go go go", 1)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.format_matches("doc1", "go", {"italic": True})

    starts = [
        r["updateTextStyle"]["range"]["startIndex"]
        for r in client.calls[-1]["json"]["requests"]
    ]
    assert starts == [7, 4, 1]  # descending
    assert result["occurrences"] == 3


def test_format_matches_utf16_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    # A rocket emoji is a UTF-16 surrogate pair (2 code units), so "🚀X" spans 3.
    client = _RecordingClient([_one_run("\U0001F680X", 10)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    adapter.format_matches("doc1", "\U0001F680X", {"bold": True})

    rng = client.calls[-1]["json"]["requests"][0]["updateTextStyle"]["range"]
    assert rng["startIndex"] == 10
    assert rng["endIndex"] == 13  # 10 + 3 UTF-16 units, not 10 + 2 Python chars


def test_format_matches_reset_uses_explicit_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([_one_run("Total", 13)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    # Empty style + explicit fields -> reset the named property to inherited default.
    adapter.format_matches("doc1", "Total", {}, fields="bold")

    req = client.calls[-1]["json"]["requests"][0]["updateTextStyle"]
    assert req["textStyle"] == {}
    assert req["fields"] == "bold"


def test_format_matches_case_insensitive_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([_one_run("Total total", 1)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.format_matches("doc1", "total", {"italic": True})

    assert result["occurrences"] == 2  # matches both cases


def test_format_matches_empty_find_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([_one_run("x", 1)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    with pytest.raises(ValueError, match="non-empty"):
        adapter.format_matches("doc1", "", {"bold": True})


# ---- multi-tab: reads must resolve from the same tab the writes target -------


def _tabbed(tab_id: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    """A documents.get payload (includeTabsContent mode) with one named tab."""
    return {
        "tabs": [
            {
                "tabProperties": {"tabId": tab_id},
                "documentTab": {"body": {"content": content}},
            }
        ]
    }


def test_edit_cell_multitab_reads_and_writes_same_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _table_2x2_tree()["body"]["content"]
    client = _RecordingClient([_tabbed("t2", content)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.edit_cell("doc1", "X", row=1, col=0, tab_id="t2")

    # The index-resolving read must request tab content, not the primary body.
    assert client.calls[0]["params"] == {"includeTabsContent": "true"}
    reqs = client.calls[-1]["json"]["requests"]
    # Both the delete and the insert address tab t2 with indices read FROM t2.
    assert reqs[0]["deleteContentRange"]["range"] == {
        "startIndex": 34,
        "endIndex": 48,
        "segmentId": "",
        "tabId": "t2",
    }
    assert reqs[1]["insertText"]["location"] == {
        "index": 34,
        "segmentId": "",
        "tabId": "t2",
    }
    assert result["cleared"] is True


def test_segment_content_unknown_tab_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([_tabbed("t2", [])], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    with pytest.raises(RuntimeError, match="tab_id"):
        adapter.edit_cell("doc1", "X", row=0, col=0, tab_id="does-not-exist")


# ---- create_table ordinal math with pre-existing tables ---------------------


def test_create_table_at_index_selects_correct_ordinal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two pre-existing tables (startIndex 5 and 100); insert at index 50 sits
    # BETWEEN them -> ordinal = count(startIndex < 50) = 1.
    def tbl(start: int, cell_start: int | None = None) -> dict[str, Any]:
        rows = (
            [{"tableCells": [{"endIndex": cell_start + 9, "content": [{"startIndex": cell_start}]}]}]
            if cell_start is not None
            else []
        )
        return {"startIndex": start, "endIndex": start + 15, "table": {"tableRows": rows}}

    before = {"body": {"content": [tbl(5), tbl(100)]}}
    after = {"body": {"content": [tbl(5), tbl(50, cell_start=60), tbl(120)]}}
    client = _RecordingClient([before, after], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.create_table("doc1", 1, 1, data=[["Z"]], index=50)

    insert = client.calls[1]["json"]["requests"][0]["insertTable"]
    assert insert["location"] == {"index": 50, "segmentId": ""}
    # The fill must land in the NEWLY inserted table (ordinal 1, cell start 60),
    # not table 0 or table 2 — proves the `< index` count picks the right table.
    fills = client.calls[-1]["json"]["requests"]
    assert [f["insertText"]["location"]["index"] for f in fills] == [60]
    assert fills[0]["insertText"]["text"] == "Z"
    assert result["tableStartIndex"] == 50


def test_create_table_keeps_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {"body": {"content": []}}
    after = {
        "body": {
            "content": [
                {
                    "startIndex": 2,
                    "endIndex": 40,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"endIndex": 8, "content": [{"startIndex": 3}]},
                                    {"endIndex": 20, "content": [{"startIndex": 15}]},
                                ]
                            }
                        ]
                    },
                }
            ]
        }
    }
    client = _RecordingClient([before, after], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    # 0 is a real value and must be written; only None / "" are skipped.
    result = adapter.create_table("doc1", 1, 2, data=[[0, ""]])

    fills = client.calls[-1]["json"]["requests"]
    assert [f["insertText"]["text"] for f in fills] == ["0"]
    assert result["cellsFilled"] == 1


# ---- format_matches across multiple runs / non-text gaps --------------------


def _para(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"body": {"content": [{"paragraph": {"elements": elements}}]}}


def test_format_matches_end_does_not_cross_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    # "Total" (5..9), then an inline object at 10 (no textRun), then "s" at 11.
    doc = _para(
        [
            {"startIndex": 5, "textRun": {"content": "Total"}},
            {"startIndex": 10, "inlineObjectElement": {"inlineObjectId": "io"}},
            {"startIndex": 11, "textRun": {"content": "s"}},
        ]
    )
    client = _RecordingClient([doc], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    adapter.format_matches("doc1", "Total", {"bold": True}, all_occurrences=False)

    rng = client.calls[-1]["json"]["requests"][0]["updateTextStyle"]["range"]
    # End = end of the last matched char (10), NOT the next char's start (11).
    assert rng["startIndex"] == 5
    assert rng["endIndex"] == 10


def test_format_matches_spans_two_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # A match that legitimately spans two runs stitches across them.
    doc = _para(
        [
            {"startIndex": 5, "textRun": {"content": "Tot"}},
            {"startIndex": 8, "textRun": {"content": "al"}},
        ]
    )
    client = _RecordingClient([doc], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.format_matches("doc1", "Total", {"italic": True})

    rng = client.calls[-1]["json"]["requests"][0]["updateTextStyle"]["range"]
    assert rng["startIndex"] == 5
    assert rng["endIndex"] == 10
    assert result["occurrences"] == 1


def test_format_matches_first_only_with_multiple_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two occurrences present; all_occurrences=False must stop after the first.
    client = _RecordingClient([_one_run("Total Total", 1)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.format_matches(
        "doc1", "Total", {"bold": True}, all_occurrences=False
    )

    assert result["occurrences"] == 1
    assert len(client.calls[-1]["json"]["requests"]) == 1


def test_format_matches_non_overlapping(monkeypatch: pytest.MonkeyPatch) -> None:
    # re.finditer yields non-overlapping matches: "aa" in "aaa" matches once.
    client = _RecordingClient([_one_run("aaa", 1)], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.format_matches("doc1", "aa", {"bold": True})

    assert result["occurrences"] == 1


# ---- append_text on an empty body (index clamp) -----------------------------


def test_append_text_empty_body_clamps_to_index_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty body -> get_end_index() returns 1 -> insert clamps to 1, not 0.
    client = _RecordingClient([{"body": {"content": []}}], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.append_text("doc1", "First.")

    req = client.calls[-1]["json"]["requests"][0]["insertText"]
    assert req["location"]["index"] == 1
    assert result["index"] == 1
