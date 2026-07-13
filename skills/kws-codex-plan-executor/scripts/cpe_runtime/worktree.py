"""Ownership and handoff checks for one isolated CPE Git worktree."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")


def _git(path: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git command failed: {detail or arguments[0]}")
    return completed


def _repository_root(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Git repository is unavailable: {path}") from exc
    if not resolved.is_dir():
        raise ValueError("Git repository path must be a directory")
    completed = _git(resolved, "rev-parse", "--show-toplevel")
    try:
        root = Path(completed.stdout.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("Git repository root is invalid") from exc
    if root != resolved:
        raise ValueError("Git repository path must be the checkout root")
    return root


def _common_git_dir(path: Path) -> Path:
    raw = _git(path, "rev-parse", "--git-common-dir").stdout.decode("utf-8").strip()
    declared = Path(raw)
    if not declared.is_absolute():
        declared = path / declared
    try:
        return declared.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Git common directory is unavailable") from exc


def _head(path: Path) -> str:
    value = _git(path, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode(
        "ascii"
    ).strip()
    if _COMMIT.fullmatch(value) is None:
        raise ValueError("Git HEAD is not a full commit hash")
    return value


def _status(path: Path, *, include_untracked: bool) -> tuple[str, ...]:
    value = "all" if include_untracked else "no"
    raw = _git(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        f"--untracked-files={value}",
    ).stdout
    try:
        entries = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise ValueError("Git status contains a non-UTF-8 path") from exc
    if entries[-1:] != [""]:
        raise ValueError("Git status output is incomplete")
    return tuple(entries[:-1])


@dataclass(frozen=True)
class Worktree:
    source: Path
    root: Path
    branch: str
    base_commit: str

    @classmethod
    def create(cls, *, source: Path, root: Path, run_id: str) -> "Worktree":
        source_root = _repository_root(source)
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run_id is not safe for a CPE worktree branch")
        branch = f"codex/{run_id}"
        if _status(source_root, include_untracked=False):
            raise ValueError("source checkout has tracked changes")
        base_commit = _head(source_root)

        declared_root = root.expanduser()
        if declared_root.exists() or declared_root.is_symlink():
            raise ValueError("isolated worktree path already exists")
        resolved_root = declared_root.resolve(strict=False)
        if resolved_root.is_relative_to(source_root):
            raise ValueError("isolated worktree must not be inside the source checkout")
        if not resolved_root.parent.is_dir() or resolved_root.parent.is_symlink():
            raise ValueError("isolated worktree parent must be an existing directory")

        completed = subprocess.run(
            [
                "git",
                "-C",
                str(source_root),
                "worktree",
                "add",
                "-b",
                branch,
                str(resolved_root),
                base_commit,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"could not create isolated worktree: {detail}")
        worktree = cls(
            source=source_root,
            root=resolved_root.resolve(strict=True),
            branch=branch,
            base_commit=base_commit,
        )
        worktree.verify_identity()
        if worktree.head() != base_commit or worktree.status():
            raise ValueError("new isolated worktree did not start clean at source HEAD")
        return worktree

    @classmethod
    def open(
        cls,
        *,
        source: Path,
        root: Path,
        branch: str,
        base_commit: str,
    ) -> "Worktree":
        source_root = _repository_root(source)
        worktree_root = _repository_root(root)
        if not isinstance(branch, str) or not branch.startswith("codex/"):
            raise ValueError("worktree branch must use the codex/ namespace")
        if not isinstance(base_commit, str) or _COMMIT.fullmatch(base_commit) is None:
            raise ValueError("base_commit must be a full Git commit hash")
        worktree = cls(source_root, worktree_root, branch, base_commit)
        worktree.verify_identity()
        return worktree

    def head(self) -> str:
        return _head(self.root)

    def status(self) -> tuple[str, ...]:
        return _status(self.root, include_untracked=True)

    def verify_identity(self) -> None:
        source_root = _repository_root(self.source)
        worktree_root = _repository_root(self.root)
        if source_root != self.source or worktree_root != self.root:
            raise ValueError("worktree paths no longer match their recorded identity")
        if _common_git_dir(source_root) != _common_git_dir(worktree_root):
            raise ValueError("isolated worktree is not owned by the source repository")
        branch = _git(worktree_root, "symbolic-ref", "--quiet", "--short", "HEAD")
        current_branch = branch.stdout.decode("utf-8").strip()
        if current_branch != self.branch:
            raise ValueError("isolated worktree branch identity changed")
        if _git(
            worktree_root,
            "merge-base",
            "--is-ancestor",
            self.base_commit,
            "HEAD",
            check=False,
        ).returncode != 0:
            raise ValueError("isolated worktree HEAD is not based on the recorded commit")

    def verify_read_only_handoff(
        self, before_head: str, before_status: tuple[str, ...]
    ) -> None:
        self.verify_identity()
        if self.head() != before_head:
            raise ValueError("read-only child changed the worktree HEAD")
        if self.status() != before_status:
            raise ValueError("read-only child changed the visible worktree status")

    def verify_write_handoff(self, reported_commit: str) -> None:
        self.verify_identity()
        if not isinstance(reported_commit, str) or reported_commit != self.head():
            raise ValueError("write child commit does not equal worktree HEAD")
        if self.status():
            raise ValueError("write child left a dirty worktree")

    def diff(self, start: str, end: str) -> str:
        for name, value in (("start", start), ("end", end)):
            if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
                raise ValueError(f"{name} must be a full Git commit hash")
        return _git(self.root, "diff", "--binary", "--no-ext-diff", start, end, "--").stdout.decode(
            "utf-8", errors="replace"
        )
