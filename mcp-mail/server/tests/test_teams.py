"""Read-only Teams transport, pagination boundaries, scopes and dispatch."""

import asyncio
import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from mcp_mail import auth, server, teams_tools
from mcp_mail.adapters import teams
from mcp_mail.config import M365Account, load_accounts

CHAT = "19:meeting_fixture@thread.v2"
ACCOUNT = M365Account(
    id="work",
    provider="m365",
    address="you@example.com",
    client_id="client",
    tenant_id="tenant",
    keychain_service="test",
    keychain_user="work",
    auto_send=False,
    capabilities=("mail", "teams"),
)


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(teams, "acquire_teams_token", lambda account: "fixture-token")
    client = teams.GraphTeamsAdapter(ACCOUNT)
    yield client
    client._client.close()


def transport(adapter, handler):
    adapter._client.close()
    adapter._client = httpx.Client(
        base_url=teams.GRAPH, transport=httpx.MockTransport(handler), follow_redirects=False
    )


def response(payload, status=200, headers=None):
    return httpx.Response(status, json=payload, headers=headers)


def test_chat_pagination_retains_empty_page_continuation(adapter):
    calls = []

    def handler(request):
        calls.append(request)
        if "$skiptoken" not in request.url.params:
            return response(
                {"value": [], "@odata.nextLink": teams.GRAPH + "/me/chats?$skiptoken=opaque"}
            )
        return response({"value": [{"id": CHAT, "topic": "Meeting"}]})

    transport(adapter, handler)
    first = adapter.list_chats(limit=2)
    assert first["value"] == []
    assert first["next_cursor"]
    second = adapter.list_chats(cursor=first["next_cursor"])
    assert second == {"value": [{"id": CHAT, "topic": "Meeting"}], "next_cursor": None}
    assert calls[0].url.params["$top"] == "2"
    assert calls[1].url.params["$skiptoken"] == "opaque"
    assert all(r.headers["Authorization"] == "Bearer fixture-token" for r in calls)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1.0/me/chats",
        "https://graph.microsoft.com/other",
        "https://graph.microsoft.com/v1.0/users/other/chats",
        "http://graph.microsoft.com/v1.0/me/chats",
        "https://graph.microsoft.com:443/v1.0/me/chats",
        "https://graph.microsoft.com/v1.0/me/chats#fragment",
    ],
)
def test_continuation_refuses_other_hosts_or_resources(adapter, url):
    calls = []

    def handler(request):
        calls.append(request)
        return response({"value": [], "@odata.nextLink": url})

    transport(adapter, handler)
    with pytest.raises(ValueError, match="expected Microsoft Graph resource"):
        adapter.list_chats()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "state",
    [
        {"account": "other", "path": "/me/chats", "url": teams.GRAPH + "/me/chats"},
        {
            "account": "work",
            "path": "/chats/other/members",
            "url": teams.GRAPH + "/chats/other/members",
        },
        {"account": "work", "path": "/me/chats", "url": 123},
        [],
    ],
)
def test_cursors_are_account_and_resource_bound(adapter, state):
    transport(adapter, lambda request: pytest.fail("Invalid cursor must not send a request"))
    cursor = base64.urlsafe_b64encode(json.dumps(state).encode()).decode()
    with pytest.raises(ValueError, match="Invalid Teams cursor"):
        adapter.list_chats(cursor=cursor)


@pytest.mark.parametrize(
    "chat_id",
    ["", "..", "https://example.com", "chat/messages", "chat?x=1", "chat\\other", "chat\x00"],
)
def test_invalid_ids_never_enter_request_paths(adapter, chat_id):
    transport(adapter, lambda request: pytest.fail("Invalid ID must not send a request"))
    with pytest.raises(ValueError, match=r"Teams ID|Teams IDs"):
        adapter.get_chat(chat_id)


def test_messages_retain_body_mentions_attachments_and_created_order(adapter):
    payload = {
        "id": "message",
        "body": {"contentType": "html", "content": "<p>Meeting notes</p>"},
        "mentions": [{"mentionText": "Reviewer"}],
        "attachments": [{"contentUrl": "https://example.com/reference"}],
    }

    def handler(request):
        assert request.method == "GET"
        assert request.url.params["$orderby"] == "createdDateTime desc"
        assert request.url.params["$filter"] == "createdDateTime lt 2026-10-30T12:00:00Z"
        assert b"19%3Ameeting_fixture%40thread.v2/messages" in request.url.raw_path
        return response({"value": [payload]})

    transport(adapter, handler)
    assert adapter.list_messages(CHAT, before="2026-10-30T13:00:00+01:00")["value"] == [payload]


@pytest.mark.parametrize("before", ["2026-10-30T12:00:00", "not-a-time", "2026-10-30Z' or true"])
def test_message_cutoff_must_be_a_zoned_timestamp(adapter, before):
    with pytest.raises(ValueError, match=r"timezone|Invalid isoformat"):
        adapter.list_messages(CHAT, before=before)


def test_chat_members_and_single_message_are_read_only(adapter):
    paths = []

    def handler(request):
        assert request.method == "GET"
        paths.append(request.url.path)
        return response(
            {"value": [{"id": "member"}]}
            if request.url.path.endswith("members")
            else {"id": "message"}
        )

    transport(adapter, handler)
    assert adapter.list_members(CHAT)["value"] == [{"id": "member"}]
    assert adapter.get_message(CHAT, "message")["id"] == "message"
    assert paths[-1].endswith("/messages/message")


def test_search_is_graph_v1_read_query_with_continuation(adapter):
    def handler(request):
        assert request.url.path == "/v1.0/search/query"
        assert request.method == "POST"
        body = json.loads(request.content)["requests"][0]
        assert body["entityTypes"] == ["chatMessage"]
        assert body["query"]["queryString"] == "topic from:reviewer"
        assert body["from"] == 25
        assert body["size"] == 10
        return response(
            {
                "value": [
                    {
                        "hitsContainers": [
                            {
                                "hits": [{"resource": {"id": "m", "chatId": CHAT}}],
                                "moreResultsAvailable": True,
                            }
                        ]
                    }
                ]
            }
        )

    transport(adapter, handler)
    result = adapter.search_messages("topic from:reviewer", from_index=25, size=10)
    assert result["next_from_index"] == 35
    assert result["hits"][0]["resource"]["chatId"] == CHAT


@pytest.mark.parametrize("limit", [-1, 0, 51, True, "10"])
def test_page_size_is_validated_before_auth(adapter, limit):
    with pytest.raises(ValueError, match="limit must be between"):
        adapter.list_chats(limit=limit)


def test_graph_denial_is_actionable_without_remote_details(adapter):
    transport(
        adapter, lambda request: response({"error": {"message": "private-error-detail"}}, 403)
    )
    with pytest.raises(RuntimeError, match="membership") as error:
        adapter.get_chat(CHAT)
    assert "private-error-detail" not in str(error.value)


def test_graph_redirect_does_not_forward_bearer_token(adapter):
    calls = []

    def handler(request):
        calls.append(request)
        return response({}, 302, {"Location": "https://example.com/redirect"})

    transport(adapter, handler)
    with pytest.raises(httpx.HTTPStatusError):
        adapter.profile()
    assert len(calls) == 1


def test_tool_schemas_are_read_only_and_registered():
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(teams_tools.METHODS).issubset(tools)
    for name in teams_tools.METHODS:
        assert tools[name].annotations.readOnlyHint
        assert tools[name].inputSchema["additionalProperties"] is False
        assert "account" in tools[name].inputSchema["required"]


def test_undeclared_capability_stops_before_auth_or_transport(monkeypatch):
    monkeypatch.setattr(
        teams_tools, "get_account", lambda _: replace(ACCOUNT, capabilities=("mail",))
    )
    monkeypatch.setattr(
        teams_tools,
        "GraphTeamsAdapter",
        lambda _: pytest.fail("Must fail before adapter construction"),
    )
    with pytest.raises(ValueError, match="capabilities"):
        asyncio.run(server.call_tool("teams_list_chats", {"account": "work"}))


@pytest.mark.parametrize(
    ("provider", "mailbox"), [("gmail", ""), ("imap", ""), ("m365", "shared@example.com")]
)
def test_config_rejects_teams_on_other_providers_and_delegates(tmp_path, provider, mailbox):
    text = f'[[account]]\nid="work"\nprovider="{provider}"\naddress="you@example.com"\nclient_id="client"\ntenant_id="tenant"\ncapabilities=["teams"]\nmailbox="{mailbox}"\nimap_host="example.com"\nsmtp_host="example.com"\n'
    path = tmp_path / "accounts.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="own account"):
        load_accounts(path)


def test_teams_scopes_do_not_expand_mail_or_old_reconsent():
    assert all("Chat." not in scope for scope in auth.GRAPH_SCOPES + auth.GRAPH_REAUTH_SCOPES)
    assert {s.rsplit("/", 1)[1] for s in auth.GRAPH_TEAMS_SCOPES} == {"User.Read", "Chat.Read"}


@pytest.fixture
def login(monkeypatch):
    saved = []
    app = SimpleNamespace(
        get_accounts=lambda: [{"username": "you@example.com"}],
        acquire_token_silent=lambda scopes, account: None,
        acquire_token_interactive=lambda **kw: pytest.fail("Tools must never open sign-in"),
    )
    isolated = replace(ACCOUNT, keychain_user="work.teams")
    cache = object()
    monkeypatch.setattr(auth, "_teams_app", lambda acct: (isolated, app, cache))
    monkeypatch.setattr(auth, "_save_cache", lambda acct, cache: saved.append(acct.keychain_user))
    return app, saved


def test_missing_teams_consent_is_silent_and_does_not_save(login):
    _, saved = login
    with pytest.raises(RuntimeError, match=r"reauth_teams\.py"):
        auth.acquire_teams_token(ACCOUNT)
    assert saved == []


def test_valid_teams_token_only_saves_isolated_cache(login):
    app, saved = login

    def silent(scopes, account):
        assert scopes == auth.GRAPH_TEAMS_SCOPES
        assert account["username"] == ACCOUNT.address
        return {"access_token": "fixture"}

    app.acquire_token_silent = silent
    assert auth.acquire_teams_token(ACCOUNT) == "fixture"
    assert saved == ["work.teams"]


def test_interactive_wrong_identity_does_not_persist(login):
    app, saved = login
    # The cache may still contain the expected account from an earlier login.
    # The actual new result must match, not merely some cached identity.
    app.acquire_token_interactive = lambda **kwargs: {
        "access_token": "fixture",
        "id_token_claims": {"preferred_username": "other@example.com"},
    }
    with pytest.raises(RuntimeError, match="identity"):
        auth.reauth_teams_interactive(ACCOUNT)
    assert saved == []


def test_interactive_expected_identity_saves_only_teams_cache(login):
    app, saved = login
    app.acquire_token_interactive = lambda **kwargs: {
        "access_token": "fixture",
        "id_token_claims": {"preferred_username": ACCOUNT.address.upper()},
    }
    assert auth.reauth_teams_interactive(ACCOUNT)["ok"]
    assert saved == ["work.teams"]


def test_teams_bootstrap_leaves_mail_cache_untouched(monkeypatch):
    writes = []
    calls = []
    monkeypatch.setattr(
        auth, "get_secret", lambda service, user: "mail-cache" if user == "work" else None
    )

    def load(account, **kwargs):
        calls.append((account.keychain_user, kwargs))
        return object(), object()

    monkeypatch.setattr(auth, "_load_app", load)
    monkeypatch.setattr(auth, "set_secret", lambda *args: writes.append(args))
    isolated, _, _ = auth._teams_app(ACCOUNT)
    assert isolated.keychain_user == "work.teams"
    assert calls == [("work.teams", {"bootstrap_cache": "mail-cache"})]
    assert writes == []
