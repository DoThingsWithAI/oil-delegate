import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("native_worktree", Path(__file__).resolve().parents[1] / "scripts" / "native_worktree.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class NativeWorktreeTests(unittest.TestCase):
    def test_native_command_has_no_container_dependency(self):
        args = argparse.Namespace(runner="dsh", timeout=60, prompt="test", file=["main.py"])
        cmd = NATIVE.command(args, Path("/tmp/checkout"), "session-id")
        self.assertIn("write", cmd)
        self.assertIn("dsh", cmd)
        self.assertNotIn("docker", cmd)
        self.assertEqual(cmd[cmd.index("--session") + 1], "session-id")

    def test_claude_native_write_uses_existing_runner(self):
        args = argparse.Namespace(runner="claude", timeout=60, prompt="edit", file=[])
        cmd = NATIVE.command(args, Path("/tmp/checkout"), "session-id")
        self.assertEqual(cmd[cmd.index("--runner") + 1], "claude")
        self.assertEqual(cmd[cmd.index("--mode") + 1], "write")
        self.assertNotIn("--model", cmd)

    def test_snapshot_excludes_dirty_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "main.py").write_text("committed")
            NATIVE.git(repo, "add", "main.py")
            NATIVE.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial")
            head = NATIVE.git(repo, "rev-parse", "HEAD")
            (repo / "main.py").write_text("dirty")
            (repo / ".env").write_text("local-only")
            checkout = root / "checkout"
            NATIVE.check_tracked_files(repo, head)
            NATIVE.git(repo, "worktree", "add", "--detach", str(checkout), head)
            self.assertEqual((checkout / "main.py").read_text(), "committed")
            self.assertFalse((checkout / ".env").exists())
            (checkout / "main.py").write_text("child change")
            self.assertEqual((repo / "main.py").read_text(), "dirty")
            NATIVE.git(repo, "add", ".env")
            NATIVE.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "secret")
            with self.assertRaises(ValueError):
                NATIVE.check_tracked_files(repo, NATIVE.git(repo, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
