# Pattern catalog — numaco-standard-blue

This style **is** the approved Numaco reference deck. Compose slides from the archetypes and components below, using the reference class names. The build wraps your slides in `<deck-stage><div class="deck-canvas"> … </div></deck-stage>`, scales the canvas to the viewport on screen, and paginates one `<section>` per page for the PDF.

## Ground rules

- Every slide is `<section class="<archetype> …" data-title="…">`, exactly 1920x1080. The `data-title` feeds the overflow report.
- The reference `section { display:flex; flex-direction:column }` base is overridden by each archetype (s1/s3/s5/s6 are `grid`). Do not add a `.slide` class; use the archetype classes only.
- **Brand marks** render from injected logo CSS vars: `.s1-mark-abstract`, `.s6-brand .mono`, and `.brand-watermark` are empty divs backed by `var(--logo-blue)` (the symbol-only monogram), turned white on dark panels via a CSS filter. The wordmark "Numaco." in `.numaco-mark` / `.wordmark` / `.s6-brand .name` is TEXT, not the logo image. Never inline a logo lockup with the wordmark.
- **Accent discipline:** one deep navy, generous white, amber (`--accent-amber`) used sparingly on the single object that matters per slide; `--accent-cyan` and `--numaco-navy-400` appear in the card accent cascade. On dark panels, `--hl-blue-bright` (#a5c8ff) is the emphasis colour.
- No dashes as punctuation in any on-slide text.

## Chrome (light content slides)

Footer + faint watermark, drop on s2 and s4-style slides:

```html
<div class="brand-watermark"></div>
<div class="chrome">
  <div class="left"><span class="wordmark">Numaco<span class="dot">.</span></span><span class="sep"></span><span>Customer · Topic</span></div>
  <div class="right"><span>02 / 05</span></div>
</div>
```

On the two-column `s3` slide use `.s3foot` instead (a single footer strip across the light column).

Eyebrow (running signpost on every slide): `<p class="eyebrow"><span class="bar"></span>LABEL</p>`. On dark panels add `on-navy`. A leading amber dot instead of the bar (`<span class="dot"></span>`) is the cover/close variant.

---

## ARCHETYPES

### 1. Cover · `section.s1.variant-abstract`

Navy split: left is the wordmark, an amber-dot eyebrow, a large headline (use `<em>` to mute a trailing phrase), and up to three meta pairs. Right is the abstract deep-navy panel with the faint monogram and tick grid.

```html
<section class="s1 variant-abstract" data-title="Cover">
  <div class="s1-left">
    <div class="s1-top"><span class="numaco-mark">Numaco<span class="dot">.</span></span></div>
    <div>
      <div class="s1-eyebrow"><span class="dot"></span>Proposal for &lt;Customer&gt;</div>
      <h1 class="s1-headline">Big headline,<br><em>muted tail.</em></h1>
      <div class="s1-meta">
        <div><div class="label">Prepared for</div><div class="value">&lt;Name&gt;</div></div>
        <div><div class="label">By</div><div class="value">Numaco AG</div></div>
        <div><div class="label">Date</div><div class="value">&lt;Month Year&gt;</div></div>
      </div>
    </div>
    <div></div>
  </div>
  <div class="s1-right"><div class="s1-mark-abstract"></div><div class="s1-ticks"></div></div>
</section>
```

### 2. Content with cards + stats · `section.s2`

Header (`.s2-head` = title left, tagline right), then a body. The reference body is `.s2-grid` of `.svc` cards and a `.s2-stats` band, but the body is free: use `.svc` cards, the `.cost-grid` cost cards, or a `.s7-callout`. For a 3-card row override the grid: `<div class="s2-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">`.

```html
<section class="s2" data-title="…">
  <div class="brand-watermark"></div>
  <div class="s2-head">
    <div><p class="eyebrow"><span class="bar"></span>EYEBROW</p><h2 class="s2-title">Title,<br>two lines.</h2></div>
    <p class="s2-tagline">One supporting sentence.</p>
  </div>
  <!-- body: .s2-grid of .svc, or .cost-grid, or .s7-callout -->
  <div class="chrome">…</div>
</section>
```

### 3. Diagram + dark side · `section.s3` (add `mid` to centre both columns)

The signature slide. Left (`.s3-main`, light): eyebrow, `.s3-title`, a diagram, a `.s3-lead2` sentence. Right (`aside.s3-side`, navy): eyebrow `on-navy`, an `h3`, and `.s3-points` (`.pt` items). Add `mid` when the content is light so both columns centre vertically.

```html
<section class="s3 mid" data-title="…">
  <div class="brand-watermark tight"></div>
  <div class="s3-main">
    <p class="eyebrow"><span class="bar"></span>EYEBROW</p>
    <h2 class="s3-title">Title.</h2>
    <div class="s3-diagram flow"><!-- .pipeflow here --></div>
    <p class="s3-lead2">One explanatory sentence.</p>
  </div>
  <aside class="s3-side">
    <div class="brand-watermark"></div>
    <p class="eyebrow on-navy"><span class="bar"></span>EYEBROW</p>
    <h3>Panel statement.</h3>
    <div class="s3-points">
      <div class="pt"><div class="pt-mark">01</div><p><strong>Lead-in</strong>, the rest.</p></div>
    </div>
  </aside>
  <div class="s3foot"><span class="wordmark">Numaco<span class="dot">.</span></span><span class="sep"></span><span>Customer · Topic</span><span class="sep"></span><span>03 / 05</span></div>
</section>
```

### 5. Split hero · `section.s5`

Navy split for a product/screenshot or feature story: `.s5-left` (tag, `.s5-title`, intro, `.adv` advantage rows) and `.s5-right` (a framed mock in `.s5-screenshot-wrap`). Use when you have a UI or a hero visual. See the reference deck for the full `.appmock` mock.

### 6. Close · `section.s6`

Mirror of the cover. Thanks eyebrow (amber dot), headline (`<em>` mutes the tail), then the signature and the booking CTA **below** it, and the monogram + tagline on the right.

```html
<section class="s6" data-title="Close">
  <div class="s6-content">
    <div class="s6-thanks"><span class="dot"></span>Thank you</div>
    <h1 class="s6-headline">Closing line <em>tail.</em></h1>
    <div class="s6-cta-row">
      <div class="s6-contact"><strong>Name</strong><br>Numaco AG · email</div>
      <a class="s6-book" href="https://booking.numaco.ch"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg> Book a meeting with us</a>
    </div>
  </div>
  <div class="s6-brand"><div class="mono"></div><div class="tag">Industrial labeling · since 1980</div></div>
  <div class="s6-band"><span class="wordmark">Numaco<span class="dot">.</span></span><div class="meta"><span><strong>Numaco AG</strong> · Switzerland</span><span>Customer · Topic</span></div></div>
</section>
```

---

## COMPONENTS

- **`.svc` card** (in a grid): `<div class="svc"><div class="svc-icon">{svg}</div><h3>Title</h3><p>Body.</p></div>`. The accent bar + icon tint cascade by `nth-child`: navy, cyan, amber, navy-400.
- **`.stat` band**: `<div class="s2-stats"><div class="stat"><div class="num">300 dpi</div><div class="lbl"><strong>Bold</strong> label.</div></div>…</div>`. Three stats; num colours cascade navy, amber, cyan.
- **`.ben` numbered rows** (in `.s3-benefits`, a 2-col grid): `<div class="ben"><div class="ben-num">01</div><div><h4>Heading</h4><p>Body.</p></div></div>`. Add `is-hero` for an emphasised amber-tinted row.
- **`.pt` points** (dark panels): `<div class="pt"><div class="pt-mark">01</div><p><strong>Lead</strong>, rest.</p></div>`.
- **`.pipeflow`** (process flow): `.pnode` stages, `.parrow` arrows (inline SVG right-arrow), and one emphasised `.pgroup` with `.pglabel` + `.ppills`. Ends at a plain `.pnode`. Wrap in `.s3-diagram.flow` on an s3 slide. Keep to <= 6 nodes; mono for a port like `TCP 9100`.
- **`.cost-grid` / `.cost-card`** (reusable): a 2-col grid of accent-barred cards, index in its own column so the description indents under the title. `.cost-card.hero` spans full width for an emphasised item. Markup: `<div class="cost-card"><span class="cost-num">01</span><div><div class="cost-cat">Category</div><p class="cost-desc">Detail.</p></div></div>`.
- **`.s7-callout`** (navy band): `<div class="s7-callout"><div class="ic">{svg}</div><p>One punchy line, <strong>amber</strong> emphasis.</p></div>`.
- **`.s6-book`** (booking CTA): translucent pill with an amber calendar icon; place inside `.s6-cta-row` after `.s6-contact`.
- **Icons**: inline SVG, lucide style (`stroke="currentColor" stroke-width="2"`, ~28-30px), monochrome to the tile accent. No icon fonts, no external files.

## Density budgets

Cover headline <= 6 words. Content title <= 2 lines. `.svc`/`.cost-card` body <= ~20 words. `.pt`/`.ben` <= 2 lines each; <= 5 per panel. `.pipeflow` <= 6 nodes. The build's overflow checker is the backstop; never ship a slide it flags.

## Escape hatch

A one-off bespoke slide is allowed inside a `<section>`: reuse the tokens (`var(--numaco-navy)`, spacing, type helpers) and the chrome, keep to 1920x1080, and it still passes the overflow check.
