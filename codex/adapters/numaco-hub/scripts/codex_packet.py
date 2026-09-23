#!/usr/bin/env python3
"""Install the hub and its declared dependency plugins through the Codex CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


HUB_ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, json_output: bool = False):
    try:
        result = subprocess.run(args, text=True, encoding="utf-8", capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Command timed out; inspect its state before retrying: {args[0]}") from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or str(args))
    if json_output:
        return json.loads(result.stdout)
    return result.stdout.rstrip()


def packet_names(root: Path = HUB_ROOT) -> list[str]:
    manifest = json.loads((root / "packet.json").read_text(encoding="utf-8"))
    names = list(dict.fromkeys(manifest["plugins"]))
    if not names or not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names):
        raise ValueError("Invalid dependency name in the hub manifest")
    return names


def catalog(codex: str) -> dict:
    return run([codex, "plugin", "list", "--marketplace", "numaco", "--available", "--json"], json_output=True)


def source_version(entry: dict) -> str | None:
    source = entry.get("source", {})
    if source.get("source") != "local" or not source.get("path"):
        return None
    root = Path(source["path"])
    for relative in ("plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        path = root / relative
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")).get("version")
    return None


def clean_checkout(git: str, root: str) -> None:
    status = run([git, "-C", root, "status", "--porcelain", "--untracked-files=all"])
    # Ignore only Codex's untracked marker, never a modified tracked file.
    changes = [line for line in status.splitlines() if line != "?? .codex-marketplace-install.json"]
    if changes:
        raise RuntimeError("Preserve or commit local edits before refreshing " + root + ":\n" + "\n".join(changes))


def refresh(entries: list[dict]) -> None:
    """Fast-forward source only. Codex's marketplace upgrade also replaces caches."""
    git_entries = [entry for entry in entries if entry.get("marketplaceSource", {}).get("sourceType") == "git"]
    if not git_entries:
        print("Local marketplace: checking local source versions; no upstream fetch.")
        return
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to check local edits before refreshing the marketplace")
    roots = {}
    for entry in git_entries:
        source = entry.get("source", {})
        if source.get("source") != "local" or not source.get("path"):
            raise RuntimeError("Cannot inspect the Git marketplace checkout safely")
        root = run([git, "-C", source["path"], "rev-parse", "--show-toplevel"])
        configured_source = entry["marketplaceSource"].get("source")
        if root in roots and roots[root] != configured_source:
            raise RuntimeError("Conflicting marketplace sources for " + root)
        roots[root] = configured_source
    plans = []
    # Preflight every checkout before any fetch or working-tree update.
    for root, configured_source in sorted(roots.items()):
        clean_checkout(git, root)
        marker = Path(root) / ".codex-marketplace-install.json"
        if not marker.is_file():
            raise RuntimeError("Cannot determine the configured Git ref safely: missing " + str(marker))
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        origin = run([git, "-C", root, "remote", "get-url", "origin"])
        if (metadata.get("source_type") != "git" or not configured_source
                or metadata.get("source") != configured_source or origin != configured_source):
            raise RuntimeError("Marketplace source/remote mismatch; refusing to switch sources: " + root)
        ref = metadata.get("ref_name") or "HEAD"
        if not isinstance(ref, str) or ref.startswith(("-", "+")) or any(c in ref for c in ":*?[^~\\") or any(c.isspace() for c in ref):
            raise RuntimeError("Unsafe configured Git ref: " + repr(ref))
        run([git, "check-ref-format", "--allow-onelevel", ref])
        plans.append((root, ref))
    for root, ref in plans:
        run([git, "-C", root, "fetch", "--no-tags", "--", "origin", ref])
        target = run([git, "-C", root, "rev-parse", "--verify", "FETCH_HEAD^{commit}"])
        clean_checkout(git, root)
        # merge --ff-only alone permits a locally-ahead checkout. Refuse that
        # too, so a successful refresh means the exact configured upstream tip.
        try:
            run([git, "-C", root, "merge-base", "--is-ancestor", "HEAD", target])
        except RuntimeError as error:
            raise RuntimeError("Local commits or rewritten upstream prevent a fast-forward; preserve the checkout: " + root) from error
        run([git, "-C", root, "merge", "--ff-only", "--no-edit", target])
        print(f"Refreshed Git source ({ref}) to {target[:12]}; installed caches untouched.")


def install_packet(codex: str, *, update: bool = False) -> dict:
    state = catalog(codex)
    entries = state.get("installed", []) + state.get("available", [])
    if update:
        refresh(entries)
        state = catalog(codex)
        entries = state.get("installed", []) + state.get("available", [])
    # Read the refreshed hub declaration, not the older installed helper's copy.
    targets = {entry["name"]: entry for entry in entries}
    hub_source = targets.get("numaco-hub", {}).get("source", {})
    names = packet_names(Path(hub_source["path"])) if hub_source.get("source") == "local" and hub_source.get("path") else packet_names()
    known = {entry["name"] for entry in entries}
    missing = set(names) - known
    if missing:
        raise RuntimeError("Numaco marketplace is absent or incomplete; missing: " + ", ".join(sorted(missing)))
    desired_versions = {name: source_version(targets[name]) for name in names}
    unknown = [name for name, version in desired_versions.items() if not isinstance(version, str) or not version]
    if unknown:
        raise RuntimeError("Cannot determine source versions; no plugins installed: " + ", ".join(unknown))
    installed = {entry["name"]: entry for entry in state.get("installed", [])}
    for name in names:
        entry = installed.get(name, {})
        desired = desired_versions[name]
        current = entry.get("version") == desired
        if entry.get("enabled") and current:
            print(f"Already enabled: {name}@numaco")
            continue
        try:
            result = run([codex, "plugin", "add", f"{name}@numaco", "--json"], json_output=True)
        except RuntimeError as error:
            raise RuntimeError(f"Could not install {name}@numaco: {error}\n"
                               "If Windows reports a locked cache, close the affected tool and retry. "
                               "Do not force-delete caches or discard local edits.") from error
        print(f"Installed {result['pluginId']} {result.get('version', '')}")
    verified = catalog(codex)
    by_name = {entry["name"]: entry for entry in verified.get("installed", [])}
    failed = [name for name in names if not by_name.get(name, {}).get("enabled")
              or by_name[name].get("version") != desired_versions[name]]
    if failed:
        raise RuntimeError("Plugins still missing, disabled, or outdated: " + ", ".join(failed))
    print(f"Verified: all {len(names)} Numaco plugins installed and enabled.")
    print("Start a new Codex task to load new skills and MCP tools.")
    return verified


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Explicitly register this local or Git marketplace source first")
    parser.add_argument("--update", action="store_true", help="Refresh a clean Git source and install changed, missing, or disabled plugins")
    args = parser.parse_args()
    codex = shutil.which("codex")
    if not codex:
        parser.error("Codex CLI is not on PATH")
    try:
        if args.source:
            print(run([codex, "plugin", "marketplace", "add", args.source, "--json"]))
        install_packet(codex, update=args.update)
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
