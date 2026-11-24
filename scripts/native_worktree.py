#!/usr/bin/env python3
"""Run a native CLI in a detached Git worktree. No Docker required."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

DELEGATE = Path(__file__).resolve().with_name("delegate.py")
RUN_ID = re.compile(r"[a-f0-9]{32}\Z")


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
         "-c", "core.fsmonitor=false", "-c", "submodule.recurse=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def check_tracked_files(repo, commit):
    names = git(repo, "ls-tree", "-r", "--name-only", "-z", commit).split("\0")
    for name in names:
        n = Path(name).name.lower()
        if (n == ".env" or (n.startswith(".env.") and n not in {".env.example", ".env.sample", ".env.template"})
                or n in {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"}
                or n.endswith((".pem", ".key", ".p12", ".pfx"))):
            raise ValueError(f"Potential secret tracked in the snapshot: {name}")


def private_root():
    root = Path.home() / ".oil-delegate" / "native-worktrees"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError("Native worktree state must be a private directory owned by the current user")
    return root


def store(path, data):
    temp = path.with_name(".metadata-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def command(args, workspace, session):
    cmd = [sys.executable, str(DELEGATE), "run", "--runner", args.runner,
           "--workspace", str(workspace), "--mode", "write",
           "--timeout", str(args.timeout), "--json", "--prompt", args.prompt]
    if session:
        cmd += ["--session", session]
    for name in args.file:
        cmd += ["--file", name]
    return cmd


def execute(args):
    if not 1 <= args.timeout <= 3600:
        raise ValueError("Timeout must be between 1 and 3600 seconds")
    repo = Path(git(Path(args.workspace).expanduser().resolve(), "rev-parse", "--show-toplevel")).resolve()
    run_id = args.resume_run or uuid.uuid4().hex
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID")
    root = private_root() / run_id
    if args.resume_run:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Unknown native run")
    else:
        root.mkdir(mode=0o700)
    workspace = root / "workspace"
    meta_path = root / "metadata.json"
    lock_fd = os.open(root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.resume_run:
            if meta_path.is_symlink() or workspace.is_symlink():
                raise ValueError("Unexpected symlink in run state")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("repo") != str(repo) or meta.get("runner") != args.runner:
                raise ValueError("Resume requires the same repository and runner")
            if not meta.get("session"):
                raise ValueError("No saved session; refusing to start an unrelated replacement")
            if Path(git(workspace, "rev-parse", "--show-toplevel")).resolve() != workspace:
                raise ValueError("Worktree path has changed")
            if git(workspace, "rev-parse", "HEAD") != meta["head"]:
                raise ValueError("Worktree HEAD changed; inspect manually before continuing")
        else:
            head = git(repo, "rev-parse", "HEAD")
            check_tracked_files(repo, head)
            git(repo, "worktree", "add", "--detach", str(workspace), head)
            meta = {"repo": str(repo), "runner": args.runner, "head": head, "session": None}
            store(meta_path, meta)
        # Entry files are relative to the committed checkout, never the host's original directory.
        for name in args.file:
            p = Path(name)
            if p.is_absolute() or not (workspace / p).resolve().is_relative_to(workspace):
                raise ValueError("Entry files must stay inside the detached worktree")
        print(json.dumps({"run_id": run_id, "worktree": str(workspace), "status": "starting"}),
              file=sys.stderr, flush=True)
        proc = subprocess.run(command(args, workspace, meta["session"]), text=True, capture_output=True)
        try:
            result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                result = {}
        except ValueError:
            result = {}
        sid = result.get("session_id")
        if isinstance(sid, str) and 0 < len(sid) <= 512:
            meta["session"] = sid
            store(meta_path, meta)
        success = proc.returncode == 0 and result.get("status") == "completed"
        print(json.dumps({
            "status": "completed" if success else "failed", "run_id": run_id,
            "worktree": str(workspace), "base_commit": meta["head"], "session_id": meta["session"],
            "output_path": result.get("output_path"), "result_path": result.get("result_path"),
            "error": result.get("error") or result.get("message") if not success else None,
            "exit_code": proc.returncode,
        }, ensure_ascii=False))
        return 0 if success else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, choices=("dsh", "codex", "claude", "claude-volces", "claude-minimax"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--resume-run")
    args = parser.parse_args(argv)
    try:
        return execute(args)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc) if isinstance(exc, ValueError)
                          else "Native worktree failed; inspect local Git setup and retained run state."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
