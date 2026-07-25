"""Shared M365 app identity: ~/.config/mcp-mail/defaults.toml.

The account block always wins; the shared file fills in only what the account
leaves out; a broken shared file is ignored rather than fatal; and when neither
side supplies a value the error names the account and both candidate files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mail.config import load_accounts, load_defaults

_SHARED_ONLY = """
[[account]]
id = "work-m365"
provider = "m365"
address = "you@example.com"
"""

_PER_ACCOUNT_WINS = """
[[account]]
id = "work-m365"
provider = "m365"
address = "you@example.com"
client_id = "own-client"
tenant_id = "own-tenant"
"""

_MIXED = """
[[account]]
id = "work-m365"
provider = "m365"
address = "you@example.com"
client_id = "own-client"
"""

_DEFAULTS = """
[m365]
client_id = "shared-client"
tenant_id = "shared-tenant"
"""


def _write(tmp_path: Path, accounts: str, defaults: str | None) -> tuple[Path, Path]:
    accounts_path = tmp_path / "accounts.toml"
    accounts_path.write_text(accounts)
    defaults_path = tmp_path / "defaults.toml"
    if defaults is not None:
        defaults_path.write_text(defaults)
    return accounts_path, defaults_path


def test_shared_defaults_fill_in_missing_app_identity(tmp_path: Path) -> None:
    accounts_path, defaults_path = _write(tmp_path, _SHARED_ONLY, _DEFAULTS)
    acct = load_accounts(accounts_path, defaults_path)[0]
    assert acct.client_id == "shared-client"
    assert acct.tenant_id == "shared-tenant"


def test_per_account_values_win_over_shared_defaults(tmp_path: Path) -> None:
    accounts_path, defaults_path = _write(tmp_path, _PER_ACCOUNT_WINS, _DEFAULTS)
    acct = load_accounts(accounts_path, defaults_path)[0]
    assert acct.client_id == "own-client"
    assert acct.tenant_id == "own-tenant"


def test_precedence_is_per_key(tmp_path: Path) -> None:
    accounts_path, defaults_path = _write(tmp_path, _MIXED, _DEFAULTS)
    acct = load_accounts(accounts_path, defaults_path)[0]
    assert acct.client_id == "own-client"
    assert acct.tenant_id == "shared-tenant"


def test_missing_everywhere_raises_a_message_naming_both_files(tmp_path: Path) -> None:
    accounts_path, defaults_path = _write(tmp_path, _SHARED_ONLY, None)
    with pytest.raises(ValueError) as exc:
        load_accounts(accounts_path, defaults_path)
    message = str(exc.value)
    assert "work-m365" in message
    assert "client_id" in message and "tenant_id" in message
    assert str(accounts_path) in message
    assert str(defaults_path) in message


def test_broken_defaults_file_is_ignored_not_fatal(tmp_path: Path) -> None:
    accounts_path, defaults_path = _write(tmp_path, _PER_ACCOUNT_WINS, "this is not toml {{")
    assert load_defaults(defaults_path) == {}
    acct = load_accounts(accounts_path, defaults_path)[0]
    assert acct.client_id == "own-client"


def test_missing_defaults_file_is_ignored(tmp_path: Path) -> None:
    assert load_defaults(tmp_path / "nope.toml") == {}
