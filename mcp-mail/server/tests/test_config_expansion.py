"""Tests for the config-schema additions: capabilities, auto_write, localfs roots."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mail.config import (
    GmailAccount,
    LocalFSAccount,
    has_capability,
    load_accounts,
)

_CONFIG = """
[[account]]
id = "personal-gmail"
provider = "gmail"
address = "x@example.com"
capabilities = ["mail", "drive", "calendar"]
auto_write = true

[[account]]
id = "legacy-gmail"
provider = "gmail"
address = "legacy@example.com"

[[account]]
id = "icloud-drive"
provider = "localfs"
capabilities = ["drive"]
auto_write = false
roots = ["{root_a}", "{root_b}"]
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    root_a = tmp_path / "CloudDocs"
    root_b = tmp_path / "obsidian"
    root_a.mkdir()
    root_b.mkdir()
    p = tmp_path / "accounts.toml"
    p.write_text(_CONFIG.format(root_a=root_a, root_b=root_b))
    return p


def test_capabilities_parsed(config_file: Path) -> None:
    accounts = {a.id: a for a in load_accounts(config_file)}
    gmail = accounts["personal-gmail"]
    assert gmail.capabilities == ("mail", "drive", "calendar")
    assert gmail.auto_write is True
    assert has_capability(gmail, "drive")
    assert has_capability(gmail, "calendar")


def test_legacy_account_defaults_to_mail_only(config_file: Path) -> None:
    accounts = {a.id: a for a in load_accounts(config_file)}
    legacy = accounts["legacy-gmail"]
    assert isinstance(legacy, GmailAccount)
    assert legacy.capabilities == ("mail",)
    assert legacy.auto_write is False
    assert not has_capability(legacy, "drive")


def test_localfs_account(config_file: Path) -> None:
    accounts = {a.id: a for a in load_accounts(config_file)}
    fs = accounts["icloud-drive"]
    assert isinstance(fs, LocalFSAccount)
    assert fs.provider == "localfs"
    assert fs.capabilities == ("drive",)
    assert len(fs.roots) == 2
    assert all(isinstance(r, Path) for r in fs.roots)


def test_unknown_capability_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text(
        '[[account]]\nid="x"\nprovider="gmail"\naddress="x@y.z"\n'
        'capabilities=["mail","teleport"]\n'
    )
    with pytest.raises(ValueError, match="unknown capabilities"):
        load_accounts(p)


def test_localfs_requires_roots(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text('[[account]]\nid="fs"\nprovider="localfs"\n')
    with pytest.raises(ValueError, match="requires a non-empty"):
        load_accounts(p)
