"""Cross-cutting helpers shared by the drive / sheets / calendar adapters.

These modules implement the safety rails from the expansion spec section 10:

- ``sandbox``: the hard path sandbox for the localfs backend (reject ``..``
  traversal and symlink escape outside an account's ``roots``).
- ``guard``: the destructive-op guard reading per-account ``auto_write``, plus
  the always-on gate for outward-facing ops (sharing, attendee writes).
- ``audit``: the append-only audit log of every write / move / delete / share.
- ``native_format``: the Google native-format (Docs/Sheets/Slides) mime mapper.
"""

from __future__ import annotations
