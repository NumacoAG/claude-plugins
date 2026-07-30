"""Tests for Google credential scope handling in ``acquire_credentials``.

Regression cover for a silent, self-inflicted authorization failure. google-auth
sends ``creds.scopes`` as the refresh request's ``scope`` parameter, so handing a
per-surface subset (``MAIL_SCOPES``, ``FILE_SCOPES``) to
``Credentials.from_authorized_user_info`` made Google mint an access token
narrowed to that subset. ``to_json()`` then persisted the narrowed list while
dropping ``granted_scopes``, so the next call on a *different* surface presented
a token that no longer covered it and got HTTP 403
``ACCESS_TOKEN_SCOPE_INSUFFICIENT``. Google only logs a warning when requested
scopes are missing, so nothing surfaced until an API call failed. Mail and Docs
then took turns breaking each other after every token expiry.

Everything is pinned without touching the network or the Keychain: ``keyring``,
``Credentials`` and ``Request`` are stubbed. Covered:

1. Loading requests the union, never the caller's per-surface subset.
2. After a refresh, the blob records the scopes Google *granted*, not the ones
   requested, so the grant survives a round trip.
3. A blob whose recorded grant was narrowed by an older release heals itself
   from the refresh token instead of demanding a pointless re-consent.
4. A genuinely narrow grant still raises the actionable re-consent error.
"""

from __future__ import annotations

import json

import pytest

from mcp_mail.adapters import gmail
from mcp_mail.adapters.gmail import CONSENT_SCOPES, FILE_SCOPES, MAIL_SCOPES


class _FakeAccount:
    id = "work-gmail"
    keychain_service = "mcp-mail"
    keychain_user = "work-gmail"


class _FakeCreds:
    """Stand-in for ``google.oauth2.credentials.Credentials``.

    Mirrors the two behaviours that caused the bug: ``to_json`` serialises the
    *requested* scopes, and ``granted_scopes`` (the truth from Google) is not
    serialised at all.
    """

    def __init__(self, info: dict, scopes: list[str] | None) -> None:
        self.token = info.get("token")
        self.refresh_token = info.get("refresh_token")
        self.scopes = list(scopes or [])
        self.expired = bool(info.get("_expired"))
        self._granted = list(info.get("_granted") or [])
        self.refresh_calls = 0

    @property
    def granted_scopes(self) -> list[str]:
        return self._granted

    @property
    def valid(self) -> bool:
        return self.token is not None and not self.expired

    def refresh(self, request) -> None:
        self.refresh_calls += 1
        self.expired = False
        self.token = "refreshed-token"

    def to_json(self) -> str:
        return json.dumps(
            {
                "token": self.token,
                "refresh_token": self.refresh_token,
                "client_id": "cid",
                "client_secret": "secret",
                "scopes": self.scopes,
            }
        )


@pytest.fixture
def env(monkeypatch):
    """Stub keyring + Credentials; expose the stored blob and requested scopes."""
    store: dict[tuple[str, str], str] = {}
    seen: dict[str, object] = {}

    class _FakeKeyring:
        @staticmethod
        def get_password(service: str, user: str):
            return store.get((service, user))

        @staticmethod
        def set_password(service: str, user: str, value: str) -> None:
            store[(service, user)] = value

    class _FakeCredentials:
        @classmethod
        def from_authorized_user_info(cls, info, scopes=None):
            seen["requested"] = scopes
            creds = _FakeCreds(info, scopes)
            seen["creds"] = creds
            return creds

    monkeypatch.setattr(gmail, "keyring", _FakeKeyring)
    monkeypatch.setattr(gmail, "Credentials", _FakeCredentials)
    monkeypatch.setattr(gmail, "Request", lambda: None)

    def write_blob(*, scopes, granted, expired=False):
        store[("mcp-mail", "work-gmail")] = json.dumps(
            {
                "token": "stored-token",
                "refresh_token": "r",
                "client_id": "cid",
                "client_secret": "secret",
                "scopes": scopes,
                "_granted": granted,
                "_expired": expired,
            }
        )

    def stored_scopes():
        return json.loads(store[("mcp-mail", "work-gmail")])["scopes"]

    return type(
        "Env",
        (),
        {
            "write_blob": staticmethod(write_blob),
            "stored_scopes": staticmethod(stored_scopes),
            "seen": seen,
        },
    )


def test_load_requests_the_union_not_the_surface_subset(env):
    """The caller's subset must never reach ``creds.scopes``, or refresh narrows."""
    env.write_blob(scopes=list(CONSENT_SCOPES), granted=list(CONSENT_SCOPES))

    gmail.acquire_credentials(_FakeAccount(), required_scopes=FILE_SCOPES)

    assert env.seen["requested"] == CONSENT_SCOPES
    assert env.seen["requested"] != FILE_SCOPES


def test_refresh_records_granted_scopes_not_requested(env):
    """An expired mail call must not shrink the stored grant to the mail subset."""
    env.write_blob(
        scopes=list(CONSENT_SCOPES), granted=list(CONSENT_SCOPES), expired=True
    )

    gmail.acquire_credentials(_FakeAccount(), required_scopes=MAIL_SCOPES)

    assert env.stored_scopes() == sorted(set(CONSENT_SCOPES))
    assert set(env.stored_scopes()) > set(MAIL_SCOPES)


def test_stale_narrow_record_heals_without_re_consent(env):
    """A grant narrowed by an older release is re-learned from the refresh token."""
    env.write_blob(scopes=list(MAIL_SCOPES), granted=list(CONSENT_SCOPES))

    creds = gmail.acquire_credentials(_FakeAccount(), required_scopes=FILE_SCOPES)

    assert creds.refresh_calls == 1
    assert env.stored_scopes() == sorted(set(CONSENT_SCOPES))


def test_genuinely_narrow_grant_still_demands_re_consent(env):
    """When Google really has not granted the surface, say so actionably."""
    env.write_blob(scopes=list(MAIL_SCOPES), granted=list(MAIL_SCOPES))

    with pytest.raises(RuntimeError, match="reauth_google.py"):
        gmail.acquire_credentials(_FakeAccount(), required_scopes=FILE_SCOPES)
