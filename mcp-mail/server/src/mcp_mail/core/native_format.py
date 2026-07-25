"""Google native-format export/import mapper (spec section 6).

Native Docs / Sheets / Slides have no byte stream: the on-disk ``.gsheet`` is a
4-line JSON pointer, which is the exact wall that blocked the gym-log edit. So
``drive_read`` and ``drive_update`` must special-case the native mime types
instead of returning that pointer.

This module is pure logic (a mime -> handler table plus a couple of helpers) so
it is cheap to unit test and carries no Drive client. The Drive adapter consults
it to decide how to read or refuse-to-write each file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Google native mime types.
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES = "application/vnd.google-apps.presentation"
GOOGLE_FOLDER = "application/vnd.google-apps.folder"

# Read strategy for a given native mime type.
#   "export"      -> Drive files.export to the chosen export mime; bytes returned.
#   "route_sheet" -> not exported for editing; caller routed to sheet_* tools.
#                    (drive_read may still export a CSV/xlsx snapshot for a glance.)
#   "binary"      -> a normal binary/text file; download via files.get?alt=media.
ReadStrategy = Literal["export", "route_sheet", "binary"]


@dataclass(frozen=True)
class NativeHandler:
    mime: str
    read_strategy: ReadStrategy
    # The export mime to request from Drive files.export when read_strategy is
    # "export" (Docs -> markdown/plain text) or for the read-only snapshot of a
    # Sheet ("route_sheet" still names a snapshot mime for drive_read glances).
    export_mime: str | None
    # Whether drive_update can write raw bytes to this type. Native Docs/Sheets/
    # Slides cannot be byte-written; Sheets must go through sheet_* and Docs are
    # out of scope for cell-level writes in v0.1.
    byte_writable: bool


# The mime -> handler map. The Drive adapter degrades predictably off this table
# instead of handing back a 4-line JSON pointer (the field-observed failure).
_HANDLERS: dict[str, NativeHandler] = {
    GOOGLE_DOC: NativeHandler(
        mime=GOOGLE_DOC,
        read_strategy="export",
        export_mime="text/markdown",
        byte_writable=False,
    ),
    GOOGLE_SHEET: NativeHandler(
        mime=GOOGLE_SHEET,
        read_strategy="route_sheet",
        export_mime="text/csv",
        byte_writable=False,
    ),
    GOOGLE_SLIDES: NativeHandler(
        mime=GOOGLE_SLIDES,
        read_strategy="export",
        export_mime="text/plain",
        byte_writable=False,
    ),
}


def is_google_native(mime: str | None) -> bool:
    """True for any ``application/vnd.google-apps.*`` mime (incl. folders)."""
    return bool(mime) and mime.startswith("application/vnd.google-apps")


def is_folder(mime: str | None) -> bool:
    return mime == GOOGLE_FOLDER


def handler_for(mime: str | None) -> NativeHandler | None:
    """Return the native handler for `mime`, or None for a plain binary file."""
    if not mime:
        return None
    return _HANDLERS.get(mime)


def read_plan(mime: str | None) -> NativeHandler:
    """Resolve how ``drive_read`` should fetch a file of this mime.

    A non-native (or unknown) mime maps to a synthetic "binary" handler so the
    caller has a single, total function to dispatch on.
    """
    handler = handler_for(mime)
    if handler is not None:
        return handler
    return NativeHandler(
        mime=mime or "application/octet-stream",
        read_strategy="binary",
        export_mime=None,
        byte_writable=True,
    )


def assert_byte_writable(mime: str | None) -> None:
    """Raise a clear error if ``drive_update`` is asked to byte-write a native type.

    Sheets are redirected to ``sheet_write`` / ``sheet_append``; Docs/Slides
    cell-level writes are out of scope for v0.1 (read-only export is enough).
    """
    handler = handler_for(mime)
    if handler is not None and not handler.byte_writable:
        if handler.mime == GOOGLE_SHEET:
            raise ValueError(
                "Cannot byte-write a Google Sheet via drive_update. Use sheet_write "
                "/ sheet_append / sheet_batch_update, which edit cells through the "
                "Sheets API (there is no '.gsheet blob' to overwrite)."
            )
        raise ValueError(
            f"Cannot byte-write Google native type {handler.mime!r} via drive_update. "
            "Native Docs/Slides are read-only (export) in v0.1."
        )
