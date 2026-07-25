# mcp-mail

A self-hosted [Model Context Protocol](https://modelcontextprotocol.io) server
that gives Claude full read + write control over your **mail, calendar, and
files** across **Microsoft 365 / Outlook** (including SharePoint and OneDrive),
**Gmail / Google Workspace** (Drive, Docs, Sheets, Slides, Calendar), **any IMAP
provider** (iCloud, Yahoo, Fastmail, …), and a **local iCloud Drive or OneDrive
folder**. It ships as a Claude Code plugin: one install registers the MCP server
plus a `/contacts` skill that sweeps your mail into a contact directory.

55 tools over six surfaces: mail (16), Drive files (16), Google Docs (10),
calendar (5), Sheets (5), Slides (3). Mail works on its own. Calendar and files
are **opt-in per account**, so nothing widens by surprise: an account serves only
the surfaces it lists in `capabilities`, and on M365 and Google you re-consent
once so the cached token carries the wider OAuth scopes.

Everything runs locally on your machine (macOS, Windows, or Linux). Credentials
live in your OS credential store — never in plaintext on disk. There is no
shared server and no third party in the loop; the MCP talks straight to each
provider's API from your machine.

## What you can do from Claude

- List accounts and folders/labels; search and read full messages (with
  attachments) across every account.
- Send and reply (with threading), gated behind a per-message confirmation.
- Mark read/unread, move between folders, mark spam, delete.
- Save drafts and reply-drafts instead of sending, on every provider.
- One-click unsubscribe (RFC 8058 `List-Unsubscribe`), with a graceful
  spam → block → delete fallback cascade.
- Build and maintain a contact directory from your mail history (`/contacts`).
- Read and write your calendar: list calendars and events, create, update and
  delete. Events with attendees are treated as outward facing and gated.
- Browse, search, read, create, update, move, copy, delete and share files on
  OneDrive, SharePoint document libraries, Google Drive, or a plain local
  folder that iCloud Drive or OneDrive already syncs.
- Read and edit Google Docs (text, tables, formatting), read and write Google
  Sheets ranges, and read and edit text in Google Slides.
- Comment threads on Google Drive files: list, add, reply, resolve, reopen.

## Providers

| Provider | Protocol | Auth |
|---|---|---|
| Microsoft 365 / Outlook | Microsoft Graph | Azure AD app registration → OAuth (auth-code + PKCE) |
| Gmail / Google Workspace | Gmail API | Google OAuth client (shared across your Google accounts) |
| iCloud / Yahoo / other IMAP | IMAP + SMTP | provider app-specific password |
| Local folder (iCloud Drive, synced OneDrive) | filesystem | none |

You can run with any subset — a single account is a valid setup.

**Which surfaces each provider serves**

| Provider | Mail | Calendar | Files |
|---|---|---|---|
| Microsoft 365 | yes | yes | OneDrive and SharePoint |
| Gmail / Workspace | yes | yes | Drive, Docs, Sheets, Slides |
| IMAP | yes | no | no |
| Local folder | no | no | yes, no permissions needed |

The local folder backend is the fallback worth knowing about: if your tenant
admin will not grant the SharePoint permission, it gives you a working file
surface with nothing to register and no consent screen. Its `roots` list is a
hard sandbox, and its deletes go to the macOS Trash, which also makes
`drive_delete` macOS only.

## Install

See **[INSTALL.md](INSTALL.md)** for the full, provider-by-provider walkthrough.
It's written so you can hand it to Claude and have it guide you through setup
step by step.

## Requirements

- macOS, Windows, or Linux (secrets go to the OS credential store —
  Keychain / Credential Manager / Secret Service — automatically)
- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/)
- Claude Code

## Layout

```
mcp-mail/
├── .claude-plugin/        plugin + marketplace manifests
├── server/                the MCP server (Python, one adapter per provider)
├── server/tests/          the regression suite (232 tests, `uv run pytest tests`)
├── hooks/                 the PreToolUse send gate for mail_send / mail_reply
├── skills/contacts/       the /contacts skill
├── accounts.toml.example  copy to ~/.config/mcp-mail/accounts.toml
├── requirements.md        what it does and why (spec)
├── tier-2-docs/           how it's built (architecture)
└── INSTALL.md             setup walkthrough
```

## Security model

- Secrets (OAuth client secret, refresh tokens, app-specific passwords) live only
  in your OS credential store (macOS Keychain / Windows Credential Manager /
  Linux Secret Service). The config file holds non-secret IDs only.
- The server binds to `localhost` and is spoken to over stdio by Claude Code.
- `mail_send` / `mail_reply` always trigger a per-message confirmation prompt,
  enforced by a `PreToolUse` hook that fails **closed**: if the hook cannot run,
  the send is blocked rather than let through. `mail_delete` is **not** gated —
  think before allowlisting it.
- File and calendar writes have a second guard: unless an account sets
  `auto_write = true`, every write, move, delete and share is refused server side
  until you confirm the intent. Sharing a file, and any calendar event that
  carries attendees, count as **outward facing** and are gated like sending mail.
- An account can only serve the surfaces it declares in `capabilities`, so a
  mail-only account cannot be drawn into a file or calendar call.
- **One new local file.** Every write, move, delete and share is appended as a
  JSON line to `~/.local/state/mcp-mail/audit.log`, which therefore records file
  names, sharing recipients and calendar references. It stays on your machine and
  is never transmitted. `MCP_MAIL_AUDIT_LOG` moves it; deleting it is safe.

## License

MIT.
