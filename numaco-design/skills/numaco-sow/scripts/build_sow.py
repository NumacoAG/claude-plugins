#!/usr/bin/env python3
"""Render a Numaco Statement of Work as a branded PDF from a JSON payload.

Presentation is the LOCKED Numaco Signature design, driven entirely by the shared
module at shared/signature/signature.py: a navy full-bleed cover, a sober light
interior (brand navy plus one amber accent), Manrope for display/body and
JetBrains Mono for reference codes, a faint corner watermark and a running
header/footer. The two-pass render (which bakes the true page count into the
footer) and the CoreGraphics fidelity check both live in that module; this file
only turns the SOW payload into the module's helper calls. Fully self-contained
and offline. The final deliverable is the PDF.

Usage:
    python3 build_sow.py payload.json output.pdf
    cat payload.json | python3 build_sow.py - output.pdf

Payload schema (unchanged contract):

{
  "sow_number":        "261130",
  "issue_date":        "April 2026",
  "project_title":     "Label management migration advisory",
  "client_legal_name": "Acme Labs AG",
  "client_address":    ["Industriestrasse 12", "CH-8600 Duebendorf", "Switzerland"],
  "client_contacts":   [{"name": "Petra Meier", "email": "petra.meier@acmelabs.ch", "role": "Head of IT"}],
  "context":           "Paragraph 1.\n\nParagraph 2.",
  "deliverables":      [{"summary": "short label", "body": "full sentence."}, "plain string works too"],
  "exclusions":        [{"summary": "short label", "body": "full sentence."}],
  "assumptions":       [{"summary": "short label", "body": "full sentence."}],
  "workstreams":       [{"name": "Scope and analysis", "days": 3.0}, ...],
  "day_rate_chf":      1000,
  "payment_days":      60,
  "optional_addons":   [                                  // optional; omit or []
    {"number": 2, "title": "CSV schema validation", "days": 1.0, "body": "..."}
  ],
  "day_rate_narrative":     "...",   // optional override (e.g. list rate then discount)
  "total_amount_narrative": "...",   // optional override
  "output_path":            "/absolute/path/to/final.pdf"  // optional; else argv[2]
}
"""
import html
import json
import os
import re
import sys
from pathlib import Path

# --- locate the shared renderer + signature module ---
SKILL_DIR = Path(__file__).resolve().parents[1]          # .../skills/numaco-sow
ND = Path(__file__).resolve().parents[3]                 # .../numaco-design
sys.path.insert(0, str(ND / "shared" / "render"))
sys.path.insert(0, str(ND / "shared" / "signature"))
import numaco_render as R  # noqa: E402  (kept so tools can reach build_sow.R.*)
import signature as S      # noqa: E402  (the LOCKED Numaco Signature design)

REFERENCES = SKILL_DIR / "references"

# ---- Numaco company constants (do not change without the user's explicit approval) ----
NUMACO_ADDRESS = ["Haldenstrasse 3c", "CH-8905 Islisberg", "Switzerland"]
NUMACO_VAT = "CHE-107.980.861 MWST"
NUMACO_CONTACTS = [
    {"name": "Finance contact", "role": "Engagement lead",
     "email": "finance@numaco.ch"},
    {"name": "Your Name", "role": "Solution architect",
     "email": "you@numaco.ch"},
]

# ---- Verbatim boilerplate (preserve exactly; commercial + activation + separator) ----
ADDON_SEP_LABEL = ("Optional add-ons (priced separately, not included in the "
                   "total below)")

ADDON_SCOPE_NOTE = (
    "The items below are not part of the base engagement. Each is priced "
    "separately in the effort estimate; any combination can be added at the "
    "client's discretion before or during the engagement, via a PO amendment "
    "referencing this SOW."
)

COMMERCIAL_INTRO = (
    "The work provided under this SOW is based on time and material. Numaco "
    "charges only labor effectively accomplished, not the full amount in the "
    "estimation. Numaco will inform the client as soon as possible if there "
    "is a risk that the estimated costs are exceeded. It is then the client's "
    "responsibility to decide whether (a) further work hours under this SOW "
    "can be done, (b) a new SOW must be signed, or (c) this SOW will be "
    "terminated without further action."
)


# ---------- helpers ----------
def esc(text):
    """Escape for HTML body context (quotes left intact for readable apostrophes)."""
    return html.escape(str(text), quote=False)


def _days(d):
    """%g day formatting: 3, 1.5, 0.25 ."""
    return f"{float(d):g}"


def _pair(item):
    """A scope item is a plain string or {summary, body}; return (title, body)."""
    if isinstance(item, dict):
        return (item.get("summary") or "").strip(), (item.get("body") or "").strip()
    return str(item).strip(), ""


def _multi(text):
    """Escape a text block and join its blank-line paragraphs with breaks."""
    paras = [esc(p.strip()) for p in str(text or "").split("\n\n") if p.strip()]
    return "<br><br>".join(paras)


def _client_city(data):
    """The address line that reads as a postcode+city (for the cover meta band)."""
    addr = data.get("client_address", [])
    for line in addr:
        if re.search(r"\d{3,}", str(line)):
            return esc(line)
    if len(addr) > 1:
        return esc(addr[1])
    return esc(addr[0]) if addr else ""


def _subtitle(data):
    """A one-line subtitle: the first sentence of the context, else a fallback."""
    ctx = str(data.get("context") or "").strip()
    if ctx:
        first = ctx.split("\n\n")[0].strip()
        sentence = re.split(r"(?<=[.!?])\s+", first, maxsplit=1)[0].strip()
        if len(sentence) > 200:
            sentence = sentence[:197].rstrip() + "..."
        return esc(sentence)
    return "Statement of work for " + esc(data.get("project_title", "")) + "."


# ---------- section bodies (return HTML strings) ----------
def _context_body(data):
    paras = [p.strip() for p in str(data.get("context") or "").split("\n\n") if p.strip()]
    if not paras:
        return ""
    out = [S.lead(esc(paras[0]))]
    out += [S.para(esc(p)) for p in paras[1:]]
    return "".join(out)


def _scope_body(data):
    parts = []

    deliverables = data.get("deliverables", [])
    if deliverables:
        rows = []
        for i, item in enumerate(deliverables, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"S{i}", esc(title), esc(body)))
        parts.append(S.subhead("Deliverables") + S.items(*rows))

    exclusions = data.get("exclusions", [])
    if exclusions:
        rows = []
        for i, item in enumerate(exclusions, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"N{i}", esc(title), esc(body), excl=True))
        parts.append(S.subhead("Exclusions") + S.items(*rows))

    assumptions = data.get("assumptions", [])
    if assumptions:
        rows = []
        for i, item in enumerate(assumptions, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"A{i}", esc(title), esc(body)))
        parts.append(S.subhead("Assumptions") + S.items(*rows))

    addons = data.get("optional_addons") or []
    if addons:
        rows = []
        for i, addon in enumerate(addons, 1):
            number = addon.get("number", i)
            rows.append(S.scope_item(
                f"O{number}", esc(addon.get("title", "")),
                _multi(addon.get("body", "")), tag="Priced separately"))
        parts.append(
            S.subhead("Optional add-ons")
            + S.para(esc(ADDON_SCOPE_NOTE))
            + S.items(*rows)
        )

    return "".join(parts)


def _effort_body(data):
    rate = float(data["day_rate_chf"])
    workstreams = data.get("workstreams", [])
    addons = data.get("optional_addons") or []

    rows = []
    base_days = 0.0
    for i, ws in enumerate(workstreams, 1):
        d = float(ws["days"])
        base_days += d
        rows.append([
            (f"W{i}", "ref"), (esc(ws["name"]), "ws"),
            (_days(d), "num"), (S.num(d * rate), "num"),
        ])

    total_row = [
        ("", ""), ("Base engagement total", "ws"),
        (_days(base_days), "num"), (S.num(base_days * rate), "num amt"),
    ]

    addon_rows = None
    if addons:
        addon_rows = [[("", "ref"), (ADDON_SEP_LABEL, "ws"), ("", "num"), ("", "num")]]
        for i, addon in enumerate(addons, 1):
            number = addon.get("number", i)
            d = float(addon.get("days", 0))
            addon_rows.append([
                (f"O{number}", "ref"), (esc(addon.get("title", "")), "ws"),
                (_days(d), "num"), (S.num(d * rate), "num"),
            ])

    footnote = (
        "All effort above is an estimation. Billing is based on time actually "
        "worked, as described in section 4 below."
    )
    if addons:
        footnote += (
            " Add-ons are optional and priced separately; if the client selects "
            "any, its days and amount are added to the total via a PO amendment."
        )

    table = S.effort_table(
        [("Ref", False, "12mm"), ("Workstream", False, None),
         ("Days", True, None), ("Amount CHF", True, None)],
        rows, total_row=total_row, addon_rows=addon_rows, footnote=footnote,
    )
    billing = S.callout(
        "Billing basis",
        "Billing is for time actually worked, not the estimate above. Optional "
        "add-ons are excluded from the base engagement total and are activated by "
        "a purchase order amendment that references this SOW.",
    )
    return table + billing


def _commercial_body(data):
    rate = float(data["day_rate_chf"])
    total_days = sum(float(ws["days"]) for ws in data.get("workstreams", []))
    total_amount = rate * total_days
    payment_days = int(data.get("payment_days", 60))

    day_rate_narrative = data.get("day_rate_narrative") or (
        f"{S.chf(rate)} per working day. A working day means 8 hours performed "
        "during standard working hours, defined as 08:00 to 17:00 CET on Swiss "
        "business days."
    )
    total_amount_narrative = data.get("total_amount_narrative") or (
        f"{S.chf(total_amount)} (excluding Swiss VAT)."
    )

    terms = [
        ("Day rate", day_rate_narrative),
        ("Work outside standard hours",
         "Evenings, weekends, and Swiss bank holidays require a separate written "
         "agreement and are billed at a surcharge to be agreed at the time."),
        ("Travel",
         "Any travel outside Numaco offices or the customer's Switzerland "
         "premises is to be agreed in advance and billed separately."),
        ("Total estimated amount", total_amount_narrative),
        ("Payment",
         f"{payment_days} days net from date of invoice. The invoice for the "
         "total amount is sent at the end of the performance."),
        ("Acceptance",
         "All services are recorded in a timesheet with a detailed description "
         "of the service. The client may inspect the timesheet at any time. At "
         "the end of the performance period Numaco sends the timesheet to the "
         "client for review and approval; once approved, it serves as the basis "
         "for invoicing."),
    ]
    return (
        S.para(esc(COMMERCIAL_INTRO))
        + S.term_list([(k, esc(v)) for k, v in terms])
    )


def _activation_body(data):
    para = (
        f"This SOW is agreed between {data['client_legal_name']} and Numaco AG. "
        "It is valid without formal signatures and comes into operation with a "
        "commercial purchase order that includes a reference to this document."
    )
    return (
        S.para(esc(para))
        + S.signature_block([
            ("For the client", esc(data["client_legal_name"])),
            ("For the supplier", "Numaco AG"),
        ])
    )


def _appendix(data):
    """Parse tcs_body.md into (marker, heading, text) clauses, verbatim."""
    md = (REFERENCES / "tcs_body.md").read_text(encoding="utf-8")
    clauses = []
    cur_marker = None
    cur_heading = None
    buf = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if cur_marker is not None:
                clauses.append((cur_marker, cur_heading, "<br><br>".join(buf)))
            buf = []
            head = line[3:].strip()
            m = re.match(r"^(\d+)\.\s*(.*)$", head)
            if m:
                cur_marker = "&sect;" + m.group(1)
                cur_heading = esc(m.group(2))
            else:
                cur_marker, cur_heading = "&sect;", esc(head)
        elif line.startswith("---"):
            break  # the single --- separates the clauses from the address footer
        elif line.startswith("#"):
            continue
        elif line.startswith("*") and line.endswith("*") and len(line) > 2:
            continue  # the italic "embedded at ~8pt" note in the header
        elif line.strip() and cur_marker is not None:
            buf.append(esc(line.strip()))
    if cur_marker is not None:
        clauses.append((cur_marker, cur_heading, "<br><br>".join(buf)))
    return S.appendix("Terms and Conditions", clauses, tag="Standard terms")


# ---------- assembly ----------
def build_body(data):
    rate = float(data["day_rate_chf"])

    cover = S.cover(
        "Statement of Work",
        esc(data["sow_number"]),
        esc(data["project_title"]),
        _subtitle(data),
        [
            ("Prepared for", esc(data["client_legal_name"]), _client_city(data)),
            ("Prepared by", "Numaco AG", "CH-8905 Islisberg"),
            ("Issued", esc(data["issue_date"]), "Commercial in confidence"),
            ("Reference", esc(data["sow_number"]), "Rev A"),
        ],
        "Numaco AG &middot; CH-8905 Islisberg",
    )

    client = {
        "role": "Client",
        "name": esc(data["client_legal_name"]),
        "address": [esc(line) for line in data.get("client_address", [])],
        "contacts_label": "Key contacts",
        "contacts": [
            {"name": esc(c.get("name", "")),
             "role": esc(c.get("role", "") or ""),
             "email": esc(c.get("email", "") or "")}
            for c in data.get("client_contacts", [])
        ],
    }
    supplier = {
        "role": "Supplier",
        "name": "Numaco AG",
        "address": NUMACO_ADDRESS,
        "contacts_label": "Contacts &middot; VAT " + NUMACO_VAT,
        "contacts": NUMACO_CONTACTS,
    }
    parties = S.block_eyebrow("Contracting parties") + S.parties(client, supplier)

    sec_context = S.section(
        "01", "Context", "BACKGROUND &middot; PROBLEM STATEMENT",
        _context_body(data), first=True)
    sec_scope = S.section(
        "02", "Scope",
        "DELIVERABLES &middot; EXCLUSIONS &middot; ASSUMPTIONS &middot; OPTIONS",
        _scope_body(data))
    sec_effort = S.section(
        "03", "Effort estimate",
        "BASE ENGAGEMENT &middot; DAY RATE " + S.chf(rate),
        _effort_body(data))
    sec_commercial = S.section(
        "04", "Commercial terms", "RATES &middot; INVOICING &middot; VALIDITY",
        _commercial_body(data))
    sec_activation = S.section(
        "05", "Activation", "AGREEMENT &middot; PURCHASE ORDER",
        _activation_body(data))
    apx = _appendix(data)

    # Disable ligatures so the literal "(c)" in the commercial boilerplate is not
    # rendered as a copyright glyph by Manrope.
    ligature_off = (
        '<style>body{font-variant-ligatures:none;'
        'font-feature-settings:"liga" 0,"clig" 0,"dlig" 0,"hlig" 0,"calt" 0;}</style>'
    )

    return ligature_off + cover + S.main_body(
        parties, sec_context, sec_scope, sec_effort,
        sec_commercial, sec_activation, apx,
    )


def render(data, output_path):
    """Render the SOW PDF via the shared signature two-pass renderer.

    Returns (html_path, pdf_path). signature.render_pdf writes the intermediate
    HTML alongside the PDF (same stem, .html), which is what we report back.
    """
    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    body = build_body(data)
    title = f"Numaco SOW {data['sow_number']}"
    S.render_pdf(title, body, output_path, "Statement of Work", data["sow_number"])
    html_path = os.path.splitext(output_path)[0] + ".html"
    return html_path, output_path


# ---------- CLI ----------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    payload_arg = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else ""

    if payload_arg == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(payload_arg).read_text(encoding="utf-8"))

    if not output_path:
        output_path = data.get("output_path")
    if not output_path:
        sys.exit("ERROR: no output path (argv[2] or payload.output_path).")

    html_path, pdf_path = render(data, output_path)
    print(f"Wrote HTML: {html_path}")
    print(f"Wrote PDF:  {pdf_path}")


if __name__ == "__main__":
    main()
