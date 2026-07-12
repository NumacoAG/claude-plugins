"""The unsubscribe cascade.

Per tier-2 §4: one-click POST → mailto: → mark spam → block sender → delete,
stopping at the first step that succeeds. Each step's outcome is returned
to the caller so Claude can narrate which step worked.
"""

from __future__ import annotations

import re
from typing import Protocol

import httpx

HTTP_TIMEOUT = 10.0


class UnsubscribableAdapter(Protocol):
    """The adapter surface the cascade needs."""

    def read(self, message_id: str) -> dict: ...
    def send(
        self, to: list[str], subject: str, body_text: str | None,
        body_html: str | None, cc: list[str] | None, bcc: list[str] | None,
        attachments: list[str] | None,
    ) -> None: ...
    def mark_spam(self, message_id: str) -> dict: ...
    def block_sender(self, sender: str) -> dict: ...
    def delete(self, message_id: str) -> None: ...


_LU_TOKEN = re.compile(r"<([^>]+)>")


def parse_list_unsubscribe(header: str | None) -> tuple[list[str], list[str]]:
    """Parse a `List-Unsubscribe` header. Returns (urls, mailtos)."""
    if not header:
        return [], []
    urls: list[str] = []
    mailtos: list[str] = []
    for m in _LU_TOKEN.finditer(header):
        target = m.group(1).strip()
        if target.startswith("mailto:"):
            # strip optional ?subject= and other params
            mailtos.append(target[len("mailto:") :].split("?", 1)[0])
        elif target.startswith(("http://", "https://")):
            urls.append(target)
    return urls, mailtos


def cascade(adapter: UnsubscribableAdapter, message_id: str) -> dict:
    """Walk the unsubscribe cascade. Returns a dict describing the outcome."""
    msg = adapter.read(message_id)
    lu_header = msg.get("listUnsubscribe")
    lup_header = msg.get("listUnsubscribePost") or ""
    sender = msg.get("from")
    urls, mailtos = parse_list_unsubscribe(lu_header)
    has_one_click = "one-click" in lup_header.lower()

    attempts: list[dict] = []

    # Step 1: RFC 8058 one-click POST.
    if has_one_click:
        for url in urls:
            if not url.startswith("https://"):
                continue
            try:
                r = httpx.post(
                    url,
                    data={"List-Unsubscribe": "One-Click"},
                    timeout=HTTP_TIMEOUT,
                    follow_redirects=True,
                )
                attempts.append({"step": "one-click", "url": url, "status": r.status_code})
                if r.status_code < 400:
                    return {
                        "outcome": "unsubscribed",
                        "step": "one-click",
                        "url": url,
                        "status": r.status_code,
                        "attempts": attempts,
                    }
            except Exception as e:
                attempts.append({"step": "one-click", "url": url, "error": str(e)})

    # Step 2: mailto: — send an empty-body unsubscribe email via this account's SMTP.
    for mailto in mailtos:
        try:
            adapter.send(
                to=[mailto],
                subject="unsubscribe",
                body_text="",
                body_html=None,
                cc=None,
                bcc=None,
                attachments=None,
            )
            attempts.append({"step": "mailto", "address": mailto, "ok": True})
            return {
                "outcome": "unsubscribed",
                "step": "mailto",
                "address": mailto,
                "attempts": attempts,
            }
        except Exception as e:
            attempts.append({"step": "mailto", "address": mailto, "error": str(e)})

    # Step 3: mark as spam.
    spam_done = False
    spam_err: str | None = None
    try:
        adapter.mark_spam(message_id)
        spam_done = True
    except Exception as e:
        spam_err = str(e)
    attempts.append({"step": "mark_spam", "ok": spam_done, "error": spam_err})

    # Step 4: block sender (provider-specific filter/rule).
    block_done = False
    block_err: str | None = None
    if sender:
        try:
            adapter.block_sender(sender)
            block_done = True
        except NotImplementedError as e:
            block_err = f"not supported on this provider: {e}"
        except Exception as e:
            block_err = str(e)
    attempts.append({"step": "block_sender", "ok": block_done, "sender": sender, "error": block_err})

    if spam_done or block_done:
        return {
            "outcome": "spammed",
            "step": "spam+block",
            "sender": sender,
            "marked_spam": spam_done,
            "blocked_sender": block_done,
            "attempts": attempts,
        }

    # Step 5: last resort — delete.
    try:
        adapter.delete(message_id)
        return {
            "outcome": "deleted",
            "step": "delete",
            "sender": sender,
            "attempts": attempts,
        }
    except Exception as e:
        return {
            "outcome": "failed",
            "error": str(e),
            "lu_urls": urls,
            "lu_mailtos": mailtos,
            "attempts": attempts,
        }
