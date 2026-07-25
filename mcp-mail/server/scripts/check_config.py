"""Validate accounts.toml and print the accounts it parsed. Network-free.

Run it against the installed plugin (no clone needed):

    uv --directory "$MCPMAIL/server" run python scripts/check_config.py

or, from a checkout of this repository, from the `server/` directory:

    uv run python scripts/check_config.py

Reads ~/.config/mcp-mail/accounts.toml, plus the optional shared
~/.config/mcp-mail/defaults.toml, exactly as the server does. Prints a clear
error if either file is missing or malformed, and shows, per M365 account,
whether client_id and tenant_id came from the account block or from the shared
defaults file.
"""

from __future__ import annotations

import tomllib

from mcp_mail.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULTS_PATH,
    load_accounts,
    load_defaults,
)


def _raw_entries() -> dict[str, dict]:
    """The account tables exactly as written, so we can see which keys are set."""
    try:
        with open(DEFAULT_CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {
        e["id"]: e
        for e in data.get("account", [])
        if isinstance(e, dict) and "id" in e
    }


def main() -> None:
    accts = load_accounts()
    if not accts:
        print(f"No accounts found. Did you fill in {DEFAULT_CONFIG_PATH}?")
        return
    shared = load_defaults().get("m365", {})
    raw = _raw_entries()
    print(f"Parsed {len(accts)} account(s) from {DEFAULT_CONFIG_PATH}:")
    for a in accts:
        print(f"  - {a.provider:6} {a.id:20} {a.address}")
        if a.provider != "m365":
            continue
        entry = raw.get(a.id, {})
        for key in ("client_id", "tenant_id"):
            origin = "accounts.toml" if entry.get(key) else "defaults.toml [m365]"
            print(f"      {key:10} from {origin}")
    if shared:
        print(f"\nShared M365 app identity loaded from {DEFAULTS_PATH}.")
    else:
        print(
            f"\nNo shared M365 app identity at {DEFAULTS_PATH} "
            "(fine: every M365 account then carries its own client_id and tenant_id)."
        )


if __name__ == "__main__":
    main()
