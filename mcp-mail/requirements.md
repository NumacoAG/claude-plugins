# mcp-mail — requirements
**v2.0**

> Source-of-truth spec for the `mcp-mail` project. Detailed technical design
> (architecture, tool surface, auth, sanitisation rules, etc.) lives in
> `tier-2-docs/technical-design.md`.

## 1. Purpose

A self-hosted MCP server that gives Claude full read + write control over your
email accounts across multiple providers (Microsoft 365, Google, and any
IMAP/SMTP mailbox such as Apple iCloud or Yahoo). The server runs locally on
your machine and is consumed by Claude only.

## 2. Providers in scope

You configure any subset of these — a single account is a valid setup.

| Provider | Protocol | Auth mechanism |
|---|---|---|
| Microsoft 365 / Outlook | Microsoft Graph | One Azure AD app registration → OAuth (auth-code + PKCE) |
| Gmail / Google Workspace | Gmail API | One Google OAuth client, shared across your Google accounts |
| iCloud / Yahoo / other IMAP | IMAP + SMTP | App-specific password per account |

## 3. Functional requirements (per account)

### Priority 1 — must work

1. **Send** — compose and send a new message. `To` / `Cc` / `Bcc`, attachments,
   threading headers (`In-Reply-To`, `References`) supported. Default body
   format is HTML with a plain-text fallback (multipart/alternative); outgoing
   HTML is sanitised (no scripts, no remote content, no external CSS —
   bold/italic/links/lists only). Pure plain-text sends available on request.
   Requires per-message confirmation (see §4).
2. **Read** — list folders/labels; list messages in a folder; search across all
   folders; read full message including headers, both plain-text and HTML
   bodies, and attachments.
3. **Mark as spam / unsubscribe** — apply the provider-native spam marker; for
   unsubscribe, parse `List-Unsubscribe` and `List-Unsubscribe-Post` headers and
   walk a graceful-degradation cascade: POST one-click URL (RFC 8058) → mailto:
   via account SMTP → mark spam → block sender → delete. Per-provider details in
   tier-2.
4. **Move between folders within the same account** — move a message to a
   different folder (or apply/remove labels for Gmail).
5. **Mark read / unread** — toggle the read state on a message.
6. **Delete** — move a message to the provider's trash/deleted-items folder.
   Executes immediately on call; not confirmation-gated.

### Priority 2 — nice-to-have

1. **Create / delete folders** within an account.
2. **Archive emails** — provider-native archive (Gmail: remove `INBOX` label;
   M365: move to Archive folder; IMAP: move to `Archive`). A first-class verb so
   Claude doesn't have to know the per-provider spelling.

## 4. Non-functional requirements

- **Local-only.** Server runs on your local machine (macOS, Windows, or Linux),
  bound to `localhost`. No remote deployment, no shared instance.
- **Credentials at rest in the OS credential store.** Never plaintext on disk.
  Refresh tokens (Google, Microsoft) and app-specific passwords (iCloud, Yahoo)
  all live in credential-store entries the MCP reads at runtime via `keyring`
  (macOS Keychain / Windows Credential Manager / Linux Secret Service).
- **One repo, three adapters.** Single MCP server process; one adapter per
  protocol (Graph for M365, Gmail API for Google accounts, IMAP+SMTP for iCloud,
  Yahoo and other IMAP mailboxes). Architecture in tier-2.
- **Account routing.** Every tool call takes an `account` argument; the
  dispatcher routes to the right adapter via the config file. Schema in tier-2.
- **Sessions stay authenticated indefinitely under normal use.**
  Reauthentication is required only when the provider forces it — namely:
  - You change the account's primary password.
  - You revoke the credential at the provider (Azure AD, Google account, Apple
    ID, Yahoo account).
  - The provider's inactivity/policy timeout is exceeded — practically, 90+ days
    unused for Microsoft, 6+ months unused for personal Gmail. A Google OAuth
    consent screen left in **Testing** mode expires refresh tokens after ~7 days
    (set it to Production — see INSTALL.md). Workspace Gmail and Apple/Yahoo
    app-passwords don't expire on a timer.

  In all other cases the MCP refreshes tokens automatically and silently. When
  reauth is unavoidable, it surfaces a clear, actionable prompt rather than a
  cryptic 401.
- **Send requires explicit per-message confirmation.** Claude proposes the full
  envelope; you approve; only then does the SMTP/API call happen. Mechanism:
  Claude Code's per-call permission prompt, not a separate confirmation tool
  inside the MCP. Configurable to auto-send per account in the config file.
  Delete is NOT gated — it executes immediately.
- **Idempotent where reasonable.** Marking-read on an already-read message is a
  no-op, not an error. Same for marking-spam on an already-spam message.

## 5. Out of scope

Calendar read/write was listed here originally and is no longer out of scope: as
of 0.5.0 the server registers five `cal_*` tools for Google and Microsoft 365,
alongside Drive, Docs, Sheets and Slides. What follows is what is still genuinely
excluded.

- Contacts as a first-class API (note: a derived contact directory from emails
  IS a success criterion — see §7 #6).
- Calendar invitations parsed from inside emails (forwarded ICS handling). The
  calendar tools act on calendars directly, not on ICS attachments.
- Cross-account move (would be forward + delete; explicitly excluded for safety).
- Mobile / iOS surface.
- A UI. The MCP is consumed by Claude only.

## 6. Known risks

- **Yahoo app-password reliability.** Yahoo has tightened account security
  repeatedly; treat the Yahoo adapter as the most likely to break. Mitigation:
  the IMAP adapter writes a startup self-test on each account; if Yahoo auth
  fails, surface it immediately rather than at first user-triggered call.
- **Google verification / scopes.** `gmail.modify` and `gmail.send` are
  restricted scopes. For self-hosted personal use, set the OAuth consent screen
  to Production and click through the "unverified app" warning; keeping it in
  Testing forces weekly reauth. Details in INSTALL.md.

## 7. Success criteria (end-to-end smoke test)

From a single Claude session, you can:

1. From a **Gmail** account, search a newsletter and mark it spam.
2. From a **Microsoft 365** account, draft and send a reply to a specific thread
   (with the confirmation step).
3. From an **iCloud** account, mark an old promo email read and move it to an
   `Archive` folder.
4. From a **Yahoo** account, parse a `List-Unsubscribe: <https://...>` header and
   one-click unsubscribe.
5. List all unread messages across all configured accounts, sorted by date.
6. Build a contact directory across all accounts: read through email history and
   compose a directory of human contacts with name, role, a one-line note and a
   confidence level (real contact vs. probable noise). Timeboxed (analyse *x*
   emails per run; the next run picks up the next batch). Output is a single
   markdown file at a path you configure. Productised as the `/contacts` skill.

## 8. Implementation phases

1. **Phase 1 — M365 adapter.** Highest-value first; Graph API is well-documented;
   unlocks send on the primary account.
2. **Phase 2 — Gmail adapter (personal + Workspace).** Two accounts for the
   price of one identity flow.
3. **Phase 3 — IMAP adapter (iCloud + Yahoo + generic).** Same code, many configs.
4. **Phase 4 — Unsubscribe cascade + bulk cleanup workflows.** Higher-level
   orchestration on top of the primitives.
5. **Phase 5 — contact-directory skill.** Productises success criterion §7 #6 as
   the user-invocable `/contacts` skill that wraps the MCP primitives in a
   stable, checkpointed workflow.

## 9. Delivery

The end-state is a single **Claude Code plugin** called `mcp-mail`. The plugin's
manifest bundles the MCP server (phases 1–4) and the contact-directory skill
(phase 5) into one install:

- registers the MCP server automatically (no manual `settings.json` editing),
- drops the contact skill into Claude's discoverable skill path,
- versions both as a unit.

Distribution mode is local install: add the repo as a plugin marketplace and
install from it. See INSTALL.md.
