"""Operating system credential store helpers."""

from __future__ import annotations

import pytest
from keyring.errors import KeyringError

from clockify_mcp import credentials
from clockify_mcp.errors import ConfigError


def test_store_and_load_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], str] = {}

    def set_password(service: str, account: str, value: str) -> None:
        stored[(service, account)] = value

    def get_password(service: str, account: str) -> str | None:
        return stored.get((service, account))

    monkeypatch.setattr(credentials.keyring, "set_password", set_password)
    monkeypatch.setattr(credentials.keyring, "get_password", get_password)

    credentials.store_api_key("  secret  ")

    assert credentials.load_api_key() == "secret"
    assert stored[(credentials.KEYRING_SERVICE, credentials.KEYRING_ACCOUNT)] == "secret"


def test_delete_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(credentials, "load_api_key", lambda: "secret")
    monkeypatch.setattr(
        credentials.keyring,
        "delete_password",
        lambda service, account: deleted.append((service, account)),
    )

    assert credentials.delete_api_key() is True
    assert deleted == [(credentials.KEYRING_SERVICE, credentials.KEYRING_ACCOUNT)]


def test_keyring_failure_becomes_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_service: str, _account: str) -> str | None:
        raise KeyringError("unavailable")

    monkeypatch.setattr(credentials.keyring, "get_password", fail)

    with pytest.raises(ConfigError, match="credential store"):
        credentials.load_api_key()
