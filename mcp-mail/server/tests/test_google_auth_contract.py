"""Library-contract tests for the REAL ``google.oauth2.credentials.Credentials``.

Companion to ``test_google_scope_persistence.py``. That module stubs
``Credentials`` outright, so it proves the adapter's own logic and nothing at all
about the google-auth behaviour that logic is built on. This module closes that
gap: it imports the real class and drives it with a recording fake transport, so
an upgrade of google-auth that changes any of the pinned behaviours fails here
loudly instead of silently re-opening the bug.

The bug being protected against (see ``mcp_mail.adapters.gmail`` for the full
story): handing a per-surface scope subset (``MAIL_SCOPES``, ``FILE_SCOPES``) to
``Credentials.from_authorized_user_info`` makes the refresh request carry that
subset as its ``scope`` parameter, so Google mints an access token narrowed to
it. ``to_json()`` then persists the narrowed ``scopes`` list and drops
``granted_scopes`` entirely, so the next call on a *different* surface presents a
token that no longer covers it and gets HTTP 403
``ACCESS_TOKEN_SCOPE_INSUFFICIENT``. Nothing raises along the way: narrowing is
only a log warning. Mail and Docs then take turns breaking each other after
every token expiry.

Three library behaviours the fix depends on, each pinned below:

1. ``refresh()`` sends ``scope`` derived from ``creds.scopes``, space joined, and
   omits the parameter entirely when ``scopes`` is ``None``. Asserted on what the
   fake transport actually received, not on any adapter-side intent.
2. ``granted_scopes`` is populated from the token response's ``scope`` field, but
   only under the exact condition ``if scopes and "scope" in grant_response``
   (google-auth 2.53.0, ``Credentials._perform_refresh_token``). Both halves are
   load bearing: with ``scopes=None`` the response's ``scope`` is ignored, and
   with no ``scope`` in the response the previous value is left untouched rather
   than cleared. Neither the constructor nor
   ``from_authorized_user_info`` restores it, so a freshly loaded credential
   always reports ``granted_scopes is None`` until a refresh happens.
3. ``to_json()`` serialises ``scopes`` and never ``granted_scopes``, which is why
   the adapter overwrites the ``scopes`` key with the recorded grant before
   writing the blob to the Keychain.

No network and no Keychain: the transport is a callable that records the request
and replays a canned token response.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

import pytest
from google.oauth2.credentials import Credentials

from mcp_mail.adapters.gmail import CONSENT_SCOPES, FILE_SCOPES, MAIL_SCOPES

GOOGLE_AUTH_LOGGER = "google.oauth2.credentials"


class _FakeResponse:
    """Minimal stand-in for a ``google.auth.transport.Response``."""

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self.data = json.dumps(payload).encode("utf-8")


class _RecordingRequest:
    """Stand-in for ``google.auth.transport.Request`` that never connects.

    google-auth calls the request object as
    ``request(method=..., url=..., headers=..., body=...)`` with a urlencoded
    body, so the recorded body is exactly the wire form of the token request.
    """

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str = "GET",
        url: str = "",
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
        **kwargs: Any,
    ) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return _FakeResponse(self._payload, self._status)

    @property
    def sent_params(self) -> dict[str, str]:
        """The last token request's body, urldecoded into a flat mapping."""
        assert self.calls, "the transport was never called"
        raw = self.calls[-1]["body"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return dict(urllib.parse.parse_qsl(raw or ""))


def _token_response(granted: list[str] | None) -> dict[str, Any]:
    """A successful refresh-grant response, optionally carrying ``scope``."""
    payload: dict[str, Any] = {
        "access_token": "fresh-access-token",
        "expires_in": 3599,
        "token_type": "Bearer",
    }
    if granted is not None:
        payload["scope"] = " ".join(granted)
    return payload


def _load_creds(scopes: list[str] | None) -> Credentials:
    """Build real ``Credentials`` the way the adapter does, from a stored blob."""
    info: dict[str, Any] = {
        "token": "stale-access-token",
        "refresh_token": "stored-refresh-token",
        "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "client-secret",
    }
    if scopes is not None:
        info["scopes"] = list(scopes)
    return Credentials.from_authorized_user_info(info, scopes=scopes)


def _refresh(
    creds: Credentials, granted: list[str] | None
) -> _RecordingRequest:
    """Refresh ``creds`` against a fake transport and return the recorder."""
    request = _RecordingRequest(_token_response(granted))
    creds.refresh(request)
    return request


# ---- 1. the refresh request's ``scope`` parameter ---------------------------


def test_refresh_sends_scope_derived_from_creds_scopes() -> None:
    """``creds.scopes`` becomes the wire ``scope``, space joined, in order.

    This is the whole mechanism of the bug: whatever list sits in ``creds.scopes``
    is what Google is asked to mint a token for. Passing a per-surface subset here
    is how the access token got narrowed.
    """
    creds = _load_creds(list(MAIL_SCOPES))

    request = _refresh(creds, list(MAIL_SCOPES))

    params = request.sent_params
    assert params["grant_type"] == "refresh_token"
    assert params["refresh_token"] == "stored-refresh-token"
    assert "scope" in params, "google-auth stopped sending a scope parameter on refresh"
    assert params["scope"] == " ".join(MAIL_SCOPES)
    assert params["scope"].split(" ") == list(MAIL_SCOPES)
    # A single POST to Google's token endpoint, and nothing else.
    assert len(request.calls) == 1
    assert request.calls[0]["method"] == "POST"
    assert request.calls[0]["url"] == "https://oauth2.googleapis.com/token"


def test_refresh_sends_the_union_when_the_union_was_requested() -> None:
    """The fix's remedy has to reach the wire, not just ``creds.scopes``."""
    creds = _load_creds(list(CONSENT_SCOPES))

    params = _refresh(creds, list(CONSENT_SCOPES)).sent_params

    assert params["scope"].split(" ") == list(CONSENT_SCOPES)
    assert set(FILE_SCOPES) <= set(params["scope"].split(" "))


def test_refresh_omits_scope_when_scopes_is_none() -> None:
    """With ``scopes=None`` no ``scope`` parameter is sent at all.

    Google then returns a token for the full existing grant. The adapter does not
    rely on this (it always asks for ``CONSENT_SCOPES``), but the asymmetry is why
    "no scopes" is safe while "some scopes" is dangerous.
    """
    creds = _load_creds(None)
    assert creds.scopes is None

    request = _refresh(creds, list(CONSENT_SCOPES))

    params = request.sent_params
    assert "scope" not in params
    assert params["grant_type"] == "refresh_token"


def test_refresh_omits_scope_for_an_empty_scope_list() -> None:
    """An empty list is falsy in google-auth's ``if scopes`` guard, like ``None``."""
    creds = _load_creds([])

    params = _refresh(creds, list(CONSENT_SCOPES)).sent_params

    assert "scope" not in params


# ---- 2. ``granted_scopes`` and its exact precondition ----------------------


def test_granted_scopes_comes_from_the_token_response_scope_field() -> None:
    """Google's answer, not the request, is the truth about the grant."""
    creds = _load_creds(list(CONSENT_SCOPES))
    assert creds.granted_scopes is None

    _refresh(creds, list(CONSENT_SCOPES))

    assert creds.granted_scopes == list(CONSENT_SCOPES)
    # ``scopes`` is untouched by the refresh: it stays what was requested.
    assert creds.scopes == list(CONSENT_SCOPES)


def test_narrowed_grant_is_only_a_warning_never_an_error() -> None:
    """Requesting more than was granted succeeds and merely logs.

    This silence is why the bug never surfaced at refresh time and only showed up
    later as an HTTP 403 ``ACCESS_TOKEN_SCOPE_INSUFFICIENT`` from an API call.
    Asking for the union is therefore safe.
    """
    creds = _load_creds(list(CONSENT_SCOPES))

    with caplog_at_warning() as records:
        _refresh(creds, list(MAIL_SCOPES))

    assert creds.granted_scopes == list(MAIL_SCOPES)
    assert creds.valid
    missing = set(CONSENT_SCOPES) - set(MAIL_SCOPES)
    assert records, "google-auth stopped warning about ungranted scopes"
    warning = " ".join(r.getMessage() for r in records)
    assert "Not all requested scopes were granted" in warning
    for scope in missing:
        assert scope in warning


def test_granted_scopes_stays_none_when_no_scopes_were_requested() -> None:
    """First half of ``if scopes and "scope" in grant_response``.

    With ``scopes=None`` the response's ``scope`` is ignored outright, so a caller
    that omits scopes can never learn the grant from a refresh.
    """
    creds = _load_creds(None)

    _refresh(creds, list(CONSENT_SCOPES))

    assert creds.granted_scopes is None


def test_granted_scopes_is_left_untouched_when_the_response_omits_scope() -> None:
    """Second half of the condition, and it is *not* a reset to ``None``.

    A response without ``scope`` leaves whatever ``granted_scopes`` held before,
    so a stale value can survive a refresh. The adapter's
    ``creds.granted_scopes or recorded`` fallback covers the ``None`` case for
    exactly this reason.
    """
    creds = _load_creds(list(CONSENT_SCOPES))
    _refresh(creds, list(MAIL_SCOPES))
    assert creds.granted_scopes == list(MAIL_SCOPES)

    _refresh(creds, None)

    assert creds.granted_scopes == list(MAIL_SCOPES)


def test_a_freshly_loaded_credential_reports_no_granted_scopes() -> None:
    """``from_authorized_user_info`` never restores ``granted_scopes``.

    Not from an explicit key either: the blob's own recorded grant is the only
    thing the adapter can consult before a refresh happens.
    """
    creds = _load_creds(list(CONSENT_SCOPES))
    assert creds.granted_scopes is None

    with_key = Credentials.from_authorized_user_info(
        {
            "token": "t",
            "refresh_token": "r",
            "client_id": "cid",
            "client_secret": "secret",
            "scopes": list(MAIL_SCOPES),
            "granted_scopes": list(CONSENT_SCOPES),
        }
    )
    assert with_key.granted_scopes is None
    assert with_key.scopes == list(MAIL_SCOPES)


# ---- 3. what ``to_json`` persists -----------------------------------------


def test_to_json_serialises_scopes_but_not_granted_scopes() -> None:
    """The serialiser drops the only honest record of the grant."""
    creds = _load_creds(list(CONSENT_SCOPES))
    _refresh(creds, list(MAIL_SCOPES))

    blob = json.loads(creds.to_json())

    assert blob["scopes"] == list(CONSENT_SCOPES)
    assert "granted_scopes" not in blob
    assert not any("granted" in key for key in blob)
    # The keys the adapter's rewrite relies on survive the round trip.
    assert blob["refresh_token"] == "stored-refresh-token"
    assert blob["token"] == "fresh-access-token"


def test_the_full_narrowing_loop_still_reproduces_with_the_real_class() -> None:
    """End to end, with no stubs: a subset request poisons the stored blob.

    Store a per-surface subset, refresh, serialise, reload: the reloaded
    credential asks for the subset again, so every other surface's token is
    narrowed and 403s. This is the loop the adapter breaks by rewriting the
    ``scopes`` key with the recorded grant; if this test ever stops reproducing,
    the library changed and the fix's premise needs rereading.
    """
    creds = _load_creds(list(MAIL_SCOPES))
    _refresh(creds, list(CONSENT_SCOPES))

    blob = json.loads(creds.to_json())
    assert blob["scopes"] == list(MAIL_SCOPES)
    assert set(FILE_SCOPES).isdisjoint(blob["scopes"])

    reloaded = Credentials.from_authorized_user_info(blob)
    assert reloaded.scopes == list(MAIL_SCOPES)

    params = _refresh(reloaded, list(CONSENT_SCOPES)).sent_params
    assert params["scope"] == " ".join(MAIL_SCOPES)


# ---- helpers ---------------------------------------------------------------


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _CaplogAtWarning:
    """Capture google-auth's warnings without depending on caplog propagation."""

    def __init__(self, logger_name: str) -> None:
        self._logger = logging.getLogger(logger_name)
        self._handler = _CaptureHandler()
        self._previous_level = self._logger.level

    def __enter__(self) -> list[logging.LogRecord]:
        self._logger.setLevel(logging.WARNING)
        self._logger.addHandler(self._handler)
        return self._handler.records

    def __exit__(self, *exc_info: object) -> None:
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._previous_level)


def caplog_at_warning(logger_name: str = GOOGLE_AUTH_LOGGER) -> _CaplogAtWarning:
    return _CaplogAtWarning(logger_name)


def test_the_pinned_source_of_truth_is_the_installed_google_auth() -> None:
    """Guard the premise: these tests must exercise the real library.

    A stub sneaking in (a conftest monkeypatch, a shadowing module) would make
    every assertion above vacuous.
    """
    import google.auth

    assert Credentials.__module__ == "google.oauth2.credentials"
    assert google.auth.__version__.split(".")[0] == "2", (
        "google-auth went to a new major version; re-read "
        "Credentials._perform_refresh_token and to_json before trusting the fix"
    )


@pytest.mark.parametrize("scopes", [list(MAIL_SCOPES), list(FILE_SCOPES), list(CONSENT_SCOPES)])
def test_every_surface_subset_narrows_the_wire_scope(scopes: list[str]) -> None:
    """No surface list is special: each one is sent verbatim if handed over."""
    creds = _load_creds(scopes)

    params = _refresh(creds, list(CONSENT_SCOPES)).sent_params

    assert params["scope"].split(" ") == scopes
