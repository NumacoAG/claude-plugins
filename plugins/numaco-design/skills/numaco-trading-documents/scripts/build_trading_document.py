#!/usr/bin/env python3
"""Build Numaco quotation, order confirmation, delivery note, and invoice PDFs.

The input is one JSON payload. The builder validates document semantics and
financial arithmetic, renders the locked Signal Stack trading document layout,
and verifies the PDF through the shared CoreGraphics workflow on macOS.

Usage:
    build_trading_document.py payload.json output.pdf
"""

from __future__ import annotations

import base64
import html
import json
import os
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

ND = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ND / "shared" / "signature"))
import signature as S  # noqa: E402


TWO = Decimal("0.01")
TOLERANCE = Decimal("0.02")
VALID_KINDS = {"quotation", "order_confirmation", "delivery_note", "invoice"}
VALID_LANGUAGES = {"en", "de"}

NUMACO = {
    "name": "Numaco AG",
    "address": ["Haldenstrasse 3c", "CH 8905 Islisberg", "Switzerland"],
    "vat": "CHE-107.980.861 MWST",
    "bank_name": "UBS Switzerland AG",
    "bank_address": "Bahnhofstrasse 11, 5201 Brugg",
    "iban": "CH08 0021 0210 1452 5701 F",
    "swift": "UBSWCHZH52A",
}

TEXT = {
    "en": {
        "quotation": "Quotation",
        "order_confirmation": "Order Confirmation",
        "delivery_note": "Delivery Note",
        "invoice": "Invoice",
        "document_no": "Document no.",
        "date": "Date",
        "valid_until": "Valid until",
        "expected_delivery": "Expected delivery",
        "due_date": "Due date",
        "payment_terms": "Payment terms",
        "days_net": "days net",
        "customer_po": "Customer PO",
        "carrier": "Carrier",
        "tracking": "Tracking",
        "from": "From",
        "bill_to": "Bill to",
        "deliver_to": "Deliver to",
        "item": "Item",
        "description": "Description",
        "qty": "Qty",
        "qty_delivered": "Qty delivered",
        "list_price": "List price",
        "discount": "Discount",
        "unit_price": "Unit price",
        "total_price": "Total",
        "net": "Net",
        "packing": "Packing and transport",
        "vat": "VAT",
        "rounding": "Rounding",
        "total_incl_vat": "Total incl. VAT",
        "subtotal_excl_vat": "Subtotal excl. VAT",
        "terms_heading": "Payment terms and default",
        "payment": "Payment",
        "payment_reference": "Payment reference",
        "dispatch": "Dispatch",
        "page": "Page",
        "of": "of",
    },
    "de": {
        "quotation": "Offerte",
        "order_confirmation": "Auftragsbestätigung",
        "delivery_note": "Lieferschein",
        "invoice": "Rechnung",
        "document_no": "Dokument Nr.",
        "date": "Datum",
        "valid_until": "Gültig bis",
        "expected_delivery": "Voraussichtliche Lieferung",
        "due_date": "Fällig am",
        "payment_terms": "Zahlungsziel",
        "days_net": "Tage netto",
        "customer_po": "Kundenbestellung",
        "carrier": "Spediteur",
        "tracking": "Sendungs Nr.",
        "from": "Von",
        "bill_to": "Rechnung an",
        "deliver_to": "Lieferung an",
        "item": "Artikel",
        "description": "Bezeichnung",
        "qty": "Menge",
        "qty_delivered": "Gelieferte Menge",
        "list_price": "Listenpreis",
        "discount": "Rabatt",
        "unit_price": "Einzelpreis",
        "total_price": "Total",
        "net": "Netto",
        "packing": "Verpackung und Transport",
        "vat": "MwSt",
        "rounding": "Rundung",
        "total_incl_vat": "Total inkl. MwSt",
        "subtotal_excl_vat": "Zwischentotal exkl. MwSt",
        "terms_heading": "Zahlungsbedingungen und Verzug",
        "payment": "Zahlung",
        "payment_reference": "Zahlungsreferenz",
        "dispatch": "Versand",
        "page": "Seite",
        "of": "von",
    },
}


class PayloadError(ValueError):
    pass


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def dec(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayloadError(f"{field} must be numeric") from exc


def cents(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def money(value) -> str:
    amount = cents(dec(value, "money"))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole, fraction = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", "'")
    return f"{sign}{grouped}.{fraction}"


def quantity(value) -> str:
    amount = dec(value, "quantity")
    if amount == amount.to_integral_value():
        return str(int(amount))
    return format(amount.normalize(), "f")


def percentage(value) -> str:
    amount = dec(value, "percentage")
    rendered = format(amount.normalize(), "f")
    return f"{rendered}%"


def data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


LOGO = data_uri(
    ND / "shared" / "signature" / "assets" / "numaco_wordmark_white.png"
)


def required_text(payload: dict, key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise PayloadError(f"{key} is required")
    return value


def address_lines(value, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(str(v).strip() for v in value):
        raise PayloadError(f"{field} must be a nonempty list of address lines")
    return [str(v).strip() for v in value]


def assert_close(actual: Decimal, expected: Decimal, field: str) -> None:
    if abs(cents(actual) - cents(expected)) > TOLERANCE:
        raise PayloadError(
            f"{field} does not reconcile: {cents(actual)} versus {cents(expected)}"
        )


def validate(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise PayloadError("payload must be a JSON object")

    kind = required_text(payload, "document_type")
    if kind not in VALID_KINDS:
        raise PayloadError(f"document_type must be one of {sorted(VALID_KINDS)}")
    language = str(payload.get("language", "en")).lower()
    if language not in VALID_LANGUAGES:
        raise PayloadError("language must be en or de")
    payload["language"] = language

    required_text(payload, "document_number")
    required_text(payload, "issue_date")
    currency = str(payload.get("currency", "CHF")).strip().upper()
    if currency != "CHF":
        raise PayloadError("the locked template currently supports CHF only")
    payload["currency"] = currency

    customer = payload.get("customer")
    if not isinstance(customer, dict):
        raise PayloadError("customer is required")
    required_text(customer, "name")
    address_lines(customer.get("address"), "customer.address")
    references = customer.get("references", [])
    if references is not None and (
        not isinstance(references, list) or not all(str(v).strip() for v in references)
    ):
        raise PayloadError("customer.references must be a list of text lines")

    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise PayloadError("lines must contain at least one line item")

    line_total = Decimal("0")
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise PayloadError(f"lines[{index}] must be an object")
        required_text(line, "position")
        required_text(line, "description")
        qty = dec(line.get("quantity"), f"lines[{index}].quantity")
        if qty <= 0:
            raise PayloadError(f"lines[{index}].quantity must be greater than zero")

        if kind == "delivery_note":
            forbidden = {"list_price", "discount_percent", "unit_price", "total_price"}
            present = sorted(key for key in forbidden if line.get(key) is not None)
            if present:
                raise PayloadError(
                    f"delivery note lines must not expose prices: {', '.join(present)}"
                )
            continue

        unit = dec(line.get("unit_price"), f"lines[{index}].unit_price")
        computed_total = cents(qty * unit)
        if line.get("total_price") is None:
            line["total_price"] = str(computed_total)
        else:
            assert_close(
                dec(line["total_price"], f"lines[{index}].total_price"),
                computed_total,
                f"lines[{index}].total_price",
            )
        line_total += computed_total

        if kind == "quotation":
            list_price = dec(line.get("list_price"), f"lines[{index}].list_price")
            discount = dec(
                line.get("discount_percent"), f"lines[{index}].discount_percent"
            )
            if discount < 0 or discount > 100:
                raise PayloadError(
                    f"lines[{index}].discount_percent must be between zero and 100"
                )
            expected_unit = cents(list_price * (Decimal("1") - discount / Decimal("100")))
            assert_close(unit, expected_unit, f"lines[{index}].unit_price after discount")

    totals = payload.get("totals")
    if kind in {"order_confirmation", "invoice"} and not isinstance(totals, dict):
        raise PayloadError(f"totals are required for {kind}")
    if isinstance(totals, dict):
        net = dec(totals.get("net"), "totals.net")
        assert_close(net, line_total, "totals.net")
        packing = dec(totals.get("packing_transport", 0), "totals.packing_transport")
        vat = dec(totals.get("vat_amount", 0), "totals.vat_amount")
        rounding = dec(totals.get("rounding", 0), "totals.rounding")
        expected_grand = cents(net + packing + vat + rounding)
        if totals.get("grand_total") is None:
            totals["grand_total"] = str(expected_grand)
        else:
            assert_close(
                dec(totals["grand_total"], "totals.grand_total"),
                expected_grand,
                "totals.grand_total",
            )

        if totals.get("vat_rate_percent") is not None:
            rate = dec(totals["vat_rate_percent"], "totals.vat_rate_percent")
            expected_vat = cents((net + packing) * rate / Decimal("100"))
            assert_close(vat, expected_vat, "totals.vat_amount")

    if kind == "quotation" and not payload.get("valid_until"):
        raise PayloadError("valid_until is required for quotations")
    if kind == "invoice" and not payload.get("due_date"):
        raise PayloadError("due_date is required for invoices")

    return payload


def labels(payload: dict) -> dict:
    return TEXT[payload["language"]]


def issuer(payload: dict) -> dict:
    supplied = payload.get("issuer") or {}
    merged = dict(NUMACO)
    if not isinstance(supplied, dict):
        raise PayloadError("issuer must be an object")
    for key in merged:
        if supplied.get(key) not in (None, "", []):
            merged[key] = supplied[key]
    merged["address"] = address_lines(merged["address"], "issuer.address")
    return merged


def meta_cells(payload: dict) -> list[tuple[str, str]]:
    t = labels(payload)
    kind = payload["document_type"]
    cells = [
        (t["document_no"], payload["document_number"]),
        (t["date"], payload["issue_date"]),
    ]
    if kind == "quotation":
        cells.append((t["valid_until"], payload["valid_until"]))
    elif kind == "invoice":
        cells.append((t["due_date"], payload["due_date"]))
    elif kind == "order_confirmation" and payload.get("expected_delivery"):
        cells.append((t["expected_delivery"], payload["expected_delivery"]))
    elif kind == "delivery_note" and payload.get("carrier"):
        cells.append((t["carrier"], payload["carrier"]))

    if payload.get("customer_po"):
        cells.append((t["customer_po"], payload["customer_po"]))
    elif kind != "delivery_note":
        days = int(dec(payload.get("payment_terms_days", 30), "payment_terms_days"))
        cells.append((t["payment_terms"], f"{days} {t['days_net']}"))
    elif payload.get("tracking"):
        cells.append((t["tracking"], payload["tracking"]))
    return cells[:4]


def render_header(payload: dict) -> str:
    t = labels(payload)
    kind = payload["document_type"]
    title = t[kind]
    meta = "".join(
        f'<div class="meta-cell"><div class="meta-key">{esc(key)}</div>'
        f'<div class="meta-value">{esc(value)}</div></div>'
        for key, value in meta_cells(payload)
    )
    return f"""
<header class="trade-banner">
  <img class="trade-logo" src="{LOGO}" alt="Numaco">
  <div class="trade-eyebrow"><span></span>{esc(title.upper())}&nbsp;&nbsp;&middot;&nbsp;&nbsp;{esc(payload['document_number'])}</div>
  <h1>{esc(title)}</h1>
</header>
<div class="meta-grid">{meta}</div>
"""


def party_card(role: str, name: str, address: list[str], tail: list[str], shaded=False) -> str:
    lines = "<br>".join(esc(v) for v in address + tail)
    cls = "party-card shaded" if shaded else "party-card"
    return (
        f'<div class="{cls}"><div class="party-role">{esc(role)}</div>'
        f'<div class="party-name">{esc(name)}</div><div class="party-lines">{lines}</div></div>'
    )


def render_parties(payload: dict) -> str:
    t = labels(payload)
    company = issuer(payload)
    customer = payload["customer"]
    issuer_tail = [f"VAT {company['vat']}"]
    left = party_card(t["from"], company["name"], company["address"], issuer_tail)

    if payload["document_type"] == "delivery_note" and payload.get("ship_to"):
        ship_to = payload["ship_to"]
        if not isinstance(ship_to, dict):
            raise PayloadError("ship_to must be an object")
        role = t["deliver_to"]
        right = party_card(
            role,
            required_text(ship_to, "name"),
            address_lines(ship_to.get("address"), "ship_to.address"),
            [str(v) for v in ship_to.get("references", [])],
            shaded=True,
        )
    else:
        right = party_card(
            t["bill_to"],
            customer["name"],
            customer["address"],
            [str(v) for v in customer.get("references", [])],
            shaded=True,
        )
    return f'<section class="party-grid">{left}{right}</section>'


def cell(value, cls="") -> str:
    attr = f' class="{cls}"' if cls else ""
    return f"<td{attr}>{esc(value)}</td>"


def render_table(payload: dict) -> str:
    t = labels(payload)
    kind = payload["document_type"]
    currency = payload["currency"]

    if kind == "quotation":
        headers = [
            "#",
            t["item"],
            t["description"],
            t["qty"],
            f"{t['list_price']} {currency}",
            t["discount"],
            f"{t['unit_price']} {currency}",
            f"{t['total_price']} {currency}",
        ]
        classes = ["center", "", "", "num", "num", "num", "num", "num"]
        table_class = "quotation-table"
    elif kind == "delivery_note":
        headers = ["#", t["item"], t["description"], t["qty_delivered"]]
        classes = ["center", "", "", "num"]
        table_class = "delivery-table"
    else:
        headers = [
            "#",
            t["item"],
            t["description"],
            t["qty"],
            f"{t['unit_price']} {currency}",
            f"{t['net']} {currency}",
        ]
        classes = ["center", "", "", "num", "num", "num"]
        table_class = "priced-table"

    head = "".join(
        f'<th class="{classes[index]}">{esc(label)}</th>'
        for index, label in enumerate(headers)
    )
    rows = []
    for line in payload["lines"]:
        values = [
            str(line["position"]),
            str(line.get("item", "")),
            str(line["description"]),
            quantity(line["quantity"]),
        ]
        if kind == "quotation":
            values.extend(
                [
                    money(line["list_price"]),
                    percentage(line["discount_percent"]),
                    money(line["unit_price"]),
                    money(line["total_price"]),
                ]
            )
        elif kind != "delivery_note":
            values.extend([money(line["unit_price"]), money(line["total_price"])])
        rows.append(
            "<tr>"
            + "".join(cell(value, classes[index]) for index, value in enumerate(values))
            + "</tr>"
        )

    return (
        f'<table class="trade-table {table_class}"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def render_totals(payload: dict) -> str:
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        return ""
    t = labels(payload)
    currency = payload["currency"]
    rows = [(t["net"], totals["net"])]
    packing = dec(totals.get("packing_transport", 0), "totals.packing_transport")
    if packing:
        rows.append((t["packing"], packing))
    vat = dec(totals.get("vat_amount", 0), "totals.vat_amount")
    if totals.get("vat_rate_percent") is not None or vat:
        vat_label = t["vat"]
        if totals.get("vat_rate_percent") is not None:
            vat_label += f" ({percentage(totals['vat_rate_percent'])})"
        rows.append((vat_label, vat))
    rounding = dec(totals.get("rounding", 0), "totals.rounding")
    if rounding:
        rows.append((t["rounding"], rounding))

    detail = "".join(
        f'<div class="total-row"><span>{esc(label)}</span><strong>{esc(currency)} {money(value)}</strong></div>'
        for label, value in rows
    )
    grand_label = (
        t["total_incl_vat"]
        if payload["document_type"] == "invoice"
        else t["subtotal_excl_vat"]
    )
    return f"""
<section class="totals-wrap">
  <div class="totals-detail">{detail}</div>
  <div class="grand-total"><span>{esc(grand_label.upper())} {esc(currency)}</span><strong>{money(totals['grand_total'])}</strong></div>
</section>
"""


def terms_text(payload: dict) -> str:
    days = int(dec(payload.get("payment_terms_days", 30), "payment_terms_days"))
    if payload["language"] == "de":
        return (
            f"Unsere Rechnungen sind innert {days} Tagen ab Rechnungsdatum rein netto und ohne Abzug zahlbar. "
            "Diese Zahlungsfrist gilt als Verfalltag im Sinne von Art. 102 Abs. 2 OR. Nach unbenutztem Ablauf der Frist gerät der Kunde ohne weitere Mahnung in Verzug. "
            "Ab Verzugsbeginn wird ein Verzugszins von 5% pro Jahr gemäss Art. 104 Abs. 1 OR geschuldet. Die Geltendmachung eines weitergehenden Verzugsschadens gemäss Art. 106 OR bleibt vorbehalten. "
            "Mit Erteilung der Bestellung wird der Auftrag verbindlich und kann nicht mehr storniert werden. Bereits angefallene Kosten werden bei einer verlangten Stornierung in Rechnung gestellt."
        )
    return (
        f"Our invoices are payable strictly net, without any deduction, within {days} days of the invoice date. "
        "This payment period constitutes a fixed due date within the meaning of Art. 102 para. 2 of the Swiss Code of Obligations. Upon expiry, the customer is automatically in default without any reminder. "
        "From the onset of default, default interest of 5% per annum is owed pursuant to Art. 104 para. 1 CO. The right to claim further damages caused by default under Art. 106 CO is reserved. "
        "Once the customer has issued the purchase order, the order is binding and can no longer be cancelled. Costs already incurred are charged if cancellation is nevertheless requested."
    )


def render_terms(payload: dict) -> str:
    if payload["document_type"] == "delivery_note":
        return ""
    t = labels(payload)
    return f"""
<section class="terms-block">
  <h2>{esc(t['terms_heading'].upper())}</h2>
  <p>{esc(terms_text(payload))}</p>
</section>
"""


def render_dispatch(payload: dict) -> str:
    if payload["document_type"] != "delivery_note":
        return ""
    t = labels(payload)
    details = []
    if payload.get("carrier"):
        details.append(f"{t['carrier']}: {payload['carrier']}")
    if payload.get("tracking"):
        details.append(f"{t['tracking']}: {payload['tracking']}")
    if not details:
        return ""
    return (
        f'<section class="dispatch-block"><h2>{esc(t["dispatch"].upper())}</h2>'
        f'<p>{esc(". ".join(details))}</p></section>'
    )


def render_payment(payload: dict) -> str:
    if payload["document_type"] != "invoice":
        return ""
    t = labels(payload)
    company = issuer(payload)
    return f"""
<section class="payment-block">
  <h2>{esc(t['payment'].upper())}</h2>
  <p><strong>{esc(company['bank_name'])}</strong>, {esc(company['bank_address'])}<br>
  IBAN {esc(company['iban'])} &middot; SWIFT {esc(company['swift'])}<br>
  {esc(t['payment_reference'])}: {esc(payload['document_number'])}</p>
</section>
"""


TRADING_CSS = r"""
@page{
  size:A4; margin:20mm 17mm 16mm 17mm; background:none;
  @bottom-left{
    content:"__FOOTER__"; font-family:'JetBrains Mono',monospace; font-size:6pt;
    letter-spacing:.055em; color:#8a93a3;
  }
}
@page:first{
  margin:12mm 17mm 16mm 17mm; background:none;
  @top-left{content:none} @top-right{content:none}
  @bottom-left{
    content:"__FOOTER__"; font-family:'JetBrains Mono',monospace; font-size:6pt;
    letter-spacing:.055em; color:#8a93a3;
  }
  @bottom-right{
    content:"Page " counter(page) " of " counter(pages);
    font-family:'JetBrains Mono',monospace; font-size:6.2pt; letter-spacing:.04em; color:#8a93a3;
  }
}

body{ font-size:9.2pt; line-height:1.42; color:var(--body); }
.trade-doc{ width:100%; }

.trade-banner{ position:relative; height:32mm; padding:6.4mm 7.5mm; border-radius:1mm;
  background:var(--navy); color:#fff; break-inside:avoid; }
.trade-logo{ width:34mm; height:auto; display:block; margin-bottom:3mm; }
.trade-eyebrow{ display:flex; align-items:center; font-family:var(--font-mono); font-size:5.9pt;
  letter-spacing:.11em; color:var(--amber); }
.trade-eyebrow span{ width:2mm; height:2mm; margin-right:2.4mm; border-radius:50%; background:var(--amber); }
.trade-banner h1{ position:absolute; left:7.5mm; right:7.5mm; bottom:4.5mm; margin:0;
  font-family:var(--font-sans); font-size:16.5pt; line-height:1; font-weight:800; color:#fff; }

.meta-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:6mm; padding:4.2mm 0 4.5mm;
  break-inside:avoid; }
.meta-key{ font-family:var(--font-mono); font-size:5.5pt; letter-spacing:.09em;
  text-transform:uppercase; color:var(--grey2); margin-bottom:.7mm; }
.meta-value{ color:var(--ink); font-weight:700; font-size:8.4pt; line-height:1.2; }

.party-grid{ display:grid; grid-template-columns:1fr 1fr; border:.25mm solid var(--hair);
  margin-bottom:7mm; break-inside:avoid; }
.party-card{ min-height:42mm; padding:5.5mm 6mm; }
.party-card + .party-card{ border-left:.25mm solid var(--hair); }
.party-card.shaded{ background:#f7f9fc; }
.party-role{ font-family:var(--font-mono); font-size:5.5pt; letter-spacing:.11em;
  text-transform:uppercase; color:var(--amber); margin-bottom:4mm; }
.party-name{ font-size:11.4pt; font-weight:800; color:var(--ink); margin-bottom:3mm; }
.party-lines{ font-family:var(--font-mono); font-size:6.8pt; line-height:1.43; color:var(--grey); }

.trade-table{ width:100%; border-collapse:collapse; table-layout:fixed; margin-top:0;
  font-variant-numeric:tabular-nums; }
.trade-table thead{ display:table-header-group; break-after:avoid; }
.trade-table th{ padding:0 1.5mm 2.3mm; border-bottom:.45mm solid var(--navy);
  font-family:var(--font-mono); font-size:5.3pt; font-weight:500; letter-spacing:.07em;
  text-transform:uppercase; color:var(--grey2); text-align:left; vertical-align:middle; }
.trade-table td{ padding:2.8mm 1.5mm; border-bottom:.22mm solid var(--hair2);
  font-size:8.1pt; line-height:1.35; vertical-align:middle; color:var(--body); overflow-wrap:anywhere; }
.trade-table tbody tr:nth-child(even) td{ background:var(--zebra); }
.trade-table td:nth-child(2){ font-family:var(--font-mono); font-size:7.2pt; color:var(--grey); }
.trade-table .num{ text-align:right; font-family:var(--font-mono); white-space:nowrap; }
.trade-table .center{ text-align:center; font-family:var(--font-mono); }

.quotation-table col{}
.quotation-table th:nth-child(1),.quotation-table td:nth-child(1){width:5%}
.quotation-table th:nth-child(2),.quotation-table td:nth-child(2){width:16%}
.quotation-table th:nth-child(3),.quotation-table td:nth-child(3){width:26%}
.quotation-table th:nth-child(4),.quotation-table td:nth-child(4){width:6%}
.quotation-table th:nth-child(5),.quotation-table td:nth-child(5){width:12%}
.quotation-table th:nth-child(6),.quotation-table td:nth-child(6){width:9%}
.quotation-table th:nth-child(7),.quotation-table td:nth-child(7){width:13%}
.quotation-table th:nth-child(8),.quotation-table td:nth-child(8){width:13%}

.priced-table th:nth-child(1),.priced-table td:nth-child(1){width:6%}
.priced-table th:nth-child(2),.priced-table td:nth-child(2){width:18%}
.priced-table th:nth-child(3),.priced-table td:nth-child(3){width:43%}
.priced-table th:nth-child(4),.priced-table td:nth-child(4){width:8%}
.priced-table th:nth-child(5),.priced-table td:nth-child(5){width:12.5%}
.priced-table th:nth-child(6),.priced-table td:nth-child(6){width:12.5%}

.delivery-table th:nth-child(1),.delivery-table td:nth-child(1){width:7%}
.delivery-table th:nth-child(2),.delivery-table td:nth-child(2){width:23%}
.delivery-table th:nth-child(3),.delivery-table td:nth-child(3){width:56%}
.delivery-table th:nth-child(4),.delivery-table td:nth-child(4){width:14%}

.totals-wrap{ width:94mm; margin:4.5mm 0 0 auto; break-inside:avoid; }
.totals-detail{ padding-left:5mm; }
.total-row{ display:grid; grid-template-columns:1fr 34mm; align-items:center; gap:5mm;
  padding:1mm 0; font-family:var(--font-mono); }
.total-row span{ font-size:5.8pt; letter-spacing:.08em; text-transform:uppercase; color:var(--grey); }
.total-row strong{ text-align:right; color:var(--ink); font-size:7.8pt; font-weight:500; }
.grand-total{ display:grid; grid-template-columns:1fr 30mm; align-items:center; gap:5mm;
  margin-top:2.4mm; padding:3.2mm 4mm 5mm; border-top:.5mm solid var(--navy);
  background:linear-gradient(var(--amber),var(--amber)) 4mm calc(100% - 2mm) / calc(100% - 8mm) .7mm no-repeat, var(--tint-total); }
.grand-total span{ font-family:var(--font-mono); font-size:5.7pt; letter-spacing:.07em;
  color:var(--navy); font-weight:600; }
.grand-total strong{ text-align:right; color:var(--navy); font-size:12.5pt; line-height:1;
  font-weight:800; font-variant-numeric:tabular-nums; }

.terms-block{ margin-top:6mm; padding-top:4mm; border-top:.4mm solid var(--navy); }
.terms-block h2,.dispatch-block h2,.payment-block h2{ margin:0 0 2mm; font-family:var(--font-mono);
  font-size:5.8pt; letter-spacing:.1em; color:var(--grey); font-weight:500; }
.terms-block p{ margin:0; font-size:6.35pt; line-height:1.38; color:var(--grey); }

.dispatch-block{ margin-top:5mm; padding:4mm 5mm; border-left:.6mm solid var(--amber);
  background:#fbfaf6; break-inside:avoid; }
.dispatch-block h2{ color:var(--amber); }
.dispatch-block p{ margin:0; font-size:8pt; color:var(--grey); }

.payment-block{ margin-top:5mm; padding:4mm 5mm; border-radius:1mm; background:var(--navy);
  color:#fff; break-inside:avoid; }
.payment-block h2{ color:var(--amber); }
.payment-block p{ margin:0; font-size:8pt; line-height:1.35; color:#fff; }
"""


def build_html(payload: dict) -> tuple[str, str, str]:
    payload = validate(payload)
    t = labels(payload)
    title = f"{t[payload['document_type']]} {payload['document_number']}"
    body = (
        '<main class="trade-doc">'
        + render_header(payload)
        + render_parties(payload)
        + render_table(payload)
        + render_totals(payload)
        + render_dispatch(payload)
        + render_terms(payload)
        + render_payment(payload)
        + "</main>"
    )
    return title, t[payload["document_type"]], body


def trading_css(payload: dict) -> str:
    company = issuer(payload)
    footer_text = f"{company['name'].upper()}  ·  {company['vat']}  ·  {company['iban']}"
    footer_text = footer_text.replace("\\", "\\\\").replace('"', '\\"')
    return TRADING_CSS.replace("__FOOTER__", footer_text)


def render(payload: dict, pdf_path: Path) -> tuple[str, int]:
    title, kind_label, body = build_html(payload)
    pdf_path = Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    engine, pages = S.render_pdf(
        title,
        body,
        str(pdf_path),
        None,
        None,
        extra_css=trading_css(payload),
        watermark_opacity=0.06,
    )
    check_pages = ",".join(str(n) for n in range(1, pages + 1)) if pages <= 4 else f"1,2,{pages}"
    S.R.pdfcheck(str(pdf_path), pdf_path.stem, pages=check_pages)
    return engine, pages


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Usage: build_trading_document.py <payload.json> <output.pdf>")
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        engine, pages = render(payload, target)
    except (OSError, json.JSONDecodeError, PayloadError) as exc:
        sys.exit(f"trading document error: {exc}")
    print(f"rendered -> {target.resolve()} (engine {engine}, {pages} pages)")
    print(f"wrote {target.resolve().with_suffix('.html')}")


if __name__ == "__main__":
    main()
