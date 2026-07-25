"""Microsoft Graph adapter for M365 accounts."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx

from ._recipients import _extra_recipients
from ..auth import acquire_file_token, acquire_shared_token, acquire_token
from ..config import M365Account

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Graph sendMail accepts attachments inline up to ~3MB per file (4MB total
# request size). Above that you have to use createUploadSession; not yet
# implemented — we raise a clear error so Claude can re-route.
INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024


class GraphAdapter:
    """Synchronous Graph adapter. Auth refreshed per-call via MSAL silent flow."""

    def __init__(self, account: M365Account) -> None:
        self.account = account
        self._client = httpx.Client(base_url=GRAPH_BASE, timeout=60.0)
        # A delegate account targets another user's mailbox at /users/{mailbox};
        # a normal account targets /me. Computed once so every mailbox-content
        # endpoint below can share the same root.
        self._mail_root = (
            f"/users/{account.mailbox}" if account.mailbox else "/me"
        )

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        # A delegate mailbox needs the delegated shared-mailbox (Mail.ReadWrite
        # .Shared) token; a normal account uses its own mail token.
        token = (
            acquire_shared_token(self.account)
            if self.account.mailbox
            else acquire_token(self.account)
        )
        h = {"Authorization": f"Bearer {token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- basic / sanity ----------------------------------------------------

    def me(self) -> dict:
        # Always /me: this validates the signed-in delegate's own identity/token,
        # not the delegated mailbox.
        resp = self._client.get("/me", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def list_folders(self) -> list[dict]:
        resp = self._client.get(f"{self._mail_root}/mailFolders", headers=self._headers())
        resp.raise_for_status()
        return resp.json().get("value", [])

    # ---- read --------------------------------------------------------------

    def search(
        self,
        query: str = "",
        folder: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "$top": min(limit, 100),
            "$select": (
                "id,subject,from,toRecipients,receivedDateTime,"
                "isRead,hasAttachments,bodyPreview,webLink,conversationId"
            ),
        }
        if query:
            params["$search"] = f'"{query}"'
        else:
            params["$orderby"] = "receivedDateTime desc"

        url = (
            f"{self._mail_root}/mailFolders/{folder}/messages"
            if folder
            else f"{self._mail_root}/messages"
        )
        resp = self._client.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return [self._project_search(m) for m in resp.json().get("value", [])]

    def read(self, message_id: str) -> dict:
        # Request internetMessageHeaders so we can expose List-Unsubscribe etc.
        resp = self._client.get(
            f"{self._mail_root}/messages/{message_id}",
            headers=self._headers(),
            params={
                "$select": (
                    "id,conversationId,subject,from,toRecipients,ccRecipients,"
                    "receivedDateTime,isRead,hasAttachments,internetMessageId,"
                    "body,webLink,internetMessageHeaders"
                ),
            },
        )
        resp.raise_for_status()
        m = resp.json()
        atts: list[dict] = []
        # Graph reports hasAttachments=false for messages whose only images are
        # inline (referenced by cid: in the HTML body). Fetch the attachment list
        # in that case too, so inline images surface in the read output.
        body_content = (m.get("body") or {}).get("content") or ""
        if m.get("hasAttachments") or "cid:" in body_content:
            atts = self.list_attachments(message_id)
        return self._project_full(m, atts)

    @staticmethod
    def _project_search(m: dict) -> dict:
        return {
            "id": m.get("id"),
            "conversationId": m.get("conversationId"),
            "subject": m.get("subject"),
            "from": (m.get("from") or {}).get("emailAddress", {}).get("address"),
            "to": [
                r.get("emailAddress", {}).get("address")
                for r in m.get("toRecipients") or []
            ],
            "receivedDateTime": m.get("receivedDateTime"),
            "isRead": m.get("isRead"),
            "hasAttachments": m.get("hasAttachments"),
            "bodyPreview": m.get("bodyPreview"),
            "webLink": m.get("webLink"),
        }

    @staticmethod
    def _project_full(m: dict, attachments: list[dict]) -> dict:
        body = m.get("body") or {}
        # Pull List-Unsubscribe* headers if present in internetMessageHeaders.
        lu: str | None = None
        lup: str | None = None
        for h in m.get("internetMessageHeaders") or []:
            n = (h.get("name") or "").lower()
            if n == "list-unsubscribe":
                lu = h.get("value")
            elif n == "list-unsubscribe-post":
                lup = h.get("value")
        return {
            "id": m.get("id"),
            "conversationId": m.get("conversationId"),
            "subject": m.get("subject"),
            "from": (m.get("from") or {}).get("emailAddress", {}).get("address"),
            "to": [r.get("emailAddress", {}).get("address") for r in m.get("toRecipients") or []],
            "cc": [r.get("emailAddress", {}).get("address") for r in m.get("ccRecipients") or []],
            "receivedDateTime": m.get("receivedDateTime"),
            "isRead": m.get("isRead"),
            "hasAttachments": m.get("hasAttachments"),
            "attachments": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "size": a.get("size"),
                    "contentType": a.get("contentType"),
                    "isInline": a.get("isInline"),
                }
                for a in attachments
            ],
            "internetMessageId": m.get("internetMessageId"),
            "bodyContentType": body.get("contentType"),
            "body": body.get("content"),
            "webLink": m.get("webLink"),
            "listUnsubscribe": lu,
            "listUnsubscribePost": lup,
        }

    def block_sender(self, sender: str) -> dict:
        """Create an inbox rule that moves messages from `sender` to Junk Email."""
        rule = {
            "displayName": f"mcp-mail: block {sender}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"senderContains": [sender]},
            "actions": {
                "moveToFolder": "junkemail",
                "stopProcessingRules": True,
            },
        }
        resp = self._client.post(
            f"{self._mail_root}/mailFolders/inbox/messageRules",
            headers=self._headers(content_type="application/json"),
            json=rule,
        )
        resp.raise_for_status()
        return resp.json()

    # ---- attachments -------------------------------------------------------

    def list_attachments(self, message_id: str) -> list[dict]:
        """Return attachment metadata (no bytes)."""
        resp = self._client.get(
            f"{self._mail_root}/messages/{message_id}/attachments",
            headers=self._headers(),
            params={"$select": "id,name,size,contentType,isInline"},
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

    def download_attachment(self, message_id: str, attachment_id: str) -> tuple[str, bytes]:
        """Download a single attachment. Returns (filename, raw bytes)."""
        resp = self._client.get(
            f"{self._mail_root}/messages/{message_id}/attachments/{attachment_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name", "attachment")
        if "contentBytes" not in data:
            raise NotImplementedError(
                f"Attachment {data.get('@odata.type')!r} (not a fileAttachment) "
                "not yet supported"
            )
        return name, base64.b64decode(data["contentBytes"])

    # ---- mutate ------------------------------------------------------------

    def mark_read(self, message_id: str, read: bool = True) -> None:
        resp = self._client.patch(
            f"{self._mail_root}/messages/{message_id}",
            headers=self._headers(content_type="application/json"),
            json={"isRead": read},
        )
        resp.raise_for_status()

    def move(self, message_id: str, target_folder: str) -> dict:
        resp = self._client.post(
            f"{self._mail_root}/messages/{message_id}/move",
            headers=self._headers(content_type="application/json"),
            json={"destinationId": target_folder},
        )
        resp.raise_for_status()
        return resp.json()

    def mark_spam(self, message_id: str) -> dict:
        return self.move(message_id, "junkemail")

    def delete(self, message_id: str) -> None:
        resp = self._client.delete(
            f"{self._mail_root}/messages/{message_id}", headers=self._headers()
        )
        resp.raise_for_status()

    # ---- send / reply ------------------------------------------------------

    @staticmethod
    def _build_body(body_text: str | None, body_html: str | None) -> dict[str, str]:
        if not body_text and not body_html:
            raise ValueError("Either body_text or body_html must be provided.")
        if body_html:
            return {"contentType": "HTML", "content": body_html}
        return {"contentType": "Text", "content": body_text or ""}

    @staticmethod
    def _recipients(addrs: list[str] | None) -> list[dict]:
        return [{"emailAddress": {"address": a}} for a in (addrs or [])]

    @staticmethod
    def _attachments_payload(
        paths: list[str] | None, body_html: str | None = None
    ) -> list[dict]:
        """Turn a list of local file paths into Graph fileAttachment dicts.

        If ``body_html`` references an attachment by ``cid:<filename>``, that
        attachment is marked inline (``isInline`` + ``contentId`` = filename) so
        it renders inside the message body (e.g. a signature logo) rather than as
        a separate downloadable file. Attachments not referenced this way stay
        regular attachments, so existing callers are unaffected.
        """
        if not paths:
            return []
        out: list[dict] = []
        for p in paths:
            path = Path(p).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")
            data = path.read_bytes()
            if len(data) > INLINE_ATTACHMENT_LIMIT:
                raise ValueError(
                    f"Attachment {path.name} is {len(data) / 1024 / 1024:.1f}MB; "
                    f"Graph inline-send caps at ~3MB. "
                    "Large-file upload session not implemented in this phase."
                )
            ctype, _ = mimetypes.guess_type(str(path))
            att: dict = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": path.name,
                "contentType": ctype or "application/octet-stream",
                "contentBytes": base64.b64encode(data).decode("ascii"),
            }
            if body_html and f"cid:{path.name}" in body_html:
                att["isInline"] = True
                att["contentId"] = path.name
            out.append(att)
        return out

    def send(
        self,
        to: list[str],
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[str] | None = None,
    ) -> None:
        if self.account.mailbox:
            raise RuntimeError(
                f"Sending from a delegated mailbox ({self.account.mailbox}) is not "
                f"enabled: it requires the Mail.Send.Shared scope, which this build "
                f"does not request. Create a draft (mail_draft / mail_reply_draft) "
                f"instead."
            )
        message: dict = {
            "subject": subject,
            "body": self._build_body(body_text, body_html),
            "toRecipients": self._recipients(to),
        }
        if cc:
            message["ccRecipients"] = self._recipients(cc)
        if bcc:
            message["bccRecipients"] = self._recipients(bcc)
        atts = self._attachments_payload(attachments, body_html)
        if atts:
            message["attachments"] = atts

        resp = self._client.post(
            "/me/sendMail",
            headers=self._headers(content_type="application/json"),
            json={"message": message, "saveToSentItems": True},
        )
        resp.raise_for_status()

    def reply(
        self,
        message_id: str,
        body_text: str | None = None,
        body_html: str | None = None,
        reply_all: bool = False,
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> None:
        if self.account.mailbox:
            raise RuntimeError(
                f"Sending from a delegated mailbox ({self.account.mailbox}) is not "
                f"enabled: it requires the Mail.Send.Shared scope, which this build "
                f"does not request. Create a draft (mail_draft / mail_reply_draft) "
                f"instead."
            )
        message: dict = {"body": self._build_body(body_text, body_html)}
        atts = self._attachments_payload(attachments, body_html)
        if atts:
            message["attachments"] = atts

        # Graph's /reply and /replyAll actions REPLACE the recipient collections
        # with whatever we supply (they do not append), and /replyAll
        # auto-populates ccRecipients with the ORIGINAL cc. Setting extras-only
        # therefore drops every original cc recipient. So whenever recipients
        # need composing (reply_all, or extra cc/bcc), we read the original once,
        # compute the FULL recipient set client-side (mirroring Gmail/IMAP), and
        # POST to the single-shot /reply action supplying the complete set — the
        # /reply action still threads. When there are no extras and this is not a
        # reply-all, we keep the cheap single-shot path (no read; the /reply
        # action auto-resolves To to the original sender).
        if reply_all or cc or bcc:
            original = self.read(message_id)
            sender = original.get("from")
            exclude = {self.account.address.lower()}
            if sender:
                exclude.add(sender.lower())
            to = [sender] if sender else []
            base = (
                (original.get("to") or []) + (original.get("cc") or [])
                if reply_all
                else []
            )
            final_cc = _extra_recipients(base + (cc or []), exclude)
            already = {a.lower() for a in to} | {a.lower() for a in final_cc}
            final_bcc = _extra_recipients(bcc, exclude, already=already)
            message["toRecipients"] = self._recipients(to)
            if final_cc:
                message["ccRecipients"] = self._recipients(final_cc)
            if final_bcc:
                message["bccRecipients"] = self._recipients(final_bcc)

        resp = self._client.post(
            f"/me/messages/{message_id}/reply",
            headers=self._headers(content_type="application/json"),
            json={"message": message},
        )
        resp.raise_for_status()

    # ---- drafts (never sent) ----------------------------------------------
    #
    # Draft creation is the destination for the user's "Save as draft" choice in
    # the send-confirmation box. It builds the SAME message payload as send()
    # (recipients, cc/bcc, inline-logo attachments) but writes it to the Drafts
    # folder via createDraft / createReply, and NEVER calls /sendMail or the
    # /reply action, so nothing leaves the mailbox.

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[str] | None = None,
    ) -> dict:
        """Create a draft message (POST /me/messages = createDraft). Not sent."""
        message: dict = {
            "subject": subject,
            "body": self._build_body(body_text, body_html),
            "toRecipients": self._recipients(to),
        }
        if cc:
            message["ccRecipients"] = self._recipients(cc)
        if bcc:
            message["bccRecipients"] = self._recipients(bcc)
        atts = self._attachments_payload(attachments, body_html)
        if atts:
            message["attachments"] = atts

        resp = self._client.post(
            f"{self._mail_root}/messages",
            headers=self._headers(content_type="application/json"),
            json=message,
        )
        resp.raise_for_status()
        created = resp.json()
        return {
            "id": created.get("id"),
            "webLink": created.get("webLink"),
            "isDraft": created.get("isDraft", True),
            "provider": "m365",
        }

    def create_reply_draft(
        self,
        message_id: str,
        body_text: str | None = None,
        body_html: str | None = None,
        reply_all: bool = False,
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Create a threaded reply DRAFT (createReply), then PATCH body + recipients.

        Uses /createReply so the draft threads to the original conversation, then
        PATCHes the new body and the client-composed recipient set (mirroring
        reply(), so reply_all preserves the original To+Cc and extra cc/bcc are
        added without dropping anyone). Attachments are POSTed to the draft's
        attachments collection. No send action is ever invoked.
        """
        resp = self._client.post(
            f"{self._mail_root}/messages/{message_id}/createReply",
            headers=self._headers(content_type="application/json"),
            json={},
        )
        resp.raise_for_status()
        draft = resp.json()
        draft_id = draft.get("id")

        # Compose the full recipient set client-side, exactly like reply().
        original = self.read(message_id)
        sender = original.get("from")
        exclude = {self.account.address.lower()}
        if sender:
            exclude.add(sender.lower())
        to = [sender] if sender else []
        base = (
            (original.get("to") or []) + (original.get("cc") or [])
            if reply_all
            else []
        )
        final_cc = _extra_recipients(base + (cc or []), exclude)
        already = {a.lower() for a in to} | {a.lower() for a in final_cc}
        final_bcc = _extra_recipients(bcc, exclude, already=already)

        patch: dict = {"body": self._build_body(body_text, body_html)}
        if to:
            patch["toRecipients"] = self._recipients(to)
        if final_cc:
            patch["ccRecipients"] = self._recipients(final_cc)
        if final_bcc:
            patch["bccRecipients"] = self._recipients(final_bcc)
        presp = self._client.patch(
            f"{self._mail_root}/messages/{draft_id}",
            headers=self._headers(content_type="application/json"),
            json=patch,
        )
        presp.raise_for_status()

        for att in self._attachments_payload(attachments, body_html):
            aresp = self._client.post(
                f"{self._mail_root}/messages/{draft_id}/attachments",
                headers=self._headers(content_type="application/json"),
                json=att,
            )
            aresp.raise_for_status()

        return {
            "id": draft_id,
            "webLink": draft.get("webLink"),
            "isDraft": True,
            "provider": "m365",
        }

    # ---- files (SharePoint / OneDrive) -------------------------------------
    #
    # These use a SEPARATE, file-scoped token (acquire_file_token) so the mail
    # surface's silent scope set is never widened (spec section 7.2). A `ref`
    # is either a plain driveItem id in the account's own OneDrive, or a
    # "drive_id/item_id" pair addressing a SharePoint document library; the
    # helpers below normalise both.

    def _file_headers(self, content_type: str | None = None) -> dict[str, str]:
        token = acquire_file_token(self.account)
        h = {"Authorization": f"Bearer {token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    @staticmethod
    def _item_base(ref: str) -> str:
        """Resolve `ref` to a Graph driveItem URL base.

        - ``"<drive_id>/<item_id>"`` -> ``/drives/<drive_id>/items/<item_id>``
          (a SharePoint document library or a shared drive).
        - ``"<item_id>"`` -> ``/me/drive/items/<item_id>`` (the account's own
          OneDrive). ``"root"`` addresses the OneDrive root.
        """
        if "/" in ref:
            drive_id, _, item_id = ref.partition("/")
            return f"/drives/{drive_id}/items/{item_id}"
        if ref == "root":
            return "/me/drive/root"
        return f"/me/drive/items/{ref}"

    def drive_list(self, path: str | None = None, page: str | None = None) -> dict:
        """List children of a folder. `path` is a driveItem ref (None = OneDrive root)."""
        base = self._item_base(path) if path else "/me/drive/root"
        url = f"{base}/children"
        params: dict[str, str | int] = {
            "$select": "id,name,size,folder,file,parentReference,lastModifiedDateTime,webUrl",
            "$top": 100,
        }
        if page:
            params["$skiptoken"] = page
        resp = self._client.get(url, headers=self._file_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        return {
            "files": [self._project_drive_item(i) for i in data.get("value", [])],
            "nextPageToken": _skiptoken(data.get("@odata.nextLink")),
        }

    def drive_search(self, query: str, limit: int = 25) -> list[dict]:
        """Search the account's OneDrive for `query`."""
        resp = self._client.get(
            f"/me/drive/root/search(q='{query}')",
            headers=self._file_headers(),
            params={"$top": min(limit, 100)},
        )
        resp.raise_for_status()
        return [self._project_drive_item(i) for i in resp.json().get("value", [])]

    def drive_get_metadata(self, ref: str) -> dict:
        resp = self._client.get(self._item_base(ref), headers=self._file_headers())
        resp.raise_for_status()
        return self._project_drive_item(resp.json())

    def drive_read(self, ref: str, target_dir: str | None = None) -> dict:
        """Download a file's content to a local dir; return the path."""
        meta = self.drive_get_metadata(ref)
        resp = self._client.get(
            f"{self._item_base(ref)}/content",
            headers=self._file_headers(),
            follow_redirects=True,
        )
        resp.raise_for_status()
        out_dir = Path(target_dir).expanduser() if target_dir else (
            Path(_gettempdir()) / "mcp-mail-graph"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / (meta.get("name") or ref).replace("/", "_")
        dest.write_bytes(resp.content)
        return {"ref": ref, "mode": "binary", "path": str(dest), "metadata": meta}

    def drive_create(
        self,
        name: str,
        parent: str | None = None,
        content: str | None = None,
        mime: str | None = None,
    ) -> dict:
        """Create a folder or upload a small text/byte file under `parent`."""
        parent_base = self._item_base(parent) if parent else "/me/drive/root"
        if content is None:
            # Folder create.
            resp = self._client.post(
                f"{parent_base}/children",
                headers=self._file_headers(content_type="application/json"),
                json={
                    "name": name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "rename",
                },
            )
            resp.raise_for_status()
            return self._project_drive_item(resp.json())
        # Simple upload (content under ~4MB; large files would need an upload
        # session, out of scope for this phase).
        upload_mime = mime or "text/plain"
        resp = self._client.put(
            f"{parent_base}:/{name}:/content",
            headers=self._file_headers(content_type=upload_mime),
            content=content.encode("utf-8"),
        )
        resp.raise_for_status()
        return self._project_drive_item(resp.json())

    def drive_update(self, ref: str, content: str) -> dict:
        """Replace a file's bytes/text."""
        meta = self.drive_get_metadata(ref)
        upload_mime = meta.get("file", {}).get("mimeType") or "text/plain"
        resp = self._client.put(
            f"{self._item_base(ref)}/content",
            headers=self._file_headers(content_type=upload_mime),
            content=content.encode("utf-8"),
        )
        resp.raise_for_status()
        return self._project_drive_item(resp.json())

    def drive_move(self, ref: str, dest: str) -> dict:
        """Move/rename. `dest` is 'parent_ref' or 'parent_ref/new name'."""
        new_parent, _, new_name = dest.partition("/")
        body: dict = {}
        if new_parent:
            # parentReference needs the driveItem id of the target folder.
            body["parentReference"] = {"id": new_parent}
        if new_name:
            body["name"] = new_name
        resp = self._client.patch(
            self._item_base(ref),
            headers=self._file_headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()
        return self._project_drive_item(resp.json())

    def drive_copy(self, ref: str, dest: str) -> dict:
        new_parent, _, new_name = dest.partition("/")
        body: dict = {}
        if new_parent:
            body["parentReference"] = {"id": new_parent}
        if new_name:
            body["name"] = new_name
        resp = self._client.post(
            f"{self._item_base(ref)}/copy",
            headers=self._file_headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()
        # Copy is async; Graph returns 202 with a monitor URL.
        return {"ref": ref, "dest": dest, "status": "accepted", "monitor": resp.headers.get("Location")}

    def drive_delete(self, ref: str) -> dict:
        """Send to the OneDrive / SharePoint recycle bin (reversible)."""
        resp = self._client.delete(self._item_base(ref), headers=self._file_headers())
        resp.raise_for_status()
        return {"ref": ref, "recycled": True}

    def drive_share(self, ref: str, principal: str, role: str) -> dict:
        """Grant a sharing permission. Outward-facing: gated at the server boundary."""
        graph_role = "write" if role in ("write", "writer", "edit") else "read"
        body = {
            "recipients": [{"email": principal}],
            "roles": [graph_role],
            "sendInvitation": False,
            "requireSignIn": True,
        }
        resp = self._client.post(
            f"{self._item_base(ref)}/invite",
            headers=self._file_headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()
        return {"ref": ref, "principal": principal, "role": graph_role, "result": resp.json()}

    # ---- sites (SharePoint) ------------------------------------------------

    def site_search(self, query: str, limit: int = 25) -> list[dict]:
        """Search SharePoint sites by name."""
        resp = self._client.get(
            "/sites",
            headers=self._file_headers(),
            params={"search": query, "$top": min(limit, 100)},
        )
        resp.raise_for_status()
        return [
            {"id": s.get("id"), "name": s.get("displayName"), "webUrl": s.get("webUrl")}
            for s in resp.json().get("value", [])
        ]

    def site_list_drives(self, site_id: str) -> list[dict]:
        """List document libraries (drives) of a SharePoint site."""
        resp = self._client.get(
            f"/sites/{site_id}/drives",
            headers=self._file_headers(),
            params={"$select": "id,name,webUrl,driveType"},
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

    def files_auth_status(self) -> dict:
        """Cheap probe used by drive_list_backends; never raises."""
        try:
            token = acquire_file_token(self.account)
            return {"ok": bool(token)}
        except Exception as e:
            # A status probe must surface "needs re-auth", not crash the listing.
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _project_drive_item(i: dict) -> dict:
        is_folder = "folder" in i
        return {
            "id": i.get("id"),
            "name": i.get("name"),
            "isFolder": is_folder,
            "size": i.get("size"),
            "mimeType": (i.get("file") or {}).get("mimeType"),
            "parentId": (i.get("parentReference") or {}).get("id"),
            "driveId": (i.get("parentReference") or {}).get("driveId"),
            "modifiedTime": i.get("lastModifiedDateTime"),
            "webUrl": i.get("webUrl"),
        }


# ---- module helpers --------------------------------------------------------


def _gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()


def _skiptoken(next_link: str | None) -> str | None:
    """Extract the ``$skiptoken`` value from a Graph @odata.nextLink, if any."""
    if not next_link or "$skiptoken=" not in next_link:
        return None
    return next_link.split("$skiptoken=", 1)[1].split("&", 1)[0]
