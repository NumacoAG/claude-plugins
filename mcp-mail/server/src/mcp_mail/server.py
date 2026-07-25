"""MCP stdio server for mcp-mail."""

from __future__ import annotations

import html
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import unsubscribe as unsub
from .adapters.gcalendar import GoogleCalendarAdapter
from .adapters.gdocs import GoogleDocsAdapter
from .adapters.gdrive import GoogleDriveAdapter
from .adapters.gmail import GmailAdapter
from .adapters.graph import GraphAdapter
from .adapters.gslides import GoogleSlidesAdapter
from .adapters.imap import IMAPAdapter
from .adapters.localfs import LocalFSAdapter
from .adapters.mscalendar import GraphCalendarAdapter
from .config import (
    Account,
    GmailAccount,
    LocalFSAccount,
    M365Account,
    get_account,
    has_capability,
    load_accounts,
)
from .core import audit
from .core.guard import is_outward_facing, require_auto_write

server: Server = Server("mcp-mail")


# ---- adapter abstraction ---------------------------------------------------


class MailAdapter(Protocol):
    """Cross-provider adapter contract. Both GraphAdapter and GmailAdapter
    implement this surface and return normalized dicts (see project shape
    in adapters/graph.py and adapters/gmail.py)."""

    def me(self) -> dict: ...
    def list_folders(self) -> list[dict]: ...
    def search(self, query: str, folder: str | None, limit: int) -> list[dict]: ...
    def read(self, message_id: str) -> dict: ...
    def list_attachments(self, message_id: str) -> list[dict]: ...
    def download_attachment(self, message_id: str, attachment_id: str) -> tuple[str, bytes]: ...
    def mark_read(self, message_id: str, read: bool) -> None: ...
    def move(self, message_id: str, target_folder: str) -> dict: ...
    def mark_spam(self, message_id: str) -> dict: ...
    def delete(self, message_id: str) -> None: ...
    def send(
        self,
        to: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
        cc: list[str] | None,
        bcc: list[str] | None,
        attachments: list[str] | None,
    ) -> None: ...
    def reply(
        self,
        message_id: str,
        body_text: str | None,
        body_html: str | None,
        reply_all: bool,
        attachments: list[str] | None,
        cc: list[str] | None,
        bcc: list[str] | None,
    ) -> None: ...
    def create_draft(
        self,
        to: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
        cc: list[str] | None,
        bcc: list[str] | None,
        attachments: list[str] | None,
    ) -> dict: ...
    def create_reply_draft(
        self,
        message_id: str,
        body_text: str | None,
        body_html: str | None,
        reply_all: bool,
        attachments: list[str] | None,
        cc: list[str] | None,
        bcc: list[str] | None,
    ) -> dict: ...


def _get_adapter(account_id: str) -> tuple[Account, MailAdapter]:
    acct = get_account(account_id)
    if acct.provider == "m365":
        return acct, GraphAdapter(acct)
    if acct.provider == "gmail":
        return acct, GmailAdapter(acct)
    if acct.provider == "imap":
        return acct, IMAPAdapter(acct)
    raise NotImplementedError(
        f"Provider {acct.provider!r} not yet implemented (account {acct.id!r})"
    )


def _ok(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


# ---- drive / calendar adapter dispatch -------------------------------------
#
# Drive tools route across three backends by provider: Gmail accounts -> Google
# Drive + Sheets (gdrive); M365 -> Graph files; localfs -> the sandboxed
# filesystem backend. Calendar tools route Gmail -> Google Calendar and M365 ->
# Graph calendar. Each dispatch first asserts the account declares the relevant
# capability so a mail-only account rejects drive_* / cal_* cleanly.


def _require_capability(account: Account, capability: str) -> None:
    if not has_capability(account, capability):
        raise ValueError(
            f"Account {account.id!r} does not declare the {capability!r} capability. "
            f"Add it to the account's `capabilities` in accounts.toml."
        )


def _get_drive_adapter(account_id: str) -> tuple[Account, Any]:
    """Return (account, drive-capable adapter) for a drive_* / sheet_* call."""
    acct = get_account(account_id)
    _require_capability(acct, "drive")
    if isinstance(acct, GmailAccount):
        return acct, GoogleDriveAdapter(acct)
    if isinstance(acct, M365Account):
        return acct, GraphAdapter(acct)
    if isinstance(acct, LocalFSAccount):
        return acct, LocalFSAdapter(acct)
    raise NotImplementedError(
        f"Provider {acct.provider!r} has no drive backend (account {acct.id!r})"
    )


def _get_calendar_adapter(account_id: str) -> tuple[Account, Any]:
    """Return (account, calendar adapter)."""
    acct = get_account(account_id)
    _require_capability(acct, "calendar")
    if isinstance(acct, GmailAccount):
        return acct, GoogleCalendarAdapter(acct)
    if isinstance(acct, M365Account):
        return acct, GraphCalendarAdapter(acct)
    raise NotImplementedError(
        f"Provider {acct.provider!r} has no calendar backend (account {acct.id!r})"
    )


def _get_docs_adapter(account_id: str) -> tuple[Account, GoogleDocsAdapter]:
    """Return (account, Docs adapter). Google-only; rides the drive capability.

    The Docs API shares the Drive OAuth scope, so a doc_* call requires the same
    ``drive`` capability the Drive / Sheets tools require.
    """
    acct = get_account(account_id)
    _require_capability(acct, "drive")
    if isinstance(acct, GmailAccount):
        return acct, GoogleDocsAdapter(acct)
    raise NotImplementedError(
        f"Docs editing is Google-only; account {acct.id!r} is {acct.provider!r}."
    )


def _get_slides_adapter(account_id: str) -> tuple[Account, GoogleSlidesAdapter]:
    """Return (account, Slides adapter). Google-only; rides the drive capability.

    The Slides API shares the Drive OAuth scope, so a slides_* call requires the
    same ``drive`` capability the Drive / Sheets / Docs tools require.
    """
    acct = get_account(account_id)
    _require_capability(acct, "drive")
    if isinstance(acct, GmailAccount):
        return acct, GoogleSlidesAdapter(acct)
    raise NotImplementedError(
        f"Slides editing is Google-only; account {acct.id!r} is {acct.provider!r}."
    )


def _is_graph(adapter: Any) -> bool:
    return isinstance(adapter, GraphAdapter)


def _drive_call(adapter: Any, base_name: str, graph_name: str, *args: Any) -> Any:
    """Call the right method on a drive adapter.

    The Graph adapter prefixes its file methods with ``drive_`` (so they sit
    beside its mail methods of the same verb, like ``move``); the Google and
    localfs adapters expose the bare verb. This bridges the two so the server
    body stays uniform.
    """
    method = graph_name if _is_graph(adapter) else base_name
    return getattr(adapter, method)(*args)


def _require_google_sheets(adapter: Any, tool: str) -> None:
    """Sheets tools are Google-only; reject Graph / localfs backends clearly."""
    if not isinstance(adapter, GoogleDriveAdapter):
        raise ValueError(
            f"{tool} is a Google Sheets operation; the account's drive backend is "
            f"{type(adapter).__name__}, which has no Sheets surface."
        )


def _require_google_drive_comments(adapter: Any, tool: str) -> None:
    """Comments are a Google Drive surface; reject Graph / localfs backends clearly."""
    if not isinstance(adapter, GoogleDriveAdapter):
        raise ValueError(
            f"{tool} reads Google Drive comments; the account's drive backend is "
            f"{type(adapter).__name__}, which has no comments surface."
        )


def _drive_list_backends() -> list[dict]:
    """Configured drive-capable accounts plus a cheap per-account auth probe."""
    out: list[dict] = []
    for acct in load_accounts():
        if not has_capability(acct, "drive"):
            continue
        entry: dict[str, Any] = {
            "id": acct.id,
            "provider": acct.provider,
            "capabilities": list(acct.capabilities),
            "auto_write": getattr(acct, "auto_write", False),
        }
        if isinstance(acct, GmailAccount):
            entry["backend"] = "google-drive"
            entry["auth"] = GoogleDriveAdapter(acct).auth_status()
        elif isinstance(acct, M365Account):
            entry["backend"] = "graph-files"
            entry["auth"] = GraphAdapter(acct).files_auth_status()
        elif isinstance(acct, LocalFSAccount):
            entry["backend"] = "localfs"
            roots = [str(r) for r in acct.roots]
            entry["roots"] = roots
            entry["auth"] = {
                "ok": any(r.expanduser().exists() for r in acct.roots),
                "rootsPresent": [str(r) for r in acct.roots if r.expanduser().exists()],
            }
        out.append(entry)
    return out


def _gate_refusal(tool: str) -> list[TextContent]:
    """The server-side outward-facing gate's refusal for an unconfirmed attendee write.

    Enforced in the server, independent of any Claude Code allowlist: an
    attendee-bearing calendar write sends invitations or cancellations (the same
    outward-facing shape as mail_send), so the server refuses to perform it until
    the caller re-invokes with confirmed=true after the user has approved. Solo
    events carry no attendees and never reach this path, so they do not prompt.
    """
    return _ok({
        "ok": False,
        "gated": True,
        "reason": (
            f"{tool} carries attendees, so it sends invitations or a cancellation "
            f"to guests (outward-facing, like mail_send). Surface the full event to "
            f"the user for approval, then re-invoke {tool} with confirmed=true."
        ),
    })


def _comment_gate_refusal(tool: str) -> list[TextContent]:
    """The server-side outward-facing gate's refusal for an unconfirmed comment write.

    A new comment (``drive_comment_add``) or a reply (``drive_comment_reply``) is
    visible to everyone with access to the file and can notify them, so it is
    outward-facing exactly like mail_send. The server refuses the write until the
    caller re-invokes with confirmed=true after the user has approved the text.
    Resolve / reopen are state toggles (no new outward content) and do not reach
    this path.
    """
    return _ok({
        "ok": False,
        "gated": True,
        "reason": (
            f"{tool} posts a comment others with file access can see (outward-facing, "
            f"like mail_send). Surface the exact comment text to the user for approval, "
            f"then re-invoke {tool} with confirmed=true."
        ),
    })


def _apply_signature(
    acct: Account,
    *,
    body_text: str | None,
    body_html: str | None,
    attachments: list[str] | None,
    is_reply: bool,
    append_signature: bool | None,
) -> tuple[str | None, list[str] | None]:
    """Append the account's configured signature to an outgoing HTML body and
    attach its inline images. Returns a possibly-changed (body_html, attachments).

    Only accounts with a `signature_html` in accounts.toml are affected; every
    other account passes through untouched. Fail-open: any problem reading the
    snippet leaves the message as-is rather than blocking the send. A
    `data-mcpmail-sig` marker makes the append idempotent, so a caller that has
    already embedded the signature is never doubled. `append_signature=False`
    suppresses it for a single call (automated notices, threads where it stacks).
    """
    sig = getattr(acct, "signature", None)
    if sig is None or append_signature is False:
        return body_html, attachments
    if is_reply and not sig.on_reply:
        return body_html, attachments
    try:
        raw = sig.html_path.read_text()
    except OSError:
        return body_html, attachments
    sig_html = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    if not sig_html:
        return body_html, attachments
    if body_html and "data-mcpmail-sig" in body_html:
        return body_html, attachments  # already signed
    if body_html is not None:
        new_html = body_html + "\n" + sig_html
    elif body_text is not None:
        esc = html.escape(body_text).replace("\n", "<br>")
        new_html = (
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;'
            'color:#1a1a1a">' + esc + "</div>\n" + sig_html
        )
    else:
        new_html = sig_html
    merged = list(attachments or [])
    for img in sig.inline_images:
        s = str(img)
        if s not in merged:
            merged.append(s)
    return new_html, (merged or None)


# ---- tool registration -----------------------------------------------------


@server.list_tools()
async def list_tools() -> list[Tool]:
    account_arg = {
        "account": {
            "type": "string",
            "description": "Account id from accounts.toml (e.g. 'work-m365', 'personal-gmail').",
        }
    }
    return [
        Tool(
            name="mail_list_accounts",
            description="Return all configured email accounts. Config-only; no network, no auth.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="mail_whoami",
            description="Profile of the authenticated user for the given account. Useful sanity check for auth.",
            inputSchema={
                "type": "object",
                "properties": account_arg,
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_list_folders",
            description="List mail folders / labels for the given account. First call after install may open a browser for sign-in.",
            inputSchema={
                "type": "object",
                "properties": account_arg,
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_search",
            description=(
                "Search messages in the given account. With `query`, uses provider full-text search "
                "(KQL on M365; Gmail search syntax on Gmail). Without `query`, lists newest-first. "
                "Returns metadata only — call `mail_read` for full body. Optional `folder` scopes the "
                "search (well-known name like 'inbox', 'sent', 'spam', 'archive', or a provider-native id)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "query": {"type": "string", "description": "Provider full-text query."},
                    "folder": {"type": "string", "description": "Well-known name or provider folder/label id."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_read",
            description="Read one message in full: headers, body (HTML preferred), attachment metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_mark_read",
            description="Mark a message as read (default) or unread.",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "read": {"type": "boolean", "description": "Default true."},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_move",
            description=(
                "Move a message. `target_folder` accepts well-known names "
                "('inbox', 'archive', 'sent', 'drafts', 'trash', 'spam', 'starred', 'important') "
                "or provider-native folder/label ids."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "target_folder": {"type": "string"},
                },
                "required": ["account", "message_id", "target_folder"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_mark_spam",
            description="Move a message to the provider's spam/junk folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_delete",
            description="Soft-delete: move to Trash / Deleted Items. Executes immediately (not gated).",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_send",
            description=(
                "Send a new message. Default body format is HTML with plain-text fallback. "
                "Pass `body_html` for rich, `body_text` for plain-only. Optional `attachments` "
                "is a list of local file paths. If the account has a configured signature it is "
                "appended automatically (with its inline logo); pass append_signature=false to "
                "suppress it. HARD-GATED: a PreToolUse hook BLOCKS this call unless the user has "
                "just selected 'Send email' in an AskUserQuestion box offering exactly three "
                "options — 'Send email' / 'Save as draft' / 'Do not send'. You MUST present that "
                "box as the final step immediately before calling mail_send. For the 'Save as "
                "draft' choice call mail_draft instead (never mail_send); for 'Do not send', "
                "stop. Do NOT add to the allowlist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "to": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Local file paths to attach.",
                    },
                    "append_signature": {
                        "type": "boolean",
                        "description": "Override the account's automatic signature for this send (false to omit it).",
                    },
                },
                "required": ["account", "to", "subject"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_reply",
            description=(
                "Reply to a message; the provider handles threading. Pass `reply_all` to copy the "
                "original message's recipients (its To + CC) onto the reply. Pass `cc` and/or `bcc` "
                "to ADD NEW recipients (e.g. loop a colleague into CC) on top of that, distinct from "
                "`reply_all`: the extra addresses are deduped and never include yourself or the "
                "original sender. Optional `attachments` is a list of local file paths. If the "
                "account has a configured signature (with signature_on_reply) it is appended "
                "automatically; pass append_signature=false to suppress it. HARD-GATED exactly like "
                "mail_send: a PreToolUse hook BLOCKS this call unless the user just selected 'Send "
                "email' in an AskUserQuestion box offering 'Send email' / 'Save as draft' / 'Do not "
                "send'. Present that box as the final step before replying. For 'Save as draft' call "
                "mail_reply_draft instead; for 'Do not send', stop. Do NOT add to the allowlist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "reply_all": {"type": "boolean", "description": "Default false."},
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New CC recipients to ADD to the reply (distinct from reply_all).",
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New BCC recipients to ADD to the reply (distinct from reply_all).",
                    },
                    "attachments": {"type": "array", "items": {"type": "string"}},
                    "append_signature": {
                        "type": "boolean",
                        "description": "Override the account's automatic signature for this reply (false to omit it).",
                    },
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_draft",
            description=(
                "Create a NEW-message draft in the account's Drafts folder WITHOUT sending it. "
                "This is the destination for the user's 'Save as draft' choice in the send-"
                "confirmation box: when the user picks 'Save as draft', call mail_draft (not "
                "mail_send). Same fields and behaviour as mail_send (HTML-first body, cc/bcc, "
                "`attachments` local file paths, automatic signature with inline logo unless "
                "append_signature=false), except the message is saved as a draft and never "
                "delivered. NOT gated by the send hook, so it needs no confirmation box. Returns "
                "the draft id (and a webLink where the provider exposes one)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "to": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Local file paths to attach.",
                    },
                    "append_signature": {
                        "type": "boolean",
                        "description": "Override the account's automatic signature for this draft (false to omit it).",
                    },
                },
                "required": ["account", "to", "subject"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_reply_draft",
            description=(
                "Create a threaded reply DRAFT in the account's Drafts folder WITHOUT sending it. "
                "This is the destination for the user's 'Save as draft' choice when replying: when "
                "the user picks 'Save as draft', call mail_reply_draft (not mail_reply). Same "
                "fields and behaviour as mail_reply (`reply_all`, extra `cc`/`bcc`, `attachments`, "
                "automatic reply signature unless append_signature=false, threading preserved), "
                "except the reply is saved as a draft and never delivered. NOT gated by the send "
                "hook. Returns the draft id (and a webLink where the provider exposes one)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "reply_all": {"type": "boolean", "description": "Default false."},
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New CC recipients to ADD to the reply draft (distinct from reply_all).",
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New BCC recipients to ADD to the reply draft (distinct from reply_all).",
                    },
                    "attachments": {"type": "array", "items": {"type": "string"}},
                    "append_signature": {
                        "type": "boolean",
                        "description": "Override the account's automatic signature for this reply draft (false to omit it).",
                    },
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_download_attachments",
            description=(
                "Download file attachments to a local directory. By default only "
                "non-inline attachments are written; pass include_inline=true to also "
                "download inline images (those referenced by cid: in the HTML body, e.g. "
                "screenshots pasted into the message), so you can open and view them. "
                "Default target_dir: $TMPDIR/mcp-mail/. Pass target_dir explicitly to keep the files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "target_dir": {"type": "string"},
                    "include_inline": {
                        "type": "boolean",
                        "description": "Also download inline images referenced by cid: in the body (default false).",
                    },
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_unsubscribe",
            description=(
                "Walk the unsubscribe cascade for a message: "
                "List-Unsubscribe one-click POST → mailto: → mark spam → block sender → delete. "
                "Stops at the first step that succeeds. Returns a dict describing the outcome "
                "and a full attempts log."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_block_sender",
            description=(
                "Block a sender on the given account via a provider-native rule/filter: "
                "Microsoft Graph creates an inbox rule, Gmail creates a settings filter, "
                "IMAP returns 'not supported' (no standard API). The rule moves future "
                "messages from this sender to Junk/Trash."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "sender_address": {"type": "string"},
                },
                "required": ["account", "sender_address"],
                "additionalProperties": False,
            },
        ),
        # ---- drive (generic, all backends) ---------------------------------
        Tool(
            name="drive_list_backends",
            description=(
                "List the drive-capable accounts and their auth status. Config-only "
                "plus a cheap per-account auth probe. Shows which backends (Google "
                "Drive, Graph SharePoint/OneDrive, localfs iCloud/OneDrive) are ready "
                "and which need a re-consent."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="drive_list",
            description=(
                "List a folder. `path` is a Drive folder id (Google), a driveItem ref "
                "(Graph), or a sandboxed absolute path (localfs). Omit `path` for the "
                "backend's root."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "path": {"type": "string"},
                    "page": {"type": "string", "description": "Pagination token."},
                },
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_search",
            description="Search files by name (and content where the backend supports it).",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["account", "query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_read",
            description=(
                "Read a file's content. Binary files are written to a temp dir (or "
                "`target_dir`) and the path returned. Google Docs/Slides are exported "
                "(markdown/text). A Google Sheet routes you to sheet_* for cell access "
                "and returns a read-only CSV snapshot path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id or sandboxed path."},
                    "target_dir": {"type": "string"},
                },
                "required": ["account", "ref"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_get_metadata",
            description="File metadata: size, mime, parents, modified time, sharing.",
            inputSchema={
                "type": "object",
                "properties": {**account_arg, "ref": {"type": "string"}},
                "required": ["account", "ref"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_comments",
            description="List comments and replies on a Drive file (Google Drive only; read-only).",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id."},
                },
                "required": ["account", "ref"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_comment_add",
            description=(
                "Add a new top-level comment to a Drive file (Google Drive only; "
                "works on Docs, Sheets, and Slides). OUTWARD-FACING: the comment is "
                "visible to everyone with access and can notify them, so the SERVER "
                "refuses the write unless `confirmed=true`. Surface the comment text "
                "to the user first, then re-invoke with confirmed=true. Honours the "
                "per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id."},
                    "content": {"type": "string", "description": "Comment text."},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true after the user approves the comment.",
                    },
                },
                "required": ["account", "ref", "content"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_comment_reply",
            description=(
                "Reply to an existing comment on a Drive file (Google Drive only). "
                "OUTWARD-FACING: the reply is visible to the thread's participants and "
                "can notify them, so the SERVER refuses the write unless "
                "`confirmed=true`. Surface the reply text to the user first, then "
                "re-invoke with confirmed=true. Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id."},
                    "comment_id": {"type": "string", "description": "Id of the comment to reply to."},
                    "content": {"type": "string", "description": "Reply text."},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true after the user approves the reply.",
                    },
                },
                "required": ["account", "ref", "comment_id", "content"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_comment_resolve",
            description=(
                "Mark a comment resolved on a Drive file (Google Drive only). Done by "
                "posting an action reply; optional `content` adds a closing note. A "
                "state toggle, not new outward content, so it is gated by the "
                "per-account auto_write guard only (no separate confirm gate)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id."},
                    "comment_id": {"type": "string", "description": "Id of the comment to resolve."},
                    "content": {"type": "string", "description": "Optional note added with the resolve."},
                },
                "required": ["account", "ref", "comment_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_comment_reopen",
            description=(
                "Reopen a resolved comment on a Drive file (Google Drive only). Done by "
                "posting an action reply; optional `content` adds a note. A state "
                "toggle, gated by the per-account auto_write guard only (no separate "
                "confirm gate)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string", "description": "File id."},
                    "comment_id": {"type": "string", "description": "Id of the comment to reopen."},
                    "content": {"type": "string", "description": "Optional note added with the reopen."},
                },
                "required": ["account", "ref", "comment_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_create",
            description=(
                "Create a file or folder. Pass `mime='application/vnd.google-apps.folder' "
                "for a folder, a Google native mime for an empty Doc/Sheet (populate a "
                "Sheet via sheet_*), or text `content` for a regular file. Honours the "
                "per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "name": {"type": "string"},
                    "parent": {"type": "string"},
                    "content": {"type": "string"},
                    "mime": {"type": "string"},
                },
                "required": ["account", "name"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_update",
            description=(
                "Replace a file's bytes/text. Refuses Google native types (use sheet_* "
                "for a Sheet; Docs/Slides are read-only in v0.1). States what it "
                "replaces; honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["account", "ref", "content"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_move",
            description=(
                "Move and/or rename. `dest` is 'parent' or 'parent/new name'. Honours "
                "the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string"},
                    "dest": {"type": "string"},
                },
                "required": ["account", "ref", "dest"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_copy",
            description="Copy a file. `dest` is 'parent' or 'parent/new name'. Honours auto_write.",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string"},
                    "dest": {"type": "string"},
                },
                "required": ["account", "ref", "dest"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_delete",
            description=(
                "Send a file to trash / recycle bin / macOS Trash (reversible; never a "
                "hard delete). Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {**account_arg, "ref": {"type": "string"}},
                "required": ["account", "ref"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="drive_share",
            description=(
                "Set a sharing permission (Google + Graph only; localfs returns "
                "not-supported). OUTWARD-FACING: always confirmation-gated by the "
                "per-call prompt regardless of auto_write; do NOT add to the allowlist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "ref": {"type": "string"},
                    "principal": {"type": "string", "description": "Email, or 'anyone'."},
                    "role": {"type": "string", "description": "e.g. 'reader' / 'writer'."},
                },
                "required": ["account", "ref", "principal", "role"],
                "additionalProperties": False,
            },
        ),
        # ---- sheets (Google) -----------------------------------------------
        Tool(
            name="sheet_get",
            description="Spreadsheet structure: tab list, dimensions, named ranges.",
            inputSchema={
                "type": "object",
                "properties": {**account_arg, "spreadsheet_id": {"type": "string"}},
                "required": ["account", "spreadsheet_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="sheet_read",
            description="Read an A1 range, e.g. 'Sheet1!A1:D20'. Returns values.",
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "spreadsheet_id": {"type": "string"},
                    "range": {"type": "string"},
                },
                "required": ["account", "spreadsheet_id", "range"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="sheet_write",
            description=(
                "Overwrite an A1 range with `values` (a list of rows). Refuses to "
                "silently clobber a non-empty range unless `overwrite=true`. Honours "
                "the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "spreadsheet_id": {"type": "string"},
                    "range": {"type": "string"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "A list of rows; each row a list of cell values.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Required true to overwrite a non-empty range.",
                    },
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="sheet_append",
            description=(
                "Append rows below the last row of an A1 range. Honours the per-account "
                "auto_write guard. (This is the gym-log fix.)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "spreadsheet_id": {"type": "string"},
                    "range": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "array", "items": {}}},
                },
                "required": ["account", "spreadsheet_id", "range", "values"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="sheet_batch_update",
            description=(
                "Structural edits (insert rows, format, add tabs) via the Sheets "
                "batchUpdate `requests` array. Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "spreadsheet_id": {"type": "string"},
                    "requests": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["account", "spreadsheet_id", "requests"],
                "additionalProperties": False,
            },
        ),
        # ---- docs (Google) -------------------------------------------------
        Tool(
            name="doc_get",
            description=(
                "Read a Google Doc (Google only). Returns the documentId, title, and a "
                "plain-text rendering of the body. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                },
                "required": ["account", "document_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_insert_text",
            description=(
                "Insert text into a Google Doc at `index` (default 1, the start of the "
                "body; index 0 is not insertable). Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "text": {"type": "string"},
                    "index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Insertion point; defaults to 1 (start of body).",
                    },
                },
                "required": ["account", "document_id", "text"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_append",
            description=(
                "Append text to the end of a Google Doc's body (just before the final "
                "newline). Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["account", "document_id", "text"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_replace_text",
            description=(
                "Replace every occurrence of `find` with `replace` across a Google Doc. "
                "Pass `match_case` for a case-sensitive match. Returns occurrencesChanged; "
                "honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                    "match_case": {"type": "boolean", "description": "Default false."},
                },
                "required": ["account", "document_id", "find", "replace"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_get_structured",
            description=(
                "Read the full Google Docs `documents.get` JSON: the structural "
                "element tree with paragraphs, tables, table rows/cells and their "
                "start/end indices, and styles. This is what index-based edits are "
                "computed against (use it before doc_batch_update). Pass an optional "
                "`fields` mask (Docs partial-response syntax, e.g. "
                "`body.content(startIndex,endIndex,table)`) to bound large payloads, "
                "and `include_tabs` for multi-tab docs. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "fields": {
                        "type": "string",
                        "description": "Docs partial-response field mask (URL query).",
                    },
                    "include_tabs": {
                        "type": "boolean",
                        "description": "Set includeTabsContent=true for multi-tab docs.",
                    },
                },
                "required": ["account", "document_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_batch_update",
            description=(
                "Apply raw Google Docs `documents.batchUpdate` requests — the "
                "full-power tool. `requests` is the raw list of Docs API Request "
                "objects, so anything the API can do is reachable: insert/style "
                "tables, cells, borders, column widths, merges, text styling, "
                "images, bullets, page/section breaks, named ranges, etc. Requests "
                "apply atomically and sequentially; order multiple index-based edits "
                "highest-index-first. Optional `write_control` "
                "({requiredRevisionId} or {targetRevisionId}) for optimistic "
                "concurrency. Read the doc first with doc_get_structured to get "
                "indices. Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "requests": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Raw Docs API Request objects, applied in order.",
                    },
                    "write_control": {
                        "type": "object",
                        "description": "Optional {requiredRevisionId} or {targetRevisionId}.",
                    },
                },
                "required": ["account", "document_id", "requests"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_create",
            description=(
                "Create a new Google Doc with the given `title` (in the account's My "
                "Drive). The Docs API ignores any body at creation, so this only sets "
                "the title; add content with doc_batch_update / doc_create_table / "
                "doc_edit_cell / doc_format_matches. Returns documentId. Honours the "
                "per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "title": {"type": "string"},
                },
                "required": ["account", "title"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_create_table",
            description=(
                "Insert a `rows`x`columns` table into a Google Doc and optionally "
                "fill it from `data` (a row-major 2D array of strings; empty/omitted "
                "cells are skipped). Handles the Docs index math internally (insert, "
                "re-fetch, fill highest-index-first) so cells never corrupt. Appends "
                "at the end of the body by default; pass `index` to insert at a "
                "specific body index. Returns the table's start index. Honours the "
                "per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "rows": {"type": "integer", "minimum": 1},
                    "columns": {"type": "integer", "minimum": 1},
                    "data": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Row-major cell text; empty cells skipped.",
                    },
                    "index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Body index to insert at; omit to append at end.",
                    },
                    "tab_id": {"type": "string", "description": "Target tab (multi-tab docs)."},
                },
                "required": ["account", "document_id", "rows", "columns"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_edit_cell",
            description=(
                "Set the text of a single table cell by (row, col) grid coordinates, "
                "clearing any existing cell content first. `table_ordinal` selects "
                "which table in the doc (0-based, document order; default 0). Handles "
                "cell index lookup and the clear-then-insert sequence internally. "
                "Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "row": {"type": "integer", "minimum": 0},
                    "col": {"type": "integer", "minimum": 0},
                    "text": {"type": "string"},
                    "table_ordinal": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Which table (0-based, doc order). Default 0.",
                    },
                    "tab_id": {"type": "string", "description": "Target tab (multi-tab docs)."},
                },
                "required": ["account", "document_id", "row", "col", "text"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="doc_format_matches",
            description=(
                "Apply text styling to every (or the first) occurrence of a substring "
                "in a Google Doc. `text_style` is a Docs API TextStyle object (e.g. "
                '{"bold": true, "foregroundColor": {"color": {"rgbColor": {"red": '
                '1.0}}}}); the update field-mask is derived from its keys unless you '
                "pass `fields` explicitly (pass `fields` with an empty/partial "
                "`text_style` to RESET properties). `match_case` (default false) and "
                "`all_occurrences` (default true) control matching. Returns the count "
                "styled. Honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "document_id": {"type": "string"},
                    "find": {"type": "string"},
                    "text_style": {"type": "object"},
                    "fields": {
                        "type": "string",
                        "description": "Override the update field-mask (else derived from text_style keys).",
                    },
                    "match_case": {"type": "boolean", "description": "Default false."},
                    "all_occurrences": {"type": "boolean", "description": "Default true."},
                    "tab_id": {"type": "string", "description": "Target tab (multi-tab docs)."},
                },
                "required": ["account", "document_id", "find", "text_style"],
                "additionalProperties": False,
            },
        ),
        # ---- slides (Google) -----------------------------------------------
        Tool(
            name="slides_get",
            description=(
                "Read a Google Slides presentation (Google only). Returns the "
                "presentationId, title, slideCount, and per-slide text with the "
                "objectId of each text box (use it with slides_insert_text). Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "presentation_id": {"type": "string"},
                },
                "required": ["account", "presentation_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="slides_replace_text",
            description=(
                "Replace every occurrence of `find` with `replace` across a Google "
                "Slides deck. Pass `match_case` for a case-sensitive match. Returns "
                "occurrencesChanged; honours the per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "presentation_id": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                    "match_case": {"type": "boolean", "description": "Default false."},
                },
                "required": ["account", "presentation_id", "find", "replace"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="slides_insert_text",
            description=(
                "Insert text into a Google Slides shape (`object_id`, from slides_get) "
                "at `index` (default 0, the start of the shape's text). Honours the "
                "per-account auto_write guard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "presentation_id": {"type": "string"},
                    "object_id": {"type": "string"},
                    "text": {"type": "string"},
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Insertion point within the shape; defaults to 0.",
                    },
                },
                "required": ["account", "presentation_id", "object_id", "text"],
                "additionalProperties": False,
            },
        ),
        # ---- calendar (Google) ---------------------------------------------
        Tool(
            name="cal_list_calendars",
            description="List the calendars the account can see.",
            inputSchema={
                "type": "object",
                "properties": {**account_arg},
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="cal_list_events",
            description=(
                "List/search events between time_min and time_max (RFC3339). Optional "
                "`query` full-text filters; `calendar_id` defaults to 'primary'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "calendar_id": {"type": "string"},
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                },
                "required": ["account"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="cal_create_event",
            description=(
                "Create an event. `start`/`end` are RFC3339 datetimes or all-day dates. "
                "When `attendees` (a list of emails) is present the event sends "
                "invitations and is OUTWARD-FACING: the SERVER refuses the write unless "
                "`confirmed=true`, so surface the event to the user first, then re-invoke "
                "with confirmed=true. Solo events (no attendees) proceed with no friction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "calendar_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true after the user approves an attendee-bearing event.",
                    },
                },
                "required": ["account", "summary", "start", "end"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="cal_update_event",
            description=(
                "Update an event by id. OUTWARD-FACING when the stored event OR the patch "
                "carries attendees, since guests are notified of the change: the SERVER "
                "refuses the write unless `confirmed=true`. Re-invoke with confirmed=true "
                "after the user approves. Solo events proceed with no friction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true after the user approves an attendee-bearing change.",
                    },
                },
                "required": ["account", "event_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="cal_delete_event",
            description=(
                "Delete an event by id. OUTWARD-FACING when the stored event has "
                "attendees, since a cancellation is sent: the SERVER refuses the delete "
                "unless `confirmed=true`. Re-invoke with confirmed=true after the user "
                "approves. Solo events proceed with no friction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true after the user approves cancelling an attendee event.",
                    },
                },
                "required": ["account", "event_id"],
                "additionalProperties": False,
            },
        ),
    ]


# ---- tool dispatch ---------------------------------------------------------


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "mail_list_accounts":
        return _ok([
            {"id": a.id, "provider": a.provider, "address": a.address}
            for a in load_accounts()
        ])

    if name == "mail_whoami":
        _, adapter = _get_adapter(arguments["account"])
        return _ok(adapter.me())

    if name == "mail_list_folders":
        _, adapter = _get_adapter(arguments["account"])
        return _ok(adapter.list_folders())

    if name == "mail_search":
        _, adapter = _get_adapter(arguments["account"])
        return _ok(adapter.search(
            query=arguments.get("query", ""),
            folder=arguments.get("folder"),
            limit=int(arguments.get("limit", 25)),
        ))

    if name == "mail_read":
        _, adapter = _get_adapter(arguments["account"])
        return _ok(adapter.read(arguments["message_id"]))

    if name == "mail_mark_read":
        _, adapter = _get_adapter(arguments["account"])
        adapter.mark_read(arguments["message_id"], read=bool(arguments.get("read", True)))
        return _ok({"ok": True, "message_id": arguments["message_id"]})

    if name == "mail_move":
        _, adapter = _get_adapter(arguments["account"])
        result = adapter.move(arguments["message_id"], arguments["target_folder"])
        return _ok({"ok": True, "new_message_id": result.get("id")})

    if name == "mail_mark_spam":
        _, adapter = _get_adapter(arguments["account"])
        result = adapter.mark_spam(arguments["message_id"])
        return _ok({"ok": True, "new_message_id": result.get("id")})

    if name == "mail_delete":
        _, adapter = _get_adapter(arguments["account"])
        adapter.delete(arguments["message_id"])
        return _ok({"ok": True, "message_id": arguments["message_id"]})

    if name == "mail_send":
        acct, adapter = _get_adapter(arguments["account"])
        body_html, attachments = _apply_signature(
            acct,
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            attachments=arguments.get("attachments"),
            is_reply=False,
            append_signature=arguments.get("append_signature"),
        )
        adapter.send(
            to=arguments["to"],
            subject=arguments["subject"],
            body_text=arguments.get("body_text"),
            body_html=body_html,
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
            attachments=attachments,
        )
        return _ok({"ok": True, "sent_to": arguments["to"]})

    if name == "mail_reply":
        acct, adapter = _get_adapter(arguments["account"])
        body_html, attachments = _apply_signature(
            acct,
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            attachments=arguments.get("attachments"),
            is_reply=True,
            append_signature=arguments.get("append_signature"),
        )
        adapter.reply(
            message_id=arguments["message_id"],
            body_text=arguments.get("body_text"),
            body_html=body_html,
            reply_all=bool(arguments.get("reply_all", False)),
            attachments=attachments,
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
        )
        return _ok({"ok": True, "replied_to": arguments["message_id"]})

    if name == "mail_draft":
        # Native draft creation: the "Save as draft" destination. Applies the
        # account signature exactly like mail_send, but writes to Drafts and
        # never sends. Not gated by the send hook.
        acct, adapter = _get_adapter(arguments["account"])
        body_html, attachments = _apply_signature(
            acct,
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            attachments=arguments.get("attachments"),
            is_reply=False,
            append_signature=arguments.get("append_signature"),
        )
        result = adapter.create_draft(
            to=arguments["to"],
            subject=arguments["subject"],
            body_text=arguments.get("body_text"),
            body_html=body_html,
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
            attachments=attachments,
        )
        return _ok({"ok": True, "draft": result})

    if name == "mail_reply_draft":
        # Native reply-draft creation: the "Save as draft" destination for a
        # reply. Applies the reply signature (is_reply=True) like mail_reply, but
        # writes to Drafts and never sends. Not gated by the send hook.
        acct, adapter = _get_adapter(arguments["account"])
        body_html, attachments = _apply_signature(
            acct,
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            attachments=arguments.get("attachments"),
            is_reply=True,
            append_signature=arguments.get("append_signature"),
        )
        result = adapter.create_reply_draft(
            message_id=arguments["message_id"],
            body_text=arguments.get("body_text"),
            body_html=body_html,
            reply_all=bool(arguments.get("reply_all", False)),
            attachments=attachments,
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
        )
        return _ok({"ok": True, "draft": result})

    if name == "mail_unsubscribe":
        _, adapter = _get_adapter(arguments["account"])
        return _ok(unsub.cascade(adapter, arguments["message_id"]))

    if name == "mail_block_sender":
        _, adapter = _get_adapter(arguments["account"])
        try:
            result = adapter.block_sender(arguments["sender_address"])
            return _ok({"ok": True, "sender": arguments["sender_address"], "rule": result})
        except NotImplementedError as e:
            return _ok({"ok": False, "reason": str(e)})

    if name == "mail_download_attachments":
        _, adapter = _get_adapter(arguments["account"])
        msg_id = arguments["message_id"]
        default_dir = Path(tempfile.gettempdir()) / "mcp-mail"
        target = Path(arguments.get("target_dir") or default_dir).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        include_inline = bool(arguments.get("include_inline", False))
        written: list[str] = []
        skipped: list[dict] = []
        for meta in adapter.list_attachments(msg_id):
            if meta.get("isInline") and not include_inline:
                skipped.append({"name": meta.get("name"), "reason": "inline"})
                continue
            try:
                fname, data = adapter.download_attachment(msg_id, meta["id"])
            except NotImplementedError as e:
                skipped.append({"name": meta.get("name"), "reason": str(e)})
                continue
            out_path = target / fname
            n = 1
            while out_path.exists():
                stem, _, suf = fname.rpartition(".")
                out_path = target / (f"{stem}_{n}.{suf}" if stem else f"{fname}_{n}")
                n += 1
            out_path.write_bytes(data)
            written.append(str(out_path))
        return _ok({"directory": str(target), "written": written, "skipped": skipped})

    # ---- drive (generic, all backends) ---------------------------------

    if name == "drive_list_backends":
        return _ok(_drive_list_backends())

    if name == "drive_list":
        _, adapter = _get_drive_adapter(arguments["account"])
        return _ok(_drive_call(
            adapter, "list", "drive_list",
            arguments.get("path"), arguments.get("page"),
        ))

    if name == "drive_search":
        _, adapter = _get_drive_adapter(arguments["account"])
        return _ok(_drive_call(
            adapter, "search", "drive_search",
            arguments["query"], int(arguments.get("limit", 25)),
        ))

    if name == "drive_read":
        _, adapter = _get_drive_adapter(arguments["account"])
        return _ok(_drive_call(
            adapter, "read", "drive_read",
            arguments["ref"], arguments.get("target_dir"),
        ))

    if name == "drive_get_metadata":
        _, adapter = _get_drive_adapter(arguments["account"])
        return _ok(_drive_call(
            adapter, "get_metadata", "drive_get_metadata", arguments["ref"],
        ))

    if name == "drive_comments":
        _, adapter = _get_drive_adapter(arguments["account"])
        _require_google_drive_comments(adapter, "drive_comments")
        return _ok(adapter.list_comments(arguments["ref"]))

    if name == "drive_comment_add":
        # Outward-facing: a new comment is visible to everyone with file access,
        # so the server refuses the write until the caller confirms (like the
        # attendee gate). Auto_write still applies on top.
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_drive_comments(adapter, "drive_comment_add")
        require_auto_write(acct, "drive_comment_add")
        if not bool(arguments.get("confirmed", False)):
            return _comment_gate_refusal("drive_comment_add")
        result = adapter.add_comment(arguments["ref"], arguments["content"])
        audit.record(
            "drive_comment_add", acct.id, arguments["ref"],
            detail={"commentId": result.get("id")},
        )
        return _ok(result)

    if name == "drive_comment_reply":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_drive_comments(adapter, "drive_comment_reply")
        require_auto_write(acct, "drive_comment_reply")
        if not bool(arguments.get("confirmed", False)):
            return _comment_gate_refusal("drive_comment_reply")
        result = adapter.reply_comment(
            arguments["ref"], arguments["comment_id"], arguments["content"],
        )
        audit.record(
            "drive_comment_reply", acct.id, arguments["ref"],
            detail={"commentId": arguments["comment_id"], "replyId": result.get("id")},
        )
        return _ok(result)

    if name == "drive_comment_resolve":
        # State toggle: gated by auto_write only, no separate confirm gate.
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_drive_comments(adapter, "drive_comment_resolve")
        require_auto_write(acct, "drive_comment_resolve")
        result = adapter.resolve_comment(
            arguments["ref"], arguments["comment_id"], arguments.get("content"),
        )
        audit.record(
            "drive_comment_resolve", acct.id, arguments["ref"],
            detail={"commentId": arguments["comment_id"]},
        )
        return _ok(result)

    if name == "drive_comment_reopen":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_drive_comments(adapter, "drive_comment_reopen")
        require_auto_write(acct, "drive_comment_reopen")
        result = adapter.reopen_comment(
            arguments["ref"], arguments["comment_id"], arguments.get("content"),
        )
        audit.record(
            "drive_comment_reopen", acct.id, arguments["ref"],
            detail={"commentId": arguments["comment_id"]},
        )
        return _ok(result)

    if name == "drive_create":
        acct, adapter = _get_drive_adapter(arguments["account"])
        require_auto_write(acct, "drive_create")
        result = _drive_call(
            adapter, "create", "drive_create",
            arguments["name"], arguments.get("parent"),
            arguments.get("content"), arguments.get("mime"),
        )
        audit.record(
            "drive_create", acct.id, result.get("id") or arguments["name"],
            detail={"parent": arguments.get("parent"), "mime": arguments.get("mime")},
        )
        return _ok(result)

    if name == "drive_update":
        acct, adapter = _get_drive_adapter(arguments["account"])
        require_auto_write(acct, "drive_update")
        result = _drive_call(
            adapter, "update", "drive_update",
            arguments["ref"], arguments["content"],
        )
        audit.record("drive_update", acct.id, arguments["ref"], detail={"replaced": True})
        return _ok(result)

    if name == "drive_move":
        acct, adapter = _get_drive_adapter(arguments["account"])
        require_auto_write(acct, "drive_move")
        result = _drive_call(
            adapter, "move", "drive_move", arguments["ref"], arguments["dest"],
        )
        audit.record("drive_move", acct.id, arguments["ref"], detail={"dest": arguments["dest"]})
        return _ok(result)

    if name == "drive_copy":
        acct, adapter = _get_drive_adapter(arguments["account"])
        require_auto_write(acct, "drive_copy")
        result = _drive_call(
            adapter, "copy", "drive_copy", arguments["ref"], arguments["dest"],
        )
        audit.record("drive_copy", acct.id, arguments["ref"], detail={"dest": arguments["dest"]})
        return _ok(result)

    if name == "drive_delete":
        acct, adapter = _get_drive_adapter(arguments["account"])
        require_auto_write(acct, "drive_delete")
        result = _drive_call(adapter, "delete", "drive_delete", arguments["ref"])
        audit.record("drive_delete", acct.id, arguments["ref"], detail={"reversible": True})
        return _ok(result)

    if name == "drive_share":
        # Outward-facing: always gated by the per-call prompt (kept off the
        # allowlist), regardless of auto_write. Audited because it grants access.
        acct, adapter = _get_drive_adapter(arguments["account"])
        try:
            result = _drive_call(
                adapter, "share", "drive_share",
                arguments["ref"], arguments["principal"], arguments["role"],
            )
        except NotImplementedError as e:
            return _ok({"ok": False, "reason": str(e)})
        audit.record(
            "drive_share", acct.id, arguments["ref"],
            detail={"principal": arguments["principal"], "role": arguments["role"]},
        )
        return _ok(result)

    # ---- sheets (Google) -----------------------------------------------

    if name == "sheet_get":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_sheets(adapter, "sheet_get")
        return _ok(adapter.sheet_get(arguments["spreadsheet_id"]))

    if name == "sheet_read":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_sheets(adapter, "sheet_read")
        return _ok(adapter.sheet_read(arguments["spreadsheet_id"], arguments["range"]))

    if name == "sheet_write":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_sheets(adapter, "sheet_write")
        require_auto_write(acct, "sheet_write")
        sid, rng = arguments["spreadsheet_id"], arguments["range"]
        # No silent clobber of a non-empty range (spec section 10).
        if not arguments.get("overwrite") and not adapter.sheet_range_is_empty(sid, rng):
            return _ok({
                "ok": False,
                "reason": (
                    f"Range {rng!r} is not empty. Pass overwrite=true to replace its "
                    f"current contents, or use sheet_append to add rows below it."
                ),
            })
        result = adapter.sheet_write(sid, rng, arguments["values"])
        audit.record("sheet_write", acct.id, sid, detail={"range": rng, "rows": len(arguments["values"])})
        return _ok(result)

    if name == "sheet_append":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_sheets(adapter, "sheet_append")
        require_auto_write(acct, "sheet_append")
        sid, rng = arguments["spreadsheet_id"], arguments["range"]
        result = adapter.sheet_append(sid, rng, arguments["values"])
        audit.record("sheet_append", acct.id, sid, detail={"range": rng, "rows": len(arguments["values"])})
        return _ok(result)

    if name == "sheet_batch_update":
        acct, adapter = _get_drive_adapter(arguments["account"])
        _require_google_sheets(adapter, "sheet_batch_update")
        require_auto_write(acct, "sheet_batch_update")
        sid = arguments["spreadsheet_id"]
        result = adapter.sheet_batch_update(sid, arguments["requests"])
        audit.record("sheet_batch_update", acct.id, sid, detail={"requests": len(arguments["requests"])})
        return _ok(result)

    # ---- docs (Google) -------------------------------------------------

    if name == "doc_get":
        _, adapter = _get_docs_adapter(arguments["account"])
        return _ok(adapter.get(arguments["document_id"]))

    if name == "doc_insert_text":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_insert_text")
        doc_id = arguments["document_id"]
        result = adapter.insert_text(
            doc_id, arguments["text"], int(arguments.get("index", 1)),
        )
        audit.record(
            "doc_insert_text", acct.id, doc_id,
            detail={"index": result.get("index"), "inserted": result.get("inserted")},
        )
        return _ok(result)

    if name == "doc_append":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_append")
        doc_id = arguments["document_id"]
        result = adapter.append_text(doc_id, arguments["text"])
        audit.record(
            "doc_append", acct.id, doc_id,
            detail={"index": result.get("index"), "inserted": result.get("inserted")},
        )
        return _ok(result)

    if name == "doc_replace_text":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_replace_text")
        doc_id = arguments["document_id"]
        result = adapter.replace_all_text(
            doc_id,
            arguments["find"],
            arguments["replace"],
            bool(arguments.get("match_case", False)),
        )
        audit.record(
            "doc_replace_text", acct.id, doc_id,
            detail={"occurrencesChanged": result.get("occurrencesChanged")},
        )
        return _ok(result)

    if name == "doc_get_structured":
        _, adapter = _get_docs_adapter(arguments["account"])
        return _ok(
            adapter.get_structured(
                arguments["document_id"],
                arguments.get("fields"),
                bool(arguments.get("include_tabs", False)),
            )
        )

    if name == "doc_batch_update":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_batch_update")
        doc_id = arguments["document_id"]
        result = adapter.batch_update(
            doc_id, arguments["requests"], arguments.get("write_control"),
        )
        audit.record(
            "doc_batch_update", acct.id, doc_id,
            detail={"requests": len(arguments["requests"])},
        )
        return _ok(result)

    if name == "doc_create":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_create")
        result = adapter.create(arguments["title"])
        audit.record(
            "doc_create", acct.id, result.get("documentId"),
            detail={"title": arguments["title"]},
        )
        return _ok(result)

    if name == "doc_create_table":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_create_table")
        doc_id = arguments["document_id"]
        result = adapter.create_table(
            doc_id,
            int(arguments["rows"]),
            int(arguments["columns"]),
            arguments.get("data"),
            arguments.get("index"),
            arguments.get("tab_id"),
        )
        audit.record(
            "doc_create_table", acct.id, doc_id,
            detail={
                "rows": arguments["rows"],
                "columns": arguments["columns"],
                "cellsFilled": result.get("cellsFilled"),
            },
        )
        return _ok(result)

    if name == "doc_edit_cell":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_edit_cell")
        doc_id = arguments["document_id"]
        result = adapter.edit_cell(
            doc_id,
            arguments["text"],
            int(arguments["row"]),
            int(arguments["col"]),
            int(arguments.get("table_ordinal", 0)),
            arguments.get("tab_id"),
        )
        audit.record(
            "doc_edit_cell", acct.id, doc_id,
            detail={
                "row": arguments["row"],
                "col": arguments["col"],
                "tableOrdinal": arguments.get("table_ordinal", 0),
            },
        )
        return _ok(result)

    if name == "doc_format_matches":
        acct, adapter = _get_docs_adapter(arguments["account"])
        require_auto_write(acct, "doc_format_matches")
        doc_id = arguments["document_id"]
        result = adapter.format_matches(
            doc_id,
            arguments["find"],
            arguments["text_style"],
            arguments.get("fields"),
            bool(arguments.get("match_case", False)),
            bool(arguments.get("all_occurrences", True)),
            arguments.get("tab_id"),
        )
        audit.record(
            "doc_format_matches", acct.id, doc_id,
            detail={"occurrences": result.get("occurrences")},
        )
        return _ok(result)

    # ---- slides (Google) -----------------------------------------------

    if name == "slides_get":
        _, adapter = _get_slides_adapter(arguments["account"])
        return _ok(adapter.get(arguments["presentation_id"]))

    if name == "slides_replace_text":
        acct, adapter = _get_slides_adapter(arguments["account"])
        require_auto_write(acct, "slides_replace_text")
        pres_id = arguments["presentation_id"]
        result = adapter.replace_all_text(
            pres_id,
            arguments["find"],
            arguments["replace"],
            bool(arguments.get("match_case", False)),
        )
        audit.record(
            "slides_replace_text", acct.id, pres_id,
            detail={"occurrencesChanged": result.get("occurrencesChanged")},
        )
        return _ok(result)

    if name == "slides_insert_text":
        acct, adapter = _get_slides_adapter(arguments["account"])
        require_auto_write(acct, "slides_insert_text")
        pres_id = arguments["presentation_id"]
        result = adapter.insert_text(
            pres_id,
            arguments["object_id"],
            arguments["text"],
            int(arguments.get("index", 0)),
        )
        audit.record(
            "slides_insert_text", acct.id, pres_id,
            detail={"objectId": result.get("objectId"), "inserted": result.get("inserted")},
        )
        return _ok(result)

    # ---- calendar ------------------------------------------------------

    if name == "cal_list_calendars":
        _, adapter = _get_calendar_adapter(arguments["account"])
        return _ok(adapter.list_calendars())

    if name == "cal_list_events":
        _, adapter = _get_calendar_adapter(arguments["account"])
        return _ok(adapter.list_events(
            calendar_id=arguments.get("calendar_id", "primary"),
            time_min=arguments.get("time_min"),
            time_max=arguments.get("time_max"),
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 50)),
        ))

    if name == "cal_create_event":
        acct, adapter = _get_calendar_adapter(arguments["account"])
        confirmed = bool(arguments.get("confirmed", False))
        fields = {
            k: v for k, v in arguments.items()
            if k not in ("account", "calendar_id", "confirmed")
        }
        # Server-side outward-facing gate (spec section 4.3): an event with
        # attendees sends invitations, so the server refuses to write it until
        # the caller re-invokes with confirmed=true. Solo events proceed.
        has_attendees = adapter.fields_have_attendees(fields)
        if is_outward_facing("cal_create_event", has_attendees=has_attendees) and not confirmed:
            return _gate_refusal("cal_create_event")
        result = adapter.create_event(arguments.get("calendar_id", "primary"), **fields)
        audit.record(
            "cal_create_event", acct.id, result.get("id"),
            detail={"summary": fields.get("summary"), "attendees": fields.get("attendees")},
        )
        return _ok(result)

    if name == "cal_update_event":
        acct, adapter = _get_calendar_adapter(arguments["account"])
        cal_id = arguments.get("calendar_id", "primary")
        event_id = arguments["event_id"]
        confirmed = bool(arguments.get("confirmed", False))
        fields = {
            k: v for k, v in arguments.items()
            if k not in ("account", "calendar_id", "event_id", "confirmed")
        }
        # Gate on the OR of the stored event's attendees (fetched) and any in the
        # patch: a patch that omits attendees must still gate, and still notify,
        # when the stored event has guests.
        stored_has_attendees = adapter.event_has_attendees(event_id, cal_id)
        has_attendees = stored_has_attendees or adapter.fields_have_attendees(fields)
        if is_outward_facing("cal_update_event", has_attendees=has_attendees) and not confirmed:
            return _gate_refusal("cal_update_event")
        result = adapter.update_event(event_id, cal_id, notify=has_attendees, **fields)
        audit.record(
            "cal_update_event", acct.id, event_id,
            detail={"attendees": fields.get("attendees"), "storedHadAttendees": stored_has_attendees},
        )
        return _ok(result)

    if name == "cal_delete_event":
        acct, adapter = _get_calendar_adapter(arguments["account"])
        cal_id = arguments.get("calendar_id", "primary")
        event_id = arguments["event_id"]
        confirmed = bool(arguments.get("confirmed", False))
        # Gate on the stored event's attendees (a delete carries no patch).
        has_attendees = adapter.event_has_attendees(event_id, cal_id)
        if is_outward_facing("cal_delete_event", has_attendees=has_attendees) and not confirmed:
            return _gate_refusal("cal_delete_event")
        result = adapter.delete_event(event_id, cal_id, notify=has_attendees)
        audit.record("cal_delete_event", acct.id, event_id, detail={"hadAttendees": has_attendees})
        return _ok(result)

    raise ValueError(f"Unknown tool: {name}")


async def run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
