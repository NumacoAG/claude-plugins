"""Tests for the server-side attendee gate on calendar writes (spec section 4.3).

The gate is enforced in the server dispatch, independent of any Claude Code
allowlist: a solo event proceeds ungated, an attendee event is refused unless
confirmed=true, and update/delete fetch the stored event so a patch that omits
attendees still gates (and still notifies existing guests).

The tests drive ``call_tool`` with a fake calendar adapter so no network or
Keychain is touched; the fake records what the dispatch asked of it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import mcp_mail.server as srv
from mcp_mail.adapters.gcalendar import GoogleCalendarAdapter
from mcp_mail.adapters.mscalendar import GraphCalendarAdapter
from mcp_mail.config import M365Account
from mcp_mail.core import audit


class FakeCalendar:
    """Records calls; mirrors the adapter surface the dispatch uses.

    `stored_attendees` controls what ``event_has_attendees`` reports, so the
    update/delete fetch path can be exercised for both solo and attendee events.
    Attendee detection reuses the real static helper so the test pins the actual
    logic, not a re-implementation.
    """

    def __init__(self, stored_attendees: bool = False) -> None:
        self.stored_attendees = stored_attendees
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[dict] = []

    def fields_have_attendees(self, fields: dict[str, Any]) -> bool:
        return GoogleCalendarAdapter.fields_have_attendees(fields)

    def event_has_attendees(self, event_id: str, calendar_id: str = "primary") -> bool:
        return self.stored_attendees

    def create_event(self, calendar_id: str = "primary", **fields: Any) -> dict:
        self.created.append({"calendar_id": calendar_id, "fields": fields})
        return {"id": "evt-new", "summary": fields.get("summary")}

    def update_event(
        self, event_id: str, calendar_id: str = "primary",
        notify: bool | None = None, **fields: Any,
    ) -> dict:
        self.updated.append({"event_id": event_id, "notify": notify, "fields": fields})
        return {"id": event_id}

    def delete_event(
        self, event_id: str, calendar_id: str = "primary", notify: bool | None = None
    ) -> dict:
        self.deleted.append({"event_id": event_id, "notify": notify})
        return {"event_id": event_id, "deleted": True}


def _call(name: str, arguments: dict[str, Any]) -> dict:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


class _FakeAccount:
    id = "g"


@pytest.fixture
def patch_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path):
    # Keep the audit log out of the real home dir during tests.
    monkeypatch.setattr(audit, "DEFAULT_AUDIT_PATH", tmp_path / "audit.log")

    def _install(fake: FakeCalendar) -> FakeCalendar:
        monkeypatch.setattr(
            srv, "_get_calendar_adapter", lambda account_id: (_FakeAccount(), fake)
        )
        return fake

    return _install


# ---- create -----------------------------------------------------------------


def test_solo_create_proceeds_ungated(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar())
    out = _call("cal_create_event", {
        "account": "g", "summary": "PT session",
        "start": "2026-06-26T09:00:00Z", "end": "2026-06-26T10:00:00Z",
    })
    assert out.get("id") == "evt-new"
    assert len(fake.created) == 1
    assert "confirmed" not in fake.created[0]["fields"]


def test_attendee_create_refused_without_confirm(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar())
    out = _call("cal_create_event", {
        "account": "g", "summary": "Sync",
        "start": "2026-06-26T09:00:00Z", "end": "2026-06-26T10:00:00Z",
        "attendees": ["a@b.c"],
    })
    assert out["gated"] is True
    assert out["ok"] is False
    assert not fake.created  # no write happened


def test_attendee_create_proceeds_with_confirm(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar())
    out = _call("cal_create_event", {
        "account": "g", "summary": "Sync",
        "start": "2026-06-26T09:00:00Z", "end": "2026-06-26T10:00:00Z",
        "attendees": ["a@b.c"], "confirmed": True,
    })
    assert out.get("id") == "evt-new"
    assert len(fake.created) == 1
    # `confirmed` must not leak into the event fields.
    assert "confirmed" not in fake.created[0]["fields"]
    assert fake.created[0]["fields"]["attendees"] == ["a@b.c"]


# ---- update -----------------------------------------------------------------


def test_solo_update_proceeds_ungated(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar(stored_attendees=False))
    out = _call("cal_update_event", {
        "account": "g", "event_id": "e1", "location": "Room 2",
    })
    assert out.get("id") == "e1"
    assert len(fake.updated) == 1
    assert fake.updated[0]["notify"] is False


def test_update_gated_when_stored_event_has_attendees(patch_adapter) -> None:
    # Patch omits attendees, but the stored event has guests: must gate.
    fake = patch_adapter(FakeCalendar(stored_attendees=True))
    out = _call("cal_update_event", {
        "account": "g", "event_id": "e1", "location": "Room 9",
    })
    assert out["gated"] is True
    assert not fake.updated


def test_update_attendee_event_notifies_existing_guests(patch_adapter) -> None:
    # Confirmed update of an attendee event: proceeds AND notifies (notify=True)
    # even though the patch itself carries no attendees.
    fake = patch_adapter(FakeCalendar(stored_attendees=True))
    out = _call("cal_update_event", {
        "account": "g", "event_id": "e1", "location": "Room 9", "confirmed": True,
    })
    assert out.get("id") == "e1"
    assert len(fake.updated) == 1
    assert fake.updated[0]["notify"] is True


# ---- delete -----------------------------------------------------------------


def test_solo_delete_proceeds_ungated(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar(stored_attendees=False))
    out = _call("cal_delete_event", {"account": "g", "event_id": "e1"})
    assert out.get("deleted") is True
    assert len(fake.deleted) == 1
    assert fake.deleted[0]["notify"] is False


def test_attendee_delete_refused_without_confirm(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar(stored_attendees=True))
    out = _call("cal_delete_event", {"account": "g", "event_id": "e1"})
    assert out["gated"] is True
    assert not fake.deleted


def test_attendee_delete_proceeds_with_confirm_and_notifies(patch_adapter) -> None:
    fake = patch_adapter(FakeCalendar(stored_attendees=True))
    out = _call("cal_delete_event", {"account": "g", "event_id": "e1", "confirmed": True})
    assert out.get("deleted") is True
    assert len(fake.deleted) == 1
    assert fake.deleted[0]["notify"] is True


# ---- provider dispatch (M365 parity) ----------------------------------------
#
# The gate above is provider-agnostic (it drives whatever adapter the dispatch
# returns), so these pin only the routing: an m365 account reaches the Graph
# calendar backend, and the capability guard still refuses m365 accounts that do
# not declare "calendar". Constructing GraphCalendarAdapter touches no network
# or Keychain (auth is per-call), so no monkeypatching of the token is needed.


def _m365_account(capabilities: tuple[str, ...]) -> M365Account:
    return M365Account(
        id="work-m365",
        provider="m365",
        address="you@example.com",
        client_id="cid",
        tenant_id="tid",
        keychain_service="mcp-mail",
        keychain_user="work-m365",
        auto_send=False,
        capabilities=capabilities,
    )


def test_m365_routes_to_graph_calendar_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    acct = _m365_account(("mail", "drive", "calendar"))
    monkeypatch.setattr(srv, "get_account", lambda account_id: acct)
    got_acct, adapter = srv._get_calendar_adapter("work-m365")
    assert got_acct is acct
    assert isinstance(adapter, GraphCalendarAdapter)


def test_m365_without_calendar_capability_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    acct = _m365_account(("mail", "drive"))
    monkeypatch.setattr(srv, "get_account", lambda account_id: acct)
    with pytest.raises(ValueError, match="calendar"):
        srv._get_calendar_adapter("work-m365")
