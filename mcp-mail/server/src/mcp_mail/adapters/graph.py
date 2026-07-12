"""Microsoft Graph adapter for M365 accounts."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx

from ..auth import acquire_token
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

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        token = acquire_token(self.account)
        h = {"Authorization": f"Bearer {token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- basic / sanity ----------------------------------------------------

    def me(self) -> dict:
        resp = self._client.get("/me", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def list_folders(self) -> list[dict]:
        resp = self._client.get("/me/mailFolders", headers=self._headers())
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

        url = f"/me/mailFolders/{folder}/messages" if folder else "/me/messages"
        resp = self._client.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return [self._project_search(m) for m in resp.json().get("value", [])]

    def read(self, message_id: str) -> dict:
        # Request internetMessageHeaders so we can expose List-Unsubscribe etc.
        resp = self._client.get(
            f"/me/messages/{message_id}",
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
        if m.get("hasAttachments"):
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
            "/me/mailFolders/inbox/messageRules",
            headers=self._headers(content_type="application/json"),
            json=rule,
        )
        resp.raise_for_status()
        return resp.json()

    # ---- attachments -------------------------------------------------------

    def list_attachments(self, message_id: str) -> list[dict]:
        """Return attachment metadata (no bytes)."""
        resp = self._client.get(
            f"/me/messages/{message_id}/attachments",
            headers=self._headers(),
            params={"$select": "id,name,size,contentType,isInline"},
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

    def download_attachment(self, message_id: str, attachment_id: str) -> tuple[str, bytes]:
        """Download a single attachment. Returns (filename, raw bytes)."""
        resp = self._client.get(
            f"/me/messages/{message_id}/attachments/{attachment_id}",
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
            f"/me/messages/{message_id}",
            headers=self._headers(content_type="application/json"),
            json={"isRead": read},
        )
        resp.raise_for_status()

    def move(self, message_id: str, target_folder: str) -> dict:
        resp = self._client.post(
            f"/me/messages/{message_id}/move",
            headers=self._headers(content_type="application/json"),
            json={"destinationId": target_folder},
        )
        resp.raise_for_status()
        return resp.json()

    def mark_spam(self, message_id: str) -> dict:
        return self.move(message_id, "junkemail")

    def delete(self, message_id: str) -> None:
        resp = self._client.delete(f"/me/messages/{message_id}", headers=self._headers())
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
    def _attachments_payload(paths: list[str] | None) -> list[dict]:
        """Turn a list of local file paths into Graph fileAttachment dicts."""
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
            out.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": path.name,
                    "contentType": ctype or "application/octet-stream",
                    "contentBytes": base64.b64encode(data).decode("ascii"),
                }
            )
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
        message: dict = {
            "subject": subject,
            "body": self._build_body(body_text, body_html),
            "toRecipients": self._recipients(to),
        }
        if cc:
            message["ccRecipients"] = self._recipients(cc)
        if bcc:
            message["bccRecipients"] = self._recipients(bcc)
        atts = self._attachments_payload(attachments)
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
    ) -> None:
        endpoint = "replyAll" if reply_all else "reply"
        message: dict = {"body": self._build_body(body_text, body_html)}
        atts = self._attachments_payload(attachments)
        if atts:
            message["attachments"] = atts
        resp = self._client.post(
            f"/me/messages/{message_id}/{endpoint}",
            headers=self._headers(content_type="application/json"),
            json={"message": message},
        )
        resp.raise_for_status()
