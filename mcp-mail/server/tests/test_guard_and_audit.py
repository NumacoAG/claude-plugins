"""Tests for the write guard, the outward-facing gate, and the audit log."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mail.config import GmailAccount
from mcp_mail.core import audit
from mcp_mail.core.guard import (
    WriteGuardError,
    is_outward_facing,
    require_auto_write,
)


def _account(auto_write: bool) -> GmailAccount:
    return GmailAccount(
        id="test-gmail",
        provider="gmail",
        address="t@example.com",
        oauth_keychain_service="mcp-mail",
        oauth_keychain_user="google-oauth-config",
        keychain_service="mcp-mail",
        keychain_user="test-gmail",
        auto_send=False,
        capabilities=("mail", "drive"),
        auto_write=auto_write,
    )


def test_guard_blocks_when_auto_write_false() -> None:
    with pytest.raises(WriteGuardError):
        require_auto_write(_account(auto_write=False), "drive_delete")


def test_guard_allows_when_auto_write_true() -> None:
    # Should not raise.
    require_auto_write(_account(auto_write=True), "drive_delete")


def test_drive_share_always_outward_facing() -> None:
    assert is_outward_facing("drive_share")
    assert is_outward_facing("drive_share", has_attendees=False)


def test_calendar_gate_depends_on_attendees() -> None:
    assert is_outward_facing("cal_create_event", has_attendees=True)
    assert not is_outward_facing("cal_create_event", has_attendees=False)
    assert is_outward_facing("cal_delete_event", has_attendees=True)
    assert not is_outward_facing("cal_update_event", has_attendees=False)


def test_non_outward_tool() -> None:
    assert not is_outward_facing("drive_read")
    assert not is_outward_facing("sheet_append")


def test_audit_appends_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    audit.record("drive_delete", "test-gmail", "file-123", detail={"reversible": True}, path=log)
    audit.record("sheet_append", "test-gmail", "sheet-9", detail={"rows": 7}, path=log)
    records = audit.read_all(log)
    assert len(records) == 2
    assert records[0]["op"] == "drive_delete"
    assert records[0]["account"] == "test-gmail"
    assert records[0]["ref"] == "file-123"
    assert records[1]["detail"]["rows"] == 7
    assert "ts" in records[0]


def test_audit_is_append_only(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    audit.record("drive_create", "a", "r1", path=log)
    audit.record("drive_create", "a", "r2", path=log)
    # A second logger run must not truncate the first record.
    assert len(audit.read_all(log)) == 2


def test_audit_never_raises_on_bad_path() -> None:
    # A directory that cannot be created should be swallowed, not raised.
    bad = Path("/proc/should-not-be-writable/audit.log")
    audit.record("drive_delete", "a", "r", path=bad)  # must not raise
