"""Google Slides API v1 adapter.

The Slides analog of the Docs adapter: read a presentation's slide text and make
targeted edits (deck-wide find/replace, insert text into a shape) without leaving
the MCP boundary. Shares the same OAuth client and Keychain token as the Gmail /
Drive / Docs / Calendar adapters; the existing
``https://www.googleapis.com/auth/drive`` scope already authorizes the Slides
API, so no scope change is needed (the Slides API must, however, be enabled on the
OAuth project; that is verified separately).

Like the sibling adapters, this holds no write guard or audit logic itself; the
server boundary applies ``core.guard`` and ``core.audit`` before / after calling
these methods. Editing a presentation the user can already reach is not
outward-facing, so the writes here ride the per-account auto_write guard exactly
like ``doc_insert_text`` (no separate confirm gate).
"""

from __future__ import annotations

from typing import Any

import httpx

from .gmail import acquire_credentials, FILE_SCOPES
from ..config import GmailAccount

SLIDES_BASE = "https://slides.googleapis.com/v1"


class GoogleSlidesAdapter:
    """Google Slides adapter. Auth refreshed per-call via google-auth."""

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._client = httpx.Client(timeout=60.0)

    # ---- auth --------------------------------------------------------------

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        creds = acquire_credentials(self.account, required_scopes=FILE_SCOPES)
        h = {"Authorization": f"Bearer {creds.token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- read --------------------------------------------------------------

    def get(self, presentation_id: str) -> dict:
        """Fetch a presentation and project a slide-by-slide text summary.

        Returns ``{presentationId, title, slideCount, slides}`` where each slide
        is ``{objectId, text, textBoxes}``. ``textBoxes`` is one entry per shape
        that carries text: ``{objectId, text}``, with ``objectId`` the page
        element's id. That id is what ``insert_text`` targets, so surfacing it
        here is how a caller learns where it can write.
        """
        resp = self._client.get(
            f"{SLIDES_BASE}/presentations/{presentation_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        pres = resp.json()
        slides = self._project_slides(pres)
        return {
            "presentationId": pres.get("presentationId"),
            "title": pres.get("title"),
            "slideCount": len(slides),
            "slides": slides,
        }

    # ---- write -------------------------------------------------------------

    def replace_all_text(
        self, presentation_id: str, find: str, replace: str, match_case: bool = False
    ) -> dict:
        """Replace every occurrence of ``find`` with ``replace`` deck-wide."""
        data = self._batch_update(
            presentation_id,
            [
                {
                    "replaceAllText": {
                        "containsText": {"text": find, "matchCase": match_case},
                        "replaceText": replace,
                    }
                }
            ],
        )
        replies = data.get("replies") or [{}]
        changed = (replies[0].get("replaceAllText") or {}).get("occurrencesChanged", 0)
        return {"presentationId": presentation_id, "occurrencesChanged": changed}

    def insert_text(
        self, presentation_id: str, object_id: str, text: str, index: int = 0
    ) -> dict:
        """Insert ``text`` into the shape ``object_id`` at ``index`` (default 0).

        ``object_id`` identifies a shape on a slide; get it from the
        ``textBoxes`` projection of ``get``. ``index`` is the insertion point
        within that shape's text (0 is the start).
        """
        self._batch_update(
            presentation_id,
            [
                {
                    "insertText": {
                        "objectId": object_id,
                        "insertionIndex": index,
                        "text": text,
                    }
                }
            ],
        )
        return {
            "presentationId": presentation_id,
            "objectId": object_id,
            "inserted": len(text),
            "index": index,
        }

    # ---- helpers -----------------------------------------------------------

    def _batch_update(self, presentation_id: str, requests: list[dict]) -> dict:
        resp = self._client.post(
            f"{SLIDES_BASE}/presentations/{presentation_id}:batchUpdate",
            headers=self._headers(content_type="application/json"),
            json={"requests": requests},
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def _project_slides(cls, pres: dict[str, Any]) -> list[dict]:
        """Project each slide to ``{objectId, text, textBoxes}``.

        Walks ``slides[*].pageElements[*].shape.text.textElements[*].textRun``;
        page elements without ``shape.text`` (images, lines, tables) carry no
        text box and are skipped. The slide-level ``text`` joins the text boxes
        with newlines so a caller can scan the whole slide at a glance.
        """
        slides: list[dict] = []
        for slide in pres.get("slides") or []:
            text_boxes: list[dict] = []
            for element in slide.get("pageElements") or []:
                text = (element.get("shape") or {}).get("text")
                if not text:
                    continue
                text_boxes.append(
                    {
                        "objectId": element.get("objectId"),
                        "text": cls._render_shape_text(text),
                    }
                )
            slides.append(
                {
                    "objectId": slide.get("objectId"),
                    "text": "\n".join(box["text"] for box in text_boxes),
                    "textBoxes": text_boxes,
                }
            )
        return slides

    @staticmethod
    def _render_shape_text(text: dict[str, Any]) -> str:
        """Concatenate every text element's ``textRun.content`` in order."""
        parts: list[str] = []
        for element in text.get("textElements") or []:
            text_run = element.get("textRun")
            if not text_run:
                continue
            parts.append(text_run.get("content") or "")
        return "".join(parts)
