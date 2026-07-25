"""Google Drive v3 (files) + Sheets v4 (cells) adapter.

This is the core deliverable of the expansion: it unblocks the gym-log use case
(open a Sheet by id, append rows, read them back) that the on-disk ``.gsheet``
pointer made impossible. Two REST surfaces share one OAuth client and one
Keychain token with the Gmail adapter (see ``gmail.acquire_credentials`` and the
unioned ``SCOPES`` there):

- Drive v3 ``files`` for list / search / read / create / update / move / copy /
  trash / share, with the Google native-format mapper from ``core.native_format``
  deciding how each mime degrades.
- Sheets v4 ``spreadsheets.values`` (and ``batchUpdate``) for cell-level read /
  write / append, the only path that can edit a native Sheet.

The adapter holds no write guard or audit logic itself; the server boundary
applies ``core.guard`` and ``core.audit`` before/after calling these methods, so
the same rails cover every backend uniformly.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx

from .gmail import acquire_credentials, FILE_SCOPES
from ..config import GmailAccount
from ..core import native_format as nf

DRIVE_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Fields we ask Drive to return for a file. Kept in one place so list / search /
# metadata stay consistent.
FILE_FIELDS = (
    "id,name,mimeType,size,parents,modifiedTime,createdTime,"
    "trashed,webViewLink,owners(emailAddress),shared"
)


class GoogleDriveAdapter:
    """Google Drive + Sheets adapter. Auth refreshed per-call via google-auth."""

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._client = httpx.Client(timeout=120.0)

    # ---- auth --------------------------------------------------------------

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        creds = acquire_credentials(self.account, required_scopes=FILE_SCOPES)
        h = {"Authorization": f"Bearer {creds.token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- backend status ----------------------------------------------------

    def auth_status(self) -> dict:
        """Cheap probe: does the account have a usable token + Drive access?

        Used by ``drive_list_backends``. Never raises; returns a status dict so
        an unconsented account shows up as needing re-auth rather than crashing
        the listing.
        """
        try:
            resp = self._client.get(
                f"{DRIVE_BASE}/about",
                headers=self._headers(),
                params={"fields": "user(emailAddress,displayName),storageQuota(usage,limit)"},
            )
            resp.raise_for_status()
            about = resp.json()
            return {
                "ok": True,
                "user": (about.get("user") or {}).get("emailAddress"),
                "storage": about.get("storageQuota"),
            }
        except Exception as e:
            # A status probe must surface "needs re-auth", not crash the listing.
            return {"ok": False, "error": str(e)}

    # ---- Drive files: read-side -------------------------------------------

    def list(self, path: str | None = None, page: str | None = None) -> dict:
        """List a folder's children. `path` is a Drive folder id (None = root)."""
        parent = path or "root"
        params: dict[str, str | int] = {
            "q": f"'{parent}' in parents and trashed = false",
            "fields": f"nextPageToken,files({FILE_FIELDS})",
            "pageSize": 100,
            "orderBy": "folder,name",
            # Reach Shared Drives: corpora=allDrives requires both flags below.
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "corpora": "allDrives",
        }
        if page:
            params["pageToken"] = page
        resp = self._client.get(f"{DRIVE_BASE}/files", headers=self._headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        return {
            "files": [self._project_file(f) for f in data.get("files", [])],
            "nextPageToken": data.get("nextPageToken"),
        }

    def search(self, query: str, limit: int = 25) -> list[dict]:
        """Search by name / full text, name-first and relevance-ordered.

        Two Drive passes merged, instead of one recency-ordered pass: a
        ``name contains`` pass first, then a ``fullText contains`` pass for the
        ids the name pass did not already return. Exact / substring name matches
        are what a user means most of the time, so they rank first; content-only
        matches still come through, just after. Neither pass forces
        ``orderBy="modifiedTime desc"``: a single recency-ordered pass capped at
        ``limit`` buried a name match (proven cases: a 2023 "SI Q2 2026 strategy"
        and "Quarterly Idea Gathering Meeting Template") under hundreds of newer
        full-text hits. Omitting the forced ordering lets Drive rank by relevance
        within each pass.
        """
        # Escape single quotes inside the user query for the Drive `q` grammar.
        safe = query.replace("'", "\\'")
        name_hits = self._search_pass(f"name contains '{safe}' and trashed = false", limit)
        text_hits = self._search_pass(f"fullText contains '{safe}' and trashed = false", limit)

        # Name hits first; then full-text hits whose id is not already present.
        merged: list[dict] = []
        seen: set[str] = set()
        for f in (*name_hits, *text_hits):
            fid = f.get("id")
            if fid in seen:
                continue
            seen.add(fid)
            merged.append(f)
        return [self._project_file(f) for f in merged[:limit]]

    def _search_pass(self, q: str, limit: int) -> list[dict]:
        """Run one ``files.list`` relevance pass for ``search`` and return raw files.

        No ``orderBy`` is set, so Drive returns by relevance rather than recency.
        Carries the same ``pageSize``, shared-drive params, and projection fields
        that both ``search`` passes share.
        """
        params: dict[str, str | int] = {
            "q": q,
            "fields": f"files({FILE_FIELDS})",
            "pageSize": min(limit, 100),
            # Reach Shared Drives: corpora=allDrives requires both flags below.
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "corpora": "allDrives",
        }
        resp = self._client.get(f"{DRIVE_BASE}/files", headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json().get("files", [])

    def get_metadata(self, ref: str) -> dict:
        resp = self._client.get(
            f"{DRIVE_BASE}/files/{ref}",
            headers=self._headers(),
            params={"fields": FILE_FIELDS, "supportsAllDrives": "true"},
        )
        resp.raise_for_status()
        return self._project_file(resp.json())

    def list_comments(self, ref: str) -> list[dict]:
        """List comments (and replies) on a Drive file, newest pagination merged.

        Walks every ``comments.list`` page (following ``nextPageToken`` as
        ``pageToken``) and projects each comment through ``_project_comment``.
        Note: ``supportsAllDrives`` is deliberately NOT sent; it is not a valid
        param for ``comments.list`` and the endpoint reaches Shared Drive files
        without it. Drive often exposes only ``author.displayName`` (no email),
        so the projection tolerates a missing ``emailAddress``.
        """
        fields = (
            "comments(id,author(displayName,emailAddress,me),content,htmlContent,"
            "createdTime,modifiedTime,resolved,quotedFileContent(value),"
            "replies(id,author(displayName,emailAddress),content,createdTime,"
            "modifiedTime,action)),nextPageToken"
        )
        comments: list[dict] = []
        page_token: str | None = None
        while True:
            params: dict[str, str | int] = {
                "fields": fields,
                "pageSize": 100,
                "includeDeleted": "false",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self._client.get(
                f"{DRIVE_BASE}/files/{ref}/comments",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            comments.extend(self._project_comment(c) for c in data.get("comments", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return comments

    def read(self, ref: str, target_dir: str | None = None) -> dict:
        """Read a file's content. Google-native types are exported (spec section 6).

        Returns a dict describing what happened: for a binary file, the bytes
        are written under `target_dir` (default $TMPDIR/mcp-mail-drive) and the
        path returned; for a Doc/Slides, the export is written likewise; for a
        Sheet, the caller is routed to ``sheet_read`` (a CSV snapshot path is
        still provided for a read-only glance).
        """
        meta = self.get_metadata(ref)
        mime = meta.get("mimeType")
        plan = nf.read_plan(mime)
        out_dir = Path(target_dir).expanduser() if target_dir else (
            Path(tempfile_gettempdir()) / "mcp-mail-drive"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        if plan.read_strategy == "binary":
            resp = self._client.get(
                f"{DRIVE_BASE}/files/{ref}",
                headers=self._headers(),
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            resp.raise_for_status()
            dest = out_dir / _safe_name(meta.get("name") or ref)
            dest.write_bytes(resp.content)
            return {"ref": ref, "mode": "binary", "path": str(dest), "metadata": meta}

        # Native export (Docs/Slides) or the read-only Sheet snapshot.
        export_mime = plan.export_mime or "text/plain"
        resp = self._client.get(
            f"{DRIVE_BASE}/files/{ref}/export",
            headers=self._headers(),
            params={"mimeType": export_mime, "supportsAllDrives": "true"},
        )
        resp.raise_for_status()
        suffix = _suffix_for_mime(export_mime)
        dest = out_dir / (_safe_name(meta.get("name") or ref) + suffix)
        dest.write_bytes(resp.content)
        result = {
            "ref": ref,
            "mode": plan.read_strategy,
            "exportMime": export_mime,
            "path": str(dest),
            "metadata": meta,
        }
        if plan.read_strategy == "route_sheet":
            result["note"] = (
                "This is a Google Sheet. The exported CSV above is a read-only "
                "snapshot of the first tab. To read or edit cells, use sheet_get "
                "/ sheet_read / sheet_write / sheet_append with this spreadsheet_id."
            )
            result["spreadsheet_id"] = ref
        return result

    # ---- Drive files: write-side ------------------------------------------

    def create(
        self,
        name: str,
        parent: str | None = None,
        content: str | None = None,
        mime: str | None = None,
    ) -> dict:
        """Create a folder, an empty native file, or a file with text/byte content.

        - ``mime='application/vnd.google-apps.folder'`` -> a folder.
        - a Google native mime with no content -> an empty native doc/sheet
          (populate a Sheet afterwards via ``sheet_*``).
        - otherwise -> a regular file; `content` (a string) is uploaded as bytes.
        """
        metadata: dict[str, Any] = {"name": name}
        if parent:
            metadata["parents"] = [parent]
        if mime:
            metadata["mimeType"] = mime

        if content is None or nf.is_folder(mime) or nf.is_google_native(mime):
            # Metadata-only create (folder or empty native file).
            resp = self._client.post(
                f"{DRIVE_BASE}/files",
                headers=self._headers(content_type="application/json"),
                params={"fields": FILE_FIELDS, "supportsAllDrives": "true"},
                json=metadata,
            )
            resp.raise_for_status()
            return self._project_file(resp.json())

        # Multipart upload of a regular file with content.
        upload_mime = mime or _guess_mime(name)
        files = {
            "metadata": ("metadata", _json_bytes(metadata), "application/json; charset=UTF-8"),
            "file": (name, content.encode("utf-8"), upload_mime),
        }
        resp = self._client.post(
            f"{DRIVE_UPLOAD_BASE}/files",
            headers=self._headers(),
            params={
                "uploadType": "multipart",
                "fields": FILE_FIELDS,
                "supportsAllDrives": "true",
            },
            files=files,
        )
        resp.raise_for_status()
        return self._project_file(resp.json())

    def update(self, ref: str, content: str) -> dict:
        """Replace a file's bytes/text. Refuses Google-native types (spec section 6).

        Native Sheets must go through ``sheet_write`` / ``sheet_append``; native
        Docs/Slides are read-only in v0.1. ``core.native_format`` raises a clear,
        actionable error for those instead of clobbering the pointer.
        """
        meta = self.get_metadata(ref)
        mime = meta.get("mimeType")
        nf.assert_byte_writable(mime)  # raises for native types
        upload_mime = mime or _guess_mime(meta.get("name") or ref)
        resp = self._client.patch(
            f"{DRIVE_UPLOAD_BASE}/files/{ref}",
            headers=self._headers(content_type=upload_mime),
            params={
                "uploadType": "media",
                "fields": FILE_FIELDS,
                "supportsAllDrives": "true",
            },
            content=content.encode("utf-8"),
        )
        resp.raise_for_status()
        return self._project_file(resp.json())

    def move(self, ref: str, dest: str) -> dict:
        """Move and/or rename. `dest` is 'folder_id' or 'folder_id/new name'."""
        new_parent, _, new_name = dest.partition("/")
        meta = self.get_metadata(ref)
        old_parents = ",".join(meta.get("parents") or [])
        params: dict[str, str] = {"fields": FILE_FIELDS, "supportsAllDrives": "true"}
        if new_parent:
            params["addParents"] = new_parent
        if old_parents:
            params["removeParents"] = old_parents
        body: dict[str, str] = {}
        if new_name:
            body["name"] = new_name
        resp = self._client.patch(
            f"{DRIVE_BASE}/files/{ref}",
            headers=self._headers(content_type="application/json"),
            params=params,
            json=body,
        )
        resp.raise_for_status()
        return self._project_file(resp.json())

    def copy(self, ref: str, dest: str) -> dict:
        """Copy a file. `dest` is 'parent_folder_id' or 'parent_folder_id/new name'."""
        new_parent, _, new_name = dest.partition("/")
        body: dict[str, Any] = {}
        if new_parent:
            body["parents"] = [new_parent]
        if new_name:
            body["name"] = new_name
        resp = self._client.post(
            f"{DRIVE_BASE}/files/{ref}/copy",
            headers=self._headers(content_type="application/json"),
            params={"fields": FILE_FIELDS, "supportsAllDrives": "true"},
            json=body,
        )
        resp.raise_for_status()
        return self._project_file(resp.json())

    def delete(self, ref: str) -> dict:
        """Send to Drive trash (reversible). Never hard-deletes (spec section 10)."""
        resp = self._client.patch(
            f"{DRIVE_BASE}/files/{ref}",
            headers=self._headers(content_type="application/json"),
            params={"fields": "id,name,trashed", "supportsAllDrives": "true"},
            json={"trashed": True},
        )
        resp.raise_for_status()
        return {"ref": ref, "trashed": True}

    def share(self, ref: str, principal: str, role: str) -> dict:
        """Grant a permission. Outward-facing: gated at the server boundary."""
        body = {
            "type": "user" if "@" in principal else "anyone",
            "role": role,
        }
        if "@" in principal:
            body["emailAddress"] = principal
        resp = self._client.post(
            f"{DRIVE_BASE}/files/{ref}/permissions",
            headers=self._headers(content_type="application/json"),
            params={"sendNotificationEmail": "false", "supportsAllDrives": "true"},
            json=body,
        )
        resp.raise_for_status()
        return {"ref": ref, "principal": principal, "role": role, "permission": resp.json()}

    # ---- Drive comments: write-side ---------------------------------------
    #
    # The comments surface works uniformly across Docs / Sheets / Slides. As with
    # ``list_comments``, ``supportsAllDrives`` is deliberately NOT sent: it is not
    # a valid param on the comments endpoints, which reach Shared Drive files
    # without it. Every write asks Drive back for a ``fields`` projection so the
    # adapter returns a clean dict rather than the raw resource.

    def add_comment(self, ref: str, content: str) -> dict:
        """Create a new top-level comment on a file. Returns a projected comment."""
        fields = "id,author(displayName,emailAddress),content,createdTime,resolved"
        resp = self._client.post(
            f"{DRIVE_BASE}/files/{ref}/comments",
            headers=self._headers(content_type="application/json"),
            params={"fields": fields},
            json={"content": content},
        )
        resp.raise_for_status()
        return self._project_comment(resp.json())

    def reply_comment(self, ref: str, comment_id: str, content: str) -> dict:
        """Reply to an existing comment. Returns a projected reply."""
        fields = "id,author(displayName),content,createdTime,action"
        resp = self._client.post(
            f"{DRIVE_BASE}/files/{ref}/comments/{comment_id}/replies",
            headers=self._headers(content_type="application/json"),
            params={"fields": fields},
            json={"content": content},
        )
        resp.raise_for_status()
        return self._project_reply(resp.json())

    def resolve_comment(self, ref: str, comment_id: str, content: str | None = None) -> dict:
        """Mark a comment resolved by posting an ``action`` reply."""
        return self._action_reply(ref, comment_id, "resolve", content)

    def reopen_comment(self, ref: str, comment_id: str, content: str | None = None) -> dict:
        """Reopen a resolved comment by posting an ``action`` reply."""
        return self._action_reply(ref, comment_id, "reopen", content)

    def _action_reply(
        self, ref: str, comment_id: str, action: str, content: str | None
    ) -> dict:
        """Toggle a comment's resolved state via a reply that carries an ``action``.

        Drive exposes no PATCHable ``resolved`` field on a comment; resolve / reopen
        are done by creating a reply whose ``action`` is ``"resolve"`` or
        ``"reopen"``. ``content`` is optional for an action reply, so it is omitted
        from the body entirely when not provided. The reply resource carries
        ``action``; the parent comment's ``resolved`` reflects the new state on a
        subsequent read.

        The reply resource itself has no ``resolved`` field (only the parent
        comment does), so it must be left out of the projection: asking for it
        makes the live API return 400 Bad Request.
        """
        fields = "id,action,content,createdTime,author(displayName)"
        body: dict[str, Any] = {"action": action}
        if content is not None:
            body["content"] = content
        resp = self._client.post(
            f"{DRIVE_BASE}/files/{ref}/comments/{comment_id}/replies",
            headers=self._headers(content_type="application/json"),
            params={"fields": fields},
            json=body,
        )
        resp.raise_for_status()
        return self._project_reply(resp.json())

    # ---- Sheets v4 ---------------------------------------------------------

    def sheet_get(self, spreadsheet_id: str) -> dict:
        """Tab list, dimensions, named ranges for a spreadsheet."""
        resp = self._client.get(
            f"{SHEETS_BASE}/{spreadsheet_id}",
            headers=self._headers(),
            params={
                "fields": (
                    "spreadsheetId,properties(title),"
                    "sheets(properties(sheetId,title,gridProperties(rowCount,columnCount))),"
                    "namedRanges"
                ),
            },
        )
        resp.raise_for_status()
        return resp.json()

    def sheet_read(self, spreadsheet_id: str, a1_range: str) -> dict:
        resp = self._client.get(
            f"{SHEETS_BASE}/{spreadsheet_id}/values/{a1_range}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {"range": data.get("range"), "values": data.get("values", [])}

    def sheet_range_is_empty(self, spreadsheet_id: str, a1_range: str) -> bool:
        """True if the A1 range holds no values. Used to refuse a silent clobber."""
        return not self.sheet_read(spreadsheet_id, a1_range).get("values")

    def sheet_write(
        self, spreadsheet_id: str, a1_range: str, values: list[list[Any]]
    ) -> dict:
        """Overwrite a range with `values` (a list of rows)."""
        resp = self._client.put(
            f"{SHEETS_BASE}/{spreadsheet_id}/values/{a1_range}",
            headers=self._headers(content_type="application/json"),
            params={"valueInputOption": "USER_ENTERED"},
            json={"range": a1_range, "values": values},
        )
        resp.raise_for_status()
        return resp.json()

    def sheet_append(
        self, spreadsheet_id: str, a1_range: str, values: list[list[Any]]
    ) -> dict:
        """Append rows below the last row of `a1_range`."""
        resp = self._client.post(
            f"{SHEETS_BASE}/{spreadsheet_id}/values/{a1_range}:append",
            headers=self._headers(content_type="application/json"),
            params={
                "valueInputOption": "USER_ENTERED",
                "insertDataOption": "INSERT_ROWS",
            },
            json={"range": a1_range, "values": values},
        )
        resp.raise_for_status()
        return resp.json()

    def sheet_batch_update(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        """Structural edits (insert rows, format, add tabs) via batchUpdate."""
        resp = self._client.post(
            f"{SHEETS_BASE}/{spreadsheet_id}:batchUpdate",
            headers=self._headers(content_type="application/json"),
            json={"requests": requests},
        )
        resp.raise_for_status()
        return resp.json()

    # ---- projection --------------------------------------------------------

    @staticmethod
    def _project_file(f: dict) -> dict:
        return {
            "id": f.get("id"),
            "name": f.get("name"),
            "mimeType": f.get("mimeType"),
            "isFolder": nf.is_folder(f.get("mimeType")),
            "isGoogleNative": nf.is_google_native(f.get("mimeType")),
            "size": f.get("size"),
            "parents": f.get("parents") or [],
            "modifiedTime": f.get("modifiedTime"),
            "createdTime": f.get("createdTime"),
            "trashed": f.get("trashed"),
            "webViewLink": f.get("webViewLink"),
            "shared": f.get("shared"),
            "owners": [o.get("emailAddress") for o in f.get("owners") or []],
        }

    @staticmethod
    def _project_comment(c: dict) -> dict:
        """Project a Drive comment into a clean, stable dict.

        ``authorEmail`` / ``anchorText`` may be None: Drive frequently exposes
        only the author's display name, and a comment is not always anchored to
        a quoted text selection.
        """
        author = c.get("author") or {}
        quoted = c.get("quotedFileContent") or {}
        return {
            "id": c.get("id"),
            "author": author.get("displayName"),
            "authorEmail": author.get("emailAddress"),
            "content": c.get("content"),
            "createdTime": c.get("createdTime"),
            "modifiedTime": c.get("modifiedTime"),
            "resolved": c.get("resolved"),
            "anchorText": quoted.get("value"),
            "replies": [
                {
                    "author": (r.get("author") or {}).get("displayName"),
                    "authorEmail": (r.get("author") or {}).get("emailAddress"),
                    "content": r.get("content"),
                    "createdTime": r.get("createdTime"),
                    "action": r.get("action"),
                }
                for r in c.get("replies") or []
            ],
        }

    @staticmethod
    def _project_reply(r: dict) -> dict:
        """Project a single Drive reply (the create/reply/action-reply result).

        Mirrors the per-reply shape inside ``_project_comment``, plus the reply
        ``id``. ``authorEmail`` and ``action`` may be None: a plain reply carries
        no action, and Drive often exposes only the author's display name.
        """
        author = r.get("author") or {}
        return {
            "id": r.get("id"),
            "author": author.get("displayName"),
            "authorEmail": author.get("emailAddress"),
            "content": r.get("content"),
            "createdTime": r.get("createdTime"),
            "action": r.get("action"),
        }


# ---- module helpers --------------------------------------------------------


def tempfile_gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()


def _json_bytes(obj: dict) -> bytes:
    import json

    return json.dumps(obj).encode("utf-8")


def _guess_mime(name: str) -> str:
    ctype, _ = mimetypes.guess_type(name)
    return ctype or "application/octet-stream"


def _suffix_for_mime(mime: str) -> str:
    return {
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/pdf": ".pdf",
    }.get(mime, "")


def _safe_name(name: str) -> str:
    """Strip path separators so a Drive file name can't escape the target dir."""
    return name.replace("/", "_").replace("\\", "_").lstrip(".") or "file"
