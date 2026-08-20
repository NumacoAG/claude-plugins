"""Clockify API key storage in the operating system credential store."""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

from .errors import ConfigError

KEYRING_SERVICE = "clockify-mcp"
KEYRING_ACCOUNT = "api-key"


def load_api_key() -> str | None:
    """Return the locally stored API key, or ``None`` when none is configured."""
    try:
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as exc:
        raise ConfigError(
            f"Could not read the Clockify API key from the OS credential store: {exc}"
        ) from exc
    return value.strip() if value and value.strip() else None


def store_api_key(api_key: str) -> None:
    """Store one user's API key without writing it to a file or shell history."""
    value = api_key.strip()
    if not value:
        raise ConfigError("Clockify API key is empty; nothing was stored.")
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, value)
    except KeyringError as exc:
        raise ConfigError(
            f"Could not store the Clockify API key in the OS credential store: {exc}"
        ) from exc


def delete_api_key() -> bool:
    """Delete the locally stored API key. Return whether a key existed."""
    existing = load_api_key()
    if existing is None:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as exc:
        raise ConfigError(
            f"Could not delete the Clockify API key from the OS credential store: {exc}"
        ) from exc
    return True
