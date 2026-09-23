#!/usr/bin/env python3
"""dvsync: reconcile a small "tier 1" set of markdown docs between two vaults.

Two vaults hold the same project trees:

  laptop vault : ~/Code/<project>/...            (git versioned)
  mobile vault : <MOBILE_BASE>/<project>/...      (iCloud Obsidian, no git)

Only an explicit, registered set of files (the "tracked set", i.e. the tier 1
docs the user actually reads and reviews) is ever touched. Everything else in either
vault is ignored, never auto-deleted, never auto-synced.

State lives centrally (outside both trees) at:

  ~/.claude/dvsync/<project>/config.json   roots + tracked set
  ~/.claude/dvsync/<project>/base/<rel>    last-synced snapshot (3-way merge base)

The core operation is `sync`: for each tracked file it compares laptop (L),
mobile (M) and the stored base (B), then:

  L == M                  : in sync; refresh base if both moved together
  only L changed vs base  : mirror L -> M
  only M changed vs base  : mirror M -> L
  both changed (L != M)   : 3-way UNION merge(base=B, L, M) -> write to both
  new on one side only    : create the counterpart from the side that has it
  deleted on one side     : reported, never auto-applied

`pull` and `push` are friendly aliases of `sync`: the algorithm is symmetric and
base-driven, so one operation handles "mobile edited out of band" and "Claude
just edited the laptop copy" equally.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MOBILE_BASE = HOME / "Library/Mobile Documents/iCloud~md~obsidian/Documents/Code"
STATE_ROOT = HOME / ".claude/dvsync"
LOCK_PATH = STATE_ROOT / ".lock"
PRUNE_LOG = STATE_ROOT / "prune.log"  # additive: mobile rolling-window prune audit trail


@contextlib.contextmanager
def sync_lock(blocking=True, timeout=10.0):
    """Serialize reconcile runs across processes. The user may run parallel Claude
    sessions, and the Stop hook fires every turn in each, so without this two
    dvsync processes could interleave reads/writes on the same file. Hooks use
    blocking=False (skip if busy); manual commands wait briefly."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    f = open(LOCK_PATH, "w")
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if not blocking or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
        f.close()


# ---------------------------------------------------------------- helpers

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(p: Path):
    try:
        return p.read_bytes()
    except FileNotFoundError:
        return None


def write_bytes(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def icloud_placeholder(p: Path) -> bool:
    """True when the mobile file is an iCloud stub that has not downloaded yet."""
    stub = p.parent / ("." + p.name + ".icloud")
    return (not p.exists()) and stub.exists()


def state_dir(project: str) -> Path:
    return STATE_ROOT / project


def config_path(project: str) -> Path:
    return state_dir(project) / "config.json"


def base_path(project: str, rel: str) -> Path:
    return state_dir(project) / "base" / rel


def load_config(project: str):
    p = config_path(project)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_config(project: str, cfg: dict):
    p = config_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")


def list_projects():
    """Every project that has a config under the state root."""
    if not STATE_ROOT.exists():
        return []
    return sorted(d.name for d in STATE_ROOT.iterdir()
                  if (d / "config.json").exists())


def mtime(p: Path):
    """Modification time in epoch seconds, or None if the file is absent."""
    try:
        return p.stat().st_mtime
    except (FileNotFoundError, OSError):
        return None


def prune_log_append(line: str):
    """Append one prune (or would-prune) event to the central prune audit log."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with open(PRUNE_LOG, "a") as f:
        f.write(f"{now_iso()} {line}\n")


def git_toplevel(start: Path):
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except Exception:
        return None


def derive_roots(project: str, cwd: Path):
    """Best-effort laptop + mobile roots for a project.

    Laptop root: git top-level if cwd is inside the project, else ~/Code/<project>.
    Mobile root: always <MOBILE_BASE>/<project> (imperative per the setup).
    """
    top = git_toplevel(cwd)
    if top is not None and top.name == project:
        laptop = top
    else:
        laptop = HOME / "Code" / project
    mobile = MOBILE_BASE / project
    return laptop, mobile


def union_merge(base: bytes, ours: bytes, theirs: bytes) -> bytes:
    """git merge-file --union: keep both sides' lines, no conflict markers."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bo, oo, to = td / "base", td / "ours", td / "theirs"
        bo.write_bytes(base or b"")
        oo.write_bytes(ours or b"")
        to.write_bytes(theirs or b"")
        res = subprocess.run(
            ["git", "merge-file", "-p", "--union", str(oo), str(bo), str(to)],
            capture_output=True,
        )
        # merge-file returns the conflict count as exit status; with --union there
        # are no markers, so any nonzero just means hunks overlapped. stdout is the
        # merged result regardless.
        return res.stdout


# ---------------------------------------------------------------- core reconcile

def reconcile_file(cfg: dict, rel: str, dry: bool):
    """Reconcile one tracked file. Returns (status, message)."""
    project = cfg["project"]
    L = Path(cfg["laptop_root"]) / rel
    M = Path(cfg["mobile_root"]) / rel
    B = base_path(project, rel)

    if icloud_placeholder(M):
        return ("skip", f"mobile copy not downloaded from iCloud (placeholder): {rel}")

    lb, mb, bb = read_bytes(L), read_bytes(M), read_bytes(B)
    lex, mex, bex = lb is not None, mb is not None, bb is not None

    # absent on both sides (e.g. storage offline) -> quiet skip, never an error
    if not lex and not mex:
        return ("skip", f"missing in BOTH vaults: {rel}")

    # present on one side only
    if lex and not mex:
        if bex:
            return ("conflict", f"present on laptop, deleted on mobile (not auto-applied): {rel}")
        if not dry:
            write_bytes(M, lb); write_bytes(B, lb)
        return ("create-mobile", f"new on laptop -> created on mobile: {rel}")
    if mex and not lex:
        if bex:
            return ("conflict", f"present on mobile, deleted on laptop (not auto-applied): {rel}")
        if not dry:
            write_bytes(L, mb); write_bytes(B, mb)
        return ("create-laptop", f"new on mobile -> created on laptop: {rel}")

    # present on both sides
    if lb == mb:
        if not bex or bb != lb:
            if not dry:
                write_bytes(B, lb)
            return ("insync", f"identical on both sides; base refreshed: {rel}")
        return ("nochange", f"in sync: {rel}")

    # both present, differ
    l_changed = (not bex) or (lb != bb)
    m_changed = (not bex) or (mb != bb)

    if l_changed and not m_changed:
        if not dry:
            write_bytes(M, lb); write_bytes(B, lb)
        return ("push-mobile", f"laptop changed -> mirrored to mobile: {rel}")
    if m_changed and not l_changed:
        if not dry:
            write_bytes(L, mb); write_bytes(B, mb)
        return ("push-laptop", f"mobile changed -> mirrored to laptop: {rel}")

    # both changed -> union
    merged = union_merge(bb or b"", lb, mb)
    if not dry:
        write_bytes(L, merged); write_bytes(M, merged); write_bytes(B, merged)
    note = "" if bex else " (no base; first-time union may duplicate identical lines)"
    return ("union", f"both changed -> UNION merged to both vaults{note}: {rel}")


# ---------------------------------------------------------------- commands

def require_cfg(project: str):
    cfg = load_config(project)
    if cfg is None:
        print(f"dvsync: project '{project}' not initialized. Run: dvsync track {project} <file.md>", file=sys.stderr)
        sys.exit(2)
    return cfg


def cmd_init(args):
    project = args.project
    laptop, mobile = derive_roots(project, Path(args.cwd or Path.cwd()))
    if args.laptop:
        laptop = Path(args.laptop)
    if args.mobile:
        mobile = Path(args.mobile)
    cfg = load_config(project) or {"project": project, "tracked": []}
    cfg["laptop_root"] = str(laptop)
    cfg["mobile_root"] = str(mobile)
    cfg.setdefault("tracked", [])
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    print(f"initialized {project}")
    print(f"  laptop: {laptop}")
    print(f"  mobile: {mobile}")


def cmd_track(args):
    project = args.project
    cfg = load_config(project)
    if cfg is None:
        # For a ~/Code project the roots derive automatically. For a doc that
        # lives anywhere else (personal vault, BOK, ...), the caller passes the
        # explicit --laptop and --mobile roots after scaffolding the mobile home.
        laptop, mobile = derive_roots(project, Path(args.cwd or Path.cwd()))
        if getattr(args, "laptop", None):
            laptop = Path(args.laptop).expanduser()
        if getattr(args, "mobile", None):
            mobile = Path(args.mobile).expanduser()
        cfg = {"project": project, "laptop_root": str(laptop),
               "mobile_root": str(mobile), "tracked": []}
    added = []
    for rel in args.files:
        rel = rel.lstrip("/")
        if rel not in cfg["tracked"]:
            L = Path(cfg["laptop_root"]) / rel
            M = Path(cfg["mobile_root"]) / rel
            if not L.exists() and not M.exists() and not icloud_placeholder(M):
                print(f"  ! not found in either vault, skipped: {rel}", file=sys.stderr)
                continue
            cfg["tracked"].append(rel)
            added.append(rel)
    cfg["tracked"].sort()
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    if added:
        print(f"tracked {len(added)} file(s) in {project}:")
        for r in added:
            print(f"  + {r}")
    else:
        print("nothing new to track")
    # reconcile the newly tracked files immediately
    if added and not args.no_sync:
        print("--- initial sync ---")
        results = _run_sync(cfg, list(added), dry=False)
        for status, msg in results:
            if status == "nochange":
                continue
            print(f"  [{status.upper()}] {msg}")


def cmd_untrack(args):
    project = args.project
    cfg = require_cfg(project)
    removed = []
    for rel in args.files:
        rel = rel.lstrip("/")
        if rel in cfg["tracked"]:
            cfg["tracked"].remove(rel)
            removed.append(rel)
            bp = base_path(project, rel)
            if bp.exists():
                bp.unlink()
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    print(f"untracked {len(removed)} file(s) (files left in place): {', '.join(removed) or '(none)'}")


def cmd_list(args):
    project = args.project
    cfg = require_cfg(project)
    print(f"{project}: {len(cfg['tracked'])} tracked file(s)")
    print(f"  laptop: {cfg['laptop_root']}")
    print(f"  mobile: {cfg['mobile_root']}")
    for r in cfg["tracked"]:
        print(f"  - {r}")


def _run_sync(cfg, files, dry):
    """Reconcile each file; returns list of (status, message). No printing."""
    return [reconcile_file(cfg, rel, dry) for rel in files]


# Statuses worth surfacing in quiet (hook) mode. Everything else (nochange,
# insync, skip) stays silent so hooks are noise-free on a no-op.
QUIET_SHOW = {"push-mobile", "push-laptop", "create-mobile",
              "create-laptop", "union", "conflict"}


def _print_report(header, project, n, results, quiet):
    """Print a project's reconcile results. Quiet mode shows only noteworthy
    lines (and nothing at all if there are none)."""
    if quiet:
        lines = [(s, m) for s, m in results if s in QUIET_SHOW]
        if not lines:
            return
        print(f"dvsync {header}: {project}")
        for s, m in lines:
            print(f"  [{s.upper()}] {m}")
        return
    print(f"dvsync {header}: {project} ({n} tracked)")
    if not results:
        print("  (nothing tracked)")
    for s, m in results:
        label = "in-sync" if s in ("nochange", "insync") else s
        print(f"  [{label.upper()}] {m}")


def _reconcile_project(project, dry):
    """Reconcile one project's tracked set. Returns (results, cfg) or (None, None)
    if the project should be skipped (no config, empty set, storage offline)."""
    cfg = load_config(project)
    if not cfg:
        return None, None
    laptop, mobile = Path(cfg.get("laptop_root", "")), Path(cfg.get("mobile_root", ""))
    if not laptop.exists() and not mobile.exists():
        return None, None  # both roots gone (e.g. drive offline) -> skip silently
    files = cfg.get("tracked", [])
    if not files:
        return None, None
    return _run_sync(cfg, files, dry), cfg


def cmd_sync(args):
    project = args.project
    cfg = require_cfg(project)
    dry = args.dry or args.cmd == "status"
    quiet = getattr(args, "quiet", False)
    # A dry-run status reads only; no lock needed. A real sync takes the lock.
    if dry:
        files = cfg["tracked"]
        results = _run_sync(cfg, files, dry) if files else []
        _print_report("status (dry-run)", project, len(files), results, quiet)
        if not quiet and any(s == "conflict" for s, _ in results):
            sys.exit(1)
        return
    with sync_lock(blocking=True) as ok:
        if not ok:
            if not quiet:
                print("dvsync: another reconcile is in progress; skipped")
            return
        cfg = require_cfg(project)  # reload under lock
        files = cfg["tracked"]
        results = _run_sync(cfg, files, dry=False) if files else []
        _print_report("sync", project, len(files), results, quiet)
        if files:
            cfg["updated"] = now_iso()
            save_config(project, cfg)
    if not quiet and any(s == "conflict" for s, _ in results):
        sys.exit(1)


def cmd_sync_all(args):
    """Reconcile every configured project. Used by the hooks so sync happens
    regardless of where the session's working directory is. Non-blocking lock:
    if another reconcile is already running (e.g. a parallel session), skip this
    pass silently rather than racing or waiting."""
    dry = getattr(args, "dry", False)
    quiet = getattr(args, "quiet", False)
    if dry:
        for project in list_projects():
            results, cfg = _reconcile_project(project, dry=True)
            if results is None:
                continue
            _print_report("status (dry-run)", project, len(cfg["tracked"]), results, quiet)
        return
    with sync_lock(blocking=False) as ok:
        if not ok:
            if not quiet:
                print("dvsync: another reconcile is in progress; skipped")
            return
        any_conflict = False
        for project in list_projects():
            results, cfg = _reconcile_project(project, dry=False)
            if results is None:
                continue
            _print_report("sync", project, len(cfg["tracked"]), results, quiet)
            cfg["updated"] = now_iso()
            save_config(project, cfg)
            if any(s == "conflict" for s, _ in results):
                any_conflict = True
    if not quiet and any_conflict:
        sys.exit(1)


# ---------------------------------------------------------------- pin / prune (additive)
#
# These commands add a mobile rolling-window prune to keep the phone vault tiny
# without ever risking the canonical laptop/OneDrive copy. They are strictly
# additive: no existing subcommand's behaviour, defaults, or output changes.
#
#   pin / unpin <project> <relpath>  manage a per-project 'pinned' exemption list
#   prune <project> / prune-all      delete STALE mobile copies (DRY-RUN by
#                                    default; only --apply actually deletes)
#
# The prune is deliberately conservative. Per doc, in this order:
#   1. hold sync_lock(blocking=True) for the project,
#   2. skip if pinned,
#   3. skip if the mobile copy is an iCloud placeholder or missing (cannot
#      confirm a real sync),
#   4. skip if not stale (touched within the rolling window),
#   5. reconcile the doc FIRST; abort the doc on a 'conflict' or 'skip' status,
#   6. confirm the laptop copy is authoritative (base snapshot bytes == laptop
#      bytes),
#   7. ONLY THEN, and ONLY with --apply, delete the MOBILE file and untrack the
#      doc atomically. The laptop / OneDrive file is NEVER touched.

def cmd_pin(args):
    project = args.project
    cfg = require_cfg(project)
    pinned = cfg.setdefault("pinned", [])
    added = []
    for rel in args.files:
        rel = rel.lstrip("/")
        if rel not in pinned:
            pinned.append(rel)
            added.append(rel)
    pinned.sort()
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    print(f"pinned {len(added)} file(s) in {project} (exempt from prune): "
          f"{', '.join(added) or '(none)'}")


def cmd_unpin(args):
    project = args.project
    cfg = require_cfg(project)
    pinned = cfg.setdefault("pinned", [])
    removed = []
    for rel in args.files:
        rel = rel.lstrip("/")
        if rel in pinned:
            pinned.remove(rel)
            removed.append(rel)
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    print(f"unpinned {len(removed)} file(s) in {project}: "
          f"{', '.join(removed) or '(none)'}")


def _prune_report(project, rel, action, reason, quiet):
    """Print one prune outcome line. 'skip' lines are suppressed in quiet mode;
    would-prune / pruned / abort always surface. Returns the log-body string."""
    body = f"[{action}] {project}:{rel} :: {reason}"
    if action == "skip" and quiet:
        return body
    print(f"dvsync prune {body}")
    return body


def _prune_doc(cfg, project, rel, pinned, now, window_secs, window_days, apply, quiet):
    """Evaluate (and, with apply, execute) the prune of ONE tracked doc.
    Mutates cfg + saves only when it actually prunes. Never touches the laptop
    file. Returns True if the doc was pruned (or would be, in dry-run)."""
    L = Path(cfg["laptop_root"]) / rel
    M = Path(cfg["mobile_root"]) / rel

    # 2. pinned docs are exempt.
    if rel in pinned:
        _prune_report(project, rel, "skip", "pinned (exempt from prune)", quiet)
        return False

    # 3. a placeholder or missing mobile copy means we cannot confirm a real
    #    sync, so we must never prune it.
    if icloud_placeholder(M):
        _prune_report(project, rel, "skip",
                      "mobile copy is an iCloud placeholder (not downloaded)", quiet)
        return False
    if not M.exists():
        _prune_report(project, rel, "skip",
                      "mobile copy missing (cannot confirm a real sync)", quiet)
        return False

    # 4. staleness = now - max(mtime(laptop), mtime(mobile)); skip if fresh.
    mts = [t for t in (mtime(L), mtime(M)) if t is not None]
    if not mts:
        _prune_report(project, rel, "skip", "no mtime available on either side", quiet)
        return False
    age = now - max(mts)
    if age < window_secs:
        _prune_report(project, rel, "skip",
                      f"fresh ({age/86400.0:.1f}d < {window_days}d window)", quiet)
        return False

    # 5. reconcile FIRST. In dry-run this is a read-only status probe; with
    #    --apply it actually brings the two vaults + base into agreement so the
    #    authoritative check below can pass. Abort the doc on conflict/skip.
    status, msg = reconcile_file(cfg, rel, dry=(not apply))
    if status in ("conflict", "skip"):
        _prune_report(project, rel, "abort", f"reconcile status '{status}': {msg}", quiet)
        return False

    # 6. confirm the laptop copy is authoritative: the base snapshot (last
    #    synced bytes) must equal the current laptop bytes. If they differ, the
    #    laptop copy is not provably the source of truth, so we do not prune.
    lb = read_bytes(L)
    bb = read_bytes(base_path(project, rel))
    if lb is None or bb is None or lb != bb:
        _prune_report(project, rel, "skip",
                      "laptop copy not confirmed authoritative (base != laptop)", quiet)
        return False

    # 7. eligible. Dry-run reports; --apply deletes the MOBILE file and untracks.
    if not apply:
        body = _prune_report(project, rel, "would-prune",
                             f"stale {age/86400.0:.1f}d; laptop authoritative; "
                             f"mobile would be deleted + doc untracked", quiet)
        prune_log_append("DRY " + body)
        return True

    try:
        M.unlink()
    except FileNotFoundError:
        pass
    if rel in cfg.get("tracked", []):
        cfg["tracked"].remove(rel)
    bp = base_path(project, rel)
    if bp.exists():
        bp.unlink()
    cfg["updated"] = now_iso()
    save_config(project, cfg)
    body = _prune_report(project, rel, "pruned",
                         f"stale {age/86400.0:.1f}d; mobile deleted + doc untracked "
                         f"(laptop/OneDrive untouched)", quiet)
    prune_log_append("APPLY " + body)
    return True


def _prune_project(project, window_days, apply, quiet):
    """Prune one project's tracked set under the cross-process lock."""
    cfg = load_config(project)
    if not cfg:
        return
    tracked = cfg.get("tracked", [])
    if not tracked:
        return
    window_secs = window_days * 86400.0
    with sync_lock(blocking=True) as ok:
        if not ok:
            if not quiet:
                print(f"dvsync prune: {project}: another reconcile in progress; skipped")
            return
        cfg = load_config(project)  # reload under lock
        if not cfg:
            return
        pinned = set(cfg.get("pinned", []))
        now = time.time()
        tracked = list(cfg.get("tracked", []))  # snapshot; cfg mutates on prune
        if not quiet:
            mode = "APPLY" if apply else "DRY-RUN"
            print(f"dvsync prune: {project} ({len(tracked)} tracked, "
                  f"window {window_days}d, {mode})")
        for rel in tracked:
            _prune_doc(cfg, project, rel, pinned, now, window_secs,
                       window_days, apply, quiet)


def cmd_prune(args):
    project = args.project
    require_cfg(project)
    _prune_project(project, args.window_days, args.apply, getattr(args, "quiet", False))


def cmd_prune_all(args):
    quiet = getattr(args, "quiet", False)
    for project in list_projects():
        _prune_project(project, args.window_days, args.apply, quiet)


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(prog="dvsync", description="dual-vault markdown sync")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("project")
    p.add_argument("--laptop"); p.add_argument("--mobile"); p.add_argument("--cwd")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("track"); p.add_argument("project"); p.add_argument("files", nargs="+")
    p.add_argument("--cwd"); p.add_argument("--no-sync", action="store_true")
    p.add_argument("--laptop"); p.add_argument("--mobile")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("untrack"); p.add_argument("project"); p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_untrack)

    p = sub.add_parser("list"); p.add_argument("project")
    p.set_defaults(func=cmd_list)

    for name in ("sync", "pull", "push", "status"):
        p = sub.add_parser(name); p.add_argument("project")
        p.add_argument("--dry", action="store_true")
        p.add_argument("--quiet", action="store_true")
        p.set_defaults(func=cmd_sync)

    p = sub.add_parser("sync-all")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_sync_all)

    # additive: pin/unpin exemptions + mobile rolling-window prune
    p = sub.add_parser("pin"); p.add_argument("project"); p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_pin)

    p = sub.add_parser("unpin"); p.add_argument("project"); p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_unpin)

    p = sub.add_parser("prune"); p.add_argument("project")
    p.add_argument("--window-days", type=int, default=28)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("prune-all")
    p.add_argument("--window-days", type=int, default=28)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_prune_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
