#!/usr/bin/env python3
"""Refuse to publish a tree that carries private data.

Exit 0 when the tree is publishable, 1 when it is not. Runs both as a pre-commit
hook and as a CI gate, so the same verdict applies in both places.

Two rule sets:

* Generic rules live here and need no configuration: real-looking email
  addresses, GUIDs, absolute home paths, and private-key blocks.
* Site-specific rules (your own name, your employer's customer names, internal
  hostnames) are deliberately NOT in this file, because this file is public and
  listing them here would publish exactly what it exists to catch. Put them, one
  regex per line, in whichever of these exists:

      $NUMACO_GATE_TERMS
      ~/.config/numaco-publish-gate/terms.txt

  That file stays on your machine and is never committed. Without it the gate
  still runs, it just cannot know that "Acme Corp" is a customer of yours.

Baseline: known-safe matches (invented sample contacts, a vendored library
author) go in a committed `.publish-allow`, one `<relpath>:<token>` per line. A
baseline entry silences one token in one file, never a whole rule, so a new leak
inside an already-baselined file still fails.
"""
import os
import re
import subprocess
import sys

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
             "dist", "build", ".ruff_cache", "vendor"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".woff", ".woff2", ".ttf",
            ".otf", ".ico", ".zip", ".lock", ".svg"}
BASELINE_NAME = ".publish-allow"

GENERIC_RULES = [
    ("absolute-home-path", re.compile(r"/(?:Users|home)/(?!me\b)[a-z][a-z0-9._-]{2,}", re.I)),
    ("guid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("real-email", re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I)),
]

ALLOW_LINE = [
    re.compile(r"/users/me\b", re.I),                              # Gmail REST path
    re.compile(r"example\.(com|org|net)", re.I),                   # doc placeholders
    re.compile(r"@(yourcompany|your-workspace|yourdomain|company)\b", re.I),
]

PLACEHOLDER_LOCAL = re.compile(
    r"^(you|your\w*|user|username|someone|somebody|name|first\.last|finance|support|"
    r"noreply|no-reply|admin|root|test|example|sample|placeholder|me)$", re.I)


def load_terms():
    """Site-specific regexes, from a file that is never committed."""
    path = os.environ.get("NUMACO_GATE_TERMS") or os.path.expanduser(
        "~/.config/numaco-publish-gate/terms.txt")
    if not os.path.exists(path):
        return [], path
    pats = []
    with open(path, errors="ignore") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                pats.append(re.compile(line, re.I))
            except re.error:
                pats.append(re.compile(re.escape(line), re.I))
    return pats, path


def load_baseline(root):
    allow = set()
    path = os.path.join(root, BASELINE_NAME)
    if not os.path.exists(path):
        return allow
    with open(path, errors="ignore") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            rel, _, tok = line.partition(":")
            if tok:
                allow.add((rel.strip(), tok.strip()))
    return allow


def email_is_placeholder(token):
    return bool(PLACEHOLDER_LOCAL.match(token.split("@", 1)[0]))


def publishable_files(root):
    """Relative paths of every file that could actually reach the public repo.

    Inside a git work tree that means tracked files plus untracked files that
    are not ignored, which is exactly what a push can carry. Build artifacts
    are ignored by definition, so a local build must never turn the gate red:
    the sample renderers write megabytes of HTML that no commit will ever
    contain, and scanning them reports leaks that cannot leak.

    Outside a git work tree (the pre-commit hook scans a temp directory of
    staged copies, and CI may scan an exported tree) fall back to walking
    everything, which is the safe direction to fail in.
    """
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            capture_output=True, check=True).stdout
        rels = [r.decode("utf-8", "surrogateescape") for r in out.split(b"\0") if r]
        if rels:
            return rels
    except (OSError, subprocess.CalledProcessError):
        pass
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            rels.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return rels


def scan(root, site_pats):
    rules = GENERIC_RULES + [("site-specific-term", p) for p in site_pats]
    hits = []
    for rel in publishable_files(root):
        parts = rel.split(os.sep)
        if any(p in SKIP_DIRS for p in parts[:-1]):
            continue
        fn = parts[-1]
        if fn == BASELINE_NAME or os.path.splitext(fn)[1].lower() in SKIP_EXT:
            continue
        path = os.path.join(root, rel)
        try:
            with open(path, "r", errors="ignore") as fh:
                for n, line in enumerate(fh, 1):
                    if any(p.search(line) for p in ALLOW_LINE):
                        continue
                    for kind, pat in rules:
                        for m in pat.finditer(line):
                            tok = m.group(0)
                            if kind == "real-email" and email_is_placeholder(tok):
                                continue
                            hits.append((rel, n, kind, tok))
        except (OSError, UnicodeDecodeError):
            continue
    return hits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = args[0] if args else "."
    site_pats, terms_path = load_terms()
    hits = scan(root, site_pats)

    if "--write-baseline" in sys.argv:
        uniq = sorted({(h[0], h[3], h[2]) for h in hits})
        with open(os.path.join(root, BASELINE_NAME), "w") as fh:
            fh.write("# Known-safe matches: one <relpath>:<token> per line, with a reason.\n")
            fh.write("# Anything NOT listed here fails the publish gate.\n")
            for rel, tok, kind in uniq:
                fh.write(f"{rel}:{tok}  # {kind}\n")
        print(f"baseline written: {len(uniq)} entries")
        return 0

    if not site_pats:
        print(f"note: no site-specific terms loaded (looked for {terms_path}); "
              f"generic rules still ran.", file=sys.stderr)

    baseline = load_baseline(root)
    hits = [h for h in hits if (h[0], h[3]) not in baseline]
    if not hits:
        print(f"PUBLISHABLE: no unbaselined private data under {root}")
        return 0

    by_kind = {}
    for rel, n, kind, tok in hits:
        by_kind.setdefault(kind, []).append((rel, n, tok))
    print(f"NOT PUBLISHABLE: {len(hits)} private-data hit(s) under {root}\n")
    for kind in sorted(by_kind, key=lambda k: -len(by_kind[k])):
        rows = by_kind[kind]
        print(f"  [{kind}] {len(rows)} hit(s)")
        for rel, n, tok in rows[:8]:
            print(f"    {rel}:{n}  {tok!r}")
        if len(rows) > 8:
            print(f"    ... and {len(rows) - 8} more")
        print()
    print(f"Fix the file, or if the match is genuinely safe add it to {BASELINE_NAME} "
          f"with a reason.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
