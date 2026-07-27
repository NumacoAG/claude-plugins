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

- **Microsoft 365 / Outlook** (Microsoft Graph): mail, calendar, and files on
  OneDrive and SharePoint,
- **Gmail / Google Workspace**: mail, calendar, and files on Drive, plus Docs,
  Sheets, and Slides,
- **any IMAP provider** such as iCloud, Yahoo, or Fastmail (IMAP and SMTP): mail
  only,
- **a local folder** that iCloud Drive or the OneDrive client already syncs
  (`localfs`): files only, with nothing to register and no consent screen.

The user configures **only the accounts they actually want**. There is no
requirement to set up every provider, and a single account is a perfectly valid
setup. Ask which accounts they want to connect, then set up just those.

Surfaces are opt-in per account as well. Each account lists what it may serve in
`capabilities` (`mail`, `calendar`, `drive`), and a tool refuses any account that
has not declared its capability. Ask what the user actually wants before widening
anything: mail alone is a complete, useful setup and needs no extra permissions.

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
   - **Microsoft 365 / Outlook. Ask this question before anything else, and do
     not skip it:** *"Did your organisation give you a `client_id` and a
     `tenant_id` for mcp-mail?"* Offer three answers and route accordingly.
     - **Yes.** Take the two values, write them into the `[m365]` table of
       `~/.config/mcp-mail/defaults.toml`, and leave `client_id`/`tenant_id` out
       of the account block. That is the whole Microsoft setup (§5A Path A).
       **Never send this user to the Azure portal.**
     - **No, or unsure, on a work or school account.** Stop and tell them to ask
       their IT administrator or whoever introduced them to the packet whether a
       shared registration already exists, before registering anything. Explain
       why in one line: on a managed tenant a self-registered app almost always
       returns `access_denied` at the consent screen, and the result is a
       duplicate registration nobody can use. Waiting for an answer beats
       creating the duplicate. Set up their other providers meanwhile.
     - **No, this is their own tenant or they are self-hosting.** Only now walk
       §5A Path B: an Azure AD app registration, no secret to store by hand, the
       first browser sign-in caches the token.
   - Gmail / Google Workspace: one shared Google OAuth client, stored with
     `scripts/store_google_oauth.py`.
   - IMAP (iCloud, Yahoo, Fastmail, and so on): one app-specific password per
     account, stored with `scripts/store_imap_password.py`. Mail only.
   - A local folder for files (`localfs`): no auth at all. Just a `roots` list in
     `accounts.toml`, which is a hard sandbox boundary, so keep it narrow.
5. **If the user wants calendar or files, do the re-consent** (section 5D). Two
   things must line up: the account declares the capability, and its cached token
   actually carries the wider OAuth scopes. Handle the two providers separately,
   because they are not symmetric.
   - **Google, and say this out loud before you touch anything:** the Drive,
     Sheets and Calendar scopes travel in the *same* list as mail, and Google
     freezes a token's scopes at consent time. So a user upgrading from a
     mail-only release **loses mail itself** until they run
     `uv run python scripts/reauth_google.py <account-id>` once per Google
     account. Tell them this before the upgrade, not after mail breaks.
   - **Microsoft 365:** no such risk. The file, calendar and shared-mailbox
     scopes are separate and requested silently, so mail is untouched whether or
     not they ever re-consent. When they want the extra surfaces, run
     `uv run python scripts/reauth_m365.py <account-id>` once.
   - **If the tenant blocks it:** `Sites.ReadWrite.All` is admin-consent gated in
     most tenants. A non-admin cannot get past that screen. Do not leave the user
     stuck there; offer the local folder backend (section 5E) instead, which
     gives them a working file surface immediately.
6. **Install the plugin and restart the session** (section 6), then run the first
   sign-in and smoke test (sections 7 and 8). Start with "list my mail accounts",
   which needs no network, then exercise one account so its sign-in runs.
7. **Mention the two write guards** before the user starts using it in anger.
   `mail_send` and `mail_reply` always ask per message. Separately, every file and
   calendar write, move, delete and share is refused unless that account sets
   `auto_write = true`; sharing a file and any calendar event with attendees count
   as outward facing and are gated like sending mail. Also tell them that file and
   calendar writes are appended to a local audit log at
   `~/.local/state/mcp-mail/audit.log`, which stays on their machine and can be
   deleted or relocated with `MCP_MAIL_AUDIT_LOG`.
8. **If anything fails,** go to INSTALL.md section 9 (Troubleshooting) with the
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
