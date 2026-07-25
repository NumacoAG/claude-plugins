"""Re-consent one Microsoft 365 account for the file, calendar and shared-mailbox scopes.

Run from the ``server/`` directory, with a browser available on this machine:

    uv run python scripts/reauth_m365.py work-m365

It opens the Microsoft sign-in (listening on localhost:8765, which must be a
registered redirect URI on the Azure app) requesting the UNION of the existing
mail scopes plus ``Files.ReadWrite.All`` and ``Sites.ReadWrite.All`` (SharePoint
/ OneDrive), ``Calendars.ReadWrite`` and ``Calendars.ReadWrite.Shared``, and
``Mail.ReadWrite.Shared`` (delegated shared-mailbox mail), then writes the
refreshed token to the SAME Keychain entry the mail surface already reads. Mail
keeps working unchanged; the token now also satisfies the drive_* file tools on
SharePoint and OneDrive, the cal_* calendar tools, and delegate mailbox reads /
drafts.

This is the M365 mirror of ``reauth_google.py``. ``Sites.ReadWrite.All`` is
admin-consent gated in most tenants: if the sign-in shows an
"admin approval required" wall, the Entra admin must grant consent once for the
app. ``Mail.ReadWrite.Shared`` is a delegated
scope that may be admin-consent gated the same way; and the target mailbox owner
must separately grant this user Exchange Full Access for delegate calls to work.
Port 8765 must be free.
"""

from __future__ import annotations

import sys

from mcp_mail.auth import reauth_interactive
from mcp_mail.config import M365Account, get_account


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: reauth_m365.py <account-id>   (e.g. work-m365)")
        raise SystemExit(2)

    account_id = sys.argv[1]
    try:
        account = get_account(account_id)
    except KeyError as exc:
        print(exc)
        raise SystemExit(1) from exc

    if not isinstance(account, M365Account):
        print(f"{account_id!r} is a {account.provider!r} account, not m365. Nothing to do.")
        raise SystemExit(1)

    print(f"Re-consenting {account_id} ({account.address})...")
    print("A browser window will open. Sign in and approve the requested permissions.")
    print("Scopes requested: Mail.ReadWrite, Mail.Send, MailboxSettings.ReadWrite,")
    print("                  Files.ReadWrite.All, Sites.ReadWrite.All,")
    print("                  Calendars.ReadWrite, Calendars.ReadWrite.Shared,")
    print("                  Mail.ReadWrite.Shared.")
    result = reauth_interactive(account)

    if result.get("ok"):
        print(f"OK: refreshed token stored for {account_id}. SharePoint / OneDrive + calendar tools enabled.")
        print(f"Granted scopes: {result.get('scopes')}")
    else:
        print(f"FAILED: did not obtain valid credentials for {account_id}.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
