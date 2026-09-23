import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("codex_packet", Path(__file__).resolve().parents[2] / "plugins/numaco-hub/scripts/codex_packet.py")
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


class PacketTests(unittest.TestCase):
    def test_install_only_missing_and_disabled_plugins(self):
        names = packet.packet_names()
        before = {"installed": [{"name": n, "enabled": n != names[1]} for n in names[1:]],
                  "available": [{"name": names[0]}]}
        after = {"installed": [{"name": n, "enabled": True} for n in names], "available": []}
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
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "source_version", side_effect=lambda entry: "1.0.1" if entry["name"] == names[0] else "1.0.0"), patch.object(packet, "run", return_value={"pluginId": names[0] + "@numaco"}) as run:
            packet.install_packet("codex")
            run.assert_called_once_with(["codex", "plugin", "add", names[0] + "@numaco", "--json"], json_output=True)

    def test_verification_detects_disabled_dependency(self):
        state = {"installed": [{"name": n, "enabled": True} for n in packet.packet_names()], "available": []}
        failed = {"installed": [], "available": []}
        with patch.object(packet, "catalog", side_effect=[state, failed]):
            with self.assertRaisesRegex(RuntimeError, "still missing or disabled"):
                packet.install_packet("codex")

    def test_dirty_git_marketplace_never_refreshes(self):
        entry = {"marketplaceSource": {"sourceType": "git"}, "source": {"source": "local", "path": "/repo/plugin"}}
        with patch.object(packet.shutil, "which", return_value="git"), patch.object(packet, "run", side_effect=["/repo", " M mail.py\n?? .codex-marketplace-install.json"]) as run:
            with self.assertRaisesRegex(RuntimeError, "Preserve or commit"):
                packet.refresh("codex", [entry])
            self.assertFalse(any("upgrade" in call.args[0] for call in run.call_args_list))

    def test_local_marketplace_does_not_fetch(self):
        with patch.object(packet, "run") as run:
            packet.refresh("codex", [{"marketplaceSource": {"sourceType": "local"}}])
            run.assert_not_called()

    def test_update_leaves_unchanged_enabled_plugins_alone(self):
        state = {"installed": [{"name": n, "enabled": True, "version": "1.0.0"} for n in packet.packet_names()]}
        with patch.object(packet, "catalog", return_value=state), patch.object(packet, "refresh") as refresh, patch.object(packet, "source_version", return_value="1.0.0"), patch.object(packet, "run") as run:
            packet.install_packet("codex", update=True)
            refresh.assert_called_once()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
