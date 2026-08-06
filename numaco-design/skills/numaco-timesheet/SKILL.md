---
name: numaco-timesheet
description: >-
  Produce a Numaco AG branded timesheet as a PDF in the locked Signal Stack document style. Use whenever the user asks for a timesheet, hours report, Stundenrapport, monthly hours, quarterly hours, billing the hours for a project, a timesheet for a customer and period, a quarterly customer hours report, or wants to turn tracked time such as Clockify entries into a customer facing hours document. Covers optional category analysis with four to eight colour coded work types, hours only sheets, sheets with a computed amount column, and sheets that track utilisation against an hours budget with a chart. The skill establishes the client, project, and period, cleans and categorises the entries, confirms the budget and financial detail, renders the branded PDF, and verifies every page through CoreGraphics.
---

# Numaco timesheet skill (Signal Stack pipeline)

## What this skill does

Produces a Numaco branded timesheet as a print ready A4 PDF in the locked
Numaco Signal Stack document style, the same visual system as the SOW and
report skills. The layout provides:

- **Page one is the navy Signature cover**: project title, a "Timesheet for
  <period>" subtitle, and the meta band with Client, Engagement, Period,
  Report date, Prepared by, Contact, and Reference (when present).
- **Page two opens the content** with the standard running header and footer:
  an Overview section with an optional **budget utilisation stat band** (budget,
  logged to date, utilisation, remaining, plus a slim progress bar) and an
  always present **hours chart** with distinct bucket colours, a cumulative
  line, explicit axis titles, and a dashed budget line when a budget is set.
  The chart is pure inline SVG generated in Python, with no chart library.
- **The optional Work mix section** appears when the payload supplies four to
  eight categories. It defines the colour system, identifies the leading work
  types, and calculates a summary table of total hours and percentage share.
- **The activity log** is one compact zebra striped table: Date, an optional By
  column for multi consultant sheets, Description, Hours, and an optional
  Amount column. When the period spans several months the table carries month
  band subheader rows and month subtotal rows. Category colours mark each row
  without changing the chronological order. The navy total row closes it.
- **The approval block** (text plus the two signature lines and the Numaco
  address and VAT foot line) always stays together on one page.

The engine is `scripts/build_timesheet.py`: it takes a JSON payload, validates
it strictly, composes the structure from the shared Signature module
(`shared/signature/signature.py`), applies the shared Signal Stack presentation,
and renders through the shared paged renderer. The two pass render bakes the
true page count into the footer. CoreGraphics verifies the result.

## When to trigger (be generous)

- "Timesheet for <customer> <period>", "hours report", "Stundenrapport".
- "Monthly hours", "quarterly hours", "bill the hours for <project>".
- "Turn my Clockify hours for <customer> into a timesheet."
- "Where do we stand against the support budget", when the answer should be a
  customer facing document.
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
and ask the user to confirm. Two optional labels refine the cover: an
`engagement` line (a short description of the engagement, shown in the cover
meta band; the project title serves when absent) and the `report_date` (pass
today's date; the engine never calls the clock itself, so the payload stays
reproducible).

### Step 1b: allocate the document number

**A timesheet takes its own number from the shared Numaco `YYDDDN` series.** It is never the accompanying SOW's number with a suffix bolted on, and never that number reused. Tenant precedent is unambiguous: `Timesheet 253507`, `Timesheet 260039`, `Arbeitsrapport 252319`, all bare six-digit numbers of their own.

Generate it, never invent it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-timesheet/scripts/generate_timesheet_number.py" --data-dir "<sales-docs>"
```

The number goes into `reference` and into the filename: `Timesheet <number> - <customer> - <period>.pdf`.

**When the same sitting produces a SOW and its timesheet, allocate both in ONE call with `--count 2`.** The collision scan reads filenames on disk, so two separate calls made before either file is written return the same number twice. The full rules (including why QU/OC/DN/IN for one transaction do share a number) live in `shared/numbering/document_number.py`, which both skills shim over.

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

Set `by` on every entry when the sheet should show who filed each line, and
always on multi-consultant sheets. Format: first name plus surname initial with
a period, for example "Petra M."; the By column renders as soon as any entry
carries one.

### Step 3: classify the work

For a substantive support or delivery timesheet, inspect the approved entry
descriptions and propose a manageable set of four to eight primary categories.
Choose categories that describe the work at a useful management level, not
individual tickets or technologies. Common families include coordination and
project management, technical design, issue management and support,
development and enhancement, configuration and rollout, and testing,
validation and handover.

Give every entry exactly one primary category. Keep the table grouped by month
and chronological within each month. The renderer calculates total hours and
percentage share, builds the Work mix insight page, and applies the category
colour to the matching activity rows. Use stable `key` values across recurring
timesheets. A small or simple sheet may omit categories entirely; never provide
fewer than four categories merely to force a Work mix page.

### Step 4: establish the budget (when there is one)

Ask whether the engagement runs against an hours budget. The budget figure
comes **from the SOW for that engagement or from the user**; never invent one
and never take one from the examples in this skill. When a budget is given,
the overview page gains the utilisation stat band and the chart gains the
dashed budget line. When the budget spans longer than the reported period (an
annual budget reported quarterly, for example), also supply `prior_hours`: the
hours already logged under the same budget before the period start, taken from
the earlier timesheets or the finance overview. Without it the utilisation
figures would mislead. Without a budget the chart still renders, hours and
cumulative only.

### Step 5: confirm hours only versus with amounts

Ask whether the sheet should show hours only (the default, and the usual
choice when the timesheet accompanies a separate invoice) or an Amount column.
When amounts are wanted, the day rate comes from the user's local defaults file
(`~/.config/numaco-design/defaults.toml`, or the `NUMACO_DESIGN_DEFAULTS`
path), from prior documents for the same customer, or from the user directly.
**Never take a rate from the examples in this skill or its sample**; those
numbers are deliberately absurd placeholders. Each amount is computed as hours
divided by 8, multiplied by the day rate.

### Step 6: render

Assemble the JSON payload (schema below) and render:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-timesheet/scripts/build_timesheet.py" payload.json "/abs/path/Timesheet <reference> - <customer> - <period>.pdf"
```

The engine writes a self-contained HTML sidecar next to the PDF and renders the
PDF through the shared paged pipeline. Save the PDF to the customer's project
folder, never into any repository.

### Step 7: verify through CoreGraphics

Verify the PDF through CoreGraphics, never a Chromium preview: run
`numaco_render.pdfcheck(pdf, name, pages="1,2,...")` (the sample script shows
the call) and inspect the rasterised pages, or open the PDF in macOS Preview.
Check the cover carries the meta band, the chart shows the bars and the
cumulative line (and the budget line when set), every axis title is legible,
the Work mix totals add to 100 percent when categories are present, category
markers agree with the definitions, month subtotals add up, and the total row
matches the sum. Present the PDF to the user and iterate until they approve.

## Recurring timesheets (series consistency)

A timesheet is usually one of a series (monthly or quarterly for the same
engagement), and the series must look identical from period to period. The
layout itself is code, so per-document consistency is guaranteed; what can
drift are the payload options. Rules:

- Save the payload JSON next to each filed PDF. Start the next period from the
  previous period's payload: change only `period_*`, `report_date`, `entries`,
  and `prior_hours` (carry it forward: previous `prior_hours` plus the previous
  period's total).
- Keep everything else identical across the series (`budget_hours`, categories,
  hours only versus amounts, the By column, `reference`, `engagement`,
  consultant) unless the engagement itself changed, and say so to the user
  when it does.

## Payload schema

> **GUARDRAIL: `day_rate_chf: 100` below is a deliberately absurd placeholder**
> (nobody bills CHF 100 per day), as is every example amount in this skill.
> Never carry an example number into a real timesheet payload. Real rates come
> only from the user's defaults file, from prior documents for that customer,
> or from the user directly. The same discipline applies to `budget_hours`:
> real budgets come from the SOW or the user, never from examples.

```json
{
  "client_legal_name": "Acme Labs AG",
  "client_address": ["Industriestrasse 12", "CH-8600 Duebendorf"],
  "project_title": "Chromatogram report archival service",
  "engagement": "Archival service build, rollout, and support",
  "period_label": "Q2 2026",
  "period_start": "2026-04-01",
  "period_end": "2026-06-30",
  "report_date": "2026-07-02",
  "reference": "261913",
  "consultant": "Alex Muster",
  "budget_hours": 120,
  "prior_hours": 30,
  "categories": [
    {
      "key": "coordination",
      "name": "Coordination and project management",
      "description": "Planning, reporting, and stakeholder coordination.",
      "color": "#3f65a6"
    },
    {
      "key": "design",
      "name": "Technical design and advisory",
      "description": "Analysis, solution design, and technical advice.",
      "color": "#c98a14"
    },
    {
      "key": "development",
      "name": "Development and enhancement",
      "description": "New capabilities and material improvements.",
      "color": "#1f7a8c"
    },
    {
      "key": "validation",
      "name": "Testing, validation and handover",
      "description": "Verification, release preparation, and handover.",
      "color": "#5b8f7b"
    }
  ],
  "entries": [
    {"date": "2026-04-03", "by": "Petra M.", "description": "Kick-off and scoping.", "hours": 3.5, "category": "coordination"}
  ],
  "day_rate_chf": 100,
  "notes": "All hours were recorded against SOW 261912.",
  "output_path": "/abs/path/final.pdf"
}
```

- `client_address`, `engagement`, `report_date`, `reference`, `consultant`,
  `budget_hours`, `prior_hours`, `categories`, `day_rate_chf`, `notes`,
  `output_path`, and the per entry `by` are optional; everything else is
  required.
- `reference` is the timesheet's OWN six digit number from the shared Numaco
  `YYDDDN` series, produced by `scripts/generate_timesheet_number.py` (step 1b).
  It is never a SOW number, and never a SOW number with a suffix: `262180-07` is
  not a Numaco number. If the same sitting also produced a SOW, the two numbers
  are consecutive, allocated together with `--count 2`.
- `engagement` present: shown as the Engagement line in the cover meta band;
  absent: the project title serves as that line.
- `report_date` is the date shown on the cover. Pass today's date; when absent
  the engine falls back to `period_end`. The engine never reads the clock, so
  a given payload always renders the same document.
- `budget_hours` present (number > 0): the overview gains the budget
  utilisation stat band and the chart gains the dashed budget line, with the
  y axis scaled to the larger of budget and cumulative hours.
- `prior_hours` (number >= 0, default 0): hours already logged under the same
  budget before `period_start`. Counted into logged to date, utilisation,
  remaining, and the progress bar (with a small carry caption under the band),
  and used as the starting baseline of the chart's cumulative line. The bars
  stay period hours only. Supply it whenever the budget spans longer than the
  reported period.
- Entries with `by` (short consultant names): the By column renders between
  Date and Description as soon as any entry carries one; when none do, the
  column is omitted entirely.
- `categories` present: supply four to eight objects with unique `key`, `name`,
  and `description` values. A six digit hexadecimal `color` is optional; the
  renderer assigns a stable palette colour when omitted. Every entry must then
  carry `category` and reference a defined key. The renderer adds the Work mix
  page and category markers. When `categories` is absent, entries must not
  carry `category`, and the timesheet renders without the Work mix page.
- `day_rate_chf` present: an Amount column appears, each amount computed at
  hours / 8 x rate, with per month subtotal amounts and a total amount. Absent:
  the sheet is hours-only and no money appears anywhere.
- `consultant` absent: the engine falls back to the second contact in the
  user's defaults file (the same `[[sow.contacts]]` block the SOW skill uses);
  if there is none, the consultant line is omitted.
- Validation is strict and fails loudly: every entry date must be an ISO date
  inside the period, every hours value must be greater than zero,
  `budget_hours` and `day_rate_chf` must be positive when given, `prior_hours`
  must not be negative, category keys and references must be valid, and missing
  required fields abort the render with a list of every violation.

## Formatting rules (enforced by the engine)

- Dates render as `dd.mm.yyyy`; the period line reads
  `<label> (dd.mm.yyyy to dd.mm.yyyy)`.
- Hours render with one decimal (`3.5`, `8.0`); quarter hours keep two. Stat
  figures and chart captions drop the decimals on whole values (`120 h`).
- Amounts render Swiss style through the shared module: apostrophe thousands
  separator and `.-` for whole francs (`CHF 12'000.-`), amounts excluding VAT.
- Chart bucketing: monthly buckets when the period spans more than one
  calendar month, else weekly buckets on ISO weeks (labeled `W24` style with
  the week's date range in small text). Empty buckets stay on the axis so the
  timeline is continuous.
- Chart bars use distinct colours, with larger value labels and explicit Hours
  and Months or Weeks axis titles. The cumulative line remains dark navy and
  the budget line remains amber, so neither can be confused with a work
  category.
- Category totals are calculated from the rendered entries, never supplied by
  the caller. The summary ranks categories by hours and shows both hours and
  percentage share. Category markers add meaning without replacing the zebra
  striping, month bands, or chronological ordering.
- When the period spans several months, the table groups entries under a month
  band subheader row with a quiet subtotal row per month; the closing total
  row is the same navy band with the amber accent as the SOW effort estimate
  total. Entry rows are compact and zebra striped; the stripes restart at each
  month so the bands never shift the pattern.
- When utilisation exceeds 100 percent, the progress bar caps at full and the
  remaining figure shows the overrun as a negative in the amber accent.
- Prose on the sheet never uses dashes as punctuation.

## GUARDRAILS

- **Real customer timesheets are deliverables.** They belong in the customer's
  project folder. Never commit a rendered timesheet, its HTML sidecar, or a
  real payload to this repository; this repository is public.
- **The bundled sample is fictional.** Client Acme Labs AG, invented project,
  invented consultants, invented entries and budget. It proves the pipeline,
  nothing more.
- **Every example number is a deliberately absurd placeholder** (CHF 12.50 per
  hour, CHF 100 per day, 10 percent discount). Real rates never come from
  examples; see Step 5. Real budgets come from the SOW or the user; see
  Step 4.
- **Internal tracking notes never leak.** Descriptions pulled from a time
  tracker are reviewed and rewritten for the customer before rendering.

## Files

```
numaco-timesheet/
├── SKILL.md                       <- you are here
├── scripts/
│   └── build_timesheet.py         <- JSON payload -> Signal Stack branded PDF
└── sample/
    ├── build_sample.py            <- renders the fictional Acme sample
    ├── sample_payload.json        <- fictional categorised payload (15 entries)
    ├── sample_timesheet.html      <- generated, gitignored
    └── sample_timesheet.pdf       <- generated, gitignored
```

The engine composes the locked Signature structure (`shared/signature/`), the
shared Signal Stack presentation (`shared/signal-stack/`), and the shared
renderer (`shared/render/numaco_render.py`). It never invents a new render path.
Its timesheet specific style block covers compact activity rows, month bands,
the stat band, Work mix components, chart legend, category markers, and the
keep together approval. The chart SVG bakes the same palette values used by the
document styles.

## Relationship to the other skills

- `numaco-sow`: Statements of Work, quotations framed as offers, proposals.
  The SOW's Acceptance term is what makes this timesheet the invoicing basis,
  and its effort estimate is where the hours budget comes from.
- `numaco-report`: the general branded document engine for reports, memos,
  handovers, and letters.
- `numaco-timesheet`: this skill, the hours report member of the transactional
  document family.
