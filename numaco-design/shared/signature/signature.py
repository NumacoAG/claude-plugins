#!/usr/bin/env python3
"""Numaco Signature - shared presentation module.

Data-driven builders that turn arbitrary content into branded, print-ready HTML in
the LOCKED Numaco Signature look: a navy full-bleed cover, a sober light interior
(white pages, brand navy plus one amber accent), Manrope for display and body,
JetBrains Mono for reference codes / small labels / figures, a faint corner
watermark and a running header/footer drawn as @page elements. Rendered to A4 PDF
through shared/render/numaco_render.py (Paged.js). Self-contained and offline:
signature.css plus Manrope, JetBrains Mono, and the cover images are inlined as
data URIs by assemble().

The production numaco-sow and numaco-report skills import this module and feed the
helpers their own content; every helper takes data and returns an HTML string.

Public API
----------
assemble(title, body_html, doc_kind=None, doc_no=None, extra_css="",
         watermark_opacity=None) -> str
    Full self-contained HTML document. Inlines signature.css + Manrope + JetBrains
    Mono + the @page watermark, adds numaco_render.paged_head(), and (when doc_kind
    and doc_no are given) the running header/footer running elements. Callers may
    add a document family presentation layer and override the watermark opacity
    without changing the shared Signature defaults. body_html is the caller's full
    body markup, typically cover(...) + main_body(...sections...).

cover(kind_label, doc_no, title, subtitle, meta_pairs, footer_line, tag=None) -> str
    Navy cover. meta_pairs is a list of (label, value[, subvalue]) tuples for the
    metadata band; footer_line is the right-hand foot text (left is "numaco.ch");
    tag overrides the top-right "Confidential / Rev A" tag.

section(no, title, tag, body_html="", first=False) -> str
    One interior section (01 / 02 amber number, Manrope heading, mono sub-tag, body).

scope_item(code, title, body, tag=None, excl=False) -> str
    One item row (deliverable / exclusion / assumption / option). Trailing digits in
    code render amber-bold. tag adds a small amber "Optional"-style tag; excl greys it.

effort_table(cols, rows, total_row=None, addon_rows=None, footnote=None, table_class="data effort") -> str
    Engineering effort / data table. cols is a list of (label, num_bool[, width]);
    rows / total_row / addon_rows are lists of (text, css_class) cells. table_class
    sets the <table> class list, so a caller can opt a table into a fixed-geometry
    variant (e.g. "data sow-effort" or "data goods") defined in signature.css.

parties(client, supplier) -> str
    Two-column contracting-parties block. client / supplier are dicts (see _party).

callout(label, text) -> str            Navy callout box (amber label, white body).
term_list(items) -> str                Commercial terms; items is a list of (key, value_html).
line_items_table(rows, subtotal, vat, total, vat_label="VAT 8.1%") -> str
    Priced line-item table. rows is a list of (description, qty, unit[, amount]).
appendix(title, clauses, tag="Representative extract", pagebreak=True, apx_label="APX") -> str
    Appendix section; clauses is a list of (marker, heading, text).
note(label, text) -> str               Amber side note.
signature_block(fields) -> str         Signature grid; fields is a list of (label, name).
option_boxes(items, label=None, note=None) -> str
    Tick-box selection grid for optional add-ons, rendered on the signature page.
    items is a list of (code, title, meta) triples.

Convenience helpers (also return HTML strings)
    running_elements(doc_kind, doc_no), main_body(*parts), block_eyebrow(text),
    lead(text), para(text), subhead(text), items(*rows), spec_list(bullets),
    num(n), chf(n).

render_pdf(title, body_html, pdf_path, doc_kind=None, doc_no=None, extra_css="",
           watermark_opacity=None) -> (engine, pages)
    Convenience two-pass render (bakes the true page count into the footer) via
    numaco_render.
"""
import base64
import html as _html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent
BRAND = SHARED / "brand-core"
ASSETS = HERE / "assets"
sys.path.insert(0, str(SHARED / "render"))
import numaco_render as R  # noqa: E402


# ---------------------------------------------------------------------------
# Inlined, offline assets (fonts + brand images) and the locked stylesheet
# ---------------------------------------------------------------------------
def _b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _png(path):
    return "data:image/png;base64," + _b64(path)


# The official Numaco monogram is now a single vector master (crisp at any size).
# Every corner-N in the Signature look is derived from it by re-tinting: the faint
# interior @page watermark (navy on white) and the big cover N (white on navy).
_MONO_SVG = (BRAND / "monogram-official.svg").read_text()   # vector master
_MONO_FILL_TOKEN = 'fill="#183060" fill-rule="nonzero"'     # master's paint attrs

# Interior corner watermark tint. The old raster (numaco_watermark_light.png)
# carried a max alpha of ~12/255, so it never actually showed; this is the
# single knob that sets how present the corner N reads on the page.
WATERMARK_OPACITY = 0.12


def _mono_variant(fill, opacity=1.0):
    """A data-URI copy of the vector monogram, re-tinted (fill + fill-opacity)."""
    repl = f'fill="{fill}" fill-opacity="{opacity:g}" fill-rule="nonzero"'
    svg = _MONO_SVG.replace(_MONO_FILL_TOKEN, repl, 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_JBM = _b64(ASSETS / "jetbrainsmono-400.woff2")            # JetBrains Mono woff2
_WM = _mono_variant("#183060", WATERMARK_OPACITY)          # faint navy corner N (interior)
_MONOGRAM = _mono_variant("#ffffff")                       # white N (cover; CSS sets opacity)
_WORDMARK = _png(ASSETS / "numaco_wordmark_white.png")     # white Numaco wordmark
_MANROPE = (BRAND / "fonts" / "manrope.css").read_text()   # variable @font-face
_CSS = (HERE / "signature.css").read_text()                # locked stylesheet


def stylesheet(watermark_opacity=None):
    """The Signature stylesheet, optionally with a document specific watermark."""
    wm = (
        _WM
        if watermark_opacity is None
        else _mono_variant("#183060", watermark_opacity)
    )
    css = _CSS.replace("__JBM__", _JBM).replace("__WM__", wm)
    return _MANROPE + "\n" + css


def _esc(s):
    return _html.escape(str(s), quote=False)


# ---------------------------------------------------------------------------
# Swiss currency: CHF 21'000.- with apostrophe thousands, .- for whole francs
# ---------------------------------------------------------------------------
def num(n):
    n = round(float(n), 2)
    whole = abs(n - round(n)) < 1e-9
    intpart = int(round(n)) if whole else int(n)
    grp = f"{intpart:,}".replace(",", "'")
    if whole:
        return f"{grp}.-"
    frac = int(round((n - intpart) * 100))
    return f"{grp}.{frac:02d}"


def chf(n):
    return "CHF " + num(n)


# ---------------------------------------------------------------------------
# Document shell
# ---------------------------------------------------------------------------
def running_elements(doc_kind, doc_no, confidential="Confidential", page_word="Page", of_word="of"):
    """The @page running header/footer elements (mono whisper header + footer)."""
    # The "Page n of m" string lives in the stylesheet, so a non-English document
    # overrides it here rather than forking the CSS.
    page_css = ""
    return (
        f'<div class="rhL">Numaco AG&nbsp;&nbsp;/&nbsp;&nbsp;<b>{doc_kind}</b></div>\n'
        f'<div class="rhR">{doc_no}&nbsp;&nbsp;&middot;&nbsp;&nbsp;<em>{confidential}</em></div>\n'
        f'<div class="rfL">numaco.ch&nbsp;&nbsp;&middot;&nbsp;&nbsp;<b>{doc_no}</b></div>'
    )


def assemble(title, body_html, doc_kind=None, doc_no=None, extra_css="",
             watermark_opacity=None, lang="en", running_labels=None):
    """Full self-contained HTML document (offline, PDFKit-safe).

    `lang` sets the document language attribute; `running_labels` is an optional
    dict of {confidential, page_word, of_word} so a non-English document can
    translate the running header and the page counter.
    """
    rl = dict(running_labels or {})
    page_word = rl.pop("page_word", "Page")
    of_word = rl.pop("of_word", "of")
    run = (running_elements(doc_kind, doc_no, **rl)
           if (doc_kind and doc_no) else "")
    # The "Page n of m" string lives in the stylesheet, and Paged.js resolves
    # @page rules from the head before the body is laid out, so a translated
    # counter has to be appended here rather than emitted with the running divs.
    if (page_word, of_word) != ("Page", "of"):
        extra_css = (extra_css or "") + (
            "@page{@bottom-right{"
            f'content:"{page_word} " counter(page) " {of_word} " counter(pages);'
            "}}"
        )
    presentation = f"\n{extra_css}" if extra_css else ""
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n"
        f"{R.paged_head()}\n"
        f"<style>{stylesheet(watermark_opacity)}{presentation}</style>\n"
        "</head><body>\n"
        f"{run}\n{body_html}\n"
        "</body></html>"
    )


def main_body(*parts):
    """Wrap interior sections in <main> (the cover sits outside main)."""
    return "<main>\n" + "\n".join(parts) + "\n</main>"


# ---------------------------------------------------------------------------
# Cover
# ---------------------------------------------------------------------------
def cover(kind_label, doc_no, title, subtitle, meta_pairs, footer_line, tag=None,
          confidential="Confidential", rev_label="Rev A", rev_year=None):
    if tag is not None:
        tag_html = tag
    else:
        rev = rev_label if rev_year is None else f"{rev_label} &middot; {rev_year}"
        tag_html = f"{confidential}<br>{rev}"
    cells = ""
    for pair in meta_pairs:
        label, value = pair[0], pair[1]
        sub = pair[2] if len(pair) > 2 else ""
        cells += (
            f'<div><div class="mk">{label}</div><div class="mv">{value}'
            + (f'<span class="u">{sub}</span>' if sub else "")
            + "</div></div>"
        )
    return f"""
<section class="cover">
  <div class="cv-glow"></div>
  <img class="cv-n" src="{_MONOGRAM}" alt="">
  <img class="cv-wordmark" src="{_WORDMARK}" alt="Numaco">
  <div class="cv-tag">{tag_html}</div>
  <div class="cv-rule"></div>
  <div class="cv-lockup">
    <div class="cv-eyebrow"><span class="dot"></span>{kind_label}<span class="sep">/</span><span class="doc">{doc_no}</span></div>
    <h1 class="cv-title">{title}</h1>
    <p class="cv-sub">{subtitle}</p>
  </div>
  <div class="cv-meta">{cells}</div>
  <div class="cv-foot"><span>numaco.ch</span><span>{footer_line}</span></div>
</section>"""


# ---------------------------------------------------------------------------
# Interior building blocks
# ---------------------------------------------------------------------------
def block_eyebrow(text):
    return f'<div class="block-eyebrow"><span class="dot"></span>{text}</div>'


def section(no, title, tag, body_html="", first=False):
    cls = "sec first" if first else "sec"
    tag_html = f'<span class="sec-tag">{tag}</span>' if tag else ""
    # The section rule, number and heading ride together in one atomic .sec-head
    # block (break-inside avoid) so a section heading can never be the last thing
    # on a page: Paged.js keeps this block with the first line of the body
    # (break-after avoid) and, being unsplittable, moves the whole opening (rule +
    # number + heading) to the next page as a unit, leaving no stranded shell.
    return f"""
<section class="{cls}">
  <div class="sec-head">
    <div class="sec-no">{no}</div>
    <div class="sec-htext"><h2 class="sec-h">{title}</h2>{tag_html}</div>
  </div>
  <div class="sec-body">
{body_html}
  </div>
</section>"""


def lead(text):
    return f'<p class="lead">{text}</p>'


def para(text):
    return f"<p>{text}</p>"


def subhead(text):
    return f'<h3 class="sub">{text}</h3>'


def subsubhead(text):
    """Third-level heading. Distinct from block_eyebrow, which is a block LABEL
    with no top margin and must stay that way (the SOW opens blocks with it)."""
    return f'<h4 class="subsub">{text}</h4>'


def spec_list(bullets):
    """Prose bullets (each item may contain <b> lead-ins)."""
    return '<ul class="spec">' + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"


def items(*rows):
    """Wrap scope_item rows in the shared .items list."""
    return '<div class="items">' + "".join(rows) + "</div>"


def scope_item(code, title, body, tag=None, excl=False):
    i = len(code)
    while i > 0 and code[i - 1].isdigit():
        i -= 1
    code_html = code[:i] + (f"<b>{code[i:]}</b>" if i < len(code) else "")
    cls = "item excl" if excl else "item"
    tag_html = f' <span class="otag">{tag}</span>' if tag else ""
    return (
        f'<div class="{cls}"><div class="code">{code_html}</div>'
        f'<div><div class="isum">{title}{tag_html}</div>'
        f'<div class="ibody">{body}</div></div></div>'
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def _cells(cells):
    out = ""
    for cell in cells:
        text = cell[0]
        cls = cell[1] if len(cell) > 1 else ""
        clsattr = f' class="{cls}"' if cls else ""
        out += f"<td{clsattr}>{text}</td>"
    return out


def effort_table(cols, rows, total_row=None, addon_rows=None, footnote=None,
                 table_class="data effort"):
    thead = ""
    for c in cols:
        label = c[0]
        is_num = c[1] if len(c) > 1 else False
        width = c[2] if len(c) > 2 else None
        # True keeps the historical "num" header class (mono, flush right). A
        # string names the header class outright, which is how a column with an
        # alignment other than the numeric one reaches its own th; the body cells
        # of that column already name their class through _cells().
        col_cls = "num" if is_num is True else (is_num or "")
        clsattr = f' class="{col_cls}"' if col_cls else ""
        style = f' style="width:{width}"' if width else ""
        thead += f"<th{clsattr}{style}>{label}</th>"
    body = ""
    for r in rows:
        body += f"<tr>{_cells(r)}</tr>\n"
    if total_row is not None:
        body += f'<tr class="total">{_cells(total_row)}</tr>\n'
    for ar in (addon_rows or []):
        body += f'<tr class="addon">{_cells(ar)}</tr>\n'
    tbl = (
        f'<table class="{table_class}"><thead><tr>{thead}</tr></thead>'
        f"<tbody>\n{body}</tbody></table>"
    )
    if footnote:
        tbl += f'<p style="margin-top:3mm">{footnote}</p>'
    return tbl


def line_items_table(rows, subtotal, vat, total, vat_label="VAT 8.1%"):
    body = ""
    for r in rows:
        desc, qty, unit = r[0], r[1], r[2]
        amount = r[3] if len(r) > 3 else qty * unit
        body += (
            f'<tr><td class="ws">{desc}</td><td class="num">{qty}</td>'
            f'<td class="num">{num(unit)}</td><td class="num">{num(amount)}</td></tr>\n'
        )
    body += '<tr class="subrule"><td colspan="4"></td></tr>\n'
    body += f'<tr class="totrow"><td colspan="2"></td><td class="k">Subtotal</td><td class="num">{num(subtotal)}</td></tr>\n'
    body += f'<tr class="totrow"><td colspan="2"></td><td class="k">{vat_label}</td><td class="num">{num(vat)}</td></tr>\n'
    body += f'<tr class="totrow grand"><td colspan="2"></td><td class="k">Total incl. VAT</td><td class="num">{num(total)}</td></tr>\n'
    return (
        '<table class="data"><thead><tr><th>Description</th><th class="num">Qty</th>'
        '<th class="num">Unit CHF</th><th class="num">Amount CHF</th></tr></thead>'
        f"<tbody>\n{body}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Parties, callout, terms, notes, appendix, signatures
# ---------------------------------------------------------------------------
def _party(p):
    addr = p.get("address", [])
    if isinstance(addr, (list, tuple)):
        addr = "<br>".join(addr)
    contacts = ""
    for c in p.get("contacts", []):
        nm = c.get("name", "")
        role = c.get("role", "")
        email = c.get("email", "")
        role_html = f' <span>&middot; {role}</span>' if role else ""
        contacts += f'<div class="cn">{nm}{role_html}</div>'
        if email:
            contacts += f'<div class="ce">{email}</div>'
    cx = ""
    if p.get("contacts"):
        cl = p.get("contacts_label", "Contacts")
        cx = f'<div class="cx"><div class="cl">{cl}</div>{contacts}</div>'
    return (
        f'<div class="party"><div class="role">{p.get("role", "")}</div>'
        f'<div class="nm">{p.get("name", "")}</div>'
        f'<div class="addr">{addr}</div>{cx}</div>'
    )


def parties(client, supplier):
    return f'<div class="parties">{_party(client)}{_party(supplier)}</div>'


def callout(label, text):
    return f'<div class="callout"><span class="ck">{label}</span><p>{text}</p></div>'


def term_list(items):
    rows = ""
    for k, v in items:
        rows += f'<div class="term"><div class="tk">{k}</div><div class="tv">{v}</div></div>'
    return f'<div class="terms">{rows}</div>'


def note(label, text):
    return f'<div class="note"><span class="nk">{label}</span>{text}</div>'


def appendix(title, clauses, tag="Representative extract", pagebreak=True, apx_label="APX"):
    cl = ""
    for marker, heading, text in clauses:
        cl += (
            f'<div class="clause"><div class="cn">{marker}</div>'
            f'<div class="ct"><b>{heading}</b>{text}</div></div>'
        )
    pb = '<div class="pagebreak"></div>' if pagebreak else ""
    tag_html = f'<span class="sec-tag">{tag}</span>' if tag else ""
    return f"""{pb}
<section class="sec first">
  <div class="sec-head">
    <div class="sec-no apx">{apx_label}</div>
    <div class="sec-htext"><h2 class="sec-h">{title}</h2>{tag_html}</div>
  </div>
  <div class="sec-body"><div class="clauses">{cl}</div></div>
</section>"""


def option_boxes(items, label=None, note=None):
    """A tick-box selection grid, one box per selectable option.

    `items` is a list of (code, title, meta) triples: the code renders inside
    the box's corner, the title is what the signer reads, and meta carries the
    effort and price. Exists so a customer can choose options on the signature
    page itself rather than in a covering email, which is where an option
    selection otherwise gets lost.
    """
    rows = ""
    for code, title, meta in items:
        meta_html = f'<div class="obm">{meta}</div>' if meta else ""
        rows += (
            '<div class="ob"><div class="obx"></div>'
            f'<div class="obt"><div class="obc">{code}</div>'
            f'<div class="obn">{title}</div>{meta_html}</div></div>'
        )
    head = f'<div class="obl">{label}</div>' if label else ""
    foot = f'<div class="obn2">{note}</div>' if note else ""
    return f'<div class="optbox">{head}<div class="obg">{rows}</div>{foot}</div>'


def signature_block(fields):
    sigs = ""
    for label, name in fields:
        sigs += (
            f'<div class="sig"><div class="sigbox"></div>'
            f'<div class="sl">{label}</div><div class="sn">{name}</div></div>'
        )
    return f'<div class="sign">{sigs}</div>'


# ---------------------------------------------------------------------------
# Convenience render (two-pass: bake the true page count into the footer)
# ---------------------------------------------------------------------------
def render_pdf(title, body_html, pdf_path, doc_kind=None, doc_no=None,
               extra_css="", watermark_opacity=None, lang="en",
               running_labels=None):
    html = assemble(
        title,
        body_html,
        doc_kind,
        doc_no,
        extra_css=extra_css,
        watermark_opacity=watermark_opacity,
        lang=lang,
        running_labels=running_labels,
    )
    pdf_path = Path(pdf_path)
    tmp = pdf_path.with_suffix(".html")
    tmp.write_text(html.replace("counter(pages)", '"0"'))
    R.render_paged(str(tmp), str(pdf_path))
    n = R.pdf_page_count(pdf_path)
    tmp.write_text(html.replace("counter(pages)", f'"{n}"'))
    eng = R.render_paged(str(tmp), str(pdf_path))
    return eng, n
