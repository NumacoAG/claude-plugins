---
name: obsidian-versioned-review
description: >-
  Collaboratively draft, iterate on, review, and lock a markdown document in your Obsidian vault using the green-mark versioned-review regime. Use whenever the user wants to co-author or review a vault doc over multiple rounds — triggers include "let's draft/write X in the vault", "review this doc", "iterate on it", "incorporate my comments", "bump the version", "lock the doc", or working on any file that carries a `**vN.y**` version line under its title. Covers the full loop: versioning, green-marking changes with inline color spans, the review cadence, Obsidian rendering gotchas, the git worktree → commit → push → merge flow, and enshrining conventions.
status: stable
version: "1.4 (2026-06-30: no hard line wraps inside a paragraph or bullet, one logical line equals one physical line; see § D)"
---

# Obsidian versioned-doc review

The regime the user and Claude use to co-author markdown docs in the vault. A doc under this regime is identified by a `**vN.y**` line immediately under its H1 title. Plain notes without that line are not under the regime.

The canonical written spec also lives in the vault at `_meta/conventions.md` § *Versioned-doc review*, with a mandatory highlight in the vault root `CLAUDE.md`. This skill is the operating manual; keep all three in sync if any changes.

## When to trigger

- The user asks to draft, write, or build a new doc *in the vault* that you'll iterate on together.
- The user asks to review, iterate, revise, or "incorporate comments" on a vault doc.
- The user says "lock the doc", "bump the version", or similar.
- You open any doc whose first content line is `**vN.y**`.

## Green-marking uses INLINE COLOR SPANS only — never callout blocks

**FORBIDDEN:** `> [!new]` / `[!new]+` callout blocks — or any `>`-prefixed block wrapper — for green-marking. Do **not** use them. The user dislikes whole-doc green blocks, and the `>` line prefixes break formatting. There is no longer any "multi-block callout" form.

Green-marking is done **only** with inline spans:

```markdown
<span style="color: mediumseagreen">changed or new text</span>
```

No CSS snippet is required — inline `style="color: …"` renders natively in Obsidian. (The old `.obsidian/snippets/versioned-doc-review.css` callout snippet is obsolete and has been removed; don't recreate it.)

## A. Versioning

- Put `**vN.y**` directly under the H1 title.
- Each Claude revision for review bumps `y` by 1 (`0.3` → `0.4`).
- **In-revision fixes do not bump `y`.** If you must correct your own output (broken render, typo, missed change) *before* the user has reviewed the current revision, fix in place and keep the same `y`.
- **Lock:** when the user says "lock", bump to `(N+1).0`, strip all green (delete the `<span …>` tags, keep their inner text), put a 🔒 next to the version line (`**v1.0** 🔒`), and add a 🔒 footer at the very end (`🔒 **Locked — vX.0 (YYYY-MM-DD).**`).

## B. Green-marking — only what changed this round, with spans

Mark **only the changes you made in the current revision**, in `mediumseagreen`, using inline `<span style="color: mediumseagreen">…</span>`.

Spans are **inline only**, so mark at the granularity of the changed text — put the span *inside* the element, never around a whole block:

- a sentence or list-item text: `- <span style="color: mediumseagreen">new item</span>`
- a heading's text (span goes inside the heading line): `## <span style="color: mediumseagreen">New heading</span>`
- a changed table cell's text: `| <span style="color: mediumseagreen">new value</span> | … |`

Rules:

- **Initial / all-new doc (v0.1): do NOT blanket-color it.** That is the noise the user rejected. Write clean plain markdown; the `**v0.1**` line already signals "all new, first review." Green is reserved for marking **deltas in later revisions**.
- **A wholly new multi-line block** you can't span cleanly (a new table or fenced code block added in v0.2+): leave the block itself plain and precede it with a one-line green marker, e.g. `<span style="color: mediumseagreen">(new — added vX.y:)</span>`.
- On each new revision, **first remove the previous round's green** (delete its `<span>` tags, keep the text), then green only the newest changes.
- On lock, strip all spans (keep their inner content).

## C. The review loop

1. Claude makes its changes, bumps `y`, green-spans them, and opens the file for the user with a one-click bash command (see § File opening).
2. The user reads the green parts.
3. The user responds. **Detecting the user's comments:** the user writes plain `>` blockquote comments (no marker) — **diff their current doc against the exact version you last released and treat every change they made (their `>` notes, edits, additions, deletions) as their instructions.** Keep a copy/memory of what you released so you can compute that diff. (`>mp` is retired; plain `>` is the convention. Their review blockquotes are their own channel and are unaffected by the green-marking rules.) **Strikethrough = delete:** text the user wraps in `~~…~~` means *remove it* — drop that text (and the `~~` markup) in the next revision.
4. Claude incorporates the user's comments and direct edits, removes the previous round's green, green-spans the new round, bumps `y`. Go to 2.
5. Repeat until the user says "lock", then run the lock procedure (§ A).

Note: incorporating the user's own comments usually means they become **plain** (accepted) text; reserve green for content that is genuinely new for them to review. When the user says "incorporate and remove the marking", de-green the incorporated parts.

## D. Obsidian rendering gotchas (do not relearn these)

- **`[!new]` / callout blocks are forbidden** for green-marking — use inline spans (see above).
- `<span>` is **inline only** — never wrap a heading, table, list, or blockquote in one big span. Put the span *inside* the element (inside the heading line, inside the cell, around the item's text).
- `<div>` wrappers **do not render markdown inside** in current Obsidian (headings/tables come out as literal text). Don't use them.
- **MUST escape angle brackets inside any raw HTML span.** Placeholders like `<team>`, `<product>`, or `<name>.<surname>` are parsed as HTML tags and silently swallow the surrounding content. Inside a `<span>`, replace `<` with `&lt;` and `>` with `&gt;`: e.g. `<span style="color: mediumseagreen">my &lt;name&gt;.&lt;surname&gt;</span>`. Any literal `>` you want to *show* inside a span must also be written `&gt;`. In plain markdown (outside spans), backticks are preferred: `` `<team>` ``.
- A markdown link wrapped in a green `<span>` will not render as a link — keep the link outside the span, or accept it for the review round (lock removes the green anyway).
- **Cross-references must be clickable links.** Any reference to another doc or section is an Obsidian link `[text](relative/path.md)` (or `[[wikilink]]`), never bare prose ("see §3", "the other doc"). The user reviews on mobile and wants to tap through.
- **No hard line wraps inside a paragraph, bullet, or table row.** Write each paragraph, list item, and table row as a single physical line and let the editor soft-wrap. Never insert manual newlines to wrap prose at a column width: they make text break at fixed points when the user resizes the window or changes the font, and they reflow badly. One logical line is one physical line. (Blank lines between blocks stay, as normal markdown.)

## E. Git worktree → commit → push → merge

For non-trivial doc work, isolate changes in a worktree, then ship.

1. Create a worktree off the vault on a new branch:
   `git worktree add <path-outside-vault> -b <branch>` (run from the vault root).
2. Do all edits in the worktree. Open files for the user from the worktree path.
3. When the user approves (usually at lock), commit in the worktree, push the branch, then merge into `main`.
   - The vault uses the **obsidian-git** plugin, which auto-commits "vault backup" commits to `main`. Expect `main` to have advanced; merges are normally real merges, not fast-forwards.
4. After merge, the canonical copy is in the vault on `main`; edit there. Offer to remove the now-redundant worktree (`git worktree remove …`).

Enshrine any change to the regime itself in `_meta/conventions.md` § *Versioned-doc review* and keep the highlight in vault root `CLAUDE.md` (and this skill) in sync.

## File opening (vault rule)

Always surface a doc for review with a runnable bash command in a bash fence so the user gets a one-click open:
- Visible path (no dotted segment): `open -a "Obsidian" "<absolute-path>"`
- Path under a hidden folder (e.g. `.obsidian/`, `.claude/`, worktrees under a dotted dir): `open -a "Cursor" "<absolute-path>"`

Always absolute, always double-quoted.

## Quick checklist per round

- [ ] Used inline color spans only — **no `[!new]` / callout blocks** (forbidden)
- [ ] Removed previous round's green (deleted old `<span>` tags, kept the text)
- [ ] Greened **only** this round's changes; left an all-new v0.1 doc plain
- [ ] Escaped `&lt;` / `&gt;` for every literal `<` / `>` inside a span
- [ ] No hard line wraps inside paragraphs, bullets, or table rows (one logical line equals one physical line)
- [ ] Bumped `y` (or kept it for an in-revision fix)
- [ ] Opened the file for the user with a bash-fence command
- [ ] On lock: bumped to `(N+1).0`, stripped all spans, added 🔒 by the version and a 🔒 footer
