#!/usr/bin/env python3
"""Opt-in isolated CLI delegation; never mounts the host home or Docker socket."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

IMAGE = re.compile(r"(?:[^@\s]+@)?sha256:[a-f0-9]{64}\Z")
RUN_ID = re.compile(r"[a-f0-9]{32}\Z")
RESULT_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[a-f0-9]{10}\Z")
KEYS = {
    "dsh": ("DEEPSEEK_API_KEY", "DSH_API_KEY"),
    "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
}
SCRIPT = Path(__file__).resolve().with_name("delegate.py")


class IsolationError(Exception):
    pass


def run_checked(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def git(repo, *args):
    return ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false", "-c", "submodule.recurse=false", *args]


def check_tracked_files(repo):
    names = run_checked(git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD")).split("\0")
    for name in names:
        p = Path(name)
        n = p.name.lower()
        if (n == ".env" or (n.startswith(".env.") and n not in {".env.example", ".env.sample", ".env.template"})
                or n in {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"}
                or n.endswith((".pem", ".key", ".p12", ".pfx"))):
            raise IsolationError(f"Potential secret tracked in HEAD: {name}; remove it before delegation")


def local_docker():
    binary = shutil.which("docker")
    if not binary:
        raise IsolationError("Docker CLI is required; no unisolated fallback")
    if os.environ.get("DOCKER_CONTEXT"):
        context = os.environ["DOCKER_CONTEXT"]
        endpoint = run_checked([binary, "context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"])
    elif os.environ.get("DOCKER_HOST"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        context = run_checked([binary, "context", "show"])
        endpoint = run_checked([binary, "context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"])
    if not endpoint.startswith("unix://"):
        raise IsolationError("Only a local Unix-socket Docker daemon is supported")
    env = os.environ.copy()
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    return [binary, "--host", endpoint], env


def bind(source: Path, target: str, readonly=False):
    if source.is_symlink() or "," in str(source) or "\n" in str(source):
        raise IsolationError(f"Unsafe bind source: {source}")
    return f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")


def docker_command(docker, args, root: Path, name: str, session=None):
    if not IMAGE.fullmatch(args.image):
        raise IsolationError("Use a trusted local image pinned by sha256 digest or image ID")
    cmd = [*docker, "run", "--rm", "--name", name, "--pull", "never",
           "--init", "--read-only", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges:true",
           "--user", f"{os.getuid()}:{os.getgid()}",
           "--pids-limit", "256", "--memory", "4g", "--cpus", "2",
           "--network", "bridge" if args.allow_network else "none",
           "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
           "--workdir", "/workspace", "--entrypoint", "python3",
           "--mount", bind(root / "workspace", "/workspace", args.mode == "read"),
           "--mount", bind(root / "workspace" / ".git", "/workspace/.git", True),
           "--mount", bind(root / "agent-home", "/agent-home"),
           "--mount", bind(root / "state", "/delegate-state"),
           "--mount", bind(SCRIPT, "/delegate.py", True),
           "--env", "HOME=/agent-home", "--env", "XDG_CONFIG_HOME=/agent-home/.config",
           "--env", "XDG_CACHE_HOME=/agent-home/.cache",
           "--env", "XDG_DATA_HOME=/agent-home/.local/share",
           "--env", "CODEX_HOME=/agent-home/.codex"]
    if args.allow_network:
        for key in KEYS[args.runner]:
            if os.environ.get(key):
                cmd += ["--env", key]
    # Use stdin to avoid putting the task in Docker's command metadata.
    cmd += ["-i", args.image, "-c",
            "import runpy,sys; sys.argv=['/delegate.py',*sys.argv[1:],'--prompt',sys.stdin.read()]; runpy.run_path('/delegate.py',run_name='__main__')",
            "--home", "/delegate-state", "run", "--runner", args.runner,
            "--workspace", "/workspace", "--mode", args.mode, "--timeout", str(args.timeout), "--json"]
    if session:
        cmd += ["--session", session]
    return cmd


def result_path(root, value):
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    if len(parts) != 5 or parts[:3] != ["", "delegate-state", "runs"]:
        return None
    if not RESULT_ID.fullmatch(parts[3]) or parts[4] not in {"output.md", "result.json"}:
        return None
    path = root / "state" / "runs" / parts[3] / parts[4]
    if not path.resolve().is_relative_to(root / "state") or not path.is_file():
        return None
    return str(path)


def store_metadata(path, metadata):
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def execute(args):
    if sys.platform not in {"darwin", "linux"} or os.getuid() == 0:
        raise IsolationError("Isolation requires macOS/Linux and a non-root local user")
    if not IMAGE.fullmatch(args.image):
        raise IsolationError("Use a trusted local image pinned by sha256 digest or image ID")
    if not 1 <= args.timeout <= 3600:
        raise IsolationError("Timeout must be between 1 and 3600 seconds")
    repo = Path(run_checked(git(Path(args.workspace).expanduser().resolve(), "rev-parse", "--show-toplevel"))).resolve()
    docker, docker_env = local_docker()
    run_checked([*docker, "image", "inspect", args.image], env=docker_env)
    home = Path.home() / ".oil-delegate" / "isolated"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if home.is_symlink() or home.stat().st_uid != os.getuid() or home.stat().st_mode & 0o077:
        raise IsolationError("Isolation state directory must be private and owned by the current user")
    identity = {"repo": str(repo), "runner": args.runner, "mode": args.mode, "image": args.image}
    run_id = args.resume_run or uuid.uuid4().hex
    if not RUN_ID.fullmatch(run_id):
        raise IsolationError("Invalid run ID")
    root = home / run_id
    if args.resume_run:
        if root.is_symlink() or not root.is_dir():
            raise IsolationError("Unknown isolated run")
    else:
        check_tracked_files(repo)
        root.mkdir(mode=0o700)
    with (root / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IsolationError("This isolated run is already active") from exc
        metadata_path = root / "metadata.json"
        if args.resume_run:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if any(metadata.get(k) != v for k, v in identity.items()):
                raise IsolationError("Resume requires the same repository, runner, mode and image")
            if not metadata.get("session"):
                raise IsolationError("No recorded session; refusing to start an unrelated replacement")
        else:
            head = run_checked(git(repo, "rev-parse", "HEAD"))
            run_checked(git(repo, "worktree", "add", "--detach", str(root / "workspace"), head))
            for child in ("state", "agent-home"):
                (root / child).mkdir(mode=0o700)
            metadata = {**identity, "head": head, "session": None,
                        "git_pointer": (root / "workspace" / ".git").read_text(encoding="utf-8")}
            store_metadata(metadata_path, metadata)
        git_pointer = root / "workspace" / ".git"
        if git_pointer.is_symlink() or git_pointer.read_text(encoding="utf-8") != metadata["git_pointer"]:
            raise IsolationError("Worktree metadata changed; refusing execution")
        name = "oil-delegate-" + uuid.uuid4().hex
        command = docker_command(docker, args, root, name, metadata["session"])
        # Print run ID before starting so interruption does not lose the checkout location.
        print(json.dumps({"run_id": run_id, "worktree": str(root / "workspace"),
                          "base_commit": metadata["head"], "status": "starting"}), file=sys.stderr, flush=True)
        try:
            proc = subprocess.run(command, input=args.prompt, text=True, capture_output=True,
                                  env=docker_env, timeout=args.timeout + 60)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            subprocess.run([*docker, "rm", "-f", name], capture_output=True, env=docker_env, timeout=20)
            raise IsolationError(f"Interrupted; worktree retained. Run ID: {run_id}")
        try:
            result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                result = {}
        except ValueError:
            result = {}
        session = result.get("session_id")
        if isinstance(session, str) and 0 < len(session) <= 512:
            metadata["session"] = session
            store_metadata(metadata_path, metadata)
        summary = {
            "status": "completed" if proc.returncode == 0 and result.get("status") == "completed" else "failed",
            "exit_code": proc.returncode, "run_id": run_id, "worktree": str(root / "workspace"),
            "base_commit": metadata["head"], "session_id": metadata["session"],
            "output_path": result_path(root, result.get("output_path")),
            "result_path": result_path(root, result.get("result_path")),
            "network": "bridge (unrestricted egress)" if args.allow_network else "disabled",
        }
        # Runner output and repository content are untrusted. Never auto-apply or push changes.
        print(json.dumps(summary, ensure_ascii=False))
        if summary["status"] != "completed":
            print("Delegation failed; inspect the private state directory and check image/credentials/network.", file=sys.stderr)
        return 0 if summary["status"] == "completed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", choices=tuple(KEYS), required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--image", required=True, help="Trusted, locally installed digest-pinned image with Python and runner")
    parser.add_argument("--mode", choices=("read", "write"), default="read")
    parser.add_argument("--allow-network", action="store_true", help="Explicitly enable bridge networking and selected model credentials; no egress filtering")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--resume-run")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args(argv)
    try:
        return execute(args)
    except (IsolationError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Isolation failed: {type(exc).__name__}: {exc if isinstance(exc, IsolationError) else 'check local configuration'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
