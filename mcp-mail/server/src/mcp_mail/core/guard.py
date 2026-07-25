"""The write guard and the outward-facing gate (spec section 10).

Two distinct rails, mirroring how the mail surface treats ``auto_send``:

1. **Per-account write guard.** Write / move / overwrite / delete honour the
   account's ``auto_write`` flag. When it is False the operation is refused at
   the server boundary with a clear, actionable error; reads never consult it.
   This is server-side enforcement, independent of any Claude Code allowlist.

2. **Outward-facing gate.** ``drive_share`` and attendee-bearing calendar
   writes are *always* surfaced for confirmation regardless of ``auto_write``,
   because they send something outward (a sharing grant, an invitation, a
   cancellation), exactly like ``mail_send``. The gate is realised the same way
   the mail surface realises send-confirmation: these tools are kept off the
   Claude Code allowlist so the per-call permission prompt always fires. This
   module documents and labels the requirement so the tool wiring stays honest;
   it does not itself pop a prompt (that is the MCP client's job).
"""

from __future__ import annotations

from ..config import Account


class WriteGuardError(PermissionError):
    """Raised when a write/move/delete is attempted on an ``auto_write=false`` account."""


def require_auto_write(account: Account, op: str) -> None:
    """Refuse a destructive op unless the account opts into autonomous writes.

    `op` is a short verb used in the error message (e.g. "drive_update",
    "drive_delete", "sheet_write"). Outward-facing ops should NOT rely solely
    on this guard: they are gated by the per-call prompt as well (see
    ``is_outward_facing``).
    """
    if not getattr(account, "auto_write", False):
        raise WriteGuardError(
            f"{op} refused: account {account.id!r} has auto_write=false. "
            f"This guards write / move / overwrite / delete against autonomous "
            f"edits. Set auto_write=true for {account.id!r} in accounts.toml to "
            f"allow it, or perform the change manually."
        )


# Tools that send something outward and therefore always require the per-call
# confirmation prompt, independent of auto_write. Kept here as the single source
# of truth so the server wiring and the docs cannot drift apart.
OUTWARD_FACING_TOOLS = frozenset({"drive_share"})


def is_outward_facing(tool_name: str, *, has_attendees: bool = False) -> bool:
    """True if `tool_name` is outward-facing for this call.

    ``drive_share`` is always outward-facing. Calendar create/update/delete are
    outward-facing only when the event carries attendees (a solo personal event
    sends no invitation), so the caller passes ``has_attendees``.
    """
    if tool_name in OUTWARD_FACING_TOOLS:
        return True
    if tool_name in {"cal_create_event", "cal_update_event", "cal_delete_event"}:
        return has_attendees
    return False
