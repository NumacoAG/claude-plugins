"""Shared recipient-filtering helper for threaded replies.

Imported by the Graph, Gmail, and IMAP adapters so that adding extra ``cc`` /
``bcc`` addresses to a reply behaves identically everywhere. Keeping this in one
module (rather than three copy-pasted definitions) makes "identical semantics"
real: a fix to normalization or dedupe lands once for all three adapters.
"""

from __future__ import annotations

from email.utils import parseaddr


def _bare_address(value: str | None) -> str | None:
    """Return the bare ``addr@host`` from a possibly display-name-formed string.

    A display-name form (``Name <addr@host>``) resolves to the bare address; a
    bare address is returned unchanged, with its case preserved. Returns ``None``
    for empty or unparseable input.
    """
    if not value:
        return None
    _, addr = parseaddr(value)
    return addr or None


def _extra_recipients(
    addrs: list[str] | None,
    exclude: set[str],
    already: set[str] | None = None,
) -> list[str]:
    """Filter ``addrs`` down to genuinely new recipients.

    Each address is normalized to its bare ``addr@host`` form BEFORE it is
    compared or stored, so a display-name-form extra (``"Name <addr>"``) is
    excluded / deduped by its address rather than sneaking past the string
    comparison. Drops any address whose lowercase bare form is in ``exclude``
    (e.g. the account's own address and the original sender) or ``already``
    (addresses that are already recipients), and collapses case-insensitive
    duplicates while preserving order. ``exclude`` and ``already`` are expected
    to hold bare, lowercased addresses.
    """
    seen = set(already or set())
    out: list[str] = []
    for a in addrs or []:
        bare = _bare_address(a)
        if not bare:
            continue
        al = bare.lower()
        if al in exclude or al in seen:
            continue
        seen.add(al)
        out.append(bare)
    return out
