from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from .contracts import require_digest, require_full_sha


MAX_HASH_BYTES = 8 * 1024 * 1024
MAX_GIT_IDENTITY_BYTES = 1024
VOLATILE_REF_POLICY_VERSION = 1

_VOLATILE_REF_PREFIXES = (
    "refs/codex/turn-diffs/captures/",
    "refs/codex/turn-diffs/checkpoints/",
)

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
_GENERIC_CREDENTIAL_SUFFIXES = (
    "_TOKEN",
    "_SECRET",
    "_API_KEY",
    "_PASSWORD",
    "_PASSWD",
    "_PRIVATE_KEY",
    "_SECRET_KEY",
    "_ACCESS_KEY",
    "_CREDENTIAL",
    "_CREDENTIALS",
    "_CONNECTION_STRING",
)
_SERVICE_CREDENTIALS = frozenset(
    (
        "DOCKER_AUTH_CONFIG",
        "MONGODB_URI",
        "MYSQL_PWD",
        "PGPASSWORD",
    )
)
_GIT_ENV_INJECTION_KEYS = frozenset(
    (
        "EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_DATE",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM",
    )
)
_GIT_REPOSITORY_ROUTING_KEYS = frozenset(
    (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_INDEX_FILE",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    )
)


@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str

    def __post_init__(self) -> None:
        for label, value in (("name", self.name), ("email", self.email)):
            if (
                not isinstance(value, str)
                or value != value.strip()
                or not value
                or len(value.encode("utf-8")) > MAX_GIT_IDENTITY_BYTES
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(f"invalid Git identity {label}")

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "email": self.email}

    @classmethod
    def from_mapping(cls, value: object) -> "GitIdentity":
        if not isinstance(value, dict) or set(value) != {"name", "email"}:
            raise ValueError("invalid sealed Git identity")
        return cls(name=value["name"], email=value["email"])


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


def _sanitized_git_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    clean = dict(os.environ if source is None else source)
    for key in (
        *_GIT_ENV_INJECTION_KEYS,
        *_GIT_REPOSITORY_ROUTING_KEYS,
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
    ):
        clean.pop(key, None)
    for key in tuple(clean):
        if key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            clean.pop(key, None)
    return clean


def _trusted_git_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    clean = _sanitized_git_env(source)
    clean["GIT_CONFIG_GLOBAL"] = os.devnull
    clean["GIT_CONFIG_NOSYSTEM"] = "1"
    return clean


def _git(
    cwd: Path,
    arguments: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    read_user_config: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            env=(
                _sanitized_git_env(env)
                if read_user_config
                else _trusted_git_env(env)
            ),
            check=False,
            capture_output=True,
            text=False,
        )
    except FileNotFoundError as error:
        raise ValueError(f"Git common directory is unavailable: {cwd}") from error


def git_text(cwd: Path, *arguments: str) -> str:
    result = _git(cwd, arguments)
    return _output(result, " ".join(arguments)).decode(
        "utf-8", "surrogateescape"
    ).strip()


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


def is_volatile_ref(refname: str) -> bool:
    return any(refname.startswith(prefix) for prefix in _VOLATILE_REF_PREFIXES)


def _all_refs(path: Path) -> dict[str, str]:
    raw = _output(
        _git(path, ("for-each-ref", "--format=%(refname)\t%(objectname)")),
        "for-each-ref",
    )
    refs: dict[str, str] = {}
    for line in raw.decode("utf-8", "surrogateescape").splitlines():
        name, separator, object_id = line.partition("\t")
        if separator:
            refs[name] = require_full_sha(object_id)
    return refs


def protected_refs(path: Path, assigned_branch: str) -> dict[str, str]:
    return {
        name: sha
        for name, sha in _all_refs(path).items()
        if name != f"refs/heads/{assigned_branch}" and not is_volatile_ref(name)
    }


def configured_git_identity(path: Path) -> GitIdentity:
    try:
        name = _output(
            _git(path, ("config", "--get", "user.name"), read_user_config=True),
            "Git user.name",
        ).decode().rstrip("\n")
        email = _output(
            _git(path, ("config", "--get", "user.email"), read_user_config=True),
            "Git user.email",
        ).decode().rstrip("\n")
        return GitIdentity(name=name, email=email)
    except (UnicodeError, ValueError) as error:
        raise RuntimeError("configured Git identity is missing or invalid") from error


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
        return protected_refs(self.worktree, self.branch)

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

    def require_ancestor(self, ancestor: str, candidate: str) -> None:
        ancestor = require_full_sha(ancestor)
        candidate = require_full_sha(candidate)
        result = _git(
            self.worktree,
            ("merge-base", "--is-ancestor", ancestor, candidate),
        )
        if result.returncode != 0:
            raise ValueError("plan handoff commit is not an ancestor of candidate HEAD")


def validate_commit_identities(
    worktree: Path,
    starting_commit: str,
    candidate_head: str,
    identity: GitIdentity,
) -> None:
    starting_commit = require_full_sha(starting_commit)
    candidate_head = require_full_sha(candidate_head)
    try:
        raw = _output(
            _git(
                worktree,
                (
                    "log",
                    "--format=%H%x00%an%x00%ae%x00%cn%x00%ce",
                    f"{starting_commit}..{candidate_head}",
                ),
            ),
            "log commit identities",
        )
    except ValueError as error:
        raise RuntimeError("commit identity validation failed") from error
    expected = (identity.name.encode(), identity.email.encode()) * 2
    for record in raw.splitlines():
        fields = record.split(b"\0")
        if len(fields) != 5:
            raise RuntimeError("malformed commit identity output")
        try:
            require_full_sha(fields[0].decode("ascii"))
        except (UnicodeError, ValueError) as error:
            raise RuntimeError("malformed commit identity output") from error
        if tuple(fields[1:]) != expected:
            raise RuntimeError("commit identity mismatch")


def sanitized_child_env(
    source_env: Mapping[str, str],
    *,
    provider_auth_prefixes: Sequence[str],
    remotes: Sequence[str],
    run_id: str,
    git_identity: GitIdentity,
) -> dict[str, str]:
    """Return a child environment that blocks accidental Git remote mutation.

    The push-url overrides and credential scrubbing are accidental-mutation
    guards only; they do not provide hard isolation from another process with
    the same user identity.
    """
    allowed_prefixes = tuple(provider_auth_prefixes)
    clean: dict[str, str] = {}
    for key, value in source_env.items():
        if key in _GIT_ENV_INJECTION_KEYS or key in _GIT_REPOSITORY_ROUTING_KEYS or key in {
            "SSH_AUTH_SOCK",
            "SSH_ASKPASS",
            "GIT_ASKPASS",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
        }:
            continue
        if (
            key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            continue
        if key in _OPERATOR_CONFIG_ROOTS:
            continue
        provider_auth = key.startswith(allowed_prefixes)
        generic_credential = key.endswith(_GENERIC_CREDENTIAL_SUFFIXES)
        credential_url = key.endswith("_URL") and _url_contains_userinfo(str(value))
        unrelated_family_credential = key.startswith(_UNRELATED_CREDENTIAL_FAMILIES) and any(
            hint in key for hint in _UNRELATED_CREDENTIAL_HINTS
        )
        if not provider_auth and (
            generic_credential
            or credential_url
            or key in _CREDENTIAL_CONFIG_PATHS
            or key in _SERVICE_CREDENTIALS
            or unrelated_family_credential
        ):
            continue
        clean[str(key)] = str(value)
    clean["GIT_CONFIG_GLOBAL"] = os.devnull
    clean["GIT_CONFIG_NOSYSTEM"] = "1"
    safe_remotes: list[str] = []
    for remote in sorted(set(remotes)):
        if not isinstance(remote, str) or not remote or any(ord(character) < 32 or ord(character) == 127 for character in remote):
            raise ValueError("remote name contains control characters")
        safe_remotes.append(remote)
    if any(ord(character) < 32 or ord(character) == 127 for character in run_id):
        raise ValueError("run id contains control characters")
    safe_config = (
        ("user.name", git_identity.name),
        ("user.email", git_identity.email),
        ("user.useConfigOnly", "true"),
        ("commit.gpgSign", "false"),
    )
    for index, (key, value) in enumerate(safe_config):
        clean[f"GIT_CONFIG_KEY_{index}"] = key
        clean[f"GIT_CONFIG_VALUE_{index}"] = value
    for index, remote in enumerate(safe_remotes, start=len(safe_config)):
        clean[f"GIT_CONFIG_KEY_{index}"] = f"remote.{remote}.pushurl"
        clean[f"GIT_CONFIG_VALUE_{index}"] = f"disabled://plan-runner/{run_id}/{remote}"
    clean["GIT_CONFIG_COUNT"] = str(len(safe_config) + len(safe_remotes))
    clean["GIT_AUTHOR_NAME"] = git_identity.name
    clean["GIT_AUTHOR_EMAIL"] = git_identity.email
    clean["GIT_COMMITTER_NAME"] = git_identity.name
    clean["GIT_COMMITTER_EMAIL"] = git_identity.email
    clean["GIT_TERMINAL_PROMPT"] = "0"
    clean["GCM_INTERACTIVE"] = "Never"
    return clean


def _url_contains_userinfo(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.username is not None or parsed.password is not None
