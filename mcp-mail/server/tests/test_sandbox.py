"""Tests for the localfs path sandbox (spec section 9).

The contract under test: a resolved path must live inside the account's roots,
with ``..`` traversal and symlink escape both rejected. These are the guarantees
that make ``drive_delete`` structurally incapable of reaching ``~/.ssh``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_mail.core.sandbox import SandboxError, is_within, resolve_within


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Path:
    root = tmp_path / "drive"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "note.txt").write_text("hello")
    return root


def test_plain_child_resolves(sandbox_root: Path) -> None:
    resolved = resolve_within(str(sandbox_root / "sub" / "note.txt"), [sandbox_root])
    assert resolved == (sandbox_root / "sub" / "note.txt").resolve()


def test_relative_path_anchored_to_first_root(sandbox_root: Path) -> None:
    resolved = resolve_within("sub/note.txt", [sandbox_root])
    assert resolved == (sandbox_root / "sub" / "note.txt").resolve()


def test_dotdot_traversal_rejected(sandbox_root: Path) -> None:
    with pytest.raises(SandboxError):
        resolve_within(str(sandbox_root / "sub" / ".." / ".." / "escape.txt"), [sandbox_root])


def test_absolute_path_outside_roots_rejected(sandbox_root: Path) -> None:
    with pytest.raises(SandboxError):
        resolve_within("/etc/passwd", [sandbox_root])


def test_home_relative_outside_rejected(sandbox_root: Path) -> None:
    with pytest.raises(SandboxError):
        resolve_within("~/.ssh/id_rsa", [sandbox_root])


def test_symlink_escape_rejected(sandbox_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = sandbox_root / "escape"
    os.symlink(outside, link)
    # A path that traverses the symlink lands outside the root once resolved.
    with pytest.raises(SandboxError):
        resolve_within(str(link / "secret.txt"), [sandbox_root])


def test_symlink_within_root_allowed(sandbox_root: Path) -> None:
    target = sandbox_root / "sub"
    link = sandbox_root / "alias"
    os.symlink(target, link)
    resolved = resolve_within(str(link / "note.txt"), [sandbox_root])
    assert resolved == (sandbox_root / "sub" / "note.txt").resolve()


def test_create_under_existing_parent_allowed(sandbox_root: Path) -> None:
    # A not-yet-existing tail under a real sandboxed parent must resolve (this is
    # the drive_create case): the file does not exist yet but its parent does.
    resolved = resolve_within(str(sandbox_root / "sub" / "new.txt"), [sandbox_root])
    assert resolved == (sandbox_root / "sub" / "new.txt").resolve()


def test_empty_roots_rejects_everything(sandbox_root: Path) -> None:
    with pytest.raises(SandboxError):
        resolve_within(str(sandbox_root / "sub" / "note.txt"), [])


def test_is_within_true_and_false(sandbox_root: Path, tmp_path: Path) -> None:
    assert is_within(sandbox_root / "sub" / "note.txt", [sandbox_root])
    assert not is_within(tmp_path / "elsewhere.txt", [sandbox_root])


def test_multiple_roots(sandbox_root: Path, tmp_path: Path) -> None:
    second = tmp_path / "drive2"
    second.mkdir()
    (second / "f.txt").write_text("x")
    resolved = resolve_within(str(second / "f.txt"), [sandbox_root, second])
    assert resolved == (second / "f.txt").resolve()
