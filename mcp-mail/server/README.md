# mcp-mail server

The MCP server portion of the `mcp-mail` Claude Code plugin. For the full,
provider-by-provider setup walkthrough see [`../INSTALL.md`](../INSTALL.md); the
project spec is in [`../requirements.md`](../requirements.md).

## First-time setup (short version)

1. Install `uv` if you don't have it: `brew install uv`.
2. From this directory, sync the venv: `uv sync`.
3. Create `~/.config/mcp-mail/accounts.toml` from `../accounts.toml.example` and
   fill in the accounts you want. A Microsoft 365 account needs an Azure AD app
   registration (Application/client ID + tenant ID).
4. Store the required secrets in the macOS Keychain (Google OAuth client blob;
   IMAP app-specific passwords) — see [`../INSTALL.md`](../INSTALL.md).
5. Install the plugin in Claude Code (see `../INSTALL.md`) and restart the session.
6. In Claude, ask: "list my mail accounts", then "list folders in my work-m365
   account". The first call to a given account opens a browser for OAuth
   (Microsoft on `http://localhost:8765`, Google on `http://localhost:8766`).
   After that, tokens are cached in the Keychain and subsequent calls are silent.

## Running standalone (for debugging)

```bash
uv run python -m mcp_mail
```

This starts the stdio MCP server. Use an MCP client to talk to it; it doesn't do
anything interactive on its own.
