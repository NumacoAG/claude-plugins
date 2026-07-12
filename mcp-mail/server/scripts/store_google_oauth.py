"""Store the shared Google OAuth client (client_id + client_secret) in the OS
credential store, where the Gmail adapter looks for it.

All your Google accounts (personal + Workspace) share this one client.

Run from the `server/` directory:

    uv run python scripts/store_google_oauth.py

Cross-platform: macOS Keychain, Windows Credential Manager, or Linux Secret
Service — `keyring` picks the right backend automatically.
"""

from __future__ import annotations

import getpass
import json

import keyring

SERVICE = "mcp-mail"
ACCOUNT = "google-oauth-config"


def main() -> None:
    print("Storing the shared Google OAuth client for mcp-mail.\n")
    client_id = input("Google OAuth client_id: ").strip()
    # getpass hides the secret and keeps it out of shell history / scrollback.
    client_secret = getpass.getpass("Google OAuth client_secret (hidden): ").strip()
    if not client_id or not client_secret:
        raise SystemExit("Both client_id and client_secret are required — nothing stored.")
    keyring.set_password(
        SERVICE,
        ACCOUNT,
        json.dumps({"client_id": client_id, "client_secret": client_secret}),
    )
    print(f"\nStored '{ACCOUNT}' in the OS credential store (service '{SERVICE}').")


if __name__ == "__main__":
    main()
