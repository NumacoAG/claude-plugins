# Bootstrapping a contract from nothing

The procedure that turns a project with no clauses into an approved component
manifest, before a single identifier is minted. It runs days first and
components second, because every project has days even when it has no clauses.

Two arithmetic identities govern the shape:

```
journeys    J = 7 + F'      seven fixed days, plus one per value chain face
components  N = 3 + F       three fixed components, plus one per commercial face
```

The seven fixed days are: a new computer joins, people and permissions change,
nothing falls through, nobody touches the keyboard, the product is attacked,
disaster strikes, and it feels like one product. The three fixed components are
the platform and access component, the tempo and unattended work component, and
the production constraints component. `F` may exceed `F'`, because one day can
exercise two commercial faces.

## Step 0. Initialise

`contract.py init` writes the contract folder with its front door, an empty
registry, the configuration at the project root, and the reserved proving
directory. Nothing else exists yet, and nothing else should.

## Step 1. Harvest candidate days

A day exists wherever truth currently sits in the wrong container. That is the
extraction instruction, and it is why the harvest reads what people handle
rather than what the build contains.

| Project shape | Inputs the session may read | Extraction |
|---|---|---|
| A running system | Screens, printed and emailed documents, notification texts, exported files, the support inbox, the reported titles in the issue tracker, the manual runbook | One candidate day per artefact a person handles end to end |
| A pile of notes | Every file, every heading | One candidate day per "we need to be able to" sentence, grouped by the noun that moves |
| Greenfield | The calendar, the mailbox, the spreadsheet being replaced, the physical folders, one interview per role | One candidate day per recurring calendar block, and per spreadsheet two people both edit |

**The four harvest bans.**

1. A candidate day whose title names a screen, a module, a table, a service, a
   role name, a proper noun, a number, or a modal verb is rejected. Titles take
   the form "The day, subject, present tense verb" with the subject drawn from
   the four permitted kinds.
2. In a running system, any candidate component name that string matches a top
   level source directory is auto rejected and must be renamed by what the
   operator does. This is the single guard that stops the code's decomposition
   being re-imported as the contract.
3. The harvest never reads the module tree, the schema, or the issue tracker's
   internal titles. If the operator cannot see it, it cannot generate a day.
4. A candidate day with no artefact that exists today is speculative. It goes to
   a speculative list rather than the census, and at most **three** speculative
   days may ever be promoted.

**The artefact rule.** Every promoted day names the file, mail thread, calendar
block, or manual step that evidences it, and the census carries the count of
harvested artefacts behind each day. A day backed by forty threads and a day
backed by one are visibly different at the moment of approval.

## Step 2. Fold to the fixed skeleton

Write the seven fixed days verbatim. Then cluster the harvest into value chain
days by the noun that moves, in the order money actually moves. Two candidate
days merge when the same person experiences them as one continuous stretch.

## Step 3. Gate one, the day list

Surface the census for review. Titles only: no checkboxes, no specifications, no
identifiers. This is the cheapest gate in the process and it determines
everything downstream, because it fixes the acceptance skeleton, the component
count, and the traceability denominator. Iterate until the product owner locks
it. Locking the census mints the journey identifiers and burns those numbers
permanently.

## Step 4. Derive the components, then falsify them

The derivation is mechanical: one component per irreducible noun that moves,
plus the three fixed components. Each candidate gets a name, a draft essence
line, a draft scope inventory, and the journeys it expects to serve. Then five
tests attack it.

| Test | Statement | Pass band | Why the band |
|---|---|---|---|
| T1 essence | A single sentence names the invariant that breaks first, with one pivot mark and no top level "and" joining two unrelated promises | 17 to 31 words | A sentence needing a second promise is describing two components |
| T2 fan | Distinct journeys the component's requirements cite | 2 to 6 passes, 7 or more is suspect | Fan predicts a needed split better than word count does, because a large document at low fan is usually legitimately large |
| T3 mass | Requirement count | 10 to 25 | Below 10 the candidate is a section of a sibling; above 25 it is two documents |
| T4 closure | Every noun in the owned inventory either lives here or is handed to exactly one named sibling, with a "because" clause wherever the split is arguable | at most one shared declaration | Shared ownership is a licensed exception, and a second one means the boundary is guesswork |
| T5 blast radius | Delete the component on paper and count the siblings needing an edit | 2 to 4 | Fewer than 2 means it is a section of one sibling; more than 4 means it is cross cutting and must dissolve into its siblings |

A candidate failing T1 or T4 is redrafted. A candidate failing T2 or T3 upward
splits. A candidate failing T3 downward merges into its nearest sibling by
shared journey set. A candidate failing T5 either dissolves or absorbs.

**Overlap resolution, first rule that fires wins.**

1. **The chain rule.** A rule that holds unchanged across two documents in a
   chain belongs to the later one; the earlier one cites it.
2. **The visible half rule.** The operator visible surface belongs to the
   component whose day shows it; the machinery behind it belongs to the
   production constraints component.
3. **The choice rule.** The behaviour belongs here; the decision about how much
   of it ships belongs to the production constraints component.
4. **A declared shared clause**, only when rules 1 to 3 all fail, and only once
   per component: "The commercial consequences of X are shared with [Sibling]."
5. **A cite bullet**, when none of the above fits. It names the owner, carries
   no journey tag, mints no identifier, and states no obligation:

   ```
   - ↪ **UR-OC-04** (owned by [Order to cash](spec-05-order-to-cash.md)) Carriage terms reach the packing floor unchanged.
   ```

   The link names a file of the example project; in a real contract it resolves to the sibling document.

   At most three per document, so the pressure stays toward real ownership.

## Step 5. Gate two, the component manifest

Names, essence lines, scope paragraphs, and expected journeys go to the product
owner. Still no identifiers. This is the last moment renumbering is free.

## Step 6. Mint, write, and gate three

Scaffold one file per approved component with the frame filled and the
requirement sections empty. Identifiers are minted in document order within a
component on the first write only; every later birth goes to the end of the
range. Gate three is the per document lock, and it is the moment identifiers
stop moving.

## Split health tripwires

Run these after the first full draft and before any lock:

1. A component at fan 7 or more that is still over budget after two trim rounds.
2. A single call to action requiring edits in three or more documents. One
   boundary is in the wrong place; two such comments in one round means the
   split is wrong.
3. A journey reached by fewer than three requirements from any single document,
   which means nobody owns that day.
4. More than one shared declaration in the whole set.
5. The same coined term glossed in two documents. A term is glossed exactly
   once, anywhere in the set, and used bare forever.
6. A proposed identifier that would need to move between components.

A redo is legal only before the first lock. After the first lock, tripwires 1 to
5 are handled by the component operations in
[identifiers-and-registry.md](identifiers-and-registry.md), never by a redo.

## Five attacks on this design, and their repairs

**The greenfield census is fiction, because nobody has lived the day.** The
artefact rule answers it: a day must be evidenced by something that exists
today, and the product being new does not mean the work is new. Speculative days
are capped at three and are marked as such, so a reviewer sees exactly how much
of the contract is imagination.

**Deriving components from journeys collapses to one component per journey.**
The identity is `N = 3 + F`, never `N = J`. The seven fixed journeys generate
exactly two components between them, and the mapping between faces and days is
explicitly many to many.

**A running system re-imports its own architecture.** The source directory name
ban plus the input whitelist, which excludes the module tree entirely.

**No operator exists**, because the tool is internal and single user. The proxy
operator is whoever does the manual work today. If genuinely nobody does the
work yet, the project is pre-contract: it writes the census as a forecast, gets
it approved, and is barred from locking any document until at least one journey
has been staged once by a person.

**Gate one approves titles whose cost the owner cannot yet see.** The artefact
count per candidate day is what makes the cost visible at the moment of
approval.
