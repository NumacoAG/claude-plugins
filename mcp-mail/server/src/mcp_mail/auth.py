"""MSAL auth + OS credential-store persistence (via keyring) for Microsoft accounts."""

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
