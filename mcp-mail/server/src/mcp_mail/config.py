"""Load `accounts.toml` configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mcp-mail" / "accounts.toml"

# Optional shared, non-secret settings that several accounts can inherit. Today
# it carries one table, [m365], holding the `client_id` and `tenant_id` of an
# app registration shared across a team, so nobody has to register their own
# Azure app. Both values are application identity, not secrets: a public client
# puts the client_id in the browser URL on every sign-in, and the tenant id
# resolves from Microsoft's unauthenticated discovery endpoint. Real secrets
# still live only in the OS credential store.
DEFAULTS_PATH = Path.home() / ".config" / "mcp-mail" / "defaults.toml"

# Capability tokens an account may declare. "mail" is the original surface;
# "drive" and "calendar" are added by the Drive/Calendar/SharePoint expansion.
KNOWN_CAPABILITIES = frozenset({"mail", "drive", "calendar"})


def _parse_capabilities(entry: dict, default: list[str]) -> tuple[str, ...]:
    """Read and validate an account's `capabilities` list.

    Defaults preserve backward compatibility: an account that predates the
    expansion (no `capabilities` key) keeps the historical default passed by
    the caller (mail-only for the mail providers, drive-only for localfs).
    """
    raw = entry.get("capabilities", default)
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
        raise ValueError(
            f"account {entry.get('id')!r}: `capabilities` must be a list of strings"
        )
    unknown = [c for c in raw if c not in KNOWN_CAPABILITIES]
    if unknown:
        raise ValueError(
            f"account {entry.get('id')!r}: unknown capabilities {unknown!r}; "
            f"allowed: {sorted(KNOWN_CAPABILITIES)}"
        )
    return tuple(raw)


@dataclass(frozen=True)
class Signature:
    """An account's outgoing signature: an HTML snippet plus any inline images.

    The adapter inlines an image when the snippet references it as
    ``cid:<filename>`` (see GraphAdapter._partition_attachments); otherwise the
    image rides as a normal attachment.
    """

    html_path: Path
    inline_images: tuple[Path, ...] = ()
    on_reply: bool = True


def _parse_signature(entry: dict) -> "Signature | None":
    """Read an account's optional outgoing signature.

    Enabled only when `signature_html` (a path to an HTML snippet) is set. The
    server appends the snippet to outgoing HTML bodies and attaches
    `signature_inline_images`. `signature_on_reply` (default True) controls
    whether replies also carry the signature.
    """
    html_path = entry.get("signature_html")
    if not html_path:
        return None
    imgs = entry.get("signature_inline_images", [])
    if not isinstance(imgs, list) or not all(isinstance(i, str) for i in imgs):
        raise ValueError(
            f"account {entry.get('id')!r}: `signature_inline_images` must be a list of paths"
        )
    return Signature(
        html_path=Path(html_path).expanduser(),
        inline_images=tuple(Path(i).expanduser() for i in imgs),
        on_reply=bool(entry.get("signature_on_reply", True)),
    )


@dataclass(frozen=True)
class M365Account:
    id: str
    provider: Literal["m365"]
    address: str
    client_id: str
    tenant_id: str
    keychain_service: str
    keychain_user: str
    auto_send: bool
    # When set, this account is a DELEGATE VIEW of another user's mailbox (this
    # value is that person's UPN / SMTP). Graph mail calls target
    # `/users/{mailbox}` instead of `/me` and use the delegated shared-mailbox
    # token. `address` should equal the delegated mailbox's address so reply
    # self-exclusion is correct; `client_id` / `tenant_id` / `keychain_*` stay
    # those of the signed-in delegate, so that person's own token is reused.
    mailbox: str | None = None
    capabilities: tuple[str, ...] = ("mail",)
    auto_write: bool = False
    signature: Signature | None = None


@dataclass(frozen=True)
class GmailAccount:
    id: str
    provider: Literal["gmail"]
    address: str
    oauth_keychain_service: str
    oauth_keychain_user: str
    keychain_service: str
    keychain_user: str
    auto_send: bool
    capabilities: tuple[str, ...] = ("mail",)
    auto_write: bool = False


@dataclass(frozen=True)
class IMAPAccount:
    id: str
    provider: Literal["imap"]
    address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    keychain_service: str
    keychain_user: str
    auto_send: bool
    capabilities: tuple[str, ...] = ("mail",)
    auto_write: bool = False


@dataclass(frozen=True)
class LocalFSAccount:
    """A filesystem-backed drive account (iCloud Drive, OneDrive local mount).

    `roots` is the hard sandbox boundary: every path a tool resolves must live
    inside one of these directories (see ``core.sandbox``). There is no network
    auth; the iCloud / OneDrive daemons handle cloud propagation.
    """

    id: str
    provider: Literal["localfs"]
    address: str
    roots: tuple[Path, ...]
    capabilities: tuple[str, ...] = ("drive",)
    auto_write: bool = False
    # localfs has no mailbox, so `auto_send` is meaningless; kept for a uniform
    # account surface and always False.
    auto_send: bool = False
    keychain_service: str = ""
    keychain_user: str = ""


Account = M365Account | GmailAccount | IMAPAccount | LocalFSAccount


def _parse_roots(entry: dict) -> tuple[Path, ...]:
    raw = entry.get("roots")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"localfs account {entry.get('id')!r} requires a non-empty `roots` list"
        )
    roots: list[Path] = []
    for r in raw:
        if not isinstance(r, str):
            raise ValueError(
                f"localfs account {entry.get('id')!r}: each root must be a string path"
            )
        # Expand ~ to an absolute anchor. We do not require the root to exist at
        # load time (a mount may be offline); existence is checked when a tool
        # actually touches it.
        roots.append(Path(r).expanduser())
    return tuple(roots)


def load_defaults(path: Path | None = None) -> dict:
    """Read the optional shared defaults file (see DEFAULTS_PATH).

    Returns an empty mapping when the file is absent, unreadable or invalid.
    That is deliberate: a broken defaults file must never take mail down, it
    must only stop filling in the values it would have supplied, which then
    surfaces as a precise per-account error from `load_accounts`.
    """
    defaults_path = path or DEFAULTS_PATH
    try:
        with open(defaults_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _shared_m365(defaults: dict) -> dict:
    table = defaults.get("m365", {})
    return table if isinstance(table, dict) else {}


def load_accounts(
    path: Path | None = None, defaults_path: Path | None = None
) -> list[Account]:
    config_path = path or DEFAULT_CONFIG_PATH
    shared_defaults_path = defaults_path or DEFAULTS_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"No accounts config at {config_path}. Copy accounts.toml.example from "
            "the installed mcp-mail plugin (look up its installPath in "
            "~/.claude/plugins/installed_plugins.json) to that location."
        )
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    shared_m365 = _shared_m365(load_defaults(shared_defaults_path))
    accounts: list[Account] = []
    for entry in data.get("account", []):
        provider = entry["provider"]
        if provider == "m365":
            # Per-account values win; the shared defaults fill in only what the
            # account block leaves out, so anyone who later registers their own
            # Azure app can override one account without touching the others.
            client_id = entry.get("client_id") or shared_m365.get("client_id")
            tenant_id = entry.get("tenant_id") or shared_m365.get("tenant_id")
            missing = [
                key
                for key, value in (("client_id", client_id), ("tenant_id", tenant_id))
                if not value
            ]
            if missing:
                raise ValueError(
                    f"m365 account {entry.get('id')!r}: missing "
                    f"{' and '.join(missing)}. Set it in that account's block in "
                    f"{config_path}, or once for every M365 account in the [m365] "
                    f"table of {shared_defaults_path}."
                )
            accounts.append(
                M365Account(
                    id=entry["id"],
                    provider="m365",
                    address=entry["address"],
                    client_id=client_id,
                    tenant_id=tenant_id,
                    keychain_service=entry.get("keychain_service", "mcp-mail"),
                    keychain_user=entry.get("keychain_user", entry["id"]),
                    auto_send=bool(entry.get("auto_send", False)),
                    mailbox=entry.get("mailbox"),
                    capabilities=_parse_capabilities(entry, ["mail"]),
                    auto_write=bool(entry.get("auto_write", False)),
                    signature=_parse_signature(entry),
                )
            )
        elif provider == "gmail":
            accounts.append(
                GmailAccount(
                    id=entry["id"],
                    provider="gmail",
                    address=entry["address"],
                    oauth_keychain_service=entry.get("oauth_keychain_service", "mcp-mail"),
                    oauth_keychain_user=entry.get("oauth_keychain_user", "google-oauth-config"),
                    keychain_service=entry.get("keychain_service", "mcp-mail"),
                    keychain_user=entry.get("keychain_user", entry["id"]),
                    auto_send=bool(entry.get("auto_send", False)),
                    capabilities=_parse_capabilities(entry, ["mail"]),
                    auto_write=bool(entry.get("auto_write", False)),
                )
            )
        elif provider == "imap":
            accounts.append(
                IMAPAccount(
                    id=entry["id"],
                    provider="imap",
                    address=entry["address"],
                    imap_host=entry["imap_host"],
                    imap_port=int(entry.get("imap_port", 993)),
                    smtp_host=entry["smtp_host"],
                    smtp_port=int(entry.get("smtp_port", 587)),
                    keychain_service=entry.get("keychain_service", "mcp-mail"),
                    keychain_user=entry.get("keychain_user", entry["id"]),
                    auto_send=bool(entry.get("auto_send", False)),
                    capabilities=_parse_capabilities(entry, ["mail"]),
                    auto_write=bool(entry.get("auto_write", False)),
                )
            )
        elif provider == "localfs":
            accounts.append(
                LocalFSAccount(
                    id=entry["id"],
                    provider="localfs",
                    address=entry.get("address", entry["id"]),
                    roots=_parse_roots(entry),
                    capabilities=_parse_capabilities(entry, ["drive"]),
                    auto_write=bool(entry.get("auto_write", False)),
                )
            )
        else:
            raise NotImplementedError(
                f"Provider {provider!r} not yet supported (account {entry['id']!r})"
            )
    return accounts


def get_account(
    account_id: str, path: Path | None = None, defaults_path: Path | None = None
) -> Account:
    for acct in load_accounts(path, defaults_path):
        if acct.id == account_id:
            return acct
    raise KeyError(f"No account with id {account_id!r} in accounts.toml")


def has_capability(account: Account, capability: str) -> bool:
    """True if the account declares `capability` (e.g. 'drive', 'calendar')."""
    return capability in account.capabilities
