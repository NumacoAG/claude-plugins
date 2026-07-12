"""MCP stdio server for mcp-mail."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Protocol

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import unsubscribe as unsub
from .adapters.gmail import GmailAdapter
from .adapters.graph import GraphAdapter
from .adapters.imap import IMAPAdapter
from .config import Account, get_account, load_accounts

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
    ) -> None: ...


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
                "is a list of local file paths. Confirmation-gated by Claude Code's per-call "
                "permission prompt — do NOT add to the allowlist."
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
                },
                "required": ["account", "to", "subject"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_reply",
            description=(
                "Reply to a message; the provider handles threading. Pass `reply_all` to include CC "
                "recipients. Optional `attachments` is a list of local file paths. Confirmation-gated "
                "like `mail_send`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "reply_all": {"type": "boolean", "description": "Default false."},
                    "attachments": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="mail_download_attachments",
            description=(
                "Download all non-inline file attachments to a local directory. "
                "Default target_dir: a 'mcp-mail' folder in the OS temp directory. Pass target_dir explicitly to keep the files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **account_arg,
                    "message_id": {"type": "string"},
                    "target_dir": {"type": "string"},
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
        _, adapter = _get_adapter(arguments["account"])
        adapter.send(
            to=arguments["to"],
            subject=arguments["subject"],
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
            attachments=arguments.get("attachments"),
        )
        return _ok({"ok": True, "sent_to": arguments["to"]})

    if name == "mail_reply":
        _, adapter = _get_adapter(arguments["account"])
        adapter.reply(
            message_id=arguments["message_id"],
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            reply_all=bool(arguments.get("reply_all", False)),
            attachments=arguments.get("attachments"),
        )
        return _ok({"ok": True, "replied_to": arguments["message_id"]})

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
        written: list[str] = []
        skipped: list[dict] = []
        for meta in adapter.list_attachments(msg_id):
            if meta.get("isInline"):
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
                if stem:
                    out_path = target / f"{stem}_{n}.{suf}"
                else:
                    out_path = target / f"{fname}_{n}"
                n += 1
            out_path.write_bytes(data)
            written.append(str(out_path))
        return _ok({"directory": str(target), "written": written, "skipped": skipped})

    raise ValueError(f"Unknown tool: {name}")


async def run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
