---
name: mcp-mail-setup
description: Guide the user through installing and configuring the mcp-mail plugin so Claude can reach their own accounts (email, and where their setup includes them, calendar and drive). Use whenever the user says "set up mcp-mail", "configure my email", "configure my mail server", "connect my mail/calendar/drive to Claude", "onboard mcp-mail", "help me install mcp-mail", or otherwise asks to connect their own mailbox to Claude. The skill walks provider by provider through INSTALL.md, connecting only the accounts the user chooses (Microsoft 365 / Outlook, Gmail / Google Workspace, or any IMAP provider such as iCloud, Yahoo, or Fastmail). Everything runs locally on the user's machine; secrets go into the OS credential store, never into the chat or any file.
---

# mcp-mail setup

This skill helps you (Claude) walk a user through installing and configuring the
**mcp-mail** plugin on their own machine. The heavy lifting lives in the plugin's
`INSTALL.md`; your job is to hand it to the user provider by provider and keep the
three ground rules below front of mind at every step.

## Read this first (three rules you must never break)

### (a) The user connects their own accounts

The user sets up **their own** accounts: their email, and, where their setup
includes them, their calendar and their drive. They decide which providers to
use. The software supports:

- **Microsoft 365 / Outlook** (Microsoft Graph),
- **Gmail / Google Workspace** (Gmail API),
- **any IMAP provider** such as iCloud, Yahoo, or Fastmail (IMAP and SMTP).

The user configures **only the accounts they actually want**. There is no
requirement to set up every provider, and a single account is a perfectly valid
setup. Ask which accounts they want to connect, then set up just those.

### (b) Never disclose the author's own accounts

Never state or imply which specific providers, mailboxes, or addresses the
plugin's author uses. You have no business speaking for anyone's setup but the
user's. When you give examples, use the generic list of supported providers and
neutral placeholder addresses (for example `you@yourcompany.com`,
`you@gmail.com`, `you@icloud.com`). Speak only about the user's own choices.

### (c) Privacy guarantee (state this plainly to the user)

Everything runs **locally on the user's own machine**. There is no shared server
and no third party in the loop. Each account talks **straight to its provider's
API from the user's computer**. All secrets (OAuth client secrets, refresh
tokens, app passwords) live in the user's **OS credential store**: macOS
Keychain, Windows Credential Manager, or Linux Secret Service. No secret is ever
written to `accounts.toml` or to any other file in the package. As a result,
**no one else can see the user's email, calendar, or data**: not the author, not
Numaco, not any hosted service. The only two parties are the user's own machine
and their own provider.

One operational corollary you must follow: **never ask the user to paste a
password, client secret, app-specific password, or token into the chat.** Every
secret goes through the helper scripts in `server/scripts/`, which read it over a
hidden terminal prompt and hand it directly to the OS credential store. You run
the script; the user types the secret into their own terminal, never into the
conversation.

## How to run the setup

Read the plugin's `INSTALL.md` (it sits at the root of this mcp-mail plugin,
one level up from this skill) and work through it with the user in order. It is
written so you can follow it top to bottom on macOS, Windows, or Linux. In short:

1. **Confirm the platform and prerequisites.** Determine the user's OS (ask, or
   infer it) and use the matching command variant throughout: a POSIX shell on
   macOS or Linux, PowerShell on Windows. Check that Python 3.13+, `uv`, and
   Claude Code are present (INSTALL.md section 1).
2. **Build the server** with `uv sync` in `server/` (section 2). Nothing is
   installed globally; it builds an isolated virtual environment.
3. **Ask which accounts the user wants** and write `accounts.toml` for only those
   (sections 3 and 4). This file holds non-secret identity only: addresses, an
   Azure client and tenant ID for Microsoft 365, IMAP host and port. Validate it
   with `scripts/check_config.py`.
4. **Set up each chosen provider** (section 5), pausing after each one to confirm
   it works before moving to the next. Providers are independent.
   - Microsoft 365 / Outlook: an Azure AD app registration; no secret to store by
     hand, the first browser sign-in caches the token.
   - Gmail / Google Workspace: one shared Google OAuth client, stored with
     `scripts/store_google_oauth.py`.
   - IMAP (iCloud, Yahoo, Fastmail, and so on): one app-specific password per
     account, stored with `scripts/store_imap_password.py`.
5. **Install the plugin and restart the session** (section 6), then run the first
   sign-in and smoke test (sections 7 and 8). Start with "list my mail accounts",
   which needs no network, then exercise one account so its sign-in runs.
6. **If anything fails,** go to INSTALL.md section 9 (Troubleshooting) with the
   exact error text and the section number the user was on.

Throughout, keep rules (a), (b), and (c) above in force: only the user's chosen
accounts, no references to anyone else's setup, and secrets only ever through the
helper scripts into the OS credential store.

## Optional extra: the /contacts skill

Once at least one account is connected and the smoke test passes, the user can
build a contact directory from their own mail history with the **`/contacts`**
skill that ships in the same plugin (`skills/contacts/SKILL.md`). It sweeps the
configured accounts and maintains a single markdown directory of the people who
appear in the user's email. It is entirely optional; offer it, but only after the
core setup works. Its output path is user-configurable, so confirm where the user
wants the directory before the first sweep.
