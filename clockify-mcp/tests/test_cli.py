"""Local command line setup behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clockify_mcp import cli


def test_store_key_validates_before_persisting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = MagicMock()
    client = MagicMock()
    client.get_current_user.return_value = {
        "name": "Local User",
        "email": "local@example.com",
    }
    client_type = MagicMock(return_value=client)
    store = MagicMock()

    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "  personal-key  ")
    monkeypatch.setattr(cli.Settings, "load", MagicMock(return_value=settings))
    monkeypatch.setattr(cli, "ClockifyClient", client_type)
    monkeypatch.setattr(cli, "store_api_key", store)

    assert cli.main(["--store-key"]) == 0

    cli.Settings.load.assert_called_once_with(api_key_override="personal-key")
    client_type.assert_called_once_with(settings)
    client.get_current_user.assert_called_once_with()
    client.close.assert_called_once_with()
    store.assert_called_once_with("personal-key")
    assert "Local User <local@example.com>" in capsys.readouterr().out


def test_delete_key_reports_when_nothing_is_stored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "delete_api_key", lambda: False)

    assert cli.main(["--delete-key"]) == 0
    assert "No Clockify API key was stored" in capsys.readouterr().out
