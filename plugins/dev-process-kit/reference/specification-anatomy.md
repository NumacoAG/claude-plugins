# The anatomy of one specification

The measured detail behind the skeleton in
[spec-template.md](../templates/spec-template.md). Every example below is quoted
from the [worked example](worked-example.md) and is an example, never the rule.

## The skeleton, in order

| # | Element | Line | Required |
|---|---|---|---|
| 1 | H1 title, a bare noun phrase | 1 | always |
| 2 | blank | 2 | always |
| 3 | version line, four fields, middle dot separated | 3 | always |
| 4 | blank | 4 | always |
| 5 | essence line, one italic sentence | 5 | always |
| 6 | `## Why this matters`, a two move paragraph | | always |
| 7 | `## Scope`: owns, hands off, because | | always |
| 8 | `**Exclusion.**`, a bold lead in paragraph inside Scope | | optional |
| 9 | themed requirement sections | | always |
| 10 | `---`, exactly one per file | | always |
| 11 | traceability footer, then the lock footer | last | footer at lock |

The title is never the file name, the component code, or the word
"specification". Usually three or four things joined by commas: *Warehouse,
packing, shipping, and returns*. A colon may state the theme rather than the
parts: *How work gets done: workflows and the assistant*. A single term serves
where the territory is already one thing: *Quotation and pricing*.

## The version line

```
**v3.0** 🔒 · component 1 of 11 · Tier 1 specification
```

Four fields separated by a middle dot with one space each side, never a comma
and never a pipe: the bold two part version, the lock glyph, `component N of M`,
and the class of document. The third field is what makes any single file self
locating when it is read alone on a phone, and it is the only field this plugin
adds.

The version number, when it bumps, the lock glyph, and what a lock does to the
line all belong to review-kit's `obsidian-versioned-review`, which is the sole
authority on them. Read it there; nothing about the review regime is restated
here.

## The essence line

One sentence, present indicative, italic, on line 5. Six properties, all six
present in every good instance.

1. **No modal verb and no "the system".** The subject is the work.
2. **A pivot mark splitting claim from proof.** Abstract promise on the left, the
   same promise enumerated on the right.
3. **It names the invariant that would break first**, stated negatively.
4. **At least one hard noun from the physical or monetary world**, and no
   technical noun at all.
5. **It is a promise a person could be held to**, not a feature set.
6. **It survives being read alone**, and compresses to one table cell in the
   front door. A line that will not compress is doing too much.

> *Physical truth and paper truth never drift apart: every unit, box, parcel, and return reconciles with its record, and no correction ever rewrites history.*

> *One guarded path from the customer's purchase order to paid and deliberately closed; every document right the first time: number, language, terms.*

## Why this matters, the two move shape

One paragraph, never bulleted, 53 to 70 words. Move one is the pain today, named
as a **location** problem. Move two is the same work running well, opened by a
fixed pivot: `Running well,` or `Run well,` or `When it runs well,`.

> Hours live in a time tracker, budgets live in statement of work documents, and the two disagree. Month end timesheets mean copy and paste, and nobody can say at a glance how much of an hours bank remains. Running well: an engineer books, an operator approves, the timesheet attaches itself to the invoice, and billing past the agreed budget cannot happen.

Four structural notes, visible here and in the second annotated example in the
[worked example](worked-example.md).

- Move one is **three specific failures**, not one general complaint: three named
  containers, then the consequence in one short sentence.
- Move two is written as a **day**, not as a capability list. Actors, verbs,
  sequence.
- Move two **ends on the hardest single guarantee**, phrased as an
  impossibility, and that clause reappears below as a numbered requirement.
- Move one **never blames a person** and never names a competing tool as
  inadequate. A tool is a container, not a villain.

A component with no incumbent process may substitute a different opposition for
today and running well, such as written against unwritten, provided move two
still ends on the impossibility.

## Scope, and how boundary disputes are settled

Three moves, in one or two short paragraphs, 32 to 92 words: what it owns, as a
verbless noun phrase inventory; what it hands to a sibling, one clause each,
with the sibling named by its human title and linked by bare relative file name;
and optionally why, as a `because` clause.

> Cost build up, currency, margin, the operator's price decision, the quotation document, and quote validity. Identifying the product belongs to [Catalogue and sourcing](spec-03-catalogue-and-sourcing.md); the customer purchase order and everything after it belongs to [Order to cash](spec-05-order-to-cash.md). Document language, wording, VAT treatment, rounding, and payment terms are owned by [Order to cash](spec-05-order-to-cash.md) and [Finance and accounting](spec-07-finance-and-accounting.md), **because they apply identically from quotation through invoice**.

The links inside this excerpt name files of the example project, so they resolve there and not here.

Disputes are settled by the reason attached to the assignment, never by the
assignment alone, so a third writer can re-derive the decision without asking
anyone. Three devices do most of the work.

- **The chain rule**, quoted above: a rule holding unchanged across two
  documents in a chain belongs to the later one.
- **The visible half rule**: *It also owns the operator visible half of
  unattended work. The recovery machinery behind it belongs to Production
  expectations.*
- **The choice rule**: *Which channels are live at launch, and which stay
  manual, is a production decision and lives in Production expectations.*

Ownership is not forced to be total. A declared shared clause is licensed once
per document: *The commercial consequences of a return are shared with Order to
cash and Finance and accounting.*

Links are always bare relative file names, never folder paths, so moving a
document never breaks a citation. Back links are not required; what is required
is that the receiving side never contradicts.

## The exclusion paragraph

Optional, always inside Scope, always a bold lead in. An exclusion never says
"out of scope". It says who does the thing instead, or what class of request a
future ask would be.

> **Exclusion.** The product never books a shipment with a carrier and never pays a carrier for postage: it estimates and records what a shipment should cost, and a person books and pays outside the product.

## Bullet grammar, character by character

```
2d 20   2a2a UR-XX-01 2a2a   5c 2a   20   28 DJ-01 29   20   Sentence.
 -  SP    **          **      \  *   SP    (       )   SP
```

- A hyphen and a space at column 1. Never indented, never an asterisk bullet,
  never numbered. **The line anchor is the contract**: a requirement that is not
  at the start of its own line does not exist as far as traceability is
  concerned. State the anchor as the reason, not as a formatting preference.
- The bold identifier, its number zero padded to the declared width.
- Optionally a backslash escaped literal asterisk, marking a clause inherited
  from a prior locked contract. The escape stops the renderer opening an italic
  run to the next asterisk on the line. It is a provenance mark, never an
  importance mark, and the prior identifier never appears in the prose.
- Exactly one space, the tag in round brackets, exactly one space, then the text
  starting with a capital.

Multiple journeys go in one parenthesis, comma space, ascending: `(DJ-05, DJ-06,
DJ-10)`. Never a second bracket, never the word "and", never a range, never a
line break. One journey per requirement is the target, two is common, and three
is the signal that a requirement is doing too much.

Bodies are full sentences with a period: no fragment, no nested list, no sub
bullet.

## Headings

**Never numbered.** Numbering lives entirely in the identifiers, so a numbered
heading opens a second competing address space. Three moods, and no fourth.

1. **Present indicative with the actor as subject**, a moment in a working day:
   *A user opens the product*, *An invoice goes overdue*.
2. **A gerund naming an activity**: *Knowing what is where*, *Booking time*.
3. **A stated invariant, usually negative**: *Nothing happens off the record*,
   *The line no saving crosses*.

Where a section carries a rule plus a carve out, both go in the heading, joined
by a semicolon or by ", or": *The budget warns, the cap refuses*, *A payment
settles exactly, or a person decides*.

Never used: Overview, Introduction, General, Background, Functional
requirements, Non functional requirements, Constraints, Assumptions,
Dependencies, Glossary, References, Appendix.

**The one shape decision this plugin makes for you**: themed `##` sections sit
directly after Scope, with no `## Requirements` wrapper. The wrapper adds nothing
semantically, and one shape means a new document never re-decides.

## The conventions that hold across a whole set

**Bold has four jobs and emphasis is not one of them.** Requirement identifiers;
the version and lock strings; the `**Exclusion.**` lead in; and a term at its
single point of definition, or a number the product owner personally signed. One
licensed outlier: bolding a conjunction so *exact reference **and** exact amount*
cannot be misread as *or*.

**A coined term is glossed exactly once**, in parentheses, at its first
appearance anywhere in the set, and used bare forever after, across documents.
That single definition stops a set of documents becoming a set of glossaries.

**Requirements cite each other by identifier and never restate the cited rule**:
*the exactly once rule of UR-AB-11*. There is exactly one place any rule can be
edited, and the identifier is the citation.

**The interstitial paragraph** does one of two things and never a third: it
defines a term the surrounding bullets use, or it spells out the consequence of
the adjacent bullets so nobody later softens them. It **never adds a new
obligation**, which is why it needs no identifier and does not breach
traceability. The tell of a good one is the phrase *by design*.

**The typed confession.** Where an act's damage falls on the company or a third
party and is invisible at the moment of the act, require a typed first person
admission of the specific harm. Its power is scarcity: three in a whole
contract, and they are the only quoted strings in the set. See the
[worked example](worked-example.md).

**Numbers appear only where the product owner signed them**, each carrying unit,
statistic, and adjustability in one breath: *two seconds at the 95th percentile*,
*the configurable floor, initially 15 percent*. The word "initially" is the only
licensed way to state a soft number, and there are no unqualified soft numbers
anywhere.

**The negative voice is the dominant voice.** A good contract fences off the
failure far more often than it describes the happy path: *never invents a part
number*, *no confidence score and no near match*.

**The actor vocabulary is closed.** Declare a small set, typically the product,
the operator, a person, and at most one product specific actor, and never
introduce another. A fifth actor is a signal that the component is wrong.

## The one licensed escape hatch

Where a rule genuinely needs an algorithm, state the outcome, name the
guarantee, and hand the algorithm down a tier by name:

> Near identical licence identities always go to a person. The product never resolves a suspected duplicate on its own; **the exact matching rule lives in Tier 2.**

Once or twice in a whole contract. That single pressure valve is what lets the
no technology rule hold everywhere else. Without a valve the rule gets broken
quietly instead of used once.
