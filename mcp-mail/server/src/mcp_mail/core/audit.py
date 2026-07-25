"""Append-only audit log of every write / move / delete / share (spec section 10).

One JSON object per line (JSONL), appended under
``~/.local/state/mcp-mail/audit.log`` by default. The log is append-only by
construction: we open in append mode and never truncate or rewrite. Each record
carries the account id, the operation, the ref(s) involved, a free-form detail
dict, and a UTC timestamp, so an after-the-fact review can reconstruct exactly
what the server changed and where.

Writing the audit record must never crash the underlying operation, so failures
here are swallowed (best effort) after the real op has already succeeded; the
log is a safety aid, not a transactional dependency.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_PATH = (
    Path(os.environ.get("MCP_MAIL_AUDIT_LOG", ""))
    if os.environ.get("MCP_MAIL_AUDIT_LOG")
    else Path.home() / ".local" / "state" / "mcp-mail" / "audit.log"
)


def record(
    op: str,
    account: str,
    ref: str | None = None,
    *,
    detail: dict[str, Any] | None = None,
    path: Path | None = None,
) -> None:
    """Append one audit record. Best effort: never raises to the caller.

    `op` is the tool name (e.g. "drive_delete", "sheet_write", "drive_share").
    `account` is the account id. `ref` is the primary target (file id, path,
    spreadsheet id, event id). `detail` carries op-specific extras (destination
    of a move, the principal/role of a share, the range of a sheet write).
    """
    log_path = path or DEFAULT_AUDIT_PATH
    rec = {
        "ts": datetime.now(UTC).isoformat(),
        "op": op,
        "account": account,
        "ref": ref,
        "detail": detail or {},
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        # The audit log is a safety aid layered on top of an already-completed
        # operation; a logging failure must not surface as an op failure.
        pass


def read_all(path: Path | None = None) -> list[dict[str, Any]]:
    """Read every audit record back (used by tests and ad-hoc review)."""
    log_path = path or DEFAULT_AUDIT_PATH
    if not log_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
