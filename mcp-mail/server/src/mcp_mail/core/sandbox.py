"""The hard path sandbox for the localfs backend (spec section 9).

Every path a localfs tool touches is resolved here against the account's
allow-listed ``roots``. The contract: a resolved path must live inside one of
the roots, with ``..`` traversal and symlink escape both rejected. A
``drive_delete`` must be structurally incapable of reaching, say, ``~/.ssh``.

The function is pure and side-effect free (beyond reading the filesystem to
resolve symlinks), which keeps it cheap to unit test.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path


class SandboxError(ValueError):
    """Raised when a requested path resolves outside the account's roots."""


def _real(path: Path) -> Path:
    """Resolve a path to its canonical, symlink-free, absolute form.

    Resolves symlinks for the longest existing prefix and appends the
    not-yet-existing tail verbatim. This lets us sandbox a path that is about
    to be *created* (e.g. ``drive_create``) while still defeating a symlink
    that points outside the roots: any symlink in the existing prefix is
    followed by ``os.path.realpath`` before the tail is joined.
    """
    expanded = path.expanduser()
    # os.path.realpath resolves every symlink it can and is defined for
    # non-existent tails (it simply does not stat them), which is exactly the
    # "create a new file under a real, sandboxed parent" case.
    return Path(os.path.realpath(expanded))


def _roots_real(roots: Iterable[Path]) -> list[Path]:
    return [_real(r) for r in roots]


def is_within(path: Path, roots: Sequence[Path]) -> bool:
    """True if `path`, fully resolved, sits inside one of `roots` (resolved)."""
    target = _real(path)
    for root in _roots_real(roots):
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_within(ref: str | Path, roots: Sequence[Path]) -> Path:
    """Resolve `ref` and assert it lives inside one of `roots`.

    Returns the canonical (symlink-free, absolute) path. Raises
    ``SandboxError`` for any path that escapes the roots, whether through
    ``..`` traversal, an absolute path outside the roots, or a symlink whose
    target is outside the roots.

    `roots` must be non-empty; an empty allow-list rejects everything, which is
    the safe default for a misconfigured account.
    """
    if not roots:
        raise SandboxError("no roots configured: every path is rejected")

    candidate = Path(ref).expanduser()
    real_roots = _roots_real(roots)

    # An absolute path is taken as-is; a relative path is anchored to the first
    # root (the natural "current drive" for a single-root account).
    base = candidate if candidate.is_absolute() else (real_roots[0] / candidate)
    resolved = _real(base)

    for root in real_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise SandboxError(
        f"path {ref!r} resolves to {resolved} which is outside the account's "
        f"sandbox roots {[str(r) for r in real_roots]}"
    )
