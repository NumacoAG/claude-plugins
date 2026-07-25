"""Tests for inline (cid-referenced) image parity in read() / list_attachments /
download_attachment across the Gmail and IMAP adapters.

A prior release (EMBRASURE) made the Graph adapter surface inline images that
have NO filename (isInline=true) and made their bytes downloadable. These tests
pin the same behaviour for Gmail and IMAP:

- a filename-less inline image part is surfaced as an attachment with a non-empty
  SYNTHESIZED name and ``isInline=True``;
- the text/html body is STILL extracted (never shadowed by the inline part);
- ``download_attachment`` fetches the image bytes;
- CRITICAL guard: a text/html body part carrying ``Content-Disposition: inline``
  is NOT mistaken for an attachment (the body would otherwise be lost).

Everything is offline: message fetches and HTTP/IMAP transports are stubbed, so
no network or Keychain is touched.
"""

from __future__ import annotations

import base64
import email
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import pytest

from mcp_mail.adapters.gmail import GmailAdapter, _extract_parts as _gmail_extract_parts
from mcp_mail.adapters.imap import IMAPAdapter, _extract_parts as _imap_extract_parts


class _Acct:
    id = "acct"
    address = "me@example.com"
    auto_write = True


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any] | None = None) -> None:
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


# ---- Gmail ------------------------------------------------------------------


_IMG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _gmail_inline_message() -> dict:
    """A Gmail 'full' message: html body + a filename-less inline image part.

    The image part carries a body.attachmentId (no body.data), a Content-ID, and
    Content-Disposition: inline — exactly the shape Gmail used to DROP.
    """
    html = base64.urlsafe_b64encode(
        b"<p>Look: <img src=\"cid:img1\"></p>"
    ).decode("ascii")
    return {
        "id": "m1",
        "threadId": "T1",
        "internalDate": "1700000000000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/related",
            "headers": [
                {"name": "Subject", "value": "Inline demo"},
                {"name": "From", "value": "Sender <sender@example.org>"},
                {"name": "To", "value": "me@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": html, "size": 33},
                },
                {
                    "mimeType": "image/png",
                    "filename": "",  # inline image with NO filename
                    "headers": [
                        {"name": "Content-Type", "value": "image/png"},
                        {"name": "Content-Disposition", "value": "inline"},
                        {"name": "Content-ID", "value": "<img1@mail.example.com>"},
                    ],
                    "body": {"attachmentId": "ATT123", "size": len(_IMG_BYTES)},
                },
            ],
        },
    }


def _make_gmail(monkeypatch: pytest.MonkeyPatch, message: dict) -> GmailAdapter:
    adapter = GmailAdapter(_Acct())  # type: ignore[arg-type]

    class _Client:
        def get(self, url: str, **kwargs: Any) -> _FakeResponse:
            # Attachment-bytes endpoint.
            return _FakeResponse(
                {"data": base64.urlsafe_b64encode(_IMG_BYTES).decode("ascii")}
            )

    adapter._client = _Client()  # type: ignore[assignment]
    monkeypatch.setattr(
        adapter, "_headers", lambda content_type=None: {"Authorization": "Bearer t"}
    )
    monkeypatch.setattr(adapter, "_get_message", lambda *a, **k: message)
    return adapter


def test_gmail_extract_parts_surfaces_filenameless_inline_image() -> None:
    text, html, atts = _gmail_extract_parts(_gmail_inline_message()["payload"])

    # HTML body is still extracted (not shadowed by the inline part).
    assert html is not None and "cid:img1" in html
    # Exactly one attachment: the inline image.
    assert len(atts) == 1
    att = atts[0]
    assert att["id"] == "ATT123"
    assert att["isInline"] is True
    assert att["contentType"] == "image/png"
    # Name synthesized from the Content-ID local part; non-empty.
    assert att["name"] == "img1"


def test_gmail_read_and_list_attachments_expose_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_gmail(monkeypatch, _gmail_inline_message())

    out = adapter.read("m1")
    assert out["hasAttachments"] is True
    assert out["bodyContentType"] == "HTML"
    assert "cid:img1" in out["body"]
    assert len(out["attachments"]) == 1
    assert out["attachments"][0]["isInline"] is True
    assert out["attachments"][0]["name"] == "img1"

    atts = adapter.list_attachments("m1")
    assert atts[0]["id"] == "ATT123"
    assert atts[0]["name"] == "img1"
    assert atts[0]["isInline"] is True


def test_gmail_download_inline_resolves_name_and_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_gmail(monkeypatch, _gmail_inline_message())

    name, data = adapter.download_attachment("m1", "ATT123")
    assert name == "img1"
    assert data == _IMG_BYTES


def test_gmail_inline_name_falls_back_to_subtype_without_content_id() -> None:
    # No Content-ID and no filename -> inline-{idx}.{ext} from the MIME subtype.
    payload = {
        "mimeType": "multipart/related",
        "parts": [
            {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<p>hi</p>").decode(), "size": 9}},
            {
                "mimeType": "image/jpeg",
                "filename": "",
                "headers": [{"name": "Content-Disposition", "value": "inline"}],
                "body": {"attachmentId": "ATTX", "size": 5},
            },
        ],
    }
    _, html, atts = _gmail_extract_parts(payload)
    assert html is not None
    assert atts[0]["name"] == "inline-0.jpeg"
    assert atts[0]["isInline"] is True


@pytest.mark.parametrize("mime", ["text/plain", "text/html"])
def test_gmail_externalized_body_not_treated_as_attachment(mime: str) -> None:
    # BLOCKER 2 guard: Gmail externalizes a LARGE text body into
    # body.attachmentId with EMPTY body.data. A filename-less, marker-less
    # (no Content-Disposition, no Content-ID) text/plain or text/html part
    # carrying ONLY body.attachmentId must NOT be surfaced as an attachment —
    # that would flip hasAttachments and report the missing body as a file.
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Big body"}],
        "parts": [
            {
                "mimeType": mime,
                "filename": "",  # no filename
                # no headers -> no Content-Disposition, no Content-ID
                "body": {"attachmentId": "BODYATT", "size": 900000},  # no data
            },
        ],
    }
    text, html, atts = _gmail_extract_parts(payload)
    # No spurious attachment emitted.
    assert atts == []
    # The externalized data is not fetched here; body stays empty. That empty
    # body is the pre-existing behaviour and out of scope — the requirement is
    # only that it is NOT an attachment.
    assert text is None
    assert html is None


def test_gmail_read_externalized_body_keeps_hasattachments_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = {
        "id": "m2",
        "threadId": "T2",
        "internalDate": "1700000000000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Big body"},
                {"name": "From", "value": "sender@example.org"},
                {"name": "To", "value": "me@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "filename": "",
                    "body": {"attachmentId": "BODYATT", "size": 900000},
                },
            ],
        },
    }
    adapter = _make_gmail(monkeypatch, message)
    out = adapter.read("m2")
    assert out["hasAttachments"] is False
    assert out["attachments"] == []


def _gmail_externalized_inline_html_body_message() -> dict:
    """A Gmail 'full' message whose ONLY body part is an externalized text/html
    body carrying ``Content-Disposition: inline``.

    Gmail externalizes a LARGE body into body.attachmentId with EMPTY body.data.
    RFC 2183 makes ``inline`` the DEFAULT disposition for a body, so this shape
    (attachmentId set, data absent, disposition inline, NO filename, NO
    Content-ID) is a body, not an attachment. It must NOT be captured as a
    phantom attachment, and hasAttachments must stay False.
    """
    return {
        "id": "m3",
        "threadId": "T3",
        "internalDate": "1700000000000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Big inline body"},
                {"name": "From", "value": "sender@example.org"},
                {"name": "To", "value": "me@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "filename": "",  # no filename
                    "headers": [
                        {"name": "Content-Type", "value": "text/html"},
                        {"name": "Content-Disposition", "value": "inline"},
                        # no Content-ID
                    ],
                    # attachmentId set, body.data EMPTY/absent
                    "body": {"attachmentId": "INLINEBODY", "size": 900000},
                },
            ],
        },
    }


def test_gmail_externalized_inline_html_body_not_treated_as_attachment() -> None:
    # REGRESSION: a text/html BODY externalized to body.attachmentId (data empty)
    # with Content-Disposition: inline, no filename, no Content-ID is the RFC 2183
    # default-disposition body, NOT an attachment. Removing the "inline" capture
    # sub-clause means it is no longer misclassified as a phantom attachment.
    payload = _gmail_externalized_inline_html_body_message()["payload"]
    text, html, atts = _gmail_extract_parts(payload)

    # No spurious attachment emitted for the inline body part.
    assert atts == []
    # The externalized data is not fetched here; body stays empty (pre-existing
    # behaviour). The requirement is only that it is NOT an attachment.
    assert text is None
    assert html is None


def test_gmail_read_externalized_inline_body_keeps_hasattachments_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end via read()/_project_full: hasAttachments must stay False and no
    # attachment surfaced for the inline-disposition externalized body.
    adapter = _make_gmail(monkeypatch, _gmail_externalized_inline_html_body_message())
    out = adapter.read("m3")
    assert out["hasAttachments"] is False
    assert out["attachments"] == []


def test_gmail_attachment_named_like_inline_is_not_inline() -> None:
    # MINOR 1 (token-aware isInline): a real file attachment whose filename
    # merely CONTAINS the substring "inline" must NOT be classified inline.
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<p>hi</p>").decode(), "size": 9}},
            {
                "mimeType": "application/pdf",
                "filename": "mainline-budget.pdf",
                "headers": [
                    {"name": "Content-Disposition", "value": "attachment; filename=\"mainline-budget.pdf\""},
                ],
                "body": {"attachmentId": "ATTPDF", "size": 12},
            },
        ],
    }
    _, html, atts = _gmail_extract_parts(payload)
    assert html is not None
    assert len(atts) == 1
    assert atts[0]["name"] == "mainline-budget.pdf"
    assert atts[0]["isInline"] is False


# ---- IMAP -------------------------------------------------------------------


def _imap_inline_raw() -> bytes:
    """multipart/related: text/html body + inline image (cid, no filename)."""
    root = MIMEMultipart("related")
    root["Subject"] = "Inline demo"
    root["From"] = "sender@example.org"
    root["To"] = "me@example.com"
    root["Message-ID"] = "<orig@example.org>"

    html = MIMEText("<p>Look: <img src=\"cid:img1\"></p>", "html")
    root.attach(html)

    img = MIMEImage(_IMG_BYTES, _subtype="png")
    img.add_header("Content-Disposition", "inline")  # no filename param
    img.add_header("Content-ID", "<img1@example.com>")
    root.attach(img)

    return root.as_bytes()


class _FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL that serves a fixed raw message."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def select(self, *a: Any, **k: Any) -> tuple[str, list[bytes]]:
        return ("OK", [b"1"])

    def uid(self, cmd: str, *args: Any) -> tuple[str, list[Any]]:
        # Mimics imaplib's FETCH shape: a (meta, payload) tuple + a closing b')'.
        meta = b"1 (UID 5 FLAGS (\\Seen) BODY[] {%d}" % len(self._raw)
        return ("OK", [(meta, self._raw), b")"])

    def close(self) -> None:
        return None

    def logout(self) -> None:
        return None


def _make_imap(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> IMAPAdapter:
    adapter = IMAPAdapter(_Acct())  # type: ignore[arg-type]
    monkeypatch.setattr(adapter, "_imap", lambda: _FakeIMAP(raw))
    return adapter


def test_imap_extract_parts_surfaces_inline_without_losing_body() -> None:
    msg = email.message_from_bytes(_imap_inline_raw())
    text, html, atts = _imap_extract_parts(msg)

    # HTML body preserved.
    assert html is not None and "cid:img1" in html
    # One inline attachment with a synthesized name.
    assert len(atts) == 1
    att = atts[0]
    assert att["isInline"] is True
    assert att["contentType"] == "image/png"
    assert att["name"] == "img1"  # Content-ID local part
    assert att["id"].startswith("part-")
    assert att["size"] == len(_IMG_BYTES)


def test_imap_read_exposes_inline_and_keeps_html_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_imap(monkeypatch, _imap_inline_raw())

    out = adapter.read("INBOX/5")
    assert out["hasAttachments"] is True
    assert out["bodyContentType"] == "HTML"
    assert "cid:img1" in out["body"]
    assert len(out["attachments"]) == 1
    assert out["attachments"][0]["isInline"] is True
    assert out["attachments"][0]["name"] == "img1"


def test_imap_download_inline_returns_image_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_imap(monkeypatch, _imap_inline_raw())

    atts = adapter.list_attachments("INBOX/5")
    att_id = atts[0]["id"]
    name, data = adapter.download_attachment("INBOX/5", att_id)
    assert data == _IMG_BYTES
    assert name  # non-empty


def test_imap_text_html_inline_body_is_not_an_attachment() -> None:
    # GUARD: a text/html body part with Content-Disposition: inline must remain a
    # body candidate. If it were captured as an attachment, the html body branch
    # would never run and the message body would be LOST.
    root = MIMEMultipart("mixed")
    root["Subject"] = "Inline body"
    root["From"] = "sender@example.org"
    root["To"] = "me@example.com"
    html = MIMEText("<p>the real body</p>", "html")
    html.add_header("Content-Disposition", "inline")
    root.attach(html)

    msg = email.message_from_bytes(root.as_bytes())
    text, html_body, atts = _imap_extract_parts(msg)

    assert atts == []
    assert html_body is not None and "the real body" in html_body


def test_imap_text_plain_inline_body_is_not_an_attachment() -> None:
    # Same guard for a text/plain inline body part.
    root = MIMEMultipart("mixed")
    plain = MIMEText("plain real body", "plain")
    plain.add_header("Content-Disposition", "inline")
    root.attach(plain)

    msg = email.message_from_bytes(root.as_bytes())
    text, html_body, atts = _imap_extract_parts(msg)

    assert atts == []
    assert text is not None and "plain real body" in text


def _imap_text_file_attachment_raw(body_first: bool = False) -> bytes:
    """multipart/mixed: a text/plain FILE attachment (log.txt) + a text/plain body.

    ``body_first`` controls walk() ordering so both the attachment-before-body
    and body-before-attachment cases are exercised.
    """
    root = MIMEMultipart("mixed")
    root["Subject"] = "Log attached"
    root["From"] = "sender@example.org"
    root["To"] = "me@example.com"

    att = MIMEText("log line 1\nlog line 2\n", "plain")
    att.add_header("Content-Disposition", "attachment", filename="log.txt")
    body = MIMEText("the real plain body", "plain")

    if body_first:
        root.attach(body)
        root.attach(att)
    else:
        root.attach(att)
        root.attach(body)
    return root.as_bytes()


def test_imap_text_plain_file_attachment_before_body_preserves_body() -> None:
    # BLOCKER 1 guard: a genuine text/plain FILE attachment
    # (Content-Disposition: attachment; filename=...) placed BEFORE the real
    # text/plain body must be captured as an attachment AND must not consume the
    # body branch — the real body must survive.
    msg = email.message_from_bytes(_imap_text_file_attachment_raw(body_first=False))
    text, html, atts = _imap_extract_parts(msg)

    assert text is not None and "the real plain body" in text
    assert len(atts) == 1
    assert atts[0]["name"] == "log.txt"
    assert atts[0]["contentType"] == "text/plain"
    assert atts[0]["isInline"] is False


def test_imap_text_plain_file_attachment_after_body_preserves_body() -> None:
    # Body-first ordering variant: attachment surfaced, body preserved.
    msg = email.message_from_bytes(_imap_text_file_attachment_raw(body_first=True))
    text, html, atts = _imap_extract_parts(msg)

    assert text is not None and "the real plain body" in text
    assert len(atts) == 1
    assert atts[0]["name"] == "log.txt"
    assert atts[0]["contentType"] == "text/plain"


def test_imap_text_html_file_attachment_before_body_preserves_body() -> None:
    # text/html FILE attachment variant: report.html attachment before the real
    # text/html body; body must survive and the attachment must be surfaced.
    root = MIMEMultipart("mixed")
    root["Subject"] = "HTML attached"
    root["From"] = "sender@example.org"
    root["To"] = "me@example.com"
    att = MIMEText("<h1>report</h1>", "html")
    att.add_header("Content-Disposition", "attachment", filename="report.html")
    body = MIMEText("<p>the real html body</p>", "html")
    root.attach(att)
    root.attach(body)

    msg = email.message_from_bytes(root.as_bytes())
    text, html, atts = _imap_extract_parts(msg)

    assert html is not None and "the real html body" in html
    assert len(atts) == 1
    assert atts[0]["name"] == "report.html"
    assert atts[0]["contentType"] == "text/html"
    assert atts[0]["isInline"] is False


def test_imap_attachment_named_like_inline_is_not_inline() -> None:
    # MINOR 1 (token-aware isInline): a real attachment whose filename merely
    # CONTAINS the substring "inline" ("mainline-budget.pdf") must have
    # isInline == False (parse the disposition TYPE, not a substring match).
    root = MIMEMultipart("mixed")
    root["Subject"] = "Budget"
    body = MIMEText("<p>the real html body</p>", "html")
    root.attach(body)
    pdf = MIMEApplication(b"%PDF-1.4 fake", _subtype="pdf")
    pdf.add_header("Content-Disposition", "attachment", filename="mainline-budget.pdf")
    root.attach(pdf)

    msg = email.message_from_bytes(root.as_bytes())
    text, html, atts = _imap_extract_parts(msg)

    assert html is not None and "the real html body" in html
    assert len(atts) == 1
    assert atts[0]["name"] == "mainline-budget.pdf"
    assert atts[0]["isInline"] is False


def test_imap_download_inline_name_matches_list_and_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # MINOR 2 (download name parity): a filename-less cid inline image must
    # download under the SAME synthesized friendly name that list/read report,
    # not a divergent "attachment-{idx}".
    adapter = _make_imap(monkeypatch, _imap_inline_raw())

    atts = adapter.list_attachments("INBOX/5")
    listed_name = atts[0]["name"]
    att_id = atts[0]["id"]

    name, data = adapter.download_attachment("INBOX/5", att_id)
    assert data == _IMG_BYTES
    assert name == listed_name == "img1"
    assert not name.startswith("attachment-")
