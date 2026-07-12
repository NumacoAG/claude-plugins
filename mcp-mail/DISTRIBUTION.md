# mcp-mail, distribution notes

## What this package is

This folder is the official, shareable build of **mcp-mail**, a self-hosted
Model Context Protocol server that gives Claude read and write access to your
own email accounts (Microsoft 365 / Outlook, Gmail / Google Workspace, and any
IMAP provider such as iCloud, Yahoo, or Fastmail).

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

## What is inside

| Item | Purpose |
|---|---|
| `INSTALL.md` | Full, cross-platform setup walkthrough |
| `README.md` | One-page overview |
| `requirements.md` | What it does and why (the spec) |
| `tier-2-docs/` | How it is built (architecture) |
| `accounts.toml.example` | Template you copy to `~/.config/mcp-mail/accounts.toml` |
| `server/` | The MCP server (Python, one adapter per provider) |
| `skills/contacts/` | The optional `/contacts` skill |
| `.claude-plugin/` | Plugin and marketplace manifests |

## Privacy and provenance

This build ships with no personal data of any kind. The example config and the
`/contacts` skill use placeholder names and addresses only. When you set it up,
the configuration you create (your addresses, your credentials) stays on your
machine; nothing is ever sent back to the author or anyone else.

## Re-sharing this package

If you pass mcp-mail on to someone else, send **this package** (this folder, or
the zip it came in) exactly as you received it. Do not substitute a local
working copy or a development checkout: those can contain machine-specific file
paths and the previous user's own account details. This packaged build is the
one that has been vetted as clean.

## License

MIT. Use it, modify it, share it.

## Questions

Setup problems are best handed back to Claude with the exact error text and the
INSTALL.md section number you were on. For anything else, contact whoever sent
you this package.
