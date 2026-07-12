#!/usr/bin/env python3
"""
numaco-design shared renderer.

One place to turn branded HTML into PDF for every Numaco output type (slide decks,
SOWs, reports, and future timesheets/quotations/POs/invoices), plus the CoreGraphics
fidelity check so the PDF is verified through the engine macOS Preview actually uses.

Two modes:
  fixed : one HTML <section> == one fixed-size page (slide decks, 1920x1080).
  paged : flowing content reflowed across A4 pages by Paged.js (running header/footer,
          page numbers, table breaks). Self-contained and offline: the vendored
          paged.polyfill.js is inlined into the HTML head by paged_head().

CLI:
  numaco_render.py render   --html doc.html --pdf doc.pdf [--mode paged|fixed]
  numaco_render.py pdfcheck --pdf doc.pdf [--name doc] [--pages 1,2,3]

Why this exists: Chrome renders the PDF, so any Chromium-based check agrees with it
and hides PDFKit-only bugs (transform, mask-image, aspect-ratio, % sizing on
decoration). pdfcheck rasterises through CoreGraphics (sips) so we see what Preview
shows. Never trust `qlmanage -t` thumbnails or the naive PDF rasteriser.
"""
import argparse, base64, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND_CORE = HERE.parent / "brand-core"
PAGED_POLYFILL = HERE / "vendor" / "paged.polyfill.js"

CHROME_FLAGS = ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run"]


# ---------- chrome plumbing (from build_deck.py: Chrome 150 renders then fails to exit) ----------
def _run_chrome_until(chrome, extra_args, ready, timeout=90, poll=0.4, stdout=None):
    with tempfile.TemporaryDirectory() as td:
        args = [chrome] + CHROME_FLAGS + [f"--user-data-dir={td}"] + extra_args
        out = open(stdout, "wb") if stdout else subprocess.DEVNULL
        p = subprocess.Popen(args, stdout=out, stderr=subprocess.DEVNULL)
        try:
            t0 = time.time()
            while time.time() - t0 < timeout:
                if p.poll() is not None:
                    break
                if ready():
                    break
                time.sleep(poll)
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
            if stdout:
                out.close()


def find_chrome():
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def data_uri_png(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


# ---------- shared brand core (inlined, offline) ----------
def brand_core_css():
    """Manrope font + design tokens, ready to inline in <style>."""
    font = (BRAND_CORE / "fonts" / "manrope.css").read_text()
    theme = (BRAND_CORE / "theme.css").read_text()
    return font + "\n" + theme


def logo_vars_css():
    parts = [":root{"]
    for name, fn in (("--logo-blue", "logo-blue.png"), ("--logo-white", "logo-white.png"),
                     ("--numaco-wordmark", "numaco_wordmark.png"), ("--numaco-watermark", "numaco_watermark.png"),
                     ("--numaco-watermark-light", "numaco_watermark_light.png")):
        f = BRAND_CORE / fn
        if f.exists():
            parts.append(f'{name}:url("{data_uri_png(f)}");')
    parts.append("}")
    return "".join(parts)


def doc_watermark_css(size_mm=98, image="numaco_watermark_light.png"):
    """The shared page watermark: the big geometric N monogram anchored FLUSH to the
    top-right corner of every content page (edges touching the page top and right),
    faint, and suppressed on the cover. Matches the Numaco letterhead template. Returns
    an @page block to inject into the document <style> (needs the embedded data URI)."""
    f = BRAND_CORE / image
    if not f.exists():
        return ""
    uri = data_uri_png(f)
    return (
        "@page { background-image: url(%s); background-repeat: no-repeat; "
        "background-position: right top; background-size: %dmm auto; }\n"
        "@page cover { background-image: none; }"
    ) % (uri, size_mm)


def paged_head():
    """Inlined Paged.js polyfill + a completion sentinel, for the document <head>."""
    poly = PAGED_POLYFILL.read_text()
    cfg = ("<script>window.PagedConfig={auto:true,after:function(){"
           "try{document.documentElement.setAttribute('data-paged-done','1');}catch(e){}}};</script>")
    return cfg + "\n<script>" + poly + "</script>"


# ---------- render: fixed-page (slide decks) ----------
def render_fixed(html_path, pdf_path, width="1920px", height="1080px"):
    try:
        import playwright  # noqa
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page()
            pg.goto(Path(html_path).resolve().as_uri())
            pg.emulate_media(media="print")
            pg.pdf(path=str(pdf_path), width=width, height=height, print_background=True,
                   margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
            b.close()
        return "playwright"
    except Exception:
        pass
    chrome = find_chrome()
    if not chrome:
        sys.exit("ERROR: no render engine (install Google Chrome or playwright).")
    Path(pdf_path).unlink(missing_ok=True)
    st = {"size": -1, "stable": 0}

    def ready():
        if not Path(pdf_path).exists():
            return False
        s = Path(pdf_path).stat().st_size
        st["stable"] = st["stable"] + 1 if (s > 0 and s == st["size"]) else 0
        st["size"] = s
        return st["stable"] >= 2

    _run_chrome_until(chrome, ["--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
                               Path(html_path).resolve().as_uri()], ready, timeout=90)
    if not Path(pdf_path).exists() or Path(pdf_path).stat().st_size == 0:
        sys.exit("ERROR: Chrome produced no PDF.")
    return "chrome"


# ---------- render: paged (documents via Paged.js) ----------
def render_paged(html_path, pdf_path, budget_ms=90000):
    """Primary path: drive Chrome via puppeteer-core (node), waiting for Paged.js to
    finish pagination (the data-paged-done sentinel) before printing. This is what
    pagedjs-cli does and is the only reliable way; `chrome --print-to-pdf` races
    Paged.js and yields a single un-paginated page."""
    node = shutil.which("node")
    chrome = find_chrome()
    script = HERE / "render_paged.js"
    have_pptr = (HERE / "node_modules" / "puppeteer-core").exists()
    if node and chrome and script.exists() and have_pptr:
        Path(pdf_path).unlink(missing_ok=True)
        try:
            r = subprocess.run(
                [node, str(script), str(Path(html_path).resolve()), str(Path(pdf_path).resolve()), chrome, str(budget_ms)],
                capture_output=True, text=True, timeout=max(180, budget_ms // 1000 + 120))
            for line in (r.stderr or "").strip().splitlines():
                print("  [pagedjs] " + line)
            if Path(pdf_path).exists() and Path(pdf_path).stat().st_size > 0:
                return "puppeteer+pagedjs"
            print("paged render via puppeteer produced no PDF; trying Chrome CLI fallback")
        except Exception as e:
            print(f"puppeteer paged render failed ({e}); trying Chrome CLI fallback")
    # fallback: Chrome CLI with a virtual-time budget (less reliable for Paged.js completion)
    if not chrome:
        sys.exit("ERROR: Google Chrome required for paged render.")
    Path(pdf_path).unlink(missing_ok=True)
    st = {"size": -1, "stable": 0}

    def ready():
        if not Path(pdf_path).exists():
            return False
        s = Path(pdf_path).stat().st_size
        st["stable"] = st["stable"] + 1 if (s > 0 and s == st["size"]) else 0
        st["size"] = s
        return st["stable"] >= 3

    _run_chrome_until(chrome, [
        "--no-pdf-header-footer",
        f"--virtual-time-budget={budget_ms}",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf_path}",
        Path(html_path).resolve().as_uri(),
    ], ready, timeout=max(150, budget_ms // 1000 + 90))
    if not Path(pdf_path).exists() or Path(pdf_path).stat().st_size == 0:
        sys.exit("ERROR: Chrome produced no paged PDF.")
    return "chrome+pagedjs-cli-fallback"


# ---------- verification ----------
def pdf_page_count(pdf_path):
    import re
    d = Path(pdf_path).read_bytes()
    n = len(re.findall(rb"/Type\s*/Page(?![s])", d))
    return n


def _which_qpdf():
    q = shutil.which("qpdf")
    if q:
        return q
    for c in ("/opt/homebrew/bin/qpdf", "/usr/local/bin/qpdf"):
        if Path(c).exists():
            return c
    return None


def _extract_page(pdf_path, page, out_pdf):
    """Extract a single page to its own PDF using qpdf if available (for CoreGraphics of interior pages)."""
    qpdf = _which_qpdf()
    if not qpdf:
        return False
    try:
        subprocess.run([qpdf, "--empty", "--pages", str(pdf_path), str(page), "--", str(out_pdf)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
        return Path(out_pdf).exists()
    except Exception:
        return False


def pdfcheck(pdf_path, name="doc", pages="1"):
    """Rasterise the requested pages through CoreGraphics (sips) = macOS Preview's engine."""
    sips = shutil.which("sips")
    outdir = Path(tempfile.gettempdir()) / "numaco-design-pdfcheck"
    outdir.mkdir(parents=True, exist_ok=True)
    n = pdf_page_count(pdf_path)
    print(f"pdfcheck   -> pages: {n}")
    if not sips:
        print("pdfcheck   -> sips not found; open the PDF in macOS Preview to verify.")
        return
    want = [p.strip() for p in str(pages).split(",") if p.strip()]
    for p in want:
        png = outdir / f"{name}-p{p}-coregraphics.png"
        png.unlink(missing_ok=True)
        src = pdf_path
        tmp = None
        if p != "1":
            tmp = outdir / f"{name}-p{p}.pdf"
            if _extract_page(pdf_path, p, tmp):
                src = tmp
            else:
                print(f"pdfcheck   -> page {p}: qpdf not available to split; skipping (install qpdf for interior-page checks).")
                continue
        try:
            subprocess.run([sips, "-s", "format", "png", str(src), "--out", str(png)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
            if png.exists() and png.stat().st_size > 0:
                print(f"pdfcheck   -> {png}")
        except Exception as e:
            print(f"pdfcheck   -> page {p}: sips failed ({e}).")
    print("             CoreGraphics renders (macOS Preview engine). Inspect against the HTML.")
    print("             Verify the full PDF in Preview; do NOT trust Chrome-only or `qlmanage -t`.")


def main():
    ap = argparse.ArgumentParser(description="numaco-design shared renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--html", required=True); r.add_argument("--pdf", required=True)
    r.add_argument("--mode", default="paged", choices=["paged", "fixed"])
    r.add_argument("--width", default="1920px"); r.add_argument("--height", default="1080px")
    r.add_argument("--budget", type=int, default=40000)
    r.add_argument("--check-pages", default="1")
    pc = sub.add_parser("pdfcheck")
    pc.add_argument("--pdf", required=True); pc.add_argument("--name", default="doc"); pc.add_argument("--pages", default="1")
    a = ap.parse_args()
    if a.cmd == "render":
        eng = render_fixed(a.html, a.pdf, a.width, a.height) if a.mode == "fixed" else render_paged(a.html, a.pdf, a.budget)
        print(f"rendered   -> {a.pdf}  (mode {a.mode}, engine {eng})")
        pdfcheck(a.pdf, Path(a.pdf).stem, a.check_pages)
    elif a.cmd == "pdfcheck":
        pdfcheck(a.pdf, a.name, a.pages)


if __name__ == "__main__":
    main()
