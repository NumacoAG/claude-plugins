"""Configuration precedence and local credential loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from clockify_mcp.config import Settings
from clockify_mcp.errors import ConfigError


def test_settings_uses_os_credential_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CLOCKIFY_API_KEY", raising=False)
    monkeypatch.setattr("clockify_mcp.config.load_api_key", lambda: "keyring-key")

    settings = Settings.load(config_path=tmp_path / "missing.toml")

    assert settings.api_key == "keyring-key"


def test_environment_key_takes_precedence_over_keyring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CLOCKIFY_API_KEY", "environment-key")

    def unexpected_keyring_read() -> str | None:
        raise AssertionError("Keyring should not be read when an environment key is set")

    monkeypatch.setattr("clockify_mcp.config.load_api_key", unexpected_keyring_read)

    settings = Settings.load(config_path=tmp_path / "missing.toml")

    assert settings.api_key == "environment-key"


def test_legacy_file_key_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CLOCKIFY_API_KEY", raising=False)
    monkeypatch.setattr("clockify_mcp.config.load_api_key", lambda: None)
    config_path = tmp_path / "config.toml"
    config_path.write_text('api_key = "legacy-key"\n', encoding="utf-8")

    settings = Settings.load(config_path=config_path)

    assert settings.api_key == "legacy-key"


def test_missing_key_points_to_secure_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CLOCKIFY_API_KEY", raising=False)
    monkeypatch.setattr("clockify_mcp.config.load_api_key", lambda: None)

    with pytest.raises(ConfigError, match=r"clockify-mcp --store-key"):
        Settings.load(config_path=tmp_path / "missing.toml")
