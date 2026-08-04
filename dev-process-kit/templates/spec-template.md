# TERRITORY, AS A BARE NOUN PHRASE

**v0.1** · component N of M · Tier 1 specification

*ONE SENTENCE OF 17 TO 31 WORDS, PRESENT INDICATIVE, ONE PIVOT MARK, ENDING ON THE INVARIANT THAT BREAKS FIRST.*

<!--
HOW TO USE THIS TEMPLATE

Placeholders are written IN UPPER CASE. Replace every one of them, then delete
every comment block in this file. Identifier placeholders keep their real shape:
XX is the component code, nn is the zero padded number, DJ-nn is a journey.

THE FRAME IS POSITIONAL. The H1 sits on line 1, the version line on line 3, the
italic essence line on line 5. The gate checks those three positions, so keep
the blank lines exactly where they are.

THE TITLE is a bare noun phrase naming the territory, usually three or four
things joined by commas. Never the file name, never the component code, never
the word "specification".

THE VERSION LINE has four fields separated by a middle dot with one space each
side: the bold version, the lock glyph, "component N of M", and the class of
document. While the document is a draft the lock glyph is absent, and that
absence is the only draft marker. No status banner is ever used.

THE ESSENCE LINE. One sentence. No modal verb and no "the system": the subject
is the work, not the software. One pivot mark, a colon or a comma series,
splitting the abstract promise from its enumerated checkable half. It ends on
the invariant that would break first if this component were built badly, stated
negatively. It carries at least one hard noun from the physical or monetary
world and no technical noun at all. It must compress to a single table cell in
the contract front door; a line that will not compress is doing the work of two
components.

Reference: reference/specification-anatomy.md
-->

## Why this matters

TIME ANCHOR (Today, Until now, or Before this product) FOLLOWED BY THREE NAMED CONTAINERS HOLDING THE TRUTH IN THE WRONG PLACE, THEN ONE SHORT SENTENCE NAMING THE CONSEQUENCE. Running well, THE SAME WORK AS A SEQUENCE OF ACTORS AND VERBS, ENDING ON THIS COMPONENT'S HARDEST GUARANTEE STATED AS AN IMPOSSIBILITY.

<!--
TWO MOVES, ONE PARAGRAPH, 53 TO 70 WORDS, NEVER BULLETED.

Move one is three specific failures, not one general complaint. Name three
containers, then name the consequence in one short sentence. Never blame a
person and never name a competing tool as inadequate; a tool is a container, not
a villain.

Move two is written as a day rather than as a capability list: actors, verbs,
sequence. It opens on a fixed pivot ("Running well," or "Run well," or "When it
runs well,") and it ends on this component's sharpest promise phrased as an
impossibility. That last clause must reappear below as a numbered requirement.

This is the only section in the contract permitted to age, which is why it opens
with a time anchor from the closed set above.
-->

## Scope

VERBLESS NOUN PHRASE INVENTORY OF WHAT THIS COMPONENT OWNS, COMMA SEPARATED, WITH NO LEAD IN. WHAT IT HANDS OFF, ONE CLAUSE EACH, BELONGS TO [SIBLING TITLE](spec-NN-sibling-slug.md); SOMETHING ELSE IS OWNED BY [ANOTHER SIBLING](spec-NN-other-slug.md), because A PRINCIPLE A THIRD WRITER COULD RE DERIVE WITHOUT ASKING ANYONE.

**Exclusion.** WHAT THE PRODUCT WILL NOT DO, PLUS WHO DOES IT INSTEAD, OR WHAT CLASS OF REQUEST A FUTURE ASK WOULD BE.

<!--
THREE MOVES, IN THIS ORDER, 32 TO 92 WORDS.

1. What it owns: a verbless noun phrase inventory.
2. What it hands to a sibling: one clause per handoff, verb "belongs to" or "is
   owned by" or "lives in", the sibling named by its human title and linked by
   bare relative file name. Never a folder path, so moving a document never
   breaks a citation. Back links are not required; what is required is that the
   receiving side never contradicts.
3. Optionally, why: a "because" clause giving the principle behind the split.
   Write one wherever the split is arguable. Three boundary devices settle most
   disputes: a rule that holds unchanged across two documents in a chain belongs
   to the later one; the operator visible half belongs here and the machinery
   belongs to the sibling that owns machinery; the behaviour belongs here and
   the choice of how much of it ships belongs to the production component.

Shared ownership is licensed once per component: "The commercial consequences of
X are shared with [Sibling](spec-NN-sibling-slug.md)."

The Exclusion paragraph is optional. When present it never says "out of scope";
it always says who does the thing instead, or what class of request a future ask
would be.
-->

## A MOMENT IN THE WORKING DAY, OR A GERUND NAMING AN ACTIVITY, OR A STATED INVARIANT

- **UR-XX-01** (DJ-01) FULL SENTENCES STATING OBSERVABLE PRODUCT BEHAVIOUR. ABOUT FORTY WORDS. ONE TESTABLE PROPOSITION.
- **UR-XX-02** (DJ-01, DJ-04) A REQUIREMENT THAT TWO JOURNEYS PROVE. ONE PARENTHESIS, COMMA SPACE, ASCENDING, NEVER A SECOND BRACKET AND NEVER THE WORD "AND".

<!--
BULLET GRAMMAR, CHARACTER BY CHARACTER.

    - **UR-XX-nn**\* (DJ-mm, DJ-nn) Sentence. Sentence.

A hyphen and a space at column 1. The line is anchored, so a requirement that is
not at the start of its own line does not exist as far as traceability is
concerned. That is the reason for the anchor, not a formatting preference.

Then the bold identifier. Then, only for a clause inherited from a prior locked
contract, a backslash escaped literal asterisk (the escape is what stops the
renderer opening an italic run to the next asterisk on the line). Then exactly
one space, the tag in round brackets, exactly one space, and the requirement
text starting with a capital.

Full sentences with a period. Never a fragment, never a nested list, never a sub
bullet. Prefer one journey per requirement; two is common; three is the signal
that a requirement is doing too much.
-->

THE OPTIONAL INTERSTITIAL PARAGRAPH DOES EXACTLY ONE OF TWO THINGS: IT DEFINES A TERM THE SURROUNDING BULLETS USE, OR IT SPELLS OUT THE CONSEQUENCE OF THE ADJACENT BULLETS SO NOBODY LATER SOFTENS THEM. IT NEVER ADDS A NEW OBLIGATION, WHICH IS WHY IT NEEDS NO IDENTIFIER.

## ANOTHER THEMED SECTION, ITS HEADING CARRYING THE ARGUMENT AND ITS CARVE OUT

- **UR-XX-03**\* (DJ-04) A CLAUSE INHERITED FROM A PRIOR LOCKED CONTRACT. THE MARKER SAYS THAT CHANGING THIS TEXT IS AN AMENDMENT RATHER THAN AN EDIT. DELETE THE MARKER IF NOTHING IS INHERITED.
- **UR-XX-04** (constraint) A STANDING RULE NO OPERATOR PERFORMS, TRUE CONTINUOUSLY RATHER THAN AT AN INSTANT, VERIFIED BY SOMETHING OTHER THAN A SCREEN, AND CONSTRAINING THE BUILD RATHER THAN THE PRODUCT'S BEHAVIOUR.

<!--
HEADINGS ARE NEVER NUMBERED. Numbering lives entirely in the identifiers, so a
numbered heading creates a second competing address space. Three moods are
permitted and no fourth: a moment in the working day with the actor as subject,
a gerund naming an activity, or a stated invariant, usually negative. Where a
section has a rule plus a carve out, both go in the heading, joined by a
semicolon or by ", or".

Never used: Overview, Introduction, General, Background, Functional
requirements, Non-functional requirements, Constraints, Assumptions,
Dependencies, Glossary, References, Appendix.

BOLD HAS FOUR JOBS and emphasis is not one of them: requirement identifiers, the
version and lock strings, the Exclusion lead in, and a term at its single point
of definition or a number the product owner personally signed.

THE CONSTRAINT TAG replaces the journey list and is never combined with one.
There is no empty parenthesis and no third option. Keep it scarce: about two
percent of a contract, and every use is a promise nobody can watch being kept.
-->

---

Traceability: UR-XX-01 to UR-XX-04 → DJ-01, DJ-04.

<!--
THE TRACEABILITY FOOTER is one sentence, always range endpoints and never an
enumeration, then the journeys ascending, comma separated, terminated by a
period. The range form is what makes retirement cheap: a withdrawn identifier
costs no footer edit, where an enumeration would have to be maintained and would
drift. Exactly one horizontal rule sits above it, and there is no other
horizontal rule in the file.

AT LOCK, add the glyph to the version line and append this as the final line:

    🔒 **Locked: v1.0 (YYYY-MM-DD).**

The footer is a state assertion. It never says why the version moved, never
lists what changed, and never names a reviewer. Provenance lives in git, in the
crosswalk, and in the registry.

TARGETS FOR A FINISHED DOCUMENT: about 1,000 body words, ten to twenty five
requirements, about forty words each, one journey per requirement, zero
technology nouns, zero code spans, one horizontal rule.
-->
