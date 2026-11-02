"""Exercise Windows token-cache limits and upgrade/failure recovery without secrets."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from keyring.errors import PasswordDeleteError, PasswordSetError
from msal import SerializableTokenCache

from mcp_mail import auth
from mcp_mail import credential_store as store

SERVICE = "mcp-mail-test"
USER = "test-account"


@pytest.fixture
def vault(monkeypatch):
    entries = {}
    failures = {"write": None}

    def write(service, username, value):
        if failures["write"] and failures["write"](username):
            raise PasswordSetError("Simulated credential-store write failure")
        if len(value.encode("utf-16-le")) > 2560:
            raise PasswordSetError("Windows credential blob limit")
        entries[service, username] = value

    def delete(service, username):
        if (service, username) not in entries:
            raise PasswordDeleteError("Missing test entry")
        del entries[service, username]

    monkeypatch.setattr(store, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(store.keyring, "get_password", lambda s, u: entries.get((s, u)))
    monkeypatch.setattr(store.keyring, "set_password", write)
    monkeypatch.setattr(store.keyring, "delete_password", delete)
    return entries, failures


def legacy(entries, value):
    pieces = [value[i : i + 1000] for i in range(0, len(value), 1000)]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    entries[SERVICE, USER] = f"mcp-mail-chunked-v1:{len(pieces)}:{digest}"
    for i, piece in enumerate(pieces):
        entries[SERVICE, f"{USER}.__mcp_mail_chunk_{i:04d}"] = piece


def test_upgrade_reads_legacy_and_plain_caches(vault):
    entries, _ = vault
    assert store.get_secret(SERVICE, USER) is None
    entries[SERVICE, USER] = '{"Account": {}}'
    assert store.get_secret(SERVICE, USER) == '{"Account": {}}'
    value = json.dumps({"RefreshToken": {"fixture": {"secret": "fixture" * 3000}}})
    legacy(entries, value)
    assert json.loads(store.get_secret(SERVICE, USER)) == json.loads(value)


@pytest.mark.parametrize("value", ["a" * 1000, "a" * 1001, "😀" * 1300, "fixture" * 3000])
def test_round_trip_respects_utf16_windows_limit(vault, value):
    entries, _ = vault
    store.set_secret(SERVICE, USER, value)
    assert store.get_secret(SERVICE, USER) == value
    assert all(len(v.encode("utf-16-le")) <= 2560 for v in entries.values())


@pytest.mark.parametrize("fail_primary", [False, True])
def test_failed_refresh_preserves_previous_cache(vault, fail_primary):
    entries, failures = vault
    legacy(entries, "previous" * 1000)
    before = entries.copy()
    failures["write"] = lambda u: u == USER if fail_primary else u.endswith("_0001")
    with pytest.raises(PasswordSetError):
        store.set_secret(SERVICE, USER, "replacement" * 1000)
    assert entries == before
    assert store.get_secret(SERVICE, USER) == "previous" * 1000


def test_replacing_and_shrinking_remove_previous_chunks(vault):
    entries, _ = vault
    legacy(entries, "previous" * 1000)
    store.set_secret(SERVICE, USER, "replacement" * 1000)
    assert not any(u.endswith("chunk_0000") for _, u in entries)
    old_keys = set(entries) - {(SERVICE, USER)}
    store.set_secret(SERVICE, USER, "small")
    assert not old_keys.intersection(entries)
    assert entries == {(SERVICE, USER): "small"}


@pytest.mark.parametrize("corruption", ["missing", "changed"])
def test_corrupt_cache_has_clear_error_without_content(vault, corruption):
    entries, _ = vault
    legacy(entries, "sensitive-fixture" * 1000)
    key = SERVICE, f"{USER}.__mcp_mail_chunk_0000"
    if corruption == "missing":
        del entries[key]
    else:
        entries[key] = "changed-fixture"
    with pytest.raises(RuntimeError, match="credential store") as error:
        store.get_secret(SERVICE, USER)
    assert "sensitive-fixture" not in str(error.value)


@pytest.mark.parametrize("manifest", ["mcp-mail-chunked-v1:0:bad", "mcp-mail-chunked-v2:bad"])
def test_malformed_manifest_is_not_returned_as_cache_json(vault, manifest):
    entries, _ = vault
    entries[SERVICE, USER] = manifest
    with pytest.raises(RuntimeError, match="Invalid chunked credential manifest"):
        store.get_secret(SERVICE, USER)


def test_microsoft_auth_load_and_save_use_chunk_aware_storage(vault, monkeypatch):
    entries, _ = vault
    value = json.dumps({"RefreshToken": {"fixture": {"secret": "fixture" * 3000}}})
    legacy(entries, value)
    seen = {}

    def application(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(auth, "PublicClientApplication", application)
    account = SimpleNamespace(
        keychain_service=SERVICE, keychain_user=USER, client_id="test-client", tenant_id="common"
    )
    _, cache = auth._load_app(account)
    assert json.loads(cache.serialize()) == json.loads(value)
    assert seen["token_cache"] is cache
    cache.has_state_changed = True
    auth._save_cache(account, cache)
    assert entries[SERVICE, USER].startswith("mcp-mail-chunked-v2:")
    assert json.loads(store.get_secret(SERVICE, USER)) == json.loads(value)


def test_cache_unchanged_does_not_write(vault):
    entries, _ = vault
    account = SimpleNamespace(keychain_service=SERVICE, keychain_user=USER)
    auth._save_cache(account, SerializableTokenCache())
    assert entries == {}


def test_read_retries_if_another_writer_replaced_and_cleaned_old_cache(vault, monkeypatch):
    entries, _ = vault
    legacy(entries, "previous" * 1000)

    def read(service, username):
        if username.endswith("chunk_0000"):
            entries[SERVICE, USER] = "refreshed-cache"
            return None
        return entries.get((service, username))

    monkeypatch.setattr(store.keyring, "get_password", read)
    assert store.get_secret(SERVICE, USER) == "refreshed-cache"


def test_non_windows_keeps_native_large_credential(vault, monkeypatch):
    entries, _ = vault
    monkeypatch.setattr(store, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(store.keyring, "set_password", lambda s, u, v: entries.update({(s, u): v}))
    value = "fixture" * 3000
    store.set_secret(SERVICE, USER, value)
    assert entries == {(SERVICE, USER): value}


def test_cleanup_failure_does_not_break_newly_published_cache(vault, monkeypatch):
    entries, _ = vault
    legacy(entries, "previous" * 1000)

    def denied(*args):
        raise PasswordDeleteError("Simulated cleanup failure")

    monkeypatch.setattr(store.keyring, "delete_password", denied)
    store.set_secret(SERVICE, USER, "replacement" * 1000)
    assert store.get_secret(SERVICE, USER) == "replacement" * 1000
