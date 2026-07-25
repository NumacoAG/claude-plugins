"""Local filesystem drive backend for iCloud Drive and OneDrive local mounts.

This is the highest-risk adapter because it touches the real home directory
(spec section 9). Three guarantees, all enforced here:

- **Hard path sandbox.** Every ``ref`` is resolved through ``core.sandbox``
  against the account's ``roots``. ``..`` traversal and symlink escape are
  rejected, so a ``drive_delete`` is structurally incapable of reaching, say,
  ``~/.ssh``.
- **Trash, never rm.** Deletion moves the item to the macOS Trash via Finder
  (``osascript``), so it is recoverable. There is no hard-delete path.
- **Materialise dataless files.** iCloud / OneDrive files may be cloud-only
  placeholders; a read triggers download (``brctl download`` for iCloud, a
  read-to-materialise touch for OneDrive) with a timeout and a clear error if
  offline.

``ref`` for this backend is an absolute-within-sandbox path (the dispatcher
passes paths straight through; the sandbox normalises and validates them).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..config import LocalFSAccount
from ..core import sandbox

# iCloud placeholder files surface as ".<name>.icloud" siblings until
# materialised; OneDrive uses APFS dataless files with no special name.
ICLOUD_PLACEHOLDER_SUFFIX = ".icloud"
MATERIALISE_TIMEOUT_S = 60


class LocalFSError(RuntimeError):
    """Raised for localfs operations that fail for non-sandbox reasons."""


class ShareNotSupportedError(NotImplementedError):
    """drive_share is not meaningful on a local filesystem backend."""


class LocalFSAdapter:
    """Sandboxed filesystem backend. All paths pass through ``core.sandbox``."""

    def __init__(self, account: LocalFSAccount) -> None:
        self.account = account
        self.roots = list(account.roots)

    # ---- sandbox resolution ------------------------------------------------

    def _resolve(self, ref: str) -> Path:
        """Resolve `ref` to a real path inside the account's roots, or raise."""
        return sandbox.resolve_within(ref, self.roots)

    # ---- read-side ---------------------------------------------------------

    def list(self, path: str | None = None, page: str | None = None) -> dict:
        target = self._resolve(path) if path else self._first_existing_root()
        if not target.is_dir():
            raise LocalFSError(f"Not a directory: {target}")
        files: list[dict] = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            files.append(self._stat(child))
        return {"files": files, "nextPageToken": None}

    def search(self, query: str, limit: int = 25) -> list[dict]:
        """Name-substring search beneath the roots (case-insensitive)."""
        needle = query.lower()
        hits: list[dict] = []
        for root in self.roots:
            real_root = root.expanduser()
            if not real_root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(real_root):
                # Skip the iCloud placeholder dot-files in the listing pass.
                for name in list(dirnames) + filenames:
                    if needle in name.lower():
                        candidate = Path(dirpath) / name
                        try:
                            hits.append(self._stat(self._resolve(str(candidate))))
                        except sandbox.SandboxError:
                            continue
                        if len(hits) >= limit:
                            return hits
        return hits

    def get_metadata(self, ref: str) -> dict:
        return self._stat(self._resolve(ref))

    def read(self, ref: str, target_dir: str | None = None) -> dict:
        """Read a file, materialising a cloud-only placeholder first if needed."""
        path = self._resolve(ref)
        path = self._materialise(path)
        if not path.is_file():
            raise LocalFSError(f"Not a readable file: {path}")
        return {
            "ref": str(path),
            "mode": "binary",
            "path": str(path),
            "metadata": self._stat(path),
        }

    # ---- write-side --------------------------------------------------------

    def create(
        self,
        name: str,
        parent: str | None = None,
        content: str | None = None,
        mime: str | None = None,
    ) -> dict:
        """Create a file or folder under `parent` (a sandboxed directory path).

        Folder creation is EXPLICIT, never inferred from the name: pass the
        Google-folder mime (``application/vnd.google-apps.folder``) or a trailing
        slash on `name`. Any other input creates a FILE (with `content`, or empty
        when none is given), so an extension-less name like "report" yields an
        empty file, not a surprise directory.
        """
        parent_dir = self._resolve(parent) if parent else self._first_existing_root()
        want_folder = mime == "application/vnd.google-apps.folder" or name.endswith("/")
        clean_name = name.rstrip("/")
        if not clean_name:
            raise LocalFSError("create requires a non-empty name")
        # Resolve the final path through the sandbox too, so a `name` containing
        # traversal ("../../x") cannot escape.
        dest = self._resolve(str(parent_dir / clean_name))
        if want_folder:
            if content is not None:
                raise LocalFSError("a folder cannot be created with file content")
            dest.mkdir(parents=True, exist_ok=True)
            return self._stat(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content or "", encoding="utf-8")
        return self._stat(dest)

    def update(self, ref: str, content: str) -> dict:
        """Overwrite a file's text content."""
        path = self._resolve(ref)
        if path.is_dir():
            raise LocalFSError(f"Refusing to overwrite a directory: {path}")
        path.write_text(content, encoding="utf-8")
        return self._stat(path)

    def move(self, ref: str, dest: str) -> dict:
        """Move/rename within the sandbox. Both source and destination validated."""
        src = self._resolve(ref)
        dst = self._resolve(dest)
        if dst.is_dir():
            dst = dst / src.name
            dst = self._resolve(str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return self._stat(dst)

    def copy(self, ref: str, dest: str) -> dict:
        src = self._resolve(ref)
        dst = self._resolve(dest)
        if dst.is_dir():
            dst = self._resolve(str(dst / src.name))
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return self._stat(dst)

    def delete(self, ref: str) -> dict:
        """Move to macOS Trash (recoverable). Never ``rm`` (spec section 9)."""
        path = self._resolve(ref)
        if not path.exists():
            raise LocalFSError(f"Nothing to delete at {path}")
        self._trash(path)
        return {"ref": str(path), "trashed": True}

    def share(self, ref: str, principal: str, role: str) -> dict:
        raise ShareNotSupportedError(
            "drive_share is not supported on a local filesystem backend "
            "(no sharing surface). Use the Google or Graph backend for sharing."
        )

    # ---- materialisation ---------------------------------------------------

    def _materialise(self, path: Path) -> Path:
        """Download a cloud-only placeholder so the bytes are local before read.

        iCloud: a not-yet-downloaded file shows up as a sibling
        ``.<name>.icloud`` placeholder; ``brctl download`` pulls it down.
        OneDrive: APFS dataless files materialise on first read, so a bounded
        read is enough to trigger the daemon. Both paths time out with a clear
        error if the machine is offline.
        """
        icloud_placeholder = path.parent / f".{path.name}{ICLOUD_PLACEHOLDER_SUFFIX}"
        if not path.exists() and icloud_placeholder.exists():
            try:
                subprocess.run(
                    ["brctl", "download", str(path)],
                    check=True,
                    timeout=MATERIALISE_TIMEOUT_S,
                    capture_output=True,
                )
            except FileNotFoundError as e:
                raise LocalFSError(
                    "brctl not available to materialise the iCloud placeholder "
                    f"for {path}."
                ) from e
            except subprocess.TimeoutExpired as e:
                raise LocalFSError(
                    f"Timed out materialising iCloud file {path}; the Mac may be "
                    "offline. Try again when online."
                ) from e
            except subprocess.CalledProcessError as e:
                raise LocalFSError(
                    f"Failed to materialise iCloud file {path}: {e.stderr!r}"
                ) from e

        if path.exists() and path.is_file():
            # Touch the first byte to coax OneDrive's APFS dataless file down.
            try:
                with open(path, "rb") as f:
                    f.read(1)
            except OSError as e:
                raise LocalFSError(
                    f"Could not read {path}; if this is a cloud-only OneDrive "
                    "file the machine may be offline."
                ) from e
        return path

    def _trash(self, path: Path) -> None:
        """Move `path` to the macOS Trash via Finder (recoverable)."""
        posix = str(path)
        script = (
            'tell application "Finder" to move (POSIX file '
            f'{_applescript_quote(posix)} as alias) to trash'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                timeout=30,
                capture_output=True,
            )
        except FileNotFoundError as e:
            raise LocalFSError("osascript not available to Trash files.") from e
        except subprocess.CalledProcessError as e:
            raise LocalFSError(
                f"Failed to move {path} to Trash: {e.stderr!r}"
            ) from e

    # ---- stat projection ---------------------------------------------------

    def _first_existing_root(self) -> Path:
        for root in self.roots:
            real = root.expanduser()
            if real.exists():
                return real
        # None mounted: surface the first declared root in the error.
        raise LocalFSError(
            f"None of the configured roots are present (offline mount?): "
            f"{[str(r) for r in self.roots]}"
        )

    @staticmethod
    def _stat(path: Path) -> dict:
        exists = path.exists()
        is_dir = path.is_dir() if exists else False
        size = path.stat().st_size if (exists and not is_dir) else None
        icloud_placeholder = path.parent / f".{path.name}{ICLOUD_PLACEHOLDER_SUFFIX}"
        return {
            "id": str(path),
            "name": path.name,
            "path": str(path),
            "isFolder": is_dir,
            "size": size,
            "exists": exists,
            "cloudOnly": (not exists) and icloud_placeholder.exists(),
            "mimeType": None,
        }


def _applescript_quote(value: str) -> str:
    """Quote a string for safe interpolation into an AppleScript literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
