"""Gmail adapter for personal + Workspace Google accounts."""

from __future__ import annotations

import base64
import json
import mimetypes
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from pathlib import Path

import httpx
import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from ._recipients import _extra_recipients
from ..config import GmailAccount

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"

# The mail surface plus the Drive / Sheets / Calendar scopes added by the
# expansion. The whole list is requested as a UNION at consent time: a Google
# refresh token freezes its granted scopes when the user re-consents, so the Drive
# and Calendar adapters (which reuse this same OAuth client and Keychain token)
# get their scopes from one re-consent rather than three separate clients.
# Re-consent is a user action (scripts/reauth_google.py); shipping these scopes
# does NOT touch an existing token until that script is re-run.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]

# Same inline-attachment limit philosophy as Graph; Gmail's actual cap is
# higher (~25MB per send) but we keep parity with M365 for predictable UX.
INLINE_ATTACHMENT_LIMIT = 25 * 1024 * 1024


# Gmail uses labels, not folders. Map common cross-provider folder names to
# the right label-modify or trash action.
GMAIL_WELLKNOWN_LOWER = {
    "inbox":         ("modify", ["INBOX"],   []),
    "archive":       ("modify", [],          ["INBOX"]),
    "starred":       ("modify", ["STARRED"], []),
    "important":     ("modify", ["IMPORTANT"], []),
    "sentitems":     ("modify", ["SENT"],    []),
    "sent":          ("modify", ["SENT"],    []),
    "drafts":        ("modify", ["DRAFT"],   []),
    "draft":         ("modify", ["DRAFT"],   []),
    "trash":         ("trash",  [],          []),
    "deleteditems":  ("trash",  [],          []),
    "spam":          ("modify", ["SPAM"],    ["INBOX"]),
    "junkemail":     ("modify", ["SPAM"],    ["INBOX"]),
}


# ---- auth ------------------------------------------------------------------


def _load_oauth_client_config(account: GmailAccount) -> dict:
    """Read the shared OAuth client config (client_id + client_secret) from Keychain."""
    blob = keyring.get_password(account.oauth_keychain_service, account.oauth_keychain_user)
    if not blob:
        raise RuntimeError(
            f"OAuth client config not found in Keychain "
            f"(service={account.oauth_keychain_service!r}, "
            f"account={account.oauth_keychain_user!r}). "
            "Store a JSON blob with client_id and client_secret first."
        )
    data = json.loads(blob)
    return {
        "installed": {
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def acquire_credentials(account: GmailAccount, allow_interactive: bool = False) -> Credentials:
    """Return valid Gmail credentials.

    Loads the cached refresh token from Keychain and refreshes silently if
    expired. In the MCP server (``allow_interactive=False``, the default) an
    expired, revoked, or missing token raises a clear, actionable error instead
    of opening a browser: ``run_local_server`` would block the headless server
    indefinitely waiting for a redirect that never arrives (the "stuck for
    hours" failure). The re-auth helper (``scripts/reauth_google.py``) passes
    ``allow_interactive=True`` to run the one-off browser consent flow.
    """
    creds: Credentials | None = None
    token_blob = keyring.get_password(account.keychain_service, account.keychain_user)
    if token_blob:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(token_blob), SCOPES)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            keyring.set_password(
                account.keychain_service, account.keychain_user, creds.to_json()
            )
        except Exception:
            creds = None  # refresh failed: token expired or revoked

    if creds and creds.valid:
        return creds

    if not allow_interactive:
        raise RuntimeError(
            f"{account.id}: no valid Gmail credentials (token missing, expired, "
            f"or revoked, or the granted scopes do not cover this operation). "
            f"Re-authorize from a terminal:\n"
            f"    uv run python scripts/reauth_google.py {account.id}\n"
            f"If this recurs every ~7 days, set the Google OAuth consent screen "
            f"to 'In production'; Testing mode expires refresh tokens weekly."
        )

    # Interactive (re-auth helper only) opens a browser and listens on
    # localhost:8766 (different from MSAL's 8765 to avoid a port conflict if
    # both servers run concurrently).
    client_config = _load_oauth_client_config(account)
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=8766, prompt="consent", open_browser=True)
    keyring.set_password(
        account.keychain_service, account.keychain_user, creds.to_json()
    )
    return creds


# ---- helpers ---------------------------------------------------------------


def _b64url_decode(data: str) -> bytes:
    """Decode Gmail's URL-safe base64 (which may be missing padding)."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _header(payload: dict, name: str) -> str | None:
    name_l = name.lower()
    for h in payload.get("headers", []) or []:
        if h.get("name", "").lower() == name_l:
            return h.get("value")
    return None


def _emails_only(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr for _, addr in getaddresses([value]) if addr]


def _email_only(value: str | None) -> str | None:
    if not value:
        return None
    _, addr = parseaddr(value)
    return addr or None


def _internal_date_iso(internal_date: str | None) -> str | None:
    if not internal_date:
        return None
    return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC).isoformat()


def _synth_attachment_name(idx: int, mime: str, content_id: str | None) -> str:
    """Synthesize a stable name for a filename-less (usually inline) part.

    Prefer the Content-ID local part (``<abc@host>`` -> ``abc``) so a cid-
    referenced inline image gets a recognisable handle. Otherwise fall back to
    ``inline-{idx}.{ext}`` where ext is the MIME subtype (``image/png`` ->
    ``png``), and finally ``attachment-{idx}`` when even the subtype is missing.
    """
    if content_id:
        local = content_id.strip().strip("<>").strip().split("@", 1)[0].strip()
        if local:
            return local
    subtype = mime.split("/", 1)[1].strip() if "/" in mime else ""
    if subtype:
        return f"inline-{idx}.{subtype}"
    return f"attachment-{idx}"


def _extract_parts(payload: dict) -> tuple[str | None, str | None, list[dict]]:
    """Walk a Gmail payload tree. Returns (text_body, html_body, attachment_metas)."""
    text: str | None = None
    html: str | None = None
    attachments: list[dict] = []

    def walk(p: dict) -> None:
        nonlocal text, html
        mime = p.get("mimeType", "")
        body = p.get("body", {}) or {}
        attachment_id = body.get("attachmentId")
        filename = p.get("filename")

        # Read Content-Disposition and Content-ID BEFORE deciding whether this
        # part is an attachment, so the decision can inspect them.
        cd = ""
        content_id: str | None = None
        for h in p.get("headers", []) or []:
            hn = h.get("name", "").lower()
            if hn == "content-disposition":
                cd = (h.get("value") or "").lower()
            elif hn == "content-id":
                content_id = h.get("value")
        # Parse the disposition TYPE (token before the first ';').
        disp_type = cd.split(";", 1)[0].strip()

        # A part carrying body.attachmentId is normally a real attachment: a
        # file (has a filename) OR a cid-referenced inline image (often
        # filename-less). BUT Gmail also externalizes a LARGE text/plain or
        # text/html BODY into body.attachmentId with empty body.data — a
        # filename-less text part carrying only an attachmentId is that
        # externalized body, NOT an attachment. "inline" is the RFC 2183 DEFAULT
        # disposition for a body, so it must NOT flip a text part into an
        # attachment; only a filename, an explicit "attachment" disposition, or a
        # Content-ID does. Such a text part then falls through to the body
        # branches below (yielding an empty body for that rare externalized case,
        # the pre-existing behaviour). Non-text parts keep capturing on
        # attachment_id alone, so inline IMAGES (non-text) are unaffected; cid-
        # referenced inline text is still caught by content_id.
        is_attachment = bool(attachment_id) and (
            mime not in ("text/plain", "text/html")
            or bool(filename)
            or "attachment" in disp_type
            or content_id is not None
        )

        if is_attachment:
            name = filename or _synth_attachment_name(len(attachments), mime, content_id)
            # Token-aware isInline: classify by the disposition TYPE so a real
            # attachment whose filename merely CONTAINS "inline"
            # (e.g. "mainline-budget.pdf") is not mislabelled inline.
            is_inline = (disp_type == "inline") or (
                content_id is not None and disp_type != "attachment"
            )
            attachments.append({
                "id": attachment_id,
                "name": name,
                "size": body.get("size", 0),
                "contentType": mime,
                "isInline": is_inline,
            })
        elif mime == "text/plain" and body.get("data") and text is None:
            text = _b64url_decode(body["data"]).decode("utf-8", errors="replace")
        elif mime == "text/html" and body.get("data") and html is None:
            html = _b64url_decode(body["data"]).decode("utf-8", errors="replace")

        for child in p.get("parts", []) or []:
            walk(child)

    walk(payload)
    return text, html, attachments


# ---- adapter ---------------------------------------------------------------


class GmailAdapter:
    """Gmail REST API adapter. Auth refreshed per-call via google-auth."""

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._client = httpx.Client(base_url=GMAIL_BASE, timeout=60.0)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        creds = acquire_credentials(self.account)
        h = {"Authorization": f"Bearer {creds.token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- basic / sanity ----------------------------------------------------

    def me(self) -> dict:
        resp = self._client.get("/users/me/profile", headers=self._headers())
        resp.raise_for_status()
        p = resp.json()
        return {
            "displayName": None,  # Gmail profile doesn't expose display name
            "userPrincipalName": p.get("emailAddress"),
            "mail": p.get("emailAddress"),
            "id": p.get("emailAddress"),
            "messagesTotal": p.get("messagesTotal"),
            "threadsTotal": p.get("threadsTotal"),
        }

    def list_folders(self) -> list[dict]:
        """List labels (Gmail's folder-equivalent)."""
        resp = self._client.get("/users/me/labels", headers=self._headers())
        resp.raise_for_status()
        labels = resp.json().get("labels", [])
        # Get message counts per label (Gmail returns them inline if we
        # request each label individually; for now skip the extra calls
        # and just return id/name/type).
        return [
            {
                "id": label["id"],
                "displayName": label["name"],
                "type": label.get("type"),  # "system" or "user"
                "totalItemCount": None,  # would require N extra calls
                "unreadItemCount": None,
            }
            for label in labels
        ]

    # ---- read --------------------------------------------------------------

    def search(
        self,
        query: str = "",
        folder: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Search messages. `query` is Gmail search syntax (e.g. 'from:alice subject:foo').

        `folder` can be a well-known name ('inbox', 'sent', 'spam', etc.), a Gmail
        label id (like 'Label_42'), or a label NAME (like 'Travel/2026'). Omit
        to search across all messages.
        """
        params: dict[str, str | int] = {"maxResults": min(limit, 100)}
        if query:
            params["q"] = query

        if folder:
            label_id = self._resolve_label(folder)
            if label_id:
                params["labelIds"] = label_id

        resp = self._client.get("/users/me/messages", headers=self._headers(), params=params)
        resp.raise_for_status()
        message_refs = resp.json().get("messages", []) or []

        # Each search result is just {id, threadId} — fetch metadata for each.
        results = []
        for ref in message_refs:
            full = self._get_message(ref["id"], fmt="metadata", headers=("From", "To", "Subject", "Date"))
            results.append(self._project_search(full))
        return results

    def read(self, message_id: str) -> dict:
        full = self._get_message(message_id, fmt="full")
        return self._project_full(full)

    def _get_message(
        self, message_id: str, fmt: str = "full", headers: tuple[str, ...] = ()
    ) -> dict:
        params: dict[str, str | list[str]] = {"format": fmt}
        if fmt == "metadata" and headers:
            params["metadataHeaders"] = list(headers)
        resp = self._client.get(
            f"/users/me/messages/{message_id}",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    def _resolve_label(self, folder: str) -> str | None:
        """Resolve a well-known name or user label name to a Gmail label id."""
        key = folder.lower()
        wellknown = {
            "inbox": "INBOX",
            "sent": "SENT",
            "sentitems": "SENT",
            "drafts": "DRAFT",
            "draft": "DRAFT",
            "trash": "TRASH",
            "deleteditems": "TRASH",
            "spam": "SPAM",
            "junkemail": "SPAM",
            "starred": "STARRED",
            "important": "IMPORTANT",
            "unread": "UNREAD",
        }
        if key in wellknown:
            return wellknown[key]
        # Already looks like a label id?
        if folder.startswith("Label_") or folder.isupper():
            return folder
        # Otherwise look up by display name.
        for label in self.list_folders():
            if label["displayName"].lower() == key:
                return label["id"]
        return None

    # ---- projections (cross-provider normalized shapes) --------------------

    @staticmethod
    def _project_search(m: dict) -> dict:
        payload = m.get("payload", {}) or {}
        return {
            "id": m.get("id"),
            "conversationId": m.get("threadId"),
            "subject": _header(payload, "Subject"),
            "from": _email_only(_header(payload, "From")),
            "to": _emails_only(_header(payload, "To")),
            "receivedDateTime": _internal_date_iso(m.get("internalDate")),
            "isRead": "UNREAD" not in (m.get("labelIds") or []),
            "hasAttachments": False,  # would need full read to know; cheaper to skip
            "bodyPreview": m.get("snippet"),
            "webLink": None,
        }

    @staticmethod
    def _project_full(m: dict) -> dict:
        payload = m.get("payload", {}) or {}
        text, html, attachments = _extract_parts(payload)
        body = html if html else (text or "")
        body_ct = "HTML" if html else "Text"
        return {
            "id": m.get("id"),
            "conversationId": m.get("threadId"),
            "subject": _header(payload, "Subject"),
            "from": _email_only(_header(payload, "From")),
            "to": _emails_only(_header(payload, "To")),
            "cc": _emails_only(_header(payload, "Cc")),
            "receivedDateTime": _internal_date_iso(m.get("internalDate")),
            "isRead": "UNREAD" not in (m.get("labelIds") or []),
            "hasAttachments": bool(attachments),
            "attachments": attachments,
            "internetMessageId": _header(payload, "Message-ID") or _header(payload, "Message-Id"),
            "bodyContentType": body_ct,
            "body": body,
            "webLink": None,
            "listUnsubscribe": _header(payload, "List-Unsubscribe"),
            "listUnsubscribePost": _header(payload, "List-Unsubscribe-Post"),
        }

    def block_sender(self, sender: str) -> dict:
        """Create a Gmail filter that sends future mail from `sender` to Trash."""
        body = {
            "criteria": {"from": sender},
            "action": {
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX", "UNREAD"],
            },
        }
        resp = self._client.post(
            "/users/me/settings/filters",
            headers=self._headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    # ---- attachments -------------------------------------------------------

    def list_attachments(self, message_id: str) -> list[dict]:
        """Return attachment metadata. Walks the full message payload."""
        full = self._get_message(message_id, fmt="full")
        _, _, atts = _extract_parts(full.get("payload", {}) or {})
        return atts

    def download_attachment(self, message_id: str, attachment_id: str) -> tuple[str, bytes]:
        """Download a single attachment. Returns (filename, raw bytes)."""
        # We need the filename — fetch it from the message structure.
        full = self._get_message(message_id, fmt="full")
        _, _, atts = _extract_parts(full.get("payload", {}) or {})
        filename = next(
            (a["name"] for a in atts if a["id"] == attachment_id),
            "attachment",
        )
        resp = self._client.get(
            f"/users/me/messages/{message_id}/attachments/{attachment_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json().get("data", "")
        return filename, _b64url_decode(data)

    # ---- mutate ------------------------------------------------------------

    def mark_read(self, message_id: str, read: bool = True) -> None:
        body = {"removeLabelIds": ["UNREAD"]} if read else {"addLabelIds": ["UNREAD"]}
        resp = self._client.post(
            f"/users/me/messages/{message_id}/modify",
            headers=self._headers(content_type="application/json"),
            json=body,
        )
        resp.raise_for_status()

    def move(self, message_id: str, target_folder: str) -> dict:
        """Move a message. For Gmail, this is really label add/remove or trash."""
        key = target_folder.lower()
        action = GMAIL_WELLKNOWN_LOWER.get(key)
        if action:
            kind, add, remove = action
            if kind == "trash":
                resp = self._client.post(
                    f"/users/me/messages/{message_id}/trash",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return {"id": message_id}
            else:
                resp = self._client.post(
                    f"/users/me/messages/{message_id}/modify",
                    headers=self._headers(content_type="application/json"),
                    json={"addLabelIds": add, "removeLabelIds": remove},
                )
                resp.raise_for_status()
                return {"id": message_id}
        # Treat as a label id or user-defined label name.
        label_id = self._resolve_label(target_folder) or target_folder
        resp = self._client.post(
            f"/users/me/messages/{message_id}/modify",
            headers=self._headers(content_type="application/json"),
            json={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
        )
        resp.raise_for_status()
        return {"id": message_id}

    def mark_spam(self, message_id: str) -> dict:
        return self.move(message_id, "spam")

    def delete(self, message_id: str) -> None:
        """Soft-delete: move to Trash (Gmail's equivalent of Deleted Items)."""
        resp = self._client.post(
            f"/users/me/messages/{message_id}/trash",
            headers=self._headers(),
        )
        resp.raise_for_status()

    # ---- send / reply ------------------------------------------------------

    def _build_mime(
        self,
        subject: str,
        body_text: str | None,
        body_html: str | None,
        to: list[str] | None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[str] | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> bytes:
        """Build an RFC822 MIME message for Gmail's `/send` endpoint."""
        if not body_text and not body_html:
            raise ValueError("Either body_text or body_html must be provided.")

        msg = EmailMessage()
        msg["From"] = self.account.address
        if to:
            msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to

        # Multipart/alternative if both bodies given; HTML default per spec.
        plain = body_text or ""
        msg.set_content(plain)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        for p in attachments or []:
            path = Path(p).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")
            data = path.read_bytes()
            if len(data) > INLINE_ATTACHMENT_LIMIT:
                raise ValueError(
                    f"Attachment {path.name} is {len(data) / 1024 / 1024:.1f}MB; "
                    f"limit is {INLINE_ATTACHMENT_LIMIT // 1024 // 1024}MB."
                )
            ctype, _ = mimetypes.guess_type(str(path))
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=path.name,
            )

        return msg.as_bytes()

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
        mime = self._build_mime(
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            to=to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )
        raw = base64.urlsafe_b64encode(mime).decode("ascii")
        resp = self._client.post(
            "/users/me/messages/send",
            headers=self._headers(content_type="application/json"),
            json={"raw": raw},
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
        """Reply, preserving threading."""
        # Fetch original to get Subject/From/Message-ID/threadId.
        original = self._get_message(
            message_id,
            fmt="metadata",
            headers=("Subject", "From", "To", "Cc", "Message-ID", "References"),
        )
        payload = original.get("payload", {}) or {}
        orig_subject = _header(payload, "Subject") or ""
        orig_from = _email_only(_header(payload, "From"))
        orig_to = _emails_only(_header(payload, "To"))
        orig_cc = _emails_only(_header(payload, "Cc"))
        orig_msgid = _header(payload, "Message-ID") or _header(payload, "Message-Id")
        orig_refs = _header(payload, "References")

        reply_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

        # Recipients: always reply to the From of the original. reply_all folds
        # the original To + Cc into cc; extra `cc` addresses are ADDED on top.
        self_addr = self.account.address.lower()
        sender_addr = (orig_from or "").lower()
        to = [orig_from] if orig_from else []
        # Route the WHOLE cc set (reply_all's original To+Cc plus the extras)
        # through the shared helper, mirroring Graph. This drops self + the
        # original sender and collapses case-insensitive duplicates, so an
        # address present in BOTH the original To and Cc is listed only once.
        exclude = {self_addr, sender_addr}
        final_cc = _extra_recipients(
            (orig_to + orig_cc if reply_all else []) + (cc or []),
            exclude,
        )
        # Dedupe bcc against the resolved To + Cc too, so an address already
        # visible in cc doesn't reappear as a blind copy.
        final_bcc = _extra_recipients(
            bcc,
            exclude,
            already={a.lower() for a in to} | {a.lower() for a in final_cc},
        )

        mime = self._build_mime(
            subject=reply_subject,
            body_text=body_text,
            body_html=body_html,
            to=to,
            cc=final_cc,
            bcc=final_bcc,
            attachments=attachments,
            in_reply_to=orig_msgid,
            references=f"{orig_refs} {orig_msgid}".strip() if orig_refs else orig_msgid,
        )
        raw = base64.urlsafe_b64encode(mime).decode("ascii")
        resp = self._client.post(
            "/users/me/messages/send",
            headers=self._headers(content_type="application/json"),
            json={"raw": raw, "threadId": original.get("threadId")},
        )
        resp.raise_for_status()

    # ---- drafts (never sent) ----------------------------------------------
    #
    # Destination for the user's "Save as draft" choice. Builds the identical
    # MIME send() would build, then writes it via users.drafts.create instead of
    # users.messages.send, so nothing is delivered.

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
        """Create a draft (users.drafts.create) from a built MIME. Not sent."""
        mime = self._build_mime(
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            to=to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )
        raw = base64.urlsafe_b64encode(mime).decode("ascii")
        resp = self._client.post(
            "/users/me/drafts",
            headers=self._headers(content_type="application/json"),
            json={"message": {"raw": raw}},
        )
        resp.raise_for_status()
        created = resp.json()
        msg = created.get("message", {}) or {}
        return {
            "id": created.get("id"),
            "messageId": msg.get("id"),
            "threadId": msg.get("threadId"),
            "provider": "gmail",
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
        """Create a threaded reply DRAFT (users.drafts.create with threadId).

        Composes recipients and threading headers exactly like reply(), but
        writes the MIME to Drafts (threaded via threadId + In-Reply-To) rather
        than sending it.
        """
        original = self._get_message(
            message_id,
            fmt="metadata",
            headers=("Subject", "From", "To", "Cc", "Message-ID", "References"),
        )
        payload = original.get("payload", {}) or {}
        orig_subject = _header(payload, "Subject") or ""
        orig_from = _email_only(_header(payload, "From"))
        orig_to = _emails_only(_header(payload, "To"))
        orig_cc = _emails_only(_header(payload, "Cc"))
        orig_msgid = _header(payload, "Message-ID") or _header(payload, "Message-Id")
        orig_refs = _header(payload, "References")

        reply_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        self_addr = self.account.address.lower()
        sender_addr = (orig_from or "").lower()
        to = [orig_from] if orig_from else []
        exclude = {self_addr, sender_addr}
        final_cc = _extra_recipients(
            (orig_to + orig_cc if reply_all else []) + (cc or []),
            exclude,
        )
        final_bcc = _extra_recipients(
            bcc,
            exclude,
            already={a.lower() for a in to} | {a.lower() for a in final_cc},
        )

        mime = self._build_mime(
            subject=reply_subject,
            body_text=body_text,
            body_html=body_html,
            to=to,
            cc=final_cc,
            bcc=final_bcc,
            attachments=attachments,
            in_reply_to=orig_msgid,
            references=f"{orig_refs} {orig_msgid}".strip() if orig_refs else orig_msgid,
        )
        raw = base64.urlsafe_b64encode(mime).decode("ascii")
        resp = self._client.post(
            "/users/me/drafts",
            headers=self._headers(content_type="application/json"),
            json={"message": {"raw": raw, "threadId": original.get("threadId")}},
        )
        resp.raise_for_status()
        created = resp.json()
        msg = created.get("message", {}) or {}
        return {
            "id": created.get("id"),
            "messageId": msg.get("id"),
            "threadId": msg.get("threadId"),
            "provider": "gmail",
        }
