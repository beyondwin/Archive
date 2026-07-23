from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import require_digest, require_full_sha

MAX_HASH_BYTES = 8 * 1024 * 1024


def _git(cwd: Path, *arguments: str, env: Mapping[str, str] | None = None) -> bytes:
    try:
        process = subprocess.run(
            ["git", *arguments], cwd=cwd,
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise ValueError(f"Git is unavailable for {cwd}") from error
    if process.returncode:
        detail = (process.stderr or process.stdout).decode("utf-8", "replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail or 'unknown error'}")
    return process.stdout


def _head(repo: Path) -> str:
    return require_full_sha(_git(repo, "rev-parse", "HEAD").decode().strip())


def _branch(repo: Path) -> str:
    name = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    if not name:
        raise ValueError("worktree branch is missing")
    return name


def _common(repo: Path) -> Path:
    raw = _git(repo, "rev-parse", "--git-common-dir").decode().strip()
    if not raw:
        raise ValueError("Git common directory is missing")
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else repo / candidate).resolve()
    if not resolved.is_dir():
        raise ValueError("Git common directory is not a directory")
    return resolved


def _registered(source: Path) -> list[dict[str, str]]:
    blocks = _git(source, "worktree", "list", "--porcelain").decode(
        "utf-8", "surrogateescape"
    ).strip().split("\n\n")
    result = []
    for block in blocks:
        record = {}
        for line in block.splitlines():
            key, separator, value = line.partition(" ")
            if separator:
                record[key] = value
        if record:
            result.append(record)
    return result


def _paths(repo: Path, *arguments: str) -> list[bytes]:
    return sorted(value for value in _git(repo, *arguments).split(b"\0") if value)


def _safe_file(root: Path, encoded_path: bytes) -> Path:
    relative = Path(os.fsdecode(encoded_path))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Git path escapes worktree")
    current = root
    for component in relative.parts:
        current /= component
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise ValueError("worktree file is unavailable") from error
        if stat.S_ISLNK(mode):
            raise ValueError("symlink worktree entries are not allowed")
    resolved = current.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Git path escapes worktree") from error
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_HASH_BYTES:
        raise ValueError("worktree file cannot be safely hashed")
    return resolved


def _hash_file(root: Path, relative: bytes) -> str:
    digest = hashlib.sha256()
    with _safe_file(root, relative).open("rb") as stream:
        while piece := stream.read(65536):
            digest.update(piece)
    return digest.hexdigest()


def _hash_index(repo: Path, relative: bytes) -> str | None:
    name = os.fsdecode(relative)
    probe = subprocess.run(
        ["git", "cat-file", "-s", f":{name}"], cwd=repo,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if probe.returncode:
        return None
    try:
        length = int(probe.stdout)
    except ValueError as error:
        raise ValueError("Git index blob size is invalid") from error
    if length > MAX_HASH_BYTES:
        raise ValueError("Git index blob exceeds bounded hash limit")
    blob = _git(repo, "show", f":{name}")
    if len(blob) != length:
        raise ValueError("Git index blob size changed while hashing")
    return hashlib.sha256(blob).hexdigest()


def _digests(repo: Path) -> tuple[str, str, bool]:
    status = _git(repo, "status", "--porcelain=v2", "-z")
    rows = sorted(item for item in status.split(b"\0") if item)
    porcelain = hashlib.sha256(b"\0".join(rows)).hexdigest()
    content: list[bytes] = []
    for relative in _paths(repo, "diff", "--name-only", "-z", "HEAD"):
        candidate = repo / os.fsdecode(relative)
        if candidate.exists() or candidate.is_symlink():
            content.append(b"w\0" + relative + b"\0" + _hash_file(repo, relative).encode())
    for relative in _paths(repo, "diff", "--cached", "--name-only", "-z"):
        if (digest := _hash_index(repo, relative)) is not None:
            content.append(b"i\0" + relative + b"\0" + digest.encode())
    for relative in _paths(repo, "ls-files", "--others", "--exclude-standard", "-z"):
        content.append(b"u\0" + relative + b"\0" + _hash_file(repo, relative).encode())
    tree = hashlib.sha256(b"\0".join(sorted([*rows, *content]))).hexdigest()
    return porcelain, tree, not rows


@dataclass(frozen=True)
class WorktreeObservation:
    head: str
    branch: str
    porcelain_digest: str
    tree_digest: str
    clean: bool

    def __post_init__(self) -> None:
        require_full_sha(self.head)
        require_digest(self.porcelain_digest)
        require_digest(self.tree_digest)


@dataclass(frozen=True)
class GitWorkspace:
    source: Path
    worktree: Path
    branch: str
    _common_dir: Path
    _protected_refs: dict[str, str] = field(repr=False, compare=False)

    @classmethod
    def create(cls, source: Path, worktree: Path, branch: str) -> "GitWorkspace":
        source = Path(source).resolve()
        worktree = Path(worktree).resolve()
        if _git(source, "status", "--porcelain=v2", "-z"):
            raise ValueError("source worktree must be clean")
        if worktree.exists():
            raise ValueError("worktree already exists")
        branch_ref = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=source,
        )
        if branch_ref.returncode == 0:
            raise ValueError("assigned plan branch already exists")
        _git(source, "worktree", "add", "-b", branch, str(worktree), _head(source))
        return cls.open(source, worktree, branch)

    @classmethod
    def open(cls, source: Path, worktree: Path, branch: str) -> "GitWorkspace":
        source = Path(source).resolve()
        worktree = Path(worktree).resolve()
        if not worktree.is_dir() or _common(source) != _common(worktree):
            raise ValueError("Git common directory does not match source")
        matches = [
            row for row in _registered(source)
            if row.get("worktree") == str(worktree)
            and row.get("branch") == f"refs/heads/{branch}"
        ]
        if len(matches) != 1:
            raise ValueError("worktree is not the exact registered branch worktree")
        shell = cls(source, worktree, branch, _common(source), {})
        return cls(source, worktree, branch, shell._common_dir, shell.protected_refs())

    def protected_refs(self) -> dict[str, str]:
        output = _git(
            self.worktree, "for-each-ref", "--format=%(refname)\t%(objectname)"
        ).decode("utf-8", "surrogateescape")
        assigned = f"refs/heads/{self.branch}"
        protected = {}
        for row in output.splitlines():
            name, tab, value = row.partition("\t")
            if tab and name != assigned:
                protected[name] = require_full_sha(value)
        return protected

    def require_identity(self) -> WorktreeObservation:
        if _common(self.source) != self._common_dir or _common(self.worktree) != self._common_dir:
            raise ValueError("Git common directory drift detected")
        if _branch(self.worktree) != self.branch:
            raise ValueError("worktree branch drift detected")
        valid = [
            row for row in _registered(self.source)
            if row.get("worktree") == str(self.worktree)
            and row.get("branch") == f"refs/heads/{self.branch}"
        ]
        if len(valid) != 1:
            raise ValueError("registered worktree identity drift detected")
        porcelain, tree, clean = _digests(self.worktree)
        return WorktreeObservation(_head(self.worktree), self.branch, porcelain, tree, clean)

    def observe(self) -> WorktreeObservation:
        return self.require_identity()

    def require_clean_ancestor(self, starting_commit: str) -> WorktreeObservation:
        start = require_full_sha(starting_commit)
        observed = self.require_identity()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", start, observed.head],
            cwd=self.worktree,
        )
        if ancestor.returncode:
            raise ValueError("starting commit is not an ancestor of worktree HEAD")
        if not observed.clean:
            raise ValueError("worktree must be clean")
        if self.protected_refs() != self._protected_refs:
            raise ValueError("protected ref mutation detected")
        return observed


def sanitized_child_env(
    source_env: Mapping[str, str],
    *,
    provider_auth_prefixes: Sequence[str],
    remotes: Sequence[str],
    run_id: str,
) -> dict[str, str]:
    auth = tuple(provider_auth_prefixes)
    result: dict[str, str] = {}
    explicit = {"SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND"}
    for key, value in source_env.items():
        if key in explicit or key == "GIT_CONFIG_COUNT":
            continue
        if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            continue
        looks_secret = key.endswith(("_TOKEN", "_SECRET", "_API_KEY"))
        if looks_secret and not key.startswith(auth):
            continue
        result[str(key)] = str(value)
    names = sorted(set(remotes))
    if any(
        not isinstance(name, str)
        or not name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
        for name in names
    ):
        raise ValueError("remote name contains control characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in run_id):
        raise ValueError("run id contains control characters")
    for index, name in enumerate(names):
        result[f"GIT_CONFIG_KEY_{index}"] = f"remote.{name}.pushurl"
        result[f"GIT_CONFIG_VALUE_{index}"] = f"disabled://plan-runner/{run_id}/{name}"
    result["GIT_CONFIG_COUNT"] = str(len(names))
    result["GIT_TERMINAL_PROMPT"] = "0"
    return result
