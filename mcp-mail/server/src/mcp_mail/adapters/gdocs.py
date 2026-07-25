"""Google Docs API v1 adapter.

Rounds out the Google surface: read a Doc's text and make targeted edits
(insert, append, find/replace) without leaving the MCP boundary. Shares the same
OAuth client and Keychain token as the Gmail / Drive / Calendar adapters; the
existing ``https://www.googleapis.com/auth/drive`` scope already authorizes the
Docs API, so no scope change is needed (the Docs API must, however, be enabled on
the OAuth project; that is verified separately).

Like the sibling adapters, this holds no write guard or audit logic itself; the
server boundary applies ``core.guard`` and ``core.audit`` before / after calling
these methods. Editing a Doc the user can already reach is not outward-facing, so
the writes here ride the per-account auto_write guard exactly like ``drive_update``
(no separate confirm gate).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .gmail import acquire_credentials
from ..config import GmailAccount

DOCS_BASE = "https://docs.googleapis.com/v1"


class GoogleDocsAdapter:
    """Google Docs adapter. Auth refreshed per-call via google-auth."""

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._client = httpx.Client(timeout=60.0)

    # ---- auth --------------------------------------------------------------

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        creds = acquire_credentials(self.account)
        h = {"Authorization": f"Bearer {creds.token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- read --------------------------------------------------------------

    def get(self, document_id: str) -> dict:
        """Fetch a document and project ``{documentId, title, text}``.

        ``text`` is a plain-text rendering: every paragraph element's
        ``textRun.content`` concatenated in document order. Elements without a
        ``textRun`` (inline objects, page breaks, equations) carry no text and
        are skipped.
        """
        resp = self._client.get(
            f"{DOCS_BASE}/documents/{document_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        doc = resp.json()
        return {
            "documentId": doc.get("documentId"),
            "title": doc.get("title"),
            "text": self._render_text(doc),
        }

    def get_end_index(self, document_id: str) -> int:
        """Return the ``endIndex`` of the body's last structural element.

        The body content is a list of structural elements; the final element's
        ``endIndex`` is one past the document's last character (the trailing
        newline that always closes the body). ``append_text`` inserts just before
        it. Defaults to 1 for an empty body so an append still lands at the start.
        """
        resp = self._client.get(
            f"{DOCS_BASE}/documents/{document_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        content = (resp.json().get("body") or {}).get("content") or []
        if not content:
            return 1
        return int(content[-1].get("endIndex", 1))

    # ---- write -------------------------------------------------------------

    def insert_text(self, document_id: str, text: str, index: int = 1) -> dict:
        """Insert ``text`` at ``index`` (default 1, the start of the body).

        Index 0 is the document start sentinel and is not insertable, so the body
        begins at index 1.
        """
        self._batch_update(
            document_id,
            [{"insertText": {"location": {"index": index}, "text": text}}],
        )
        return {"documentId": document_id, "inserted": len(text), "index": index}

    def append_text(self, document_id: str, text: str) -> dict:
        """Append ``text`` at the end of the body.

        Computes the body's end via ``get_end_index`` (the last element's
        ``endIndex``), then inserts at ``end_index - 1``: the position just before
        the final newline that closes the body, so the appended text lands inside
        the document rather than after its terminating boundary.
        """
        end_index = self.get_end_index(document_id)
        index = max(end_index - 1, 1)
        self._batch_update(
            document_id,
            [{"insertText": {"location": {"index": index}, "text": text}}],
        )
        return {"documentId": document_id, "inserted": len(text), "index": index}

    def replace_all_text(
        self, document_id: str, find: str, replace: str, match_case: bool = False
    ) -> dict:
        """Replace every occurrence of ``find`` with ``replace`` across the doc."""
        data = self._batch_update(
            document_id,
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
        return {"documentId": document_id, "occurrencesChanged": changed}

    # ---- structured read + full-power writes -------------------------------

    def get_structured(
        self,
        document_id: str,
        fields: str | None = None,
        include_tabs: bool = False,
    ) -> dict:
        """Return the raw Docs ``documents.get`` JSON (full structural tree).

        Unlike :meth:`get` (a flattened plain-text projection), this exposes the
        element tree — paragraphs, tables, table rows / cells with their start &
        end indices, and styles — which is what index-based edits are computed
        against. ``fields`` is the Docs partial-response mask sent as the URL
        ``fields`` query parameter (e.g. ``body.content(startIndex,endIndex,table)``)
        to bound large payloads; ``include_tabs`` sets ``includeTabsContent=true``
        for multi-tab documents.
        """
        return self._get_raw(document_id, fields=fields, include_tabs=include_tabs)

    def create(self, title: str) -> dict:
        """Create a new empty Doc titled ``title`` (in the account's My Drive).

        The Docs API ignores any body supplied at creation, so this only sets the
        title; add content with :meth:`batch_update` or the table / format helpers.
        Returns ``{documentId, title, revisionId}``.
        """
        resp = self._client.post(
            f"{DOCS_BASE}/documents",
            headers=self._headers(content_type="application/json"),
            json={"title": title},
        )
        resp.raise_for_status()
        doc = resp.json()
        return {
            "documentId": doc.get("documentId"),
            "title": doc.get("title"),
            "revisionId": doc.get("revisionId"),
        }

    def batch_update(
        self,
        document_id: str,
        requests: list[dict],
        write_control: dict | None = None,
    ) -> dict:
        """Apply raw Docs ``batchUpdate`` requests; the full-power passthrough.

        ``requests`` is forwarded verbatim (no reordering or rewriting), so every
        request type in the Docs API ``Request`` union is reachable. ``batchUpdate``
        is atomic and sequential: an invalid request rejects the whole batch, and
        each request sees the state left by the prior ones, so multiple index-based
        edits should be ordered highest-index-first by the caller. ``write_control``
        (``{"requiredRevisionId": ...}`` or ``{"targetRevisionId": ...}``) is
        attached when given.
        """
        body: dict[str, Any] = {"requests": requests}
        if write_control:
            body["writeControl"] = write_control
        resp = self._client.post(
            f"{DOCS_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    def _batch_update(self, document_id: str, requests: list[dict]) -> dict:
        """Back-compat internal alias used by the text-level helpers."""
        return self.batch_update(document_id, requests)

    def create_table(
        self,
        document_id: str,
        rows: int,
        columns: int,
        data: list[list[Any]] | None = None,
        index: int | None = None,
        tab_id: str | None = None,
    ) -> dict:
        """Insert a ``rows`` by ``columns`` table and optionally fill it from ``data``.

        Index-safe by construction. The table is inserted (appended at the end of
        the body by default, or at ``index`` if given) in its own ``batchUpdate``;
        the document is then re-fetched to read each cell's true insertion index
        (cell indices do not exist until the table does), and the cell text is
        written in a single ``batchUpdate`` ordered highest-index-first so no insert
        shifts a later target. ``data`` is row-major; empty / falsy cells are
        skipped. Returns ``{documentId, tableStartIndex, rows, columns, cellsFilled}``.
        """
        tables_before = self._tables(
            self._segment_content(
                document_id, "body.content(startIndex,table)", tab_id
            )
        )
        if index is None:
            ordinal = len(tables_before)
            location_req: dict[str, Any] = {"endOfSegmentLocation": self._end_loc(tab_id)}
        else:
            ordinal = sum(1 for t in tables_before if t.get("startIndex", 0) < index)
            location_req = {"location": self._loc(index, tab_id)}

        self.batch_update(
            document_id,
            [{"insertTable": {"rows": rows, "columns": columns, **location_req}}],
        )

        tables_after = self._tables(
            self._segment_content(
                document_id, "body.content(startIndex,endIndex,table)", tab_id
            )
        )
        if ordinal >= len(tables_after):
            raise RuntimeError(
                "create_table: inserted table not found after re-fetch "
                f"(expected ordinal {ordinal}, doc has {len(tables_after)} tables)."
            )
        target = tables_after[ordinal]
        table_start = target.get("startIndex")

        fills: list[dict] = []
        if data:
            table_rows = (target.get("table") or {}).get("tableRows") or []
            for r in range(min(rows, len(table_rows))):
                cells = table_rows[r].get("tableCells") or []
                row_data = data[r] if r < len(data) else []
                for c in range(min(columns, len(cells))):
                    value = row_data[c] if c < len(row_data) else None
                    # Skip only genuinely absent cells; keep falsy-but-real values
                    # like 0 / False (written via str()), never silently dropped.
                    if value is None or value == "":
                        continue
                    cell_index = cells[c]["content"][0]["startIndex"]
                    fills.append(
                        {
                            "insertText": {
                                "text": str(value),
                                "location": self._loc(cell_index, tab_id),
                            }
                        }
                    )
            # Highest index first: an insert only shifts indices at or after it, and
            # every cell index was read from the same pre-fill snapshot, so filling
            # the tail cells first keeps the lower ones exactly valid.
            fills.sort(key=lambda q: q["insertText"]["location"]["index"], reverse=True)
            if fills:
                self.batch_update(document_id, fills)

        return {
            "documentId": document_id,
            "tableStartIndex": table_start,
            "rows": rows,
            "columns": columns,
            "cellsFilled": len(fills),
        }

    def edit_cell(
        self,
        document_id: str,
        text: str,
        row: int,
        col: int,
        table_ordinal: int = 0,
        tab_id: str | None = None,
    ) -> dict:
        """Set table cell ``[row][col]``'s text, clearing existing content first.

        ``table_ordinal`` selects which table in the document (0-based, document
        order). The cell's existing content is removed with ``deleteContentRange``
        (preserving the mandatory trailing newline that closes every cell) and the
        new text inserted, both in one ``batchUpdate``. A cell that holds only its
        newline is filled without a delete. Returns
        ``{documentId, tableOrdinal, row, col, cleared}``.
        """
        tables = self._tables(
            self._segment_content(
                document_id, "body.content(startIndex,endIndex,table)", tab_id
            )
        )
        if table_ordinal < 0 or table_ordinal >= len(tables):
            raise IndexError(
                f"edit_cell: table_ordinal {table_ordinal} out of range "
                f"(doc has {len(tables)} tables)."
            )
        table = tables[table_ordinal].get("table") or {}
        table_rows = table.get("tableRows") or []
        if row < 0 or row >= len(table_rows):
            raise IndexError(
                f"edit_cell: row {row} out of range ({len(table_rows)} rows)."
            )
        cells = table_rows[row].get("tableCells") or []
        if col < 0 or col >= len(cells):
            raise IndexError(
                f"edit_cell: col {col} out of range ({len(cells)} columns)."
            )
        cell = cells[col]
        clear_start = cell["content"][0]["startIndex"]
        clear_end = cell["endIndex"] - 1

        reqs: list[dict] = []
        cleared = clear_start < clear_end
        if cleared:
            reqs.append(
                {"deleteContentRange": {"range": self._range(clear_start, clear_end, tab_id)}}
            )
        reqs.append(
            {"insertText": {"text": text, "location": self._loc(clear_start, tab_id)}}
        )
        self.batch_update(document_id, reqs)
        return {
            "documentId": document_id,
            "tableOrdinal": table_ordinal,
            "row": row,
            "col": col,
            "cleared": cleared,
        }

    def format_matches(
        self,
        document_id: str,
        find: str,
        text_style: dict,
        fields: str | None = None,
        match_case: bool = False,
        all_occurrences: bool = True,
        tab_id: str | None = None,
    ) -> dict:
        """Apply ``text_style`` to occurrences of ``find`` in the body.

        Locates the substring against a run-stitched projection of the body (so a
        match may span multiple text runs) and emits one ``updateTextStyle`` per
        match. The update field-mask defaults to the sorted keys of ``text_style``;
        pass ``fields`` explicitly to override (e.g. to RESET a property, name it in
        ``fields`` while omitting it from ``text_style``). Indices are computed in
        UTF-16 code units to match the Docs API; style edits do not change length.
        Returns ``{documentId, occurrences}``.
        """
        if not find:
            raise ValueError("format_matches: 'find' must be a non-empty string.")
        content = self._segment_content(
            document_id, "body.content(startIndex,endIndex,paragraph)", tab_id
        )
        text, starts, ends = self._flatten_runs(content)
        mask = fields if fields is not None else ",".join(sorted(text_style.keys()))
        flags = 0 if match_case else re.IGNORECASE

        reqs: list[dict] = []
        occurrences = 0
        for m in re.finditer(re.escape(find), text, flags):
            reqs.append(
                {
                    "updateTextStyle": {
                        # End = end of the LAST matched char (not the next char's
                        # start), so a match ending at a run boundary never extends
                        # the style range across a following non-text gap.
                        "range": self._range(starts[m.start()], ends[m.end() - 1], tab_id),
                        "textStyle": text_style,
                        "fields": mask,
                    }
                }
            )
            occurrences += 1
            if not all_occurrences:
                break
        reqs.sort(key=lambda q: q["updateTextStyle"]["range"]["startIndex"], reverse=True)
        if reqs:
            self.batch_update(document_id, reqs)
        return {"documentId": document_id, "occurrences": occurrences}

    # ---- helpers -----------------------------------------------------------

    def _get_raw(
        self,
        document_id: str,
        fields: str | None = None,
        include_tabs: bool = False,
    ) -> dict:
        """Fetch ``documents.get`` and return the raw JSON.

        ``fields`` (Docs partial-response mask) and ``include_tabs`` are sent as URL
        query parameters when set.
        """
        params: dict[str, str] = {}
        if fields:
            params["fields"] = fields
        if include_tabs:
            params["includeTabsContent"] = "true"
        resp = self._client.get(
            f"{DOCS_BASE}/documents/{document_id}",
            headers=self._headers(),
            params=params or None,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _utf16_len(s: str) -> int:
        """Length of ``s`` in UTF-16 code units (the Docs API index unit)."""
        return len(s.encode("utf-16-le")) // 2

    @staticmethod
    def _loc(index: int, tab_id: str | None) -> dict:
        loc: dict[str, Any] = {"index": index, "segmentId": ""}
        if tab_id:
            loc["tabId"] = tab_id
        return loc

    @staticmethod
    def _end_loc(tab_id: str | None) -> dict:
        loc: dict[str, Any] = {"segmentId": ""}
        if tab_id:
            loc["tabId"] = tab_id
        return loc

    @staticmethod
    def _range(start: int, end: int, tab_id: str | None) -> dict:
        rng: dict[str, Any] = {"startIndex": start, "endIndex": end, "segmentId": ""}
        if tab_id:
            rng["tabId"] = tab_id
        return rng

    def _segment_content(
        self, document_id: str, fields: str | None, tab_id: str | None
    ) -> list[dict]:
        """Content list of the segment an edit targets, so reads match writes.

        For the primary / no-tab case this is the top-level ``body.content`` (bounded
        by ``fields``). For a specific ``tab_id`` the document is fetched with
        ``includeTabsContent=true`` (in that mode the top-level ``body`` is empty) and
        the matching tab's ``documentTab.body.content`` is returned. Resolving indices
        from the *same* segment the write addresses prevents cross-tab corruption.
        """
        if not tab_id:
            doc = self._get_raw(document_id, fields=fields)
            return (doc.get("body") or {}).get("content") or []
        doc = self._get_raw(document_id, include_tabs=True)
        tab = self._find_tab(doc.get("tabs"), tab_id)
        if tab is None:
            raise RuntimeError(f"tab_id {tab_id!r} not found in document.")
        return ((tab.get("documentTab") or {}).get("body") or {}).get("content") or []

    @classmethod
    def _find_tab(cls, tabs: list[dict] | None, tab_id: str) -> dict | None:
        """Depth-first search for the Tab whose ``tabProperties.tabId`` matches."""
        for tab in tabs or []:
            props = tab.get("tabProperties") or {}
            if props.get("tabId") == tab_id:
                return tab
            found = cls._find_tab(tab.get("childTabs"), tab_id)
            if found is not None:
                return found
        return None

    @staticmethod
    def _tables(content: list[dict]) -> list[dict]:
        """Structural elements that are tables, in document order."""
        return [e for e in content if e.get("table")]

    @classmethod
    def _flatten_runs(
        cls, content: list[dict]
    ) -> tuple[str, list[int], list[int]]:
        """Stitch text runs into ``(text, starts, ends)``.

        ``text`` concatenates every ``textRun.content`` in order. ``starts[i]`` and
        ``ends[i]`` are the absolute Docs (UTF-16) indices bounding character ``i`` of
        ``text`` (``ends[i]`` is one past it). A match spanning Python positions
        ``[a, b)`` maps to the Docs range ``[starts[a], ends[b - 1]]`` — using the
        end of the last matched character (rather than the next character's start)
        keeps the range correct even when the following element is a non-text node
        (inline object, page break) at a discontiguous index. Each run resets to its
        own ``startIndex`` so those gaps never distort the mapping.
        """
        parts: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for element in content:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for run_element in paragraph.get("elements") or []:
                text_run = run_element.get("textRun")
                if not text_run:
                    continue
                run_text = text_run.get("content") or ""
                abs_i = run_element.get("startIndex")
                if abs_i is None:
                    continue
                for ch in run_text:
                    starts.append(abs_i)
                    abs_i += cls._utf16_len(ch)
                    ends.append(abs_i)
                    parts.append(ch)
        return "".join(parts), starts, ends

    @staticmethod
    def _render_text(doc: dict[str, Any]) -> str:
        """Concatenate every paragraph element's ``textRun.content``."""
        parts: list[str] = []
        content = (doc.get("body") or {}).get("content") or []
        for element in content:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for run_element in paragraph.get("elements") or []:
                text_run = run_element.get("textRun")
                if not text_run:
                    continue
                parts.append(text_run.get("content") or "")
        return "".join(parts)
