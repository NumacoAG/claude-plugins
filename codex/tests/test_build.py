import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("build_codex", Path(__file__).resolve().parents[2] / "scripts/build_codex.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = builder.ROOT
        cls.output = builder.build()
        cls.catalog = json.loads(cls.output[builder.MARKETPLACE])

    def test_deterministic(self):
        self.assertEqual(self.output, builder.build())

    def test_generated_output_never_targets_claude_sources(self):
        self.assertTrue(all(path.startswith("plugins/") or path in {builder.MARKETPLACE, builder.INVENTORY} for path in self.output))
        self.assertFalse(any("/.claude-plugin/" in path or "/commands/" in path or path.endswith("hooks/hooks.json") for path in self.output))

    def test_every_source_skill_and_command_is_available(self):
        counts = {}
        for entry in self.catalog["plugins"]:
            name = entry["name"]
            canonical = self.root / name
            expected = {p.parent.name for p in canonical.glob("skills/*/SKILL.md")} | {p.stem for p in canonical.glob("commands/*.md")}
            if name in builder.DIRECT:
                actual = {p.parent.name for p in canonical.glob("skills/*/SKILL.md")}
            else:
                actual = {Path(p).parent.name for p in self.output if p.startswith(f"plugins/{name}/skills/") and p.endswith("/SKILL.md")}
            self.assertEqual(actual, expected, name)
            counts[name] = len(actual)
        self.assertEqual(counts, {"numaco-hub": 3, "numaco-design": 5, "review-kit": 7, "dev-process-kit": 6, "mcp-mail": 3, "clockify-mcp": 2})

    def test_shared_workflow_bodies_are_preserved(self):
        for entry in self.catalog["plugins"]:
            name = entry["name"]
            if name in builder.DIRECT:
                continue
            source = self.root / name
            for command in source.glob("commands/*.md"):
                self.assertEqual(builder.portable_bytes(command), self.output[f"plugins/{name}/workflows/{command.name}"])
            for original in source.glob("skills/*/SKILL.md"):
                relative = original.relative_to(source).as_posix()
                if (self.root / "codex/adapters" / name / relative).exists():
                    continue  # Onboarding is a host-specific adapter.
                _, body = builder.frontmatter(builder.portable_bytes(original).decode())
                self.assertTrue(self.output[f"plugins/{name}/{relative}"].decode().endswith(body), str(original))

    def test_versions_are_content_addressed(self):
        self.assertNotEqual(builder.package_version("1.0.0", {"a": b"one"}), builder.package_version("1.0.0", {"a": b"two"}))
        self.assertEqual(builder.package_version("1.0.0", {"a": b"one"}), builder.package_version("1.0.0+old", {"a": b"one"}))

    def test_packet_is_generated_from_shared_dependencies(self):
        hub = json.loads((self.root / "numaco-hub/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
        packet = json.loads(self.output["plugins/numaco-hub/packet.json"])
        self.assertEqual(set(packet["plugins"]), {*hub["dependencies"], hub["name"]})

    def test_mcp_configuration_retains_mail_approval_gate(self):
        mail = json.loads((self.root / "mcp-mail/.mcp.json").read_text(encoding="utf-8"))["mcpServers"]["mail"]
        self.assertEqual(mail["env"]["MCP_MAIL_CLIENT_APPROVAL_GATE"], "codex")
        self.assertEqual(mail["tools"]["mail_send"]["approval_mode"], "prompt")
        clockify = json.loads(self.output["plugins/clockify-mcp/.codex-plugin/plugin.json"])["mcpServers"]["clockify"]
        self.assertEqual(clockify["cwd"], ".")
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", json.dumps(clockify))

    def test_check_is_read_only_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            self.assertFalse(builder.sync(root, self.output, check=True))
            self.assertEqual(list(root.iterdir()), [])
            builder.sync(root, self.output)
            self.assertTrue(builder.sync(root, self.output, check=True))
            target = root / "plugins/numaco-hub/CODEX.md"
            target.write_text("manual drift", encoding="utf-8")
            self.assertFalse(builder.sync(root, self.output, check=True))
            self.assertEqual(target.read_text(), "manual drift")

    def test_stale_inventory_cannot_remove_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex").mkdir()
            victim = root / "important.txt"
            victim.write_bytes(b"keep")
            (root / builder.INVENTORY).write_text(json.dumps({"important.txt": hashlib.sha256(b"keep").hexdigest()}))
            with self.assertRaisesRegex(ValueError, "outside generated"):
                builder.sync(root, {})
            self.assertEqual(victim.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
