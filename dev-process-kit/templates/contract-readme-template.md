# The PROJECT NAME contract

**v0.1**

This folder is the whole product contract. M specifications say what the product does; one Definition of Done says what must be proven working before release. Nothing else is Tier 1. If a promise is not in these documents, the product does not make it. Each document carries its own version line, and 🔒 marks a locked one.

<!--
HOW TO USE THIS TEMPLATE

Placeholders are IN UPPER CASE. M is the component count. Replace every
placeholder, then delete every comment block in this file.

The opening paragraph is the CLOSURE CLAUSE and it is the whole point of the
front door. Without closure a contract set silently acquires another authority
and nobody knows which document binds. Keep the sentence "Nothing else is Tier
1" and keep the sentence after it.
-->

## Read in this order

1. [THE CONSTRAINTS COMPONENT](spec-NN-constraints-slug.md): the decisions only the product owner owns. Cost, speed, accepted risk, recovery. Read first; everything else stands on it.
2. [Definition of Done](definition-of-done.md): J days in the life that prove the product. If all J pass, the organisation runs on this system.
3. The components, in any order:

| Code | Component | Essence |
|---|---|---|
| XX | [COMPONENT TITLE](spec-NN-component-slug.md) | THE ESSENCE LINE, COMPRESSED TO A TABLE CELL |
| YY | [COMPONENT TITLE](spec-NN-component-slug.md) | THE ESSENCE LINE, COMPRESSED TO A TABLE CELL |

<!--
THE ESSENCE COLUMN is the compression test made visible. Each cell is that
document's italic essence line reduced to a phrase. A line that will not
compress to a cell is doing the work of two components, and the table is where
you find that out cheaply.

Cross references are bare relative file names, never folder paths, so moving a
document never breaks a citation.
-->

## How to read a requirement line

Every identifier names its kind and its home. `UR-XX-03` is a requirement living in the component whose code is XX; the tag after it, such as `(DJ-04)`, names the [Definition of Done](definition-of-done.md) journey that proves it; `(constraint)` marks a standing rule verified by the engineering gate and the product owner's approval rather than by an operator journey. An asterisk after an identifier marks a clause inherited from a prior locked contract; the mapping lives in `../tier-2/machine-readable/id-map.json`, never in the prose.

<!--
DELETE THE ASTERISK SENTENCE IF NOTHING IS INHERITED. When the registry declares
no sources, any inheritance marker anywhere is a hard gate failure, because the
character has no referent.

If the project declares an action glyph, define it here in one sentence too, or
point at the single interstitial paragraph in the specification set that defines
it. It is defined exactly once, anywhere in the set, and used bare forever.
-->

## House rules

Requirement identifiers are immutable once locked; before a lock, a renumber needs the product owner's explicit say so. Every requirement traces to a Definition of Done journey or is a declared standing constraint. The generated crosswalk in `../tier-2/machine-readable/` accounts for every identifier and fails the build if one goes missing. Locks happen document by document; the crosswalk records the live state.

<!--
AT LOCK, add the glyph to the version line and append:

    🔒 **Locked: v1.0 (YYYY-MM-DD).**
-->
