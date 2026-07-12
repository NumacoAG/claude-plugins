# Slide-content spec — schema

The spec is the contract for a deck. It carries a `**vN.y**` line so it runs under the obsidian-versioned-review regime (green-mark each round, lock at `vN.0 🔒`). Write the exact on-slide text here; the render phase only lays out what this doc already says. No dashes as punctuation. One logical line per bullet or paragraph (no hard wraps), so mobile review reflows cleanly.

Copy the skeleton below, fill it, review, lock, then render.

---

```markdown
# <Deck title> — slide content

**v0.1** — slide-content spec for the <audience> deck. Status: drafting.
Deck goal: <the one decision or reaction this deck should produce>.
Audience: <who is in the room>. Length: <n> slides. Style: numaco-standard-blue.
Source: [<source doc>](<relative/path.md>).

## Storyline (one line per slide)

1. Cover — <the promise in a phrase>
2. <Section or content> — <the beat>
3. ...
N. Close — <the ask>

---

## Slide 1 — Cover
- Pattern: cover
- Eyebrow: `Proposal for Acme Labs`
- Headline: `Native PDF generation, built in`
- Meta: Prepared for = `Petra Meier`; By = `Numaco AG`; Date = `July 2026`

## Slide 2 — <name>
- Pattern: content (points)
- Eyebrow: `...`
- Title: `...`
- Bullets (verbatim):
  - `...`
  - `...`

## Slide 3 — <name>
- Pattern: pipeflow
- Title: `...`
- Nodes: `Label designer` -> `Print server` -> group[`Numaco listener` : capture ZPL, render PDF, forward] -> `Printer`
- Caption: `...`

... one block per slide ...

## Slide N — Close
- Pattern: closing
- Headline: `Let's build it in`
- Contact: `Your Name, you@numaco.ch`
- URL: `booking.numaco.ch`
```

---

## Rules for the spec

- **Verbatim text in backticks.** Everything a viewer will read on the slide is written here exactly, in backticks, so review is about the real words. The render phase does not invent copy.
- **One pattern per slide**, named from `pattern-catalog.md`. If a slide needs a bespoke layout, say `Pattern: bespoke` and describe the intent; the render phase uses the escape hatch.
- **Respect the density budgets** in the catalog (bullet counts, word limits). If a beat needs more, split it into two slides in the storyline rather than overfilling one.
- **No speaker notes.** Each slide must stand on its own from the text it shows. If a point only makes sense when spoken, put it on the slide or cut it.
- **Storyline first.** Agree the arc (the one-liner per slide) before writing the verbatim blocks; it is cheaper to re-order lines than to rewrite slides.
- **Lock before rendering.** The render phase starts only once the spec is at `vN.0 🔒`.
