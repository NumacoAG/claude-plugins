#!/usr/bin/env python3
"""Render a Numaco timesheet as a branded PDF from a JSON payload.

Presentation is the LOCKED Numaco Signal Stack design. The shared Signature
module at shared/signature/signature.py provides document structure and the
Signal Stack stylesheet provides the presentation. Page one is the navy cover
with title, document subtitle, and engagement metadata. Content starts with an
overview containing an optional budget utilisation band and an always present
multicolour hours chart with strong labels and explicit axis titles. When the
payload defines four to eight categories, a dedicated Work mix section explains
the colour system and calculates hours and percentage per category. The
chronological activity log remains grouped by month while each row carries its
category colour. A keep together approval block closes the document. The two
pass render, true page count footer, and CoreGraphics fidelity check live in the
shared module. This file turns the timesheet payload into those shared helpers.
The document is fully self contained and offline. The final deliverable is the
PDF.

Usage:
    python3 build_timesheet.py payload.json output.pdf
    cat payload.json | python3 build_timesheet.py - output.pdf

Payload schema:

{
  "client_legal_name": "Acme Labs AG",
  "client_address":    ["Industriestrasse 12", "CH-8600 Duebendorf"],   // optional
  "project_title":     "Chromatogram report archival service",
  "engagement":        "Archival service build and support",
                                     // OPTIONAL. Shown as the Engagement line in
                                     // the cover meta band; when absent the
                                     // project_title serves as that line.
  "period_label":      "Q2 2026",                       // e.g. "April 2026"
  "period_start":      "2026-04-01",                    // ISO date
  "period_end":        "2026-06-30",                    // ISO date
  "report_date":       "2026-07-02",
                                     // OPTIONAL ISO date shown on the cover.
                                     // The caller passes today's date; when
                                     // absent the engine falls back to
                                     // period_end. The engine never calls
                                     // datetime.now(), so a given payload
                                     // always renders the same document.
  "reference":         "TS-261912-Q2",                  // optional timesheet number
  "consultant":        "Alex Muster",                   // optional; defaults to the
                                                        // second contact in the
                                                        // per-user defaults file
  "budget_hours":      120,
                                     // OPTIONAL, number > 0. When present the
                                     // overview page gains a budget utilisation
                                     // stat band (budget, logged to date,
                                     // utilisation, remaining, plus a progress
                                     // bar) and the chart gains a dashed budget
                                     // line. Comes from the SOW or from the
                                     // user, never invented.
  "prior_hours":       30,
                                     // OPTIONAL, number >= 0, default 0. Hours
                                     // already logged under the same budget
                                     // BEFORE period_start (engagement level
                                     // budgets often span several invoicing
                                     // periods). When > 0: the stat band counts
                                     // them into logged to date, utilisation,
                                     // remaining, and the progress bar, and
                                     // notes the carry under the band; the
                                     // chart's cumulative line starts from this
                                     // baseline at the left edge, while the
                                     // bars stay period hours only. When the
                                     // budget spans longer than the reported
                                     // period, supply this figure (from earlier
                                     // timesheets or the finance overview);
                                     // omitting it would make the utilisation
                                     // figures mislead.
  "categories": [
    {"key": "coordination", "name": "Coordination and project management",
     "description": "Planning, alignment, reporting, and stakeholder coordination.",
     "color": "#3f65a6"},
    {"key": "design", "name": "Technical design and advisory",
     "description": "Architecture, analysis, solution design, and technical advice.",
     "color": "#c98a14"},
    {"key": "development", "name": "Development and enhancement",
     "description": "Implementation of new capabilities and material improvements.",
     "color": "#1f7a8c"},
    {"key": "validation", "name": "Testing, validation and handover",
     "description": "Verification, release preparation, documentation, and handover.",
     "color": "#5b8f7b"}
  ],
                                     // OPTIONAL. Supply four to eight categories.
                                     // The renderer calculates the Work mix and
                                     // applies colours to the chronological log.
  "entries": [
    {"date": "2026-04-03", "description": "Kick-off and scoping.", "hours": 3.5,
     "by": "Petra M.", "category": "coordination"}
                                     // "by" is OPTIONAL per entry: a short
                                     // consultant name. When any entry carries
                                     // "by", a By column renders between Date
                                     // and Description; when none do, the
                                     // column is omitted entirely.
                                     // "category" is REQUIRED on every entry
                                     // when top-level categories are supplied.
  ],
  "hourly_rate_chf":   12.50,        // OPTIONAL. The billing rate per hour, and
                                     // the preferred way to price a sheet: a
                                     // timesheet records hours, so the note
                                     // states an hourly rate. Takes precedence
                                     // over day_rate_chf. The 12.50 here is a
                                     // deliberately absurd placeholder.
  "rate_note":         "...",        // OPTIONAL. Replaces the footnote under the
                                     // log table outright; "" removes it.
  "day_rate_chf":      100,          // OPTIONAL, legacy. Divided by 8 to get the
                                     // hourly rate. When present, an Amount column
                                     // appears and each amount is computed as
                                     // hours / 8 * rate. When absent the sheet
                                     // is hours-only. The 100 here is a
                                     // deliberately absurd placeholder; real
                                     // rates come from the user, never from
                                     // examples.
  "notes":             "footer paragraph",              // optional
  "output_path":       "/absolute/path/to/final.pdf"    // optional; else argv[2]
}

Chart bucketing rule: monthly buckets when the period spans more than one
calendar month, else weekly buckets on ISO weeks (labeled "W24" style, with the
week's date range in small text under the label).

Validation is strict and fails loudly: every entry date must parse as an ISO
date and fall inside [period_start, period_end], every hours value must be
greater than zero, budget_hours and day_rate_chf must be positive numbers when
given, prior_hours must be a non negative number when given, report_date must
be an ISO date when given, categories must contain four to eight unique keys,
and every categorised entry must reference a defined key. Required fields must
be present.

The consultant default (when the payload omits "consultant") is read from the
per-user defaults file at $NUMACO_DESIGN_DEFAULTS or
~/.config/numaco-design/defaults.toml: the second [[sow.contacts]] entry, the
same file the SOW skill uses. If no defaults file exists, the consultant line is
simply omitted.
"""
import html
import json
import math
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

# --- locate the shared renderer + signature module ---
ND = Path(__file__).resolve().parents[3]                 # .../numaco-design
sys.path.insert(0, str(ND / "shared" / "render"))
sys.path.insert(0, str(ND / "shared" / "signature"))
import numaco_render as R  # noqa: E402  (kept so tools can reach build_timesheet.R.*)
import signature as S      # noqa: E402  (the LOCKED Numaco Signature design)

TIMESHEET_CSS = (ND / "shared" / "signal-stack" / "signal-stack.css").read_text()
TIMESHEET_WATERMARK_OPACITY = 0.085

# ---- Numaco company constants (identical to build_sow.py; company-wide truths) ----
NUMACO_FOOTER = ("Numaco AG &middot; Haldenstrasse 3c &middot; CH-8905 Islisberg "
                 "&middot; Switzerland &middot; VAT CHE-107.980.861 MWST "
                 "&middot; numaco.ch")
COVER_FOOTER_LINE = "Numaco AG &middot; CH-8905 Islisberg"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Signature palette literals for the inline SVG chart. SVG presentation
# attributes cannot resolve CSS custom properties reliably across Paged.js and
# CoreGraphics, so the chart bakes the same values that signature.css binds to
# its variables: navy, ink, amber, grey, grey2, hair.
_C_NAVY = "#183060"
_C_INK = "#14181f"
_C_AMBER = "#c98a14"
_C_GREY = "#5c6474"
_C_GREY2 = "#8a93a3"
_C_HAIR = "#e3e7ee"
_SVG_MONO = "JetBrains Mono, monospace"
_CHART_COLORS = ("#183060", "#1f7a8c", "#c98a14", "#3f65a6",
                 "#5b8f7b", "#b75c4d", "#7b61a8", "#5c6474")
_CATEGORY_COLORS = ("#3f65a6", "#c98a14", "#b75c4d", "#1f7a8c",
                    "#5b8f7b", "#7b61a8", "#8a6a48", "#56708f")


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


def _hours_trim(h):
    """Hours for stat figures and chart captions: no decimals on whole values."""
    h = float(h)
    if abs(h - round(h)) < 1e-9:
        return str(int(round(h)))
    return _hours(h)


def _month_label(d):
    return f"{MONTHS[d.month - 1]} {d.year}"


def _parsed_entries(data):
    """Entries parsed, normalised, and sorted by date."""
    return sorted(
        ({"date": _iso(e["date"], "date"),
          "description": str(e["description"]).strip(),
          "hours": float(e["hours"]),
          "by": str(e.get("by") or "").strip(),
          "category": str(e.get("category") or "").strip()} for e in data["entries"]),
        key=lambda e: e["date"])


def _categories(data):
    """Normalised category definitions with stable fallback colours."""
    return [
        {
            "key": str(category["key"]).strip(),
            "name": str(category["name"]).strip(),
            "description": str(category["description"]).strip(),
            "color": str(category.get("color") or _CATEGORY_COLORS[i]).strip(),
        }
        for i, category in enumerate(data.get("categories") or [])
    ]


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

    if data.get("report_date"):
        try:
            _iso(data["report_date"], "report_date")
        except ValueError as e:
            problems.append(str(e))

    raw_categories = data.get("categories")
    category_keys = set()
    if raw_categories is not None:
        if not isinstance(raw_categories, list) or not 4 <= len(raw_categories) <= 8:
            problems.append("'categories' must contain between 4 and 8 category objects")
        else:
            for i, category in enumerate(raw_categories, 1):
                if not isinstance(category, dict):
                    problems.append(f"category {i}: must be an object")
                    continue
                key = str(category.get("key") or "").strip()
                if not key:
                    problems.append(f"category {i}: missing 'key'")
                elif key in category_keys:
                    problems.append(f"category {i}: duplicate key {key!r}")
                else:
                    category_keys.add(key)
                if not str(category.get("name") or "").strip():
                    problems.append(f"category {i}: missing 'name'")
                if not str(category.get("description") or "").strip():
                    problems.append(f"category {i}: missing 'description'")
                color = category.get("color")
                if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
                    problems.append(f"category {i}: 'color' must be a six digit hex colour")

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
            entry_category = str(entry.get("category") or "").strip()
            if category_keys and entry_category not in category_keys:
                problems.append(
                    f"entry {i}: category {entry_category!r} is not defined in 'categories'")
            elif not category_keys and entry_category:
                problems.append(
                    f"entry {i}: carries a category but the payload has no 'categories' list")

    for key in ("day_rate_chf", "hourly_rate_chf", "budget_hours"):
        if key in data and data[key] is not None:
            try:
                if not float(data[key]) > 0:
                    problems.append(f"'{key}' must be greater than 0 when given")
            except (TypeError, ValueError):
                problems.append(f"'{key}' is not a number")

    if "prior_hours" in data and data["prior_hours"] is not None:
        try:
            if float(data["prior_hours"]) < 0:
                problems.append("'prior_hours' must not be negative")
        except (TypeError, ValueError):
            problems.append("'prior_hours' is not a number")

    if problems:
        raise ValueError("invalid timesheet payload:\n  - "
                         + "\n  - ".join(problems))


# ---------------------------------------------------------------- style glue
# One timesheet specific style block, composed strictly from the LOCKED
# Signature tokens. It lives here (not in signature.css) because these are
# timesheet specifics, exactly like build_report.py carries its fineprint()
# glue. The block sits at the END of the body: a trailing rule position that
# reliably wins the cascade in this pipeline (verified empirically against
# Paged.js). The !important keeps the locked nth-child zebra off the timesheet
# rows, whose stripes are assigned explicitly per month group so band and
# subtotal rows never shift the parity.
_TS_CSS = (
    "<style>\n"
    "/* compact zebra entry rows (explicit stripes, parity safe) */\n"
    "table.data td.tse{ padding-top:1.3mm; padding-bottom:1.3mm;"
    " background:var(--paper) !important; vertical-align:middle; }\n"
    "table.data td.tse.ref{ font-size:var(--fs-table_body,9pt) !important;"
    " letter-spacing:.01em; white-space:nowrap; }\n"
    "table.data td.tse.tsz{ background:var(--hair2) !important; }\n"
    "/* month band subheader rows (stronger than the zebra) */\n"
    "table.data td.tsm{ font-family:var(--font-mono); font-weight:600;"
    " font-size:6.4pt; letter-spacing:.09em; text-transform:uppercase;"
    " color:var(--navy); padding:1.9mm 3mm 1.9mm 2.5mm;"
    " border-bottom:0.25mm solid var(--hair);"
    " background:var(--tint-total) !important; }\n"
    "/* month subtotal rows */\n"
    "table.data td.tsq{ background:var(--paper) !important;"
    " border-bottom:0.25mm solid var(--hair);"
    " padding-top:1.7mm; padding-bottom:1.7mm; }\n"
    "table.data td.tsq.k{ text-align:right; font-family:var(--font-mono);"
    " font-size:6.4pt; letter-spacing:.08em; text-transform:uppercase;"
    " color:var(--navy); font-weight:600; padding-top:2.3mm; }\n"
    "table.data td.tsq.num{ font-weight:600; color:var(--navy); }\n"
    "/* gutter between adjacent numeric columns (Hours and Amount) */\n"
    "table.data td.num + td.num{ padding-left:4mm; }\n"
    "table.data th.num + th.num{ padding-left:4mm; }\n"
    "/* budget utilisation stat band */\n"
    ".ts-stats{ border:0.25mm solid var(--hair);"
    " border-top:0.5mm solid var(--navy); padding:4mm 5mm 3.4mm;"
    " margin-top:4.5mm; break-inside:avoid; }\n"
    ".ts-stats .hd{ font-family:var(--font-mono); font-weight:600;"
    " font-size:6.4pt; letter-spacing:.09em; text-transform:uppercase;"
    " color:var(--navy); margin-bottom:3mm; }\n"
    ".ts-stats .grid{ display:grid; grid-template-columns:repeat(4,1fr);"
    " gap:5mm; }\n"
    ".ts-stats .v{ font-family:var(--font-mono); font-weight:600;"
    " font-size:13pt; color:var(--navy); letter-spacing:-.01em; }\n"
    ".ts-stats .v.alert{ color:var(--amber); }\n"
    ".ts-stats .k{ font-family:var(--font-mono); font-size:5.9pt;"
    " letter-spacing:.1em; text-transform:uppercase; color:var(--grey2);"
    " margin-top:1.2mm; }\n"
    ".ts-bar{ height:2.4mm; background:var(--hair2); margin-top:3.6mm; }\n"
    ".ts-bar i{ display:block; height:100%; background:var(--navy); }\n"
    ".ts-bar i.alert{ background:var(--amber); }\n"
    ".ts-bar-cap{ font-family:var(--font-mono); font-size:6.2pt;"
    " letter-spacing:.05em; color:var(--grey); margin-top:1.4mm;"
    " text-align:right; }\n"
    ".ts-carry{ font-family:var(--font-mono); font-size:6.2pt;"
    " letter-spacing:.05em; color:var(--grey2); margin-top:1mm; }\n"
    "/* By column: short consultant names never wrap */\n"
    "table.data td.tsb{ white-space:nowrap; }\n"
    "/* chart block: legend row + inline SVG, kept on one page */\n"
    ".ts-chart{ margin-top:2mm; break-inside:avoid; }\n"
    ".ts-legend{ display:flex; gap:7mm; align-items:center;"
    " font-family:var(--font-mono); font-size:8pt; font-weight:600;"
    " letter-spacing:.06em; color:#3f4a5f; margin:3.5mm 0 1.5mm; }\n"
    ".ts-legend .lg{ display:flex; align-items:center; gap:1.8mm; }\n"
    ".ts-legend .sw{ display:inline-block; }\n"
    ".ts-legend .swb{ width:9mm; height:3mm;"
    " background:linear-gradient(90deg,#183060 0 20%,#1f7a8c 20% 40%,"
    "#c98a14 40% 60%,#3f65a6 60% 80%,#b75c4d 80% 100%); }\n"
    ".ts-legend .swl{ width:4.5mm; height:0.6mm; background:var(--ink); }\n"
    ".ts-legend .swd{ width:4.5mm; height:0;"
    " border-top:0.5mm dashed var(--amber); }\n"
    "/* Hours heading centred, numeric values right aligned with breathing room */\n"
    "table.data th.num{ text-align:center !important;"
    " padding-left:3.5mm !important; padding-right:3.5mm !important; }\n"
    "table.data td.num{ text-align:right !important;"
    " padding-right:4mm !important; }\n"
    "/* optional Work mix insight page */\n"
    ".work-mix-page{ page-break-before:always !important;"
    " break-before:page !important; page-break-after:always; break-after:page;"
    " page-break-inside:avoid; break-inside:avoid-page; }\n"
    ".mix-lead strong{ color:var(--navy); }\n"
    ".category-grid{ display:grid; grid-template-columns:1fr 1fr; gap:3mm;"
    " margin:5mm 0 7mm; page-break-inside:avoid; break-inside:avoid-page; }\n"
    ".category-card{ display:grid; grid-template-columns:4mm 1fr; gap:2.5mm;"
    " padding:3.3mm 3.8mm; border:0.25mm solid #dfe5ed; background:#f7f9fc;"
    " page-break-inside:avoid; break-inside:avoid-page; }\n"
    ".category-swatch{ width:3mm; height:3mm; margin-top:.8mm; border-radius:50%; }\n"
    ".category-name{ color:var(--navy); font-weight:700; font-size:9.4pt;"
    " line-height:1.25; }\n"
    ".category-description{ margin-top:1mm; color:var(--grey); font-size:8.25pt;"
    " line-height:1.36; }\n"
    ".mix-table td:first-child{ font-weight:600; color:#273247; }\n"
    ".mix-key{ display:inline-block; width:2.8mm; height:2.8mm; margin-right:2mm;"
    " border-radius:50%; vertical-align:-.25mm; }\n"
    ".share-wrap{ display:grid; grid-template-columns:1fr 10mm; gap:2mm;"
    " align-items:center; }\n"
    ".share-track{ height:2.2mm; background:#e8edf4; }\n"
    ".share-track i{ display:block; height:100%; }\n"
    ".share-value{ text-align:right; font-family:var(--font-mono); font-weight:600;"
    " color:var(--navy); }\n"
    "/* category markers preserve chronological order and month grouping */\n"
    "table.category-log td.cat-edge{ padding-left:3.8mm !important;"
    " box-shadow:inset 1.15mm 0 0 var(--cat); }\n"
    ".entry-cat{ display:inline-block; width:2.2mm; height:2.2mm;"
    " margin-right:1.6mm; border-radius:50%; background:var(--cat);"
    " vertical-align:.1mm; }\n"
    "/* approval section: text and signature lines stay together */\n"
    ".ts-keep{ break-inside:avoid; }\n"
    "</style>"
)


def _footer_block():
    """The standard Signature document foot line: address and VAT, mono grey."""
    return ('<p style="margin-top:10mm; padding-top:2.5mm;'
            ' border-top:0.25mm solid var(--hair);'
            ' font-family:var(--font-mono); font-size:6.8pt;'
            ' letter-spacing:.04em; color:var(--grey2)">'
            f"{NUMACO_FOOTER}</p>")


# ---------------------------------------------------------------- chart
def _bucket_entries(entries, start, end):
    """Bucket the entries for the chart.

    Monthly buckets when the period spans more than one calendar month, else
    weekly buckets on ISO weeks. Every bucket in the period appears, including
    empty ones, so the time axis is continuous. Returns (buckets, mode) where
    each bucket is {"label", "sub", "hours"} and mode is "monthly" or "weekly".
    """
    monthly = (start.year, start.month) != (end.year, end.month)
    buckets = []
    if monthly:
        index = {}
        y, m = start.year, start.month
        multi_year = start.year != end.year
        while (y, m) <= (end.year, end.month):
            label = MONTHS[m - 1][:3]
            if multi_year:
                label += f" {y % 100:02d}"
            index[(y, m)] = len(buckets)
            buckets.append({"label": label, "sub": "", "hours": 0.0})
            m += 1
            if m == 13:
                m, y = 1, y + 1
        for e in entries:
            buckets[index[(e["date"].year, e["date"].month)]]["hours"] += e["hours"]
        return buckets, "monthly"

    index = {}
    cur = start - timedelta(days=start.weekday())        # Monday of the first week
    while cur <= end:
        iso_y, iso_w, _ = cur.isocalendar()
        wk_a = max(cur, start)
        wk_b = min(cur + timedelta(days=6), end)
        index[(iso_y, iso_w)] = len(buckets)
        buckets.append({
            "label": f"W{iso_w}",
            "sub": (f"{wk_a.day:02d}.{wk_a.month:02d} to "
                    f"{wk_b.day:02d}.{wk_b.month:02d}"),
            "hours": 0.0,
        })
        cur += timedelta(days=7)
    for e in entries:
        iso_y, iso_w, _ = e["date"].isocalendar()
        buckets[index[(iso_y, iso_w)]]["hours"] += e["hours"]
    return buckets, "weekly"


def _nice_step(ymax):
    """A clean tick step (1, 2, 2.5, 5 times a power of ten) for about 5 ticks."""
    raw = ymax / 5.0
    if raw <= 0:
        return 1.0
    mag = 10.0 ** math.floor(math.log10(raw))
    for f in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = f * mag
        if step >= raw - 1e-9:
            return step
    return 10.0 * mag


def _fmt_tick(v):
    return f"{v:g}"


def _chart_svg(buckets, budget, prior=0.0):
    """The hours chart as a pure inline SVG string.

    Distinct brand palette bars per bucket with value labels, an ink cumulative line with round
    point markers and a terminal caption, and (when budget is given) a dashed
    amber budget line with a right aligned label. When prior hours are carried
    forward, the cumulative line starts from that baseline at the left plot
    edge while the bars stay period hours only. All colors are the Signature
    palette literals; labels use the mono face. No external chart library, so
    the drawing survives Paged.js and CoreGraphics unchanged. The SVG scales to
    the content column (roughly 154mm), so one SVG unit prints at about 0.63pt;
    the font sizes below are chosen for that scale.
    """
    prior = float(prior or 0.0)
    cums = []
    run = prior
    for b in buckets:
        run += b["hours"]
        cums.append(run)
    total = run

    ymax = max([total, 1.0]
               + ([float(budget)] if budget else [])
               + [b["hours"] for b in buckets])
    step = _nice_step(ymax)
    top = math.ceil(ymax / step - 1e-9) * step

    width, height = 690.0, 300.0
    has_sub = any(b["sub"] for b in buckets)
    pad_l, pad_r, pad_t = 64.0, 10.0, 22.0
    pad_b = 62.0 if has_sub else 49.0
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def ypos(v):
        return pad_t + plot_h * (1.0 - v / top)

    p = []
    t = step
    while t <= top + 1e-9:
        yy = ypos(t)
        p.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}"'
                 f' y2="{yy:.1f}" stroke="{_C_HAIR}" stroke-width="1"/>')
        t += step
    t = 0.0
    while t <= top + 1e-9:
        yy = ypos(t)
        p.append(f'<text x="{pad_l - 8}" y="{yy + 3.4:.1f}" text-anchor="end"'
                 f' font-family="{_SVG_MONO}" font-size="12.5" font-weight="600"'
                 f' fill="{_C_GREY}">{_fmt_tick(t)}</text>')
        t += step
    base = ypos(0.0)
    p.append(f'<line x1="{pad_l}" y1="{base:.1f}" x2="{width - pad_r}"'
             f' y2="{base:.1f}" stroke="{_C_GREY2}" stroke-width="1"/>')

    n = len(buckets)
    slot = plot_w / n
    bar_w = min(slot * 0.5, 36.0)
    centers = []
    for i, b in enumerate(buckets):
        cx = pad_l + slot * (i + 0.5)
        centers.append(cx)
        if b["hours"] > 0:
            yb = ypos(b["hours"])
            p.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{yb:.1f}"'
                     f' width="{bar_w:.1f}" height="{base - yb:.1f}"'
                     f' fill="{_CHART_COLORS[i % len(_CHART_COLORS)]}"/>')
            p.append(f'<text x="{cx:.1f}" y="{yb - 6:.1f}" text-anchor="middle"'
                     f' font-family="{_SVG_MONO}" font-size="13.5"'
                     f' font-weight="700" fill="{_C_NAVY}">'
                     f'{_hours(b["hours"])}</text>')
        p.append(f'<text x="{cx:.1f}" y="{base + 15:.1f}" text-anchor="middle"'
                 f' font-family="{_SVG_MONO}" font-size="12.5" font-weight="600"'
                 f' fill="#3f4a5f">{b["label"]}</text>')
        if b["sub"]:
            p.append(f'<text x="{cx:.1f}" y="{base + 28:.1f}"'
                     f' text-anchor="middle" font-family="{_SVG_MONO}"'
                     f' font-size="10.5" font-weight="600" fill="{_C_GREY}">'
                     f'{b["sub"]}</text>')

    budget_label_y = None
    if budget:
        yb = ypos(float(budget))
        budget_label_y = yb - 6.0
        p.append(f'<line x1="{pad_l}" y1="{yb:.1f}" x2="{width - pad_r}"'
                 f' y2="{yb:.1f}" stroke="{_C_AMBER}" stroke-width="1.8"'
                 f' stroke-dasharray="6 5"/>')
        p.append(f'<text x="{width - pad_r}" y="{budget_label_y:.1f}"'
                 f' text-anchor="end" font-family="{_SVG_MONO}"'
                 f' font-size="13" font-weight="700" fill="{_C_AMBER}">'
                 f'Budget {_hours_trim(budget)} h</text>')

    line_pts = list(zip(centers, cums))
    if prior > 0:
        line_pts.insert(0, (pad_l, prior))
    pts = " ".join(f"{cx:.1f},{ypos(c):.1f}" for cx, c in line_pts)
    p.append(f'<polyline points="{pts}" fill="none" stroke="{_C_INK}"'
             ' stroke-width="2.8"/>')
    for cx, c in zip(centers, cums):
        p.append(f'<circle cx="{cx:.1f}" cy="{ypos(c):.1f}" r="4.2"'
                 f' fill="{_C_INK}" stroke="#ffffff" stroke-width="1.2"/>')

    label_y = ypos(cums[-1]) - 9.0
    if budget_label_y is not None and abs(label_y - budget_label_y) < 14.0:
        label_y = ypos(cums[-1]) + 18.0
    p.append(f'<text x="{centers[-1]:.1f}" y="{label_y:.1f}" text-anchor="end"'
             f' font-family="{_SVG_MONO}" font-size="14" font-weight="700"'
             f' fill="{_C_INK}">{_hours_trim(total)} h cumulative</text>')

    axis_label = "WEEKS" if has_sub else "MONTHS"
    p.append(f'<text x="{width / 2:.1f}" y="{height - 6:.1f}" text-anchor="middle"'
             f' font-family="{_SVG_MONO}" font-size="13.5" font-weight="700"'
             f' letter-spacing="1.2" fill="{_C_NAVY}">{axis_label}</text>')
    y_axis_center = -(pad_t + plot_h / 2.0)
    p.append(f'<text x="{y_axis_center:.1f}" y="14" transform="rotate(-90)"'
             f' text-anchor="middle"'
             f' font-family="{_SVG_MONO}" font-size="13.5" font-weight="700"'
             f' letter-spacing="1.2" fill="{_C_NAVY}">HOURS</text>')

    return (f'<svg viewBox="0 0 {width:g} {height:g}"'
            ' xmlns="http://www.w3.org/2000/svg"'
            ' style="width:100%; height:auto; display:block">'
            + "".join(p) + "</svg>")


def _legend(with_budget):
    parts = ['<span class="lg"><span class="sw swb"></span>Hours</span>',
             '<span class="lg"><span class="sw swl"></span>Cumulative</span>']
    if with_budget:
        parts.append('<span class="lg"><span class="sw swd"></span>Budget</span>')
    return '<div class="ts-legend">' + "".join(parts) + "</div>"


def _stat_band(budget, period_total, prior, period_start):
    """The budget utilisation stat band: four figures and a slim progress bar.

    Logged to date counts the prior hours carried forward from before the
    period; utilisation, remaining, and the bar follow from that total. Past
    100 percent the bar caps visually and the remaining figure turns into a
    negative styled in the Signature amber accent. When prior hours exist, a
    small caption under the bar states the carry.
    """
    budget = float(budget)
    logged = float(prior) + float(period_total)
    pct = logged / budget * 100.0
    remaining = budget - logged
    over = remaining < -1e-9
    fill = min(pct, 100.0)
    rem_cls = "v alert" if over else "v"
    rem_txt = (f"-{_hours_trim(-remaining)} h" if over
               else f"{_hours_trim(remaining)} h")
    bar_cls = "alert" if over else ""
    carry = ""
    if float(prior) > 0:
        carry = (f'<div class="ts-carry">Includes {_hours_trim(prior)} h '
                 f"carried forward from before {_ddmmyyyy(period_start)}</div>")
    return (
        '<div class="ts-stats">'
        '<div class="hd">Budget utilisation</div>'
        '<div class="grid">'
        f'<div><div class="v">{_hours_trim(budget)} h</div>'
        '<div class="k">Budget</div></div>'
        f'<div><div class="v">{_hours_trim(logged)} h</div>'
        '<div class="k">Logged to date</div></div>'
        f'<div><div class="v">{pct:.1f}%</div>'
        '<div class="k">Utilisation</div></div>'
        f'<div><div class="{rem_cls}">{rem_txt}</div>'
        '<div class="k">Remaining</div></div>'
        "</div>"
        f'<div class="ts-bar"><i class="{bar_cls}"'
        f' style="width:{fill:.2f}%"></i></div>'
        f'<div class="ts-bar-cap">{pct:.1f}% of {_hours_trim(budget)} h</div>'
        f"{carry}"
        "</div>"
    )


# ---------------------------------------------------------------- table
def _hourly_rate(data):
    """The billing rate per hour, or None for an hours-only sheet.

    Accepts `hourly_rate_chf` directly, or derives it from `day_rate_chf` on the
    eight hour working day the SOW defines. Everything downstream reasons in
    hours, because that is the unit the timesheet actually records.
    """
    if data.get("hourly_rate_chf") is not None:
        return float(data["hourly_rate_chf"])
    if data.get("day_rate_chf") is not None:
        return float(data["day_rate_chf"]) / 8.0
    return None


def _entry_amount(hours, rate):
    """Amount for one entry, where `rate` is per hour."""
    return round(float(hours) * float(rate), 2)


def _category_totals(data):
    totals = {category["key"]: 0.0 for category in _categories(data)}
    for entry in _parsed_entries(data):
        totals[entry["category"]] += entry["hours"]
    return totals


def _category_css(data):
    rules = []
    for i, category in enumerate(_categories(data)):
        rules.append(f'.cat-{i}{{--cat:{category["color"]};}}')
    return "<style>" + "".join(rules) + "</style>" if rules else ""


def _entries_table(data):
    rate = _hourly_rate(data)
    with_amount = rate is not None

    start = _iso(data["period_start"], "period_start")
    end = _iso(data["period_end"], "period_end")
    multi_month = (start.year, start.month) != (end.year, end.month)

    entries = _parsed_entries(data)
    with_by = any(e["by"] for e in entries)
    categories = _categories(data)
    category_index = {category["key"]: i for i, category in enumerate(categories)}

    cols = [("Date", False, "22mm")]
    if with_by:
        cols.append(("By", False, "26mm"))
    cols.append(("Description", False, None))
    cols.append(("Hours", True, "14mm" if with_amount else "16mm"))
    if with_amount:
        cols.append(("Amount CHF", True, "24mm"))
    ncols = len(cols)

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
        for j, e in enumerate(month_entries):
            sub_hours += e["hours"]
            z = " tsz" if j % 2 else ""       # explicit stripe, restarts per month
            category_class = ""
            marker = ""
            if categories:
                category_class = f" cat-edge cat-{category_index[e['category']]}"
                marker = f'<span class="entry-cat cat-{category_index[e["category"]]}"></span>'
            cells = [(_ddmmyyyy(e["date"]), "ref tse" + z + category_class)]
            if with_by:
                cells.append((esc(e["by"]), "tsb tse" + z))
            cells.append((marker + esc(e["description"]), "tse" + z))
            cells.append((_hours(e["hours"]), "num tse" + z))
            if with_amount:
                amount = _entry_amount(e["hours"], rate)
                sub_amount += amount
                cells.append((S.num(amount), "num tse" + z))
            rows.append(cells)
        total_hours += sub_hours
        total_amount += sub_amount
        if multi_month:
            lead_blanks = ncols - 2 - (1 if with_amount else 0)
            sub = ([("", "tsq")] * lead_blanks
                   + [(f"Subtotal {esc(label)}", "tsq k"),
                      (_hours(sub_hours), "num tsq")])
            if with_amount:
                sub.append((S.num(sub_amount), "num tsq"))
            rows.append(sub)

    total_label = f"Total {esc(data['period_label'])}"
    lead_blanks = ncols - 2 - (1 if with_amount else 0)
    total_row = [("", "")] * lead_blanks + [(total_label, "ws")]
    if with_amount:
        total_row += [(_hours(total_hours), "num"),
                      (S.num(total_amount), "num amt")]
    else:
        total_row += [(_hours(total_hours), "num amt")]

    if "rate_note" in data:
        footnote = str(data["rate_note"] or "")
    else:
        footnote = "Hours are stated in decimal form: 0.5 equals 30 minutes."
        if with_amount:
            footnote += (
                " Amounts are computed as hours multiplied by the hourly rate of "
                f"{S.chf(rate)} per hour, excluding Swiss VAT."
            )

    table_class = "data effort category-log" if categories else "data effort"
    return S.effort_table(cols, rows, total_row=total_row, footnote=footnote,
                          table_class=table_class)


def _work_mix_section(data):
    categories = _categories(data)
    totals = _category_totals(data)
    grand = sum(totals.values())
    ranked = sorted(categories, key=lambda category: totals[category["key"]], reverse=True)
    first, second = ranked[:2]
    first_share = totals[first["key"]] / grand * 100.0
    second_share = totals[second["key"]] / grand * 100.0

    lead = (
        f'The activity mix was led by <strong>{esc(first["name"])}</strong> at '
        f'{_hours(totals[first["key"]])} h ({first_share:.1f}%), followed by '
        f'<strong>{esc(second["name"])}</strong> at '
        f'{_hours(totals[second["key"]])} h ({second_share:.1f}%). '
        'Each entry is assigned to the category that best represents its primary purpose.'
    )

    cards = []
    category_index = {category["key"]: i for i, category in enumerate(categories)}
    for category in categories:
        cls = f'cat-{category_index[category["key"]]}'
        cards.append(
            '<div class="category-card">'
            f'<span class="category-swatch {cls}" style="background:var(--cat)"></span>'
            '<div>'
            f'<div class="category-name">{esc(category["name"])}</div>'
            f'<div class="category-description">{esc(category["description"])}</div>'
            '</div></div>'
        )

    rows = []
    for category in ranked:
        hours = totals[category["key"]]
        share = hours / grand * 100.0
        cls = f'cat-{category_index[category["key"]]}'
        label = (
            f'<span class="mix-key {cls}" style="background:var(--cat)"></span>'
            f'{esc(category["name"])}'
        )
        share_html = (
            '<div class="share-wrap">'
            '<span class="share-track">'
            f'<i class="{cls}" style="width:{share:.2f}%;background:var(--cat)"></i>'
            '</span>'
            f'<span class="share-value">{share:.1f}%</span>'
            '</div>'
        )
        rows.append([(label, ""), (_hours(hours), "num"), (share_html, "")])

    total_row = [(f'Total {esc(data["period_label"])}', "ws"),
                 (_hours(grand), "num"), ("100.0%", "num amt")]
    summary = S.effort_table(
        [("Category", False, None), ("Hours", True, "18mm"),
         ("Share", False, "48mm")],
        rows,
        total_row=total_row,
        table_class="data effort mix-table",
    )
    body = (
        f'<p class="lead mix-lead">{lead}</p>'
        '<div class="category-grid">' + ''.join(cards) + '</div>'
        + S.subhead("Hours by category") + summary
    )
    return '<div class="pagebreak"></div><div class="work-mix-page">' + S.section(
        "02", "Work mix", "SERVICE CATEGORIES &middot; HOURS", body
    ) + '</div><div class="pagebreak"></div>'


# ---------------------------------------------------------------- sections
def _cover(data, consultant):
    """The navy Signature cover, the same idiom the report skill uses."""
    start = _iso(data["period_start"], "period_start")
    end = _iso(data["period_end"], "period_end")
    report_d = _iso(data.get("report_date") or data["period_end"], "report_date")
    doc_no = esc(str(data.get("reference") or data["period_label"]))

    title = esc(data["project_title"])
    subtitle = (f"Timesheet for {esc(data['period_label'])}. Hours recorded by "
                f"Numaco AG for {esc(data['client_legal_name'])}.")

    addr = data.get("client_address") or []
    if isinstance(addr, str):
        addr = [addr]
    addr_line = ", ".join(esc(line) for line in addr)

    meta = [
        ("Client", esc(data["client_legal_name"]), addr_line),
        ("Engagement", esc(data.get("engagement") or data["project_title"])),
        ("Period", esc(data["period_label"]),
         f"{_ddmmyyyy(start)} to {_ddmmyyyy(end)}"),
        ("Report date", _ddmmyyyy(report_d)),
        ("Prepared by", "Numaco AG",
         esc(consultant) if consultant else "CH-8905 Islisberg"),
        ("Contact", "numaco.ch", "Haldenstrasse 3c &middot; CH-8905 Islisberg"),
    ]
    if data.get("reference"):
        meta.append(("Reference", esc(data["reference"])))

    return S.cover("Timesheet", doc_no, title, subtitle, meta, COVER_FOOTER_LINE)


def _overview_section(data):
    """Section 01: lead line, optional budget stat band, and the hours chart."""
    start = _iso(data["period_start"], "period_start")
    end = _iso(data["period_end"], "period_end")
    entries = _parsed_entries(data)
    budget = data.get("budget_hours")
    budget = float(budget) if budget is not None else None
    prior = float(data.get("prior_hours") or 0.0)
    total = sum(e["hours"] for e in entries)

    lead = (f"Hours recorded by Numaco AG for {esc(data['client_legal_name'])} "
            f"on the project {esc(data['project_title'])}, covering "
            f"{esc(data['period_label'])}.")

    buckets, mode = _bucket_entries(entries, start, end)
    chart_title = ("Monthly hours and cumulative usage" if mode == "monthly"
                   else "Weekly hours and cumulative usage")
    if budget:
        chart_title += " vs budget"

    body = S.lead(lead)
    if budget:
        body += _stat_band(budget, total, prior, start)
    body += S.subhead(chart_title)
    body += ('<div class="ts-chart">' + _legend(bool(budget))
             + _chart_svg(buckets, budget, prior) + "</div>")

    tag = "HOURS &middot; CUMULATIVE"
    if budget:
        tag += " &middot; BUDGET"
    return S.section("01", "Overview", tag, body, first=True)


def _entries_section(data):
    body = _entries_table(data)
    if data.get("notes"):
        body += S.note("Notes", esc(data["notes"]))
    number = "03" if data.get("categories") else "02"
    return S.section(number, "Recorded hours", "", body)


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
    number = "04" if data.get("categories") else "03"
    sec = S.section(number, "Approval", "REVIEW &middot; SIGN-OFF",
                    S.para(para) + sig + _footer_block())
    return '<div class="ts-keep">' + sec + "</div>"


# ---------------------------------------------------------------- assembly
def build_body(data):
    consultant = data.get("consultant") or _default_consultant()
    sections = [_overview_section(data)]
    if data.get("categories"):
        sections.append(_work_mix_section(data))
    sections.extend((_entries_section(data), _approval_section(data, consultant)))
    return (_cover(data, consultant) + S.main_body(*sections)
            + _TS_CSS + _category_css(data))


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
    S.render_pdf(
        title,
        body,
        output_path,
        "Timesheet",
        esc(doc_no),
        extra_css=TIMESHEET_CSS,
        watermark_opacity=TIMESHEET_WATERMARK_OPACITY,
    )
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
