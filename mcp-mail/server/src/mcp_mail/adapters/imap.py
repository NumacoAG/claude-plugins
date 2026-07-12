"""IMAP + SMTP adapter for iCloud and Yahoo."""

from __future__ import annotations

import email
import imaplib
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage, Message
from email.utils import getaddresses, make_msgid, parseaddr, parsedate_to_datetime
from pathlib import Path

import keyring

from ..config import IMAPAccount

INLINE_ATTACHMENT_LIMIT = 25 * 1024 * 1024


def _get_password(account: IMAPAccount) -> str:
    pw = keyring.get_password(account.keychain_service, account.keychain_user)
    if not pw:
        raise RuntimeError(
            f"No app-specific password in Keychain for {account.id!r} "
            f"(service={account.keychain_service!r}, account={account.keychain_user!r}). "
            "Generate one at the provider and add the Keychain entry."
        )
    return pw


def _parse_date(date_s: str | None) -> str | None:
    if not date_s:
        return None
    try:
        return parsedate_to_datetime(date_s).isoformat()
    except Exception:
        return None


def _extract_flags(flag_part: str) -> list[str]:
    """Parse a raw FETCH FLAGS chunk like '... FLAGS (\\Seen \\Answered)' into ['\\Seen', '\\Answered']."""
    if "FLAGS" not in flag_part:
        return []
    start = flag_part.find("(", flag_part.find("FLAGS"))
    end = flag_part.find(")", start)
    if start == -1 or end == -1:
        return []
    return [f.decode() if isinstance(f, bytes) else f for f in flag_part[start + 1 : end].split()]


def _extract_parts(msg: Message) -> tuple[str | None, str | None, list[dict]]:
    """Walk a parsed RFC822 message. Returns (text_body, html_body, attachment_metas)."""
    text: str | None = None
    html: str | None = None
    attachments: list[dict] = []
    for idx, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        is_attachment = bool(filename) or "attachment" in disposition

        if is_attachment:
            payload = part.get_payload(decode=True) or b""
            attachments.append({
                "id": f"part-{idx}",
                "name": filename or f"attachment-{idx}",
                "size": len(payload),
                "contentType": ctype,
                "isInline": "inline" in disposition,
            })
        elif ctype == "text/plain" and text is None:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        elif ctype == "text/html" and html is None:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            html = payload.decode(charset, errors="replace")
    return text, html, attachments


class IMAPAdapter:
    """IMAP/SMTP adapter. Each tool call opens its own short-lived connections."""

    def __init__(self, account: IMAPAccount) -> None:
        self.account = account
        self._folder_cache: dict[str, str] | None = None

    # ---- connections -------------------------------------------------------

    def _imap(self) -> imaplib.IMAP4_SSL:
        ctx = ssl.create_default_context()
        m = imaplib.IMAP4_SSL(self.account.imap_host, self.account.imap_port, ssl_context=ctx)
        m.login(self.account.address, _get_password(self.account))
        return m

    def _smtp(self) -> smtplib.SMTP:
        s = smtplib.SMTP(self.account.smtp_host, self.account.smtp_port, timeout=30)
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(self.account.address, _get_password(self.account))
        return s

    @staticmethod
    def _close(m: imaplib.IMAP4_SSL) -> None:
        try:
            m.close()
        except Exception:
            pass
        try:
            m.logout()
        except Exception:
            pass

    # ---- sanity ------------------------------------------------------------

    def me(self) -> dict:
        m = self._imap()
        try:
            m.noop()
        finally:
            m.logout()
        return {
            "displayName": None,
            "userPrincipalName": self.account.address,
            "mail": self.account.address,
            "id": self.account.address,
        }

    # ---- folders -----------------------------------------------------------

    def _discover_folders(self) -> list[dict]:
        m = self._imap()
        try:
            _, data = m.list()
        finally:
            m.logout()

        out: list[dict] = []
        for raw in data or []:
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            # Format: (\Flag1 \Flag2) "/" "FolderName" — flags within parens, then delimiter, then quoted name.
            close = line.find(")")
            if close == -1:
                continue
            flags = [f for f in line[1:close].split() if f.startswith("\\")]
            rest = line[close + 1 :].strip()
            # Take the last quoted token as the folder name.
            parts = rest.split('"')
            name = parts[-2] if len(parts) >= 2 else rest.strip()
            out.append({"name": name, "flags": flags})
        return out

    def list_folders(self) -> list[dict]:
        return [
            {
                "id": f["name"],
                "displayName": f["name"],
                "type": "system" if any(fl in ("\\Sent", "\\Drafts", "\\Trash", "\\Junk", "\\Archive", "\\Inbox") for fl in f["flags"]) else "user",
                "flags": f["flags"],
                "totalItemCount": None,
                "unreadItemCount": None,
            }
            for f in self._discover_folders()
        ]

    def _build_folder_cache(self) -> dict[str, str]:
        cache: dict[str, str] = {"inbox": "INBOX"}
        flag_to_name: dict[str, str] = {}
        for f in self._discover_folders():
            for flag in f["flags"]:
                flag_to_name[flag] = f["name"]
        for canonical, flag in [
            ("sent", "\\Sent"), ("sentitems", "\\Sent"),
            ("drafts", "\\Drafts"), ("draft", "\\Drafts"),
            ("trash", "\\Trash"), ("deleteditems", "\\Trash"),
            ("junk", "\\Junk"), ("spam", "\\Junk"), ("junkemail", "\\Junk"),
            ("archive", "\\Archive"),
        ]:
            if flag in flag_to_name:
                cache[canonical] = flag_to_name[flag]
        return cache

    def _resolve_folder(self, folder: str) -> str:
        if self._folder_cache is None:
            self._folder_cache = self._build_folder_cache()
        return self._folder_cache.get(folder.lower(), folder)

    # ---- message ids -------------------------------------------------------

    @staticmethod
    def _split_id(message_id: str) -> tuple[str, int]:
        folder, _, uid_s = message_id.rpartition("/")
        if not folder or not uid_s.isdigit():
            raise ValueError(f"Invalid message_id {message_id!r}: expected 'folder/uid' format")
        return folder, int(uid_s)

    @staticmethod
    def _join_id(folder: str, uid: int) -> str:
        return f"{folder}/{uid}"

    # ---- search ------------------------------------------------------------

    def search(self, query: str = "", folder: str | None = None, limit: int = 25) -> list[dict]:
        target = self._resolve_folder(folder or "INBOX")
        m = self._imap()
        try:
            m.select(f'"{target}"', readonly=True)
            if query:
                # TEXT searches headers + body; safer cross-provider than BODY.
                _, data = m.uid("SEARCH", None, "UNDELETED", "TEXT", f'"{query}"')
            else:
                _, data = m.uid("SEARCH", None, "UNDELETED")
            uids = (data[0].split() if data and data[0] else [])
            uids = list(reversed(uids))[:limit]
            if not uids:
                return []

            # Batch the FETCH for all UIDs in one call.
            uid_set = b",".join(uids)
            _, fetched = m.uid(
                "FETCH",
                uid_set,
                "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])",
            )

            # imaplib returns each message as a tuple in the list, plus a closing b')'
            # between messages. Walk in pairs.
            results: list[dict] = []
            current_flags: list[str] = []
            current_uid: int | None = None
            for item in fetched:
                if isinstance(item, tuple) and len(item) >= 2:
                    meta = item[0].decode("utf-8", errors="replace") if isinstance(item[0], bytes) else str(item[0])
                    current_flags = _extract_flags(meta)
                    # Extract UID from the metadata line, e.g. "1 (UID 42 FLAGS ...)"
                    uid_idx = meta.find("UID ")
                    if uid_idx != -1:
                        rest = meta[uid_idx + 4 :].split()
                        if rest and rest[0].rstrip(")").isdigit():
                            current_uid = int(rest[0].rstrip(")"))
                    header_bytes = item[1]
                    if header_bytes and current_uid is not None:
                        msg = email.message_from_bytes(header_bytes)
                        results.append({
                            "id": self._join_id(target, current_uid),
                            "conversationId": None,
                            "subject": msg.get("Subject"),
                            "from": parseaddr(msg.get("From", ""))[1] or None,
                            "to": [a for _, a in getaddresses(msg.get_all("To") or []) if a],
                            "receivedDateTime": _parse_date(msg.get("Date")),
                            "isRead": "\\Seen" in current_flags,
                            "hasAttachments": False,  # would need BODYSTRUCTURE; skip in search
                            "bodyPreview": None,
                            "webLink": None,
                        })
                    current_uid = None
            return results
        finally:
            self._close(m)

    # ---- read --------------------------------------------------------------

    def read(self, message_id: str) -> dict:
        folder, uid = self._split_id(message_id)
        m = self._imap()
        try:
            m.select(f'"{folder}"', readonly=True)
            _, fetched = m.uid("FETCH", str(uid).encode(), "(FLAGS BODY.PEEK[])")
            raw: bytes | None = None
            flags: list[str] = []
            for item in fetched:
                if isinstance(item, tuple) and len(item) >= 2:
                    meta = item[0].decode("utf-8", errors="replace") if isinstance(item[0], bytes) else str(item[0])
                    flags = _extract_flags(meta)
                    raw = item[1]
            if not raw:
                raise KeyError(f"Message {message_id} not found")
            msg = email.message_from_bytes(raw)
            text, html, attachments = _extract_parts(msg)
            body = html or text or ""
            return {
                "id": message_id,
                "conversationId": None,
                "subject": msg.get("Subject"),
                "from": parseaddr(msg.get("From", ""))[1] or None,
                "to": [a for _, a in getaddresses(msg.get_all("To") or []) if a],
                "cc": [a for _, a in getaddresses(msg.get_all("Cc") or []) if a],
                "receivedDateTime": _parse_date(msg.get("Date")),
                "isRead": "\\Seen" in flags,
                "hasAttachments": bool(attachments),
                "attachments": attachments,
                "internetMessageId": msg.get("Message-ID") or msg.get("Message-Id"),
                "bodyContentType": "HTML" if html else "Text",
                "body": body,
                "webLink": None,
                "listUnsubscribe": msg.get("List-Unsubscribe"),
                "listUnsubscribePost": msg.get("List-Unsubscribe-Post"),
            }
        finally:
            self._close(m)

    # ---- attachments -------------------------------------------------------

    def list_attachments(self, message_id: str) -> list[dict]:
        # Cheapest reuse: full read returns them; IMAP has no separate cheap path.
        return self.read(message_id).get("attachments", [])

    def download_attachment(self, message_id: str, attachment_id: str) -> tuple[str, bytes]:
        folder, uid = self._split_id(message_id)
        m = self._imap()
        try:
            m.select(f'"{folder}"', readonly=True)
            _, fetched = m.uid("FETCH", str(uid).encode(), "(BODY.PEEK[])")
            raw: bytes | None = None
            for item in fetched:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw = item[1]
            if not raw:
                raise KeyError(f"Message {message_id} not found")
        finally:
            self._close(m)

        if not attachment_id.startswith("part-"):
            raise ValueError(f"Invalid attachment_id {attachment_id!r}; expected 'part-<n>'")
        target_idx = int(attachment_id.removeprefix("part-"))
        msg = email.message_from_bytes(raw)
        for idx, part in enumerate(msg.walk()):
            if idx == target_idx:
                payload = part.get_payload(decode=True) or b""
                filename = part.get_filename() or f"attachment-{idx}"
                return filename, payload
        raise KeyError(f"Attachment {attachment_id} not found in {message_id}")

    # ---- mutate ------------------------------------------------------------

    def mark_read(self, message_id: str, read: bool = True) -> None:
        folder, uid = self._split_id(message_id)
        m = self._imap()
        try:
            m.select(f'"{folder}"')
            cmd = "+FLAGS" if read else "-FLAGS"
            m.uid("STORE", str(uid).encode(), cmd, "(\\Seen)")
        finally:
            self._close(m)

    def move(self, message_id: str, target_folder: str) -> dict:
        folder, uid = self._split_id(message_id)
        target = self._resolve_folder(target_folder)
        m = self._imap()
        try:
            m.select(f'"{folder}"')
            # Try MOVE (RFC 6851); fall back to COPY + STORE \Deleted + EXPUNGE.
            try:
                typ, _ = m.uid("MOVE", str(uid).encode(), f'"{target}"')
                if typ != "OK":
                    raise RuntimeError("MOVE not OK")
            except Exception:
                m.uid("COPY", str(uid).encode(), f'"{target}"')
                m.uid("STORE", str(uid).encode(), "+FLAGS", "(\\Deleted)")
                m.expunge()
            # Without UIDPLUS we can't get the new UID reliably. Return the
            # target folder name so the caller knows where it went.
            return {"id": self._join_id(target, -1)}
        finally:
            self._close(m)

    def mark_spam(self, message_id: str) -> dict:
        return self.move(message_id, "spam")

    def delete(self, message_id: str) -> None:
        """Soft-delete: move to Trash."""
        self.move(message_id, "trash")

    def block_sender(self, sender: str) -> dict:
        """IMAP has no standardized server-side filter API.

        Most IMAP providers (iCloud, Yahoo) only expose filters/rules via
        their web UI. The unsubscribe cascade catches this NotImplementedError
        and falls through to delete.
        """
        raise NotImplementedError(
            f"block_sender not supported on {self.account.provider}: "
            "IMAP exposes no standard server-side filter API. "
            "Add a filter in the provider's web UI instead."
        )

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
    ) -> EmailMessage:
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
        msg["Message-ID"] = make_msgid(domain=self.account.address.split("@", 1)[1])
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to

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
        return msg

    def _append_to_sent(self, msg: EmailMessage) -> None:
        """IMAP servers don't auto-save SMTP-sent messages. APPEND to Sent ourselves."""
        try:
            sent = self._resolve_folder("sent")
        except Exception:
            return
        try:
            m = self._imap()
            try:
                m.append(f'"{sent}"', "(\\Seen)", None, msg.as_bytes())
            finally:
                m.logout()
        except Exception:
            pass  # don't fail the send if APPEND fails

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
        msg = self._build_mime(subject, body_text, body_html, to, cc, bcc, attachments)
        with self._smtp() as s:
            s.send_message(msg)
        self._append_to_sent(msg)

    def reply(
        self,
        message_id: str,
        body_text: str | None = None,
        body_html: str | None = None,
        reply_all: bool = False,
        attachments: list[str] | None = None,
    ) -> None:
        original = self.read(message_id)
        orig_subject = original.get("subject") or ""
        orig_from = original.get("from")
        orig_to = original.get("to") or []
        orig_cc = original.get("cc") or []
        orig_msgid = original.get("internetMessageId")

        reply_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        to = [orig_from] if orig_from else []
        cc: list[str] = []
        if reply_all:
            self_addr = self.account.address.lower()
            cc = [
                a for a in (orig_to + orig_cc)
                if a.lower() != self_addr and a.lower() != (orig_from or "").lower()
            ]

        msg = self._build_mime(
            reply_subject,
            body_text,
            body_html,
            to,
            cc=cc,
            attachments=attachments,
            in_reply_to=orig_msgid,
        )
        with self._smtp() as s:
            s.send_message(msg)
        self._append_to_sent(msg)
