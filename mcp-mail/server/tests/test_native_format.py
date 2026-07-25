"""Tests for the Google native-format mapper (spec section 6).

The mapper decides how ``drive_read`` fetches a file and whether ``drive_update``
may byte-write it, degrading predictably instead of returning the 4-line
``.gsheet`` JSON pointer that blocked the gym-log edit.
"""

from __future__ import annotations

import pytest

from mcp_mail.core import native_format as nf


def test_is_google_native() -> None:
    assert nf.is_google_native(nf.GOOGLE_DOC)
    assert nf.is_google_native(nf.GOOGLE_SHEET)
    assert nf.is_google_native(nf.GOOGLE_FOLDER)
    assert not nf.is_google_native("application/pdf")
    assert not nf.is_google_native(None)


def test_is_folder() -> None:
    assert nf.is_folder(nf.GOOGLE_FOLDER)
    assert not nf.is_folder(nf.GOOGLE_SHEET)


def test_doc_reads_via_export_markdown() -> None:
    plan = nf.read_plan(nf.GOOGLE_DOC)
    assert plan.read_strategy == "export"
    assert plan.export_mime == "text/markdown"
    assert plan.byte_writable is False


def test_sheet_routes_to_sheet_tools() -> None:
    plan = nf.read_plan(nf.GOOGLE_SHEET)
    assert plan.read_strategy == "route_sheet"
    assert plan.export_mime == "text/csv"
    assert plan.byte_writable is False


def test_slides_reads_via_export_text() -> None:
    plan = nf.read_plan(nf.GOOGLE_SLIDES)
    assert plan.read_strategy == "export"
    assert plan.byte_writable is False


def test_binary_file_is_byte_path() -> None:
    plan = nf.read_plan("application/pdf")
    assert plan.read_strategy == "binary"
    assert plan.byte_writable is True
    assert plan.export_mime is None


def test_unknown_mime_treated_as_binary() -> None:
    plan = nf.read_plan(None)
    assert plan.read_strategy == "binary"
    assert plan.byte_writable is True


def test_assert_byte_writable_allows_binary() -> None:
    # Should not raise for a regular file.
    nf.assert_byte_writable("text/plain")
    nf.assert_byte_writable("application/pdf")
    nf.assert_byte_writable(None)


def test_assert_byte_writable_blocks_sheet_with_routing_message() -> None:
    with pytest.raises(ValueError, match="sheet_write"):
        nf.assert_byte_writable(nf.GOOGLE_SHEET)


def test_assert_byte_writable_blocks_doc() -> None:
    with pytest.raises(ValueError, match="read-only"):
        nf.assert_byte_writable(nf.GOOGLE_DOC)


def test_handler_for_returns_none_for_binary() -> None:
    assert nf.handler_for("application/pdf") is None
    assert nf.handler_for(None) is None
    assert nf.handler_for(nf.GOOGLE_SHEET) is not None
