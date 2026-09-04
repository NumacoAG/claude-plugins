"""Tests for protocol-native outbound email confirmation.

Claude Code keeps its transcript hook. Other MCP clients use form elicitation
inside the mail_send and mail_reply tools, with every abnormal result failing
closed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_mail import server as srv


class _Acct:
    id = "acct"
    address = "me@example.com"
    auto_write = True
    mailbox = None
    signature = None


class _CapturingAdapter:
    def __init__(self) -> None:
        self.sent: dict[str, Any] | None = None
        self.replied: dict[str, Any] | None = None
        self.draft: dict[str, Any] | None = None
        self.reply_draft: dict[str, Any] | None = None

    def send(self, **kwargs: Any) -> None:
        self.sent = kwargs

    def reply(self, **kwargs: Any) -> None:
        self.replied = kwargs

    def create_draft(self, **kwargs: Any) -> dict[str, str]:
        self.draft = kwargs
        return {"id": "draft-1"}

    def create_reply_draft(self, **kwargs: Any) -> dict[str, str]:
        self.reply_draft = kwargs
        return {"id": "reply-draft-1"}


class _ElicitationSession:
    def __init__(self, *, action: str = "accept", decision: str | None = "Send email") -> None:
        self.action = action
        self.decision = decision
        self.calls: list[dict[str, Any]] = []

    async def elicit_form(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        content = None if self.decision is None else {"decision": self.decision}
        return SimpleNamespace(action=self.action, content=content)


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return json.loads(asyncio.run(srv.call_tool(name, arguments))[0].text)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    session: _ElicitationSession | None,
    *,
    capability_error: str | None = None,
) -> _CapturingAdapter:
    adapter = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (_Acct(), adapter))
    monkeypatch.setattr(
        srv,
        "_native_elicitation_target",
        lambda: (session, capability_error, "request-1"),
    )
    return adapter


def _send_arguments(tmp_path: Path) -> dict[str, Any]:
    attachment = tmp_path / "offer.pdf"
    attachment.write_bytes(b"pdf")
    return {
        "account": "acct",
        "to": ["person@example.com"],
        "cc": ["copy@example.com"],
        "bcc": ["blind@example.com"],
        "subject": "Proposal",
        "body_text": "Exact body",
        "attachments": [str(attachment)],
    }


def test_send_choice_sends_after_showing_exact_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = _ElicitationSession(decision="Send email")
    adapter = _install(monkeypatch, session)
    arguments = _send_arguments(tmp_path)

    out = _call("mail_send", arguments)

    assert out == {"ok": True, "sent_to": ["person@example.com"]}
    assert adapter.sent is not None
    assert adapter.draft is None
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["related_request_id"] == "request-1"
    assert call["requestedSchema"]["properties"]["decision"]["enum"] == [
        "Send email",
        "Save as draft",
        "Do not send",
    ]
    message = call["message"]
    for expected in (
        "Account: acct",
        "To: person@example.com",
        "CC: copy@example.com",
        "BCC: blind@example.com",
        "Subject: Proposal",
        "offer.pdf",
        "Exact body",
    ):
        assert expected in message


def test_save_as_draft_never_sends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = _ElicitationSession(decision="Save as draft")
    adapter = _install(monkeypatch, session)

    out = _call("mail_send", _send_arguments(tmp_path))

    assert out == {"ok": True, "draft": {"id": "draft-1"}}
    assert adapter.sent is None
    assert adapter.draft is not None


@pytest.mark.parametrize(
    ("action", "decision"),
    [
        ("accept", "Do not send"),
        ("accept", "Unexpected"),
        ("decline", None),
        ("cancel", None),
    ],
)
def test_negative_or_invalid_result_never_sends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
    decision: str | None,
) -> None:
    session = _ElicitationSession(action=action, decision=decision)
    adapter = _install(monkeypatch, session)

    out = _call("mail_send", _send_arguments(tmp_path))

    assert out["ok"] is False
    assert out["cancelled"] is True
    assert adapter.sent is None
    assert adapter.draft is None


def test_client_without_confirmation_capability_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = _install(
        monkeypatch,
        None,
        capability_error="The MCP client cannot display the required confirmation.",
    )

    out = _call("mail_send", _send_arguments(tmp_path))

    assert out["ok"] is False
    assert out["cancelled"] is True
    assert "cannot display" in out["reason"]
    assert adapter.sent is None


def test_legacy_hook_path_remains_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _install(monkeypatch, None)

    out = _call("mail_send", _send_arguments(tmp_path))

    assert out["ok"] is True
    assert adapter.sent is not None


def test_reply_save_as_draft_never_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _ElicitationSession(decision="Save as draft")
    adapter = _install(monkeypatch, session)

    out = _call(
        "mail_reply",
        {
            "account": "acct",
            "message_id": "message-1",
            "body_text": "Reply body",
            "reply_all": True,
            "cc": ["new@example.com"],
        },
    )

    assert out == {"ok": True, "draft": {"id": "reply-draft-1"}}
    assert adapter.replied is None
    assert adapter.reply_draft is not None
    assert adapter.reply_draft["reply_all"] is True
    message = session.calls[0]["message"]
    assert "Reply to message: message-1" in message
    assert "Reply all: True" in message
    assert "Additional CC: new@example.com" in message


def test_confirmation_round_trip_over_mcp_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CapturingAdapter()
    monkeypatch.setattr(srv, "_get_adapter", lambda account_id: (_Acct(), adapter))
    prompts: list[Any] = []

    async def choose_send(context: Any, params: Any) -> types.ElicitResult:
        prompts.append(params)
        return types.ElicitResult(action="accept", content={"decision": "Send email"})

    async def scenario() -> dict[str, Any]:
        async with create_connected_server_and_client_session(
            srv.server,
            elicitation_callback=choose_send,
            client_info=types.Implementation(name="codex", version="test"),
            raise_exceptions=True,
        ) as session:
            result = await session.call_tool(
                "mail_send",
                {
                    "account": "acct",
                    "to": ["person@example.com"],
                    "subject": "Transport test",
                    "body_text": "No real adapter is connected.",
                },
            )
            return json.loads(result.content[0].text)

    out = asyncio.run(scenario())

    assert out == {"ok": True, "sent_to": ["person@example.com"]}
    assert adapter.sent is not None
    assert len(prompts) == 1
    assert "Transport test" in prompts[0].message
