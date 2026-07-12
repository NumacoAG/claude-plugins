---
name: numaco-sow
description: Draft, iterate on, and generate a Numaco AG Statement of Work (SOW) as a branded PDF for approval. Use whenever the user asks to write, draft, prepare, or quote an SOW, proposal, quotation, or offer for any customer, even if the customer name is given casually (e.g. "write an SOW for Acme", "quote 10 days for a system migration"). Also use when editing, revising, or extending an existing SOW (change requests). The skill runs as an interactive conversation: it gathers inputs, drafts sections in chat for approval, opens a live budget artifact for iteration, renders the branded PDF, and only finalises once the user confirms. Do not generate an SOW in a single step without running the conversation protocol below.
status: beta
version: 0.1.0
---

# Numaco SOW skill (HTML pipeline)

## What this skill does

Produces Numaco-branded Statements of Work end to end, via an interactive conversation. The user should be able to say *"write an SOW for &lt;customer&gt;, &lt;short scope&gt;, &lt;rough effort&gt;"* and end up with a finished branded PDF saved to the right customer folder, without ever editing a document by hand.

This is the HTML pipeline rewrite of the SOW skill: instead of python-docx, the final PDF is assembled as self-contained branded HTML (Manrope + the shared `numaco-doc.css`) and rendered through the shared `numaco_render` paged pipeline (puppeteer-core plus Paged.js). The final deliverable is the PDF.

## Golden rules

1. **Draft in chat first, then render the doc.** Never generate the PDF in one shot. Always walk the user through the sections as plain text in chat, iterate with them, and only run the render step after they explicitly say *"generate"* / *"write the doc"* / similar.
2. **The budget goes in an interactive artifact, not in chat.** Use a live budget artifact for the effort estimate. The user iterates live; values come back to chat only when they commit.
3. **Ask for the rate every time, with context.** Never hard-code a rate. Look up the customer's history and comparable customers first, then ask.
4. **Never invent SOW numbers.** Generate them via the algorithm in *SOW number generation* and check for collisions against existing files.
5. **English only.** Unless the user explicitly asks for another language.
6. **Respect the project rule**: confirm each new file write the first time. After the first SOW to a new customer folder, subsequent SOWs to the same folder do not need to re-ask.

## Company constants (do not change without the user's explicit approval)

Registered/operating address shown on all SOWs:

```
Numaco AG
Haldenstrasse 3c
CH-8905 Islisberg
Switzerland
```

VAT / UID: `CHE-107.980.861 MWST`
Website: `https://www.numaco.ch`

**Ignore** the Moehlin address in any stale template or T&Cs footer. The commercial register may still show Moehlin; SOWs always use Islisberg. Postcode is `8905` (Aargau / Bremgarten district). `9805` is a typo that travelled through older SOWs, do not reproduce it.

Default Numaco contacts in the SOW Parties block:

- **Financials**: Finance contact, `finance@numaco.ch`
- **Engineering**: Your Name, `you@numaco.ch`

These constants are baked into `scripts/build_sow.py` (address, VAT, and the two contacts). The renderer hardcodes the supplier side of the parties table so it can never drift.

## Conversation protocol

Follow these steps in order. Do not skip the confirmation between steps.

### Step 1 — Understand the request

Extract from the user's message:
- Customer name
- Short project title / scope keywords
- Rough effort (days, weeks, or an explicit total)
- Any special terms they mention (deadline, fixed price, onsite, etc.)

Echo back what you understood in 2 to 3 lines and ask them only for what is genuinely missing. Do not run a long questionnaire.

### Step 2 — Gather the missing inputs

Minimum you need before drafting:

| Input | Source |
|---|---|
| Customer legal name + address | Ask the user, or look it up in existing SOWs for the same customer |
| Customer key contact(s) | Ask the user |
| Scope outline (what they want) | Ask the user, or propose based on project context |
| Out of scope (what is explicitly excluded) | Ask the user. This is a required section, do not skip it. |
| Assumptions | Derive from scope; confirm with the user |
| Target start (month) | Ask the user |

For repeat customers, pre-fill from the most recent SOW for the same customer and ask the user only to confirm or correct.

### Step 3 — Draft Context and Scope in chat

Write as plain markdown in the chat, clearly labelled by section. Use the tone and structure described in *Writing style* below.

Present:
- **Context**: 1 to 2 short paragraphs. Who the client is, the situation, the problem this SOW addresses.
- **Scope, What we deliver**: 4 to 8 items, specific outcomes or artefacts, not activities.
- **Scope, What we do not deliver**: 3 to 6 items, explicit exclusions.
- **Assumptions**: 2 to 5 items, what must be true for the engagement to work.
- **Optional add-ons** (if any): each with a short heading and a 2 to 4 sentence paragraph that leads with business impact and then describes what is actually delivered.

Ask the user to push back on wording. Iterate until they approve.

### Step 4 — Rate lookup and selection

Before drafting the commercial section, run the rate lookup procedure:

1. Search the customer's project folder for prior SOWs. Parse each to extract the day rate (or hourly rate x 8). Report to the user: *"For &lt;Customer&gt;, you used CHF X / day in SOW &lt;number&gt; dated &lt;date&gt;."* List all prior SOWs if more than one.
2. If no prior SOW for this customer, look up 2 to 3 comparable customers, using this definition of *similar*:
   - Same industry (pharma, food, industrial, chemicals, etc.), plus
   - Same engagement type (T&M consulting vs. fixed-price vs. software resale), plus
   - Most recent first (last 12 months preferred).
   - If fewer than two matches fit, relax to "same engagement type only" and flag the match quality as loose.
3. Present the findings in chat. Then ask the user which rate to use for this SOW. Accept their answer as given.

### Step 5 — Interactive budget artifact

Once scope is approved and the rate is chosen, open the live budget artifact.

Artifact spec:

- Table with editable rows. Columns: *Workstream / item*, *Days*, (computed) *Amount CHF*. Plus a Delete-row button on each row.
- Do NOT add a cap / budget-ceiling column. We tried that, and it added more friction than it solved.
- Rate card at top: editable list rate (CHF/hour), editable customer discount (%), computed effective day rate.
- Live totals row: total days, total CHF amount (Swiss formatting: apostrophe thousands separator, `.-` for zero cents, e.g. `12'800.-`).
- A separate "base engagement only" readout so the user can see that number even when the table also includes add-ons.
- A *Commit to SOW* control that copies a formatted summary the user can paste into chat.
- Prefill the artifact with a sensible first draft (propose workstreams from the approved scope). Tell the user they can iterate as many times as they want and the chat stays clean until they commit.

Example committed payload:

  ```
  Commit these budget values to the Acme SOW:

  List rate: CHF 150.00 / hour (CHF 1200.00 / day)
  Customer discount: 35%
  Effective rate: CHF 780.00 / day

  Workstreams:
  - Base engagement: 1.25 days = CHF 975.00
  - Add-on #1 CSV validation: 0.25 days = CHF 195.00
  ...
  ```

### Step 6 — Draft Commercial section in chat

Once budget is committed, draft the Commercial terms section in chat using the boilerplate in *Text library, Commercial* below, substituting the chosen day rate and total amount.

### Step 7 — Final review

Post the full SOW content in chat, section by section, one more time. Ask the user: *"Ready to generate? Any last changes?"*

### Step 8 — Render the branded PDF (HTML pipeline)

Only after the user says yes:

1. Generate the SOW number with `scripts/generate_sow_number.py` (see *SOW number generation*).
2. Compute the filename: `SOW <number> - <customer> - <project>.pdf`.
3. Determine the output folder (see *Output folder*).
4. Assemble a JSON payload with all the filled fields (schema below) and render it:
   ```bash
   python3 scripts/build_sow.py payload.json "/abs/path/SOW <number> - <customer> - <project>.pdf"
   ```
   `build_sow.py` writes a self-contained HTML sidecar next to the PDF and renders the PDF through the shared `numaco_render` paged pipeline. The PDF carries the Numaco cover, the light-grey monogram watermark on content pages (suppressed on the cover), the running footer with address and VAT, page numbers, the parties table, the effort table, and the T&Cs appendix.
5. **Verify the PDF through CoreGraphics, not Chrome.** Run `numaco_render.pdfcheck(pdf, name, pages="1,2,3")` (and the last page) and eyeball the rasterised pages. This is the macOS Preview engine; never trust a Chromium-only preview or `qlmanage -t`.
6. Present the PDF to the user and ask them to review. When the user asks for edits, update the payload, re-render, re-check, present again. Loop until the user says *approve*.

The JSON payload contract (same as the legacy renderer, see the header of `scripts/build_sow.py` for the authoritative copy):

```json
{
  "sow_number": "261912",
  "issue_date": "July 2026",
  "project_title": "ZPL to PDF label archival service",
  "client_legal_name": "Acme Labs AG",
  "client_address": ["Industriestrasse 12", "CH-8600 Duebendorf", "Switzerland"],
  "client_contacts": [{"name": "Petra Meier", "email": "petra.meier@acmelabs.ch", "role": "Head of IT"}],
  "context": "Paragraph 1.\n\nParagraph 2.",
  "deliverables": [{"summary": "short label", "body": "full sentence."}, "plain string works too"],
  "exclusions": [{"summary": "short label", "body": "full sentence."}],
  "assumptions": [{"summary": "short label", "body": "full sentence."}],
  "workstreams": [{"name": "Scope and analysis", "days": 3.0}],
  "day_rate_chf": 1400,
  "payment_days": 60,
  "optional_addons": [{"number": 1, "title": "CSV schema validation", "days": 1.0, "body": "business-impact pitch then what is delivered"}],
  "day_rate_narrative": "optional override (e.g. list rate then discount then effective rate)",
  "total_amount_narrative": "optional override",
  "output_path": "/abs/path/final.pdf"
}
```

A ready-to-run example lives in `sample/build_sample.py` (client Acme Labs AG, four workstreams, one optional add-on). It renders `sample/sample_sow.pdf` and runs the CoreGraphics check.

## SOW number generation

Format: `YYDDDN` where
- `YY` = two-digit year (e.g. `26` for 2026)
- `DDD` = day of year, zero-padded (001 to 366). For 2026-04-23 this is `113`.
- `N` = a single collision-avoidance digit 0 to 9.

Algorithm:

1. Compute `YYDDD` from today's date.
2. Search the Numaco data directory recursively for filenames containing any number matching the prefix `YYDDD`. Collect the trailing digits already used.
3. Pick the smallest unused digit 0 to 9 as `N`.
4. If all ten are taken (very unlikely), pad with a second digit and tell the user.

Implementation: `scripts/generate_sow_number.py`. The data directory is configurable and never assumed to exist: pass `--data-dir "<path>"` or set `NUMACO_DATA_DIR`; with no data dir the scan finds no collisions and `N` starts at 0.

## Output folder

Default target: the customer's project folder, in a `SOW/` subfolder.

- If the customer folder does not exist: create it and ask the user once for permission.
- If it exists but has no `SOW/` subfolder: create `SOW/`. If the customer already uses a differently named subfolder (e.g. `Project and Financial Documents/`, `Financials/`), use that existing folder instead, detected via a listing.
- the user has indicated they will restructure this later; do not block on the naming mess.

## Writing style

- Formal but clean. No marketing fluff. No dashes used as punctuation (use commas, colons, semicolons, periods, or parentheses).
- Third person throughout: *"Numaco will..."* not *"we will..."*. Customer referred to as *"the client"* in definitional contexts and by legal name elsewhere.
- Future tense for commitments: *"Numaco will deliver..."*, *"The solution will support..."*.
- Bullets for lists of deliverables, exclusions, assumptions. Prose for context and commercial paragraphs.
- CHF amounts formatted Swiss-style with apostrophe thousands separator and `.-` for zero cents, e.g. `CHF 12'800.-`.
- No quotes around currency symbols or amounts.
- Dates in ISO-like form where possible (e.g. `May 2026`), not `05/26`.

## Document structure (what the PDF contains)

Fixed section order, enforced by `scripts/build_sow.py`.

1. **Cover** (`.doc-cover`): wordmark, "Statement of Work" title, `# <sow_number>`, italic project title, "Prepared for &lt;client&gt;", issue date. The watermark is suppressed on the cover.
2. **Parties table** (`table.parties`): teal headers "The Client" / "The Supplier". The supplier cell is hardcoded to the Numaco address, VAT, and the two named contacts.
3. **1. Context**: 1 to 2 short paragraphs.
4. **2. Scope** with sub-blocks, each item labelled with a letter-prefixed number that stays stable across revisions:
   - *What we deliver*: items labelled **S1, S2, S3, ...**
   - *What we do not deliver*: items labelled **N1, N2, N3, ...**
   - *Assumptions*: items labelled **A1, A2, A3, ...**
   - *Optional add-ons*: headings labelled **O1, O2, O3, ...** (navy, bold), each with a business-impact body. **Do NOT write days or price inside the Scope section**; effort and amount live in the effort table only. In the payload, each deliverable/exclusion/assumption item is either a plain string or a dict `{"summary": "...", "body": "..."}`. Numbering is stable across revisions.
5. **3. Effort estimate**: a single `table.doc` (Workstream ~70%, Days ~12%, Amount ~18%). Base rows show `days x day_rate_chf`. If add-ons are present, a merged separator row reads *"Optional add-ons (priced separately, not included in the total below)"*, then the add-on rows render in grey italic. The navy total row shows the **base engagement total only**, never the all-items sum. A small footnote covers billing on time actually worked and the PO amendment for add-ons.
6. **4. Commercial terms**: the T&M intro, then labelled terms Day rate, Work outside standard hours, Travel, Total estimated amount, Payment, Acceptance. When a customer discount applies, pass `day_rate_narrative` to show the full calculation (list rate, discount, effective rate).
7. **5. Activation**: single paragraph. The SOW activates on a PO referencing this document, no formal signatures.
8. **Appendix: Terms and Conditions**: full text at ~8pt, page break before, verbatim from `references/tcs_body.md`.

## Visual conventions (enforced by `numaco-doc.css` + `scripts/build_sow.py`)

- **Font**: Manrope, embedded via the shared brand core.
- **Colour palette**: navy `#0E2841` for section headings and the effort-table grand-total; teal `#156082` for the parties-table header, the effort-table header, and sub-headings. Same blue family on purpose.
- **Body text is justified**. Headings, cover titles, and the footer are not justified.
- **Parties table**: two columns (Client, Supplier), teal header, body cells top-aligned so both addresses start at the same baseline.
- **Effort table**: teal header, subtle zebra on base rows, grey italic add-on rows, a light-grey separator above add-ons, navy base-engagement total at the bottom.
- **Watermark**: light-grey Numaco monogram anchored top-right of every content page, injected by `build_sow.py` as an `@page` background from the embedded watermark data URI; the cover page suppresses it.
- **Ligatures are disabled** in the body so the literal `(c)` in the commercial boilerplate does not render as a copyright glyph.

## Text library — reusable boilerplate

### Commercial terms (substitute the day rate and total amount)

> The work provided under this SOW is based on time and material. Numaco charges only labor effectively accomplished, not the full amount in the estimation. Numaco will inform the client as soon as possible if there is a risk that the estimated costs are exceeded. It is then the client's responsibility to decide whether (a) further work hours under this SOW can be done, (b) a new SOW must be signed, or (c) this SOW will be terminated without further action.
>
> **Day rate**: CHF {{DAY_RATE}} per working day. A working day means 8 hours performed during standard working hours, defined as 08:00 to 17:00 CET on Swiss business days.
>
> **Work outside standard hours**: Evenings, weekends, and Swiss bank holidays require a separate written agreement and are billed at a surcharge to be agreed at the time.
>
> **Travel**: Any travel outside Numaco offices or the customer's Switzerland premises is to be agreed in advance and billed separately.
>
> **Total estimated amount**: CHF {{TOTAL_AMOUNT}} (excluding Swiss VAT).
>
> **Payment**: {{PAYMENT_DAYS}} days net from date of invoice. The invoice for the total amount is sent at the end of the performance.

### Acceptance (rendered as the last labelled term in Commercial)

> All services are recorded in a timesheet with a detailed description of the service. The client may inspect the timesheet at any time. At the end of the performance period Numaco sends the timesheet to the client for review and approval; once approved, it serves as the basis for invoicing.

### Activation

> This SOW is agreed between {{CLIENT_LEGAL_NAME}} and Numaco AG. It is valid without formal signatures and comes into operation with a commercial purchase order that includes a reference to this document.

### Effort footnote

> All effort above is an estimation. Billing is based on time actually worked, as described in section 4 below.

When add-ons are present, the footnote continues:

> Add-ons are optional and priced separately; if the client selects any, its days and amount are added to the total via a PO amendment.

### Add-on separator label (merged effort-table row)

> Optional add-ons (priced separately, not included in the total below)

## References and assets

- `scripts/build_sow.py`: renders the branded PDF from a JSON payload via the shared HTML pipeline. Reuse the shared `numaco_render` API; do not invent a new render path.
- `scripts/generate_sow_number.py`: produces the next unused SOW number by scanning a configurable data dir for collisions.
- `references/tcs_body.md`: the full *Terms and Conditions for IT Business Consulting Services*, embedded as the appendix at small font, verbatim.
- `sample/build_sample.py` and `sample/sample_sow.pdf`: a rendered reference SOW (fake Acme Labs customer) to preview the visual baseline.
- Shared brand core (`shared/brand-core/`): `numaco-doc.css`, embedded Manrope, wordmark and watermark PNGs. Consumed by `build_sow.py`.

## Change requests (CR SOWs)

For extensions to an existing SOW (additional scope on a live engagement):

- Use the same section structure.
- In Context, reference the parent SOW number explicitly: *"This SOW extends the scope of SOW &lt;parent&gt; by..."*.
- Scope: describe only the delta, not the whole parent engagement.
- Effort: show only the additional days.
- Filename: `SOW <new-number> - <customer> - <project> (CR to <parent>).pdf`.

## What NOT to do

- Do not include a phased GxP project-plan grid unless the customer explicitly requires it (e.g. regulated pharma validation work). It is too heavy for most engagements.
- Do not include a three-tier rate table. Show one day rate. Outside hours by separate agreement.
- Do not include a Sites and Systems block as a separate section; fold it into Scope.
- Do not add a Supplier Personnel section naming engineers; it is not useful for the customer and ages fast.
- Do not put the attrition clause in the main body; it is covered by the T&Cs.
- Do not include a "Schedule, Milestones" placeholder saying "to be defined with PM"; timeline discussion happens outside the SOW.
- Do not quote financial figures in chat without first confirming with the user that the value is correct.
- Do not render the PDF before the user has approved all sections in chat.
- Do not write days or price inside the Scope section; they live in the effort table only.
