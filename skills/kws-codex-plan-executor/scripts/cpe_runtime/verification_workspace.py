"""Disposable, detached acceptance worktrees for CPE v4 checkpoints."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping


MAX_OUTPUT_BYTES = 64 * 1024
ACCEPTANCE_TIMEOUT_SECONDS = 15 * 60
ENV_ALLOWLIST = frozenset({"LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TERM", "TMPDIR", "TZ"})
SENSITIVE_ENV = re.compile(
    r"(?:AUTH|COOKIE|CREDENTIAL|HOME|KEY|ORACLE|PASSWORD|SECRET|TOKEN)", re.IGNORECASE
)


@dataclass(frozen=True)
class AcceptanceResult:
    revision: str
    command_sha256: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool


class _BoundedCapture:
    def __init__(self) -> None:
        self.content = bytearray()
        self.total = 0

    def drain(self, stream) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            self.total += len(chunk)
            remaining = MAX_OUTPUT_BYTES - len(self.content)
            if remaining > 0:
                self.content.extend(chunk[:remaining])


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return subprocess.CompletedProcess(["git", *args], 127, b"", b"")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


@contextmanager
def verification_worktree(
    repo: Path,
    commit: str,
    run_dir: Path,
    task_id: str,
) -> Iterator[Path]:
    """Yield a detached worktree and fail closed when Git cannot remove it."""

    repository = repo.expanduser().resolve()
    run_root = run_dir.expanduser().resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("verification_commit_invalid")
    if not task_id or "/" in task_id or task_id in {".", ".."}:
        raise ValueError("verification_task_id_invalid")
    common = _run_git(repository, ["rev-parse", "--show-toplevel"])
    if common.returncode:
        raise RuntimeError("verification_repository_invalid")
    product_root = Path(os.fsdecode(common.stdout).strip()).resolve()
    if _inside(run_root, product_root):
        raise ValueError("verification_run_dir_inside_product_worktree")
    parent = run_root / "verification-worktrees"
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if parent.is_symlink():
        raise RuntimeError("evidence_integrity_failure")
    name = f"{task_id}-{commit[:12]}-{uuid.uuid4().hex[:12]}"
    checkout = parent / name
    added = _run_git(repository, ["worktree", "add", "--detach", str(checkout), commit])
    if added.returncode:
        raise RuntimeError("verification_worktree_create_failed")
    try:
        yield checkout.resolve()
    finally:
        removed = _run_git(repository, ["worktree", "remove", "--force", str(checkout)])
        listing = _run_git(repository, ["worktree", "list", "--porcelain"])
        listed = listing.returncode != 0 or os.fsencode(str(checkout)) in listing.stdout
        if removed.returncode or checkout.exists() or listed:
            raise RuntimeError("evidence_integrity_failure")
        try:
            parent.rmdir()
        except OSError:
            pass


def _bounded_environment(root: Path, supplied: Mapping[str, str]) -> tuple[dict[str, str], bytes]:
    child = {
        key: value
        for key, value in supplied.items()
        if key in ENV_ALLOWLIST and isinstance(value, str)
    }
    child.setdefault("PATH", os.defpath)
    home = root / ".cpe-acceptance-home"
    home.mkdir(mode=0o700, exist_ok=True)
    if home.is_symlink() or not home.is_dir():
        raise RuntimeError("evidence_integrity_failure")
    child["HOME"] = str(home)
    child["CPE_ACCEPTANCE"] = "1"
    redactions = {
        str(value)
        for key, value in supplied.items()
        if isinstance(value, str) and value and (SENSITIVE_ENV.search(key) or value.startswith("/"))
    }
    redactions.add(str(root))
    redactions.add(str(home))
    return child, b"\0".join(value.encode("utf-8", "surrogateescape") for value in sorted(redactions))


def _sanitized_digest(content: bytes, redactions: bytes, truncated: bool) -> str:
    sanitized = content
    for secret in redactions.split(b"\0"):
        if secret:
            sanitized = sanitized.replace(secret, b"<redacted>")
    prefix = b"CPE-BOUNDED-OUTPUT-V1\0truncated\0" if truncated else b"CPE-BOUNDED-OUTPUT-V1\0complete\0"
    return hashlib.sha256(prefix + sanitized).hexdigest()


def run_acceptance(
    commands: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str],
) -> tuple[AcceptanceResult, ...]:
    """Run approved commands with bounded env/output and retain only digests."""

    checkout = root.expanduser().resolve()
    if not checkout.is_dir() or not commands:
        raise ValueError("acceptance_input_invalid")
    revision_result = _run_git(checkout, ["rev-parse", "--verify", "HEAD"])
    revision = os.fsdecode(revision_result.stdout).strip()
    if revision_result.returncode or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("acceptance_revision_invalid")
    child_env, redactions = _bounded_environment(checkout, environment)
    results: list[AcceptanceResult] = []
    for command in commands:
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ValueError("acceptance_command_invalid")
        process = subprocess.Popen(
            ["/bin/sh", "-c", command],
            cwd=checkout,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None and process.stderr is not None
        stdout = _BoundedCapture()
        stderr = _BoundedCapture()
        threads = (
            threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
        )
        for thread in threads:
            thread.start()
        try:
            exit_code = process.wait(timeout=ACCEPTANCE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            exit_code = 124
        for thread in threads:
            thread.join()
        stdout_truncated = stdout.total > len(stdout.content)
        stderr_truncated = stderr.total > len(stderr.content)
        result = AcceptanceResult(
            revision=revision,
            command_sha256=hashlib.sha256(
                b"CPE-ACCEPTANCE-COMMAND-V1\0" + command.encode("utf-8")
            ).hexdigest(),
            exit_code=exit_code,
            stdout_sha256=_sanitized_digest(
                bytes(stdout.content), redactions, stdout_truncated
            ),
            stderr_sha256=_sanitized_digest(
                bytes(stderr.content), redactions, stderr_truncated
            ),
            stdout_bytes=stdout.total,
            stderr_bytes=stderr.total,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        results.append(result)
        if exit_code != 0:
            break
    return tuple(results)
