# numaco-design

Numaco AG branded output engine for Claude Code. One shared renderer and one
brand core turn Markdown (or a JSON payload) into branded, self-contained HTML
and then into a print-ready PDF. Every PDF is verified through CoreGraphics (the
engine macOS Preview uses), not through a Chromium preview, because the two
diverge on print layout.

The plugin ships three skills that all sit on the same renderer and brand core:

- **numaco-report**: the general branded document engine. It takes one Markdown
  file with a small front-matter header and produces a branded A4 PDF (reports,
  memos, one-pagers, architecture overviews, handovers, solution designs,
  letters). It also carries a first-class line-items table with computed totals,
  the seam for future timesheets, quotations, purchase orders, and invoices.
- **numaco-sow**: an interactive Statement of Work skill. It gathers inputs,
  drafts each section in chat for approval, iterates the budget in a live
  artifact, then renders the branded PDF from a JSON payload (effort table,
  parties block, commercial terms, and a Terms and Conditions appendix).
- **numaco-slide-deck**: a Numaco branded presentation skill. It first writes and
  locks a slide-content Markdown spec (verbatim on-slide text), then renders a
  self-contained 1920x1080 deck and exports the PDF.

## How the skills trigger

Each skill is model-invoked from its description; there is no slash command to
memorise.

- Ask for a branded report, memo, one-pager, handover, solution design, or letter
  ("write it in the Numaco template", "in Numaco branding") and **numaco-report**
  runs.
- Ask to write, draft, quote, or revise a Statement of Work, proposal, quotation,
  or offer for any customer and **numaco-sow** runs.
- Ask to build a presentation, slide deck, or pitch deck for a customer and
  **numaco-slide-deck** runs.

## Runtime dependencies

- **Node.js 18 or newer.** The document renderer drives Paged.js through
  `puppeteer-core`. Install the Node dependencies once:

  ```bash
  npm install --prefix shared/render
  ```

  `shared/render/package.json` declares `puppeteer-core` (`^24.0.0`, resolved to
  `24.43.1` in the committed lockfile). `node_modules/` is gitignored; colleagues
  run the install locally.
- **A Chrome or Chromium browser must be installed.** `puppeteer-core` does not
  bundle a browser; it drives the system Chrome or Chromium. The slide-deck skill
  uses Playwright/Chromium if present, otherwise system Google Chrome headless.
- **Python 3.11 or newer.** The three build engines (`build_report.py`,
  `build_sow.py`, `build_deck.py`) are plain Python with no third-party packages;
  they call the shared renderer over a subprocess. No virtual environment is
  required.
- **PDF verification (macOS only, optional).** The CoreGraphics fidelity check
  (`pdfcheck`) uses `sips` and, for interior pages, `qpdf`, so it runs on macOS.
  Rendering itself is cross-platform; only the Preview-fidelity screenshot check
  is macOS specific.

Everything the renderer produces is self-contained and offline: all CSS is
inlined, all images are embedded as data URIs, and the fonts (Manrope, JetBrains
Mono) are embedded. No network access is needed at render time.

## Personal defaults

Your rate card and your supplier contact block (the two Numaco-side names
printed in every SOW's Parties table) live in a per-user defaults file, never
in the plugin. Copy `defaults.toml.example` from the plugin root to
`~/.config/numaco-design/defaults.toml` and fill in your own values, or set the
`NUMACO_DESIGN_DEFAULTS` environment variable to point at a custom path. The
file stays on your machine: it is per-user, machine-local, and never committed
to any repo. If it is missing, SOW PDFs fall back to placeholder contact names,
and the SOW skill will ask for your rates and offer to create the file for you
the first time you draft an SOW.

## Layout

```
numaco-design/
├── .claude-plugin/plugin.json     plugin manifest
├── defaults.toml.example          template for your per-user defaults file
├── shared/
│   ├── brand-core/                design tokens, embedded Manrope, logos, doc CSS
│   ├── render/                    Paged.js renderer (puppeteer-core), pdfcheck
│   └── signature/                 the locked Signature presentation module
└── skills/
    ├── numaco-report/             Markdown to branded PDF engine
    ├── numaco-sow/                Statement of Work engine
    └── numaco-slide-deck/         branded presentation engine
```
