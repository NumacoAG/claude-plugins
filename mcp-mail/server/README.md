# mcp-mail server

The MCP server portion of the `mcp-mail` Claude Code plugin. For the full,
provider-by-provider setup walkthrough see [`../INSTALL.md`](../INSTALL.md); the
project spec is in [`../requirements.md`](../requirements.md).

It registers 55 tools over six surfaces: mail (16), Drive and SharePoint or
OneDrive files (16), Google Docs (10), calendar (5), Sheets (5), and Slides (3).
Mail needs nothing beyond the provider setup. The other surfaces are opt-in per
account through a `capabilities` list in `accounts.toml`, plus a one-off
re-consent so the cached token carries the wider OAuth scopes. See section 5D of
`../INSTALL.md`, and read it before upgrading a Google account: on Google the
wider scopes share one list with mail, so an un-re-consented token breaks mail.

## First-time setup (short version)

1. Install `uv` if you don't have it: `brew install uv`.
2. From this directory, sync the venv: `uv sync`.
3. Create `~/.config/mcp-mail/accounts.toml` from `../accounts.toml.example` and
   fill in the accounts you want. A Microsoft 365 account needs an Azure AD app
   registration (Application/client ID + tenant ID).
4. Store the required secrets in the macOS Keychain (Google OAuth client blob;
   IMAP app-specific passwords) — see [`../INSTALL.md`](../INSTALL.md).
5. Install the plugin in Claude Code (see `../INSTALL.md`) and restart the session.
6. If you want calendar or files, add `capabilities` to those accounts and run
   the re-consent once: `uv run python scripts/reauth_m365.py <id>` for M365,
   `uv run python scripts/reauth_google.py <id>` for Google (`../INSTALL.md`
   section 5D). A `localfs` account needs neither: it declares `roots` and works
   immediately.
7. In Claude, ask: "list my mail accounts", then "list folders in my work-m365
   account". The first call to a given account opens a browser for OAuth
   (Microsoft on `http://localhost:8765`, Google on `http://localhost:8766`).
   After that, tokens are cached in the Keychain and subsequent calls are silent.

## Running standalone (for debugging)

```bash
uv run python -m mcp_mail
```

This starts the stdio MCP server. Use an MCP client to talk to it; it doesn't do
anything interactive on its own.
