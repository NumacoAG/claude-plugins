# numaco-design

Numaco AG branded output engine for Claude Code. One shared renderer and one
brand core turn Markdown (or a JSON payload) into branded, self-contained HTML
and then into a print-ready PDF. Every PDF is verified through CoreGraphics (the
engine macOS Preview uses), not through a Chromium preview, because the two
diverge on print layout.

The plugin ships four skills that all sit on the same renderer and brand core:

- **numaco-report**: the general branded document engine. It takes one Markdown
  file with a small front-matter header and produces a branded A4 PDF (reports,
  memos, one-pagers, architecture overviews, handovers, solution designs,
  letters). It also carries a first-class line-items table with computed totals,
  the seam for future quotations, purchase orders, and invoices.
- **numaco-sow**: an interactive Statement of Work skill. It gathers inputs,
  drafts each section in chat for approval, iterates the budget in a live
  artifact, then renders the branded PDF from a JSON payload (effort table,
  parties block, commercial terms, and a Terms and Conditions appendix).
- **numaco-timesheet**: a branded timesheet (hours report) skill. It renders a
  JSON payload of time entries into a Signature styled hours document: one
  entries table grouped by month with subtotals, hours-only by default with an
  optional computed Amount column, an approval block, and strict payload
  validation. Entries can be pulled from Clockify when its MCP tools are in the
  session, with the user reviewing every description before rendering.
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
- Ask for a timesheet, hours report, Stundenrapport, or to bill the hours for a
  project or period and **numaco-timesheet** runs.
- Ask to build a presentation, slide deck, or pitch deck for a customer and
  **numaco-slide-deck** runs.

## Runtime dependencies

Claude Code, signed in. The guided setup (or the first render) installs the
renderer dependencies automatically, including a private Chrome build if no
browser is found. Node 18 or newer is installed via your package manager if
absent: the renderer prints the exact command (`brew install node` on macOS,
`winget install OpenJS.NodeJS.LTS` on Windows, the distro package on Linux) and
you rerun.

How the self-install works:

- **Node dependencies.** On first use the renderer runs `npm ci` inside
  `shared/render` against the committed lockfile (`puppeteer-core` `^24.0.0`,
  resolved to `24.43.1`). `node_modules/` is gitignored.
- **Browser resolution ladder.** Every render resolves its browser in one
  place, in this order: the `PUPPETEER_EXECUTABLE_PATH` or
  `NUMACO_RENDER_BROWSER` environment override; a system Chrome, Chromium,
  Edge, or Brave (standard macOS, Windows, and Linux install locations, then
  PATH); a private build previously downloaded under
  `shared/render/.browsers/`; and, as a last resort, a fresh `chrome@stable`
  download via `@puppeteer/browsers` into that folder (about 150 MB, one
  time). The resolved executable is cached in `shared/render/.browser-path`
  and revalidated on every run. Downloaded builds are verified by actually
  starting the executable; a partially extracted build is repaired with the
  system unzip or tar automatically.
- **Doctor.** `python3 shared/render/numaco_render.py doctor` preflights the
  whole chain (Node, npm, dependencies, browser), prints every resolved path,
  and exits 0 only when a render could succeed on the machine.
- **Python 3.11 or newer.** The four build engines (`build_report.py`,
  `build_sow.py`, `build_timesheet.py`, `build_deck.py`) are plain Python with
  no third-party packages; they call the shared renderer over a subprocess. No
  virtual environment is required.
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
the first time you draft an SOW. The timesheet skill reads the same file for
its consultant default (the second contact) and for the day rate when a sheet
carries amounts.

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
    ├── numaco-timesheet/          branded timesheet (hours report) engine
    └── numaco-slide-deck/         branded presentation engine
```
