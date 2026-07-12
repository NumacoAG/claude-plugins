#!/usr/bin/env python3
"""Render a Numaco timesheet as a branded PDF from a JSON payload.

Presentation is the LOCKED Numaco Signature design, driven by the shared module
at shared/signature/signature.py. A timesheet is a working document, so there is
no navy cover page: page one opens directly in the interior style, with a
compact document header (section 01, "Timesheet"), a meta grid (client, project,
period, reference, consultant), one entries table, an approval block, and the
standard Signature running header and footer. The two-pass render (which bakes
the true page count into the footer) and the CoreGraphics fidelity check both
live in the shared module; this file only turns the timesheet payload into the
module's helper calls. Fully self-contained and offline. The final deliverable
is the PDF.

Usage:
    python3 build_timesheet.py payload.json output.pdf
    cat payload.json | python3 build_timesheet.py - output.pdf

Payload schema:

{
  "client_legal_name": "Acme Labs AG",
  "client_address":    ["Industriestrasse 12", "CH-8600 Duebendorf"],   // optional
  "project_title":     "Chromatogram report archival service",
  "period_label":      "Q2 2026",                       // e.g. "April 2026"
  "period_start":      "2026-04-01",                    // ISO date
  "period_end":        "2026-06-30",                    // ISO date
  "reference":         "TS-261912-Q2",                  // optional timesheet number
  "consultant":        "Alex Muster",                   // optional; defaults to the
                                                        // second contact in the
                                                        // per-user defaults file
  "entries": [
    {"date": "2026-04-03", "description": "Kick-off and scoping.", "hours": 3.5}
  ],
  "day_rate_chf":      100,          // OPTIONAL. When present, an Amount column
                                     // appears and each amount is computed as
                                     // hours / 8 * rate. When absent the sheet
                                     // is hours-only. The 100 here is a
                                     // deliberately absurd placeholder; real
                                     // rates come from the user, never from
                                     // examples.
  "notes":             "footer paragraph",              // optional
  "output_path":       "/absolute/path/to/final.pdf"    // optional; else argv[2]
}

Validation is strict and fails loudly: every entry date must parse as an ISO
date and fall inside [period_start, period_end], every hours value must be
greater than zero, and the required fields must be present.

The consultant default (when the payload omits "consultant") is read from the
per-user defaults file at $NUMACO_DESIGN_DEFAULTS or
~/.config/numaco-design/defaults.toml: the second [[sow.contacts]] entry, the
same file the SOW skill uses. If no defaults file exists, the consultant row is
simply omitted.
"""
import html
import json
import os
import sys
from datetime import date
from pathlib import Path

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

# --- locate the shared renderer + signature module ---
ND = Path(__file__).resolve().parents[3]                 # .../numaco-design
sys.path.insert(0, str(ND / "shared" / "render"))
sys.path.insert(0, str(ND / "shared" / "signature"))
import numaco_render as R  # noqa: E402  (kept so tools can reach build_timesheet.R.*)
import signature as S      # noqa: E402  (the LOCKED Numaco Signature design)

# ---- Numaco company constants (identical to build_sow.py; company-wide truths) ----
NUMACO_FOOTER = ("Numaco AG &middot; Haldenstrasse 3c &middot; CH-8905 Islisberg "
                 "&middot; Switzerland &middot; VAT CHE-107.980.861 MWST "
                 "&middot; numaco.ch")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------- defaults
def _load_defaults():
    """Read the per-user defaults TOML, or return {} when unavailable.

    Same loader pattern as build_sow.py: the path is $NUMACO_DESIGN_DEFAULTS if
    set, else ~/.config/numaco-design/defaults.toml. The file is personal
    machine-local config; it is never part of the plugin or any repo. A missing
    file, an unreadable or invalid file, or a Python without tomllib all
    silently fall back to {}.
    """
    try:
        import tomllib
        path = os.environ.get("NUMACO_DESIGN_DEFAULTS") or os.path.join(
            os.path.expanduser("~"), ".config", "numaco-design", "defaults.toml")
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def _default_consultant():
    """The second contact in the defaults file, if present (else None)."""
    try:
        contacts = _load_defaults().get("sow", {}).get("contacts", [])
        if len(contacts) >= 2 and contacts[1].get("name"):
            return str(contacts[1]["name"])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- helpers
def esc(text):
    """Escape for HTML body context (quotes left intact for readable apostrophes)."""
    return html.escape(str(text), quote=False)


def _iso(value, field):
    try:
        return date.fromisoformat(str(value))
    except Exception:
        raise ValueError(f"'{field}' is not a valid ISO date: {value!r}")


def _ddmmyyyy(d):
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _hours(h):
    """Hours with one decimal (two only when a quarter hour needs it)."""
    h = float(h)
    if abs(h * 10 - round(h * 10)) < 1e-9:
        return f"{h:.1f}"
    return f"{h:.2f}"


def _month_label(d):
    return f"{MONTHS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------- validation
def validate(data):
    """Strict payload validation. Raises ValueError listing every violation."""
    problems = []

    for key in ("client_legal_name", "project_title", "period_label",
                "period_start", "period_end"):
        if not str(data.get(key) or "").strip():
            problems.append(f"missing required field '{key}'")

    start = end = None
    if not problems:
        try:
            start = _iso(data["period_start"], "period_start")
            end = _iso(data["period_end"], "period_end")
            if start > end:
                problems.append("'period_start' is after 'period_end'")
        except ValueError as e:
            problems.append(str(e))

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        problems.append("'entries' must be a non-empty list")
    else:
        for i, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                problems.append(f"entry {i}: must be an object")
                continue
            try:
                d = _iso(entry.get("date"), f"entries[{i}].date")
                if start and end and not (start <= d <= end):
                    problems.append(
                        f"entry {i} ({d.isoformat()}): outside the period "
                        f"{start.isoformat()} to {end.isoformat()}")
            except ValueError as e:
                problems.append(str(e))
            if not str(entry.get("description") or "").strip():
                problems.append(f"entry {i}: missing 'description'")
            try:
                h = float(entry.get("hours"))
                if not h > 0:
                    problems.append(f"entry {i}: 'hours' must be greater than 0")
            except (TypeError, ValueError):
                problems.append(f"entry {i}: 'hours' is not a number")

    if "day_rate_chf" in data and data["day_rate_chf"] is not None:
        try:
            if not float(data["day_rate_chf"]) > 0:
                problems.append("'day_rate_chf' must be greater than 0 when given")
        except (TypeError, ValueError):
            problems.append("'day_rate_chf' is not a number")

    if problems:
        raise ValueError("invalid timesheet payload:\n  - "
                         + "\n  - ".join(problems))


# ---------------------------------------------------------------- style glue
# Two small style blocks, both composed strictly from the LOCKED Signature
# tokens. They live here (not in signature.css) because they are timesheet
# specifics, exactly like build_report.py carries its fineprint() glue.
#
# Placement matters and was verified empirically against the Paged.js
# pipeline: the @page:first override must sit in the document HEAD (Paged.js
# only honours element() running content declared in head stylesheets), while
# the table row treatments sit in a style block at the END of the body (a
# trailing rule position that reliably wins the cascade in this pipeline).
def _first_page_interior_css():
    """Restore the interior page chrome on page one.

    The locked @page:first rule strips margins, background, and the running
    header/footer because the Signature cover is normally page one. A timesheet
    has no cover, so page one must carry the standard interior chrome. This is
    a verbatim copy of the locked interior @page declarations, with the same
    watermark image (read from the shared brand core) inlined as a data URI.
    """
    wm = R.data_uri_png(ND / "shared" / "brand-core" / "numaco_watermark_light.png")
    return (
        "@page:first{\n"
        "  margin:26mm 20mm 22mm 20mm;\n"
        "  background:\n"
        f"    url({wm}) right top / 101mm auto no-repeat,\n"
        "    linear-gradient(#dbe0e9,#dbe0e9) 20mm 18.4mm / 170mm 0.25mm no-repeat,\n"
        "    linear-gradient(#dbe0e9,#dbe0e9) 20mm 281mm / 170mm 0.3mm no-repeat;\n"
        "  @top-left{ content:element(rhL); }\n"
        "  @top-right{ content:element(rhR); }\n"
        "  @bottom-left{ content:element(rfL); }\n"
        "  @bottom-right{\n"
        '    content:"Page " counter(page) " of " counter(pages);\n'
        "    font-family:'JetBrains Mono',monospace; font-size:6.2pt; "
        "letter-spacing:.04em; color:#8a93a3;\n"
        "  }\n"
        "}\n"
    )


# Month group rows inside the single entries table. td.tsm mirrors the
# tr.total td.ws treatment (mono uppercase navy); td.tsq mirrors the
# .totrow td.k treatment (mono uppercase grey, right aligned). The !important
# keeps the zebra whisper off these structural rows, matching how the locked
# stylesheet excludes .total and .totrow rows from the zebra. The last two
# rules put a gutter between the Hours and Amount columns: the auto table
# layout can squeeze right-aligned nowrap numeric columns down to their
# content width, which would let the two figures in the total row touch; a
# left padding on the second numeric cell guarantees a visible gap without
# moving the right-edge alignment of either column.
_GROUP_ROW_CSS = (
    "<style>\n"
    "table.data td.tsm{ font-family:var(--font-mono); font-weight:600;"
    " font-size:6.4pt; letter-spacing:.09em; text-transform:uppercase;"
    " color:var(--navy); padding-top:4.6mm; padding-bottom:1.6mm;"
    " border-bottom:0.4mm solid var(--hair);"
    " background:var(--paper) !important; }\n"
    "table.data td.tsq{ background:var(--paper) !important;"
    " border-bottom:0.25mm solid var(--hair); }\n"
    "table.data td.tsq.k{ text-align:right; font-family:var(--font-mono);"
    " font-size:6.4pt; letter-spacing:.08em; text-transform:uppercase;"
    " color:var(--grey); padding-top:3.4mm; }\n"
    "table.data td.num + td.num{ padding-left:4mm; }\n"
    "table.data th.num + th.num{ padding-left:4mm; }\n"
    "</style>"
)


def _head_css():
    """The timesheet's head style block (first-page interior chrome)."""
    return "<style>\n" + _first_page_interior_css() + "</style>"


def _footer_block():
    """The standard Signature document foot line: address and VAT, mono grey."""
    return ('<p style="margin-top:10mm; padding-top:2.5mm;'
            ' border-top:0.25mm solid var(--hair);'
            ' font-family:var(--font-mono); font-size:6.8pt;'
            ' letter-spacing:.04em; color:var(--grey2)">'
            f"{NUMACO_FOOTER}</p>")


# ---------------------------------------------------------------- table
def _entry_amount(hours, rate):
    return round(float(hours) / 8.0 * float(rate), 2)


def _entries_table(data):
    rate = data.get("day_rate_chf")
    rate = float(rate) if rate is not None else None
    with_amount = rate is not None

    start = _iso(data["period_start"], "period_start")
    end = _iso(data["period_end"], "period_end")
    multi_month = (start.year, start.month) != (end.year, end.month)

    entries = sorted(
        ({"date": _iso(e["date"], "date"),
          "description": str(e["description"]).strip(),
          "hours": float(e["hours"])} for e in data["entries"]),
        key=lambda e: e["date"])

    ncols = 4 if with_amount else 3
    if with_amount:
        cols = [("Date", False, "24mm"), ("Description", False, None),
                ("Hours", True, "14mm"), ("Amount CHF", True, "24mm")]
    else:
        cols = [("Date", False, "24mm"), ("Description", False, None),
                ("Hours", True, "16mm")]

    rows = []
    total_hours = 0.0
    total_amount = 0.0

    # group by calendar month, in date order
    groups = []
    for e in entries:
        key = (e["date"].year, e["date"].month)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(e)

    for (_, month_entries) in groups:
        label = _month_label(month_entries[0]["date"])
        if multi_month:
            rows.append([(esc(label), "tsm")] + [("", "tsm")] * (ncols - 1))
        sub_hours = 0.0
        sub_amount = 0.0
        for e in month_entries:
            sub_hours += e["hours"]
            cells = [(_ddmmyyyy(e["date"]), "ref"), (esc(e["description"]), "")]
            cells.append((_hours(e["hours"]), "num"))
            if with_amount:
                amount = _entry_amount(e["hours"], rate)
                sub_amount += amount
                cells.append((S.num(amount), "num"))
            rows.append(cells)
        total_hours += sub_hours
        total_amount += sub_amount
        if multi_month:
            sub = [("", "tsq"), (f"Subtotal {esc(label)}", "tsq k"),
                   (_hours(sub_hours), "num tsq")]
            if with_amount:
                sub.append((S.num(sub_amount), "num tsq"))
            rows.append(sub)

    total_label = f"Total {esc(data['period_label'])}"
    if with_amount:
        total_row = [("", ""), (total_label, "ws"),
                     (_hours(total_hours), "num"),
                     (S.num(total_amount), "num amt")]
    else:
        total_row = [("", ""), (total_label, "ws"),
                     (_hours(total_hours), "num amt")]

    footnote = "Hours are stated in decimal form: 0.5 equals 30 minutes."
    if with_amount:
        footnote += (
            " Amounts are computed as hours divided by 8, multiplied by the "
            f"day rate of {S.chf(rate)} per working day, excluding Swiss VAT."
        )

    return S.effort_table(cols, rows, total_row=total_row, footnote=footnote)


# ---------------------------------------------------------------- sections
def _meta_terms(data, consultant):
    client = esc(data["client_legal_name"])
    addr = data.get("client_address") or []
    if isinstance(addr, str):
        addr = [addr]
    if addr:
        client += ", " + ", ".join(esc(line) for line in addr)

    start = _iso(data["period_start"], "period_start")
    end = _iso(data["period_end"], "period_end")
    period = (f"{esc(data['period_label'])} "
              f"({_ddmmyyyy(start)} to {_ddmmyyyy(end)})")

    terms = [
        ("Client", client),
        ("Project", esc(data["project_title"])),
        ("Period", period),
    ]
    if data.get("reference"):
        terms.append(("Reference", esc(data["reference"])))
    if consultant:
        terms.append(("Consultant", esc(consultant)))
    return S.term_list(terms)


def _header_section(data, consultant):
    lead = (f"Hours recorded by Numaco AG for {esc(data['client_legal_name'])} "
            f"on the project {esc(data['project_title'])}, covering "
            f"{esc(data['period_label'])}.")
    body = S.lead(lead) + _meta_terms(data, consultant)
    tag = f"HOURS REPORT &middot; {esc(data['period_label'])}"
    return S.section("01", "Timesheet", tag, body, first=True)


def _entries_section(data):
    with_amount = data.get("day_rate_chf") is not None
    tag = "DATE &middot; DESCRIPTION &middot; HOURS"
    if with_amount:
        tag += " &middot; AMOUNT"
    body = _entries_table(data)
    if data.get("notes"):
        body += S.note("Notes", esc(data["notes"]))
    return S.section("02", "Recorded hours", tag, body)


def _approval_section(data, consultant):
    para = (
        f"This timesheet records the services performed by Numaco AG for "
        f"{esc(data['client_legal_name'])} on the project stated above, during "
        f"{esc(data['period_label'])}. The client is asked to review and "
        "approve the recorded hours; once approved, this timesheet serves as "
        "the basis for invoicing."
    )
    sig = S.signature_block([
        ("Numaco AG &middot; Date, signature", esc(consultant) if consultant else "Numaco AG"),
        ("For the client &middot; Date, signature", esc(data["client_legal_name"])),
    ])
    return S.section("03", "Approval", "REVIEW &middot; SIGN-OFF",
                     S.para(para) + sig + _footer_block())


# ---------------------------------------------------------------- assembly
def build_body(data):
    consultant = data.get("consultant") or _default_consultant()
    return S.main_body(
        _header_section(data, consultant),
        _entries_section(data),
        _approval_section(data, consultant),
    ) + _GROUP_ROW_CSS


def _render_two_pass(title, body_html, pdf_path, doc_kind, doc_no):
    """The shared two-pass render (bake the true page count into the footer),
    with the timesheet head styles inserted after the locked stylesheet.

    Same sequence as signature.render_pdf, composed from the module's public
    pieces (assemble + numaco_render), because the first-page chrome override
    must live in the document head for Paged.js to honour element() content.
    """
    doc = S.assemble(title, body_html, doc_kind, doc_no)
    doc = doc.replace("</head>", _head_css() + "\n</head>", 1)
    pdf_path = Path(pdf_path)
    tmp = pdf_path.with_suffix(".html")
    tmp.write_text(doc.replace("counter(pages)", '"0"'))
    R.render_paged(str(tmp), str(pdf_path))
    n = R.pdf_page_count(pdf_path)
    tmp.write_text(doc.replace("counter(pages)", f'"{n}"'))
    eng = R.render_paged(str(tmp), str(pdf_path))
    return eng, n


def render(data, output_path):
    """Validate, then render the timesheet PDF via the shared two-pass renderer.

    Returns (html_path, pdf_path). The intermediate self-contained HTML is
    written alongside the PDF (same stem, .html).
    """
    validate(data)
    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc_no = str(data.get("reference") or data["period_label"])
    body = build_body(data)
    title = f"Numaco Timesheet {doc_no}"
    _render_two_pass(title, body, output_path, "Timesheet", esc(doc_no))
    html_path = os.path.splitext(output_path)[0] + ".html"
    return html_path, output_path


# ---------------------------------------------------------------- CLI
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

    try:
        html_path, pdf_path = render(data, output_path)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    print(f"Wrote HTML: {html_path}")
    print(f"Wrote PDF:  {pdf_path}")


if __name__ == "__main__":
    main()
