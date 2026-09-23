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
    result = subprocess.run(args, text=True, encoding="utf-8", capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or str(args))
    if json_output:
        return json.loads(result.stdout)
    return result.stdout.rstrip()


def packet_names() -> list[str]:
    manifest = json.loads((HUB_ROOT / "packet.json").read_text(encoding="utf-8"))
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


def refresh(codex: str, entries: list[dict]) -> None:
    git_entries = [entry for entry in entries if entry.get("marketplaceSource", {}).get("sourceType") == "git"]
    if not git_entries:
        print("Local marketplace: checking local source versions; no upstream fetch.")
        return
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to check local edits before refreshing the marketplace")
    roots = set()
    for entry in git_entries:
        source = entry.get("source", {})
        if source.get("source") != "local" or not source.get("path"):
            raise RuntimeError("Cannot inspect the Git marketplace checkout safely")
        roots.add(run([git, "-C", source["path"], "rev-parse", "--show-toplevel"]))
    for root in roots:
        status = run([git, "-C", root, "status", "--porcelain", "--untracked-files=all"])
        # Codex owns this untracked install metadata, not the plugin source.
        changes = [line for line in status.splitlines() if line[3:].strip('"') != ".codex-marketplace-install.json"]
        if changes:
            raise RuntimeError("Preserve or commit local edits before refreshing " + root + ":\n" + "\n".join(changes))
    print(run([codex, "plugin", "marketplace", "upgrade", "numaco", "--json"]))


def install_packet(codex: str, *, update: bool = False) -> dict:
    names = packet_names()
    state = catalog(codex)
    entries = state.get("installed", []) + state.get("available", [])
    known = {entry["name"] for entry in entries}
    missing = set(names) - known
    if missing:
        raise RuntimeError("Numaco marketplace is absent or incomplete; missing: " + ", ".join(sorted(missing)))
    if update:
        refresh(codex, entries)
        state = catalog(codex)
    installed = {entry["name"]: entry for entry in state.get("installed", [])}
    for name in names:
        entry = installed.get(name, {})
        desired = source_version(entry)
        current = desired is None or entry.get("version") == desired
        if entry.get("enabled") and current:
            print(f"Already enabled: {name}@numaco")
            continue
        result = run([codex, "plugin", "add", f"{name}@numaco", "--json"], json_output=True)
        print(f"Installed {result['pluginId']} {result.get('version', '')}")
    verified = catalog(codex)
    by_name = {entry["name"]: entry for entry in verified.get("installed", [])}
    failed = [name for name in names if not by_name.get(name, {}).get("enabled")]
    if failed:
        raise RuntimeError("Plugins still missing or disabled: " + ", ".join(failed))
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
