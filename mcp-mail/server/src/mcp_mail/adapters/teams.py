"""Read-only Microsoft Teams chats through Graph v1.0 delegated permissions."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.parse import quote, unquote, urlsplit

import httpx

from mcp_mail.auth import acquire_teams_token
from mcp_mail.config import M365Account

GRAPH = "https://graph.microsoft.com/v1.0"


def _id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or value in {".", ".."}:
        raise ValueError("Supply the exact nonempty Teams ID returned by a read tool.")
    if any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
        raise ValueError("Teams IDs must be raw IDs, not URLs or paths.")
    return quote(value, safe="")


def _limit(value: int, maximum: int = 50) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}.")
    return value


class GraphTeamsAdapter:
    def __init__(self, account: M365Account) -> None:
        self.account = account
        self._client = httpx.Client(base_url=GRAPH, timeout=60.0, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {acquire_teams_token(self.account)}"},
            **kwargs,
        )
        if response.status_code in {401, 403}:
            raise RuntimeError(
                "Teams access denied for this account. Verify Teams consent, tenant policy and chat membership. "
                "A different organization's meeting may require an authorized account in that organization."
            )
        response.raise_for_status()
        return response.json()

    def _url(self, url: str, path: str) -> str:
        if not isinstance(url, str):
            raise ValueError("Teams continuation URL must be a string.")
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc.lower() != "graph.microsoft.com"
            or parts.fragment
            or unquote(parts.path) != unquote("/v1.0" + path)
        ):
            raise ValueError("Teams continuation is not for the expected Microsoft Graph resource.")
        return url

    def _page(self, path: str, params: dict | None = None, cursor: str | None = None) -> dict:
        url = path
        if cursor:
            try:
                if len(cursor) > 32768:
                    raise ValueError
                state = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
                if state["account"] != self.account.id or state["path"] != path:
                    raise ValueError
                url = self._url(state["url"], path)
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError(
                    "Invalid Teams cursor; reuse the cursor for the same account and resource."
                ) from exc
            params = None
        data = self._request("GET", url, params=params)
        next_link = data.get("@odata.nextLink")
        next_cursor = None
        if next_link:
            self._url(next_link, path)
            state = {"account": self.account.id, "path": path, "url": next_link}
            next_cursor = base64.urlsafe_b64encode(json.dumps(state).encode("utf-8")).decode(
                "ascii"
            )
        return {"value": data.get("value", []), "next_cursor": next_cursor}

    def profile(self) -> dict:
        return self._request(
            "GET", "/me", params={"$select": "id,displayName,mail,userPrincipalName"}
        )

    def list_chats(self, limit: int = 25, cursor: str | None = None) -> dict:
        return self._page(
            "/me/chats",
            {
                "$top": _limit(limit),
                "$expand": "lastMessagePreview",
                "$orderby": "lastMessagePreview/createdDateTime desc",
            },
            cursor,
        )

    def get_chat(self, chat_id: str) -> dict:
        return self._request("GET", f"/chats/{_id(chat_id)}")

    def list_members(self, chat_id: str, cursor: str | None = None) -> dict:
        # The members expansion on chat listing returns at most 25 members.
        # The separate paged endpoint avoids presenting that as a full roster.
        return self._page(f"/chats/{_id(chat_id)}/members", cursor=cursor)

    def list_messages(
        self, chat_id: str, limit: int = 25, before: str | None = None, cursor: str | None = None
    ) -> dict:
        params = {"$top": _limit(limit), "$orderby": "createdDateTime desc"}
        if before:
            if cursor:
                raise ValueError("Do not combine a Teams cursor with a new before filter.")
            timestamp = datetime.fromisoformat(before.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("before must include a timezone offset or Z.")
            stamp = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
            params["$filter"] = f"createdDateTime lt {stamp}"
        return self._page(f"/chats/{_id(chat_id)}/messages", params, cursor)

    def get_message(self, chat_id: str, message_id: str) -> dict:
        return self._request("GET", f"/chats/{_id(chat_id)}/messages/{_id(message_id)}")

    def search_messages(self, query: str, from_index: int = 0, size: int = 25) -> dict:
        _limit(size)
        if not isinstance(query, str) or not query.strip() or len(query) > 4096:
            raise ValueError("Provide a nonempty Teams search query up to 4096 characters.")
        if type(from_index) is not int or not 0 <= from_index <= 10000:
            raise ValueError("from_index must be between 0 and 10000.")
        request = {
            "entityTypes": ["chatMessage"],
            "query": {"queryString": query},
            "from": from_index,
            "size": size,
            "enableTopResults": True,
        }
        data = self._request("POST", "/search/query", json={"requests": [request]})
        containers = [
            container
            for page in data.get("value", [])
            for container in page.get("hitsContainers", [])
        ]
        hits = [hit for container in containers for hit in container.get("hits", [])]
        more = any(c.get("moreResultsAvailable", False) for c in containers)
        return {
            "hits": hits,
            "next_from_index": from_index + size if more else None,
            "more_results_available": more,
        }
