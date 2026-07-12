---
name: numaco-timesheet
description: Produce a Numaco AG branded timesheet (hours report) as a PDF in the locked Signature document style. Use whenever the user asks for a timesheet, hours report, Stundenrapport, monthly hours, quarterly hours, "bill the hours for <project>", "timesheet for <customer> <period>", "prepare the Q2 hours for <customer>", or wants to turn tracked time (for example Clockify entries) into a customer facing hours document. Covers both hours-only sheets and sheets with a computed amount column. The skill runs as a short conversation: it establishes client, project, and period, collects and cleans the entries, confirms hours-only versus with-amounts, renders the branded PDF, and verifies it through CoreGraphics.
status: beta
version: 0.1.0
---

# Numaco timesheet skill (Signature pipeline)

## What this skill does

Produces a Numaco branded timesheet as a print ready A4 PDF in the locked
Numaco Signature document style, the same visual system as the SOW and report
skills. A timesheet is a working document, so there is no navy cover page:
page one opens directly in the interior style with the standard running header
and footer, a compact document header, a meta grid (client, project, period,
reference, consultant), one entries table (grouped by month with subtotals when
the period spans several months, closed by the navy total row), a two column
approval block, and the Numaco address and VAT foot line.

The engine is `scripts/build_timesheet.py`: it takes a JSON payload, validates
it strictly, composes the document from the shared Signature module
(`shared/signature/signature.py`), and renders through the shared paged
renderer with the two pass render (which bakes the true page count into the
footer) and the CoreGraphics fidelity check.

## When to trigger (be generous)

- "Timesheet for <customer> <period>", "hours report", "Stundenrapport".
- "Monthly hours", "quarterly hours", "bill the hours for <project>".
- "Turn my Clockify hours for <customer> into a timesheet."
- Any request to produce a customer facing record of hours worked, unless the
  user explicitly wants an unbranded document.

If the user asks for a Statement of Work, quotation, or offer, defer to
`numaco-sow`. For general branded documents, defer to `numaco-report`.

## Conversation protocol

Follow these steps in order.

### Step 1: establish client, project, period

Extract from the user's message: the client legal name, the project title, and
the period (a label such as "Q2 2026" or "April 2026", plus the exact start and
end dates). Ask only for what is genuinely missing. For repeat customers,
pre-fill the legal name and address from prior documents for the same customer
and ask the user to confirm.

### Step 2: obtain the entries

Two paths, in order of preference:

1. **Clockify MCP tools, when available in the session.** If tools whose names
   start with `mcp__plugin_clockify-mcp_clockify__` are available (chiefly
   `report_detailed` and `list_time_entries`), offer to pull the user's time
   entries for the period and map them to entry rows: date from the entry's
   start time, hours from the duration in decimal hours, description from the
   entry description. Then present the mapped rows in chat for review. The user
   reviews and can rewrite every description before rendering: tracked
   descriptions are often internal shorthand, and **internal notes must not
   leak into a customer document**. Merge, split, or reword rows as the user
   directs; only render what they have approved.
2. **Manual entries or a CSV.** Otherwise ask the user for the entries
   (date, description, hours per row), or for a CSV file to parse. Present the
   parsed rows for review exactly as above.

### Step 3: confirm hours-only versus with-amounts

Ask whether the sheet should show hours only (the default, and the usual
choice when the timesheet accompanies a separate invoice) or an Amount column.
When amounts are wanted, the day rate comes from the user's local defaults file
(`~/.config/numaco-design/defaults.toml`, or the `NUMACO_DESIGN_DEFAULTS`
path), from prior documents for the same customer, or from the user directly.
**Never take a rate from the examples in this skill or its sample**; those
numbers are deliberately absurd placeholders. Each amount is computed as hours
divided by 8, multiplied by the day rate.

### Step 4: render

Assemble the JSON payload (schema below) and render:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-timesheet/scripts/build_timesheet.py" payload.json "/abs/path/Timesheet <reference> - <customer> - <period>.pdf"
```

The engine writes a self-contained HTML sidecar next to the PDF and renders the
PDF through the shared paged pipeline. Save the PDF to the customer's project
folder, never into any repository.

### Step 5: verify through CoreGraphics

Verify the PDF through CoreGraphics, never a Chromium preview: run
`numaco_render.pdfcheck(pdf, name, pages="1,2,...")` (the sample script shows
the call) and inspect the rasterised pages, or open the PDF in macOS Preview.
Check page one carries the running header and watermark, the month subtotals
add up, and the total row matches the sum. Present the PDF to the user and
iterate until they approve.

## Payload schema

> **GUARDRAIL: `day_rate_chf: 100` below is a deliberately absurd placeholder**
> (nobody bills CHF 100 per day), as is every example amount in this skill.
> Never carry an example number into a real timesheet payload. Real rates come
> only from the user's defaults file, from prior documents for that customer,
> or from the user directly.

```json
{
  "client_legal_name": "Acme Labs AG",
  "client_address": ["Industriestrasse 12", "CH-8600 Duebendorf"],
  "project_title": "Chromatogram report archival service",
  "period_label": "Q2 2026",
  "period_start": "2026-04-01",
  "period_end": "2026-06-30",
  "reference": "TS-261912-Q2",
  "consultant": "Alex Muster",
  "entries": [
    {"date": "2026-04-03", "description": "Kick-off and scoping.", "hours": 3.5}
  ],
  "day_rate_chf": 100,
  "notes": "All hours were recorded against SOW 261912.",
  "output_path": "/abs/path/final.pdf"
}
```

- `client_address`, `reference`, `consultant`, `day_rate_chf`, `notes`, and
  `output_path` are optional; everything else is required.
- `day_rate_chf` present: an Amount column appears, each amount computed at
  hours / 8 x rate, with per month subtotal amounts and a total amount. Absent:
  the sheet is hours-only and no money appears anywhere.
- `consultant` absent: the engine falls back to the second contact in the
  user's defaults file (the same `[[sow.contacts]]` block the SOW skill uses);
  if there is none, the consultant row is omitted.
- Validation is strict and fails loudly: every entry date must be an ISO date
  inside the period, every hours value must be greater than zero, and missing
  required fields abort the render with a list of every violation.

## Formatting rules (enforced by the engine)

- Dates render as `dd.mm.yyyy`; the period line reads
  `<label> (dd.mm.yyyy to dd.mm.yyyy)`.
- Hours render with one decimal (`3.5`, `8.0`); quarter hours keep two.
- Amounts render Swiss style through the shared module: apostrophe thousands
  separator and `.-` for whole francs (`CHF 12'000.-`), amounts excluding VAT.
- When the period spans several months, the table groups entries under a month
  subheader row with a quiet subtotal row per month; the closing total row is
  the same navy band with the amber accent as the SOW effort estimate total.
- Prose on the sheet never uses dashes as punctuation.

## GUARDRAILS

- **Real customer timesheets are deliverables.** They belong in the customer's
  project folder. Never commit a rendered timesheet, its HTML sidecar, or a
  real payload to this repository; this repository is public.
- **The bundled sample is fictional.** Client Acme Labs AG, invented project,
  invented entries. It proves the pipeline, nothing more.
- **Every example number is a deliberately absurd placeholder** (CHF 12.50 per
  hour, CHF 100 per day, 10 percent discount). Real rates never come from
  examples; see Step 3.
- **Internal tracking notes never leak.** Descriptions pulled from a time
  tracker are reviewed and rewritten for the customer before rendering.

## Files

```
numaco-timesheet/
├── SKILL.md                       <- you are here
├── scripts/
│   └── build_timesheet.py         <- JSON payload -> Signature branded PDF
└── sample/
    ├── build_sample.py            <- renders the fictional Acme sample
    ├── sample_payload.json        <- fictional hours-only payload (15 entries)
    ├── sample_timesheet.html      <- generated, gitignored
    └── sample_timesheet.pdf       <- generated, gitignored
```

The engine composes the locked Signature module (`shared/signature/`) and the
shared renderer (`shared/render/numaco_render.py`). It never invents a new
render path and never hand-writes a bespoke stylesheet; the two small style
blocks it carries (first page interior chrome for the coverless layout, month
group rows in the entries table) are composed strictly from the locked
Signature tokens.

## Relationship to the other skills

- `numaco-sow`: Statements of Work, quotations framed as offers, proposals.
  The SOW's Acceptance term is what makes this timesheet the invoicing basis.
- `numaco-report`: the general branded document engine for reports, memos,
  handovers, and letters.
- `numaco-timesheet`: this skill, the hours report member of the transactional
  document family.
