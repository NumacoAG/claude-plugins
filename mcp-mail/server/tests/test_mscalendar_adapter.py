"""HTTP mapping tests for the Graph calendar adapter (GraphCalendarAdapter).

Style mirrors test_drive_shared_scope: construct the real adapter, swap its
httpx client for a recorder, and monkeypatch the header builder so no Keychain /
MSAL is touched. Each test inspects the captured request (url, params, json
body) or the projected return, pinning the Google -> Graph field mapping, the
calendarView recurrence-expansion branch, and the notify-driven delete path
(cancel vs DELETE) that stands in for Google's absent sendUpdates parameter.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_mail.adapters.mscalendar import DEFAULT_TZ, GraphCalendarAdapter


class _FakeAccount:
    id = "work-m365"


class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` the adapter consumes."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingClient:
    """Captures every request (url, params, json body) and routes a canned
    payload back by method + relative path so the adapter's projection runs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # Per-test overridable canned responses.
        self.event: dict[str, Any] = {"id": "evt-1", "subject": "canned"}
        self.events_page: dict[str, Any] = {"value": []}
        self.calendars_page: dict[str, Any] = {"value": []}

    def _record(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": kwargs.get("params") or {},
                "json": kwargs.get("json"),
            }
        )
        if method == "GET" and url == "/me/calendars":
            return _FakeResponse(self.calendars_page)
        if method == "GET" and url in ("/me/events", "/me/calendarView"):
            return _FakeResponse(self.events_page)
        if method == "GET" and url.endswith("/calendarView"):
            return _FakeResponse(self.events_page)
        return _FakeResponse(self.event)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._record("DELETE", url, **kwargs)


@pytest.fixture
def cal(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GraphCalendarAdapter, _RecordingClient]:
    adapter = GraphCalendarAdapter(_FakeAccount())  # type: ignore[arg-type]
    client = _RecordingClient()
    adapter._client = client  # type: ignore[assignment]
    # Avoid touching Keychain / MSAL silent flow in the header builder.
    monkeypatch.setattr(
        adapter,
        "_calendar_headers",
        lambda content_type=None: {"Authorization": "Bearer test"},
    )
    return adapter, client


def _last(client: _RecordingClient, method: str) -> dict[str, Any]:
    matching = [c for c in client.calls if c["method"] == method]
    assert matching, f"no {method} request was recorded"
    return matching[-1]


# ---- create: Google-flat args -> Graph event resource -----------------------


def test_create_event_maps_fields_and_converts_offset_to_utc(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.create_event(
        "primary",
        summary="Sync",
        description="agenda",
        location="Room 1",
        attendees=["a@b.c", "d@e.f"],
        start="2026-07-09T14:00:00+02:00",
        end="2026-07-09T15:00:00+02:00",
    )
    call = _last(client, "POST")
    assert call["url"] == "/me/events"
    body = call["json"]
    assert body["subject"] == "Sync"
    assert body["body"] == {"contentType": "HTML", "content": "agenda"}
    assert body["location"] == {"displayName": "Room 1"}
    assert body["attendees"] == [
        {"emailAddress": {"address": "a@b.c"}, "type": "required"},
        {"emailAddress": {"address": "d@e.f"}, "type": "required"},
    ]
    # Offset carried, so the absolute instant is preserved by converting to UTC
    # (14:00+02:00 == 12:00Z) and labelling the Windows "UTC" zone id, NOT by
    # relabelling the 14:00 wall clock as Europe (which would store it 2h early).
    assert body["start"] == {"dateTime": "2026-07-09T12:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-07-09T13:00:00", "timeZone": "UTC"}


def test_create_event_z_input_preserves_instant(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.create_event(
        "primary",
        summary="UTC meeting",
        start="2026-07-09T12:00:00Z",
        end="2026-07-09T13:00:00Z",
    )
    body = _last(client, "POST")["json"]
    # A Z (UTC) input must store the SAME instant. The old adapter emitted
    # {dateTime: 12:00:00, timeZone: W. Europe}, which Graph reads as 10:00Z, 2h
    # early; the correct output keeps 12:00 under the "UTC" zone id.
    assert body["start"] == {"dateTime": "2026-07-09T12:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-07-09T13:00:00", "timeZone": "UTC"}


def test_create_event_negative_offset_converts_to_utc(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.create_event(
        "primary", summary="NY call", start="2026-01-15T09:00:00-05:00"
    )
    body = _last(client, "POST")["json"]
    # 09:00-05:00 == 14:00Z, and the date's own hyphens must not be read as the
    # offset sign.
    assert body["start"] == {"dateTime": "2026-01-15T14:00:00", "timeZone": "UTC"}


def test_create_event_naive_datetime_labelled_default_tz(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.create_event(
        "primary",
        summary="Floating",
        start="2026-07-09T14:00:00",
        end="2026-07-09T15:00:00",
    )
    body = _last(client, "POST")["json"]
    # No offset at all: a floating wall clock kept verbatim under the module
    # default zone, with no shift.
    assert body["start"] == {"dateTime": "2026-07-09T14:00:00", "timeZone": DEFAULT_TZ}
    assert body["end"] == {"dateTime": "2026-07-09T15:00:00", "timeZone": DEFAULT_TZ}


def test_create_all_day_sets_isallday_and_datetime(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.create_event("primary", summary="Trip", start="2026-07-09", end="2026-07-10")
    body = _last(client, "POST")["json"]
    assert body["isAllDay"] is True
    assert body["start"] == {"dateTime": "2026-07-09T00:00:00", "timeZone": DEFAULT_TZ}
    assert body["end"] == {"dateTime": "2026-07-10T00:00:00", "timeZone": DEFAULT_TZ}
    # No Google {date:...} shorthand leaks through.
    assert "date" not in body["start"]


# ---- list: calendarView expansion vs plain events ---------------------------


def test_list_events_with_bounds_hits_calendar_view(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.list_events(
        time_min="2026-07-01T00:00:00Z", time_max="2026-07-31T00:00:00Z"
    )
    call = _last(client, "GET")
    assert call["url"] == "/me/calendarView"
    assert call["params"]["startDateTime"] == "2026-07-01T00:00:00Z"
    assert call["params"]["endDateTime"] == "2026-07-31T00:00:00Z"


def test_list_events_named_calendar_with_bounds(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.list_events(calendar_id="cal-9", time_min="2026-07-01T00:00:00Z")
    call = _last(client, "GET")
    assert call["url"] == "/me/calendars/cal-9/calendarView"
    # An absent upper bound is defaulted so the required param is always present.
    assert call["params"]["endDateTime"]


def test_list_events_without_bounds_expands_via_calendar_view(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.list_events()
    call = _last(client, "GET")
    # A bare list must still expand recurring occurrences (Google parity:
    # singleEvents=True), so it routes to calendarView with wide default bounds,
    # never to /me/events (which returns unexpanded series masters).
    assert call["url"] == "/me/calendarView"
    assert call["params"]["startDateTime"] == "1970-01-01T00:00:00Z"
    assert call["params"]["endDateTime"] == "2999-12-31T00:00:00Z"
    assert call["params"]["$orderby"] == "start/dateTime"


def test_list_events_search_without_bounds_hits_events(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    adapter.list_events(query="budget")
    call = _last(client, "GET")
    # A windowless text search uses /me/events + $search; $search conflicts with
    # $orderby on Graph, so the order is dropped.
    assert call["url"] == "/me/events"
    assert call["params"]["$search"] == '"budget"'
    assert "$orderby" not in call["params"]


def test_list_events_query_with_bounds_filters_client_side(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    client.events_page = {
        "value": [
            {"id": "1", "subject": "Budget review"},
            {"id": "2", "subject": "Lunch"},
            {"id": "3", "subject": "team budget sync"},
        ]
    }
    out = adapter.list_events(
        query="budget",
        time_min="2026-07-01T00:00:00Z",
        time_max="2026-07-31T00:00:00Z",
    )
    call = _last(client, "GET")
    # A text search WITHIN a window rides calendarView (calendarView rejects
    # $search) and is filtered client-side, so combined search+range does not
    # 400 the way $search on calendarView would.
    assert call["url"] == "/me/calendarView"
    assert "$search" not in call["params"]
    assert call["params"]["startDateTime"] == "2026-07-01T00:00:00Z"
    assert call["params"]["endDateTime"] == "2026-07-31T00:00:00Z"
    assert [e["id"] for e in out] == ["1", "3"]


# ---- list_calendars: Graph resource -> Google-ish shape ---------------------


def test_list_calendars_projects_google_shape(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    client.calendars_page = {
        "value": [
            {
                "id": "AAA",
                "name": "Calendar",
                "isDefaultCalendar": True,
                "canEdit": True,
                "owner": {"name": "Owner", "address": "you@example.com"},
            },
            {"id": "BBB", "name": "Team", "isDefaultCalendar": False, "canEdit": False},
        ]
    }
    out = adapter.list_calendars()
    # Same key set as the Google adapter (id / summary / primary / accessRole /
    # timeZone); raw Graph keys (name / isDefaultCalendar / canEdit / owner) are
    # not leaked.
    assert out[0] == {
        "id": "AAA",
        "summary": "Calendar",
        "primary": True,
        "accessRole": "writer",
        "timeZone": None,
    }
    assert out[1] == {
        "id": "BBB",
        "summary": "Team",
        "primary": False,
        "accessRole": "reader",
        "timeZone": None,
    }


# ---- delete: notify drives cancel vs DELETE ---------------------------------


def test_delete_notify_true_posts_cancel(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    out = adapter.delete_event("evt1", notify=True)
    call = _last(client, "POST")
    assert call["url"] == "/me/events/evt1/cancel"
    assert out == {"event_id": "evt1", "deleted": True}


def test_delete_notify_false_deletes(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    out = adapter.delete_event("evt1", notify=False)
    call = _last(client, "DELETE")
    assert call["url"] == "/me/events/evt1"
    assert out == {"event_id": "evt1", "deleted": True}


# ---- projection: Graph resource -> common shape -----------------------------


_GRAPH_MEETING = {
    "id": "AAMkMeeting",
    "subject": "Weekly sync",
    "body": {"contentType": "html", "content": "<p>agenda</p>"},
    "location": {"displayName": "Room 1"},
    "start": {"dateTime": "2026-07-09T14:00:00.0000000", "timeZone": DEFAULT_TZ},
    "end": {"dateTime": "2026-07-09T15:00:00.0000000", "timeZone": DEFAULT_TZ},
    "isCancelled": False,
    "showAs": "busy",
    "webLink": "https://outlook.office365.com/owa/evt",
    "organizer": {"emailAddress": {"name": "Owner", "address": "you@example.com"}},
    "attendees": [
        {"emailAddress": {"address": "a@b.c"}, "status": {"response": "tentativelyAccepted"}},
        {"emailAddress": {"address": "d@e.f"}, "status": {"response": "notResponded"}},
        {"emailAddress": {"address": "g@h.i"}, "status": {"response": "accepted"}},
    ],
}


def test_project_event_maps_meeting() -> None:
    proj = GraphCalendarAdapter._project_event(_GRAPH_MEETING)
    assert proj["id"] == "AAMkMeeting"
    assert proj["summary"] == "Weekly sync"
    assert proj["description"] == "<p>agenda</p>"
    assert proj["location"] == "Room 1"
    assert proj["status"] == "confirmed"
    assert proj["htmlLink"] == "https://outlook.office365.com/owa/evt"
    assert proj["organizer"] == "you@example.com"
    assert proj["start"] == _GRAPH_MEETING["start"]
    assert [a["email"] for a in proj["attendees"]] == ["a@b.c", "d@e.f", "g@h.i"]
    # Response enums normalized to Google spellings; unknown passes through.
    assert proj["attendees"][0]["responseStatus"] == "tentative"
    assert proj["attendees"][1]["responseStatus"] == "needsAction"
    assert proj["attendees"][2]["responseStatus"] == "accepted"


def test_project_event_status_derivation() -> None:
    assert GraphCalendarAdapter._project_event({"isCancelled": True})["status"] == "cancelled"
    assert GraphCalendarAdapter._project_event({"showAs": "tentative"})["status"] == "tentative"
    assert GraphCalendarAdapter._project_event({"subject": "x"})["status"] == "confirmed"


def test_project_event_solo_has_empty_attendee_list() -> None:
    proj = GraphCalendarAdapter._project_event({"id": "e", "subject": "PT session"})
    assert proj["attendees"] == []
    assert proj["id"] == "e"
    assert proj["summary"] == "PT session"


def test_project_event_null_organizer_email_is_safe() -> None:
    # A present organizer whose emailAddress is explicitly null must degrade to
    # None, not raise AttributeError.
    proj = GraphCalendarAdapter._project_event(
        {"id": "e", "subject": "x", "organizer": {"emailAddress": None}}
    )
    assert proj["organizer"] is None


# ---- attendee detection drives the gate -------------------------------------


def test_fields_have_attendees() -> None:
    assert GraphCalendarAdapter.fields_have_attendees({"attendees": ["a@b.c"]}) is True
    assert GraphCalendarAdapter.fields_have_attendees({"summary": "solo"}) is False
    assert GraphCalendarAdapter.fields_have_attendees({"attendees": []}) is False


def test_event_has_attendees_hits_backend(
    cal: tuple[GraphCalendarAdapter, _RecordingClient],
) -> None:
    adapter, client = cal
    client.event = {
        "id": "m1",
        "subject": "Meeting",
        "attendees": [
            {"emailAddress": {"address": "a@b.c"}, "status": {"response": "none"}}
        ],
    }
    assert adapter.event_has_attendees("m1") is True
    assert _last(client, "GET")["url"] == "/me/events/m1"

    client.event = {"id": "s1", "subject": "Solo"}
    assert adapter.event_has_attendees("s1") is False
