---
name: numaco-report
description: Produce a Numaco AG branded document as a PDF, from a single Markdown file, through the shared HTML to PDF pipeline. Use whenever the user asks for a document "in Numaco's template", "with Numaco branding", "in the Numaco style", or by default for ANY standalone branded report, memo, one-pager, architecture overview, handover, solution design, or letter for Numaco, unless they explicitly ask for something unbranded. Successor to the old numaco-docx skill (same visual identity, PDF-native instead of Word). This is the general branded-document engine and the future home for timesheets, quotations, purchase orders, and invoices.
status: beta
version: 0.1.0
---

# Numaco branded report skill (HTML to PDF)

The general-purpose branded-document engine for Numaco AG. Where `numaco-sow` is
shaped tightly around Statements of Work, this skill produces any body document
that should wear Numaco's visual identity: reports, memos, one-pagers,
architecture overviews, handovers, solution designs, letters. It is the future
home for the transactional document family too (timesheets, quotations, purchase
orders, invoices), which is why the engine already ships a first-class line-items
table with computed totals.

This is the renamed, HTML-pipeline successor to `numaco-docx`. Same navy and teal
identity, same cover, same block vocabulary; the difference is that the
deliverable is now a PDF rendered from HTML through the shared numaco-design
renderer (Paged.js), not a Word file. There is no `.docx` step and no LibreOffice
or Word dependency.

## When to trigger (be generous)

Triggers include, but are not limited to:

- "Write a report / memo / one-pager in Numaco branding."
- "Use the Numaco template" or "in our template" or "in the Numaco style".
- "Make me an architecture overview / solution design / handover for <customer>."
- Any ad-hoc request for a standalone branded Numaco document where the user does not
  explicitly ask for something unbranded.

If the user asks for a Statement of Work, quotation, or offer, defer to `numaco-sow`.
For any other branded document, use this skill. When in doubt, use this skill
rather than hand-writing HTML or CSS from scratch.

## How it works

One Python engine, `scripts/build_report.py`, is the whole skill. It takes a
single Markdown file that carries a YAML front-matter header, maps the Markdown
onto the shared `numaco-doc.css` component vocabulary, assembles a self-contained
offline HTML page (all CSS inlined, all images embedded as data URIs, Manrope
embedded), renders it to A4 PDF through the shared paged renderer, and runs the
CoreGraphics fidelity check.

### Workflow

1. Draft the document as Markdown with a front-matter header (schema below). Put
   the `.md` next to where you want the PDF, or in a scratch folder.
2. Run the engine:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-report/scripts/build_report.py" <input.md> <output.pdf>
   ```

3. The engine writes `<output>.html` alongside the PDF, renders the PDF, prints
   the page count, and drops CoreGraphics PNGs of pages 1 to 3 in the pdfcheck
   temp folder. Inspect those (or open the PDF in Preview) before sending it on.
4. Present the PDF to the user for review.

The PDF is always the authoritative deliverable. Verify it through CoreGraphics
or macOS Preview, never a Chromium-only preview.

## Front-matter schema

```yaml
---
doc_type: Solution design        # free label, informational
title: Central Print Module      # cover / document title
subtitle: Solution design for X  # italic sub-title (optional)
prepared_for: Acme Labs AG       # cover meta (optional)
date: July 2026                  # cover meta (optional)
doc_number: 261910               # teal "# <n>" under the title (optional)
cover: true                      # emit the cover section (default true)
watermark: true                  # per-page corner watermark (default true)
---
```

Only `title` is really needed. Set `cover: false` for a memo or short internal
note that should skip the cover page but keep the header, footer, and watermark.
Set `watermark: false` for a clean, watermark-free page.

## Body Markdown vocabulary

Standard Markdown maps onto the branded components. The mapping:

| Markdown | Renders as |
|---|---|
| `# Heading` | navy ruled H1 section heading |
| `## Heading` | teal H2 sub-heading |
| `### Heading` | small navy H3 sub-sub-heading |
| paragraph | justified body `<p>` in Manrope |
| `- item` | `ul.doc` bullet (em-dash marker) |
| `- Title -- body` | bullet with the title split out in bold |
| `1. item` | numbered scope-item; a leading `S1:` / `A1:` label is honoured, and `Title -- body` splits the bold summary |
| Markdown table | `table.doc` (teal header, zebra rows) |
| `\| =Total \| ... \|` | a row whose first cell starts with `=` becomes the navy total row |
| `---:` alignment | right-aligns that column and its numbers |
| `> quote` | `.small` fine print |
| `:::small ... :::` | `.small` fine print (multi-line) |
| `:::note ... :::` | italic `.footnote` note |
| `:::appendix ... :::` | `.appendix` fine-print section (page break, 8pt) |
| `:::items {json} :::` | line-items table with computed subtotal / tax / grand-total |
| `:::pagebreak` or `---` | hard page break |

Inline: `**bold**`, `*italic*`, `` `code` ``.

### Bullet and scope-item title splits

Write a bullet or a numbered item as `Title -- body`, `Title : body`, or
`Title | body`; the engine renders the part before the separator in bold. For a
numbered item you can supply an explicit label, for example
`1. S1: Native writer -- captures ZPL and renders it inline`, which renders as a
labelled scope-item (`S1:` in the hanging gutter, `Native writer` bold, then the
body).

### Tables

Use ordinary Markdown tables. Mark a column's alignment row with `---:` to
right-align that column, which is what you want for numeric columns (days,
amounts). Start the first cell of a row with `=` to turn that row into the navy
bold total row, for example `| =BASE TOTAL | 48.0 | CHF 4'800.- |`.

### Line-items table (for quotations, POs, invoices)

Drop a fenced JSON block to get a first-class line-items table with computed
money. The engine multiplies quantity by unit price per line, sums the subtotal,
applies the tax rate, and adds the grand total; all amounts are formatted
Swiss-style (`CHF 1'500.00`).

```
:::items
{
  "currency": "CHF",
  "tax_rate": 0.081,
  "tax_label": "VAT 8.1%",
  "items": [
    {"description": "Module license, annual", "qty": 1, "unit_price": 1200},
    {"description": "Compute, per node per month", "qty": 12, "unit_price": 25}
  ]
}
:::
```

`tax_rate` may be `0` (or omitted) to suppress the tax row. This block is the
seam along which the future quotation, purchase-order, and invoice document types
will be built.

## Visual conventions (inherited from the shared brand core)

- **Page**: A4 portrait, 20 mm top / 18 mm sides / 22 mm bottom margins.
- **Font**: Manrope throughout (embedded, offline), justified body text.
- **Colours**: navy `#0E2841` for the title, H1 rules, total rows; teal
  `#156082` for the doc number, H2 sub-headings, and table headers; subtle grey
  `#F2F2F2` zebra stripes.
- **Cover**: centred wordmark (~68 mm), navy 30pt title, teal doc number, italic
  subtitle, then the "Prepared for" and "Date" meta block.
- **Watermark**: light-grey Numaco monogram anchored top-right of every content
  page, suppressed on the cover.
- **Footer**: `Numaco AG · Haldenstrasse 3c · CH-8905 Islisberg · numaco.ch`,
  with `Page N of M` on the right, on every content page.

## Rules and conventions

1. Author documents in English unless the user explicitly asks for another language.
2. Body text is justified by default; do not fight it.
3. Keep everything self-contained and offline: the engine inlines all CSS and
   embeds every image as a data URI. Never link an external file or a CDN.
4. Do not hand-write branded HTML or a bespoke stylesheet. Drive the engine with
   Markdown. If a component is missing, extend `build_report.py` and
   `shared/brand-core/numaco-doc.css` rather than bypassing them, so the whole
   Numaco document family stays consistent.
5. Verify the PDF through CoreGraphics or Preview, not a Chromium-only preview.

## Files

```
numaco-report/
├── SKILL.md                     ← you are here
├── scripts/
│   └── build_report.py          ← the data-driven Markdown -> branded PDF engine
└── sample/
    ├── sample_report.md         ← a realistic multi-page example (all block types)
    ├── sample_report.html       ← assembled HTML (generated)
    └── sample_report.pdf        ← rendered PDF (generated)
```

The engine reuses the shared renderer at
`shared/render/numaco_render.py` (paged mode, CoreGraphics check) and the shared
stylesheet and assets at `shared/brand-core/`. It never invents a new render
path.

## Relationship to the other skills

- `numaco-sow`: the specialised Statement of Work skill (fixed structure, effort
  table, T&Cs appendix, interactive budget, SOW number generator). Defer to it
  for SOWs, quotations framed as offers, and proposals.
- `numaco-report`: the general branded-document engine (this skill), and the
  future home for timesheets, quotations, purchase orders, and invoices via the
  line-items component.

## Migration note

This skill replaces `numaco-docx`. The block vocabulary is preserved one to one
(cover, H1/H2/H3, justified paragraphs, bullets with bold-title splits, numbered
scope-items, styled tables with total rows, small print, page breaks), so nothing
regresses. The only change is the pipeline: Markdown to HTML to PDF, with no Word
or LibreOffice dependency, and the line-items table is new.
