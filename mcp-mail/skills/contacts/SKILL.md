---
name: contacts
description: Sweep your configured mcp-mail email accounts and maintain a single markdown contact directory of every human contact (name, role, relationship, confidence) with date-range-tracked coverage so each run is resumable and gap-fillable. Use whenever the user says "/contacts", "build my contact directory", "extract contacts from email", "scan emails for contacts", "update my contacts", "rescan a range", "find gaps in contacts", or otherwise asks to sweep email history for people. The skill uses the mcp-mail MCP tools (mail_search, mail_read). It is resumable across runs and incremental — each run only processes uncovered ranges and updates existing entries when new evidence justifies it.
---

# /contacts — email-to-markdown contact directory

## What this skill does

Sweeps through email history across all configured `mcp-mail` accounts and
maintains a single markdown directory of every human contact — their email(s),
role / organisation, relationship, confidence level, first/last seen dates, and a
one-line note. Each contact appears once even if they emailed from multiple
addresses. Existing entries evolve as fresh evidence comes in (role changes, new
addresses, etc.).

## Configure these before first use

This skill is provider-agnostic. Set these to your own values; everything else
flows from them. (If you keep the defaults, the skill still works — it just
writes to your home directory and uses generic groupings.)

| Setting | What it is | Default |
|---|---|---|
| `OUTPUT_PATH` | Absolute path of the markdown directory file to maintain | `~/contacts.md` |
| `OWN_ADDRESSES` | Your own account addresses, to skip as senders | the `address` fields in your `accounts.toml` |
| `GROUPS` | Top-level `##` sections, in order | `Work`, `Personal`, `Other` |
| Per-account message cap | Default messages scanned per account per run | `500` |

`OWN_ADDRESSES` can be discovered automatically: call `mail_list_accounts` and
collect every `address`. Treat those as "self" and never promote them to a
contact entry.

`GROUPS` is yours to rename or extend (e.g. split work by employer, add `Family`,
`Vendors`, etc.). When you can't tell which group a new contact belongs to,
default to the last group (`Other`) and add a note.

## When to invoke

Trigger this skill when the user says any of:

- `/contacts` (any variant — see "Invocation" below)
- "build / update / extend my contact directory"
- "extract contacts from email"
- "scan emails for new contacts"
- "rescan range X to Y for contacts"
- "find gaps in my contact coverage"
- "re-evaluate existing contacts" (no new mail; refresh known entries)

If the request is ambiguous (e.g. "give me my contacts" — is that the file or a
fresh sweep?), default to **reading the file and answering the question** rather
than running a sweep. Only sweep when explicitly asked.

## Invocation variants

| Form | Meaning |
|---|---|
| `/contacts` | Extend each account's most recent covered range forward to "now". Default cap: 500 messages per account per run. |
| `/contacts <N>` | Same as default but cap is N messages per account. |
| `/contacts full` | No message cap; process everything new. |
| `/contacts gaps` | Find and fill any uncovered date ranges across all accounts. |
| `/contacts <account-id>` | Only process that account (e.g. `/contacts personal-gmail`). |
| `/contacts <account-id> from YYYY-MM-DD to YYYY-MM-DD` | Process a specific range. |
| `/contacts re-evaluate` | Don't search new emails. Walk existing contacts and check recent messages from them for changes (role/org evolution). |

When in doubt about which the user meant, **ask once** with a tight question;
don't sweep blindly.

## File structure

The file lives at `OUTPUT_PATH`. Structure:

```markdown
---
version: 1
last_run: 2026-01-01T16:00:00+01:00
coverage:
  work-m365:
    - {from: "2024-01-01", to: "2026-01-01"}
  personal-gmail:
    - {from: "2024-06-15", to: "2025-12-31"}
    - {from: "2026-03-01", to: "2026-01-01"}
  icloud: []
total_contacts: 42
---

# Contacts

## Sweep log

### 2026-01-01 — extended all accounts to today (+12 added, ~3 updated)
- **Added** (12): Alice Smith, Bob Jones, Carla Reyes, ...
- **Updated** (3): Dana Lee (role change), ...
- **Skipped** (1,847): automated / already known

[keep at most the 5 most recent sweep log entries; trim older]

## Work

### Alice Smith — alice.smith@example.com
- **Role:** Project lead at Example Corp
- **Confidence:** high
- **First seen:** 2025-11-02 · **Last seen:** 2026-01-01
- **Notes:** Primary technical liaison on the integration project.

## Personal

### Bob Jones — bob@example.net
- **Role:** Friend
- **Confidence:** high
- **First seen:** 2024-03-10 · **Last seen:** 2025-12-20

## Other
```

> The names above are illustrative placeholders. Your real directory is built
> entirely from your own mail.

### Top-level groupings (## headings)

Group contacts under `##` headings, in this order:
1. `## Sweep log` (always first after the H1)
2. Your configured `GROUPS`, in order (default: `Work`, then `Personal`, then
   `Other`).

When you can't tell which group a new contact belongs to, default to the last
group and add a note explaining the ambiguity. Don't overthink it — the user can
move entries by hand.

### Contact entry shape

Each contact is an `###` heading with `Name — primary.email@domain`, followed by
a bulleted block. Required fields:

- **Role:** short phrase (max ~12 words) — role + organisation
- **Confidence:** one of `high`, `medium`, `low` (never `noise` — those don't get
  entries)
- **First seen:** ISO date (just YYYY-MM-DD)
- **Last seen:** ISO date

Optional fields:

- **Other emails:** comma-separated, if the person uses >1 address
- **Recent thread:** a wikilink `[[Title]]` of the most recent thread (dangling
  links are fine in tools that support `[[wikilinks]]`)
- **Notes:** one short paragraph (max ~3 sentences) of context —
  relationship-relevant facts; how you met; current focus; history of role
  changes ("previously X")

## The rubric — applied per sender

For each unique sender encountered during the sweep:

### Filters (skip if any match — do NOT promote to a contact entry)

- **Self.** Sender is one of `OWN_ADDRESSES`.
- **Automated local-parts.** `noreply`, `no-reply`, `mailer-daemon`,
  `notifications`, `donotreply`, `do-not-reply`, `postmaster`, `bounce`,
  `bounces`, `automated`, `system@`, `alert@`, `notify@`, `team-notifications@`.
- **Transactional senders.** Domains/patterns clearly transactional: receipts,
  package tracking, account verification, OAuth/2FA notifications, calendar
  system accounts (e.g. `calendar-notification@google.com`).
- **Bulk newsletter generic senders.** `marketing@`, `news@`, `info@`,
  `hello@<bigcorp>` — usually not people for a directory, unless context shows
  otherwise.

If a sender is *borderline* (e.g. `support@<small-vendor>` with a real name in
the signature), evaluate by reading 1-2 of their messages. If a real human signs
the messages, promote them as that human (use the signature name); otherwise skip.

### Classification — what to put in the entry

For survivors, read 1-3 of their messages (most recent + one the user replied to
if any exists) to gather:

- **Name.** From the `From: "Name" <email>` field, falling back to the signature
  block, falling back to `<email>`. Strip honorifics ("Dr.", "Mr."), keep middle
  names.
- **Role / organisation.** From the signature block first (most reliable), then
  domain inference (e.g. `@example.com` → Example Corp), then thread context.
- **Relationship → group.** Inferred from organisation + content; map to one of
  your `GROUPS`. Professional contacts → your work group(s); friends/family →
  `Personal`; unclear → `Other`.
- **Confidence:**
  - **high** — at least one reciprocated exchange (the user replied; they replied
    back), OR a clearly known professional contact with a fresh signature block.
  - **medium** — single-direction message with a recognisable signature/role; or
    a clearly real human even if the user hasn't replied yet.
  - **low** — single inbound message, no clear signature, uncertain whether
    they're a real ongoing contact.
  - **noise** — borderline/automated/one-off. **Don't create an entry; just count
    under "Skipped".**
- **First seen:** the `receivedDateTime` of the OLDEST message from this sender in
  your sweep window. (Don't re-query history outside the window; "first seen" is
  "first seen by this sweep" if not already in the directory.)
- **Last seen:** the newest message's `receivedDateTime`.
- **Notes:** one short paragraph. Be specific, not generic. Bad: "Works at company
  X." Good: "Integration project lead; coordinated 3 KT sessions in Q1/Q2."

### Updating existing contacts

If a sender already has an entry in the directory:

1. Read the most recent message from them in your sweep window.
2. Compare its signature/domain/context to what's currently in the entry.
3. **If substantively different** (new role, new org, new alt email):
   - Update the entry, preserving the old fact as history: "previously X
     (2024-2025)".
   - Bump `Last seen` to the new message date.
4. **If same:** just bump `Last seen` if newer than current value. Don't otherwise
   touch the entry.

Update threshold: a title/role change qualifies. A signature reformat does not. A
new alt email in From: → qualifies. Err on the side of leaving entries alone
unless there's clear new evidence.

## Workflow — what to do when `/contacts` fires

### Step 1: Read the current state

Use the Read tool on `OUTPUT_PATH`.

**If the file does not exist:** create it with empty starter content (Write tool):

```markdown
---
version: 1
last_run: null
coverage: {}
total_contacts: 0
---

# Contacts

## Sweep log

(none yet)
```

…and proceed. The first sweep is a cold start: process up to the cap, then write
the file with real coverage ranges.

### Step 2: Parse the front-matter

Extract the `coverage` map (account_id → list of `{from, to}` ranges). This is
your starting state. If any account configured in `accounts.toml` is missing from
`coverage`, treat its coverage as `[]`.

### Step 3: Figure out the sweep plan

Based on the invocation variant:

- **default `/contacts`:** for each account, the new range is `(latest covered
  .to, today]`. If coverage is empty, the range is `(open, today]` — limited by
  the message cap.
- **`/contacts <N>`:** same as default, but cap each account at N messages.
- **`/contacts full`:** same as default, no cap.
- **`/contacts gaps`:** compute uncovered intervals from each account's coverage
  list against `(earliest message ever, today]`. For simplicity use
  `(2018-01-01, today]` as the assumed global lower bound. Process each gap
  oldest-first.
- **`/contacts <account-id>`:** only that account; default behaviour otherwise.
- **`/contacts <account-id> from D1 to D2`:** that account, that explicit range.
- **`/contacts re-evaluate`:** skip Step 4 (new-sender pass); jump to Step 5
  (update pass) with the candidate set = all existing contacts.

Communicate the plan back in one line before kicking off ("OK — extending all
accounts from their latest covered date through today, capped at 500/account").

### Step 4: New-sender pass

For each account in the plan, for each batch of messages in the chosen range:

1. Call `mail_search` with:
   - `account` = the account id
   - `folder` = `"inbox"` (start here; can expand to all-folders later)
   - `query` = the provider-appropriate date filter:
     - Gmail: `after:YYYY/MM/DD before:YYYY/MM/DD` (Gmail uses `/` and exclusive
       `before:`)
     - M365: leave query empty; Graph has no date filter via `$search`. Post-filter
       results by `receivedDateTime` client-side until you walk past the start of
       the window.
     - IMAP (iCloud/Yahoo/…): same as M365 — no query, post-filter client-side.
   - `limit` = a reasonable page size (50 is fine; the cap is enforced by the
     outer batch budget)
2. For each message in the page, get the `from` address.
3. If `from` is already in your "seen" set for this sweep, skip.
4. Otherwise, apply the filters. If it passes:
   - Call `mail_read` for the latest message from that sender (and optionally one
     thread the user replied to).
   - Apply the classification rubric.
   - Either skip with confidence `noise`, OR build a contact entry.
5. Track running counts (added, skipped, errors) for the sweep log.

Stop conditions per account:
- Reached the message cap (default 500).
- Walked past the start of the chosen date range.
- 3+ consecutive errors → bail this account with a warning.

### Step 5: Update pass (for existing contacts)

After Step 4, for each existing contact whose `Last seen` is older than
today-30-days:
- Try `mail_search` with `from:<their primary email>` (Gmail) or filter-by-sender
  (M365/IMAP) for the most recent message.
- If found and newer than the entry's `Last seen`, run the "Updating existing
  contacts" logic and update the entry in-memory.

For `/contacts re-evaluate`: do the update pass for ALL contacts regardless of
staleness.

Performance note: cap at 100 contacts checked per sweep unless invocation says
otherwise.

### Step 6: Compose the new file

Rebuild the file content as a single string:

1. New front-matter: `version: 1`; `last_run` (ISO 8601 w/ tz); `coverage`
   (each account's previous coverage merged with the newly-processed range —
   overlapping/adjacent intervals coalesce); `total_contacts` (count of `###`
   entries).
2. `# Contacts` header.
3. `## Sweep log` with a new entry at the TOP. Trim to the 5 most recent. Format:
   ```markdown
   ### YYYY-MM-DD — <one-line description of what was processed>
   - **Added** (N): <comma-separated names, truncated to ~10>
   - **Updated** (M): <name (change summary), ...>
   - **Skipped** (K): <one-line summary, e.g. "automated / already known">
   ```
4. Your `GROUPS` sections in order. Within each, contacts sorted by `Last seen`
   descending (most recently active first).

### Step 7: Write atomically

Use the Write tool to write the whole file in one shot to `OUTPUT_PATH`. The
harness handles the atomic temp+rename.

### Step 8 (optional): Version control

If `OUTPUT_PATH` lives inside a git repository and you want history, commit it:

```bash
cd "<repo root containing OUTPUT_PATH>" && git pull --ff-only
```

If the pull fails (non-FF), surface the git output, do NOT commit, and tell the
user how to resolve (`git status`, then commit/stash, then re-run `/contacts`).
If it succeeds:

```bash
cd "<repo root>" && git add "<relative path to file>" && git commit -m "contacts sweep: <range, accounts, +N added, ~M updated>"
```

Then optionally `git push`. If push is rejected because the remote moved, the
local commit is safe — tell the user to `git pull --rebase && git push`; do NOT
auto-rebase. If `OUTPUT_PATH` is not in a git repo, skip this step entirely.

### Step 9: Report

End with a one-paragraph summary: what was processed (accounts, date range);
counts (added, updated, skipped, errors); new `total_contacts`; where the file
lives; and version-control status if applicable.

## Edge cases & guidance

- **Conflicting `Updated` evidence within one sweep.** If two messages from the
  same sender give contradictory signals (e.g. "VP" vs "Director"), prefer the
  *most recent*. Note both in the entry's history.
- **Multi-domain contacts.** Merge into one entry under the work address (or
  whichever has more activity). List the other in `**Other emails:**`.
- **Distribution lists / mailing-list senders.** Treat the list address as the
  "sender" if it shows up consistently. Group under your last group with a note
  that it's a list, not a person. (Better: skip with `noise` if it's a one-off.)
- **Very large first sweep.** If the first sweep would scan thousands of messages,
  ask whether to chunk: "First sweep would touch ~5,000 messages across N
  accounts. OK to cap at 500 per account this run and let `/contacts` continue
  incrementally? Or `/contacts full` for everything in one go?"
- **Re-evaluating doesn't move coverage ranges forward.** Only the new-sender
  pass extends `coverage`.

## What this skill DOES NOT do

- It doesn't create per-contact files (single-file design — keep it simple).
- It doesn't manage labels/tags at the message level. Read-only on emails.
- It doesn't fetch attachments.
- It doesn't deduplicate by real-world identity beyond email matching.
- It doesn't sync with any external CRM.

## Constants for your reference

| Concept | Value |
|---|---|
| File path | `OUTPUT_PATH` (you configure; default `~/contacts.md`) |
| Account ids | whatever you named them in `accounts.toml` (e.g. `work-m365`, `personal-gmail`, `icloud`) |
| Own addresses (skip as senders) | `OWN_ADDRESSES` (the `address` fields in `accounts.toml`; or call `mail_list_accounts`) |
| Default per-account message cap | 500 |
| Default top-level groupings (in order) | Work, Personal, Other |
| Sweep log retention | 5 most recent entries |
| Update-pass staleness threshold | 30 days since `Last seen` |
| Update-pass per-sweep cap | 100 contacts |

End of skill spec.
