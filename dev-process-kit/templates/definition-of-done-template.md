# Definition of Done

**v0.1** · Tier 1 acceptance contract

The M component specifications say what the product must do. This contract says what must be **shown working end to end** before release: J days in the life that prove the product. When all J pass, THE ORGANISATION RUNS ON THIS SYSTEM. Fixtures, negative controls, evidence paths, and lane rules are deliberately absent: engineering owns them.

<!--
HOW TO USE THIS TEMPLATE

Placeholders are IN UPPER CASE. M is the component count, J the journey count.
Replace every placeholder, then delete every comment block in this file.

THE TITLE is the bare noun phrase "Definition of Done". No product name, no
version, no scope words.

THE FRAMING PARAGRAPH is exactly four sentences and about 63 words, with no
heading above it, and each sentence has one job.

  1. Defer to the sibling documents: what the product does lives elsewhere.
  2. Define this document's job by the days metaphor, and bold the single
     operative verb phrase, "shown working end to end".
  3. State the consequence in one clause, with no hedge.
  4. Fence off the engineering material and name its owner.

This document has no essence line, no "Why this matters", and no "Scope". The
framing paragraph does all three jobs, because this is the only document that is
about the other documents.

Reference: reference/definition-of-done-anatomy.md
-->

## Release rule

The release is done only when all of these hold.

- [ ] Every Tier 1 requirement and every applicable engineering production requirement passes, with evidence that can be reproduced on demand.
- [ ] Every journey below passes on the exact release that goes live, with nothing rebuilt or changed afterwards, and two separate runs from a clean start agree.
- [ ] No check fails, none is skipped, none passes only sometimes, no result is left over from an earlier run or stands in for a check that never ran, no failure is waived as acceptable, nothing the checks should cover is missing, and the machinery that runs the checks is itself free of defects.
- [ ] THE ONE EXCLUSION, STATED IN FULL. Nothing else is excluded.
- [ ] The product owner completes operator acceptance and approves the first watched live run.

<!--
FIVE BULLETS, FIVE JOBS, IN THIS ORDER, AND THIS BLOCK IS A FIXED CHECKLIST
RATHER THAN PROSE TO BE REDRAFTED EACH ROUND.

  1. Coverage across both tiers, and reproducibility rather than a stored
     result. A green record that cannot be regenerated is not evidence.
  2. Artefact identity plus determinism. The tested build is the shipped build,
     and the result is required twice from clean.
  3. Verdict integrity. One sentence on purpose, enumerating every cheat, so no
     cheat can be read as a separate negotiable clause. This is the clause most
     likely to shrink under editing pressure. Do not shorten it; count the
     cheats it names before and after every round.
  4. Scope closure. State the single exclusion in full, then close the set.
     "Nothing else is excluded" converts every future exclusion request into a
     contract change.
  5. A named human. Automated green is necessary and not sufficient.

THE BLOCK SITS ABOVE THE JOURNEYS. A reader who met the journeys first would
reasonably conclude that J ticks equals release, and every cheat in bullet three
is a way to produce J ticks.
-->

## The J days

<!--
The container heading counts the journeys, so the count is load bearing prose
rather than an accident of the list.

ORDER: access and role first, then the value chain in the order money actually
moves, then tempo, then failure, then wholeness. The seven fixed days below are
fixed for any product; only the value chain scales, at one journey per
commercial face. A group with no real day is dropped, never padded.

HEADING GRAMMAR: three hashes, the two digit zero padded identifier, a full
stop, a space, then the title. The title opens "The day" and everything after it
is lower case. Between two and seven words follow "The day". Simple present
throughout, the gnomic present of a typical day, never future, never
conditional, never a gerund.

THE ADMISSION TEST: a candidate earns a slot only if a real day exists where one
person experiences it as one continuous stretch. Subjects come from four kinds
and no fifth: a thing that arrives or moves, a person outside the building, an
absence, or the product itself in a reflexive journey.

NEVER IN A TITLE: a component name, a specification code, a role name, a
technology, a feature name, a screen name, a number, a modal verb, a proper
noun.

CHECKBOXES: four per journey is the target and five is the ceiling. Third person
present indicative, active. The subject is an actor or an artefact, never a
component. The capability and its bound go in one sentence, with the bound
stated as a refusal an operator would witness. Zero modal verbs. Every number is
a quantity a person experiences. No path, identifier, environment, fixture, or
command appears anywhere.
-->

### DJ-01. The day a new computer joins

- [ ] A CLEAN MACHINE INSTALLS THE EXACT RELEASE AND LAUNCHES, WITH THE PREREQUISITES NAMED.
- [ ] EACH SUPPORTED SURFACE CARRIES THE FEATURE SET IT PROMISES, AND ONLY THAT SET.
- [ ] ROUTINE STARTS MEET THEIR STATED SPEED, AT A STATED STATISTIC.
- [ ] A DEGRADED START SAYS SO, RETRIES SAFELY, AND ACCEPTS NO COMMAND BEFORE READINESS.

### DJ-02. The day people and permissions change

- [ ] SIGN IN OPENS ONE SHARED LIVE DATA SET, AND STAYS USABLE THROUGH A WORKING DAY.
- [ ] EACH ACCESS LEVEL SEES EXACTLY ITS PERMITTED RECORDS AND ACTIONS, ON EVERY SURFACE.
- [ ] AN ADMINISTRATOR ADDS, CHANGES, AND REVOKES ACCESS, AND RECOVERS CONTROL BY THE RECORDED EMERGENCY ROUTE.
- [ ] A REMOVAL TAKES EFFECT WITHIN A STATED TIME AND CANNOT BE BYPASSED.

### DJ-nn. The day THE THING THAT MOVES DOES WHAT IT DOES

- [ ] THE CAPABILITY, JOINED TO ITS BOUND, IN ONE SENTENCE.
- [ ] THE SECOND PROPOSITION THIS DAY PROVES.
- [ ] THE THIRD.
- [ ] THE FOURTH, USUALLY THE ONE STATING WHAT THE PRODUCT REFUSES TO DO.

<!--
REPEAT THE BLOCK ABOVE ONCE PER COMMERCIAL FACE, in the order money moves, and
number them upward from DJ-03. One journey per irreducible face. Two candidate
days merge when the same person experiences them as one continuous stretch.
-->

### DJ-nn. The day nothing falls through

- [ ] EVERY OPEN COMMITMENT HAS AN OWNER, A DUE DATE, A NEXT ACTION, AND AN EVIDENCE LINK.
- [ ] REMINDERS AND EXPIRIES SURFACE AT THE RIGHT TIME.
- [ ] EACH OPERATOR RECEIVES A BRIEFING OF PRIORITIES, OVERDUE WORK, AND OVERNIGHT RESULTS.
- [ ] AN UNMATCHED INCOMING EVENT BECOMES A PROPOSAL, AND IS NEVER SILENTLY LOST.

### DJ-nn. The day nobody touches the keyboard

- [ ] WITH EVERY CLIENT CLOSED, SCHEDULED WORK RUNS AT THE INTENDED TIME AND CATCHES UP MISSED WORK EXACTLY ONCE.
- [ ] EACH SWEEP RESUMES FROM WHERE THE LAST ONE FINISHED AND READS ONLY WHAT IS NEW.
- [ ] A TIMEOUT OR PARTIAL OUTAGE KEEPS THE LAST SAFE STATE, MARKS IT STALE, AND OFFERS A SAFE RETRY.
- [ ] NO UNATTENDED FAILURE INVENTS DATA, DUPLICATES AN EFFECT, OR COMMITS AN OUTWARD ACT.

### DJ-nn. The day the product is attacked

- [ ] THE PRODUCT ANSWERS FROM REAL PERMITTED DATA AND DISTINGUISHES A FACT, AN ESTIMATE, A STALE VALUE, AND AN UNKNOWN.
- [ ] A HOSTILE INPUT CANNOT REVEAL ANOTHER USER'S DATA, SECRETS, OR SYSTEM INSTRUCTIONS.
- [ ] CONFIDENTIALITY BOUNDARIES HOLD IDENTICALLY IN EVERY SURFACE, EXPORT, AND LOG.
- [ ] A DELIBERATE DISCLOSURE RECORDS ITS AUTHOR.

### DJ-nn. The day disaster strikes

- [ ] ORDINARY DELETION OR CORRUPTION LOSES AT MOST THE STATED AMOUNT OF WORK AND RESTORES WITHIN THE STATED TIME.
- [ ] A COMPLETE INDEPENDENT RECOVERY SET STAYS WITHIN ITS STATED AGE AND HOLDS EVERYTHING NEEDED TO REBUILD ELSEWHERE.
- [ ] RECOVERY AGE AND HEALTH ARE VISIBLE, AND A MISSING OR OVERDUE SET ALERTS BY A ROUTE THAT DOES NOT DEPEND ON THE PRODUCT BEING UP.
- [ ] A DRILL PROVES THE PROMISE AND PRESERVES DOCUMENTS, HISTORY, NUMBERING, AND IDENTITIES.

### DJ-nn. The day it feels like one product

- [ ] THE PRODUCT PRESENTS ONE COHERENT DESIGN, WITH CONSISTENT NAVIGATION, TABLES, FORMS, STATUS LANGUAGE, AND FEEDBACK.
- [ ] EVERY REFUSAL AND FAILURE IS UNDERSTANDABLE TO AN OPERATOR, PRESERVES SAFE WORK, AND GIVES THE NEXT RECOVERY ACTION.
- [ ] THE SEEDED COMPLETE JOURNEY RUNS WITHOUT A DEVELOPER INTERPRETING THE SCREEN, REPAIRING DATA, OR INTERVENING BEHIND THE PRODUCT.
- [ ] THE RELEASE HANDOVER COVERS INSTALLATION, ROUTINE OPERATION, RECOVERY, AND EMERGENCY ADMINISTRATION, AND THE PRODUCT OWNER HAS EXERCISED IT.

<!--
THE DELIBERATE ABSENCE. Fixtures, negative controls, evidence paths, and lane
rules are named as absent in the framing paragraph and appear nowhere below it.

The reason, as a causal chain: the instant this contract carries a fixture
column, an evidence path column, and a lane column, it stops being a statement
of what done means and becomes a schema for a ledger. A schema invites rows.
Rows get generated before the behaviour exists, so they fill with placeholders,
and a placeholder is indistinguishable from a pass at a glance. One project that
did this produced 1,467 acceptance rows, 98 percent of them carrying placeholder
fixtures, beside roughly 2,621 real executable checks the ledger could not see.

The absence prevents three further failures: premature layer assignment, a
contract only engineers can review, and harness churn forcing a re-lock of a
document whose promises never changed.

The absence is a LOCATION decision, not a deletion. Every excluded item exists
one tier down, and the standing rule that protects the arrangement is this:
never weaken an oracle, remove a negative control, lower a test count, add an
exclusion, or reinterpret a failure to make a gate green.

AT LOCK, add the glyph to the version line and append:

    🔒 **Locked: v1.0 (YYYY-MM-DD).**
-->
