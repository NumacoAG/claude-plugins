#!/usr/bin/env python3
"""
numaco-slide-deck build tool.

Pipeline:
  1. assemble : wrap a slides-body fragment into a self-contained deck.html
                (inlines theme + font + logos + patterns + deck CSS, plus a
                 tiny on-screen viewer/nav and an overflow checker).
  2. check    : detect slides whose content overflows the 1920x1080 canvas.
  3. render   : print deck.html to PDF, one 1920x1080 landscape page per slide.
  4. build    : assemble + check + render in one go (the usual entry point).

Render engine: Playwright/Chromium if installed, else system Google Chrome
headless. No network access; all assets are inlined.

Usage:
  build_deck.py build   --slides slides.html --outdir OUT --title "Deck title" [--style numaco-standard-blue]
  build_deck.py assemble --slides slides.html --out deck.html --title "..."   [--style ...]
  build_deck.py check   --html deck.html
  build_deck.py render  --html deck.html --pdf deck.pdf
"""
import argparse, base64, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

CHROME_FLAGS = ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run"]


def _run_chrome_until(chrome, extra_args, ready, timeout=45, poll=0.4, stdout=None):
    """Launch Chrome, poll until ready() is true (artifact produced), then kill it.
    Chrome 150 headless can render its output and then fail to exit, so we never
    wait on its exit code: we wait for the artifact and terminate."""
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

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"

VIEWER_JS = r"""
(function () {
  var canvas = document.querySelector('.deck-canvas');
  var slides = canvas ? Array.prototype.slice.call(canvas.querySelectorAll(':scope > section')) : [];
  if (!slides.length) return;
  var i = 0;

  function label(s, n) {
    var t = s.getAttribute('data-title');
    if (!t) { var h = s.querySelector('h1,h2,h3'); t = h ? h.textContent.trim().slice(0, 40) : ('slide ' + n); }
    return t;
  }

  // ---- overflow check ----
  // Sections keep their real display type (grid stays grid) because they are
  // hidden with visibility, not display:none. We only neutralise the canvas
  // scale so getBoundingClientRect returns true 1:1 pixels, then measure
  // in-flow content (absolute decoration like watermark/chrome is skipped).
  function runOverflow() {
    var prevT = canvas.style.transform;
    canvas.style.transform = 'none';
    var over = [];
    slides.forEach(function (s, n) {
      var r = s.getBoundingClientRect(), maxB = r.top, maxR = r.left;
      (function walk(el) {
        for (var c = el.firstElementChild; c; c = c.nextElementSibling) {
          var st = getComputedStyle(c);
          if (st.position === 'absolute' || st.position === 'fixed' || st.display === 'none') continue;
          var b = c.getBoundingClientRect();
          if (b.width || b.height) { if (b.bottom > maxB) maxB = b.bottom; if (b.right > maxR) maxR = b.right; }
          walk(c);
        }
      })(s);
      if ((maxB - r.bottom) > 6 || (maxR - r.right) > 6) { s.setAttribute('data-overflow', '1'); over.push((n + 1) + ':' + label(s, n + 1)); }
      else { s.removeAttribute('data-overflow'); }
    });
    canvas.style.transform = prevT;
    document.documentElement.setAttribute('data-deck-overflow', over.join(' | '));
  }
  // Measure once the embedded font is applied (fallback metrics over-report),
  // and again on a short timer so a headless dump-dom captures a font-accurate result.
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(runOverflow); }
  else { runOverflow(); }
  setTimeout(runOverflow, 500);

  // ---- on-screen viewer: scale the 1920x1080 canvas to the viewport ----
  function fit() {
    var s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    canvas.style.transform = 'scale(' + s.toFixed(4) + ')';
    canvas.style.left = Math.max(0, (window.innerWidth - 1920 * s) / 2) + 'px';
    canvas.style.top = Math.max(0, (window.innerHeight - 1080 * s) / 2) + 'px';
  }
  function show(n) {
    i = (n + slides.length) % slides.length;
    slides.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
    var c = document.getElementById('deckCnt'); if (c) c.textContent = (i + 1) + ' / ' + slides.length;
  }
  window.addEventListener('resize', fit);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { show(i + 1); e.preventDefault(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { show(i - 1); e.preventDefault(); }
  });
  var prev = document.getElementById('deckPrev'), next = document.getElementById('deckNext');
  if (prev) prev.addEventListener('click', function () { show(i - 1); });
  if (next) next.addEventListener('click', function () { show(i + 1); });
  fit(); show(0);
})();
"""

NAV_HTML = (
  '<div class="deck-nav">'
  '<button id="deckPrev" aria-label="Previous">&#8249;</button>'
  '<span class="cnt" id="deckCnt">1 / 1</span>'
  '<button id="deckNext" aria-label="Next">&#8250;</button>'
  '</div>'
)


def data_uri_png(path: Path) -> str:
    b = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/png;base64," + b


def assemble(slides_path: Path, out_path: Path, title: str, style: str) -> Path:
    style_dir = ASSETS / style
    if not style_dir.is_dir():
        sys.exit(f"ERROR: unknown style '{style}'. Available: " + ", ".join(p.name for p in ASSETS.iterdir() if p.is_dir()))

    theme = (style_dir / "theme.css").read_text()
    patterns = (style_dir / "patterns.css").read_text()
    deck = (style_dir / "deck.css").read_text()
    font = (style_dir / "fonts" / "manrope.css").read_text()

    logo_vars = ":root{"
    for name, fn in (("--logo-blue", "logo-blue.png"), ("--logo-white", "logo-white.png")):
        f = style_dir / fn
        if f.exists():
            logo_vars += f'{name}:url("{data_uri_png(f)}");'
    logo_vars += "}"

    body = slides_path.read_text()
    # accept either a full-body fragment or already-wrapped .deck
    if '<section' not in body:
        sys.exit("ERROR: slides file has no <section class=\"slide\"> elements.")

    css = "\n".join([font, theme, logo_vars, patterns, deck])
    html = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n"
        f"<style>\n{css}\n</style>\n"
        "</head>\n"
        "<body>\n"
        "<deck-stage><div class=\"deck-canvas\">\n"
        f"{body}\n"
        "</div></deck-stage>\n"
        f"{NAV_HTML}\n"
        f"<script>{VIEWER_JS}</script>\n"
        "</body>\n</html>\n"
    )
    out_path.write_text(html)
    print(f"assembled  -> {out_path}  ({len(html)//1024} KB, style '{style}')")
    return out_path


# ---------------- render engines ----------------

def find_chrome() -> str | None:
    cands = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in cands:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def have_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def render_playwright(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_path.resolve().as_uri())
        pg.emulate_media(media="print")
        pg.pdf(path=str(pdf_path), width="1920px", height="1080px", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    print(f"rendered   -> {pdf_path}  (engine: playwright)")


def render_chrome(html_path: Path, pdf_path: Path, chrome: str) -> None:
    if pdf_path.exists():
        pdf_path.unlink()
    state = {"size": -1, "stable": 0}

    def ready():
        if not pdf_path.exists():
            return False
        sz = pdf_path.stat().st_size
        state["stable"] = state["stable"] + 1 if (sz > 0 and sz == state["size"]) else 0
        state["size"] = sz
        return state["stable"] >= 2  # PDF written and size steady across polls

    _run_chrome_until(chrome, ["--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()], ready, timeout=60)
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        sys.exit("ERROR: Chrome did not produce a PDF.")
    print(f"rendered   -> {pdf_path}  (engine: chrome headless)")


def render(html_path: Path, pdf_path: Path) -> None:
    if have_playwright():
        try:
            render_playwright(html_path, pdf_path)
            return
        except Exception as e:
            print(f"playwright render failed ({e}); falling back to Chrome")
    chrome = find_chrome()
    if not chrome:
        sys.exit("ERROR: no render engine. Install Playwright (pip install playwright && playwright install chromium) or Google Chrome.")
    render_chrome(html_path, pdf_path, chrome)


# ---------------- overflow check ----------------

def check_overflow(html_path: Path) -> list[str]:
    if have_playwright():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page()
                pg.goto(html_path.resolve().as_uri())
                val = pg.evaluate("() => document.documentElement.getAttribute('data-deck-overflow') || ''")
                b.close()
            return [x for x in val.split(" | ") if x]
        except Exception:
            pass
    chrome = find_chrome()
    if not chrome:
        print("WARN: no engine for overflow check; skipping.")
        return []
    fd, tmp = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    dom = Path(tmp)

    def ready():
        try:
            return b"data-deck-overflow=" in dom.read_bytes()
        except Exception:
            return False

    _run_chrome_until(chrome, ["--virtual-time-budget=4000", "--dump-dom", html_path.resolve().as_uri()], ready, timeout=40, stdout=str(dom))
    text = dom.read_text(errors="ignore")
    dom.unlink(missing_ok=True)
    m = re.search(r'data-deck-overflow="([^"]*)"', text)
    if not m:
        print("WARN: overflow marker not found (render engine may not have run scripts).")
        return []
    raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&#124;", "|")
    return [x.strip() for x in raw.split(" | ") if x.strip()]


def report_overflow(over: list[str]) -> None:
    if over:
        print("OVERFLOW on " + str(len(over)) + " slide(s):")
        for o in over:
            print("   ! " + o)
        print("Trim content or split these slides before shipping the PDF.")
    else:
        print("overflow   -> none, all slides fit 1920x1080.")


# ---------------- PDF fidelity check (CoreGraphics / PDFKit) ----------------

def pdfcheck(pdf_path: Path, name: str = "deck") -> None:
    """Rasterise the cover (page 1) via CoreGraphics, the engine macOS Preview and
    Quick Look use, so the PDF is verified the way it will actually be viewed.

    Chromium renders the PDF, and Chromium-based rasterisers then agree with it,
    which hides PDFKit-only regressions: a CSS transform, mask-image, aspect-ratio,
    or percentage size on a decorative layer can render differently in Preview than
    in Chrome. The cover (page 1) is the most decoration-heavy archetype and where
    these bugs surface. This never fails the build; it emits an image to eyeball
    against the HTML. (Quick Look thumbnails via `qlmanage -t` are NOT faithful and
    must not be used as the oracle; sips rasterises through CoreGraphics.)
    """
    sips = shutil.which("sips")
    if not sips:
        print("pdfcheck   -> skipped (sips not found; open the PDF in macOS Preview to verify)")
        return
    outdir = Path(tempfile.gettempdir()) / "numaco-slide-deck-pdfcheck"
    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / f"{name}-cover-coregraphics.png"
    png.unlink(missing_ok=True)
    try:
        subprocess.run([sips, "-s", "format", "png", str(pdf_path), "--out", str(png)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
    except Exception as e:
        print(f"pdfcheck   -> could not rasterise via sips ({e}); open the PDF in macOS Preview to verify")
        return
    if png.exists() and png.stat().st_size > 0:
        print(f"pdfcheck   -> {png}")
        print("             CoreGraphics render of the cover, identical to macOS Preview / Quick Look.")
        print("             Inspect it against the HTML (and open the full PDF in Preview) before shipping;")
        print("             do NOT verify only in Chrome or with `qlmanage -t`, they can hide PDFKit bugs.")
    else:
        print("pdfcheck   -> sips produced no image; open the PDF in macOS Preview to verify")


# ---------------- CLI ----------------

def main() -> None:
    ap = argparse.ArgumentParser(description="numaco-slide-deck build tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("assemble"); a.add_argument("--slides", required=True); a.add_argument("--out", required=True); a.add_argument("--title", default="Numaco"); a.add_argument("--style", default="numaco-standard-blue")
    c = sub.add_parser("check"); c.add_argument("--html", required=True)
    r = sub.add_parser("render"); r.add_argument("--html", required=True); r.add_argument("--pdf", required=True)
    pc = sub.add_parser("pdfcheck"); pc.add_argument("--pdf", required=True); pc.add_argument("--name", default="deck")
    b = sub.add_parser("build"); b.add_argument("--slides", required=True); b.add_argument("--outdir", required=True); b.add_argument("--title", default="Numaco"); b.add_argument("--style", default="numaco-standard-blue"); b.add_argument("--name", default="deck")

    args = ap.parse_args()

    if args.cmd == "assemble":
        assemble(Path(args.slides), Path(args.out), args.title, args.style)
    elif args.cmd == "check":
        report_overflow(check_overflow(Path(args.html)))
    elif args.cmd == "render":
        render(Path(args.html), Path(args.pdf))
    elif args.cmd == "pdfcheck":
        pdfcheck(Path(args.pdf), args.name)
    elif args.cmd == "build":
        outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
        html = outdir / f"{args.name}.html"
        pdf = outdir / f"{args.name}.pdf"
        assemble(Path(args.slides), html, args.title, args.style)
        over = check_overflow(html)
        report_overflow(over)
        render(html, pdf)
        pdfcheck(pdf, args.name)
        print(f"\nDONE. Preview (HTML): open -a \"Google Chrome\" \"{html}\"   |   PDF: {pdf}")
        print("Verify the PDF in macOS Preview (see the pdfcheck image above); Chrome alone is not enough.")
        if over:
            sys.exit(3)  # non-zero so the caller notices overflow


if __name__ == "__main__":
    main()
