from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from .git_ops import Git


def _remote_url(repo: Path) -> str:
    result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _main_branch_ref(repo: Path) -> str:
    result = subprocess.run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo, text=True, capture_output=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().replace("refs/remotes/origin/", "refs/heads/")
    return "refs/heads/main"


def workspace_id(repo: Path) -> str:
    git = Git(repo)
    common = git.common_dir()
    basename = common.parent.name if common.name == ".git" else common.name
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", basename).strip("-").lower() or "repo"
    basis = f"{common}\n{_remote_url(repo)}\n{_main_branch_ref(repo)}"
    return f"{slug}-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:10]}"


def branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo)
    return result.returncode == 0


def next_available_run_id(repo: Path, base: str) -> str:
    candidate = base
    suffix_ord = ord("a")
    if re.search(r"-[a-z]$", candidate):
        stem = candidate[:-2]
        suffix_ord = ord(candidate[-1])
    else:
        stem = candidate
    while branch_exists(repo, f"agentrunway/{candidate}/main"):
        suffix_ord += 1
        candidate = f"{stem}-{chr(suffix_ord)}"
    return candidate


def create_main_worktree(git: Git, target: Path, run_id: str, base_commit: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = f"agentrunway/{run_id}/main"
    if branch_exists(git.root, branch):
        raise RuntimeError(f"branch already exists: {branch}")
    git.run("worktree", "add", "-b", branch, str(target), base_commit)
    return target
