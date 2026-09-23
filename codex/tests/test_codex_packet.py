import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("codex_packet", Path(__file__).resolve().parents[2] / "plugins/numaco-hub/scripts/codex_packet.py")
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


class PacketTests(unittest.TestCase):
    def setUp(self):
        version = patch.object(packet, "source_version", return_value="1.0.0")
        self.source_version = version.start()
        self.addCleanup(version.stop)

    def test_install_only_missing_and_disabled_plugins(self):
        names = packet.packet_names()
        before = {"installed": [{"name": n, "enabled": n != names[1], "version": "1.0.0"} for n in names[1:]],
                  "available": [{"name": names[0]}]}
        after = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in names], "available": []}
        with patch.object(packet, "catalog", side_effect=[before, after]), patch.object(packet, "run") as run:
            run.side_effect = lambda args, **kw: {"pluginId": args[3], "version": "1.0.0"}
            packet.install_packet("codex")
            self.assertEqual([call.args[0][3] for call in run.call_args_list], [f"{n}@numaco" for n in names[:2]])

    def test_incomplete_marketplace_fails_before_install(self):
        with patch.object(packet, "catalog", return_value={"installed": [], "available": []}), patch.object(packet, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "absent or incomplete"):
                packet.install_packet("codex")
            run.assert_not_called()

    def test_changed_source_version_reinstalls_enabled_plugin(self):
        names = packet.packet_names()
        state = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in names], "available": []}
        after = {"installed": [{"name": n, "enabled": True, "version": "1.0.1" if n == names[0] else "1.0.0"} for n in names]}
        with patch.object(packet, "catalog", side_effect=[state, after]), patch.object(packet, "source_version", side_effect=lambda entry: "1.0.1" if entry["name"] == names[0] else "1.0.0"), patch.object(packet, "run", return_value={"pluginId": names[0] + "@numaco"}) as run:
            packet.install_packet("codex")
            run.assert_called_once_with(["codex", "plugin", "add", names[0] + "@numaco", "--json"], json_output=True)

    def test_verification_detects_disabled_dependency(self):
        state = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in packet.packet_names()], "available": []}
        failed = {"installed": [], "available": []}
        with patch.object(packet, "catalog", side_effect=[state, failed]):
            with self.assertRaisesRegex(RuntimeError, "still missing, disabled, or outdated"):
                packet.install_packet("codex")

    def test_dirty_git_marketplace_never_refreshes(self):
        entry = {"marketplaceSource": {"sourceType": "git"}, "source": {"source": "local", "path": "/repo/plugin"}}
        with patch.object(packet.shutil, "which", return_value="git"), patch.object(packet, "run", side_effect=["/repo", " M mail.py\n?? .codex-marketplace-install.json"]) as run:
            with self.assertRaisesRegex(RuntimeError, "Preserve or commit"):
                packet.refresh([entry])
            self.assertFalse(any("upgrade" in call.args[0] for call in run.call_args_list))

    def test_local_marketplace_does_not_fetch(self):
        with patch.object(packet, "run") as run:
            packet.refresh([{"marketplaceSource": {"sourceType": "local"}}])
            run.assert_not_called()

    def test_unknown_source_version_stops_before_any_installs(self):
        state = {"available": [{"name": n} for n in packet.packet_names()]}
        self.source_version.return_value = None
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Cannot determine source versions"):
                packet.install_packet("codex")
            run.assert_not_called()

    def test_verification_rejects_wrong_installed_version(self):
        state = {"installed": [{"name": n, "enabled": True, "version": "0.9.0"} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "run", return_value={"pluginId": "test@numaco"}):
            with self.assertRaisesRegex(RuntimeError, "outdated"):
                packet.install_packet("codex")

    def test_locked_changed_plugin_reports_safe_recovery(self):
        state = {"available": [{"name": n} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "run", side_effect=RuntimeError("Access is denied")) as run:
            with self.assertRaisesRegex(RuntimeError, "Do not force-delete"):
                packet.install_packet("codex")
            self.assertEqual(run.call_count, 1)

    def test_refresh_rechecks_catalog_before_installing(self):
        before = {"available": []}
        after = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", side_effect=[before, after, after]), patch.object(packet, "refresh"), patch.object(packet, "run") as run:
            packet.install_packet("codex", update=True)
            run.assert_not_called()


@unittest.skipUnless(shutil.which("git"), "Git is required for source-refresh integration tests")
class GitRefreshTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.upstream = self.base / "upstream"
        self.checkout = self.base / "checkout"
        self.git = shutil.which("git")
        self.command("init", "-b", "main", str(self.upstream))
        self.command("-C", str(self.upstream), "config", "user.name", "Test")
        self.command("-C", str(self.upstream), "config", "user.email", "test@example.com")
        plugin = self.upstream / "plugin"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        (plugin / "packet.json").write_text(json.dumps({"plugins": packet.packet_names()}), encoding="utf-8")
        self.commit("initial")
        self.command("clone", str(self.upstream), str(self.checkout))
        self.origin = self.command("-C", str(self.checkout), "remote", "get-url", "origin")
        self.marker = self.checkout / ".codex-marketplace-install.json"
        self.metadata = {"source_type": "git", "source": self.origin, "ref_name": "main"}
        self.save_metadata()
        self.entry = {"marketplaceSource": {"sourceType": "git", "source": self.origin},
                      "source": {"source": "local", "path": str(self.checkout / "plugin")}}

    def command(self, *args):
        return subprocess.check_output([self.git, *args], stderr=subprocess.STDOUT, text=True, encoding="utf-8").strip()

    def commit(self, message):
        self.command("-C", str(self.upstream), "add", ".")
        self.command("-C", str(self.upstream), "commit", "-m", message)

    def advance(self):
        (self.upstream / "update.txt").write_text("new source", encoding="utf-8")
        self.commit("advance")

    def save_metadata(self):
        self.marker.write_text(json.dumps(self.metadata), encoding="utf-8")

    def head(self, root):
        return self.command("-C", str(root), "rev-parse", "HEAD")

    def test_fast_forward_updates_source_without_codex_or_marker_writes(self):
        self.advance()
        marker_before = self.marker.read_bytes()
        with patch.object(packet, "run", wraps=packet.run) as run:
            packet.refresh([self.entry, self.entry])
            self.assertTrue(all(call.args[0][0] == self.git for call in run.call_args_list))
            self.assertEqual(sum("fetch" in call.args[0] for call in run.call_args_list), 1)
        self.assertEqual(self.head(self.checkout), self.head(self.upstream))
        self.assertEqual(self.marker.read_bytes(), marker_before)

    def test_pinned_ref_is_not_silently_changed_to_main(self):
        pinned = self.head(self.upstream)
        self.command("-C", str(self.upstream), "branch", "release")
        self.advance()
        self.metadata["ref_name"] = "release"
        self.save_metadata()
        packet.refresh([self.entry])
        self.assertEqual(self.head(self.checkout), pinned)

    def test_default_ref_follows_remote_head(self):
        self.metadata["ref_name"] = None
        self.save_metadata()
        self.advance()
        packet.refresh([self.entry])
        self.assertEqual(self.head(self.checkout), self.head(self.upstream))

    def test_dirty_checkout_stops_before_fetch_and_preserves_changes(self):
        target = self.checkout / "plugin/.codex-plugin/plugin.json"
        target.write_text("local edits", encoding="utf-8")
        self.advance()
        with patch.object(packet, "run", wraps=packet.run) as run:
            with self.assertRaisesRegex(RuntimeError, "Preserve or commit"):
                packet.refresh([self.entry])
            self.assertFalse(any("fetch" in call.args[0] for call in run.call_args_list))
        self.assertEqual(target.read_text(), "local edits")

    def test_local_commits_are_never_reset_even_when_ahead(self):
        (self.checkout / "local.txt").write_text("keep", encoding="utf-8")
        self.command("-C", str(self.checkout), "add", "local.txt")
        self.command("-C", str(self.checkout), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "local")
        before = self.head(self.checkout)
        with self.assertRaisesRegex(RuntimeError, "Local commits"):
            packet.refresh([self.entry])
        self.assertEqual(self.head(self.checkout), before)
        self.assertEqual((self.checkout / "local.txt").read_text(), "keep")

    def test_source_mismatch_fails_before_fetch(self):
        self.metadata["source"] = "https://example.com/other.git"
        self.save_metadata()
        with patch.object(packet, "run", wraps=packet.run) as run:
            with self.assertRaisesRegex(RuntimeError, "source/remote mismatch"):
                packet.refresh([self.entry])
            self.assertFalse(any("fetch" in call.args[0] for call in run.call_args_list))

    def test_missing_marker_does_not_fall_back_to_cache_upgrade(self):
        self.marker.unlink()
        with self.assertRaisesRegex(RuntimeError, "configured Git ref"):
            packet.refresh([self.entry])

    def test_refspec_cannot_target_local_refs(self):
        self.metadata["ref_name"] = "main:refs/heads/main"
        self.save_metadata()
        with self.assertRaisesRegex(RuntimeError, "Unsafe configured Git ref"):
            packet.refresh([self.entry])

    def test_update_with_real_git_does_not_reinstall_unchanged_plugins(self):
        self.advance()
        state = {"installed": [{**self.entry, "name": n, "enabled": True, "version": "1.0.0"} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "run", wraps=packet.run) as run:
            packet.install_packet("codex-must-not-run", update=True)
            self.assertTrue(all(call.args[0][0] == self.git for call in run.call_args_list))
        self.assertEqual(self.head(self.checkout), self.head(self.upstream))

    def test_update_leaves_unchanged_enabled_plugins_alone(self):
        state = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "refresh") as refresh, patch.object(packet, "source_version", return_value="1.0.0"), patch.object(packet, "run") as run:
            packet.install_packet("codex", update=True)
            refresh.assert_called_once()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
