"""Google Calendar v3 adapter.

Reuses the same Google OAuth client and Keychain token as the Gmail and Drive
adapters (the ``calendar`` scope is unioned into ``gmail.SCOPES``). The
attendee gate from spec section 4.3 lives at the server boundary, not here:
creating / updating / deleting an event with guests sends invitations and
cancellations, which is outward-facing exactly like ``mail_send`` and so always
fires the per-call confirmation prompt. Solo events (the PT-style personal
entries) carry no attendees and are not gated. This adapter only knows how to
talk to the API and how to detect whether a given event payload has attendees.
"""

from __future__ import annotations

from typing import Any

import httpx

from .gmail import acquire_credentials
from ..config import GmailAccount

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarAdapter:
    """Google Calendar adapter. Auth refreshed per-call via google-auth."""

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._client = httpx.Client(timeout=60.0)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        creds = acquire_credentials(self.account)
        h = {"Authorization": f"Bearer {creds.token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- read --------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        resp = self._client.get(
            f"{CALENDAR_BASE}/users/me/calendarList",
            headers=self._headers(),
            params={"fields": "items(id,summary,primary,accessRole,timeZone)"},
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        params: dict[str, str | int | bool] = {
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": min(limit, 250),
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query
        resp = self._client.get(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return [self._project_event(e) for e in resp.json().get("items", [])]

    def get_event(self, event_id: str, calendar_id: str = "primary") -> dict:
        resp = self._client.get(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return self._project_event(resp.json())

    # ---- write -------------------------------------------------------------

    def create_event(self, calendar_id: str = "primary", **fields: Any) -> dict:
        body = self._build_event_body(fields)
        send_updates = "all" if body.get("attendees") else "none"
        resp = self._client.post(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events",
            headers=self._headers(content_type="application/json"),
            params={"sendUpdates": send_updates},
            json=body,
        )
        resp.raise_for_status()
        return self._project_event(resp.json())

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        notify: bool | None = None,
        **fields: Any,
    ) -> dict:
        body = self._build_event_body(fields)
        # Notify guests when this is an attendee-bearing change. `notify` lets
        # the server decide based on the STORED event (a patch that omits
        # attendees must still notify existing guests of a real change); when
        # not given, fall back to whether the patch itself carries attendees.
        should_notify = bool(body.get("attendees")) if notify is None else notify
        resp = self._client.patch(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(content_type="application/json"),
            params={"sendUpdates": "all" if should_notify else "none"},
            json=body,
        )
        resp.raise_for_status()
        return self._project_event(resp.json())

    def delete_event(
        self, event_id: str, calendar_id: str = "primary", notify: bool | None = None
    ) -> dict:
        # Cancellations notify guests only when the event had attendees; `notify`
        # carries the server's determination (a solo event needs no cancellation
        # notice and must not over-prompt the API).
        should_notify = True if notify is None else notify
        resp = self._client.delete(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
            params={"sendUpdates": "all" if should_notify else "none"},
        )
        resp.raise_for_status()
        return {"event_id": event_id, "deleted": True}

    # ---- attendee detection (drives the gate) ------------------------------

    def event_has_attendees(self, event_id: str, calendar_id: str = "primary") -> bool:
        """True if the stored event has guests (so update/delete must be gated)."""
        ev = self.get_event(event_id, calendar_id)
        return bool(ev.get("attendees"))

    @staticmethod
    def fields_have_attendees(fields: dict[str, Any]) -> bool:
        """True if a create/update payload carries attendees (so it must be gated)."""
        attendees = fields.get("attendees")
        return bool(attendees)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _build_event_body(fields: dict[str, Any]) -> dict[str, Any]:
        """Translate flat tool args into a Calendar event resource.

        Accepts: summary, description, location, start, end (RFC3339 strings or
        date strings), attendees (list of email strings), and any already-shaped
        keys passed through verbatim.
        """
        body: dict[str, Any] = {}
        for key in ("summary", "description", "location"):
            if fields.get(key) is not None:
                body[key] = fields[key]
        for key in ("start", "end"):
            val = fields.get(key)
            if val is None:
                continue
            if isinstance(val, dict):
                body[key] = val
            elif "T" in val:
                body[key] = {"dateTime": val}
            else:
                body[key] = {"date": val}
        attendees = fields.get("attendees")
        if attendees:
            body["attendees"] = [
                a if isinstance(a, dict) else {"email": a} for a in attendees
            ]
        return body

    @staticmethod
    def _project_event(e: dict) -> dict:
        return {
            "id": e.get("id"),
            "summary": e.get("summary"),
            "description": e.get("description"),
            "location": e.get("location"),
            "start": e.get("start"),
            "end": e.get("end"),
            "status": e.get("status"),
            "attendees": [
                {"email": a.get("email"), "responseStatus": a.get("responseStatus")}
                for a in e.get("attendees") or []
            ],
            "htmlLink": e.get("htmlLink"),
            "organizer": (e.get("organizer") or {}).get("email"),
        }
