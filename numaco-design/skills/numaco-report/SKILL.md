---
name: numaco-report
description: Produce a Numaco AG branded document as a PDF, from a single Markdown file, through the shared HTML to PDF pipeline. Use whenever the user asks for a document "in Numaco's template", "with Numaco branding", "in the Numaco style", or by default for any standalone branded report, memo, one-pager, architecture overview, handover, solution design, or letter for Numaco, unless they explicitly ask for something unbranded. Successor to the old numaco-docx skill with the same visual identity and a PDF native workflow. Use the dedicated numaco-timesheet, numaco-trading-documents, numaco-sow, or numaco-slide-deck skill for those document families.
---

# Numaco branded report skill (HTML to PDF)

The general-purpose branded-document engine for Numaco AG. Where `numaco-sow` is
shaped tightly around Statements of Work, this skill produces any body document
that should wear Numaco's visual identity: reports, memos, one-pagers,
architecture overviews, handovers, solution designs, letters. Reports use the
Signal Stack presentation: a dark technical cover, centred navy section bands,
large readable body type, strong numbered subsection rules, stacked evidence
cards, and high contrast data tables. The engine also ships a first-class
line-items table with computed totals for narrative reports that need one.
Transactional documents use the dedicated `numaco-trading-documents` skill.

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

If the user asks for a Statement of Work or scoped service proposal, defer to
`numaco-sow`. If the user asks for a quotation, order confirmation, delivery
note, or invoice, defer to `numaco-trading-documents`. For any other branded
document, use this skill. When in doubt, use this skill
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
| `### Heading` | third-level heading (`h4.subsub`), quieter than `##` and carrying a top margin |
| paragraph | justified body `<p>` in Manrope |
| `- item` | `ul.doc` bullet (em-dash marker) |
| `- Title -- body` | bullet with the title split out in bold |
| `1. item` | numbered scope-item; a leading `S1:` / `A1:` label is honoured, and `Title -- body` splits the bold summary |
| Markdown table | `table.doc` (teal header, zebra rows) |
| `\| =Total \| ... \|` | a row whose first cell starts with `=` becomes the navy total row |
| `---:` alignment | right-aligns that column and its numbers |
| `:---:` alignment | centres that column, heading and body cells together |
| `{green:text}` | the text in brand green, for a status or a verdict that passed |
| `{amber:text}` | the text in brand amber, for a warning or a partial result |
| `{red:text}` | the text in brand red, for a failure or a blocker |
| ` ``` ` fenced block | `pre.code-block` verbatim listing (monospace, whitespace preserved, no inline markdown) |
| `![Caption](image.png)` | centred `figure.figure`, image embedded as a data URI, alt text as the quiet caption below it |
| `![](image.png)` | the same figure with no caption (empty alt text) |
| `![Caption](image.png){width=60%}` | image sized to a share of the text column; `{width=90mm}` sizes it in millimetres |
| `> quote` | `.small` fine print |
| `:::small ... :::` | `.small` fine print (multi-line) |
| `:::note ... :::` | italic `.footnote` note |
| `:::appendix ... :::` | `.appendix` fine-print section (page break, 8pt) |
| `:::items {json} :::` | line-items table with computed subtotal / tax / grand-total |
| `:::pagebreak` or `---` | hard page break |

Inline: `**bold**`, `*italic*`, `` `code` ``, `{green:text}`, `{amber:text}`,
`{red:text}`.

### Semantic colour

Mark a status or a verdict with `{green:text}`, `{amber:text}` or `{red:text}`.
The words render in the brand accent colours (green `#2f7d4f`, amber `#c98a14`,
red `#b3261e`), semibold, and they work in a table cell, in a bullet and in a
paragraph alike:

```
| Site | Verdict | Hours |
|:---|:---:|---:|
| Basel | {green:Pass} | 12.0 |
| Vienna | {amber:Watch} | 8.5 |
| Milan | {red:Blocked} | 22.5 |
```

Three rules keep this honest.

1. Colour is applied to live text, never to an image, so every coloured word
   stays selectable, searchable and copyable in the finished PDF.
2. Colour never carries the meaning on its own. Write the word that says it
   (`Pass`, `Watch`, `Blocked`), so the table still reads correctly in a
   monochrome print and for a colour blind reader. Never write `{red:X}` and
   expect the colour alone to mean "failed".
3. Use it sparingly. A verdict column, a handful of statuses in a summary. A
   page of coloured prose reads as a draft, not as a Numaco document.

Only those three keywords open a marker, and only in that exact lower case
spelling with the colon straight after the word, so ordinary prose is untouched:
`{timeout: 30}`, `{"green": 1}`, a ratio written `a:b` and an unknown keyword
such as `{purple:nope}` all render exactly as typed. Nested inline markup works
(`{green:**Pass**}`). To show the syntax itself rather than use it, put it in a
fenced ` ``` ` block, which is passed through verbatim; an inline `` `code` ``
span is not an escape hatch, because inline markup still resolves inside it.

### Bullet and scope-item title splits

Write a bullet or a numbered item as `Title -- body`, `Title : body`, or
`Title | body`; the engine renders the part before the separator in bold.

`--` and `|` are explicit and take precedence over `:`, which also occurs
incidentally in prose. Four guards keep an incidental colon from bolding half a
paragraph: an item that already opens with `**` is left alone, because you have
marked the title yourself; a colon "title" longer than 80 characters is treated
as prose; a split that would strand a `**` pair is rejected; and a split that
would leave an unclosed `{` is rejected, which is what protects a `{green: ...}`
marker and any braced run you quote in a bullet. So
`- **My title.** Body with a colon: here` renders exactly as written. For a
numbered item you can supply an explicit label, for example
`1. S1: Native writer -- captures ZPL and renders it inline`, which renders as a
labelled scope-item (`S1:` in the hanging gutter, `Native writer` bold, then the
body).

### Tables

Use ordinary Markdown tables, with the standard alignment spellings in the
alignment row. `---:` right-aligns a column, which is what you want for numeric
columns (days, amounts); `:---:` centres one, which suits a short status, a
verdict or a code that would look adrift at either edge; `---` and `:---` are
left, the default. Centring reaches the heading as well as the body cells, so
the column reads as one block. Start the first cell of a row with `=` to turn
that row into the navy bold total row, for example
`| =BASE TOTAL | 48.0 | CHF 4'800.- |`.

Column widths follow the content. A cell carrying a long unbreakable identifier,
say `STO_HL_environmental_monitoring_sample_40x20`, wraps inside its own cell
rather than widening the table: the table stays inside the 174 mm text column
whatever the identifier's length and whatever the column count. Wrapping prefers
a real break point where the text offers one, so a hyphenated or dotted name
breaks at its hyphen or its dot; an underscored or slashed name has no such
point and breaks mid character, because CSS cannot be told to prefer an
underscore. Numeric columns never wrap at all.

The price of keeping the table on the paper is paid by the other columns: in a
table whose columns are already competing for width, a column can be allocated
less than its longest word and an ordinary prose word can then break mid word. A
table whose content fits is untouched. If a wide reconciliation table reads
badly, shorten the labels, drop a column, or move the identifier column to the
end.

### Figures

Place an image with standard Markdown syntax, alone on its own line:

```
![Ruler view of the Planica array label, 100 x 13 mm.](img/arrays_planica_100x13.png)
```

The path resolves against the Markdown file's own directory, so a document and
its images travel together. An absolute path works too, as does a leading `~`.
The engine reads the file and embeds it in the page as a base64 data URI, which
is what keeps the document self-contained and offline; the mime type comes from
the file extension, and `png`, `jpg`, `svg`, `gif` and `webp` are all
recognised. Each distinct image is encoded once, however many times the document
places it.

A path containing parentheses, which is what a browser and Windows both produce
on a duplicate download, needs no special handling:

```
![Array label, second copy.](img/label (1).png)
```

Wrap the path in angle brackets when it nests parentheses more deeply than that:

```
![Array label.](<img/label (1) (a).png>)
```

**The build stops rather than emitting a broken image.** A figure whose file is
missing, unreadable, empty, or not really the format its extension claims (the
engine checks the leading bytes for `png`, `jpg`, `gif` and `webp`, and looks for
an `<svg` element in an `.svg`), a figure pointing at a remote URL, an attribute
other than `width`, and a line that opens with `![` but does not parse as a
complete figure all stop the build with an error naming the file, the resolved
location and the source line. No PDF is written. In particular an image standing
on its own line is never quietly typeset as literal Markdown into a finished
document.

That promise now reaches inside the fences too. `:::note`, `:::small`,
`:::appendix` and a `>` blockquote each join their inner lines into one run of
text, so a figure line inside one of them used to be escaped and printed as
literal Markdown in the finished PDF while the build exited 0. A figure line
inside any of those four now stops the build and says where the figure can
stand. They are not taught to render one, because each emits a paragraph and a
figure is a block that may not live inside a paragraph: the browser closes the
paragraph early and the amber note box comes apart. Neither the 8.4 pt fine
print nor the amber aside has a design register for an image. Put the figure on
its own line in the section body and keep the fence for its text.

The alt text becomes the caption: small, grey and centred under the image, in
the same quiet register as the rest of the fine print. It runs through the usual
inline pass, so `**bold**`, `*italic*` and `` `code` `` all work inside it (the
`alt` attribute carried into the PDF gets the same text with the markers
removed). Leave the alt text empty when a figure needs no caption:

```
![](img/STO_HL_column_50x10.png)
```

By default an image fills the text column. Label artwork varies wildly in aspect
ratio, so an optional attribute block sizes it, either as a share of the column
or as a millimetre value:

```
![Environmental monitoring box label, 120 x 20 mm.](img/STO_HL_EM_box_120x20.png){width=80%}
![Instrument label held at its physical width.](img/instrument_planica_25x15.png){width=25mm}
```

The width sizes the **image**. The figure itself always spans the text column, so
the caption keeps a readable measure: `{width=25mm}` gives you a 25 mm label with
a full width caption centred under it, not a 25 mm ribbon of text.

A figure never runs past the text column, and it never splits across a page: the
image and its caption always travel to the next page together. A figure taller
than the space it has is scaled down to fit rather than clipped, and the block is
capped so that a figure and the section band that introduces it always fit on one
page together: a figure opening a section never strands the navy band alone at
the top of a blank page. A near page height figure still leaves white space on
the page it could not fit on, which is inherent to an image that must stay whole;
giving such a figure an explicit width of around 60 per cent usually reads
better and packs the pages more tightly.

Figures are block level by design. An image written inside a paragraph, inside a
table cell, inside a bullet, or inside a numbered item is not a figure and is
left as literal text. A line that *starts* with `![` is always read as a figure,
so write such an image mid-sentence rather than at the head of the line if you
really want it left alone.

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

## Visual conventions (Signal Stack on the shared brand core)

- **Page**: A4 portrait, 22 mm top, 18 mm sides, and 21 mm bottom margins.
- **Font**: Manrope throughout (embedded, offline), with 11.2 pt left aligned
  body text and 10.5 pt numbered subsection headings.
- **Colours**: Numaco navy `#183060` for centred main section bands and table
  headers; amber for section numbers and action markers; teal and red only for
  semantic emphasis; subtle navy tinted surfaces for cards and zebra rows.
- **Cover**: dark navy technical cover, 44 pt title, compact wordmark, quiet
  geometric monogram, and a three-column metadata band.
- **Watermark**: 100 mm Numaco monogram anchored at the top right of every
  content page at 8.5% opacity, suppressed on the cover.
- **Hierarchy**: centred 18 pt main section titles with 12 pt amber section
  numbers; ruled, uppercase 10.5 pt subsection headings.
- **Tables**: navy headers, repeated headings on page breaks, content-driven
  column widths up to five columns, tighter padding and a step down in type from
  six columns, and 9.2 pt body text. Columns are left aligned by default, right
  aligned with `---:` (mono figures, flush right) and centred with `:---:`,
  heading and body cells together. A long unbreakable identifier wraps inside
  its cell, so a table never runs past the text column.
- **Semantic colour**: `{green:...}`, `{amber:...}` and `{red:...}` set a status
  or a verdict in the brand accents, semibold, in a table cell, a bullet or a
  paragraph. Colour is applied to live text (so it stays searchable) and it
  never carries the meaning on its own.
- **Figures**: centred in the text column, never wider than it, never split
  across a page, and capped in height so a tall figure is scaled to fit rather
  than clipped and always fits on a page together with the section band above
  it, with a small grey caption centred under the image at full column measure.
- **Footer**: `Numaco AG · Haldenstrasse 3c · CH-8905 Islisberg · numaco.ch`,
  with `Page N of M` on the right, on every content page.

## Rules and conventions

1. Author documents in English unless the user explicitly asks for another language.
2. Body text is left aligned by default.
3. Keep everything self-contained and offline: the engine inlines all CSS and
   embeds every image as a data URI. Never link an external file or a CDN.
4. Do not hand-write branded HTML or a bespoke stylesheet. Drive the engine with
   Markdown. If a report component is missing, extend `build_report.py` and the
   shared presentation layer at `shared/signal-stack/signal-stack.css`. Change
   the shared Signature module only for structural capabilities needed by more
   than one document family.
5. Verify the PDF through CoreGraphics or Preview, not a preview produced only
   by Chromium.

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
path. The Signal Stack presentation shared with SOWs lives at
`shared/signal-stack/signal-stack.css`.

## Relationship to the other skills

- `numaco-sow`: the specialised Statement of Work skill with fixed structure,
  effort table, terms appendix, interactive budget, and SOW number generator.
  Defer to it for scoped service proposals and SOWs.
- `numaco-trading-documents`: the quotation, order confirmation, delivery note,
  and invoice skill. Defer every transactional document to it.
- `numaco-report`: the general branded document engine described here.

## Migration note

This skill replaces `numaco-docx`. The block vocabulary is preserved one to one
(cover, H1/H2/H3, justified paragraphs, bullets with bold-title splits, numbered
scope-items, styled tables with total rows, small print, page breaks), so nothing
regresses. The only change is the pipeline: Markdown to HTML to PDF, with no Word
or LibreOffice dependency, and the line-items table is new.
