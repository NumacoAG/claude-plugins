#!/usr/bin/env python3
"""Render a Numaco Statement of Work as a branded PDF from a JSON payload.

Presentation uses the shared Signal Stack design on the Numaco Signature
structure: a dark technical cover, centred navy section bands, large readable
body type, strong numbered subsection rules, clear commercial tables, a large
faint corner watermark, and a running header and footer. The two pass render
(which bakes the true page count into the footer) and the CoreGraphics fidelity
check live in the shared modules. This file turns the SOW payload into the
Signature component calls and applies Signal Stack. The result is fully self
contained and offline. The final deliverable is the PDF.

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
  "day_rate_chf":      100,
  "payment_days":      60,
  "optional_addons":   [                                  // optional; omit or []
    {"number": 2, "title": "CSV schema validation", "days": 1.0, "body": "..."}
  ],
  "cover_subtitle":         "...",   // the cover line; write it, do not let it truncate
  "day_rate_narrative":     "...",   // optional override (e.g. list rate then discount)
  "total_amount_narrative": "...",   // optional override
  "output_path":            "/absolute/path/to/final.pdf"  // optional; else argv[2]
}

Every block of prose in sections 4 and 5 is overridable from the payload, so no
wording is trapped in this file. A key that is absent uses the default below; a
key supplied as "" or [] or null renders nothing at all. Prose keys accept a
string (split on blank lines) or a list of paragraphs.

  "commercial_intro":        "..."   // replaces the time-and-material opener
  "commercial_overrun":      "..."   // replaces the stop-at-overrun paragraph
  "extra_commercial_intro":  [...]   // further paragraphs before the term list
  "outside_hours_narrative": "..."   // the "Work outside standard hours" term
  "travel_narrative":        "..."   // the "Travel" term
  "payment_narrative":       "..."   // the "Payment" term
  "acceptance_narrative":    "..."   // the timesheet term's body
  "acceptance_label":        "..."   // its label (default "Acceptance")
  "commercial_terms":        [{"label": ..., "body": ...}, ...]  // replaces ALL terms
  "extra_commercial_terms":  [{"label": ..., "body": ...}, ...]  // appended after
  "activation_narrative":    "..."   // replaces the section 5 paragraph
  "activation_extra":        [...]   // further section 5 paragraphs (e.g. precedence)
  "show_signature_block":    true    // set false to omit it
  "show_option_boxes":       true    // tick-boxes on the signature page, one per
                                     // optional add-on plus a "none" row, so the
                                     // client chooses options where they sign.
                                     // Automatic whenever optional_addons exist;
                                     // set false only to suppress them.
  "addon_scope_note":        "..."   // the note above the optional add-ons
  "addon_separator_label":   "..."   // the merged row in the effort table

The supplier side of the Parties block (the two Numaco contacts) is not part of
the payload: it is read from the per-user defaults file at
$NUMACO_DESIGN_DEFAULTS or ~/.config/numaco-design/defaults.toml (template:
defaults.toml.example in the plugin root). If no defaults file exists, the
placeholder contacts below are used. Rates are never read from that file at
render time; the payload stays fully explicit.
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
import signature as S      # noqa: E402  (shared structure and components)

REFERENCES = SKILL_DIR / "references"
SOW_CSS = (
    ND / "shared" / "signal-stack" / "signal-stack.css"
).read_text()
SOW_WATERMARK_OPACITY = 0.085

# ---- Numaco company constants (do not change without the user's explicit approval) ----
# Address and VAT are true company constants, identical for every colleague, so
# they stay hardcoded here.
NUMACO_ADDRESS = ["Haldenstrasse 3c", "CH-8905 Islisberg"]
NUMACO_VAT = "CHE-107.980.861 MWST"

# Placeholder supplier contacts, used only when no per-user defaults file
# exists. Real contacts come from the user's local defaults.toml (see below).
PLACEHOLDER_CONTACTS = [
    {"name": "Finance contact", "role": "Engagement lead",
     "email": "finance@numaco.ch"},
    {"name": "Your Name", "role": "Solution architect",
     "email": "you@numaco.ch"},
]


def _load_defaults():
    """Read the per-user defaults TOML, or return {} when unavailable.

    The path is $NUMACO_DESIGN_DEFAULTS if set, else
    ~/.config/numaco-design/defaults.toml. The file is personal machine-local
    config (the user's rate card and contact block); it is never part of the
    plugin or any repo. A missing file, an unreadable or invalid file, or a
    Python without tomllib all silently fall back to {}.
    """
    try:
        import tomllib
        path = os.environ.get("NUMACO_DESIGN_DEFAULTS") or os.path.join(
            os.path.expanduser("~"), ".config", "numaco-design", "defaults.toml")
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def _supplier_contacts():
    """Contacts for the SOW Parties block: user defaults, else placeholders.

    Only entries carrying both a name and an email are accepted. Note this is
    contacts only: rates are never injected from the defaults file at render
    time (the payload stays fully explicit; the rate flows through the skill
    conversation).
    """
    contacts = []
    try:
        raw = _load_defaults().get("sow", {}).get("contacts", [])
        for c in raw:
            if isinstance(c, dict) and c.get("name") and c.get("email"):
                contacts.append({
                    "name": html.escape(str(c["name"]), quote=False),
                    "role": html.escape(str(c.get("role", "") or ""), quote=False),
                    "email": html.escape(str(c["email"]), quote=False),
                })
    except Exception:
        contacts = []
    return contacts or PLACEHOLDER_CONTACTS


NUMACO_CONTACTS = _supplier_contacts()

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

COMMERCIAL_OVERRUN = (
    "Should Numaco establish that the estimated effort will be exceeded, "
    "Numaco will provide the client with a written report stating the "
    "overrun, the reasons for it and the effort still required to complete "
    "the work, and will suspend further work until the client has decided "
    "how to proceed, either by taking the remaining work over or by agreeing "
    "a new SOW. Numaco does not continue billable work beyond the estimate "
    "without that decision."
)

OUTSIDE_HOURS_NARRATIVE = (
    "Evenings, weekends, and Swiss bank holidays require a separate written "
    "agreement and are billed at a surcharge to be agreed at the time."
)

TRAVEL_NARRATIVE = (
    "Any travel outside Numaco offices or the customer's Switzerland "
    "premises is to be agreed in advance and billed separately."
)

ACCEPTANCE_NARRATIVE = (
    "All services are recorded in a timesheet with a detailed description "
    "of the service. The client may inspect the timesheet at any time. At "
    "the end of the performance period Numaco sends the timesheet to the "
    "client for review and approval; once approved, it serves as the basis "
    "for invoicing."
)



# ---------------------------------------------------------------------------
# Language packs. Every English word this engine emits lives here, so a German
# document is a payload switch rather than a fork. `language` selects the pack;
# any individual string stays overridable from the payload as before.
# ---------------------------------------------------------------------------
LABELS = {
    "en": {
        "doc_kind": "Statement of Work", "confidential": "Confidential",
        "page_word": "Page", "of_word": "of",
        "prepared_for": "Prepared for", "prepared_by": "Prepared by",
        "issued": "Issued", "reference": "Reference",
        "in_confidence": "Commercial in confidence", "rev": "Rev A",
        "parties_eyebrow": "Contracting parties", "client": "Client",
        "supplier": "Supplier", "key_contacts": "Key contacts",
        "contacts_vat": "Contacts &middot; ",
        "apx_title": "Terms and Conditions", "apx_tag": "Standard terms",
        "sec_context": "Context", "tag_context": "BACKGROUND &middot; PROBLEM STATEMENT",
        "sec_scope": "Scope",
        "tag_scope": "DELIVERABLES &middot; EXCLUSIONS &middot; ASSUMPTIONS &middot; OPTIONS",
        "sec_effort": "Effort estimate", "tag_effort": "BASE ENGAGEMENT &middot; DAY RATE ",
        "sec_commercial": "Commercial terms",
        "tag_commercial": "RATES &middot; INVOICING &middot; VALIDITY",
        "sec_activation": "Activation", "tag_activation": "AGREEMENT &middot; PURCHASE ORDER",
        "deliver": "Deliverables", "not_deliver": "Exclusions",
        "assumptions": "Assumptions", "addons": "Optional add-ons",
        "priced_separately": "Priced separately",
        "col_ref": "Ref", "col_workstream": "Workstream", "col_days": "Days",
        "col_amount": "Amount CHF", "total": "Base engagement total",
        "billing_basis": "Billing basis",
        "for_client": "For the client", "for_supplier": "For the supplier",
        "term_day_rate": "Day rate", "term_outside": "Work outside standard hours",
        "term_travel": "Travel", "term_total": "Total estimated amount",
        "term_payment": "Payment", "term_acceptance": "Acceptance",
        "opt_select_label": "Optional add-ons selected",
        "opt_select_note": ("Tick any optional add-on the client wishes to activate, then return this page with "
                            "the purchase order. Ticked items are added to the total at the rates in section 3. "
                            "Leaving every box empty orders the base engagement only."),
        "opt_none": "None, base engagement only",
        "opt_meta": "{days} d &middot; {amount}",
        "country": "Switzerland", "apx_label": "APX",
        "addon_scope_note": ADDON_SCOPE_NOTE, "addon_sep_label": ADDON_SEP_LABEL,
        "acceptance_body": ACCEPTANCE_NARRATIVE,
        "payment_body": "{days} days net from date of invoice. The invoice for the total amount is sent at the end of the performance.",
        "activation_body": "This SOW is agreed between {client} and Numaco AG. It is valid without formal signatures and comes into operation with a commercial purchase order that includes a reference to this document.",
        "billing_body": "Billing is for time actually worked, not the estimate above. Optional add-ons are excluded from the base engagement total and are activated by a purchase order amendment that references this SOW.",
        "effort_footnote": "All effort above is an estimation. Billing is based on time actually worked, as described in section 4 below.",
        "effort_footnote_addons": " Add-ons are optional and priced separately; if the client selects any, its days and amount are added to the total via a PO amendment.",
    },
    "de": {
        "doc_kind": "Leistungsbeschrieb", "confidential": "Vertraulich",
        "page_word": "Seite", "of_word": "von",
        "prepared_for": "Erstellt für", "prepared_by": "Erstellt von",
        "issued": "Ausgestellt", "reference": "Referenz",
        "in_confidence": "Vertraulich", "rev": "Rev. A",
        "parties_eyebrow": "Vertragsparteien", "client": "Kunde",
        "supplier": "Lieferant", "key_contacts": "Ansprechpartner",
        "contacts_vat": "Kontakte &middot; ",
        "apx_title": "Allgemeine Geschäftsbedingungen", "apx_tag": "Standardbedingungen",
        "sec_context": "Ausgangslage", "tag_context": "HINTERGRUND &middot; PROBLEMSTELLUNG",
        "sec_scope": "Leistungsumfang",
        "tag_scope": "LIEFERGEGENSTÄNDE &middot; ABGRENZUNGEN &middot; ANNAHMEN &middot; OPTIONEN",
        "sec_effort": "Aufwandschätzung", "tag_effort": "GRUNDLEISTUNG &middot; TAGESSATZ ",
        "sec_commercial": "Kommerzielle Bedingungen",
        "tag_commercial": "SÄTZE &middot; RECHNUNGSSTELLUNG &middot; GÜLTIGKEIT",
        "sec_activation": "Inkraftsetzung", "tag_activation": "VEREINBARUNG &middot; BESTELLUNG",
        "deliver": "Liefergegenstände", "not_deliver": "Abgrenzungen",
        "assumptions": "Annahmen", "addons": "Optionale Zusatzleistungen",
        "priced_separately": "Separat offeriert",
        "col_ref": "Pos.", "col_workstream": "Arbeitspaket", "col_days": "Tage",
        "col_amount": "Betrag CHF", "total": "Total Grundleistung",
        "billing_basis": "Verrechnungsgrundlage",
        "for_client": "Für den Kunden", "for_supplier": "Für den Lieferanten",
        "term_day_rate": "Tagessatz", "term_outside": "Arbeit ausserhalb der Normalarbeitszeit",
        "term_travel": "Reisekosten", "term_total": "Geschätzter Gesamtbetrag",
        "term_payment": "Zahlung", "term_acceptance": "Abnahme",
        "opt_select_label": "Gewählte optionale Zusatzleistungen",
        "opt_select_note": ("Kreuzen Sie jede gewünschte optionale Zusatzleistung an und senden Sie diese Seite "
                            "zusammen mit der Bestellung zurück. Angekreuzte Positionen werden zu den Ansätzen "
                            "aus Abschnitt 3 zum Total hinzugefügt. Bleiben alle Felder leer, wird ausschliesslich "
                            "die Grundleistung bestellt."),
        "opt_none": "Keine, nur die Grundleistung",
        "opt_meta": "{days} T &middot; {amount}",
        "country": "Schweiz", "apx_label": "ANH",
        "addon_scope_note": "Die nachstehenden Positionen sind nicht Teil der Grundleistung. Jede ist in der Aufwandschätzung separat bepreist; jede Kombination kann vor oder während des Auftrags nach Wahl des Kunden über eine Bestelländerung mit Bezug auf diesen Leistungsbeschrieb hinzugefügt werden.",
        "addon_sep_label": "Optionale Zusatzleistungen (separat bepreist, im Total unten nicht enthalten)",
        "acceptance_body": "Sämtliche Leistungen werden in einem Arbeitsrapport mit detaillierter Leistungsbeschreibung erfasst. Der Kunde kann den Arbeitsrapport jederzeit einsehen. Nach Abschluss der Leistungsperiode stellt Numaco dem Kunden den Arbeitsrapport zur Prüfung und Genehmigung zu; nach der Genehmigung dient er als Grundlage für die Rechnungsstellung.",
        "payment_body": "{days} Tage netto ab Rechnungsdatum. Die Rechnung über den Gesamtbetrag wird nach Abschluss der Leistung gestellt.",
        "activation_body": "Dieser Leistungsbeschrieb wird zwischen {client} und Numaco AG vereinbart. Er ist ohne förmliche Unterschriften gültig und tritt mit einer kommerziellen Bestellung in Kraft, die auf dieses Dokument Bezug nimmt.",
        "billing_body": "Verrechnet wird die tatsächlich geleistete Zeit, nicht die Schätzung oben. Optionale Zusatzleistungen sind im Total der Grundleistung nicht enthalten und werden über eine Bestelländerung mit Bezug auf diesen Leistungsbeschrieb ausgelöst.",
        "effort_footnote": "Sämtliche Aufwände oben sind Schätzungen. Verrechnet wird die tatsächlich geleistete Zeit gemäss Abschnitt 4.",
        "effort_footnote_addons": " Zusatzleistungen sind optional und separat bepreist; wählt der Kunde eine davon, werden deren Tage und Betrag über eine Bestelländerung zum Total hinzugefügt.",
    },
}


def L(data, key):
    """One label, in the payload's language, English if the pack lacks it."""
    lang = str(data.get("language", "en")).lower()
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"][key])


# ---------- helpers ----------
def _paras(value):
    """Normalise a paragraph source to a list of non-empty strings.

    Accepts None (nothing), a string (blank-line separated), or a list of
    strings. Lets every prose block in the document be supplied by the payload
    without the caller having to know how it is rendered.
    """
    if not value:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split("\n\n") if p.strip()]
    return [str(p).strip() for p in value if str(p).strip()]


def _term(item):
    """Normalise one labelled term to a (label, body) pair.

    Accepts {"label": ..., "body": ...} or a two-item sequence, so payloads can
    use whichever reads better.
    """
    if isinstance(item, dict):
        return (item.get("label", ""), item.get("body", ""))
    label, body = item
    return (label, body)


def _resolve(data, key, default):
    """Payload value for `key`, where an explicit empty value suppresses.

    Distinguishes "not supplied" (use the default) from "supplied as empty"
    (render nothing), which is what makes a hardcoded block genuinely optional.
    """
    return default if key not in data else data[key]


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


def _cover_attn(data):
    """The line under the client on the cover: the named addressee, else the city.

    A proposal is addressed to a person. When the payload names contacts, the
    first one goes on the cover so the recipient sees their own name; the city
    is the fallback when it does not.
    """
    contacts = data.get("client_contacts") or []
    if contacts and isinstance(contacts[0], dict) and contacts[0].get("name"):
        return esc(contacts[0]["name"])
    return _client_city(data)


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
    """The cover subtitle.

    Prefer an explicit `cover_subtitle`: a cover line should be written to be a
    cover line. Falling back to the context's first sentence is a convenience,
    and it truncates with an ellipsis when that sentence is long, which reads as
    a defect on a document a customer is about to sign. Supply the key.
    """
    explicit = str(data.get("cover_subtitle") or "").strip()
    if explicit:
        return esc(explicit)
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
    # Uniform body paragraphs (enshrined): the first context paragraph is NOT
    # promoted to a larger, darker .lead; it renders like every other paragraph.
    # The lead promotion read as a bug, not a lead-in. Do not re-introduce it.
    out = [S.para(esc(p)) for p in paras]
    return "".join(out)


def _scope_body(data):
    parts = []

    deliverables = data.get("deliverables", [])
    if deliverables:
        rows = []
        for i, item in enumerate(deliverables, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"S{i}", esc(title), esc(body)))
        parts.append(S.subhead(L(data, "deliver")) + S.items(*rows))

    exclusions = data.get("exclusions", [])
    if exclusions:
        rows = []
        for i, item in enumerate(exclusions, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"N{i}", esc(title), esc(body), excl=True))
        parts.append(S.subhead(L(data, "not_deliver")) + S.items(*rows))

    assumptions = data.get("assumptions", [])
    if assumptions:
        rows = []
        for i, item in enumerate(assumptions, 1):
            title, body = _pair(item)
            rows.append(S.scope_item(f"A{i}", esc(title), esc(body)))
        parts.append(S.subhead(L(data, "assumptions")) + S.items(*rows))

    addons = data.get("optional_addons") or []
    if addons:
        rows = []
        for i, addon in enumerate(addons, 1):
            number = addon.get("number", i)
            rows.append(S.scope_item(
                f"O{number}", esc(addon.get("title", "")),
                _multi(addon.get("body", "")), tag=L(data, "priced_separately")))
        parts.append(
            S.subhead(L(data, "addons"))
            + S.para(esc(_resolve(data, "addon_scope_note", L(data, "addon_scope_note"))))
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
        ("", ""), (L(data, "total"), "ws"),
        (_days(base_days), "num"), (S.num(base_days * rate), "num amt"),
    ]

    addon_rows = None
    if addons:
        addon_rows = [[("", "ref"), (_resolve(data, "addon_separator_label", L(data, "addon_sep_label")), "ws"), ("", "num"), ("", "num")]]
        for i, addon in enumerate(addons, 1):
            number = addon.get("number", i)
            d = float(addon.get("days", 0))
            addon_rows.append([
                (f"O{number}", "ref"), (esc(addon.get("title", "")), "ws"),
                (_days(d), "num"), (S.num(d * rate), "num"),
            ])

    footnote = L(data, "effort_footnote")
    if addons:
        footnote += L(data, "effort_footnote_addons")

    table = S.effort_table(
        [(L(data, "col_ref"), False, "12mm"), (L(data, "col_workstream"), False, None),
         (L(data, "col_days"), True, None), (L(data, "col_amount"), True, None)],
        rows, total_row=total_row, addon_rows=addon_rows, footnote=footnote,
    )
    billing = S.callout(L(data, "billing_basis"), L(data, "billing_body"))
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

    default_terms = [
        (L(data, "term_day_rate"), day_rate_narrative),
        (L(data, "term_outside"),
         _resolve(data, "outside_hours_narrative", OUTSIDE_HOURS_NARRATIVE)),
        (L(data, "term_travel"), _resolve(data, "travel_narrative", TRAVEL_NARRATIVE)),
        (L(data, "term_total"), total_amount_narrative),
        (L(data, "term_payment"),
         _resolve(data, "payment_narrative",
                  L(data, "payment_body").format(days=payment_days))),
        ("Acceptance label placeholder",
         _resolve(data, "acceptance_narrative", L(data, "acceptance_body"))),
    ]
    # The timesheet term's label is itself overridable: calling it "Acceptance"
    # next to a deliverable-acceptance clause starts the warranty clock on the
    # wrong document.
    default_terms[-1] = (
        _resolve(data, "acceptance_label", L(data, "term_acceptance")),
        default_terms[-1][1],
    )

    if "commercial_terms" in data:
        terms = [_term(t) for t in (data["commercial_terms"] or [])]
    else:
        terms = [(k, v) for k, v in default_terms if v]
    terms += [_term(t) for t in data.get("extra_commercial_terms", [])]

    intro = _paras(_resolve(data, "commercial_intro", COMMERCIAL_INTRO))
    intro += _paras(_resolve(data, "commercial_overrun", COMMERCIAL_OVERRUN))
    intro += _paras(data.get("extra_commercial_intro"))

    return (
        "".join(S.para(esc(p)) for p in intro)
        + S.term_list([(k, esc(v)) for k, v in terms])
    )


def _activation_body(data):
    default = L(data, "activation_body").format(client=data["client_legal_name"])
    paras = _paras(_resolve(data, "activation_narrative", default))
    paras += _paras(data.get("activation_extra"))

    out = "".join(S.para(esc(p)) for p in paras)

    # A SOW that offers options must let the signer choose them here, on the page
    # they sign, rather than in a covering email where the choice gets lost.
    addons = data.get("optional_addons") or []
    if addons and data.get("show_option_boxes", True):
        rate = float(data["day_rate_chf"])
        items = []
        for i, addon in enumerate(addons, 1):
            days = float(addon.get("days", 0) or 0)
            meta = L(data, "opt_meta").format(days=_days(days), amount=S.chf(days * rate))
            items.append((f"O{addon.get('number', i)}", esc(addon.get("title", "")), meta))
        items.append(("&mdash;", esc(L(data, "opt_none")), ""))
        out += S.option_boxes(items, label=L(data, "opt_select_label"),
                              note=esc(L(data, "opt_select_note")))

    if data.get("show_signature_block", True):
        out += S.signature_block([
            (L(data, "for_client"), esc(data["client_legal_name"])),
            (L(data, "for_supplier"), "Numaco AG"),
        ])
    return out


def _appendix(data):
    """Parse tcs_body.md into (marker, heading, text) clauses, verbatim."""
    lang = str(data.get("language", "en")).lower()
    tcs = REFERENCES / (f"tcs_body_{lang}.md" if lang != "en" else "tcs_body.md")
    if not tcs.exists():
        tcs = REFERENCES / "tcs_body.md"
    md = tcs.read_text(encoding="utf-8")
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
    return S.appendix(L(data, "apx_title"), clauses, tag=L(data, "apx_tag"),
                      apx_label=L(data, "apx_label"))


# ---------- assembly ----------
def build_body(data):
    rate = float(data["day_rate_chf"])

    cover = S.cover(
        L(data, "doc_kind"),
        esc(data["sow_number"]),
        esc(data["project_title"]),
        _subtitle(data),
        [
            (L(data, "prepared_for"), esc(data["client_legal_name"]), _cover_attn(data)),
            (L(data, "prepared_by"), "Numaco AG", "CH-8905 Islisberg"),
            (L(data, "issued"), esc(data["issue_date"]), L(data, "in_confidence")),
            (L(data, "reference"), esc(data["sow_number"]), L(data, "rev")),
        ],
        "Numaco AG &middot; CH-8905 Islisberg",
        confidential=L(data, "confidential"),
        rev_label=L(data, "rev"),
    )

    client = {
        "role": L(data, "client"),
        "name": esc(data["client_legal_name"]),
        "address": [esc(line) for line in data.get("client_address", [])],
        "contacts_label": L(data, "key_contacts"),
        "contacts": [
            {"name": esc(c.get("name", "")),
             "role": esc(c.get("role", "") or ""),
             "email": esc(c.get("email", "") or "")}
            for c in data.get("client_contacts", [])
        ],
    }
    supplier = {
        "role": L(data, "supplier"),
        "name": "Numaco AG",
        "address": NUMACO_ADDRESS + [L(data, "country")],
        "contacts_label": L(data, "contacts_vat") + NUMACO_VAT,
        "contacts": NUMACO_CONTACTS,
    }
    parties = S.block_eyebrow(L(data, "parties_eyebrow")) + S.parties(client, supplier)

    sec_context = S.section(
        "01", L(data, "sec_context"), L(data, "tag_context"),
        _context_body(data), first=True)
    sec_scope = S.section(
        "02", L(data, "sec_scope"), L(data, "tag_scope"),
        _scope_body(data))
    sec_effort = S.section(
        "03", L(data, "sec_effort"), L(data, "tag_effort") + S.chf(rate),
        _effort_body(data))
    sec_commercial = S.section(
        "04", L(data, "sec_commercial"), L(data, "tag_commercial"),
        _commercial_body(data))
    sec_activation = S.section(
        "05", L(data, "sec_activation"), L(data, "tag_activation"),
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
    title = f"Numaco {L(data, 'doc_kind')} {data['sow_number']}"
    lang = str(data.get("language", "en")).lower()
    S.render_pdf(
        title,
        body,
        output_path,
        L(data, "doc_kind"),
        data["sow_number"],
        extra_css=SOW_CSS,
        watermark_opacity=SOW_WATERMARK_OPACITY,
        lang=lang,
        running_labels={"confidential": L(data, "confidential"),
                        "page_word": L(data, "page_word"),
                        "of_word": L(data, "of_word")},
    )
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
