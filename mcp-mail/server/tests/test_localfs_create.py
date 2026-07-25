"""Tests for localfs create: folder creation is explicit, never inferred."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mail.adapters.localfs import LocalFSAdapter, LocalFSError
from mcp_mail.config import LocalFSAccount

FOLDER_MIME = "application/vnd.google-apps.folder"


def _adapter(root: Path) -> LocalFSAdapter:
    account = LocalFSAccount(
        id="fs",
        provider="localfs",
        address="fs",
        roots=(root,),
        capabilities=("drive",),
        auto_write=True,
    )
    return LocalFSAdapter(account)


def test_extensionless_name_creates_file_not_folder(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    meta = fs.create("report", content=None)
    dest = tmp_path / "report"
    assert dest.is_file()  # a FILE, not a surprise directory
    assert meta["isFolder"] is False


def test_named_file_with_content(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    fs.create("notes.txt", content="hello")
    assert (tmp_path / "notes.txt").read_text() == "hello"


def test_folder_via_mime(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    meta = fs.create("Archive", mime=FOLDER_MIME)
    assert (tmp_path / "Archive").is_dir()
    assert meta["isFolder"] is True


def test_folder_via_trailing_slash(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    meta = fs.create("Inbox/")
    assert (tmp_path / "Inbox").is_dir()
    assert meta["isFolder"] is True


def test_folder_with_content_is_rejected(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    with pytest.raises(LocalFSError):
        fs.create("Docs", content="x", mime=FOLDER_MIME)


def test_empty_name_rejected(tmp_path: Path) -> None:
    fs = _adapter(tmp_path)
    with pytest.raises(LocalFSError):
        fs.create("/")


def test_create_cannot_escape_sandbox(tmp_path: Path) -> None:
    from mcp_mail.core.sandbox import SandboxError

    fs = _adapter(tmp_path / "drive")
    (tmp_path / "drive").mkdir()
    with pytest.raises(SandboxError):
        fs.create("../escape.txt", content="x")
