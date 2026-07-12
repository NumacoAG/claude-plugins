# mcp-mail

A self-hosted [Model Context Protocol](https://modelcontextprotocol.io) server
that gives Claude full read + write control over your email across **Microsoft
365 / Outlook**, **Gmail / Google Workspace**, and **any IMAP provider** (iCloud,
Yahoo, Fastmail, …). It ships as a Claude Code plugin: one install registers the
MCP server plus a `/contacts` skill that sweeps your mail into a contact
directory.

Everything runs locally on your machine (macOS, Windows, or Linux). Credentials
live in your OS credential store — never in plaintext on disk. There is no
shared server and no third party in the loop; the MCP talks straight to each
provider's API from your machine.

## What you can do from Claude

- List accounts and folders/labels; search and read full messages (with
  attachments) across every account.
- Send and reply (with threading), gated behind a per-message confirmation.
- Mark read/unread, move between folders, mark spam, delete.
- One-click unsubscribe (RFC 8058 `List-Unsubscribe`), with a graceful
  spam → block → delete fallback cascade.
- Build and maintain a contact directory from your mail history (`/contacts`).

## Providers

| Provider | Protocol | Auth |
|---|---|---|
| Microsoft 365 / Outlook | Microsoft Graph | Azure AD app registration → OAuth (auth-code + PKCE) |
| Gmail / Google Workspace | Gmail API | Google OAuth client (shared across your Google accounts) |
| iCloud / Yahoo / other IMAP | IMAP + SMTP | provider app-specific password |

You can run with any subset — a single account is a valid setup.

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
- `mail_send` / `mail_reply` always trigger a per-message confirmation prompt.
  `mail_delete` is **not** gated — think before allowlisting it.

## License

MIT.
