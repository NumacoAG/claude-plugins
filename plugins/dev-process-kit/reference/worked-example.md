# One contract, as a worked example

Everything on this page is an **example**, drawn from one enterprise resource
planning product built by the authors of this plugin. None of it is the rule.
The rules live in [specification-anatomy.md](specification-anatomy.md),
[definition-of-done-anatomy.md](definition-of-done-anatomy.md), and
[identifiers-and-registry.md](identifiers-and-registry.md). Read the three
divergences at the end so nobody copies a local decision as a law.

## The example contract at a glance

| Quantity | Value |
|---|---|
| Component specifications, and one Definition of Done | 11 |
| Acceptance journeys | 14 |
| Requirement identifiers | 210 |
| Descending from a prior locked contract | 82 |
| Born in this contract | 128 |
| Standing constraints | 4 |
| Burned identifier numbers | 2 |
| Documents locked | all 12, one at a time |

The set lives at `docs/specs/tier-1/`, with the registry and the generated
crosswalk under `docs/specs/tier-2/machine-readable/`, outside the locked folder
because a tool writes them and no one reviews them. Documents run from about 700 to
1,900 words, median close to 1,050.

## Example: the front door closure clause

> This folder is the whole product contract. Eleven specifications say what the product does; one Definition of Done says what must be proven working before release. Nothing else is Tier 1. If a promise is not in these twelve documents, the product does not make it.

## Example: one essence line

From the warehouse and shipping component, 24 words:

> *Physical truth and paper truth never drift apart: every unit, box, parcel, and return reconciles with its record, and no correction ever rewrites history.*

The pivot is the colon. The left half is the promise, the right half the same
promise enumerated. It ends negatively, on the invariant that would break first.
Compressed for the front door table, it becomes *Physical truth and paper truth
always reconcile*, which is the compression test passing.

## Example: one "Why this matters"

From the quotation and pricing component, 70 words, the longest in the set:

> Today a quote starts with archaeology: the last price sits in an old email thread, the usual margin lives in someone's memory, and landed cost is a spreadsheet guess that may be months stale. One forgotten customs charge turns a good deal into a quiet loss. Running well, the operator prices in minutes from one screen, and the only way to quote a loss is to record a deliberate override.

Three containers, then the consequence in one sentence. The pivot is *Running
well,*. The final clause is the component's hardest guarantee stated as an
impossibility, and it reappears below as a numbered requirement.

## Example: one Scope paragraph with a because clause

From the same component:

> Cost build up, currency, margin, the operator's price decision, the quotation document, and quote validity. Identifying the product belongs to [Catalogue and sourcing](spec-03-catalogue-and-sourcing.md); the customer purchase order and everything after it belongs to [Order to cash](spec-05-order-to-cash.md). Document language, wording, VAT treatment, rounding, and payment terms are owned by [Order to cash](spec-05-order-to-cash.md) and [Finance and accounting](spec-07-finance-and-accounting.md), **because they apply identically from quotation through invoice**.

The links inside this excerpt name files of the example project, so they resolve there and not here.

The because clause is a principle, not a decision. A third writer can re-derive
it without asking anyone.

## Example: three requirement bullets

The impossibility promised above, arriving as a requirement, with a typed
confession and an inherited marker:

> - **UR-QP-06**\* (DJ-04) The operator sets every figure offered to a customer, including unit price and packing and transport. An estimate never becomes an offered price automatically. A reseller margin below the configurable floor, initially 15 percent, draws a warning ⚙. Pricing below cost is blocked. So is a line whose current margin later falls below half the margin the operator set when creating the quote. Either block yields only to a recorded operator override, and the below cost gate opens only after the operator types "I know I am losing money on this sale".

The finest glyph discrimination in the set, two adjacent requirements in one
document, same unattended premise, opposite marking:

> - **UR-AB-07**\* (DJ-10, DJ-11) Reminders run ⚙ even when nobody has the product open. They appear in the queues and in the briefing, and can notify ⚙ by email or system notification.

> - **UR-AB-11**\* (DJ-11, DJ-13) Scheduled work runs even when the product is closed on every computer. It catches up each missed business interval exactly once, retries without duplicating its effects, respects business time, and makes failures and recovery status visible without exposing secrets or customer content.

Two glyphs in the first: reminders are a governable action type, and
notification is a separately governable channel. None in the second, because it
states a property of scheduled work in general rather than a nameable action
type an administrator could switch off.

The three typed confessions are the only quoted strings in eleven documents:
*I am aware of the risk and want to proceed* before revealing a customer's
identity to a distributor, *I know I am losing money on this sale* before
pricing below cost, and *I am risking wasting money because no customer
confirmation arrived* before ordering ahead of a purchase order.

## Example: one journey with its checkboxes

> ### DJ-04. The day a customer asks for a price
>
> - [ ] An operator finds or creates a product, compares real supplier offerings, sees freshness and confidence, and never receives an invented product, price, stock, or lead time.
> - [ ] A product never sold before is discovered and added inline, without abandoning the quote.
> - [ ] The quote builder handles quantities, currency, landed cost, shipping, packing, margin, validity, and minimum order rules, requires an explicit operator chosen price, and computes every amount, subtotal, and total itself.
> - [ ] Pricing below cost, and a line whose margin has halved since creation, stay blocked until the typed and recorded override, while the margin floor and erosion on an issued quote warn without blocking, and a stale or unavailable source stays visibly unresolved.
> - [ ] Issuing a quote creates the numbered document and a staged covering message, and sends nothing.

Five checkboxes rather than four, because this day carries five distinct pricing
gates. Every subject is an actor or an artefact. There is no modal verb, no
path, no fixture, and no number that a person does not experience.

## Five places this example diverges from the rule

1. **Its component codes are two uppercase letters** because it has eleven
   components and two letters read well at that size. A project with four
   components is better served by longer, pronounceable codes, and the
   configuration accepts any pattern.
2. **Its action glyph is a project decision, not a law.** The plugin ships no
   glyph, and three of these eleven documents carry none either.
3. **Its journey count is an output of its shape, not an input.** Seven of the
   fourteen days are the fixed skeleton every product has; the rest are one per
   commercial face.
4. **Its section shape is inconsistent and the plugin harmonises it.** Six of the
   eleven documents put themed `##` sections directly after Scope; the other five
   wrap them in a `## Requirements` heading with `###` subsections. Both read
   well. The plugin picks the first so that a new document never re-decides, and
   the exemplar shows you the alternative anyway.
5. **One of its documents trips the plugin's own budget.** `spec-02` carries 30
   requirements against a band of 10 to 25, and reaches 10 journeys against a
   suspect threshold of 7. The budget is right and the document is a component
   that wants splitting. An exemplar that hid this would be teaching that the
   band is decorative.
