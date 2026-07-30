"""Re-authorize one Gmail / Google Workspace account interactively.

Run from the `server/` directory, with a browser available on this machine:

    uv run python scripts/reauth_google.py work-gmail
    uv run python scripts/reauth_google.py personal-gmail

It opens the Google consent screen (listening on localhost:8766), and on
success writes the fresh refresh token to the Keychain, so the MCP server can
read the account again. Use this whenever the server reports a Gmail token as
expired or revoked.

RUN THIS ONCE PER GOOGLE ACCOUNT AFTER UPGRADING FROM A MAIL-ONLY RELEASE. The
consent screen now requests the UNION of the mail, Drive, Sheets and Calendar
scopes, because Google freezes a refresh token's granted scopes at consent time
and one token has to cover every surface. A token minted by an older, mail-only
version therefore no longer validates against the current scope list, and mail
itself stops working until this script is run, not just the new tools.

Two things to watch on the consent screen itself:

* If you are signed into more than one Google account, check the account shown
  is the one you are re-authorizing. The flow follows the browser's active
  session, so it happily consents as the wrong identity. Use "Use another
  account" if it preselected the wrong one, and confirm afterwards with
  ``mail_whoami``.
* Google presents the permissions as individual checkboxes. Tick every one, or
  use "Select all". A partial grant is accepted silently, and the surfaces you
  left unchecked then fail with HTTP 403
  ``ACCESS_TOKEN_SCOPE_INSUFFICIENT`` while the ones you ticked keep working.

Note: if you have to run this every ~7 days, the OAuth consent screen is still
in "Testing". Set it to "In production" in Google Cloud Console (APIs &
Services -> OAuth consent screen) to stop the weekly expiry.
"""

from __future__ import annotations

import sys

from mcp_mail.adapters.gmail import acquire_credentials
from mcp_mail.config import GmailAccount, get_account


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: reauth_google.py <account-id>   (e.g. work-gmail)")
        raise SystemExit(2)

    account_id = sys.argv[1]
    try:
        account = get_account(account_id)
    except KeyError as exc:
        print(exc)
        raise SystemExit(1)

    if not isinstance(account, GmailAccount):
        print(f"{account_id!r} is a {account.provider!r} account, not gmail. Nothing to do.")
        raise SystemExit(1)

    print(f"Re-authorizing {account_id} ({account.address})...")
    print("A browser window will open. Pick the matching Google account and consent.")
    creds = acquire_credentials(account, allow_interactive=True)

    if creds and creds.valid:
        print(f"OK: fresh token stored for {account_id}. The server can read this account again.")
    else:
        print(f"FAILED: did not obtain valid credentials for {account_id}.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
