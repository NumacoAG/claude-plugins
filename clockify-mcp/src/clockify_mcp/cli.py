"""CLI entry point.

The default mode serves local MCP clients over stdio. Utility flags store,
delete, or validate the user's Clockify API key.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from .client import ClockifyClient
from .config import Settings
from .credentials import delete_api_key, store_api_key
from .errors import ClockifyError, ConfigError
from .server import _get_state, mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clockify-mcp",
        description=(
            "Clockify MCP server. Default: stdio for a local MCP client. "
            "Use --check to validate your API key."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the API key, print user info, and exit.",
    )
    parser.add_argument(
        "--store-key",
        action="store_true",
        help="Prompt for and validate your personal Clockify API key, then store it in the OS credential store.",
    )
    parser.add_argument(
        "--delete-key",
        action="store_true",
        help="Delete the Clockify API key from the OS credential store.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (writes to stderr; default INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        if args.store_key:
            return _run_store_key()
        if args.delete_key:
            return _run_delete_key()
        if args.check:
            return _run_check()
        mcp.run()
        return 0
    except ClockifyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _run_check() -> int:
    state = _get_state()
    user = state.get_user()
    settings = user.get("settings") if isinstance(user.get("settings"), dict) else {}
    tz = settings.get("timeZone") if isinstance(settings, dict) else None
    print(f"OK. Authenticated as {user.get('name')} <{user.get('email')}>")
    print(f"  user_id:              {user.get('id')}")
    print(f"  default_workspace_id: {user.get('defaultWorkspace')}")
    print(f"  active_workspace_id:  {user.get('activeWorkspace')}")
    print(f"  timezone:             {tz}")
    return 0


def _run_store_key() -> int:
    api_key = getpass.getpass("Clockify API key (hidden): ").strip()
    if not api_key:
        raise ConfigError("Clockify API key is required; nothing was stored.")

    settings = Settings.load(api_key_override=api_key)
    client = ClockifyClient(settings)
    try:
        user = client.get_current_user()
    finally:
        client.close()

    store_api_key(api_key)
    print(
        "Stored the key in the OS credential store after validating "
        f"{user.get('name')} <{user.get('email')}>."
    )
    return 0


def _run_delete_key() -> int:
    if delete_api_key():
        print("Deleted the Clockify API key from the OS credential store.")
    else:
        print("No Clockify API key was stored in the OS credential store.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
