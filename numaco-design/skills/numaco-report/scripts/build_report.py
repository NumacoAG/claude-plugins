#!/usr/bin/env python3
"""
numaco-report engine: data-driven Markdown -> LOCKED Numaco Signature A4 PDF.

Takes ONE Markdown document that carries a YAML-ish front-matter header, maps
standard Markdown (plus a few Numaco-specific fenced blocks) onto the shared
Numaco Signature presentation module (shared/signature/signature.py), and renders
it to a self-contained, offline A4 PDF through the shared paged renderer, then
runs the CoreGraphics fidelity check.

The HTML is produced ENTIRELY through signature-module calls (cover, section,
para, lead, subhead, block_eyebrow, scope_item, spec_list, effort_table,
line_items_table, note, appendix). This engine never hand-writes branded HTML or
a bespoke stylesheet; the locked look lives in the shared module.

CLI (unchanged):
    build_report.py <input.md> <output.pdf>

Front-matter keys (all optional except title):
    doc_type      cover eyebrow / running-header kind label, e.g. "Solution design"
    title         cover / document title
    subtitle      cover sub-title
    prepared_for  "Prepared for" party on the cover meta band
    date          "Issued" value on the cover meta band
    doc_number    document number (cover eyebrow doc no + running header/footer)
    cover         true|false  -> emit the Signature cover section (default true)
    watermark     true|false  -> accepted for input-contract compatibility; the
                                 faint corner watermark is part of the LOCKED
                                 Signature design and is always drawn on interior
                                 pages, so this key is a no-op.

Body Markdown vocabulary (mapped to the Signature module):
    # H1                  section(auto 01/02..., title[, tag]);  "# Title | Tag"
                          splits an optional mono sub-tag off the heading; a
                          leading "1. " ordinal is stripped (the module numbers).
    ## H2                 subhead (h3.sub)
    ### H3                block_eyebrow (small dotted eyebrow label)
    paragraph            para (the first paragraph of the first section -> lead)
    - bullet             spec_list; "Title -- body" / "Title : body" bolds the title
    1. item              scope_item inside items(); a leading "C1:" / "S1:" label
                         becomes the amber code, "Title -- body" splits summary/body
    | a | b |            effort_table; ---: alignment -> numeric column;
                         a row whose first cell starts with "=" -> total row
    :::items {json}      line_items_table with computed subtotal / VAT / grand-total
    :::note ... :::      note (amber side note)
    :::small ... :::     fine-print paragraph(s)
    > quote              fine-print paragraph
    :::appendix ... :::  appendix(); its first heading is the appendix title,
                         any ## / ### inside become clause headings
    :::pagebreak / ---   hard page break

Inline: **bold**, *italic*, `code`.
"""
import json
import os
import re
import sys
from pathlib import Path

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

ND = Path(__file__).resolve().parents[3]          # .../numaco-design
sys.path.insert(0, str(ND / "shared/signature"))
import signature as S  # noqa: E402  (pulls in the shared paged renderer itself)

FOOTER_LINE = "Numaco AG &middot; CH-8905 Islisberg"


# ---------------------------------------------------------------- utilities
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def inline(s):
    """Escape then apply inline Markdown: `code`, **bold**, *italic*."""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


# split "Title -- body" / "Title : body" / "Title | body" into (title, body)
_TITLE_SPLIT = re.compile(r"^(.*?)\s*(?:--|:|\|)\s+(.*)$", re.DOTALL)


# ---------------------------------------------------------------- front matter
def parse_front_matter(text):
    fm, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip("\n")
            body = text[end + 4:]
            for line in block.splitlines():
                if not line.strip() or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                if (v.startswith('"') and v.endswith('"')) or \
                   (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                lv = v.lower()
                if lv in ("true", "yes"):
                    v = True
                elif lv in ("false", "no"):
                    v = False
                fm[k] = v
    return fm, body.lstrip("\n")


# ---------------------------------------------------------------- table cells
def _table_cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def render_effort_table(tbl_lines):
    """Markdown table -> Signature effort_table.

    header row, alignment row (---: marks numeric columns), then body rows.
    A body row whose first cell starts with "=" becomes the total row.
    """
    header = _table_cells(tbl_lines[0])
    aligns = _table_cells(tbl_lines[1])
    right = [a.endswith(":") and not a.startswith(":") for a in aligns]

    cols = []
    for j, h in enumerate(header):
        is_num = right[j] if j < len(right) else False
        cols.append((inline(h), is_num))

    rows, total_row = [], None
    for raw in tbl_lines[2:]:
        rc = _table_cells(raw)
        is_total = bool(rc) and rc[0].startswith("=")
        if is_total:
            rc[0] = rc[0][1:].strip()
        cells = []
        for j, c in enumerate(rc):
            is_num = right[j] if j < len(right) else False
            if is_total:
                cls = "num amt" if is_num else "ws"
            else:
                cls = "num" if is_num else "ws"
            cells.append((inline(c), cls))
        if is_total:
            total_row = cells
        else:
            rows.append(cells)
    return S.effort_table(cols, rows, total_row=total_row)


def render_line_items(json_text):
    """:::items {json} -> Signature line_items_table with computed money.

    Computes amount per line, sums the subtotal, applies the VAT rate, and adds
    the grand total. Swiss VAT invariant: subtotal + subtotal*rate == total.
    """
    data = json.loads(json_text)
    rate = float(data.get("tax_rate", 0) or 0)
    tax_label = data.get("tax_label") or (f"VAT {rate * 100:.1f}%".rstrip("0").rstrip("."))
    items = data.get("items", [])

    rows, subtotal = [], 0.0
    for it in items:
        qty = float(it.get("qty", 1))
        price = float(it.get("unit_price", 0))
        amount = qty * price
        subtotal += amount
        # qty passed pre-formatted; amount passed explicitly so the module does
        # not recompute (which would fail on a string qty).
        rows.append((inline(str(it.get("description", ""))), S.num(qty), price, amount))

    vat = subtotal * rate
    total = subtotal + vat
    return S.line_items_table(rows, subtotal, vat, total, vat_label=esc(tax_label))


# ---------------------------------------------------------------- section body
def render_section_body(lines, lead_used, first_section):
    """Turn a section's inner Markdown lines into Signature body HTML."""
    out = []
    i, n = 0, len(lines)
    para = []

    def flush_para():
        if para:
            text = inline(" ".join(x.strip() for x in para).strip())
            if first_section and not lead_used[0]:
                out.append(S.lead(text))
                lead_used[0] = True
            else:
                out.append(S.para(text))
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_para()
            i += 1
            continue

        # fenced blocks  :::name ...
        if stripped.startswith(":::"):
            flush_para()
            name = stripped[3:].strip().split()[0] if stripped[3:].strip() else ""
            if name == "pagebreak":
                out.append('<div class="pagebreak"></div>')
                i += 1
                continue
            inner = []
            i += 1
            while i < n and lines[i].strip() != ":::":
                inner.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            if name == "items":
                out.append(render_line_items("\n".join(inner)))
            elif name == "note":
                txt = inline(" ".join(x.strip() for x in inner if x.strip()))
                out.append(S.note("Note", txt))
            elif name == "small":
                txt = inline(" ".join(x.strip() for x in inner if x.strip()))
                out.append(fineprint(txt))
            else:  # unknown fence: render inner as ordinary section body
                out.append(render_section_body(inner, lead_used, False))
            continue

        # horizontal rule -> page break
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush_para()
            out.append('<div class="pagebreak"></div>')
            i += 1
            continue

        # headings inside a section: ## -> subhead, ### (or deeper) -> block_eyebrow
        m = re.match(r"^(#{2,})\s+(.*)$", stripped)
        if m:
            flush_para()
            text = inline(m.group(2).strip())
            if len(m.group(1)) == 2:
                out.append(S.subhead(text))
            else:
                out.append(S.block_eyebrow(text))
            i += 1
            continue

        # blockquote -> fine print
        if stripped.startswith(">"):
            flush_para()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(fineprint(inline(" ".join(buf))))
            continue

        # markdown table -> effort_table
        if stripped.startswith("|") and i + 1 < n and \
           re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            flush_para()
            tbl_lines = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            out.append(render_effort_table(tbl_lines))
            continue

        # unordered list -> spec_list
        if re.match(r"^[-*]\s+", stripped):
            flush_para()
            bullets = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                it = re.sub(r"^[-*]\s+", "", lines[i].strip())
                mt = _TITLE_SPLIT.match(it)
                if mt and mt.group(1).strip():
                    bullets.append("<b>" + inline(mt.group(1).strip()) + "</b> "
                                   + inline(mt.group(2).strip()))
                else:
                    bullets.append(inline(it))
                i += 1
            out.append(S.spec_list(bullets))
            continue

        # ordered list -> scope_item(s) wrapped in items()
        if re.match(r"^\d+[.)]\s+", stripped):
            flush_para()
            k = 1
            rows = []
            while i < n and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                body_txt = re.sub(r"^\d+[.)]\s+", "", lines[i].strip())
                lbl_m = re.match(r"^([A-Z]{0,2}\d+):\s+(.*)$", body_txt)
                if lbl_m:
                    code = lbl_m.group(1)
                    rest = lbl_m.group(2)
                else:
                    code = str(k)
                    rest = body_txt
                mt = _TITLE_SPLIT.match(rest)
                if mt and mt.group(1).strip():
                    title = inline(mt.group(1).strip())
                    body = inline(mt.group(2).strip())
                else:
                    title = inline(rest)
                    body = ""
                rows.append(S.scope_item(esc(code), title, body))
                i += 1
                k += 1
            out.append(S.items(*rows))
            continue

        # otherwise accumulate into a paragraph
        para.append(stripped)
        i += 1

    flush_para()
    return "\n".join(out)


def fineprint(html):
    """A small, muted fine-print paragraph using the module's design tokens."""
    return ('<p style="font-size:8.4pt;line-height:1.5;color:var(--grey);'
            'margin-top:2mm">' + html + "</p>")


# ---------------------------------------------------------------- appendix
def build_appendix(inner_lines):
    """:::appendix ... ::: -> Signature appendix().

    The first heading is the appendix title. Any ## / ### inside start a new
    clause (its heading is the clause heading); prose paragraphs accumulate into
    the current clause. Markers are left blank (the source carries no clause
    symbols to invent).
    """
    title = "Appendix"
    clauses = []                 # list of [marker, heading, paragraphs]
    cur = ["", "", []]           # implicit lead-in clause (no heading)
    have_title = False
    para = []

    def flush_para():
        if para:
            cur[2].append(inline(" ".join(x.strip() for x in para).strip()))
            para.clear()

    def close_clause():
        flush_para()
        if cur[2]:
            clauses.append((cur[0], cur[1], cur[2][:]))

    for line in inner_lines:
        stripped = line.strip()
        if not stripped:
            flush_para()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            text = m.group(2).strip()
            if not have_title:
                title = text
                have_title = True
                continue
            # a sub-heading -> start a new clause
            close_clause()
            cur = ["", inline(text), []]
            continue
        para.append(stripped)
    close_clause()

    # assemble each clause's paragraphs into the (marker, heading, text) shape
    triples = []
    for marker, heading, paras in clauses:
        lead = "<br>" if heading else ""
        text = lead + "<br><br>".join(paras)
        triples.append((marker, heading, text))
    if not triples:
        triples = [("", "", "")]
    return S.appendix(inline(title), triples, tag=None)


# ---------------------------------------------------------------- body -> parts
def build_body_parts(body_lines):
    """Split the Markdown body into top-level Signature parts (sections + appendix)."""
    parts = []
    preamble = []
    sec_no = 0
    lead_used = [False]
    i, n = 0, len(body_lines)

    def flush_preamble():
        if preamble:
            html = render_section_body(preamble, lead_used, False)
            if html.strip():
                parts.append(html)
            preamble.clear()

    while i < n:
        stripped = body_lines[i].strip()

        # appendix fence (consumed whole)
        if stripped.startswith(":::appendix"):
            flush_preamble()
            inner = []
            i += 1
            while i < n and body_lines[i].strip() != ":::":
                inner.append(body_lines[i])
                i += 1
            i += 1
            parts.append(build_appendix(inner))
            continue

        # top-level H1 -> a section
        m = re.match(r"^#\s+(.*)$", stripped)
        if m:
            flush_preamble()
            title_raw = m.group(1).strip()
            inner = []
            i += 1
            while i < n:
                t = body_lines[i].strip()
                if re.match(r"^#\s+", t) or t.startswith(":::appendix"):
                    break
                inner.append(body_lines[i])
                i += 1
            sec_no += 1
            tag = None
            if " | " in title_raw:
                title_raw, tag = [x.strip() for x in title_raw.split(" | ", 1)]
            title = re.sub(r"^\d+[.)]\s+", "", title_raw)
            body_html = render_section_body(inner, lead_used, first_section=(sec_no == 1))
            parts.append(S.section(
                f"{sec_no:02d}", inline(title),
                inline(tag) if tag else None,
                body_html, first=(sec_no == 1)))
            continue

        # standalone top-level page break / rule
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped) or stripped.startswith(":::pagebreak"):
            flush_preamble()
            parts.append('<div class="pagebreak"></div>')
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        preamble.append(body_lines[i])
        i += 1

    flush_preamble()
    return parts


# ---------------------------------------------------------------- cover
def build_cover(fm):
    kind_label = esc(fm.get("doc_type") or "Document")
    doc_no = esc(str(fm.get("doc_number") or ""))
    title = esc(str(fm.get("title") or "Numaco document"))
    subtitle = esc(str(fm.get("subtitle") or ""))

    meta = []
    if fm.get("prepared_for"):
        meta.append(("Prepared for", esc(str(fm["prepared_for"]))))
    meta.append(("Prepared by", "Numaco AG", "CH-8905 Islisberg"))
    if fm.get("date"):
        meta.append(("Issued", esc(str(fm["date"]))))
    if fm.get("doc_number"):
        meta.append(("Reference", esc(str(fm["doc_number"]))))

    return S.cover(kind_label, doc_no, title, subtitle, meta, FOOTER_LINE)


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: build_report.py <input.md> <output.pdf>")
    src = Path(sys.argv[1])
    pdf = Path(sys.argv[2])

    fm, body = parse_front_matter(src.read_text())
    parts = build_body_parts(body.splitlines())

    want_cover = fm.get("cover", True)
    cover_html = build_cover(fm) if want_cover else ""
    body_html = cover_html + S.main_body(*parts)

    title = str(fm.get("title") or fm.get("doc_type") or "Numaco document")
    kind_label = str(fm.get("doc_type") or "Document")
    doc_no = str(fm.get("doc_number") or "")
    doc_kind_arg = kind_label if doc_no else None
    doc_no_arg = doc_no if doc_no else None

    eng, n = S.render_pdf(title, body_html, str(pdf), doc_kind_arg, doc_no_arg)
    print(f"rendered -> {pdf} (engine {eng}, {n} pages)")
    print(f"wrote {pdf.with_suffix('.html')}")

    pages = "1,2" if n <= 2 else f"1,2,{n}"
    S.R.pdfcheck(str(pdf), pdf.stem, pages=pages)
    print(f"page_count: {n}")


if __name__ == "__main__":
    main()
