# mcp-mail — technical design (tier-2)
**v2.0**

> Reference for Claude (and any developer working on the repo). Tier-1 is
> `../requirements.md` and is the source of truth for *what* and *why*; this
> file is *how*.

## 1. Architecture sketch

```
┌─────────────────┐
│   Claude Code   │  via MCP stdio (local)
└────────┬────────┘
         │
┌────────▼─────────────────────────────────────┐
│              mcp-mail core                   │
│  • tool schema  • account routing            │
│  • send confirmation gating (send only)      │
│  • unsubscribe header parsing (shared)       │
│  • unsubscribe → spam → block → delete       │
│      cascade (shared)                        │
│  • outgoing HTML sanitisation (shared)       │
└─┬───────────┬───────────┬───────────┬────────┘
  ▼           ▼           ▼           ▼
┌──────┐  ┌────────┐  ┌────────┐  ┌────────┐
│Graph │  │ Gmail  │  │  IMAP  │  │  IMAP  │
│M365  │  │  API   │  │        │  │        │
└──────┘  └────────┘  └────────┘  └────────┘
   │         │            │           │
   ▼         ▼            ▼           ▼
 graph.   gmail.       provider    provider
 microsoft googleapis  IMAP+SMTP   IMAP+SMTP
 .com     .com         hosts       hosts
```

## 2. Tool surface (MCP tools)

| Tool | Purpose | Confirmation-gated? |
|---|---|---|
| `mail_list_accounts` | Return configured accounts + provider + auth status. | no |
| `mail_list_folders(account)` | Folders/labels in that account. | no |
| `mail_search(account, query, folder?, limit?, offset?)` | Search; metadata only (no bodies). | no |
| `mail_read(account, message_id, target_dir?)` | Full message: headers, text body, html body, attachment paths. | no |
| `mail_send(account, to, cc?, bcc?, subject, body_text?, body_html?, attachments?, in_reply_to?)` | Send. | **yes** |
| `mail_reply(account, message_id, body_text?, body_html?, attachments?, reply_all?)` | Reply with auto-threading headers. | **yes** |
| `mail_mark_read(account, message_id, read=true)` | Toggle read state. | no |
| `mail_move(account, message_id, target_folder)` | Move within the same account. | no |
| `mail_mark_spam(account, message_id)` | Provider-native spam. | no |
| `mail_block_sender(account, sender_address)` | Provider-native sender block (filter/rule creation). | no |
| `mail_delete(account, message_id)` | Delete (to trash/deleted-items). | **no** (per tier-1 §4) |
| `mail_unsubscribe(account, message_id, mode?="auto")` | Parse `List-Unsubscribe`; act via HTTP-POST, `mailto:`, or cascade. | no |
| `mail_create_folder(account, name, parent?)` | Prio 2. | no |
| `mail_delete_folder(account, name, force?=false)` | Prio 2. Errors if non-empty unless `force=true`. | no |
| `mail_archive(account, message_id)` | Prio 2. Provider-native archive. | no |

Confirmation-gating mechanism: send and reply do NOT go in the Claude Code
allowlist; they always trigger the per-call permission prompt. Delete IS
allowlistable (it's not gated). This is per tier-1 §4.

## 3. Authentication setup

| Provider | Mechanism | Keychain entry |
|---|---|---|
| Microsoft 365 | Azure AD app registration → OAuth (auth-code with PKCE) → refresh token | `mcp-mail:<account-id>` (MSAL token cache) |
| Workspace / Personal Gmail | GCP project + one OAuth client → consent → refresh token | `mcp-mail:<account-id>` (per-account token); shared client in `mcp-mail:google-oauth-config` |
| iCloud | App-specific password from appleid.apple.com | `mcp-mail:<account-id>` |
| Yahoo | App-specific password from Yahoo account security | `mcp-mail:<account-id>` |

Account ids are user-chosen in `accounts.toml`; the Keychain `account` name
defaults to the account id. See `../INSTALL.md` for the concrete commands.

OAuth scopes:
- **Microsoft Graph:** `Mail.ReadWrite`, `Mail.Send`, `MailboxSettings.ReadWrite`
  (for blocked-sender list), `offline_access`.
- **Gmail:** `https://www.googleapis.com/auth/gmail.modify`,
  `https://www.googleapis.com/auth/gmail.send`,
  `https://www.googleapis.com/auth/gmail.settings.basic` (for filters →
  block-sender).

Redirect URIs (loopback):
- **Microsoft (MSAL interactive):** `http://localhost:8765` — **no path**.
  Register it as a "Mobile and desktop applications" redirect URI on the app.
- **Google (InstalledAppFlow):** loopback on `http://localhost:8766` (Desktop
  app client type).

### 3.1 Token-refresh contract

Per the tier-1 NFR "sessions stay authenticated indefinitely", the
implementation must:
- Always request `offline_access` (Microsoft) / set
  `access_type=offline, prompt=consent` (Google) on initial auth.
- Refresh tokens proactively, well before expiry, on every server start and
  again whenever an API call returns 401.
- On refresh failure, surface a clear, actionable reauth prompt — never silently
  swallow the error.

Conditions that force reauth (document at first encounter):
- Microsoft: 90+ days inactivity, password change, conditional-access policy
  change.
- Google personal Gmail: 6 months inactivity, password change; **OAuth consent
  screen left in Testing → ~7-day refresh-token expiry** (set to Production).
- Google Workspace: admin revocation, scope change.
- iCloud/Yahoo: main password change, manual revocation of the app-specific
  password.

## 4. Unsubscribe failure cascade

The `mail_unsubscribe` tool, when called with `mode="auto"`, walks this cascade
and stops at the first step that succeeds:

1. **`List-Unsubscribe` URL with one-click semantics** — POST
   `List-Unsubscribe=One-Click` per RFC 8058.
2. **`List-Unsubscribe` URL without one-click** — GET the URL; if it returns a
   form requiring action, surface the URL to the user rather than auto-submitting.
3. **`List-Unsubscribe` mailto:** — send an empty-body email to the address via
   this account's own SMTP/send-API.
4. **Mark as spam** — apply the provider's spam marker.
5. **Block the sender** — call `mail_block_sender` (provider-specific filter/rule
   creation).
6. **Delete** — move to trash.

Each step's outcome is returned to the caller so Claude can narrate which step
succeeded.

Per-provider implementation of step 5 (block sender):
- **Gmail:** create a filter via `gmail.settings.basic` matching `from:<address>`
  with action `trash` or `delete`.
- **M365:** add to `MailboxSettings/blockedSendersAndDomains` (requires
  `MailboxSettings.ReadWrite`).
- **iCloud / Yahoo (IMAP):** no native API for block-sender; implement as a
  server-side filter rule only if the provider's IMAP extensions support it,
  otherwise return an explicit "not supported on this provider" so the cascade
  falls through to step 6.

## 5. Outgoing-mail body handling

Default is **HTML with a plain-text fallback** (multipart/alternative).

- If caller passes only `body_text`: MCP generates a minimal HTML from it
  (paragraphs split on blank lines, line breaks become `<br>`, naive URL
  linkification). Both parts are sent.
- If caller passes only `body_html`: MCP generates a plain-text mirror by
  stripping tags. Both parts are sent.
- If caller passes both: both are sent verbatim (after sanitisation of the HTML).

HTML sanitisation rules (apply to both caller-supplied and MCP-generated HTML):
- Strip `<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, `<link>`,
  `<meta>`.
- Strip `on*` event-handler attributes.
- Allow only http/https/mailto in `href`/`src`.
- No remote-content references in `<img src>` — must be `cid:` (inline
  attachment) or refuse.
- Allowed inline styles: `font-weight`, `font-style`, `text-decoration`, `color`
  (named or hex). No expressions, no `url()`.

## 6. Attachment handling

- **Read:** the MCP writes attachments to a process-scoped tempdir at
  `$TMPDIR/mcp-mail/<message-id>/<filename>`. `mail_read` returns local paths in
  its result. The tempdir is cleaned on server shutdown. A `target_dir`
  parameter on `mail_read` lets the caller override to e.g. `~/Downloads/` for
  keeper attachments.
- **Send:** `mail_send` and `mail_reply` accept attachments as a list of local
  paths. No base64 round-tripping through Claude's context.

## 7. Account routing & config

Accounts are declared in `~/.config/mcp-mail/accounts.toml`. Minimal sketch:

```toml
[[account]]
id = "work-m365"
provider = "m365"
address = "you@yourcompany.com"
client_id = "<from Azure>"
tenant_id = "<from Azure>"
auto_send = false        # if true, skip confirmation prompt on send/reply

[[account]]
id = "personal-gmail"
provider = "gmail"
address = "you@gmail.com"
auto_send = false
```

Every MCP tool call takes an `account` argument that matches an `id` above. Full
field reference and defaults: see `../accounts.toml.example` and the parser in
`server/src/mcp_mail/config.py`.

## 8. Contact-directory workflow

Not a dedicated tool — a Claude-orchestrated workflow over the primitives,
productised as the `/contacts` skill (`skills/contacts/SKILL.md`). When you ask
to build/extend the contact directory:

1. Claude reads the existing directory file (at the path configured in the skill)
   to know what's already done.
2. Claude calls `mail_search(account, query="", limit=N, offset=last_offset)` for
   each account (round-robin or weighted).
3. For each new sender, Claude calls `mail_read` to skim a few messages, extracts
   name + role + one-line description + confidence, and appends to the directory.
4. Claude updates a checkpoint in the directory's front-matter (coverage per
   account) so the next run picks up where this one left off.
5. The directory is a single markdown file, one section per contact.

No new MCP tool needed. The MCP exposes primitives; the analytical layer lives in
the skill's prompt + the markdown file's structure.

## 9. Open implementation notes

- **Per-account default folder names.** Providers spell "Archive" / "Junk" /
  "Trash" differently; the adapters normalise common names.
- **Rate limiting.** Gmail: 250 quota units/user/sec; Graph: throttles
  per-endpoint. Each adapter does basic exponential-backoff retry on 429; no
  shared rate-limit ledger.

## 10. Plugin packaging

`mcp-mail` ships as a Claude Code plugin. Repo layout:

```
mcp-mail/
├── .claude-plugin/
│   ├── plugin.json         ← plugin manifest (registers the MCP server)
│   └── marketplace.json    ← local marketplace manifest
├── server/                 ← MCP server source (phases 1–4)
│   ├── pyproject.toml
│   ├── uv.lock
│   └── src/mcp_mail/
│       ├── __main__.py     ← stdio entrypoint
│       ├── server.py       ← tool registration + dispatch
│       ├── config.py       ← accounts.toml loader
│       ├── auth.py         ← MSAL (M365) auth + Keychain
│       └── adapters/
│           ├── graph.py
│           ├── gmail.py
│           └── imap.py
├── skills/
│   └── contacts/           ← phase 5 skill
│       └── SKILL.md
├── accounts.toml.example
├── requirements.md         ← tier-1 spec
├── INSTALL.md              ← setup walkthrough
└── tier-2-docs/
    └── technical-design.md ← this doc
```

The `plugin.json` manifest declares the MCP server entrypoint (Python module
spawned over stdio, with `${CLAUDE_PLUGIN_ROOT}` resolving to the installed
plugin directory) and the skill directory (auto-discovered by Claude Code).

On install, Claude Code:
1. Registers the MCP server in the user's settings (no manual `settings.json`
   editing).
2. Makes the contact skill discoverable.
3. Pins server/skill versions together.

Distribution mode is local install from a cloned repo (add as a plugin
marketplace, then install). See `../INSTALL.md`.
