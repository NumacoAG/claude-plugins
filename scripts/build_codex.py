#!/usr/bin/env python3
"""Build the checked-in Codex distribution from shared plugin sources (PyYAML)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ".agents/plugins/marketplace.json"
INVENTORY = "codex/generated-files.json"
DIRECT = {"mcp-mail"}  # Already dual-host; no second copy or version stream.
ALLOWED = {"name", "description", "license", "allowed-tools", "metadata"}


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def portable_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return data.replace(b"\r\n", b"\n")


def frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("Missing YAML frontmatter")
    header, body = text[4:].split("\n---\n", 1)
    data = yaml.safe_load(header)
    if not isinstance(data, dict) or not data.get("description"):
        raise ValueError("Missing skill/command description")
    return data, body


def skill(data: dict, body: str) -> bytes:
    extra = {key: str(value) for key, value in data.items() if key not in ALLOWED}
    data = {key: value for key, value in data.items() if key in ALLOWED}
    if extra:
        data["metadata"] = {**data.get("metadata", {}), **extra}
    description = data["description"]
    if not isinstance(description, str) or len(description) > 1024 or re.search(r"[<>]", description):
        raise ValueError(f"Invalid Codex description for {data.get('name')}; add an adapter override")
    return ("---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
            + "---\n" + body).encode("utf-8")


def package_version(base: str, payload: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, data in sorted(payload.items()):
        digest.update(path.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return base.split("+", 1)[0] + "+codex." + digest.hexdigest()[:16]


def build(root: Path = ROOT) -> dict[str, bytes]:
    catalog = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    hub = json.loads((root / "numaco-hub/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    packet = list(dict.fromkeys([*hub["dependencies"], hub["name"]]))
    adapters = root / "codex/adapters"
    descriptions = json.loads((adapters / "descriptions.json").read_text(encoding="utf-8"))
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode("utf-8").split("\0")
    tracked_set = set(tracked)
    output: dict[str, bytes] = {}
    entries = []
    copied = {}  # Source -> generated path, for precise privacy-baseline projection.
    for entry in catalog["plugins"]:
        name = entry["name"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError(f"Invalid plugin name: {name}")
        if entry["source"] != f"./{name}":
            raise ValueError(f"Expected repository-local canonical source for {name}")
        source = root / name
        if name in DIRECT:
            if not (source / ".codex-plugin/plugin.json").is_file():
                raise ValueError(f"Missing dual-host manifest: {name}")
            plugin_path = f"./{name}"
        else:
            plugin_path = f"./plugins/{name}"
            payload: dict[str, bytes] = {}
            for path in tracked:
                if not path.startswith(name + "/"):
                    continue
                relative = path[len(name) + 1:]
                if relative.split("/")[0] in {".claude-plugin", ".codex-plugin"} or relative == "hooks/hooks.json":
                    continue
                destination = relative.replace("commands/", "workflows/", 1) if relative.startswith("commands/") else relative
                data = portable_bytes(root / path)
                if relative.startswith("skills/") and relative.endswith("/SKILL.md"):
                    metadata, body = frontmatter(data.decode("utf-8"))
                    metadata["name"] = relative.split("/")[1]
                    metadata["description"] = descriptions.get(name + "/" + metadata["name"], metadata["description"])
                    body = "\nRead [Codex host guidance](../../CODEX.md) before the workflow below.\n" + body
                    data = skill(metadata, body)
                payload[destination] = data
                copied[path] = f"plugins/{name}/{destination}"
                if relative.startswith("commands/") and relative.endswith(".md"):
                    command = Path(relative).stem
                    metadata, _ = frontmatter(data.decode("utf-8"))
                    key = f"skills/{command}/SKILL.md"
                    if (source / key).exists():
                        raise ValueError(f"Command/skill collision: {name}/{command}")
                    payload[key] = skill({"name": command, "description": descriptions.get(name + "/" + command, metadata["description"])},
                        f"\n# {command}\n\nRead [Codex host guidance](../../CODEX.md) first, then read and follow the complete "
                        f"[shared workflow](../../workflows/{command}.md). The workflow is generated unchanged from the canonical command.\n")
            payload["CODEX.md"] = portable_bytes(adapters / "common.md")
            guide = adapters / f"{name}.md"
            if guide.exists():
                payload["CODEX.md"] += b"\n" + portable_bytes(guide)
            overlay = adapters / name
            if overlay.exists():
                for file in sorted(overlay.rglob("*")):
                    if file.is_file() and file.relative_to(root).as_posix() in tracked_set:
                        payload[file.relative_to(overlay).as_posix()] = portable_bytes(file)
            if name == "numaco-hub":
                payload["packet.json"] = json_bytes({"plugins": packet})
            canonical = json.loads((source / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
            display = "Clockify" if name == "clockify-mcp" else name.replace("-", " ").title()
            manifest = {key: canonical[key] for key in ("name", "version", "description", "author", "license")}
            manifest["skills"] = "./skills/"
            manifest["interface"] = {
                "displayName": display, "shortDescription": f"Use {display} in Codex.",
                "longDescription": canonical["description"], "developerName": "Numaco AG",
                "category": "Productivity", "capabilities": [], "websiteURL": "https://numaco.ch",
                "defaultPrompt": [f"Help me use {display}."]}
            if name == "clockify-mcp":
                manifest["mcpServers"] = {"clockify": {"command": "uv", "args": ["run", "clockify-mcp"], "cwd": ".", "startup_timeout_sec": 120}}
                manifest["interface"]["capabilities"] = ["Read", "Write"]
            payload[".codex-plugin/plugin.json"] = json_bytes(manifest)
            manifest["version"] = package_version(canonical["version"], payload)
            payload[".codex-plugin/plugin.json"] = json_bytes(manifest)
            output.update({f"plugins/{name}/{path}": data for path, data in payload.items()})
        entries.append({"name": name, "source": {"source": "local", "path": plugin_path},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"})
    if set(packet) != {e["name"] for e in entries}:
        raise ValueError("Hub dependencies and marketplace packet disagree")
    output[MARKETPLACE] = json_bytes({"name": catalog["name"], "interface": {"displayName": "Numaco"}, "plugins": entries})
    baseline = ["# Generated from the root .publish-allow; do not edit."]
    for line in (root / ".publish-allow").read_text(encoding="utf-8").splitlines():
        path, separator, rest = line.partition(":")
        if separator and path in copied:
            baseline.append(copied[path] + ":" + rest)
    output["plugins/.publish-allow"] = ("\n".join(baseline) + "\n").encode("utf-8")
    output[INVENTORY] = json_bytes({path: hashlib.sha256(data).hexdigest() for path, data in sorted(output.items())})
    return output


def sync(root: Path, output: dict[str, bytes], check: bool = False) -> bool:
    previous = json.loads((root / INVENTORY).read_text(encoding="utf-8")) if (root / INVENTORY).exists() else {}
    stale = set(previous) - output.keys()
    # The inventory is data, not permission to remove arbitrary files.
    for path in stale:
        target = (root / path).resolve()
        if not target.is_relative_to((root / "plugins").resolve()):
            raise ValueError(f"Refusing stale path outside generated plugins: {path}")
        if target.exists() and hashlib.sha256(portable_bytes(target)).hexdigest() != previous[path]:
            raise ValueError(f"Preserve manually edited generated file before removal: {path}")
    changed = [path for path, data in output.items() if not (root / path).is_file() or portable_bytes(root / path) != data]
    extra = [p.relative_to(root).as_posix() for p in (root / "plugins").rglob("*")
             if p.is_file() and p.relative_to(root).as_posix() not in output and p.relative_to(root).as_posix() not in stale
             and "__pycache__" not in p.parts]
    if extra:
        raise ValueError("Unexpected files in generated plugins: " + ", ".join(extra))
    if check:
        if changed or stale:
            print("Regenerate Codex packages: " + ", ".join(sorted(set(changed) | stale)))
            return False
        print("Codex packages match shared sources.")
        return True
    for path in stale:
        (root / path).unlink(missing_ok=True)
    for path in changed:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output[path])
    print(f"Generated {len(output)} files; {len(changed)} changed, {len(stale)} obsolete generated files removed.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed artifacts differ; write nothing")
    args = parser.parse_args()
    raise SystemExit(0 if sync(ROOT, build(), args.check) else 1)
