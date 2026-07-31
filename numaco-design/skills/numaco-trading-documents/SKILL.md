---
name: numaco-trading-documents
description: >-
  Produce Numaco AG branded trading documents as PDF files in the locked Signal Stack style. Use whenever the user asks to create, recreate, revise, or format a quotation, commercial offer, product quote, order confirmation, sales order confirmation, delivery note, packing slip, invoice, commercial invoice, Rechnung, Offerte, Angebot, Auftragsbestätigung, or Lieferschein. The skill supports English and German, validates prices and totals, preserves the standard quotation columns for list price, discount, unit price, and total price, omits prices from delivery notes, and renders every document through the shared Numaco PDF engine. Use numaco-sow instead when the request is for a scoped consulting Statement of Work or service proposal with effort, deliverables, and commercial terms.
---

# Numaco trading documents

Produce one of four customer facing documents through the shared builder:

1. Quotation
2. Order confirmation
3. Delivery note
4. Invoice

All four use the same compact Signal Stack layout, company identity, address
blocks, table geometry, footer, and PDF verification workflow. The engine is
`scripts/build_trading_document.py` and accepts one JSON payload.

## Routing

Use this skill for a commercial product or licence quotation, an order
confirmation, a delivery note, or an invoice. Use `numaco-sow` for a consulting
engagement proposal that defines scope, deliverables, assumptions, effort, and
project terms. Use `numaco-report` for narrative reports and technical documents.

## Workflow

### 1. Establish the source

Use the document or transaction data supplied by the user. When asked to
recreate an existing document, inspect the source workbook, ERP record, email,
or prior PDF before building the payload. Reuse the customer legal name,
address, reference, purchase order, item codes, dates, and prices exactly.

Never invent a document number, customer address, purchase order, price,
discount, VAT treatment, bank detail, due date, or delivery fact. Ask only for
information that cannot be recovered from the sources the user placed in scope.

### 2. Choose the document type

Set `document_type` to one of:

* `quotation`
* `order_confirmation`
* `delivery_note`
* `invoice`

Use `language: "de"` or `language: "en"`. Use `currency: "CHF"`.

### 3. Preserve each document contract

Quotation tables always show position, item, description, quantity, list price,
discount, unit price, and total price. The discount must be a real field and
must reconcile to the list price and unit price. Do not bury it in the prose.

Order confirmations and invoices show position, item, description, quantity,
unit price, and net line total. Totals must reconcile to the line items.

Delivery notes show position, item, description, and delivered quantity. They
must never expose prices, discounts, totals, or payment values.

Invoices show the annual default interest clause at 5 percent pursuant to
Article 104 paragraph 1 of the Swiss Code of Obligations. Do not print a worked
interest amount or assume a day count convention.

### 4. Build the JSON payload

Start from the matching fictional payload under `sample/`. Replace every sample
value with verified transaction data. The common structure is:

```json
{
  "document_type": "invoice",
  "document_number": "IN260004",
  "language": "en",
  "currency": "CHF",
  "issue_date": "30.07.2026",
  "due_date": "29.08.2026",
  "payment_terms_days": 30,
  "customer_po": "PO 450000001",
  "customer": {
    "name": "Example Manufacturing AG",
    "address": ["Accounts Payable", "Industriestrasse 12", "CH 8000 Zurich"],
    "references": ["Reference: OC260004, DN260004"]
  },
  "lines": [
    {
      "position": "10",
      "item": "ITEM CODE",
      "description": "Verified line description.",
      "quantity": 2,
      "unit_price": 340.00,
      "total_price": 680.00
    }
  ],
  "totals": {
    "net": 680.00,
    "vat_rate_percent": 8.1,
    "vat_amount": 55.08,
    "rounding": 0,
    "grand_total": 735.08
  }
}
```

Quotation lines additionally require `list_price` and `discount_percent`.
Quotations require `valid_until`. Invoices require `due_date`. Order
confirmations and invoices require `totals`. Delivery note lines contain no
price fields and may use `ship_to`, `carrier`, and `tracking`.

The builder calculates missing line totals and grand totals, but use explicit
values from the source when they exist. It rejects line arithmetic, discount
arithmetic, VAT, and document totals that do not reconcile within two cents.

### 5. Render

Save the reviewed payload beside the final PDF, then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/numaco-trading-documents/scripts/build_trading_document.py" "/absolute/path/payload.json" "/absolute/path/output.pdf"
```

The builder writes a self contained HTML sidecar, renders the PDF through the
shared paged engine, and runs the CoreGraphics fidelity check on macOS.

### 6. Verify before presenting

Inspect every generated page. Confirm:

* Customer, issuer, references, document number, and dates match the source.
* Quotation discount values are visible and reconcile.
* Financial columns are right aligned and table rows are vertically centred.
* Totals reconcile and the amber total rule does not cross any figure.
* Delivery notes contain no financial information.
* Invoices contain the 5 percent annual clause but no worked interest amount.
* No text is clipped, crowded, or split across the page boundary.

Present the PDF for review. Iterate from the saved JSON payload so the document
remains reproducible.
