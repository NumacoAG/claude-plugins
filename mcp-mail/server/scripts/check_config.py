"""Validate accounts.toml and print the accounts it parsed. Network-free.

Run from the `server/` directory:

    uv run python scripts/check_config.py

Reads ~/.config/mcp-mail/accounts.toml (the same path the server uses). Prints a
clear error if the file is missing or the TOML is malformed.
"""

from __future__ import annotations

from mcp_mail.config import load_accounts


def main() -> None:
    accts = load_accounts()
    if not accts:
        print("No accounts found. Did you fill in ~/.config/mcp-mail/accounts.toml?")
        return
    print(f"Parsed {len(accts)} account(s):")
    for a in accts:
        print(f"  - {a.provider:6} {a.id:20} {a.address}")


if __name__ == "__main__":
    main()
