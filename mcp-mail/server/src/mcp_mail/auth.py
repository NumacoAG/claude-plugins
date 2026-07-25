"""MSAL auth + macOS Keychain persistence for Microsoft accounts."""

from __future__ import annotations

import keyring
from msal import PublicClientApplication, SerializableTokenCache

from .config import M365Account

GRAPH_SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/MailboxSettings.ReadWrite",
]
# `offline_access` is added automatically by MSAL.

# File scopes for SharePoint / OneDrive, added by the expansion. These are kept
# SEPARATE from GRAPH_SCOPES on purpose (spec section 7.2): widening the
# silent-auth mail scope set would force an interactive prompt on every mail
# call. File ops request these silently and only succeed once you have run the
# interactive reauth (scripts/reauth_m365.py), which consents to the UNION of
# mail + file scopes against the same Azure app and writes the refreshed token
# to the same Keychain entry.
GRAPH_FILE_SCOPES = [
    "https://graph.microsoft.com/Files.ReadWrite.All",
    "https://graph.microsoft.com/Sites.ReadWrite.All",
]

# Calendar scopes. Kept OUT of GRAPH_SCOPES for the same reason as the file
# scopes: widening the silent mail set would force an interactive prompt on
# every mail call. Grant BOTH ReadWrite variants: .Shared is not implied by
# .ReadWrite and is required for delegate / shared-mailbox calendars.
GRAPH_CALENDAR_SCOPES = [
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/Calendars.ReadWrite.Shared",
]

# Delegated shared-mailbox mail scope. Lets the signed-in user read and draft in
# ANOTHER user's mailbox (targeting /users/{mailbox}) once that mailbox owner has
# granted them Exchange Full Access. Kept OUT of GRAPH_SCOPES for the same
# spec-7.2 reason as the file and calendar scopes: widening the silent mail set
# would force an interactive browser prompt on every ordinary mail call. This is
# the DELEGATED scope (Mail.ReadWrite.Shared), NOT the application/app-only
# variant; it is requested silent-only and only mints a token once you have run
# scripts/reauth_m365.py to consent to the union. The Exchange Full Access grant
# from the mailbox owner is a SEPARATE prerequisite the scope alone does not
# satisfy.
GRAPH_SHARED_SCOPES = ["https://graph.microsoft.com/Mail.ReadWrite.Shared"]

# The full set requested at interactive re-consent time. MSAL returns one
# refresh token covering the union, so a single browser consent lights up
# mail, files, calendar, and delegated shared-mailbox mail.
GRAPH_REAUTH_SCOPES = (
    GRAPH_SCOPES + GRAPH_FILE_SCOPES + GRAPH_CALENDAR_SCOPES + GRAPH_SHARED_SCOPES
)


def _load_app(acct: M365Account) -> tuple[PublicClientApplication, SerializableTokenCache]:
    cache = SerializableTokenCache()
    blob = keyring.get_password(acct.keychain_service, acct.keychain_user)
    if blob:
        cache.deserialize(blob)
    app = PublicClientApplication(
        client_id=acct.client_id,
        authority=f"https://login.microsoftonline.com/{acct.tenant_id}",
        token_cache=cache,
    )
    return app, cache


def _save_cache(acct: M365Account, cache: SerializableTokenCache) -> None:
    if cache.has_state_changed:
        keyring.set_password(acct.keychain_service, acct.keychain_user, cache.serialize())


def acquire_token(acct: M365Account) -> str:
    """Return a valid access token for this account.

    Tries silent (using the refresh token in Keychain) first; falls back to
    interactive (opens a browser; requires `http://localhost:8765` — with
    NO path — to be a registered redirect URI on the Azure AD app).
    """
    app, cache = _load_app(acct)
    msal_accounts = app.get_accounts()
    if msal_accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=msal_accounts[0])
        if result and "access_token" in result:
            _save_cache(acct, cache)
            return result["access_token"]
    result = app.acquire_token_interactive(scopes=GRAPH_SCOPES, port=8765)
    _save_cache(acct, cache)
    if "access_token" not in result:
        raise RuntimeError(
            f"Authentication failed for {acct.id}: "
            f"{result.get('error_description') or result}"
        )
    return result["access_token"]


def acquire_file_token(acct: M365Account) -> str:
    """Return a token carrying the SharePoint / OneDrive file scopes.

    Silent only: it never opens a browser. The file scopes ride on the same
    refresh token as mail once you have run ``scripts/reauth_m365.py`` to consent
    to the union. If that re-consent has not happened, the silent call cannot
    mint a file-scoped token and we raise a clear, actionable error pointing at
    the helper, rather than triggering an interactive prompt on a headless
    server (the same failure mode the Gmail adapter guards against).
    """
    app, cache = _load_app(acct)
    msal_accounts = app.get_accounts()
    if msal_accounts:
        result = app.acquire_token_silent(GRAPH_FILE_SCOPES, account=msal_accounts[0])
        if result and "access_token" in result:
            _save_cache(acct, cache)
            return result["access_token"]
    raise RuntimeError(
        f"{acct.id}: no token covering the SharePoint / OneDrive file scopes "
        f"({', '.join(s.rsplit('/', 1)[-1] for s in GRAPH_FILE_SCOPES)}). "
        f"Run the one-off interactive re-consent from a terminal:\n"
        f"    uv run python scripts/reauth_m365.py {acct.id}\n"
        f"That consents to the union of mail + file scopes against the existing "
        f"Azure app and refreshes the same Keychain token. Until then, use the "
        f"local OneDrive or iCloud Drive mount backend instead."
    )


def acquire_calendar_token(acct: M365Account) -> str:
    """Return a token carrying the calendar scopes. Silent only, never opens a
    browser. Calendar rides the same refresh token as mail + files once you have
    run scripts/reauth_m365.py to consent to the union."""
    app, cache = _load_app(acct)
    msal_accounts = app.get_accounts()
    if msal_accounts:
        result = app.acquire_token_silent(GRAPH_CALENDAR_SCOPES, account=msal_accounts[0])
        if result and "access_token" in result:
            _save_cache(acct, cache)
            return result["access_token"]
    raise RuntimeError(
        f"{acct.id}: no token covering the calendar scopes "
        f"({', '.join(s.rsplit('/', 1)[-1] for s in GRAPH_CALENDAR_SCOPES)}). "
        f"Run the one-off interactive re-consent from a terminal:\n"
        f"    uv run python scripts/reauth_m365.py {acct.id}\n"
        f"That consents to the union of mail + file + calendar scopes against "
        f"the existing Azure app and refreshes the same Keychain token."
    )


def acquire_shared_token(acct: M365Account) -> str:
    """Return a token carrying the delegated shared-mailbox mail scope. Silent
    only, never opens a browser. Shared mail rides the same refresh token as
    mail + files + calendar once you have run scripts/reauth_m365.py to consent to
    the union. Minting a token is necessary but not sufficient: the target
    mailbox owner must also have granted this user Exchange Full Access, or Graph
    still rejects /users/{mailbox} calls."""
    app, cache = _load_app(acct)
    msal_accounts = app.get_accounts()
    if msal_accounts:
        result = app.acquire_token_silent(GRAPH_SHARED_SCOPES, account=msal_accounts[0])
        if result and "access_token" in result:
            _save_cache(acct, cache)
            return result["access_token"]
    raise RuntimeError(
        f"{acct.id}: no token covering the delegated shared-mailbox mail scope "
        f"({', '.join(s.rsplit('/', 1)[-1] for s in GRAPH_SHARED_SCOPES)}). "
        f"Run the one-off interactive re-consent from a terminal:\n"
        f"    uv run python scripts/reauth_m365.py {acct.id}\n"
        f"That consents to the union of mail + file + calendar + shared-mailbox "
        f"scopes against the existing Azure app and refreshes the same Keychain "
        f"token. The mailbox owner must also grant Exchange Full Access."
    )


def reauth_interactive(acct: M365Account) -> dict:
    """One-off interactive consent for the UNION of mail + file + calendar +
    delegated shared-mailbox scopes.

    Called by ``scripts/reauth_m365.py`` (browser available). Writes the
    refreshed token, covering mail, file, calendar, and shared-mailbox scopes, to
    the same Keychain entry the mail surface already reads, so nothing about mail
    changes except that the token now also satisfies file, calendar, and
    delegated shared-mailbox ops.
    """
    app, cache = _load_app(acct)
    result = app.acquire_token_interactive(scopes=GRAPH_REAUTH_SCOPES, port=8765)
    _save_cache(acct, cache)
    if "access_token" not in result:
        raise RuntimeError(
            f"Re-consent failed for {acct.id}: "
            f"{result.get('error_description') or result}"
        )
    return {
        "ok": True,
        "account": acct.id,
        "scopes": result.get("scope"),
    }
