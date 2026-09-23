"""Demand only local MCP startup and plugin wiring."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from clockify_mcp import server
from clockify_mcp.config import Settings


async def test_listing_tools_does_not_load_credentials_or_call_clockify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_settings_load(*_args: object, **_kwargs: object) -> Settings:
        raise AssertionError("Tool discovery must not load credentials")

    monkeypatch.setattr(Settings, "load", unexpected_settings_load)

    tools = await server.mcp.list_tools()

    assert "add_time_entry" in {tool.name for tool in tools}


async def test_stdio_process_initializes_and_lists_tools_without_api_key() -> None:
    env = os.environ.copy()
    env.pop("CLOCKIFY_API_KEY", None)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "clockify_mcp.cli"],
        env=env,
    )

    async with (
        stdio_client(params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        response = await session.list_tools()

    assert "add_time_entry" in {tool.name for tool in response.tools}


def test_plugin_manifest_uses_local_stdio_process() -> None:
    manifest_path = Path(__file__).parents[1] / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    connection = manifest["mcpServers"]["clockify"]

    assert connection == {
        "command": "uv",
        "args": [
            "--directory",
            "${CLAUDE_PLUGIN_ROOT}",
            "run",
            "clockify-mcp",
        ],
    }
    assert "url" not in connection
