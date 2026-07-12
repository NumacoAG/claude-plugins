# DEDUP note (deferred de-duplication)

This skill carries its own copies of brand assets under
`assets/numaco-standard-blue/`:

- `theme.css` (design tokens)
- `fonts/manrope.css` (embedded Manrope)
- `logo-blue.png`
- `logo-white.png`

These **duplicate** the canonical copies in the plugin's
`shared/brand-core/` (`theme.css`, `fonts/manrope.css`, `logo-blue.png`,
`logo-white.png`).

## Why they are still here

They are kept intentionally, not by oversight. `scripts/build_deck.py`
inlines these files from `assets/<style>/` at assemble time so the
resulting deck HTML is fully self-contained and offline. The deck also
ships two deck-only stylesheets alongside them (`patterns.css`,
`deck.css`) that have no equivalent under `shared/brand-core/`, so the
style folder cannot simply be pointed at the shared directory as is.

## Plan for later

Once the plugin is hardened, de-duplicate by having `build_deck.py`
resolve `theme.css`, `fonts/manrope.css`, `logo-blue.png`, and
`logo-white.png` from `shared/brand-core/` (falling back to the local
style folder for `patterns.css` and `deck.css`, which remain deck
specific). Verify byte-for-byte parity between the two copies before
repointing, then delete the duplicated files from
`assets/numaco-standard-blue/`.

Do **not** delete or repoint them yet: the deck currently renders
correctly as is, and the point of this relocation was to move the skill
without breaking it.

## Parity check (as relocated)

At relocation time the duplicated files matched their `shared/brand-core/`
counterparts (theme.css and logos identical; fonts/manrope.css identical).
Re-verify with `diff` before any future repointing.
