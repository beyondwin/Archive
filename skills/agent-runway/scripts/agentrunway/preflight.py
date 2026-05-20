from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


CHECKED_SURFACE = (
    "adapter_binary",
    "run_dir_write",
    "worktree_parent_write",
    "git_identity",
    "git_common_dir",
)
SKIPPED_SURFACE = (
    "sandbox_git_worktree_write",
    "scratch_worktree_commit",
    "adapter_env_specifics",
)


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    issues: list[PreflightIssue]
    checked_surface: tuple[str, ...] = CHECKED_SURFACE
    skipped_surface: tuple[str, ...] = SKIPPED_SURFACE
    partial: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_surface": list(self.checked_surface),
            "skipped_surface": list(self.skipped_surface),
            "partial": self.partial,
        }


def _run_git(repo: Path, args: list[str], env: Mapping[str, str] | None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            env=dict(env or os.environ),
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], returncode=127, stdout="", stderr=str(exc))


def _check_git_identity(repo: Path, env: Mapping[str, str] | None) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    email = _run_git(repo, ["config", "user.email"], env)
    name = _run_git(repo, ["config", "user.name"], env)
    if email.returncode != 0 or not email.stdout.strip() or name.returncode != 0 or not name.stdout.strip():
        issues.append(PreflightIssue("git_identity_missing", "git user.name and user.email must be configured"))
    return issues


def _check_writable(path: Path, label: str) -> list[PreflightIssue]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".agentrunway-preflight"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return [PreflightIssue("path_not_writable", f"{label}: {exc}")]
    return []


def _check_adapter_binary(adapter_name: str, env: Mapping[str, str] | None) -> list[PreflightIssue]:
    if adapter_name == "local":
        return []
    binary = {"codex": "codex", "claude": "claude"}.get(adapter_name)
    if binary is None:
        return [PreflightIssue("unsupported_adapter", adapter_name)]
    if shutil.which(binary, path=dict(env or os.environ).get("PATH")) is None:
        return [PreflightIssue("missing_adapter_binary", binary)]
    return []


def run_preflight(
    *,
    adapter_name: str,
    repo: Path,
    run_dir: Path,
    worktree_root: Path,
    env: Mapping[str, str] | None = None,
) -> PreflightResult:
    issues: list[PreflightIssue] = []
    issues.extend(_check_adapter_binary(adapter_name, env))
    issues.extend(_check_writable(run_dir, "run_dir"))
    issues.extend(_check_writable(worktree_root.parent, "worktree_parent"))
    issues.extend(_check_writable(worktree_root, "worktree_root"))
    issues.extend(_check_git_identity(repo, env))
    git_dir = _run_git(repo, ["rev-parse", "--git-common-dir"], env)
    if git_dir.returncode != 0 or not git_dir.stdout.strip():
        issues.append(PreflightIssue("git_common_dir_unavailable", git_dir.stderr.strip() or "unknown git error"))
    return PreflightResult(ok=not issues, issues=issues)
