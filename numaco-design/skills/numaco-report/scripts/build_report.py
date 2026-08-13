#!/usr/bin/env python3
"""
numaco-report engine: data-driven Markdown -> LOCKED Numaco Signature A4 PDF.

Takes ONE Markdown document that carries a small YAML style front matter header,
maps standard Markdown (plus a few Numaco specific fenced blocks) onto the shared
Numaco Signature presentation module (shared/signature/signature.py), applies
the Signal Stack report presentation layer, and renders it to a self contained,
offline A4 PDF through the shared paged renderer, then runs the
CoreGraphics fidelity check.

The HTML structure is produced entirely through Signature module calls (cover,
section, para, lead, subhead, subsubhead, block_eyebrow, scope_item, spec_list,
effort_table, line_items_table, note, appendix). The Signal Stack stylesheet
changes presentation only; the shared module remains the structural contract.

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
    ### H3                subsubhead (third-level heading, carries top margin)
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
    ![Caption](img.png)  figure block; the image is embedded as a data URI, the
                         alt text becomes the caption (empty alt -> no caption),
                         and an optional {width=60%} or {width=90mm} sizes it.
                         Block level only: a figure inside :::note, :::small,
                         :::appendix or a blockquote stops the build, since those
                         join their lines into one paragraph and used to typeset
                         the figure line as literal Markdown.

Inline: **bold**, *italic*, `code`.
"""
import base64
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
REPORT_CSS = (
    ND / "shared" / "signal-stack" / "signal-stack.css"
).read_text()
REPORT_WATERMARK_OPACITY = 0.085


# Directory the Markdown source lives in. Every relative figure path resolves
# against it, so a document and its images travel together. main() sets it; the
# default keeps the module importable and testable on its own.
SRC_DIR = Path.cwd()


# ---------------------------------------------------------------- utilities
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def attr(s):
    """Escape for use inside a double-quoted HTML attribute."""
    return esc(s).replace('"', "&quot;")


def inline(s):
    """Escape then apply inline Markdown: `code`, **bold**, *italic*."""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def plain(s):
    """Drop inline Markdown markers without rendering them.

    For places that take text rather than markup, above all the img alt
    attribute: the caption renders through inline(), but the accessibility text
    must read "bold" and not "**bold**".
    """
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
    return s


# Split "Title -- body" / "Title : body" / "Title | body" into (title, body).
#
# "--" and "|" are deliberate separators and win over ":", which also turns up
# incidentally in ordinary prose. Three guards stop an incidental colon from
# bolding half a paragraph, which it used to do:
#   1. text already opening with "**" is left alone; the author has marked the
#      title themselves, and splitting it stranded the ** markers,
#   2. a colon title longer than _MAX_COLON_TITLE is prose, not a title,
#   3. a split that leaves an odd number of "**" on either side is rejected.
_TITLE_SPLIT_EXPLICIT = re.compile(r"^(.*?)\s*(?:--|\|)\s+(.*)$", re.DOTALL)
_TITLE_SPLIT_COLON = re.compile(r"^(.*?)\s*:\s+(.*)$", re.DOTALL)
_MAX_COLON_TITLE = 80


def _bold_balanced(text):
    return text.count("**") % 2 == 0


def title_split(text):
    """Return a match with (title, body), or None when the text is one run."""
    m = _TITLE_SPLIT_EXPLICIT.match(text)
    if m and _bold_balanced(m.group(1)) and _bold_balanced(m.group(2)):
        return m
    if text.lstrip().startswith("**"):
        return None
    m = _TITLE_SPLIT_COLON.match(text)
    if (m and len(m.group(1)) <= _MAX_COLON_TITLE
            and "**" not in m.group(1)
            and _bold_balanced(m.group(2))):
        return m
    return None


# ---------------------------------------------------------------- figures
#
# A figure is a standard Markdown image alone on its own line:
#
#     ![Caption text](relative/path/to/image.png)
#     ![](diagram.svg){width=60%}
#
# The path resolves against the Markdown file's own directory (an absolute path
# and a leading ~ both work), the alt text becomes the caption (empty alt means
# no caption), and the optional attribute block sizes the figure. The image is
# read and embedded as a data URI, so the assembled HTML stays self-contained and
# offline exactly like every brand asset. An image inside a paragraph or a table
# cell is deliberately out of scope: figures are block level.
#
# The target accepts one level of nested parentheses, because "img/label (1).png"
# is what a browser and Windows both produce on a duplicate download, and the
# earlier [^)]*? target stopped at the first ")" so such a line never parsed at
# all. The <angle bracket> form is accepted as the explicit escape hatch for a
# path that nests more deeply than that.
_FIGURE_LINE = re.compile(
    r"^!\[(?P<alt>(?:[^\[\]]|\[[^\[\]]*\])*)\]\("
    r"\s*(?P<target><[^<>]*>|(?:[^()]|\([^()]*\))*?)\s*"
    r"\)"
    r"(?:\s*\{(?P<attrs>[^}]*)\})?\s*$"
)
_FIGURE_WIDTH = re.compile(r"^width=(?P<v>\d+(?:\.\d+)?)(?P<u>%|mm)$", re.IGNORECASE)

# Extensions the engine will embed. png, jpg and svg are the required set; gif
# and webp ride along because the same base64 embedding covers them.
FIGURE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

# Leading bytes that prove the file really is the raster format its extension
# claims. Without this the engine happily base64s a zero length file or a text
# file renamed .png; the browser then draws its broken image glyph and paints the
# alt text across the column at body size, and the build still reports success.
FIGURE_MAGIC = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    # RIFF....WEBP: four size bytes sit between the two markers
    ".webp": [b"RIFF"],
}

# One data URI per resolved path. A 40 figure document that shows the same label
# in a summary and again in its own section otherwise carries that image twice,
# and base64 is a third larger than the file it encodes.
_FIGURE_URI_CACHE = {}


def _figure_target_path(target):
    """Strip the Markdown decorations off a link target and return the raw path.

    Handles the <angle bracket> form and a trailing "title" or 'title'.
    """
    t = target.strip()
    if t.startswith("<") and ">" in t:
        return t[1:t.index(">")].strip()
    m = re.match(r'^(\S.*?)\s+(["\']).*\2$', t)
    if m:
        t = m.group(1)
    return t.strip()


def resolve_figure(target, raw_line):
    """Resolve a figure path against the Markdown file's directory, or die."""
    raw = _figure_target_path(target)
    if not raw:
        sys.exit(f"ERROR: figure has no path: {raw_line.strip()}")
    if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE):
        sys.exit(
            f"ERROR: figure points at a remote URL: {raw}\n"
            "       Numaco documents are self-contained and offline. Download the\n"
            "       image next to the Markdown file and reference it by path."
        )
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = SRC_DIR / p
    p = Path(os.path.normpath(str(p)))
    if not p.exists():
        sys.exit(
            f"ERROR: figure not found: {raw}\n"
            f"       resolved to: {p}\n"
            f"       source line: {raw_line.strip()}\n"
            f"       Relative figure paths resolve against the Markdown file's own\n"
            f"       directory ({SRC_DIR})."
        )
    if p.is_dir():
        sys.exit(f"ERROR: figure path is a directory, not an image: {p}")
    if p.suffix.lower() not in FIGURE_MIME:
        supported = ", ".join(sorted(FIGURE_MIME))
        sys.exit(
            f"ERROR: unsupported figure type {p.suffix or '(none)'}: {p}\n"
            f"       supported extensions: {supported}"
        )
    return p


def _figure_die(problem, path, raw_line, hint=""):
    """Stop the build on a figure the page could not honestly show.

    Same shape as the neighbouring resolve_figure() errors: what is wrong, the
    resolved location, and the source line that asked for it.
    """
    sys.exit(
        f"ERROR: {problem}\n"
        f"       resolved to: {path}\n"
        f"       source line: {raw_line.strip()}"
        + (f"\n       {hint}" if hint else "")
    )


def figure_bytes(path, raw_line):
    """Read a figure and prove it is the image its extension claims.

    An unreadable file, an empty file, or a file whose leading bytes do not match
    its extension all stop the build here. Embedding them anyway produces a PDF
    that shows the browser's broken image glyph with the alt text painted across
    the column, and the build would still exit 0 reporting success.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        _figure_die(f"figure could not be read: {exc.strerror or exc}",
                    path, raw_line,
                    "Check the file's permissions and that it is a regular file.")

    if not data:
        _figure_die("figure file is empty (zero bytes)", path, raw_line)

    suffix = path.suffix.lower()
    magic = FIGURE_MAGIC.get(suffix)
    if magic and not any(data.startswith(sig) for sig in magic):
        _figure_die(f"figure is not a valid {suffix.lstrip('.')} file "
                    "(its leading bytes do not match the format)",
                    path, raw_line,
                    "The extension and the actual content disagree. Re-export the "
                    "image, or give it the extension it really has.")
    if suffix == ".webp" and not (len(data) >= 12 and data[8:12] == b"WEBP"):
        _figure_die("figure is not a valid webp file (RIFF container without a "
                    "WEBP marker)", path, raw_line)
    if suffix == ".svg" and b"<svg" not in data[:4096].lower():
        _figure_die("figure is not a valid svg file (no <svg element found)",
                    path, raw_line,
                    "An SVG must carry an <svg> root element.")
    return data


def figure_data_uri(path, raw_line):
    """Read an image and return it as a base64 data URI (self-contained, offline)."""
    key = str(path)
    if key not in _FIGURE_URI_CACHE:
        mime = FIGURE_MIME[path.suffix.lower()]
        b64 = base64.b64encode(figure_bytes(path, raw_line)).decode("ascii")
        _FIGURE_URI_CACHE[key] = f"data:{mime};base64,{b64}"
    return _FIGURE_URI_CACHE[key]


def figure_width(attrs, raw_line):
    """Parse the optional {width=60%} / {width=90mm} block; None means full column."""
    if not attrs or not attrs.strip():
        return None
    normalised = re.sub(r"\s*=\s*", "=", attrs.strip())
    width = None
    for part in re.split(r"[;,\s]+", normalised):
        if not part:
            continue
        m = _FIGURE_WIDTH.match(part)
        if not m:
            sys.exit(
                f"ERROR: unsupported figure attribute {part!r}\n"
                f"       source line: {raw_line.strip()}\n"
                "       supported: {width=60%} or {width=90mm}"
            )
        if float(m.group("v")) <= 0:
            sys.exit(f"ERROR: figure width must be greater than zero: {part}")
        width = m.group("v") + m.group("u").lower()
    return width


def reject_figure_in(lines, where):
    """Stop the build on a figure inside a block that cannot hold one.

    :::note, :::small, a blockquote and :::appendix all join their inner lines
    into one run and pass it through inline(), so the near miss guard in
    render_section_body never sees them: a perfectly well formed figure line
    inside one of these was escaped and typeset as literal Markdown into the
    finished PDF while the build reported success. They cannot simply be taught
    to render one either. Each emits a paragraph (S.note and fineprint literally,
    the appendix through its clause text), and a <figure> is a block that may not
    live inside a <p>; the browser closes the paragraph early and the amber note
    box comes apart. Neither the 8.4 pt fine print nor the amber aside has a
    design register for an image. So the figure is refused, loudly, and the
    author is told where it can stand.
    """
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("!["):
            sys.exit(
                f"ERROR: a figure cannot be placed inside {where}.\n"
                f"       source line: {stripped}\n"
                "       Figures are block level. Move the figure out of the block\n"
                "       and put it on its own line in the section body, leaving\n"
                "       the block for its text."
            )


def render_figure(m, raw_line):
    """A matched figure line -> the Signal Stack figure block.

    The only inline style is the author's chosen width, carried as a custom
    property. Every visual rule (centring, margins, column fit, break-inside)
    lives in the Signal Stack stylesheet. The width applies to the image, not to
    the whole figure, so a 25 mm image still gets a full width caption instead of
    a 25 mm ribbon of text broken over half a dozen ragged lines.
    """
    alt = (m.group("alt") or "").strip()
    path = resolve_figure(m.group("target") or "", raw_line)
    uri = figure_data_uri(path, raw_line)
    width = figure_width(m.group("attrs"), raw_line)
    style = f' style="--fig-width:{width}"' if width else ""
    caption = f"<figcaption>{inline(alt)}</figcaption>" if alt else ""
    return (f'<figure class="figure">'
            f'<img{style} src="{uri}" alt="{attr(plain(alt))}">{caption}</figure>')


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
            # Lead-paragraph promotion removed (enshrined): the first paragraph of
            # the first section renders at the SAME size and colour as every other
            # body paragraph. Do not re-introduce a .lead promotion here; the larger,
            # darker opening paragraph read as a bug, not a feature. (lead_used and
            # first_section are retained for signature compatibility, now unused.)
            out.append(S.para(text))
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_para()
            i += 1
            continue

        # fenced code block  ``` ... ```   (checked first: nothing inside a
        # listing may be re-read as a table, a list, or a heading)
        if stripped.startswith("```"):
            flush_para()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            out.append(code_block(buf))
            continue

        # figure: a Markdown image alone on its line (checked before the generic
        # paragraph fallback, so it never gets swallowed into prose). A line that
        # opens with "![" and does not parse is a near miss, never prose: letting
        # it fall through typeset the literal Markdown into a finished customer
        # PDF with no error at all, so it stops the build instead.
        if stripped.startswith("!["):
            flush_para()
            fig = _FIGURE_LINE.match(stripped)
            if not fig:
                sys.exit(
                    f"ERROR: line looks like a figure but does not parse as one:\n"
                    f"       source line: {stripped}\n"
                    "       A line that starts with '![' must be a complete figure:\n"
                    "       ![Caption](path/to/image.png) with an optional {width=60%}\n"
                    "       or {width=90mm}. Wrap a path that nests parentheses in\n"
                    "       angle brackets: ![Caption](<img/label (1) (a).png>)."
                )
            out.append(render_figure(fig, line))
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
                reject_figure_in(inner, "a :::note fence")
                txt = inline(" ".join(x.strip() for x in inner if x.strip()))
                out.append(S.note("Note", txt))
            elif name == "small":
                reject_figure_in(inner, "a :::small fence")
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

        # headings inside a section: ## -> subhead, ### and deeper -> subsubhead.
        # ### used to render as block_eyebrow, a block LABEL with no top margin,
        # so a third-level heading collided with the paragraph above it.
        m = re.match(r"^(#{2,})\s+(.*)$", stripped)
        if m:
            flush_para()
            text = inline(m.group(2).strip())
            if len(m.group(1)) == 2:
                out.append(S.subhead(text))
            else:
                out.append(S.subsubhead(text))
            i += 1
            continue

        # blockquote -> fine print
        if stripped.startswith(">"):
            flush_para()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            reject_figure_in(buf, "a blockquote")
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
                mt = title_split(it)
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
                mt = title_split(rest)
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


def code_block(buf):
    """``` fenced block -> verbatim monospace listing.

    Escaped only, never passed through inline(): the whole point of a listing is
    that backticks, asterisks, pipes and backslashes stand for themselves. Blank
    leading and trailing lines are trimmed so the fence style in the source does
    not leak into the rendered block.
    """
    lines = list(buf)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '<pre class="code-block">' + esc("\n".join(lines)) + "</pre>"


# ---------------------------------------------------------------- appendix
def build_appendix(inner_lines):
    """:::appendix ... ::: -> Signature appendix().

    The first heading is the appendix title. Any ## / ### inside start a new
    clause (its heading is the clause heading); prose paragraphs accumulate into
    the current clause. Markers are left blank (the source carries no clause
    symbols to invent).
    """
    reject_figure_in(inner_lines, "a :::appendix fence")
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

    def consume_code_fence(idx, sink):
        """Copy a ``` fenced block verbatim into sink; return the index after it.

        The splitter must not read the inside of a listing: a shell or ini line
        beginning with '#' is a comment, not a new H1 section.
        """
        sink.append(body_lines[idx])
        idx += 1
        while idx < n and not body_lines[idx].strip().startswith("```"):
            sink.append(body_lines[idx])
            idx += 1
        if idx < n:
            sink.append(body_lines[idx])
            idx += 1
        return idx

    while i < n:
        stripped = body_lines[i].strip()

        # a listing at top level belongs to the preamble, verbatim
        if stripped.startswith("```"):
            i = consume_code_fence(i, preamble)
            continue

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
                if t.startswith("```"):
                    i = consume_code_fence(i, inner)
                    continue
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
    global SRC_DIR
    if len(sys.argv) != 3:
        sys.exit("Usage: build_report.py <input.md> <output.pdf>")
    src = Path(sys.argv[1])
    pdf = Path(sys.argv[2])

    # Figures are authored relative to the document, not to the shell's cwd.
    SRC_DIR = Path(os.path.abspath(str(src))).parent
    _FIGURE_URI_CACHE.clear()   # the cache is per document, never across builds

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

    eng, n = S.render_pdf(
        title,
        body_html,
        str(pdf),
        doc_kind_arg,
        doc_no_arg,
        extra_css=REPORT_CSS,
        watermark_opacity=REPORT_WATERMARK_OPACITY,
    )
    print(f"rendered -> {pdf} (engine {eng}, {n} pages)")
    print(f"wrote {pdf.with_suffix('.html')}")

    pages = "1,2" if n <= 2 else f"1,2,{n}"
    S.R.pdfcheck(str(pdf), pdf.stem, pages=pages)
    print(f"page_count: {n}")


if __name__ == "__main__":
    main()
