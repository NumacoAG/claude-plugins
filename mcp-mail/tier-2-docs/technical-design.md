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

The table below is the original mail surface. The calendar, Drive, Docs, Sheets
and Slides surfaces added later bring the registry to **55 tools**; their design
is section 11, and the authoritative list is always `list_tools()` in
`server/src/mcp_mail/server.py`.

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

**Shared, non-secret defaults.** `load_accounts` also reads an optional
`~/.config/mcp-mail/defaults.toml` (`config.DEFAULTS_PATH`). Its one table today,
`[m365]`, carries the `client_id` and `tenant_id` of an app registration shared
across a team, which removes the Azure portal step for everyone who is not the
person who created the app. Precedence is per key and the account block always
wins: `entry.get("client_id") or shared.get("client_id")`, so an account can move
to its own registration without the shared file being deleted. `load_defaults`
returns `{}` for a missing, unreadable or invalid file, deliberately, so a broken
shared file degrades into a precise per-account `ValueError` naming both
candidate locations rather than taking mail down. Nothing secret is read from
this file: client and tenant ids are application identity, transmitted in the
browser URL on every PKCE sign-in, while tokens stay in the credential store.
Covered by `server/tests/test_shared_defaults.py`.

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

## 8.1 Native Google Docs inline comments

The public Drive comments API cannot create the native text anchor displayed by
the Google Docs editor. Even an API comment carrying custom anchor metadata is
shown by Workspace editors as a file level comment. Native inline placement is
therefore an orchestrated workflow in
`skills/google-docs-inline-comments/SKILL.md`, not another server write method.

The skill uses `doc_get` to validate the exact quote and occurrence, then uses
an authenticated Browser session to select the text and invoke the Google Docs
comment composer. It takes a `drive_comments` snapshot before the write and
verifies the new comment afterward. The Drive adapter deliberately projects the
raw `anchor` as well as `anchorText`; a successful native Docs comment has the
approved quoted text and a `kix.` anchor. An explicit staged approval remains
required before any colleague visible comment is submitted.

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
│           ├── graph.py       ← mail + OneDrive/SharePoint files
│           ├── gmail.py       ← mail + the shared Google credential
│           ├── imap.py
│           ├── _recipients.py ← one reply-recipient filter for all three
│           ├── gcalendar.py   ← Google Calendar v3
│           ├── mscalendar.py  ← Graph calendar
│           ├── gdrive.py      ← Drive v3 + Sheets v4
│           ├── gdocs.py       ← Docs v1
│           ├── gslides.py     ← Slides v1
│           └── localfs.py     ← sandboxed local folder backend
│       └── core/
│           ├── sandbox.py     ← localfs path boundary
│           ├── guard.py       ← auto_write + outward-facing classification
│           ├── audit.py       ← append-only JSONL write log
│           └── native_format.py
├── hooks/                  ← PreToolUse send gate
├── skills/
│   ├── contacts/           ← phase 5 skill
│   │   └── SKILL.md
│   └── google-docs-inline-comments/
│       └── SKILL.md        ← native Docs comment orchestration
├── accounts.toml.example
├── defaults.toml.example   ← optional shared M365 app identity
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
2. Makes the bundled skills discoverable.
3. Pins server/skill versions together.

Distribution mode is local install from a cloned repo (add as a plugin
marketplace, then install). See `../INSTALL.md`.

---

## 11. Calendar, Drive and files (the capability expansion)

The server grew from 14 mail tools to 55 across six surfaces: mail 16, Drive
files 16, Docs 10, calendar 5, Sheets 5, Slides 3. Five design decisions carry
the weight.

### 11.1 Capabilities are declared, not inferred

Every account carries a `capabilities` tuple (`mail`, `drive`, `calendar`),
validated at load time against `KNOWN_CAPABILITIES`. `_require_capability()`
refuses any tool call on an account that has not declared the matching
capability. Defaults preserve the old behaviour exactly: a mail provider with no
`capabilities` key is mail-only, and `localfs` is drive-only. The point is that
adding a surface to the server does not silently widen an existing account.

### 11.2 The two OAuth providers are deliberately asymmetric

**Microsoft 365 splits its scope sets.** `GRAPH_SCOPES` (mail) stays exactly as
it was. `GRAPH_FILE_SCOPES`, `GRAPH_CALENDAR_SCOPES` and `GRAPH_SHARED_SCOPES`
are separate constants, and `acquire_file_token`, `acquire_calendar_token` and
`acquire_shared_token` are **silent only**: they never open a browser. Widening
the silent mail set would have forced an interactive prompt on every ordinary
mail call, so it was not done. The consequence is the good one: a user who never
re-consents keeps working mail and gets an actionable error on `drive_*` and
`cal_*` naming `scripts/reauth_m365.py`. `GRAPH_REAUTH_SCOPES` is the union that
script requests once, writing back to the same credential-store entry.

**Google cannot do the same thing.** A Google refresh token freezes its granted
scopes at consent time and `Credentials.from_authorized_user_info` validates the
cached token against the requested `SCOPES` list. Drive, Sheets and Calendar are
therefore appended to the single `SCOPES` list in `adapters/gmail.py`, and a
token minted before the expansion no longer validates. That breaks **mail**, not
only the new tools. It is a one-time cost paid by running
`scripts/reauth_google.py` once per Google account, and it is called out in
INSTALL.md section 5D, DISTRIBUTION.md and both setup skills because a silent
version of this failure would look like a bug.

An alternative exists and was not taken: split `SCOPES` into a mail set and an
extended set and validate the cache against the mail set only, mirroring the
M365 design. That would make Google upgrades non-breaking, at the cost of real
new logic in the credential path. It is the obvious next change if the
re-consent proves too sharp an edge in practice.

Docs and Slides need no scope of their own: both ride the broad `/auth/drive`
scope. They do need their APIs enabled in the Google Cloud project, which is a
separate switch per API and the most common cause of a 403 on a correct token.

### 11.3 Four file backends behind one tool surface

| Backend | Adapter | Auth | Notes |
|---|---|---|---|
| OneDrive and SharePoint | `graph.py` (methods on `GraphAdapter`) | Graph file token | `Sites.ReadWrite.All` is admin-consent gated in most tenants |
| Google Drive | `gdrive.py` | shared Google credential | also carries all five `sheet_*` methods against Sheets v4 |
| Local folder | `localfs.py` | none | iCloud Drive or a synced OneDrive mount |
| (Docs, Slides) | `gdocs.py`, `gslides.py` | shared Google credential | document-level editing, not file management |

`_drive_call()` routes one `drive_*` tool call to whichever method name that
backend uses, so the tool surface stays single even though the backends do not
agree on naming. Sheets are methods on `GoogleDriveAdapter` rather than a
separate module, because they share the credential and the file-id space.

The local backend matters more than it looks. It is the answer for every user
whose tenant admin will not grant `Sites.ReadWrite.All`, and it needs no
registration, no consent screen and no network auth. Its cost is two limits:
`drive_share` is unsupported (there is no service to share through) and deletes
go to the macOS Trash through `osascript`, so `drive_delete` is macOS only.

### 11.4 Two safety rails, because files and calendars reach other people

`core/sandbox.py` is a hard path boundary for `localfs`: every resolved path must
sit inside one of the account's declared `roots`, with `..` traversal and
escaping symlinks rejected before any I/O. The `roots` list is the entire
permission model for that backend, which is why the example config tells users to
keep it narrow.

`core/guard.py` carries two independent ideas. `require_auto_write()` refuses
every write, move, delete and share unless the account opts in with
`auto_write = true`, mirroring `auto_send` on the mail side. `is_outward_facing()`
classifies the calls that reach other humans: `drive_share` always, and
`cal_create_event` / `cal_update_event` / `cal_delete_event` only when the event
carries attendees, which is why the calendar adapters both expose
`event_has_attendees` and `fields_have_attendees`. Outward-facing calls are gated
the way sending mail is gated.

### 11.5 The audit log is new persistent local data

`core/audit.py` appends one JSON line per write, move, delete and share to
`~/.local/state/mcp-mail/audit.log` (`MCP_MAIL_AUDIT_LOG` overrides the path),
recording the operation, account id, item reference and a small detail object.
Writing is best effort and never raises to the caller, so nothing depends on it.
It does accumulate file names, sharing recipients and calendar references on the
user's disk, so it is disclosed in the README and INSTALL privacy sections
rather than left to be discovered.

### 11.6 Delegate mailboxes

`M365Account.mailbox` turns an account into a delegate view of another person's
mailbox: `_item_base()` targets `/users/{mailbox}` instead of `/me` and the
adapter uses the shared-mailbox token. Reading and drafting work; sending on
behalf of the mailbox is refused. Two prerequisites are outside this code and
neither substitutes for the other: the `Mail.ReadWrite.Shared` scope, and the
mailbox owner granting Exchange Full Access.

### 11.7 Known rough edges

- `DEFAULT_TZ` in `mscalendar.py` is a hardcoded Windows timezone id used for
  floating wall-clock events. It is correct for Central Europe and wrong
  elsewhere; it is documented as an edit point rather than made configurable.
- The Google re-consent break described in 11.2 is a real upgrade cost, not a
  bug, but it is the sharpest edge in the whole surface.
- `hooks/hooks.json` currently matches `mail_send` and `mail_reply` only.
  `core.guard` designates `drive_share` and attendee-bearing calendar writes as
  outward facing, and extending the hook matcher to cover them would put the
  per-call prompt in front of those too.
