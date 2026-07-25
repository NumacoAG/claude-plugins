---
description: Scan my Outlook calendar against my Clockify entries and propose what's missing. Defaults to the last 7 days; pass a range as an argument.
allowed-tools:
  - mcp__clockify-mcp__clockify__list_projects
  - mcp__clockify-mcp__clockify__list_time_entries
  - mcp__clockify-mcp__clockify__add_time_entry
---

<!--
The calendar half of this command needs a calendar tool, and there is deliberately
no fourth entry above for it. A connector's tool name embeds a per-installation id
(mcp__<uuid>__outlook_calendar_search), so hard-coding one author's id would name a
tool that exists on exactly one machine and silently resolves nowhere else. Use
whichever calendar source you actually have (an Outlook connector, or mcp-mail's
cal_list_events from this same packet) and approve it when prompted.
-->

Use the `clockify-gaps` skill to reconcile my Outlook calendar with my Clockify entries.

Range: $ARGUMENTS (default: last 7 days, ending today)

Follow the skill's playbook exactly: pull calendar + entries + projects in parallel, classify each event, quantize proposals to 15-min increments, never propose > 2h as one entry, never double-book the same customer, present a table, wait for approval, then post.
