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
  numaco_render.py doctor

Self-installing toolchain: nothing needs to be preinstalled beyond Node.js (and even
that gets a copy-paste install command when absent). On first use the renderer runs
npm ci in shared/render to materialise the committed lockfile, and resolves a browser
through one ladder: an explicit env override, a system Chrome/Chromium/Edge/Brave, a
private build previously downloaded under shared/render/.browsers, or (last resort) a
fresh chrome@stable download via @puppeteer/browsers. The resolved executable is
cached in shared/render/.browser-path and revalidated on every run. `doctor` performs
the whole preflight and exits 0 only when a render could succeed.

Why this exists: Chrome renders the PDF, so any Chromium-based check agrees with it
and hides PDFKit-only bugs (transform, mask-image, aspect-ratio, % sizing on
decoration). pdfcheck rasterises through CoreGraphics (sips) so we see what Preview
shows. Never trust `qlmanage -t` thumbnails or the naive PDF rasteriser.
"""
import argparse, base64, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND_CORE = HERE.parent / "brand-core"
PAGED_POLYFILL = HERE / "vendor" / "paged.polyfill.js"
# Paged.js handlers we add on top of the untouched vendored polyfill. Inlined by
# paged_head() after the polyfill, in order. Keeping them out of vendor/ means the
# polyfill stays a pristine drop-in that can be re-vendored without losing patches.
PAGED_PATCHES = [HERE / "repeat_table_header.js"]

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


# ---------- self-installing toolchain: node deps bootstrap + browser resolution ladder ----------
# Env vars:
#   PUPPETEER_EXECUTABLE_PATH / NUMACO_RENDER_BROWSER : explicit browser executable override.
#   NUMACO_RENDER_BROWSERS_DIR       : test only; relocates the private-build download dir
#                                      (and its cache file) away from shared/render/.browsers.
#   NUMACO_RENDER_NO_SYSTEM_BROWSERS : test only; pretends no system browser exists so the
#                                      ladder exercises the download path.
NODE_MODULES = HERE / "node_modules"
DEFAULT_BROWSERS_DIR = HERE / ".browsers"
BROWSER_CACHE_NAME = ".browser-path"


def _node_install_hint():
    if sys.platform == "darwin":
        return "brew install node"
    if os.name == "nt":
        return "winget install OpenJS.NodeJS.LTS"
    return "sudo apt-get install -y nodejs npm    # Debian/Ubuntu; use your distro's package manager otherwise"


def _missing_node_error():
    return (
        "ERROR: Node.js (node and npm) was not found on PATH; the renderer needs it to drive the browser.\n"
        "Install it with the platform package manager, then rerun the same command:\n"
        "  " + _node_install_hint()
    )


def node_deps_ok():
    return (NODE_MODULES / "puppeteer-core").is_dir()


def ensure_node_modules():
    """Bootstrap the Node render dependencies on first use: npm ci (npm install as
    fallback) inside shared/render whenever node_modules is missing or incomplete."""
    if node_deps_ok():
        return
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        sys.exit(_missing_node_error())
    print("bootstrap  -> node_modules missing; installing render dependencies (npm, one time)...")
    last = ""
    for label, cmd in (("npm ci", [npm, "ci", "--no-fund", "--no-audit"]),
                       ("npm install", [npm, "install", "--no-fund", "--no-audit"])):
        try:
            r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=600)
        except Exception as e:
            last = f"{label} did not run ({e})"
            print("bootstrap  -> " + last)
            continue
        if r.returncode == 0 and node_deps_ok():
            print(f"bootstrap  -> {label} OK; node_modules ready.")
            return
        last = "\n".join(((r.stderr or "") + "\n" + (r.stdout or "")).strip().splitlines()[-4:])
        print(f"bootstrap  -> {label} failed (exit {r.returncode})"
              + ("; falling back to npm install..." if label == "npm ci" else "."))
    sys.exit("ERROR: could not install the Node render dependencies in " + str(HERE)
             + "\nLast npm output:\n" + last
             + "\nFix the npm error above, then rerun the same command.")


def _browsers_dir():
    env = os.environ.get("NUMACO_RENDER_BROWSERS_DIR")
    return Path(env).expanduser().resolve() if env else DEFAULT_BROWSERS_DIR


def _browser_cache_file():
    env = os.environ.get("NUMACO_RENDER_BROWSERS_DIR")
    return (Path(env).expanduser().resolve() / BROWSER_CACHE_NAME) if env else (HERE / BROWSER_CACHE_NAME)


def _is_under(path, root):
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except Exception:
        return False


def find_system_browser():
    """Standard install locations of Chrome, Chromium, Edge, and Brave on macOS,
    Windows, and Linux, then PATH lookups. Returns None when nothing is installed."""
    if os.environ.get("NUMACO_RENDER_NO_SYSTEM_BROWSERS"):
        return None  # test hook: behave as if no system browser existed
    candidates = []
    if sys.platform == "darwin":
        rel = ("Google Chrome.app/Contents/MacOS/Google Chrome",
               "Chromium.app/Contents/MacOS/Chromium",
               "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "Brave Browser.app/Contents/MacOS/Brave Browser")
        for root in (Path("/Applications"), Path.home() / "Applications"):
            candidates += [root / r for r in rel]
    elif os.name == "nt":
        rel = (r"Google\Chrome\Application\chrome.exe",
               r"Chromium\Application\chrome.exe",
               r"Microsoft\Edge\Application\msedge.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe")
        for root in (os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")):
            if root:
                candidates += [Path(root) / r for r in rel]
    else:
        candidates += [Path(p) for p in (
            "/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium",
            "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
            "/usr/bin/brave-browser", "/opt/google/chrome/chrome", "/snap/bin/chromium")]
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _find_downloaded_browser(browsers_dir):
    """A private build previously installed by @puppeteer/browsers under browsers_dir."""
    if not Path(browsers_dir).is_dir():
        return None
    if sys.platform == "darwin":
        pats = ("chrome/*/chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",)
    elif os.name == "nt":
        pats = ("chrome/*/chrome-win64/chrome.exe", "chrome/*/chrome-win32/chrome.exe")
    else:
        pats = ("chrome/*/chrome-linux64/chrome",)
    hits = []
    for pat in pats:
        hits += sorted(Path(browsers_dir).glob(pat))
    return str(hits[-1]) if hits else None


def _validate_browser(exe):
    """Confirm the executable actually runs (a partially extracted download exists on
    disk but cannot start). Skipped on Windows, where chrome.exe --version is a no-op."""
    if os.name == "nt":
        return Path(exe).exists()
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _repair_downloaded_browser(browsers_dir, exe):
    """The @puppeteer/browsers CLI unpacks zips with the extract-zip npm package, which
    on some Node versions stalls silently and leaves a partial app bundle plus the
    downloaded archive behind. Re-extract that archive with the system tools (unzip,
    then bsdtar) over the same install dir, and return True when the executable runs."""
    exe = Path(exe)
    chrome_dir = Path(browsers_dir) / "chrome"
    target = exe
    while target.parent != chrome_dir:
        if target.parent == target:
            return False
        target = target.parent
    zips = sorted(chrome_dir.glob("*.zip"))
    if not zips:
        return False
    unzip, tar = shutil.which("unzip"), shutil.which("tar")
    for z in zips:
        for cmd in ([unzip, "-o", "-qq", str(z), "-d", str(target)] if unzip else None,
                    [tar, "-xf", str(z), "-C", str(target)] if tar else None):
            if not cmd:
                continue
            print(f"browser    -> repairing a partially extracted download ({z.name}) with {Path(cmd[0]).name}...")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except Exception:
                continue
            if r.returncode == 0 and _validate_browser(exe):
                z.unlink(missing_ok=True)
                return True
    return _validate_browser(exe)


def _download_browser(browsers_dir):
    """Last resort: download a chrome@stable private build via the @puppeteer/browsers
    CLI (pinned by the committed lockfile) into browsers_dir, and return its executable."""
    ensure_node_modules()
    node = shutil.which("node")
    cli = NODE_MODULES / "@puppeteer" / "browsers" / "lib" / "cjs" / "main-cli.js"
    if node and cli.exists():
        cmd = [node, str(cli)]
    else:
        npx = shutil.which("npx")
        if not npx:
            sys.exit(_missing_node_error())
        cmd = [npx, "--yes", "@puppeteer/browsers"]
    cmd += ["install", "chrome@stable", "--path", str(browsers_dir), "--format", "{{path}}"]
    Path(browsers_dir).mkdir(parents=True, exist_ok=True)
    print("browser    -> no browser found anywhere; downloading a private chrome@stable build")
    print(f"              into {browsers_dir} (one time, roughly 150 MB)...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except Exception as e:
        sys.exit(f"ERROR: the Chrome download did not run ({e}). Retry, or install Google Chrome and rerun.")
    if r.returncode != 0:
        tail = "\n".join(((r.stderr or "") + "\n" + (r.stdout or "")).strip().splitlines()[-4:])
        sys.exit("ERROR: the Chrome download failed.\n" + tail
                 + "\nRetry on a working network, or install Google Chrome and rerun.")
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    exe = lines[-1] if lines and Path(lines[-1]).exists() else _find_downloaded_browser(browsers_dir)
    if not exe:
        sys.exit("ERROR: the Chrome download reported success but no executable was found under " + str(browsers_dir))
    if _validate_browser(exe) or _repair_downloaded_browser(browsers_dir, exe):
        return exe
    sys.exit("ERROR: the downloaded Chrome build at " + str(exe)
             + " does not start (incomplete extraction). Delete " + str(browsers_dir)
             + " and retry, or install Google Chrome and rerun.")


def resolve_browser(allow_download=True):
    """The single browser resolution ladder used by every render path:
      (a) PUPPETEER_EXECUTABLE_PATH or NUMACO_RENDER_BROWSER, if set,
          then the cached path from a previous run (revalidated);
      (b) a system Chrome, Chromium, Edge, or Brave;
      (c) a private build already downloaded under shared/render/.browsers;
      (d) last resort: download chrome@stable there via @puppeteer/browsers.
    The resolved path is persisted to shared/render/.browser-path."""
    browsers_dir = _browsers_dir()
    cache = _browser_cache_file()

    def remember(path, source):
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(str(path) + "\n", encoding="utf-8")
        except OSError:
            pass
        print(f"browser    -> {path}  (via {source})")
        return str(path)

    for var in ("PUPPETEER_EXECUTABLE_PATH", "NUMACO_RENDER_BROWSER"):
        v = os.environ.get(var)
        if v:
            if Path(v).exists():
                return remember(v, "env " + var)
            sys.exit(f"ERROR: {var} points at {v!r} but nothing exists there. Fix or unset it, then rerun.")
    if cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        usable = bool(cached) and Path(cached).exists()
        if usable and os.environ.get("NUMACO_RENDER_NO_SYSTEM_BROWSERS") and not _is_under(cached, browsers_dir):
            usable = False  # the test hook must not be satisfied by a cached system browser
        if usable:
            print(f"browser    -> {cached}  (via cache {cache.name})")
            return cached
    b = find_system_browser()
    if b:
        return remember(b, "system install")
    b = _find_downloaded_browser(browsers_dir)
    if b and (_validate_browser(b) or _repair_downloaded_browser(browsers_dir, b)):
        return remember(b, "downloaded private build")
    if allow_download:
        return remember(_download_browser(browsers_dir), "fresh chrome@stable download")
    return None


def find_chrome():
    """Back-compat detection: the ladder without the download step (None when absent)."""
    return resolve_browser(allow_download=False)


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
    """Inlined Paged.js polyfill + our handlers + a completion sentinel, for <head>.

    Order is load-bearing. The handler script must come AFTER the polyfill body,
    because `window.Paged` only exists once the polyfill has executed, and BEFORE
    pagination starts. Both hold here: our script is a synchronous, parser-blocking
    <script> in <head>, so it runs while document.readyState is still "loading",
    which is before the polyfill's own readyState-gated auto-run resolves. Paged.js
    reads registeredHandlers later still, inside Previewer.preview(), so a push at
    head-parse time is always picked up.
    """
    poly = PAGED_POLYFILL.read_text()
    cfg = ("<script>window.PagedConfig={auto:true,after:function(){"
           "try{document.documentElement.setAttribute('data-paged-done','1');}catch(e){}}};</script>")
    head = cfg + "\n<script>" + poly + "</script>"
    for patch in PAGED_PATCHES:
        if patch.exists():
            head += "\n<script>" + patch.read_text() + "</script>"
    return head


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
    chrome = resolve_browser()
    if not chrome:
        sys.exit("ERROR: no render engine (no browser could be resolved).")
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
    if not node:
        sys.exit(_missing_node_error())
    ensure_node_modules()
    chrome = resolve_browser()
    script = HERE / "render_paged.js"
    if chrome and script.exists() and node_deps_ok():
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


def doctor():
    """Preflight the whole toolchain: report node and npm, ensure node_modules (running
    the bootstrap), resolve the browser through the ladder (downloading when truly
    nothing is found), print every resolved path, and exit 0 only when a render could
    succeed on this machine."""
    print("numaco-design renderer doctor")
    print(f"platform   -> {sys.platform}")
    failures = []
    node, npm = shutil.which("node"), shutil.which("npm")
    for label, exe in (("node", node), ("npm", npm)):
        if exe:
            try:
                v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
            except Exception:
                v = "version check failed"
            print(f"{label:<10} -> {v}  ({exe})")
        else:
            print(f"{label:<10} -> MISSING; install it with:  {_node_install_hint()}")
    if not node:
        failures.append("Node.js is missing. Run:  " + _node_install_hint() + "  then rerun the doctor.")
    if not node_deps_ok() and node and npm:
        try:
            ensure_node_modules()
        except SystemExit as e:
            failures.append(str(e))
    if node_deps_ok():
        try:
            v = json.loads((NODE_MODULES / "puppeteer-core" / "package.json").read_text(encoding="utf-8"))["version"]
        except Exception:
            v = "?"
        print(f"deps       -> {NODE_MODULES}  (puppeteer-core {v})")
    else:
        print(f"deps       -> MISSING ({NODE_MODULES})")
        if not (node and npm):
            failures.append("The Node render dependencies are not installed; install Node.js first, then rerun the doctor.")
    assets = [("script", HERE / "render_paged.js"), ("polyfill", PAGED_POLYFILL)]
    assets += [("patch", p) for p in PAGED_PATCHES]
    for label, p in assets:
        if p.exists():
            print(f"{label:<10} -> {p}")
        else:
            print(f"{label:<10} -> MISSING ({p})")
            failures.append(f"{p} is missing; reinstall or update the numaco-design plugin.")
    try:
        resolve_browser(allow_download=True)
    except SystemExit as e:
        failures.append(str(e))
    if failures:
        print("doctor     -> NOT READY:")
        for f in failures:
            for line in str(f).splitlines():
                print("              " + line)
        sys.exit(1)
    print("doctor     -> OK: the renderer can produce PDFs on this machine.")


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
    sub.add_parser("doctor", help="preflight the toolchain: node, npm deps, browser ladder")
    a = ap.parse_args()
    if a.cmd == "render":
        eng = render_fixed(a.html, a.pdf, a.width, a.height) if a.mode == "fixed" else render_paged(a.html, a.pdf, a.budget)
        print(f"rendered   -> {a.pdf}  (mode {a.mode}, engine {eng})")
        pdfcheck(a.pdf, Path(a.pdf).stem, a.check_pages)
    elif a.cmd == "pdfcheck":
        pdfcheck(a.pdf, a.name, a.pages)
    elif a.cmd == "doctor":
        doctor()


if __name__ == "__main__":
    main()
