---
description: Scan my Outlook calendar against my Clockify entries and propose what's missing. Defaults to the last 7 days; pass a range as an argument.
allowed-tools:
  - mcp__clockify-mcp__clockify__list_projects
  - mcp__clockify-mcp__clockify__list_time_entries
  - mcp__clockify-mcp__clockify__add_time_entry
---

<!--
The calendar half of this command needs a calendar tool, and there is deliberately
no calendar entry in allowed-tools above. A connector's tool name embeds a
per-installation id (mcp__<uuid>__outlook_calendar_search), so hard-coding one
author's id would name a tool that exists on exactly one machine and silently
resolves nowhere else. Use whichever calendar source you actually have: mcp-mail's
cal_list_events from this same packet (preferred, no connector id needed), or an
Outlook connector's calendar-search tool. Approve it when prompted.
-->

# Find and propose missing Clockify entries

Cross-reference my calendar with my Clockify entries; surface the meetings that should be billed but aren't, with concrete proposed entries.

Range: $ARGUMENTS (default: last 7 days, ending today)

## Universal rules (binding, same as log-session)

1. **15-minute increments only.** `15m`, `30m`, `45m`, `1h`, `1h15m`, `1h30m`, `1h45m`, `2h`. Round to the nearest 15.
2. **Start times on the quarter hour.** Entry `start` and `end` must land on `HH:00`, `HH:15`, `HH:30`, or `HH:45`. For calendar events with non-aligned start times (a 14:33 standup), snap the proposed entry's start *backwards* to the previous quarter hour and adjust end accordingly.
3. **Single entry ≤ 2 h.** Prefer ≤ 1h30m. If a calendar event ran > 2 h, split into chunks with descriptions reflecting each phase.
4. **Never overlap with an existing entry on the same customer**, whether on the same project or a different project under the same client. That's double-billing the customer, always wrong.
5. **For any other overlap behaviour** (e.g. parallel work for *different* customers), defer to the user's organisation policy if one is recorded in `~/.claude/CLAUDE.md`, project-level `CLAUDE.md`, or memory. If no policy is present, default to *no* overlap and ask the user before proposing an entry that would overlap anything.
6. **Cancelled meetings, skip** (`isCancelled: true`).
7. **All-day events, skip** unless the user confirms they were full work days on a single project.
8. **`free` showAs, skip** (the user wasn't actually busy).
9. **Internal company syncs, skip by default** (all-hands, ops syncs, sales syncs, 1:1s with the user's own team). The user can include them on request. If their CLAUDE.md/memory lists specific internal-only meeting patterns to skip, honour that.

## Flow

1. **Pick the range.** If unspecified, default to the last 7 days. The user often says "yesterday" / "last week" / "this month"; interpret accordingly.

2. **Pull data in parallel:**
   - Calendar events for the range, via your calendar tool (mcp-mail `cal_list_events(account, time_min, time_max)` is preferred; an Outlook connector's calendar-search works too).
   - `list_time_entries(start, end)`, existing Clockify entries for the same range.
   - `list_projects()`, to match meeting subjects/attendees to project IDs (cached).

3. **Classify each calendar event:**
   - **Skip** if cancelled, all-day with showAs=free, or recognisably internal-to-the-user's-company.
   - **Match to a project** by subject keywords, attendee email domains, organiser email. Use the project list from `list_projects()` as the source of truth; match calendar signals against project names and any client names they expose. If the user's memory/CLAUDE.md contains a mapping cheat-sheet for their workflow, honour it.
   - Anything not matchable, flag as "needs human classification".

4. **Cross-check against existing entries:**
   - Existing entry on same project overlapping the event, `covered`.
   - Otherwise, `proposed`, subject to the user's overlap policy.

5. **Quantize proposals:**
   - Duration = event end − event start, rounded to nearest 15 min.
   - If > 2 h, split into chunks of ≤ 1h30m each, with descriptions reflecting natural breakpoints (`"phase 1, design"`, `"phase 2, implementation"`).
   - Compose description: `"<short event summary>, with <key attendees>"`. Translate cryptic meeting subjects into action verbs.

6. **Present a table.** Columns: When (local tz, 15-min slots), Duration, Project, Proposed description, Source (calendar event subject), Note (tentative / split / ambiguous).

7. **Flag ambiguities loudly.** If a meeting could match two projects, ask which.

8. **Ask for approval** before posting. Accept "file all" / "file #N, #M" / "skip #N" / "edit #N to <duration>".

9. **Post via `add_time_entry`**, one parallel batch. Show IDs after.

10. **Mapping heads-up.** After the post step, compare the projects you ended up using against the user's CLAUDE.md cheat-sheet. If any project is in Clockify but absent from the cheat-sheet (or no cheat-sheet exists), add a single one-liner at the end of your response noting how many projects lack a mapping rule. Never modify the user's CLAUDE.md from this command.

## Don'ts

- Don't auto-file. Always show the table and ask.
- Don't propose entries on internal company syncs unless the user explicitly opts in.
- Don't propose 20m / 50m durations. **Quantize.**
- Don't propose > 2 h as one entry. **Split.**
- Don't propose an entry that overlaps an existing one on the same customer.
