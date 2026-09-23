"""Read-only Codex discovery smoke test; install first in an isolated CODEX_HOME."""
import argparse
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
repo = args.repo.resolve()
marketplace_path = repo / ".agents/plugins/marketplace.json"
catalog = json.loads(marketplace_path.read_text(encoding="utf-8"))
proc = subprocess.Popen([shutil.which("codex"), "app-server", "--stdio"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                        encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
messages = queue.Queue()


def reader():
    for line in proc.stdout:
        try:
            messages.put(json.loads(line))
        except json.JSONDecodeError:
            pass


threading.Thread(target=reader, daemon=True).start()
serial = 0


def call(method, params):
    global serial
    serial += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": serial, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        result = messages.get(timeout=45)
        if result.get("id") == serial:
            if "error" in result:
                raise RuntimeError(result["error"])
            return result["result"]


try:
    call("initialize", {"clientInfo": {"name": "numaco-skill-check", "version": "1.0"},
                        "capabilities": {"experimentalApi": True}})
    proc.stdin.write('{"jsonrpc":"2.0","method":"initialized"}\n')
    proc.stdin.flush()
    listing = call("skills/list", {"cwds": [str(repo.parent.parent)], "forceReload": True})
    skills = [s for entry in listing["data"] for s in entry["skills"] if "cache/numaco/" in s["path"].replace("\\", "/")]
    errors = [e for entry in listing["data"] for e in entry["errors"] if "numaco" in e["path"]]
    plugins = {}
    for entry in catalog["plugins"]:
        detail = call("plugin/read", {"pluginName": entry["name"], "marketplacePath": str(marketplace_path)})["plugin"]
        plugins[entry["name"]] = {"enabled": detail["summary"]["enabled"],
                                    "skills": [s["name"] for s in detail["skills"]],
                                    "mcpServers": detail["mcpServers"]}
    report = {"skillCount": len(skills), "skills": [{k: s.get(k) for k in ["name", "enabled", "pluginId", "path"]} for s in skills],
              "errors": errors, "plugins": plugins}
    aliases = [s for s in skills if ":source-command-" in s["name"]]
    native = [s for s in skills if ":source-command-" not in s["name"]]
    print(json.dumps({"skillCount": len(skills), "nativeSkillCount": len(native),
                      "aliases": [s["name"] for s in aliases], "errors": errors, "plugins": plugins}, indent=2))
    roots = [repo / entry["source"]["path"] for entry in catalog["plugins"]]
    expected = sum(len(list(p.glob("skills/*/SKILL.md"))) for p in roots)
    assert not errors, errors
    assert len(native) == expected == 26, (len(native), expected)
    assert not aliases, aliases
    expected_names = {f"{p.name}:{s.parent.name}" for p in roots for s in p.glob("skills/*/SKILL.md")}
    assert {s["name"] for s in native} == expected_names
    assert all(s["enabled"] for s in skills)
    assert all(p["enabled"] for p in plugins.values())
    assert "clockify" in plugins["clockify-mcp"]["mcpServers"]
    assert "mail" in plugins["mcp-mail"]["mcpServers"]
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
