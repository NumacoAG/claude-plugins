"""Consent to read-only Teams access without changing mail's credential cache."""

import sys

from mcp_mail.auth import reauth_teams_interactive
from mcp_mail.config import M365Account, get_account


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: uv run python scripts/reauth_teams.py <account-id>")
    account = get_account(sys.argv[1])
    if (
        not isinstance(account, M365Account)
        or "teams" not in account.capabilities
        or account.mailbox
    ):
        raise SystemExit(
            "Enable teams on your own M365 account first; delegate mailboxes are unsupported."
        )
    print(f"Opening Microsoft sign-in for {account.address}.", flush=True)
    print(
        "Requested permissions: User.Read and Chat.Read. Mail permissions and credentials remain separate.",
        flush=True,
    )
    result = reauth_teams_interactive(account)
    print(f"Teams credentials saved in the OS credential store for {result['account']}.")


if __name__ == "__main__":
    main()
