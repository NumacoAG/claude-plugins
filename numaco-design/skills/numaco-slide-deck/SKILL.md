---
name: numaco-slide-deck
description: >-
  Create a Numaco-branded slide deck (presentation) and render it to PDF. Use whenever the user asks
  to "make/create/build a presentation", "a slide deck", "a pitch deck", "slides for <customer>",
  "a deck for <customer>", "put this in slides", "turn this doc into a
  presentation", or says "numaco-slide-deck" / "/numaco-slide-deck". Runs as a two-phase
  conversation: FIRST write and lock a slide-content markdown spec (down to the verbatim on-slide
  text) via the obsidian-versioned-review regime, THEN render the deck to a self-contained HTML
  and export the PDF (the PDF is the deliverable). Default look is the "numaco standard blue
  template". Other styles can be added later.
status: beta
version: "0.5 (2026-07-10 — build now emits a CoreGraphics cover check (pdfcheck) so decks are verified through PDFKit/Preview, not Chromium, plus PDFKit-safe design rules. Includes 0.4's cover CSS fix: definite-px monogram, transform-free centering with inset:0+margin:auto, gradient vignette; and 0.3's print pagination clamp.)"
---

# numaco-slide-deck

Build a Numaco-branded presentation. The hard rule: **words before pixels.** The content, down to the exact text on every slide, is written and locked as a markdown spec first. Only then is a slide rendered. The PDF is the real deliverable; the HTML is a build intermediate and a preview surface.

## Punctuation (binding)

Never use dashes as punctuation in any on-slide text, spec, or prose (no em dash, en dash, or hyphen standing in for a dash). Use commas, colons, semicolons, periods, or parentheses. Hyphens inside proper names, URLs, code, and file paths are fine. This holds for the deck exactly as it does everywhere else the user works.

## Inputs to gather (ask briefly, then proceed)

1. **Audience and goal**: who is in the room, and what decision or reaction the deck should produce.
2. **Source material**: the doc(s) to distil (a scoping doc, a locked spec, an email thread). Deck content should be distilled from a source, not invented.
3. **Length**: target number of slides (default 8 to 12).
4. **Output location**: which project folder. Default filing: the deck spec and outputs go in the project's `Deliverables/` (per the Projects-site routing), the spec may live in `Reference/` if it is still pre-delivery.
5. **Style**: default `numaco-standard-blue`. Only this style exists today.

Pick sensible defaults and state them rather than blocking.

## Phase 1 — content spec (write, review, LOCK)

1. Read `references/content-spec-template.md` for the schema, and `references/pattern-catalog.md` so you choose real patterns.
2. Write the spec as a markdown doc named `<deck-slug>-content.md` in the chosen folder. Open with a one-line-per-slide **storyline**, then a per-slide block giving: slide number, the **pattern** it uses, the **verbatim** on-slide text (headline, body, bullets, captions, stat values, labels), and any asset or diagram note. No speaker notes: every slide must be self-explanatory from what is on it.
3. Iterate and lock the spec through the **obsidian-versioned-review** skill (green-mark each round, bump `vN.y`, lock at `vN.0 🔒`). Follow that skill's rules exactly (inline color spans, one logical line per paragraph or bullet or table row, clickable cross-references).
4. **Do not render anything until the spec is locked.** This gate is the point of the skill.

## Phase 2 — render (assemble, check, preview, export)

1. Author `slides.html`: a body fragment of `<section class="slide ...">` blocks, one per slide in the locked spec, composed from the classes in `references/pattern-catalog.md`. Put the exact locked text in. Give each section a `data-title="..."` for the overflow report. Use only library patterns; a genuinely bespoke slide is allowed as an escape hatch but should reuse the tokens and chrome.
2. Build with the script (it inlines the theme, the embedded Manrope font, and the logos, so the output is self-contained and offline):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-slide-deck/scripts/build_deck.py" build \
  --slides slides.html --outdir . --name "<deck-slug>" --title "<Deck title>"
```

3. The build runs an **overflow check**. If any slide overflows the 1920x1080 canvas, the script lists it and exits non-zero. Trim or split those slides and rebuild until it reports none. Never ship a deck with overflow.
4. **Preview**: open the HTML for the user and let them eyeball it before the PDF is treated as final:

```bash
open -a "Google Chrome" "<deck-slug>.html"
```

Arrow keys or the on-screen nav move between slides; the canvas scales to the window.
5. On approval, the **PDF** (`<deck-slug>.pdf`, one 1920x1080 landscape page per slide) is the deliverable. Keep the HTML alongside as the editable intermediate.
6. **Verify the PDF through CoreGraphics (the engine macOS Preview uses), not through Chromium.** `build` auto-emits a CoreGraphics render of the cover and prints its path on the `pdfcheck` line; open that image, or open the full PDF in macOS Preview, and confirm it matches the HTML. Do this for every deck. Chromium renders the PDF, so any Chromium-based check agrees with it and hides PDFKit-only bugs; **`qlmanage -t` thumbnails are also unfaithful, do not use them as the oracle.** To re-render a page yourself: `sips -s format png <deck-slug>.pdf --out /tmp/check.png`.

## Rendering engine

`build_deck.py` uses Playwright/Chromium if installed, otherwise a browser resolved through the shared ladder in `shared/render/numaco_render.py` (env override, system Chrome, Chromium, Edge, or Brave, a previously downloaded private build, or a fresh `chrome@stable` download as the last resort). Nothing needs to be preinstalled; every asset is inlined and no network access is needed at render time.

## Design discipline

- **Reference archetypes only** (see `references/pattern-catalog.md`): the cover (`s1`), content with cards and a stat band (`s2`), the diagram-plus-dark-side slide (`s3`, the signature), the split hero (`s5`), and the close (`s6`), plus components (svc cards, stat band, `ben` rows, `pt` points, `pipeflow`, cost cards, callout band, booking CTA). These reproduce the approved Numaco reference deck exactly. Compose from them; a genuinely bespoke slide is the escape hatch. The screen viewer and PDF pagination run off the `deck-stage` / `deck-canvas` runtime, so grid archetypes keep their layout.
- **Diagrams are markup, not screenshots.** Use the `pipeflow` pattern (or CSS) for process flows so they are crisp and on brand.
- **Density budgets** in the catalog keep slides from overflowing. Respect them; the overflow check enforces the rest.
- **Self-contained**: never link external CSS, fonts, or images. Inline everything (the script does this for the theme, font, and logos; any extra image you add must be a data URI).
- **Icons**: inline SVG (lucide-style, ~28px) inside `.card-ico`, `.callout .ic`, etc. Keep them sparing and monochrome to the tile's accent.
- **PDFKit-safe decoration.** macOS Preview and Quick Look render PDFs with CoreGraphics, which diverges from Chromium on `transform` (a `translate(-50%,-50%)` centering is silently dropped), `mask-image`, `aspect-ratio`, and percentage sizing of absolutely-positioned decorative layers. For anything that must survive to the PDF, use definite px sizes, center with `inset:0` + `margin:auto` (never a transform), and fade with gradient overlays (never `mask-image`). The `s1` cover archetype already follows this; keep new patterns the same, and always run the `pdfcheck` step (Phase 2).

## Styles

Styles live under `assets/<style>/` (each has `theme.css`, `patterns.css`, `deck.css`, `fonts/`, `logo-blue.png`, `logo-white.png`). Today there is one: `numaco-standard-blue`. To add another, copy the folder, retune `theme.css` tokens and `patterns.css`, and pass `--style <name>`.

## Layout of this skill

```
numaco-slide-deck/
├── SKILL.md
├── scripts/build_deck.py            # assemble + overflow check + PDF render
├── assets/numaco-standard-blue/     # the one style: tokens, patterns, canvas, font, logos
└── references/
    ├── pattern-catalog.md           # every pattern's markup + density budget
    └── content-spec-template.md     # the slide-content spec schema
```

## Updating

This skill ships inside the `numaco-design` plugin and loads in place from the plugin directory. After editing a file here, bump `version` above and restart Claude Code to pick up the change; no reinstall is needed for a directory-sourced plugin.
