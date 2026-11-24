import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("isolated", Path(__file__).resolve().parents[1] / "scripts" / "isolated_delegate.py")
ISOLATED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ISOLATED)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for name in ("workspace", "state", "agent-home"):
            (self.root / name).mkdir()
        (self.root / "workspace" / ".git").write_text("gitdir: not-mounted")
        self.args = argparse.Namespace(image="sha256:" + "a" * 64, mode="read", runner="dsh",
                                       allow_network=False, timeout=90)

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_read_isolation(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "model-secret", "GITHUB_TOKEN": "host-secret"}):
            cmd = ISOLATED.docker_command(["docker"], self.args, self.root, "test")
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertIn("--read-only", cmd)
        self.assertIn("no-new-privileges:true", cmd)
        self.assertIn("ALL", cmd)
        self.assertIn("never", cmd)
        self.assertIn("dst=/workspace,readonly", " ".join(cmd))
        self.assertIn("dst=/workspace/.git,readonly", " ".join(cmd))
        self.assertNotIn("DEEPSEEK_API_KEY", cmd)
        self.assertNotIn("GITHUB_TOKEN", cmd)
        self.assertNotIn("/var/run/docker.sock", " ".join(cmd))

    def test_write_and_explicit_network(self):
        self.args.mode = "write"
        self.args.allow_network = True
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "model-secret", "GITHUB_TOKEN": "host-secret"}):
            cmd = ISOLATED.docker_command(["docker"], self.args, self.root, "test", "session")
        self.assertEqual(cmd[cmd.index("--network") + 1], "bridge")
        self.assertNotIn("dst=/workspace,readonly", " ".join(cmd))
        self.assertIn("DEEPSEEK_API_KEY", cmd)
        self.assertNotIn("model-secret", cmd)
        self.assertNotIn("GITHUB_TOKEN", cmd)
        self.assertEqual(cmd[-2:], ["--session", "session"])

    def test_reject_mutable_image_and_symlink(self):
        self.args.image = "latest"
        with self.assertRaises(ISOLATED.IsolationError):
            ISOLATED.docker_command(["docker"], self.args, self.root, "test")
        link = self.root / "link"
        link.symlink_to(self.root / "state")
        with self.assertRaises(ISOLATED.IsolationError):
            ISOLATED.bind(link, "/state")

    def test_reject_known_tracked_secrets(self):
        with mock.patch.object(ISOLATED, "run_checked", return_value="src/main.py\0config/.env\0"):
            with self.assertRaises(ISOLATED.IsolationError):
                ISOLATED.check_tracked_files(self.root)
        with mock.patch.object(ISOLATED, "run_checked", return_value=".env.example\0src/main.py\0"):
            ISOLATED.check_tracked_files(self.root)

    def test_result_paths_are_bounded(self):
        path = self.root / "state" / "runs" / "20261124T010101-abcdef0123"
        path.mkdir(parents=True)
        (path / "output.md").write_text("report")
        self.assertEqual(ISOLATED.result_path(self.root, "/delegate-state/runs/20261124T010101-abcdef0123/output.md"), str(path / "output.md"))
        self.assertIsNone(ISOLATED.result_path(self.root, "/delegate-state/runs/../../output.md"))
        (path / "result.json").symlink_to("/etc/passwd")
        self.assertIsNone(ISOLATED.result_path(self.root, "/delegate-state/runs/20261124T010101-abcdef0123/result.json"))


if __name__ == "__main__":
    unittest.main()
