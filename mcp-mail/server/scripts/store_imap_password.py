"""Store an IMAP account's app-specific password in the OS credential store.

Run once per IMAP account (iCloud, Yahoo, Fastmail, ...), from the `server/`
directory:

    uv run python scripts/store_imap_password.py

The account id you type must match an `id` in your accounts.toml exactly.

Cross-platform: macOS Keychain, Windows Credential Manager, or Linux Secret
Service — `keyring` picks the right backend automatically.
"""

from __future__ import annotations

import getpass

import keyring

SERVICE = "mcp-mail"


def main() -> None:
    account_id = input("Account id exactly as in accounts.toml (e.g. icloud): ").strip()
    if not account_id:
        raise SystemExit("Account id is required — nothing stored.")
    # getpass hides the password and keeps it out of shell history / scrollback.
    pw = getpass.getpass(f"App-specific password for '{account_id}' (hidden): ")
    if not pw:
        raise SystemExit("Password is required — nothing stored.")
    keyring.set_password(SERVICE, account_id, pw)
    print(f"\nStored app-specific password for '{account_id}' (service '{SERVICE}').")


if __name__ == "__main__":
    main()
