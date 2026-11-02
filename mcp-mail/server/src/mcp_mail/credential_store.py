"""Keep large Microsoft token caches entirely in the OS credential store.

Windows Generic Credentials have a 2560-byte blob limit and keyring stores
strings as UTF-16. Read the v1 chunks used by earlier local installations and
publish new chunks through a generation-specific manifest, so a failed refresh
cannot overwrite the previously usable cache. Other platforms keep plain values.
"""

from __future__ import annotations

import hashlib
import re
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass

import keyring
from keyring.errors import KeyringError

_V1 = "mcp-mail-chunked-v1:"
_V2 = "mcp-mail-chunked-v2:"
_CHUNK_BYTES = 2000
_MAX_CHUNKS = 4096


@dataclass(frozen=True)
class _Manifest:
    count: int
    digest: str
    generation: str | None = None

    def username(self, owner: str, index: int) -> str:
        if self.generation is None:
            return f"{owner}.__mcp_mail_chunk_{index:04d}"
        return f"{owner}.__mcp_mail_chunk_{self.generation}_{index:04d}"


def _parse(value: str | None) -> _Manifest | None:
    if not value or not value.startswith((_V1, _V2)):
        return None
    generation = None
    try:
        if value.startswith(_V1):
            count_text, digest = value[len(_V1) :].split(":")
        else:
            generation, count_text, digest = value[len(_V2) :].split(":")
            if not re.fullmatch(r"[0-9a-f]{32}", generation):
                raise ValueError
        count = int(count_text)
        if not 1 <= count <= _MAX_CHUNKS or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError
    except ValueError:
        raise RuntimeError(
            "Invalid chunked credential manifest in the OS credential store."
        ) from None
    return _Manifest(count, digest, generation)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read(service: str, username: str, manifest: _Manifest) -> str:
    pieces = []
    for index in range(manifest.count):
        piece = keyring.get_password(service, manifest.username(username, index))
        if piece is None:
            raise RuntimeError("A token-cache chunk is missing from the OS credential store.")
        pieces.append(piece)
    value = "".join(pieces)
    if _digest(value) != manifest.digest:
        raise RuntimeError("Token-cache checksum validation failed in the OS credential store.")
    return value


def get_secret(service: str, username: str) -> str | None:
    for _ in range(3):
        stored = keyring.get_password(service, username)
        try:
            manifest = _parse(stored)
            return _read(service, username, manifest) if manifest else stored
        except RuntimeError:
            # Another process may have replaced the manifest and cleaned up its
            # old chunks while this read was in progress. Retry only on change.
            if keyring.get_password(service, username) == stored:
                raise
    raise RuntimeError("Token cache changed repeatedly while reading the OS credential store.")


def _pieces(value: str) -> list[str]:
    pieces = []
    start = size = 0
    for index, char in enumerate(value):
        width = len(char.encode("utf-16-le"))
        if size + width > _CHUNK_BYTES:
            pieces.append(value[start:index])
            start, size = index, 0
        size += width
    pieces.append(value[start:])
    return pieces


def _cleanup(service: str, username: str, manifest: _Manifest) -> None:
    # Cleanup cannot invalidate a successfully published cache. A later
    # credential-store maintenance pass can remove an orphaned chunk.
    for index in range(manifest.count):
        with suppress(KeyringError):
            keyring.delete_password(service, manifest.username(username, index))


def set_secret(service: str, username: str, value: str) -> None:
    previous = _parse(keyring.get_password(service, username))
    if sys.platform != "win32" or len(value.encode("utf-16-le")) <= _CHUNK_BYTES:
        keyring.set_password(service, username, value)
    else:
        pieces = _pieces(value)
        if len(pieces) > _MAX_CHUNKS:
            raise ValueError("Token cache is too large for chunked credential storage.")
        pending = _Manifest(len(pieces), _digest(value), uuid.uuid4().hex)
        written = 0
        try:
            for index, piece in enumerate(pieces):
                keyring.set_password(service, pending.username(username, index), piece)
                written += 1
            keyring.set_password(
                service,
                username,
                f"{_V2}{pending.generation}:{pending.count}:{pending.digest}",
            )
        except Exception:
            _cleanup(service, username, _Manifest(written, pending.digest, pending.generation))
            raise
    if previous:
        _cleanup(service, username, previous)
