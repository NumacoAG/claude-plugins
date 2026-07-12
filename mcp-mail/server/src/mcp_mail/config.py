"""Load `accounts.toml` configuration."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mcp-mail" / "accounts.toml"


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


Account = M365Account | GmailAccount | IMAPAccount


def load_accounts(path: Path | None = None) -> list[Account]:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"No accounts config at {config_path}. "
            "Copy accounts.toml.example from the repo root."
        )
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    accounts: list[Account] = []
    for entry in data.get("account", []):
        provider = entry["provider"]
        if provider == "m365":
            accounts.append(
                M365Account(
                    id=entry["id"],
                    provider="m365",
                    address=entry["address"],
                    client_id=entry["client_id"],
                    tenant_id=entry["tenant_id"],
                    keychain_service=entry.get("keychain_service", "mcp-mail"),
                    keychain_user=entry.get("keychain_user", entry["id"]),
                    auto_send=bool(entry.get("auto_send", False)),
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
                )
            )
        else:
            # Non-mail providers (e.g. 'localfs' drive backends) live in the same
            # accounts.toml but are not mail accounts. Skip them rather than abort
            # the whole loader, so one such entry can't block mail/reauth for the
            # supported accounts. Warn on stderr so a genuine typo still surfaces.
            print(
                f"mcp-mail: skipping non-mail provider {provider!r} "
                f"(account {entry['id']!r})",
                file=sys.stderr,
            )
            continue
    return accounts


def get_account(account_id: str, path: Path | None = None) -> Account:
    for acct in load_accounts(path):
        if acct.id == account_id:
            return acct
    raise KeyError(f"No account with id {account_id!r} in accounts.toml")
