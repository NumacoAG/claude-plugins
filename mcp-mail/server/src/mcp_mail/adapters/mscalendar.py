"""Microsoft Graph calendar adapter for M365 accounts.

Parity target is ``adapters/gcalendar.GoogleCalendarAdapter``: same method
surface, same projected event shape, same attendee gate at the server boundary.
Auth rides the same Keychain token as mail and files, but through a separate
calendar-scoped silent accessor (``acquire_calendar_token``) so the mail
surface's silent scope set is never widened (the file-scope precedent, auth.py).

Key divergence from Google to keep in mind everywhere here: Graph has no
``sendUpdates`` parameter. "Has attendees" is exactly "will send mail" is
exactly "outward-facing / gated"; notification is implicit. Graph auto-emails
invitations when you POST an attendee-bearing event and auto-sends a meeting
update when the organizer PATCHes one. To notify on delete you POST
``.../cancel``; to stay silent you DELETE. There is no way to keep attendees on
an event yet suppress the mail, so this adapter never tries.

Accepted parity gap (see the build brief's Risks): ``update_event`` carries a
``notify`` argument for signature symmetry with Google, but Graph offers no
suppression flag on PATCH. An organizer PATCH of an attendee-bearing event
always notifies, so ``notify=False`` cannot force silence the way Google's
``sendUpdates="none"`` can. The server gate still fires correctly (attendee
updates require confirmation), so the user always confirms before a notifying
update.

Body times use Windows timezone ids, NOT IANA (``Europe/Zurich``); Graph rejects
IANA names. An offset-bearing or ``Z`` datetime is converted to UTC and stored
under the Windows ``UTC`` zone id so the absolute instant is preserved (Graph
would otherwise reinterpret a bare wall clock in whatever zone we attach, which
silently shifts every UTC/Z input); a genuinely naive datetime (no offset) is a
floating wall clock kept under ``DEFAULT_TZ`` (the module default zone; change it for your own region). ``list_events``
reads through ``calendarView`` (which expands recurring occurrences, matching
Google's ``singleEvents=True``) for every call except a free-text search with no
date window, which uses ``/me/events`` + ``$search``; a text search WITHIN a
window rides calendarView and is filtered client-side, since calendarView
rejects ``$search``. ``calendarView`` requires ``startDateTime`` / ``endDateTime``,
which are interpreted by the offset embedded in their ISO value and are NOT
affected by the ``Prefer`` header; the caller's RFC3339 bounds pass straight
through.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ..auth import acquire_calendar_token
from ..config import M365Account

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_TZ = "W. Europe Standard Time"   # Windows tz id, NOT IANA


class GraphCalendarAdapter:
    """Graph calendar adapter. Auth refreshed per-call via MSAL silent flow."""

    supports_drive_attachments = False

    def __init__(self, account: M365Account) -> None:
        self.account = account
        self._client = httpx.Client(base_url=GRAPH_BASE, timeout=60.0)

    def _calendar_headers(self, content_type: str | None = None) -> dict[str, str]:
        token = acquire_calendar_token(self.account)
        h = {
            "Authorization": f"Bearer {token}",
            "Prefer": f'outlook.timezone="{DEFAULT_TZ}"',
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ---- read --------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        resp = self._client.get("/me/calendars", headers=self._calendar_headers())
        resp.raise_for_status()
        return [self._project_calendar(c) for c in resp.json().get("value", [])]

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        cap = min(limit, 250)
        # A free-text search with no date window uses /me/events + $search, the
        # one endpoint that does server-side text search across the whole
        # calendar (calendarView rejects $search). `query` is KQL-ish, not a
        # free-text `q`; $search and $orderby conflict on Graph, so no $orderby.
        if query and not (time_min or time_max):
            path = (
                "/me/events"
                if calendar_id in (None, "primary")
                else f"/me/calendars/{calendar_id}/events"
            )
            resp = self._client.get(
                path,
                headers=self._calendar_headers(),
                params={"$top": cap, "$search": f'"{query}"'},
            )
            resp.raise_for_status()
            return [self._project_event(e) for e in resp.json().get("value", [])]

        # Everything else reads through calendarView, which expands recurring
        # occurrences (the true equivalent of Google's singleEvents=True) so even
        # a bare list returns expanded, start-ordered occurrences rather than
        # unexpanded series masters. Its bounds are required and offset driven
        # (they ignore the Prefer header), so default any absent bound to a wide
        # range and pass the caller's RFC3339 values through.
        params: dict[str, str | int] = {
            "startDateTime": time_min or "1970-01-01T00:00:00Z",
            "endDateTime": time_max or "2999-12-31T00:00:00Z",
            "$orderby": "start/dateTime",
            # A query here is a text search WITHIN a window, which cannot ride
            # $search on calendarView; pull a full page and filter client-side.
            "$top": 250 if query else cap,
        }
        path = (
            "/me/calendarView"
            if calendar_id in (None, "primary")
            else f"/me/calendars/{calendar_id}/calendarView"
        )
        resp = self._client.get(path, headers=self._calendar_headers(), params=params)
        resp.raise_for_status()
        events = [self._project_event(e) for e in resp.json().get("value", [])]
        if query:
            # calendarView has no $search, so keep parity with Google's
            # q + timeMin + timeMax (one call returns text-matched events inside
            # the window) by substring-matching client-side, then re-cap.
            needle = query.lower()
            events = [e for e in events if _event_matches_query(e, needle)][:cap]
        return events

    def get_event(self, event_id: str, calendar_id: str = "primary") -> dict:
        path = (
            f"/me/events/{event_id}"
            if calendar_id in (None, "primary")
            else f"/me/calendars/{calendar_id}/events/{event_id}"
        )
        resp = self._client.get(path, headers=self._calendar_headers())
        resp.raise_for_status()
        return self._project_event(resp.json())

    # ---- write -------------------------------------------------------------

    def create_event(self, calendar_id: str = "primary", **fields: Any) -> dict:
        path = (
            "/me/events"
            if calendar_id in (None, "primary")
            else f"/me/calendars/{calendar_id}/events"
        )
        # If `attendees` is present Graph auto-emails the invitations; that is
        # the desired send path (there is no sendUpdates flag to set).
        resp = self._client.post(
            path,
            headers=self._calendar_headers(content_type="application/json"),
            json=self._build_event_body(fields),
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
        # `notify` mirrors the Google signature but has no wire equivalent on
        # Graph: an organizer PATCH of an attendee-bearing event always notifies,
        # with no suppression flag (accepted parity gap, see the module
        # docstring). The gate upstream still forces confirmation before any such
        # patch, so the user always consents to the implied mail.
        path = (
            f"/me/events/{event_id}"
            if calendar_id in (None, "primary")
            else f"/me/calendars/{calendar_id}/events/{event_id}"
        )
        resp = self._client.patch(
            path,
            headers=self._calendar_headers(content_type="application/json"),
            json=self._build_event_body(fields),
        )
        resp.raise_for_status()
        return self._project_event(resp.json())

    def delete_event(
        self, event_id: str, calendar_id: str = "primary", notify: bool | None = None
    ) -> dict:
        # This is where `notify` is actionable. To notify attendees of a
        # cancellation you POST .../cancel (202); to stay silent you DELETE the
        # event (204). A solo event needs no cancellation notice.
        base = (
            f"/me/events/{event_id}"
            if calendar_id in (None, "primary")
            else f"/me/calendars/{calendar_id}/events/{event_id}"
        )
        if notify:
            resp = self._client.post(
                f"{base}/cancel",
                headers=self._calendar_headers(content_type="application/json"),
                json={},
            )
        else:
            resp = self._client.delete(base, headers=self._calendar_headers())
        resp.raise_for_status()
        return {"event_id": event_id, "deleted": True}

    # ---- attendee detection (drives the gate) ------------------------------

    def event_has_attendees(self, event_id: str, calendar_id: str = "primary") -> bool:
        """True if the stored event has guests (so update/delete must be gated)."""
        return bool(self.get_event(event_id, calendar_id).get("attendees"))

    @staticmethod
    def fields_have_attendees(fields: dict[str, Any]) -> bool:
        """True if a create/update payload carries attendees (so it must be gated)."""
        return bool(fields.get("attendees"))

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _build_event_body(fields: dict[str, Any]) -> dict[str, Any]:
        """Translate flat Google-style tool args into a Graph event resource.

        Presence-based, not None-based: on a PATCH an omitted key means
        unchanged, so only keys actually supplied are written. Accepts summary,
        description, location, attendees (list of email strings), and start / end
        (RFC3339 datetime strings or all-day ``YYYY-MM-DD`` dates).
        """
        body: dict[str, Any] = {}
        if "summary" in fields:
            body["subject"] = fields["summary"]
        if "description" in fields:
            body["body"] = {"contentType": "HTML", "content": fields["description"]}
        if "location" in fields:
            body["location"] = {"displayName": fields["location"]}
        if "attendees" in fields:
            body["attendees"] = [
                {"emailAddress": {"address": a}, "type": "required"}
                for a in (fields["attendees"] or [])
            ]
        for key in ("start", "end"):
            if key in fields:
                val = fields[key]
                body[key] = GraphCalendarAdapter._to_graph_datetime(val)
                # A bare date (no time part) is an all-day boundary; Graph needs
                # the sibling isAllDay flag since it has no {date:...} shorthand.
                if isinstance(val, str) and "T" not in val:
                    body["isAllDay"] = True
        return body

    @staticmethod
    def _to_graph_datetime(value: str) -> dict[str, str]:
        """Map an RFC3339 datetime or an all-day date to a Graph dateTimeTimeZone.

        The caller passes either an RFC3339 datetime (contains ``T``, and may
        carry an explicit offset or a trailing ``Z``) or an all-day
        ``YYYY-MM-DD`` date. The absolute instant must survive the round trip,
        so:

        * A datetime that carries an explicit offset (or trailing ``Z``) is
          converted to UTC and labelled the Windows ``UTC`` zone id. Emitting the
          bare wall clock under ``DEFAULT_TZ`` instead (the old behaviour) made
          Graph reinterpret, say, ``12:00Z`` as ``12:00`` Europe time and store
          it two hours early; converting first pins the instant the caller meant.
        * A genuinely naive datetime (no offset at all) is a floating wall clock;
          keep it verbatim under ``DEFAULT_TZ`` (the module default zone) with no shift.
        * An all-day date becomes that date at midnight under ``DEFAULT_TZ`` (the
          sibling isAllDay is set by ``_build_event_body``).
        """
        if "T" not in value:
            return {"dateTime": f"{value}T00:00:00", "timeZone": DEFAULT_TZ}
        if not _has_offset(value):
            return {"dateTime": value, "timeZone": DEFAULT_TZ}
        iso = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        instant = datetime.fromisoformat(iso).astimezone(timezone.utc)
        return {"dateTime": instant.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}

    @staticmethod
    def _project_event(e: dict) -> dict:
        if e.get("isCancelled"):
            status = "cancelled"
        elif e.get("showAs") == "tentative":
            status = "tentative"
        else:
            status = "confirmed"
        _resp = {  # normalize Graph response enum -> Google spellings
            "tentativelyAccepted": "tentative",
            "notResponded": "needsAction",
            "none": "needsAction",
        }
        return {
            "id": e.get("id"),
            "summary": e.get("subject"),
            "description": (e.get("body") or {}).get("content") or e.get("bodyPreview"),
            "location": (e.get("location") or {}).get("displayName"),
            "start": e.get("start"),   # {dateTime, timeZone}, passed through
            "end": e.get("end"),
            "status": status,
            "attendees": [
                {
                    "email": (a.get("emailAddress") or {}).get("address"),
                    "responseStatus": _resp.get(
                        (a.get("status") or {}).get("response"),
                        (a.get("status") or {}).get("response"),
                    ),
                }
                for a in (e.get("attendees") or [])
            ],
            "htmlLink": e.get("webLink"),
            # Null-safe: a present organizer whose emailAddress is explicitly
            # null must degrade to None, not raise (parity with the Google path).
            "organizer": ((e.get("organizer") or {}).get("emailAddress") or {}).get(
                "address"
            ),
        }

    @staticmethod
    def _project_calendar(c: dict) -> dict:
        """Project a Graph calendar resource to the Google-ish shape the Google
        adapter returns (id / summary / primary / accessRole / timeZone), so a
        caller reads the same keys regardless of provider. Graph exposes no
        per-calendar timeZone, so that key is present but None."""
        return {
            "id": c.get("id"),
            "summary": c.get("name"),
            "primary": bool(c.get("isDefaultCalendar")),
            "accessRole": "writer" if c.get("canEdit") else "reader",
            "timeZone": None,
        }


# ---- module helpers --------------------------------------------------------


def _has_offset(value: str) -> bool:
    """True if an RFC3339 datetime carries a UTC designator (``Z``) or a numeric
    ``+HH:MM`` / ``-HH:MM`` offset.

    The scan starts after the date's ``T`` so the date's own hyphens are never
    mistaken for a negative offset.
    """
    if value.endswith("Z"):
        return True
    t = value.find("T")
    if t == -1:
        return False
    tail = value[t + 1 :]
    return "+" in tail or "-" in tail


def _event_matches_query(event: dict, needle: str) -> bool:
    """Case-insensitive substring match of a lower-cased search term against a
    projected event's summary / description / location. Used to filter a
    calendarView window client-side, since calendarView rejects ``$search``.
    """
    for key in ("summary", "description", "location"):
        val = event.get(key)
        if val and needle in val.lower():
            return True
    return False
