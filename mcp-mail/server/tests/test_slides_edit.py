"""Tests for the Google Slides adapter (``slides_get`` / ``slides_replace_text``
/ ``slides_insert_text``).

Everything is pinned without touching the network or the Keychain: the adapter's
HTTP client and ``_headers`` are stubbed, exactly like the Docs / Drive tests.
Covered:

1. ``get`` projects ``title``, ``slideCount``, and per-slide text plus the
   ``textBoxes`` objectIds, walking each shape's ``textElements[*].textRun``
   (page elements without ``shape.text`` are skipped, as are text elements
   without a ``textRun``).
2. ``replace_all_text`` POSTs a ``replaceAllText`` request carrying
   ``containsText.text``, ``matchCase`` and ``replaceText`` and returns the
   ``occurrencesChanged`` parsed from the canned response.
3. ``insert_text`` POSTs an ``insertText`` request carrying ``objectId``,
   ``insertionIndex`` and ``text`` (default index 0).
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_mail.adapters.gslides import GoogleSlidesAdapter


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

    ``get`` pops the next queued page, falling back to the last payload once
    drained. ``post`` returns a fixed ``batchUpdate`` reply. Every call is
    captured for inspection of the URL and JSON body sent.
    """

    def __init__(
        self, get_pages: list[dict[str, Any]], post_reply: dict[str, Any] | None = None
    ) -> None:
        self._get_pages = list(get_pages)
        self._last_get = get_pages[-1] if get_pages else {}
        self._post_reply = post_reply or {}
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "json": kwargs.get("json")})
        page = self._get_pages.pop(0) if self._get_pages else self._last_get
        return _FakeResponse(page)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "json": kwargs.get("json")})
        return _FakeResponse(self._post_reply)


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch, client: _RecordingClient
) -> GoogleSlidesAdapter:
    adapter = GoogleSlidesAdapter(_FakeAccount())  # type: ignore[arg-type]
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching the Keychain / google-auth refresh in ``_headers``.
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer test"}
    )
    return adapter


# A canned presentations.get payload: one slide with two shapes that carry text
# (the first with two text runs, the second with a paragraphMarker element that
# has no textRun and must be skipped) plus an image page element with no
# ``shape.text`` that must be skipped entirely.
_PRES = {
    "presentationId": "pres1",
    "title": "Quarterly review",
    "slides": [
        {
            "objectId": "slide1",
            "pageElements": [
                {
                    "objectId": "shape1",
                    "shape": {
                        "text": {
                            "textElements": [
                                {"textRun": {"content": "Hello "}},
                                {"textRun": {"content": "world"}},
                            ]
                        }
                    },
                },
                {
                    "objectId": "image1",
                    "image": {"contentUrl": "https://example.com/x.png"},
                },
                {
                    "objectId": "shape2",
                    "shape": {
                        "text": {
                            "textElements": [
                                {"paragraphMarker": {}},
                                {"textRun": {"content": "Second box"}},
                            ]
                        }
                    },
                },
            ],
        }
    ],
}


# ---- get() projection -------------------------------------------------------


def test_get_projects_title_and_textboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([_PRES])
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.get("pres1")

    assert result["presentationId"] == "pres1"
    assert result["title"] == "Quarterly review"
    assert result["slideCount"] == 1

    slide = result["slides"][0]
    assert slide["objectId"] == "slide1"
    # Two text boxes; the image page element (no shape.text) is skipped, and the
    # objectIds carried are the page-element ids insert_text targets.
    assert [box["objectId"] for box in slide["textBoxes"]] == ["shape1", "shape2"]
    # Runs concatenated in order within a shape; the paragraphMarker is skipped.
    assert slide["textBoxes"][0]["text"] == "Hello world"
    assert slide["textBoxes"][1]["text"] == "Second box"
    # Slide-level text joins the boxes.
    assert slide["text"] == "Hello world\nSecond box"
    # The GET hit the presentations endpoint for this id.
    assert client.calls[0]["method"] == "GET"
    assert client.calls[0]["url"].endswith("/presentations/pres1")


# ---- replace_all_text() -----------------------------------------------------


def test_replace_all_text_request_and_count(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"replies": [{"replaceAllText": {"occurrencesChanged": 4}}]}
    client = _RecordingClient([], post_reply=reply)
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.replace_all_text("pres1", "foo", "bar", match_case=True)

    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/presentations/pres1:batchUpdate")
    req = post["json"]["requests"][0]["replaceAllText"]
    assert req["containsText"] == {"text": "foo", "matchCase": True}
    assert req["replaceText"] == "bar"
    assert result == {"presentationId": "pres1", "occurrencesChanged": 4}


def test_replace_all_text_defaults_zero_when_no_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.replace_all_text("pres1", "x", "y")

    # match_case defaults to false; a reply-less response means 0 changed.
    req = client.calls[-1]["json"]["requests"][0]["replaceAllText"]
    assert req["containsText"]["matchCase"] is False
    assert result["occurrencesChanged"] == 0


# ---- insert_text() ----------------------------------------------------------


def test_insert_text_posts_batch_update(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.insert_text("pres1", "shape1", "Intro. ", index=3)

    post = client.calls[-1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/presentations/pres1:batchUpdate")
    req = post["json"]["requests"][0]["insertText"]
    assert req == {"objectId": "shape1", "insertionIndex": 3, "text": "Intro. "}
    assert result == {
        "presentationId": "pres1",
        "objectId": "shape1",
        "inserted": len("Intro. "),
        "index": 3,
    }


def test_insert_text_defaults_to_index_0(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([], post_reply={})
    adapter = _make_adapter(monkeypatch, client)

    result = adapter.insert_text("pres1", "shape1", "X")

    req = client.calls[-1]["json"]["requests"][0]["insertText"]
    assert req["insertionIndex"] == 0
    assert result["index"] == 0
