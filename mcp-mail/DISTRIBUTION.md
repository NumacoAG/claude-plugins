# mcp-mail, distribution notes

## What this package is

This folder is the official, shareable build of **mcp-mail**, a self-hosted
Model Context Protocol server that gives Claude read and write access to your
own mail, calendar, and files (Microsoft 365 / Outlook including SharePoint and
OneDrive, Gmail / Google Workspace including Drive, Docs, Sheets and Slides, any
IMAP provider such as iCloud, Yahoo, or Fastmail, and a local iCloud Drive or
OneDrive folder).

It registers 55 tools across six surfaces: mail (16), Drive files (16), Google
Docs (10), calendar (5), Sheets (5), and Slides (3). Mail works on its own.
Calendar and files are opt-in per account and need a `capabilities` line plus,
on M365 and Google, a one-off re-consent. INSTALL.md section 5D is the step
people miss.

Everything runs locally on your machine. There is no shared server and no third
party in the loop. Each account talks straight to its provider's API from your
computer, and all secrets live in your operating system's credential store,
never in any file in this package.

## How to install

Open **INSTALL.md** and follow it top to bottom. It is written so you can hand
it to Claude ("read INSTALL.md and help me set this up") and have it walk you
through, provider by provider, on macOS, Windows, or Linux. **README.md** is a
shorter overview if you just want the shape of it first.

You configure only the accounts you want. A single account is a valid setup.

**If you are upgrading from a mail-only release, read this first.** Google
freezes a refresh token's scopes at consent time, and this build requests Drive,
Sheets and Calendar in the same list as mail. Your existing Gmail token
therefore no longer validates and mail stops working until you re-consent once
per Google account: `uv run python scripts/reauth_google.py <account-id>` from
`server/`. Microsoft 365 has no equivalent risk; its extra scopes are separate
and silent, so mail is untouched whether or not you ever re-consent.

## What is inside

| Item | Purpose |
|---|---|
| `INSTALL.md` | Full, cross-platform setup walkthrough |
| `README.md` | One-page overview |
| `requirements.md` | What it does and why (the spec) |
| `tier-2-docs/` | How it is built (architecture) |
| `accounts.toml.example` | Template you copy to `~/.config/mcp-mail/accounts.toml` |
| `defaults.toml.example` | Optional shared M365 app identity, copied to `~/.config/mcp-mail/defaults.toml` |
| `server/` | The MCP server (Python, one adapter per provider) |
| `server/tests/` | Regression suite, 319 tests (`cd server && uv run pytest tests`) |
| `hooks/` | The PreToolUse confirmation gate for `mail_send` and `mail_reply` |
| `skills/contacts/` | The optional contacts skill |
| `skills/mcp-mail-setup/` | The guided setup skill |
| `.claude-plugin/` | The plugin manifest |

## Privacy and provenance

This build ships with no personal data of any kind. The example config, the test
fixtures and the contacts skill use placeholder names and addresses only. A
publish gate (`scripts/publish_gate.py` at the repository root) runs in CI and as
a pre-commit hook and refuses any commit that reintroduces a real address, a
GUID, an absolute home path, or a private key block.

When you set it up, the configuration you create (your addresses, your
credentials) stays on your machine; nothing is ever sent back to the author or
anyone else. One local file is worth knowing about: every file and calendar
write, move, delete and share is appended as a JSON line to
`~/.local/state/mcp-mail/audit.log`, so that log accumulates file names, sharing
recipients and calendar references. It is local only, never transmitted, and safe
to delete at any time. Set `MCP_MAIL_AUDIT_LOG` to move it elsewhere.

## Re-sharing this package

If you pass mcp-mail on to someone else, point them at the public repository
(`NumacoAG/claude-plugins` on GitHub) or send this folder exactly as you
received it. Do not substitute a local
working copy or a development checkout: those can contain machine-specific file
paths and the previous user's own account details. This packaged build is the
one that has been vetted as clean.

## License

MIT. Use it, modify it, share it.

## Questions

Setup problems are best handed back to Claude with the exact error text and the
INSTALL.md section number you were on. For anything else, contact whoever sent
you this package.
