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

_CREDENTIAL_CONFIG_PATHS = frozenset(
    (
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AZURE_CONFIG_DIR",
        "CLOUDSDK_CONFIG",
        "DOCKER_CONFIG",
        "GCLOUD_CONFIG",
        "GH_CONFIG_DIR",
        "GITHUB_CONFIG_DIR",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "KUBECONFIG",
        "NETRC",
        "NPM_CONFIG_USERCONFIG",
        "OCI_CONFIG_FILE",
        "PIP_CONFIG_FILE",
        "TF_CLI_CONFIG_FILE",
    )
)
_UNRELATED_CREDENTIAL_FAMILIES = (
    "AWS_",
    "AZURE_",
    "BITBUCKET_",
    "CLOUDSDK_",
    "GCLOUD_",
    "GCP_",
    "GITHUB_",
    "GITLAB_",
    "GOOGLE_",
    "OCI_",
)
_UNRELATED_CREDENTIAL_HINTS = (
    "ACCESS",
    "ACCOUNT",
    "AUTH",
    "CLIENT",
    "CONFIG",
    "CREDENTIAL",
    "IDENTITY",
    "KEY",
    "PASSWORD",
    "PAT",
    "PROFILE",
    "SECRET",
    "SUBSCRIPTION",
    "TENANT",
    "TOKEN",
)
_OPERATOR_CONFIG_ROOTS = frozenset(("HOME", "XDG_CONFIG_HOME"))
_SERVICE_CREDENTIALS = frozenset(
    (
        "DATABASE_URL",
        "DB_PASSWORD",
        "DOCKER_AUTH_CONFIG",
        "MONGODB_URI",
        "MYSQL_PWD",
        "PGPASSWORD",
        "REDIS_URL",
        "STRIPE_SECRET_KEY",
    )
)


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


def _git(cwd: Path, arguments: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            env=None if env is None else dict(env),
            check=False,
            capture_output=True,
            text=False,
        )
    except FileNotFoundError as error:
        raise ValueError(f"Git common directory is unavailable: {cwd}") from error


def _output(result: subprocess.CompletedProcess[bytes], action: str) -> bytes:
    if result.returncode != 0:
        message = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise ValueError(f"git {action} failed: {message or 'unknown error'}")
    return result.stdout


def _common_directory(path: Path) -> Path:
    result = _git(path, ("rev-parse", "--git-common-dir"))
    raw = _output(result, "rev-parse --git-common-dir").strip()
    if not raw:
        raise ValueError("Git common directory is missing")
    common = Path(os.fsdecode(raw))
    if not common.is_absolute():
        common = path / common
    common = common.resolve()
    if not common.is_dir():
        raise ValueError("Git common directory is not a directory")
    return common


def _head(path: Path) -> str:
    value = _output(_git(path, ("rev-parse", "HEAD")), "rev-parse HEAD").decode().strip()
    return require_full_sha(value)


def _branch(path: Path) -> str:
    value = _output(
        _git(path, ("symbolic-ref", "--quiet", "--short", "HEAD")),
        "symbolic-ref HEAD",
    ).decode().strip()
    if not value:
        raise ValueError("worktree branch is missing")
    return value


def _worktree_records(source: Path) -> list[dict[str, str]]:
    raw = _output(_git(source, ("worktree", "list", "--porcelain")), "worktree list")
    records: list[dict[str, str]] = []
    for block in raw.decode("utf-8", "surrogateescape").strip().split("\n\n"):
        record: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition(" ")
            if separator:
                record[key] = value
        if record:
            records.append(record)
    return records


def _nul_paths(cwd: Path, arguments: Sequence[str]) -> list[bytes]:
    raw = _output(_git(cwd, arguments), " ".join(arguments))
    return sorted(item for item in raw.split(b"\0") if item)


def _regular_file(worktree: Path, relative: bytes) -> Path:
    decoded = os.fsdecode(relative)
    candidate_relative = Path(decoded)
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise ValueError("Git path escapes worktree")
    current = worktree
    for part in candidate_relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise ValueError(f"cannot read worktree file {decoded!r}") from error
        if stat.S_ISLNK(mode):
            raise ValueError("symlink worktree entries are not allowed")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(worktree)
    except ValueError as error:
        raise ValueError("Git path escapes worktree") from error
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("worktree entries must be regular files")
    if resolved.stat().st_size > MAX_HASH_BYTES:
        raise ValueError("worktree file exceeds bounded hash limit")
    return resolved


def _file_hash(worktree: Path, path: bytes) -> str:
    candidate = _regular_file(worktree, path)
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            while block := handle.read(64 * 1024):
                digest.update(block)
    except OSError as error:
        raise ValueError("cannot read worktree file") from error
    return digest.hexdigest()


def _index_hash(worktree: Path, path: bytes) -> str | None:
    path_text = os.fsdecode(path)
    size = _git(worktree, ("cat-file", "-s", f":{path_text}"))
    if size.returncode != 0:
        return None
    try:
        byte_count = int(size.stdout.strip())
    except ValueError as error:
        raise ValueError("Git index blob size is invalid") from error
    if byte_count > MAX_HASH_BYTES:
        raise ValueError("Git index blob exceeds bounded hash limit")
    blob = _output(_git(worktree, ("show", f":{path_text}")), "show index blob")
    if len(blob) != byte_count:
        raise ValueError("Git index blob size changed while hashing")
    return hashlib.sha256(blob).hexdigest()


def _observation_digests(worktree: Path) -> tuple[str, str, bool]:
    porcelain = _output(
        _git(worktree, ("status", "--porcelain=v2", "-z")),
        "status --porcelain=v2",
    )
    entries = sorted(item for item in porcelain.split(b"\0") if item)
    porcelain_digest = hashlib.sha256(b"\0".join(entries)).hexdigest()
    content: list[bytes] = []
    for path in _nul_paths(worktree, ("diff", "--name-only", "-z", "HEAD")):
        candidate = worktree / Path(os.fsdecode(path))
        if candidate.exists() or candidate.is_symlink():
            content.append(b"worktree\0" + path + b"\0" + _file_hash(worktree, path).encode())
    for path in _nul_paths(worktree, ("diff", "--cached", "--name-only", "-z")):
        digest = _index_hash(worktree, path)
        if digest is not None:
            content.append(b"index\0" + path + b"\0" + digest.encode())
    for path in _nul_paths(worktree, ("ls-files", "--others", "--exclude-standard", "-z")):
        content.append(b"untracked\0" + path + b"\0" + _file_hash(worktree, path).encode())
    tree_digest = hashlib.sha256(b"\0".join(sorted([*entries, *content]))).hexdigest()
    return porcelain_digest, tree_digest, not entries


@dataclass(frozen=True)
class GitWorkspace:
    source: Path
    worktree: Path
    branch: str
    _common_dir: Path
    _protected_refs: dict[str, str] = field(repr=False, compare=False)

    @classmethod
    def create(cls, source: Path, worktree: Path, branch: str) -> "GitWorkspace":
        source_path = Path(source).resolve()
        worktree_path = Path(worktree).resolve()
        if _output(_git(source_path, ("status", "--porcelain=v2", "-z")), "status").strip():
            raise ValueError("source worktree must be clean")
        if worktree_path.exists():
            raise ValueError("worktree already exists")
        if _git(source_path, ("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")).returncode == 0:
            raise ValueError("assigned plan branch already exists")
        starting_head = _head(source_path)
        _output(
            _git(source_path, ("worktree", "add", "-b", branch, str(worktree_path), starting_head)),
            "worktree add",
        )
        return cls.open(source_path, worktree_path, branch)

    @classmethod
    def open(cls, source: Path, worktree: Path, branch: str) -> "GitWorkspace":
        source_path = Path(source).resolve()
        worktree_path = Path(worktree).resolve()
        if not worktree_path.is_dir():
            raise ValueError("worktree is not the exact registered branch worktree")
        source_common = _common_directory(source_path)
        worktree_common = _common_directory(worktree_path)
        if source_common != worktree_common:
            raise ValueError("Git common directory does not match source")
        expected = str(worktree_path)
        matching = [record for record in _worktree_records(source_path) if record.get("worktree") == expected]
        if len(matching) != 1 or matching[0].get("branch") != f"refs/heads/{branch}":
            raise ValueError("worktree is not the exact registered branch worktree")
        instance = cls(source_path, worktree_path, branch, source_common, {})
        return cls(source_path, worktree_path, branch, source_common, instance.protected_refs())

    def protected_refs(self) -> dict[str, str]:
        raw = _output(
            _git(self.worktree, ("for-each-ref", "--format=%(refname)\t%(objectname)")),
            "for-each-ref",
        )
        protected: dict[str, str] = {}
        assigned = f"refs/heads/{self.branch}"
        for line in raw.decode("utf-8", "surrogateescape").splitlines():
            name, separator, object_id = line.partition("\t")
            if not separator or name == assigned:
                continue
            protected[name] = require_full_sha(object_id)
        return protected

    def require_identity(self) -> WorktreeObservation:
        if _common_directory(self.source) != self._common_dir or _common_directory(self.worktree) != self._common_dir:
            raise ValueError("Git common directory drift detected")
        if _branch(self.worktree) != self.branch:
            raise ValueError("worktree branch drift detected")
        records = _worktree_records(self.source)
        registered = [record for record in records if record.get("worktree") == str(self.worktree)]
        if len(registered) != 1 or registered[0].get("branch") != f"refs/heads/{self.branch}":
            raise ValueError("registered worktree identity drift detected")
        porcelain_digest, tree_digest, clean = _observation_digests(self.worktree)
        return WorktreeObservation(_head(self.worktree), self.branch, porcelain_digest, tree_digest, clean)

    def observe(self) -> WorktreeObservation:
        return self.require_identity()

    def require_clean_ancestor(self, starting_commit: str) -> WorktreeObservation:
        starting_commit = require_full_sha(starting_commit)
        observation = self.require_identity()
        ancestor = _git(self.worktree, ("merge-base", "--is-ancestor", starting_commit, observation.head))
        if ancestor.returncode != 0:
            raise ValueError("starting commit is not an ancestor of worktree HEAD")
        if not observation.clean:
            raise ValueError("worktree must be clean")
        if self.protected_refs() != self._protected_refs:
            raise ValueError("protected ref mutation detected")
        return observation


def sanitized_child_env(
    source_env: Mapping[str, str],
    *,
    provider_auth_prefixes: Sequence[str],
    remotes: Sequence[str],
    run_id: str,
) -> dict[str, str]:
    """Return a child environment that blocks accidental Git remote mutation.

    The push-url overrides and credential scrubbing are accidental-mutation
    guards only; they do not provide hard isolation from another process with
    the same user identity.
    """
    allowed_prefixes = tuple(provider_auth_prefixes)
    clean: dict[str, str] = {}
    for key, value in source_env.items():
        if key in {"SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND"}:
            continue
        if key == "GIT_CONFIG_COUNT" or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            continue
        if key in _OPERATOR_CONFIG_ROOTS:
            continue
        credential = key.endswith(("_TOKEN", "_SECRET", "_API_KEY"))
        provider_auth = key.startswith(allowed_prefixes)
        unrelated_family_credential = key.startswith(_UNRELATED_CREDENTIAL_FAMILIES) and any(
            hint in key for hint in _UNRELATED_CREDENTIAL_HINTS
        )
        if not provider_auth and (
            credential
            or key in _CREDENTIAL_CONFIG_PATHS
            or key in _SERVICE_CREDENTIALS
            or unrelated_family_credential
        ):
            continue
        clean[str(key)] = str(value)
    safe_remotes: list[str] = []
    for remote in sorted(set(remotes)):
        if not isinstance(remote, str) or not remote or any(ord(character) < 32 or ord(character) == 127 for character in remote):
            raise ValueError("remote name contains control characters")
        safe_remotes.append(remote)
    if any(ord(character) < 32 or ord(character) == 127 for character in run_id):
        raise ValueError("run id contains control characters")
    for index, remote in enumerate(safe_remotes):
        clean[f"GIT_CONFIG_KEY_{index}"] = f"remote.{remote}.pushurl"
        clean[f"GIT_CONFIG_VALUE_{index}"] = f"disabled://plan-runner/{run_id}/{remote}"
    clean["GIT_CONFIG_COUNT"] = str(len(safe_remotes))
    clean["GIT_TERMINAL_PROMPT"] = "0"
    return clean
