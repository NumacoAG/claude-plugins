"""Microsoft Graph adapter for M365 accounts."""

from __future__ import annotations

import base64
import contextlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

import httpx

from ._recipients import _extra_recipients
from ..auth import acquire_file_token, acquire_shared_token, acquire_token
from ..config import M365Account

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Per-file threshold for riding inline (base64) in the message JSON. Anything
# ABOVE it goes to the mailbox through createUploadSession instead.
#
# The same number is the upload session's FLOOR, which is why only one threshold
# exists: Graph answers ErrorAttachmentSizeShouldNotBeLessThanMinimumSize when
# asked to open a session for a file smaller than 3MB. A file may therefore ride
# inline or take a session, never both and never neither, and nothing under this
# line may ever be routed to a session.
INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024

# Graph rejects a message request body over ~4MB, and the ceiling applies to the
# WHOLE request, not to one attachment: several files that are each small enough
# to ride inline can still blow it collectively. Attachments travel base64-
# encoded (4/3 of their raw size), so this budget is measured in ENCODED bytes.
# It is exactly the encoded cost of ONE file at INLINE_ATTACHMENT_LIMIT: any
# smaller value would contradict the per-file threshold, refusing a lone
# attachment that is too small for a session and, by that budget, too big to
# ride inline. Overflow cannot be rerouted (it is under the session minimum), so
# it is refused locally, with an error naming the files and the total.
INLINE_TOTAL_LIMIT = 4 * ((INLINE_ATTACHMENT_LIMIT + 2) // 3)  # 4 MiB encoded

# Upload-session chunk size. Microsoft documents a 4MB ceiling per PUT for the
# OUTLOOK attachment session ("keep each byte range less than 4 MB", repeated on
# the Content-Length header); the 320 KiB-multiple rule commonly quoted belongs
# to the OneDrive driveItem session and does not govern this endpoint. 3.75 MiB
# sits under the documented ceiling (and is a multiple of 320 KiB anyway).
UPLOAD_CHUNK_SIZE = 3840 * 1024  # 3.75 MiB

# A chunk PUT moves megabytes, so it gets a longer budget than the 60s the
# JSON-sized Graph calls share.
UPLOAD_CHUNK_TIMEOUT = 300.0

# How many consecutive PUTs may fail to advance the service's own next-expected
# offset before the upload is declared stuck. Guards the resume loop against a
# session that keeps asking for a range it never accepts.
MAX_UPLOAD_STALLS = 3

# Graph's documented ceiling for a mail attachment upload session.
MAX_ATTACHMENT_SIZE = 150 * 1024 * 1024


@dataclass(frozen=True)
class _PendingUpload:
    """A file too big to ride inline; uploaded to an existing draft in chunks."""

    path: Path
    name: str
    size: int
    content_type: str
    is_inline: bool


@dataclass
class _Candidate:
    """One caller-supplied attachment path, stat'ed but not yet read."""

    order: int
    path: Path
    size: int
    content_type: str
    is_inline: bool

    @property
    def name(self) -> str:
        return self.path.name


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
    def _b64_size(raw: int) -> int:
        """Wire cost of ``raw`` bytes once base64-encoded.

        Base64 emits 4 characters per 3 input bytes and pads the last group, so
        the encoded length is ceil(raw * 4 / 3) rounded up to a multiple of 4.
        """
        return 4 * ((raw + 2) // 3)

    @classmethod
    def _partition_attachments(
        cls, paths: list[str] | None, body_html: str | None = None
    ) -> tuple[list[dict], list[_PendingUpload]]:
        """Split local paths into (inline fileAttachment dicts, chunked uploads).

        Size alone picks the route, because Graph's two routes meet exactly at
        INLINE_ATTACHMENT_LIMIT: at or below it a file rides inline (base64 in
        the message JSON), above it a file becomes a `_PendingUpload` that the
        caller streams to an already created draft via createUploadSession. The
        request-wide budget can NOT move a file between routes -- a small file
        pushed at a session is refused with
        ErrorAttachmentSizeShouldNotBeLessThanMinimumSize -- so a set of
        individually-inline files that together overflow the request is refused
        here, by name, instead of being sent to an endpoint that cannot take it.

        If ``body_html`` references an attachment by ``cid:<filename>``, that
        attachment is marked inline (``isInline`` + ``contentId`` = filename) so
        it renders inside the message body (e.g. a signature logo) rather than as
        a separate downloadable file. Those cid-referenced files also get first
        claim on the inline budget, so when a request is tight it is the bulk
        attachment that is reported as not fitting, never the signature logo.
        Attachments not referenced this way stay regular attachments, and when
        everything fits the emitted payload is identical to what this adapter has
        always sent.
        """
        if not paths:
            return [], []

        candidates: list[_Candidate] = []
        for i, p in enumerate(paths):
            path = Path(p).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")
            size = path.stat().st_size
            if size > MAX_ATTACHMENT_SIZE:
                raise ValueError(
                    f"Attachment {path.name} is "
                    f"{size / 1024 / 1024:.1f}MB; Microsoft Graph caps a single "
                    f"mail attachment at "
                    f"{MAX_ATTACHMENT_SIZE // 1024 // 1024}MB even with an upload "
                    f"session. Share it as a link instead of attaching it."
                )
            ctype, _ = mimetypes.guess_type(str(path))
            candidates.append(
                _Candidate(
                    order=i,
                    path=path,
                    size=size,
                    content_type=ctype or "application/octet-stream",
                    is_inline=bool(body_html and f"cid:{path.name}" in body_html),
                )
            )

        inline: list[_Candidate] = []
        uploads: list[_Candidate] = []
        overflow: list[_Candidate] = []
        budget = INLINE_TOTAL_LIMIT
        # cid-referenced files first (they are signature logos and must render in
        # the body), then the rest in the caller's order. Each group keeps its
        # relative order, and the surviving inline set is re-sorted below, so a
        # payload that fits entirely is byte-for-byte what it always was.
        for cand in sorted(candidates, key=lambda c: (not c.is_inline, c.order)):
            if cand.size > INLINE_ATTACHMENT_LIMIT:
                uploads.append(cand)
                continue
            cost = cls._b64_size(cand.size)
            if cost > budget:
                # Too big for what is left of the request, too small for a
                # session: there is no route, so say so rather than pick one
                # Graph will reject.
                overflow.append(cand)
                continue
            budget -= cost
            inline.append(cand)

        if overflow:
            small = [c for c in candidates if c.size <= INLINE_ATTACHMENT_LIMIT]
            total = sum(cls._b64_size(c.size) for c in small)
            names = ", ".join(c.name for c in sorted(small, key=lambda c: c.order))
            spilled = ", ".join(c.name for c in sorted(overflow, key=lambda c: c.order))
            raise ValueError(
                f"These attachments are each small enough to send, but together "
                f"they need {total / 1024 / 1024:.1f}MB of encoded space against "
                f"the {INLINE_TOTAL_LIMIT / 1024 / 1024:.1f}MB Microsoft Graph "
                f"allows in one message request: {names}. The ones that no longer "
                f"fit ({spilled}) cannot be rerouted either, because Graph refuses "
                f"an upload session for any file under "
                f"{INLINE_ATTACHMENT_LIMIT / 1024 / 1024:.0f}MB. Send them across "
                f"several messages, or share the bulky ones as links."
            )

        out: list[dict] = []
        for cand in sorted(inline, key=lambda c: c.order):
            att: dict = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": cand.name,
                "contentType": cand.content_type,
                "contentBytes": base64.b64encode(cand.path.read_bytes()).decode("ascii"),
            }
            if cand.is_inline:
                att["isInline"] = True
                att["contentId"] = cand.name
            out.append(att)

        pending = [
            _PendingUpload(
                path=c.path,
                name=c.name,
                size=c.size,
                content_type=c.content_type,
                is_inline=c.is_inline,
            )
            for c in sorted(uploads, key=lambda c: c.order)
        ]
        return out, pending

    # ---- large attachments (createUploadSession) ---------------------------
    #
    # Graph only accepts a big file against a message that ALREADY EXISTS in the
    # mailbox, i.e. a draft: you open an upload session on the draft's attachment
    # collection and PUT byte ranges to the pre-authenticated URL it hands back.
    # There is no such route on /sendMail, so send() restructures itself into
    # create draft -> upload -> POST /send when any attachment is oversized.

    def _guard_delegate_upload(self, uploads: list[_PendingUpload]) -> None:
        """Refuse an upload session on a delegated mailbox before anything exists.

        Microsoft: "An app with delegated permissions returns HTTP 403 Forbidden
        when attempting to attach large files to an Outlook message or event that
        is in a shared or delegated mailbox. With delegated permissions,
        createUploadSession succeeds only if the message or event is in the
        signed-in user's mailbox." No workaround is listed, so the refusal has to
        come BEFORE the draft is created; otherwise Graph 403s halfway through and
        a body-and-recipients draft with no attachment is stranded in someone
        else's mailbox. send() and reply() already refuse a delegate outright;
        this covers the two draft paths, which do not.
        """
        if not uploads or not self.account.mailbox:
            return
        raise RuntimeError(
            f"Attaching a large file to a message in the delegated mailbox "
            f"({self.account.mailbox}) is not possible: Microsoft Graph refuses "
            f"createUploadSession (HTTP 403) for any mailbox other than the "
            f"signed-in user's, and there is no workaround. Too big to ride "
            f"inline: "
            + ", ".join(f"{u.name} ({u.size / 1024 / 1024:.1f}MB)" for u in uploads)
            + ". Share those as links, or create the draft in your own mailbox."
        )

    def _upload_attachment(self, message_id: str, item: _PendingUpload) -> None:
        """Attach one oversized file to an existing draft, in chunks."""
        att_item: dict = {
            "attachmentType": "file",
            "name": item.name,
            "size": item.size,
            "contentType": item.content_type,
        }
        if item.is_inline:
            att_item["isInline"] = True
            att_item["contentId"] = item.name
        resp = self._client.post(
            f"{self._mail_root}/messages/{message_id}/attachments/createUploadSession",
            headers=self._headers(content_type="application/json"),
            json={"AttachmentItem": att_item},
        )
        # Checked by hand rather than via raise_for_status, which would drop both
        # Graph's reason and the identity of the file that could not be attached.
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Graph refused an upload session for {item.name} "
                f"({item.size / 1024 / 1024:.1f}MB): HTTP {resp.status_code} "
                f"{self._body_excerpt(resp)}"
            )
        upload_url = (resp.json() or {}).get("uploadUrl")
        if not upload_url:
            raise RuntimeError(
                f"Graph opened no upload session for {item.name} "
                f"({item.size / 1024 / 1024:.1f}MB): the response carried no "
                f"uploadUrl."
            )
        try:
            self._put_chunks(upload_url, item)
        except Exception:
            self._cancel_upload_session(upload_url)
            raise

    def _put_chunks(self, upload_url: str, item: _PendingUpload) -> None:
        """PUT the file to the session URL in Content-Range slices.

        The uploadUrl is absolute and PRE-AUTHENTICATED (its token sits in the
        query string) and lives on a different host from the Graph API, so no
        Authorization header may be attached: sending one can get the request
        rejected outright. httpx leaves an absolute URL untouched by the client's
        base_url, so the same client is safe to reuse for these requests.

        The service's answer is the only completeness signal there is, and it is
        asymmetric: every PUT that leaves the attachment unfinished answers
        200 OK carrying `nextExpectedRanges`, and ONLY the PUT that assembles it
        answers 201 Created (with a Location header). So a 200 on the last byte
        range means the service did NOT receive everything, however many bytes
        were handed to it, and the local byte counter is not evidence of
        anything. The loop is therefore driven by `nextExpectedRanges` -- which
        is where Microsoft says to resume from -- and only a 201 ends it.
        """
        total = item.size
        if total <= 0:
            raise ValueError(
                f"Attachment {item.name} is empty (0 bytes); Graph cannot open an "
                f"upload session for it."
            )
        status = 0
        completed = False
        stalls = 0
        with item.path.open("rb") as fh:
            start = 0
            while start < total:
                fh.seek(start)
                chunk = fh.read(min(UPLOAD_CHUNK_SIZE, total - start))
                if not chunk:
                    raise RuntimeError(
                        f"Attachment {item.name} shrank while uploading: expected "
                        f"{total} bytes, ran out at {start}."
                    )
                end = start + len(chunk) - 1
                resp = self._client.put(
                    upload_url,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                    content=chunk,
                    timeout=UPLOAD_CHUNK_TIMEOUT,
                )
                status = resp.status_code
                if status == 201:
                    # The attachment is assembled; nothing else is.
                    completed = True
                    break
                # 200 is the documented "more expected"; 202 is accepted too so a
                # service that uses it is not mistaken for a failure. Anything
                # else IS a failure, and the body carries the reason that
                # raise_for_status would drop.
                if status not in (200, 202):
                    raise RuntimeError(
                        f"Upload of {item.name} failed at bytes {start}-{end}/"
                        f"{total}: HTTP {status} {self._body_excerpt(resp)}"
                    )
                # Resume where the SERVICE says it wants the next byte, not where
                # the local counter landed: when it commits less than was sent,
                # advancing blindly leaves an unwritten hole in the attachment.
                nxt = self._next_expected_start(resp)
                if nxt is None:
                    nxt = end + 1
                if nxt <= start:
                    stalls += 1
                    if stalls >= MAX_UPLOAD_STALLS:
                        raise RuntimeError(
                            f"Upload of {item.name} is stuck: after "
                            f"{stalls} attempts Graph still expects byte {nxt} "
                            f"of {total} and accepts nothing more."
                        )
                else:
                    stalls = 0
                start = nxt
        if not completed:
            raise RuntimeError(
                f"Upload of {item.name} ({total} bytes) never completed: Graph "
                f"answered the last byte range with HTTP {status}, not the 201 "
                f"Created that marks the attachment as assembled, so it still "
                f"holds only part of the file."
            )

    @staticmethod
    def _next_expected_start(resp: object) -> int | None:
        """First offset from a session response's ``nextExpectedRanges``.

        Microsoft: "Use the nextExpectedRanges collection to determine where to
        start the next byte range to upload." Entries look like ``"4194304-"`` or
        ``"4194304-8388607"``. Returns None when the response carries no usable
        range, leaving the caller to fall back on its own counter.
        """
        try:
            payload = resp.json()  # type: ignore[attr-defined]
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        ranges = payload.get("nextExpectedRanges")
        if not isinstance(ranges, list) or not ranges:
            return None
        head = str(ranges[0]).strip().split("-", 1)[0].strip()
        try:
            return int(head)
        except ValueError:
            return None

    def _cancel_upload_session(self, upload_url: str) -> None:
        """Best-effort DELETE of a half-written session; never masks the cause."""
        # Cleanup must not replace the real error, so every failure is swallowed.
        with contextlib.suppress(Exception):
            self._client.delete(upload_url, timeout=UPLOAD_CHUNK_TIMEOUT)

    @staticmethod
    def _body_excerpt(resp: object, limit: int = 400) -> str:
        """Graph's own error text, which raise_for_status would otherwise drop."""
        text = getattr(resp, "text", "") or ""
        return text[:limit]

    def _upload_all(self, draft_id: str | None, uploads: list[_PendingUpload]) -> None:
        """Upload every oversized attachment to a draft that already exists.

        A failure part-way leaves a draft that LOOKS finished (it already carries
        the body, the recipients and whichever files did upload), so the error
        has to name what is missing: a user told only "it failed" opens Outlook,
        sees attachments, and sends a mail without the annexes.
        """
        if not uploads:
            return
        if not draft_id:
            raise RuntimeError(
                "Graph returned no draft id, so the large attachments "
                f"({', '.join(u.name for u in uploads)}) could not be uploaded."
            )
        for i, item in enumerate(uploads):
            try:
                self._upload_attachment(draft_id, item)
            except Exception as exc:
                attached = [u.name for u in uploads[:i]]
                missing = [u.name for u in uploads[i:]]
                raise RuntimeError(
                    f"{exc} The draft is INCOMPLETE: "
                    f"{', '.join(missing)} "
                    f"{'is' if len(missing) == 1 else 'are'} NOT attached"
                    + (f" ({', '.join(attached)} did upload)" if attached else "")
                    + ". Do not send it as it stands."
                ) from exc

    def _upload_onto_draft(
        self, draft_id: str | None, uploads: list[_PendingUpload], what: str
    ) -> None:
        """_upload_all for the DRAFT paths, which must name what they left behind.

        The send paths already tell the user a draft is sitting in Drafts; the
        draft paths used to let the raw transport error out, so a half-built
        draft accumulated silently on every retry.
        """
        if not uploads:
            return
        try:
            self._upload_all(draft_id, uploads)
        except Exception as exc:
            raise RuntimeError(
                f"{what} was created but its large attachments could not all be "
                f"uploaded: {exc} The draft"
                + (f" (id {draft_id})" if draft_id else "")
                + " is still in Drafts; delete it or attach the missing files by "
                "hand."
            ) from exc

    def _send_draft_or_report(self, draft_id: str | None, what: str) -> None:
        """POST /send, then be exact about what a failure does and does not prove.

        A refusal Graph ANSWERED (a status came back) proves the send did not
        happen. A transport failure proves nothing at all: the request left the
        machine and no answer returned, so the mail may well have gone out and
        the draft may already have moved to Sent Items. Asserting "NOT sent"
        there is how the same mail reaches a customer twice, so that case is
        reported as UNKNOWN instead.
        """
        if not draft_id:
            raise RuntimeError(
                f"Graph returned no draft id, so the {what} could not be sent."
            )
        try:
            resp = self._client.post(
                f"{self._mail_root}/messages/{draft_id}/send",
                headers=self._headers(),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Sending the {what} failed at the send step: {exc} The outcome is "
                f"UNKNOWN: the send request went out and no answer came back, so "
                f"the {what} may or may not have been sent. Check Sent Items "
                f"before resending (the draft id is {draft_id})."
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Sending the {what} failed at the send step: Graph refused it "
                f"with HTTP {resp.status_code} {self._body_excerpt(resp)}. The "
                f"{what} was NOT sent; the draft (id {draft_id}) is still in "
                f"Drafts with its attachments."
            )

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
        atts, uploads = self._partition_attachments(attachments, body_html)
        if atts:
            message["attachments"] = atts

        if uploads:
            self._send_with_large_attachments(message, uploads)
            return

        resp = self._client.post(
            "/me/sendMail",
            headers=self._headers(content_type="application/json"),
            json={"message": message, "saveToSentItems": True},
        )
        resp.raise_for_status()

    def _send_with_large_attachments(
        self, message: dict, uploads: list[_PendingUpload]
    ) -> None:
        """Send a message whose attachments are too big for /sendMail.

        /sendMail carries its message entirely in one request body, so there is
        no upload-session route through it. The only way a big file reaches the
        wire is against a message that already exists in the mailbox, so the send
        becomes: create draft -> upload each big file -> POST /send. Callers must
        have cleared the delegated-mailbox guard first, so `_mail_root` is /me.
        """
        resp = self._client.post(
            f"{self._mail_root}/messages",
            headers=self._headers(content_type="application/json"),
            json=message,
        )
        resp.raise_for_status()
        draft_id = (resp.json() or {}).get("id")
        try:
            self._upload_all(draft_id, uploads)
        except Exception as exc:
            # Nothing was sent: /send was never reached.
            raise RuntimeError(
                f"Sending with large attachments failed after the draft was "
                f"created: {exc} The message was NOT sent; the draft"
                + (f" (id {draft_id})" if draft_id else "")
                + " is still in Drafts."
            ) from exc
        self._send_draft_or_report(draft_id, what="message")

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
        body = self._build_body(body_text, body_html)  # validated before any I/O
        atts, uploads = self._partition_attachments(attachments, body_html)
        if uploads:
            # The /reply action, like /sendMail, carries the whole message in a
            # single request body, so it has no upload-session route either.
            # Compose the identical reply as a DRAFT (createReply threads it and
            # its attachment collection does take upload sessions), then send it.
            # create_reply_draft leaves the recipients /createReply resolved
            # alone unless they need composing, exactly as the single-shot /reply
            # action below does, so the recipient set does not depend on how big
            # the attachment happened to be.
            try:
                draft = self.create_reply_draft(
                    message_id,
                    body_text=body_text,
                    body_html=body_html,
                    reply_all=reply_all,
                    attachments=attachments,
                    cc=cc,
                    bcc=bcc,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Replying with large attachments failed before the send "
                    f"step: {exc} The reply was NOT sent."
                ) from exc
            self._send_draft_or_report(draft.get("id"), what="reply")
            return

        message: dict = {"body": body}
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
        atts, uploads = self._partition_attachments(attachments, body_html)
        # A delegated mailbox cannot take an upload session at all, so refuse
        # before the draft exists rather than strand an attachment-less one.
        self._guard_delegate_upload(uploads)
        if atts:
            message["attachments"] = atts

        resp = self._client.post(
            f"{self._mail_root}/messages",
            headers=self._headers(content_type="application/json"),
            json=message,
        )
        resp.raise_for_status()
        created = resp.json()
        # Big files can only be attached to a message that already exists, so the
        # draft is created first and they are streamed onto it afterwards.
        self._upload_onto_draft(created.get("id"), uploads, what="The draft")
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
        PATCHes the new body. Recipients are only composed and PATCHed when they
        actually need composing (reply_all, or extra cc/bcc), mirroring reply()'s
        single-shot path exactly: /createReply auto-populates the recipient set
        the same way the /reply action does, HONOURING a Reply-To header, and
        overwriting it with the From address would silently redirect a reply to a
        noreply mailbox. Small attachments are POSTed to the draft's attachments
        collection; oversized ones are streamed onto the same draft through an
        upload session. No send action is ever invoked.
        """
        # Partitioned first: it touches no network, so a missing file, an
        # over-ceiling file, or a delegated mailbox that cannot take an upload
        # session all fail before a draft exists to be stranded.
        atts, uploads = self._partition_attachments(attachments, body_html)
        self._guard_delegate_upload(uploads)

        resp = self._client.post(
            f"{self._mail_root}/messages/{message_id}/createReply",
            headers=self._headers(content_type="application/json"),
            json={},
        )
        resp.raise_for_status()
        draft = resp.json()
        draft_id = draft.get("id")

        patch: dict = {"body": self._build_body(body_text, body_html)}
        if reply_all or cc or bcc:
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

        for att in atts:
            aresp = self._client.post(
                f"{self._mail_root}/messages/{draft_id}/attachments",
                headers=self._headers(content_type="application/json"),
                json=att,
            )
            aresp.raise_for_status()
        self._upload_onto_draft(draft_id, uploads, what="The reply draft")

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
