#!/usr/bin/env python
"""Fail-closed, read-only legacy plan-runner audit and narrow cutover tool."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import re
import shlex
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_STATE_BYTES = 1_048_576
MAX_ABANDONMENT_BYTES = 1_048_576
MAX_PROCESS_LINES = 4_096
MAX_COMMAND_BYTES = 65_536
MAX_OUTPUT_BYTES = 1_048_576
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,126}\Z")
CPE_RUN_ID = re.compile(r"cpe-[0-9a-f]{16}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
INTEGRITY_BLOCKERS = frozenset(
    {
        "abandonment_integrity",
        "legacy_link_integrity",
        "legacy_state_integrity",
        "process_snapshot_integrity",
        "report_integrity",
        "repository_integrity",
        "runtime_integrity",
        "source_integrity",
    }
)
LEGACY_NAMES = (
    "kws-codex-plan-executor",
    "kws-claude-plan-executor",
)
NEW_NAMES = (
    "kws-codex-plan-runner",
    "kws-claude-plan-runner",
)
MULTI_AGENT_NAME = "kws-claude-multi-agent-executor"
SECRET_OPTION = re.compile(
    r"(?:token|secret|password|authorization|api[-_]?key)", re.IGNORECASE
)


class CutoverError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        exit_code: int = 65,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.exit_code = exit_code
        self.details = dict(details or {})


class InvocationError(ValueError):
    pass


class ContractArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _report_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "report_sha256"}


def seal_report(report: Mapping[str, Any]) -> dict[str, Any]:
    sealed = _report_payload(report)
    sealed["report_sha256"] = hashlib.sha256(canonical_json(sealed)).hexdigest()
    return sealed


def validate_report_digest(report: object) -> bool:
    return (
        isinstance(report, Mapping)
        and isinstance(report.get("report_sha256"), str)
        and DIGEST.fullmatch(report["report_sha256"]) is not None
        and hashlib.sha256(canonical_json(_report_payload(report))).hexdigest()
        == report["report_sha256"]
    )


def _run(
    argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=None if cwd is None else str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CutoverError("runtime_integrity", 3) from error


def runtime_identity() -> dict[str, object]:
    if sys.implementation.name != "cpython" or not (
        (3, 13) <= sys.version_info[:2] < (3, 14)
    ):
        raise CutoverError("runtime_integrity", 3)
    gil_disabled = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if gil_disabled or (callable(is_gil_enabled) and not is_gil_enabled()):
        raise CutoverError("runtime_integrity", 3)
    try:
        executable = Path(sys.executable).resolve(strict=True)
        metadata = executable.stat()
    except OSError as error:
        raise CutoverError("runtime_integrity", 3) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise CutoverError("runtime_integrity", 3)
    uv = _run(("uv", "--version"), timeout=10)
    if uv.returncode != 0 or not uv.stdout.strip():
        raise CutoverError("runtime_integrity", 3)
    return {
        "uv_version": uv.stdout.strip()[:160],
        "python_version": platform.python_version(),
        "python_executable": str(executable),
        "architecture": platform.machine(),
        "gil_disabled": gil_disabled,
    }


def _validate_absolute_repo(repo: Path) -> Path:
    if not repo.is_absolute():
        raise InvocationError("repo_must_be_absolute")
    try:
        lexical_metadata = repo.lstat()
        resolved = repo.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise InvocationError("repo_invalid") from error
    if (
        not stat.S_ISDIR(lexical_metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise InvocationError("repo_invalid")
    top = _run(("git", "rev-parse", "--show-toplevel"), cwd=resolved)
    if top.returncode != 0:
        raise InvocationError("repo_not_git")
    try:
        top_path = Path(top.stdout.strip()).resolve(strict=True)
    except OSError as error:
        raise InvocationError("repo_not_git") from error
    if top_path != resolved:
        raise InvocationError("repo_not_git_root")
    return resolved


def git_head(repo: Path) -> str:
    result = _run(("git", "rev-parse", "HEAD"), cwd=repo)
    head = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40,64}", head) is None:
        raise CutoverError("repository_integrity")
    return head


def git_branch(repo: Path) -> str:
    result = _run(("git", "branch", "--show-current"), cwd=repo)
    if result.returncode != 0:
        raise CutoverError("repository_integrity")
    return result.stdout.strip()


def _legacy_skill_dir(repo: Path, name: str) -> Path:
    return repo / "skills" / "_legacy" / name


def _source_paths(repo: Path) -> dict[str, Path]:
    return {
        name: _legacy_skill_dir(repo, name)
        for name in (*LEGACY_NAMES, *NEW_NAMES)
    }


def repository_worktree_roots(repo: Path) -> tuple[Path, ...]:
    common_result = _run(("git", "rev-parse", "--git-common-dir"), cwd=repo)
    if common_result.returncode != 0:
        raise CutoverError("repository_integrity")
    common = (repo / common_result.stdout.strip()).resolve(strict=True)
    listing = _run(("git", "worktree", "list", "--porcelain"), cwd=repo)
    if listing.returncode != 0:
        raise CutoverError("repository_integrity")
    roots: list[Path] = []
    for line in listing.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        if len(roots) >= 256:
            raise CutoverError("repository_integrity")
        candidate = Path(line.removeprefix("worktree "))
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise CutoverError("repository_integrity") from error
        candidate_common_result = _run(
            ("git", "rev-parse", "--git-common-dir"), cwd=resolved
        )
        if candidate_common_result.returncode != 0:
            raise CutoverError("repository_integrity")
        candidate_common = (
            resolved / candidate_common_result.stdout.strip()
        ).resolve(strict=True)
        if candidate_common != common:
            raise CutoverError("repository_integrity")
        roots.append(resolved)
    if repo not in roots:
        raise CutoverError("repository_integrity")
    return tuple(sorted(set(roots), key=str))


def _legacy_roots(
    repo: Path, worktrees: Sequence[Path] | None = None
) -> dict[str, tuple[Path, ...]]:
    roots = tuple(worktrees or repository_worktree_roots(repo))
    return {
        "codex": tuple(_legacy_skill_dir(root, LEGACY_NAMES[0]) for root in roots),
        "claude": tuple(_legacy_skill_dir(root, LEGACY_NAMES[1]) for root in roots),
    }


def _link_paths(home: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for provider in ("codex", "claude"):
        for name in (*LEGACY_NAMES, *NEW_NAMES):
            result[f"{provider}:{name}"] = home / f".{provider}" / "skills" / name
        result[f"{provider}:{MULTI_AGENT_NAME}"] = (
            home / f".{provider}" / "skills" / MULTI_AGENT_NAME
        )
    return result


def _lstat_fact(path: Path) -> dict[str, object]:
    fact: dict[str, object] = {"path": str(path), "kind": "absent", "target": None}
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return fact
    except OSError:
        fact["kind"] = "unreadable"
        return fact
    fact["owner_uid"] = metadata.st_uid
    fact["mode"] = stat.S_IMODE(metadata.st_mode)
    fact["device"] = metadata.st_dev
    fact["inode"] = metadata.st_ino
    if stat.S_ISLNK(metadata.st_mode):
        fact["kind"] = "symlink"
        try:
            fact["target"] = os.readlink(path)
        except OSError:
            fact["kind"] = "unreadable"
    elif stat.S_ISDIR(metadata.st_mode):
        fact["kind"] = "directory"
        fact["resolved_path"] = str(path.resolve(strict=True))
    elif stat.S_ISREG(metadata.st_mode):
        fact["kind"] = "regular"
        fact["resolved_path"] = str(path.resolve(strict=True))
    else:
        fact["kind"] = "other"
    return fact


def _safe_owned_regular(path: Path, maximum: int) -> tuple[bytes, os.stat_result]:
    try:
        lexical = path.lstat()
    except OSError as error:
        raise CutoverError("legacy_state_integrity") from error
    if (
        not stat.S_ISREG(lexical.st_mode)
        or lexical.st_uid != os.getuid()
        or stat.S_IMODE(lexical.st_mode) & 0o022
        or lexical.st_size > maximum
    ):
        raise CutoverError("legacy_state_integrity")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CutoverError("legacy_state_integrity") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (lexical.st_dev, lexical.st_ino, lexical.st_size)
        ):
            raise CutoverError("legacy_state_integrity")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum:
            raise CutoverError("legacy_state_integrity")
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise CutoverError("legacy_state_integrity")
        return payload, opened
    finally:
        os.close(descriptor)


def _state_roots(home: Path) -> tuple[tuple[str, Path, str], ...]:
    return (
        ("codex", home / ".codex" / "orchestrator", "state.json"),
        ("claude", home / ".claude" / "clpe", "run.json"),
    )


def _state_fact(
    provider: str, run_id: str, state_path: Path
) -> tuple[dict[str, object], bool]:
    fact: dict[str, object] = {
        "provider": provider,
        "run_id": run_id,
        "path": str(state_path),
        "status": None,
        "resumable": None,
        "sha256": None,
        "classification": "unsafe",
    }
    try:
        payload, _metadata = _safe_owned_regular(state_path, MAX_STATE_BYTES)
    except CutoverError:
        return fact, True
    digest = hashlib.sha256(payload).hexdigest()
    fact["sha256"] = digest
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        fact["classification"] = "malformed"
        return fact, True
    if not isinstance(document, Mapping):
        fact["classification"] = "malformed"
        return fact, True
    status = document.get("status")
    resumable = document.get("resumable")
    fact["status"] = status if isinstance(status, str) else None
    fact["resumable"] = resumable if isinstance(resumable, bool) else None
    if (
        not isinstance(status, str)
        or ("run_id" in document and document.get("run_id") != run_id)
        or ("resumable" in document and not isinstance(resumable, bool))
    ):
        fact["classification"] = "malformed"
        return fact, True
    fact["classification"] = (
        "terminal"
        if status == "completed" and not (provider == "claude" and resumable is True)
        else "continuable"
    )
    return fact, False


def scan_states(home: Path) -> tuple[list[dict[str, object]], list[str]]:
    states: list[dict[str, object]] = []
    blockers: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for provider, root, filename in _state_roots(home):
        try:
            root_metadata = root.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            blockers.add("legacy_state_integrity")
            continue
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.getuid()
            or stat.S_IMODE(root_metadata.st_mode) & 0o022
        ):
            blockers.add("legacy_state_integrity")
            continue
        try:
            entries = sorted(os.scandir(root), key=lambda entry: entry.name)
        except OSError:
            blockers.add("legacy_state_integrity")
            continue
        if len(entries) > 10_000:
            blockers.add("legacy_state_integrity")
            continue
        for entry in entries:
            run_id = entry.name
            # The Codex orchestrator root predates CPE and is shared with
            # unrelated historical controllers. Only the namespace emitted by
            # the legacy CPE runner is part of this cutover contract.
            if provider == "codex" and CPE_RUN_ID.fullmatch(run_id) is None:
                continue
            key = (provider, run_id)
            if (
                RUN_ID.fullmatch(run_id) is None
                or key in seen
                or entry.is_symlink()
                or not entry.is_dir(follow_symlinks=False)
            ):
                blockers.add("legacy_state_integrity")
                continue
            seen.add(key)
            fact, integrity = _state_fact(provider, run_id, Path(entry.path) / filename)
            states.append(fact)
            if integrity:
                blockers.add("legacy_state_integrity")
            elif fact["classification"] == "continuable":
                blockers.add("legacy_nonterminal_state")
    return states, sorted(blockers)


def _scrub_command(command: str) -> str:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    scrubbed: list[str] = []
    hide_next = False
    for token in tokens:
        if hide_next:
            scrubbed.append("<redacted>")
            hide_next = False
            continue
        if "=" in token and SECRET_OPTION.search(token.split("=", 1)[0]):
            scrubbed.append(token.split("=", 1)[0] + "=<redacted>")
            continue
        scrubbed.append(token)
        if SECRET_OPTION.search(token):
            hide_next = True
    return " ".join(scrubbed)


def _token_matches_path(token: str, exact: Path) -> bool:
    expected = str(exact)
    return token == expected or token.startswith(expected + os.sep)


def _process_match(
    command: str,
    repo: Path,
    home: Path,
    legacy_roots: Mapping[str, Sequence[Path]],
) -> tuple[list[str], list[str], list[str]]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    links = _link_paths(home)
    providers: set[str] = set()
    codes: set[str] = set()
    run_ids: set[str] = set()
    for token in tokens:
        if (
            token == "scripts/cpe.py"
            or token.endswith("/scripts/cpe.py")
            or any(_token_matches_path(token, root) for root in legacy_roots["codex"])
        ):
            providers.add("codex")
            codes.add("codex_legacy_command")
        if (
            token == "scripts/clpe.py"
            or token.endswith("/scripts/clpe.py")
            or any(
                _token_matches_path(token, root) for root in legacy_roots["claude"]
            )
        ):
            providers.add("claude")
            codes.add("claude_legacy_command")
        for key, link in links.items():
            if any(name in key for name in LEGACY_NAMES) and _token_matches_path(
                token, link
            ):
                provider = "codex" if "codex-plan-executor" in key else "claude"
                providers.add(provider)
                codes.add(f"{provider}_legacy_link")
        if RUN_ID.fullmatch(token):
            run_ids.add(token)
    return sorted(providers), sorted(codes), sorted(run_ids)


def _cwd_match(
    cwd: str,
    repo: Path,
    home: Path,
    legacy_roots: Mapping[str, Sequence[Path]],
) -> tuple[list[str], list[str]]:
    if (
        len(cwd.encode("utf-8", errors="replace")) > MAX_COMMAND_BYTES
        or not Path(cwd).is_absolute()
    ):
        raise CutoverError("process_snapshot_integrity")
    clean = cwd.removesuffix(" (deleted)")
    providers: set[str] = set()
    codes: set[str] = set()
    links = _link_paths(home)
    if any(_token_matches_path(clean, root) for root in legacy_roots["codex"]):
        providers.add("codex")
        codes.add("codex_legacy_cwd")
    if any(_token_matches_path(clean, root) for root in legacy_roots["claude"]):
        providers.add("claude")
        codes.add("claude_legacy_cwd")
    for key, link in links.items():
        if not any(name in key for name in LEGACY_NAMES):
            continue
        if _token_matches_path(clean, link):
            provider = "codex" if "codex-plan-executor" in key else "claude"
            providers.add(provider)
            codes.add(f"{provider}_legacy_cwd")
    return sorted(providers), sorted(codes)


def process_snapshot() -> str:
    result = _run(("ps", "-axo", "pid=,ppid=,pgid=,command="), timeout=10)
    if result.returncode != 0:
        raise CutoverError("process_snapshot_integrity")
    if len(result.stdout.encode("utf-8", errors="replace")) > (
        MAX_PROCESS_LINES * MAX_COMMAND_BYTES
    ):
        raise CutoverError("process_snapshot_integrity")
    return result.stdout


def process_cwd_map() -> dict[int, str]:
    """Best-effort bounded cwd inventory; command matching remains canonical."""
    executable = Path("/usr/sbin/lsof")
    if not executable.is_file():
        return {}
    try:
        result = subprocess.run(
            [str(executable), "-a", "-d", "cwd", "-Fn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if (
        result.returncode != 0
        or len(result.stdout.encode("utf-8", errors="replace"))
        > MAX_PROCESS_LINES * MAX_COMMAND_BYTES
    ):
        return {}
    mapping: dict[int, str] = {}
    current_pid: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            current_pid = int(line[1:])
        elif line.startswith("n") and current_pid is not None:
            cwd = line[1:]
            if len(cwd.encode("utf-8", errors="replace")) <= MAX_COMMAND_BYTES:
                mapping[current_pid] = cwd
    return mapping


def scan_processes(
    snapshot: str,
    repo: Path,
    home: Path,
    process_cwds: Mapping[int, str] | None = None,
    legacy_roots: Mapping[str, Sequence[Path]] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    facts: list[dict[str, object]] = []
    internal: list[dict[str, object]] = []
    blockers: set[str] = set()
    lines = snapshot.splitlines()
    recognized_roots = legacy_roots or _legacy_roots(repo)
    if len(lines) > MAX_PROCESS_LINES:
        return [], [], ["process_snapshot_integrity"]
    for raw in lines:
        if not raw.strip():
            continue
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+)\Z", raw)
        if match is None:
            blockers.add("process_snapshot_integrity")
            continue
        command = match.group(4)
        if len(command.encode("utf-8", errors="replace")) > MAX_COMMAND_BYTES:
            blockers.add("process_snapshot_integrity")
            continue
        pid = int(match.group(1))
        cwd = (process_cwds or {}).get(pid)
        try:
            providers, codes, run_ids = _process_match(
                command, repo, home, recognized_roots
            )
            if cwd is not None:
                cwd_providers, cwd_codes = _cwd_match(
                    cwd, repo, home, recognized_roots
                )
                providers = sorted(set(providers) | set(cwd_providers))
                codes = sorted(set(codes) | set(cwd_codes))
        except CutoverError:
            blockers.add("process_snapshot_integrity")
            continue
        if not providers:
            continue
        scrubbed = _scrub_command(command)
        fact: dict[str, object] = {
            "pid": pid,
            "ppid": int(match.group(2)),
            "pgid": int(match.group(3)),
            "providers": providers,
            "match_codes": codes,
            "command_sha256": hashlib.sha256(scrubbed.encode()).hexdigest(),
            "command_bytes": len(command.encode("utf-8", errors="replace")),
            "cwd": cwd,
        }
        facts.append(fact)
        internal.append({**fact, "run_ids": run_ids})
        blockers.add("legacy_process_active")
    facts.sort(key=lambda item: int(item["pid"]))
    internal.sort(key=lambda item: int(item["pid"]))
    return facts, internal, sorted(blockers)


def _read_abandonment(
    path: Path | None,
) -> tuple[list[dict[str, object]], list[str]]:
    if path is None:
        return [], []
    blockers: set[str] = set()
    entries: list[dict[str, object]] = []
    try:
        payload, _metadata = _safe_owned_regular(path, MAX_ABANDONMENT_BYTES)
        document = json.loads(payload)
    except (CutoverError, UnicodeError, json.JSONDecodeError):
        return [], ["abandonment_integrity"]
    if (
        not isinstance(document, Mapping)
        or set(document) != {"format_version", "runs"}
        or document.get("format_version") != 1
        or not isinstance(document.get("runs"), list)
    ):
        return [], ["abandonment_integrity"]
    seen: set[tuple[str, str]] = set()
    for value in document["runs"]:
        if not isinstance(value, Mapping) or set(value) != {
            "provider",
            "run_id",
            "state_sha256",
            "reason",
        }:
            blockers.add("abandonment_integrity")
            continue
        provider = value.get("provider")
        run_id = value.get("run_id")
        digest = value.get("state_sha256")
        reason = value.get("reason")
        key = (str(provider), str(run_id))
        if (
            provider not in {"codex", "claude"}
            or not isinstance(run_id, str)
            or RUN_ID.fullmatch(run_id) is None
            or not isinstance(digest, str)
            or DIGEST.fullmatch(digest) is None
            or not isinstance(reason, str)
            or len(reason.strip()) < 20
            or len(reason.strip().split()) < 3
            or key in seen
        ):
            blockers.add("abandonment_integrity")
            continue
        seen.add(key)
        entries.append(
            {
                "provider": provider,
                "run_id": run_id,
                "state_sha256": digest,
                "reason_sha256": hashlib.sha256(reason.strip().encode()).hexdigest(),
            }
        )
    return entries, sorted(blockers)


def _apply_abandonment(
    states: list[dict[str, object]],
    entries: list[dict[str, object]],
    processes: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    blockers: set[str] = set()
    state_by_key = {(item["provider"], item["run_id"]): item for item in states}
    accepted: list[dict[str, object]] = []
    for entry in entries:
        key = (entry["provider"], entry["run_id"])
        state = state_by_key.get(key)
        matching_process = any(
            entry["provider"] in process["providers"]
            and entry["run_id"] in process["run_ids"]
            for process in processes
        )
        if matching_process:
            blockers.add("abandonment_live_process")
            continue
        if (
            state is None
            or state.get("classification") != "continuable"
            or state.get("sha256") != entry["state_sha256"]
        ):
            blockers.add("abandonment_integrity")
            continue
        state["classification"] = "abandoned"
        accepted.append(dict(entry))
    accepted.sort(key=lambda item: (str(item["provider"]), str(item["run_id"])))
    return states, accepted, sorted(blockers)


def _source_facts(
    repo: Path, worktrees: Sequence[Path]
) -> list[dict[str, object]]:
    paths: list[Path] = []
    for root in worktrees:
        paths.extend(_legacy_skill_dir(root, name) for name in LEGACY_NAMES)
    paths.extend(_source_paths(repo)[name] for name in NEW_NAMES)
    return [_lstat_fact(path) for path in sorted(set(paths), key=str)]


def _link_facts(home: Path) -> list[dict[str, object]]:
    return [_lstat_fact(path) for path in _link_paths(home).values()]


def _link_integrity_blockers(
    repo: Path,
    home: Path,
    facts: list[dict[str, object]],
    legacy_roots: Mapping[str, Sequence[Path]],
    worktrees: Sequence[Path],
) -> list[str]:
    expected: dict[str, set[str]] = {}
    for key, link in _link_paths(home).items():
        skill_name = key.split(":", 1)[1]
        if skill_name == LEGACY_NAMES[0]:
            targets = legacy_roots["codex"]
        elif skill_name == LEGACY_NAMES[1]:
            targets = legacy_roots["claude"]
        elif skill_name in NEW_NAMES:
            targets = (_legacy_skill_dir(repo, skill_name),)
        else:
            targets = tuple(
                _legacy_skill_dir(root, MULTI_AGENT_NAME) for root in worktrees
            )
        expected[str(link)] = {str(target) for target in targets}
    for fact in facts:
        if fact["kind"] == "absent":
            continue
        if (
            fact["kind"] != "symlink"
            or fact.get("owner_uid") != os.getuid()
            or fact.get("target") not in expected[str(fact["path"])]
        ):
            return ["legacy_link_integrity"]
    return []


def audit_repository(
    repo: Path,
    *,
    home: Path | None = None,
    process_snapshot: str | None = None,
    process_cwds: Mapping[int, str] | None = None,
    abandonment_file: Path | None = None,
    runtime_identity: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    repository = _validate_absolute_repo(Path(repo))
    operator_home = (
        Path(home).resolve(strict=True)
        if home is not None
        else Path.home().resolve(strict=True)
    )
    if not operator_home.is_dir():
        raise InvocationError("home_invalid")
    runtime = dict(runtime_identity or globals()["runtime_identity"]())
    worktrees = repository_worktree_roots(repository)
    recognized_legacy_roots = _legacy_roots(repository, worktrees)
    states, state_blockers = scan_states(operator_home)
    live_process_inventory = process_snapshot is None
    snapshot = (
        process_snapshot if not live_process_inventory else globals()["process_snapshot"]()
    )
    cwd_inventory = (
        dict(process_cwds)
        if process_cwds is not None
        else (process_cwd_map() if live_process_inventory else {})
    )
    processes, internal_processes, process_blockers = scan_processes(
        snapshot,
        repository,
        operator_home,
        cwd_inventory,
        recognized_legacy_roots,
    )
    abandonments, abandonment_parse_blockers = _read_abandonment(abandonment_file)
    states, accepted, abandonment_apply_blockers = _apply_abandonment(
        states, abandonments, internal_processes
    )
    link_facts = _link_facts(operator_home)
    blockers = set(
        state_blockers
        + process_blockers
        + abandonment_parse_blockers
        + abandonment_apply_blockers
        + _link_integrity_blockers(
            repository,
            operator_home,
            link_facts,
            recognized_legacy_roots,
            worktrees,
        )
    )
    if any(item["classification"] == "continuable" for item in states):
        blockers.add("legacy_nonterminal_state")
    else:
        blockers.discard("legacy_nonterminal_state")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "audit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": {
            "path": str(repository),
            "head": git_head(repository),
            "branch": git_branch(repository),
        },
        "runtime": runtime,
        "home": str(operator_home),
        "legacy_source_roots": [
            str(path)
            for provider in ("codex", "claude")
            for path in recognized_legacy_roots[provider]
        ],
        "installed_link_paths": [
            str(path) for path in _link_paths(operator_home).values()
        ],
        "sources": _source_facts(repository, worktrees),
        "links": link_facts,
        "processes": processes,
        "states": states,
        "accepted_abandonments": accepted,
        "blocker_codes": sorted(blockers),
    }
    return seal_report(report)


def _safe_output_parent(path: Path) -> Path:
    if not path.is_absolute():
        raise InvocationError("output_must_be_absolute")
    parent = path.parent
    try:
        metadata = parent.lstat()
    except OSError as error:
        raise InvocationError("output_parent_invalid") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise InvocationError("output_parent_invalid")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_uid != os.getuid()
        or stat.S_IMODE(existing.st_mode) & 0o022
    ):
        raise InvocationError("output_invalid")
    return parent


def write_audit_report(path: Path, report: Mapping[str, Any]) -> None:
    if not validate_report_digest(report) or not validate_report_structure(report):
        raise CutoverError("report_integrity")
    parent = _safe_output_parent(path)
    payload = canonical_json(report) + b"\n"
    if len(payload) > MAX_OUTPUT_BYTES:
        raise CutoverError("report_integrity")
    temporary = parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _absolute_path_string(value: object) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).is_absolute()


def _unique_strings(
    value: object,
    *,
    absolute: bool = False,
    allowed: set[str] | frozenset[str] | None = None,
) -> bool:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return False
    if len(value) != len(set(value)):
        return False
    if absolute and any(not _absolute_path_string(item) for item in value):
        return False
    return allowed is None or all(item in allowed for item in value)


def _valid_lstat_fact(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    kind = value.get("kind")
    base = {"path", "kind", "target"}
    if kind in {"absent", "unreadable"}:
        return (
            set(value) == base
            and _absolute_path_string(value.get("path"))
            and value.get("target") is None
        )
    present = base | {"owner_uid", "mode", "device", "inode"}
    if kind in {"directory", "regular"}:
        present |= {"resolved_path"}
    if set(value) != present or not _absolute_path_string(value.get("path")):
        return False
    if not all(
        _plain_int(value.get(field))
        for field in ("owner_uid", "mode", "device", "inode")
    ):
        return False
    if kind == "symlink":
        return isinstance(value.get("target"), str)
    if kind in {"directory", "regular"}:
        return value.get("target") is None and _absolute_path_string(
            value.get("resolved_path")
        )
    return kind == "other" and value.get("target") is None


def _valid_process_fact(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "pid",
        "ppid",
        "pgid",
        "providers",
        "match_codes",
        "command_sha256",
        "command_bytes",
        "cwd",
    }:
        return False
    cwd = value.get("cwd")
    return (
        _plain_int(value.get("pid"), minimum=1)
        and _plain_int(value.get("ppid"))
        and _plain_int(value.get("pgid"))
        and _unique_strings(
            value.get("providers"), allowed={"codex", "claude"}
        )
        and bool(value.get("providers"))
        and _unique_strings(value.get("match_codes"))
        and bool(value.get("match_codes"))
        and isinstance(value.get("command_sha256"), str)
        and DIGEST.fullmatch(value["command_sha256"]) is not None
        and _plain_int(value.get("command_bytes"), minimum=1)
        and value["command_bytes"] <= MAX_COMMAND_BYTES
        and (cwd is None or _absolute_path_string(cwd))
    )


def _valid_state_fact(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "provider",
        "run_id",
        "path",
        "status",
        "resumable",
        "sha256",
        "classification",
    }:
        return False
    status = value.get("status")
    resumable = value.get("resumable")
    digest = value.get("sha256")
    classification = value.get("classification")
    if (
        value.get("provider") not in {"codex", "claude"}
        or not isinstance(value.get("run_id"), str)
        or RUN_ID.fullmatch(value["run_id"]) is None
        or not _absolute_path_string(value.get("path"))
        or (status is not None and not isinstance(status, str))
        or (resumable is not None and not isinstance(resumable, bool))
        or (
            digest is not None
            and (
                not isinstance(digest, str)
                or DIGEST.fullmatch(digest) is None
            )
        )
        or classification
        not in {"terminal", "continuable", "abandoned", "malformed", "unsafe"}
    ):
        return False
    if classification in {"terminal", "continuable", "abandoned"}:
        return isinstance(status, str) and digest is not None
    if classification == "malformed":
        return digest is not None
    return digest is None


def _valid_abandonment_fact(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {"provider", "run_id", "state_sha256", "reason_sha256"}
        and value.get("provider") in {"codex", "claude"}
        and isinstance(value.get("run_id"), str)
        and RUN_ID.fullmatch(value["run_id"]) is not None
        and isinstance(value.get("state_sha256"), str)
        and DIGEST.fullmatch(value["state_sha256"]) is not None
        and isinstance(value.get("reason_sha256"), str)
        and DIGEST.fullmatch(value["reason_sha256"]) is not None
    )


def validate_report_structure(report: object) -> bool:
    if not isinstance(report, Mapping) or set(report) != {
        "schema_version",
        "audit_timestamp",
        "repository",
        "runtime",
        "home",
        "legacy_source_roots",
        "installed_link_paths",
        "sources",
        "links",
        "processes",
        "states",
        "accepted_abandonments",
        "blocker_codes",
        "report_sha256",
    }:
        return False
    repository = report.get("repository")
    runtime = report.get("runtime")
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or not isinstance(report.get("audit_timestamp"), str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            report["audit_timestamp"],
        )
        is None
        or not isinstance(repository, Mapping)
        or set(repository) != {"path", "head", "branch"}
        or not _absolute_path_string(repository.get("path"))
        or not isinstance(repository.get("head"), str)
        or re.fullmatch(r"[0-9a-f]{40,64}", repository["head"]) is None
        or not isinstance(repository.get("branch"), str)
        or not isinstance(runtime, Mapping)
        or set(runtime)
        != {
            "uv_version",
            "python_version",
            "python_executable",
            "architecture",
            "gil_disabled",
        }
        or any(
            not isinstance(runtime.get(field), str) or not runtime[field]
            for field in ("uv_version", "python_version", "architecture")
        )
        or not _absolute_path_string(runtime.get("python_executable"))
        or not isinstance(runtime.get("gil_disabled"), bool)
        or not _absolute_path_string(report.get("home"))
        or not _unique_strings(report.get("legacy_source_roots"), absolute=True)
        or not _unique_strings(report.get("installed_link_paths"), absolute=True)
    ):
        return False
    list_validators = (
        ("sources", _valid_lstat_fact),
        ("links", _valid_lstat_fact),
        ("processes", _valid_process_fact),
        ("states", _valid_state_fact),
        ("accepted_abandonments", _valid_abandonment_fact),
    )
    for key, validator in list_validators:
        values = report.get(key)
        if not isinstance(values, list) or any(not validator(value) for value in values):
            return False
    blocker_codes = report.get("blocker_codes")
    allowed_blockers = set(INTEGRITY_BLOCKERS) | {
        "abandonment_live_process",
        "legacy_nonterminal_state",
        "legacy_process_active",
    }
    return (
        _unique_strings(blocker_codes, allowed=allowed_blockers)
        and blocker_codes == sorted(blocker_codes)
        and isinstance(report.get("report_sha256"), str)
        and DIGEST.fullmatch(report["report_sha256"]) is not None
    )


def read_report(path: Path) -> dict[str, Any]:
    try:
        payload, _metadata = _safe_owned_regular(path, MAX_OUTPUT_BYTES)
        report = json.loads(payload)
    except (CutoverError, UnicodeError, json.JSONDecodeError) as error:
        raise CutoverError("report_integrity") from error
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != SCHEMA_VERSION
        or not validate_report_structure(report)
        or not validate_report_digest(report)
    ):
        raise CutoverError("report_integrity")
    return report


def _stable_audit_facts(report: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {"audit_timestamp", "report_sha256"}
    return {key: value for key, value in report.items() if key not in ignored}


def _require_fresh_zero(
    repo: Path,
    report: Mapping[str, Any],
    *,
    home: Path,
    process_snapshot: str | None,
    abandonment_file: Path | None,
    runtime_identity: Mapping[str, object] | None,
) -> dict[str, Any]:
    if not validate_report_digest(report):
        raise CutoverError("report_integrity")
    if report.get("blocker_codes") != []:
        raise CutoverError("cutover_pending_legacy_runs", 3)
    fresh = audit_repository(
        repo,
        home=home,
        process_snapshot=process_snapshot,
        abandonment_file=abandonment_file,
        runtime_identity=runtime_identity,
    )
    if fresh["blocker_codes"]:
        code = (
            65
            if any(item in INTEGRITY_BLOCKERS for item in fresh["blocker_codes"])
            else 3
        )
        raise CutoverError("cutover_pending_legacy_runs", code)
    if _stable_audit_facts(fresh) != _stable_audit_facts(report):
        raise CutoverError("report_stale")
    return fresh


def _require_owned_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CutoverError("source_integrity") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise CutoverError("source_integrity")


def _validate_cutover_sources(repo: Path) -> None:
    sources = _source_paths(repo)
    for name in NEW_NAMES:
        _require_owned_directory(sources[name])
    for name in LEGACY_NAMES:
        try:
            sources[name].lstat()
        except FileNotFoundError:
            continue
        raise CutoverError("source_integrity")


def _prevalidate_links(repo: Path, home: Path) -> dict[str, dict[str, object]]:
    links = _link_paths(home)
    removals: dict[str, dict[str, object]] = {}
    for provider in ("codex", "claude"):
        skill_home = home / f".{provider}" / "skills"
        _require_owned_directory(skill_home)
        for name in LEGACY_NAMES:
            path = links[f"{provider}:{name}"]
            fact = _lstat_fact(path)
            if fact["kind"] == "absent":
                continue
            if (
                fact["kind"] != "symlink"
                or fact.get("owner_uid") != os.getuid()
                or fact.get("target") != str(_legacy_skill_dir(repo, name))
            ):
                raise CutoverError("legacy_link_integrity")
            removals[str(path)] = fact
    for provider, name in (
        ("codex", NEW_NAMES[0]),
        ("claude", NEW_NAMES[1]),
    ):
        path = links[f"{provider}:{name}"]
        fact = _lstat_fact(path)
        if fact["kind"] == "absent":
            continue
        if (
            fact["kind"] != "symlink"
            or fact.get("owner_uid") != os.getuid()
            or fact.get("target") != str(_legacy_skill_dir(repo, name))
        ):
            raise CutoverError("legacy_link_integrity")
    return removals


def _open_safe_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        lexical = path.lstat()
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CutoverError("legacy_link_integrity") from error
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(lexical.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or (lexical.st_dev, lexical.st_ino)
        != (opened.st_dev, opened.st_ino)
        or opened.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) & 0o022
    ):
        os.close(descriptor)
        raise CutoverError("legacy_link_integrity")
    return descriptor


def atomic_symlink(
    target: Path,
    destination: Path,
    *,
    before_rename: Callable[[Path, Path], None] | None = None,
) -> None:
    if destination.name in {"", ".", ".."} or os.sep in destination.name:
        raise CutoverError("legacy_link_integrity")
    temporary_name = f".{destination.name}.{uuid.uuid4().hex}.tmp"
    directory = _open_safe_directory(destination.parent)
    try:
        os.symlink(str(target), temporary_name, dir_fd=directory)
        metadata = os.stat(
            temporary_name, dir_fd=directory, follow_symlinks=False
        )
        if (
            not stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or os.readlink(temporary_name, dir_fd=directory) != str(target)
        ):
            raise CutoverError("legacy_link_integrity")
        if before_rename is not None:
            before_rename(destination.parent / temporary_name, destination)
        parent_now = destination.parent.lstat()
        opened = os.fstat(directory)
        if (parent_now.st_dev, parent_now.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise CutoverError("legacy_link_integrity")
        try:
            # symlink creation is atomic and fails with EEXIST. Unlike replace,
            # it can never overwrite a raced regular file or directory.
            os.symlink(str(target), destination.name, dir_fd=directory)
        except FileExistsError as error:
            raise CutoverError("legacy_link_integrity") from error
        installed = os.stat(
            destination.name, dir_fd=directory, follow_symlinks=False
        )
        if (
            not stat.S_ISLNK(installed.st_mode)
            or installed.st_uid != os.getuid()
            or os.readlink(destination.name, dir_fd=directory) != str(target)
        ):
            raise CutoverError("legacy_link_integrity")
        os.fsync(directory)
    except OSError as error:
        raise CutoverError("legacy_link_integrity") from error
    finally:
        try:
            os.unlink(temporary_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        finally:
            os.close(directory)


def _rename_noreplace(
    source_name: str,
    destination_name: str,
    *,
    source_dir: int,
    destination_dir: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        rename = libc.renameatx_np
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            source_dir,
            source,
            destination_dir,
            destination,
            0x00000004,  # RENAME_EXCL
        )
    elif hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            source_dir,
            source,
            destination_dir,
            destination,
            0x00000001,  # RENAME_NOREPLACE
        )
    else:
        raise CutoverError("legacy_link_integrity")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number))
    raise OSError(error_number, os.strerror(error_number))


def _create_private_quarantine(
    parent: Path, parent_directory: int
) -> tuple[Path, int]:
    for _attempt in range(16):
        name = f".plan-runner-cutover-quarantine-{uuid.uuid4().hex}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_directory)
        except FileExistsError:
            continue
        path = parent / name
        directory = _open_safe_directory(path)
        return path, directory
    raise CutoverError("legacy_link_integrity")


def quarantine_legacy_entry(
    path: Path,
    expected: Mapping[str, object],
    *,
    expected_target: str,
    before_rename: Callable[[Path, Path], None] | None = None,
) -> dict[str, object]:
    if path.name in {"", ".", ".."} or os.sep in path.name:
        raise CutoverError("legacy_link_integrity")
    parent_directory = _open_safe_directory(path.parent)
    quarantine_path: Path | None = None
    quarantine_directory: int | None = None
    destination: Path | None = None
    move_completed = False
    try:
        quarantine_path, quarantine_directory = _create_private_quarantine(
            path.parent, parent_directory
        )
        destination = quarantine_path / path.name
        metadata = os.stat(
            path.name, dir_fd=parent_directory, follow_symlinks=False
        )
        if (
            not stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_dev != expected.get("device")
            or metadata.st_ino != expected.get("inode")
            or stat.S_IMODE(metadata.st_mode) != expected.get("mode")
            or os.readlink(path.name, dir_fd=parent_directory) != expected_target
        ):
            raise CutoverError("legacy_link_integrity")
        if before_rename is not None:
            before_rename(path, destination)
        parent_now = path.parent.lstat()
        parent_opened = os.fstat(parent_directory)
        quarantine_now = quarantine_path.lstat()
        quarantine_opened = os.fstat(quarantine_directory)
        if (
            (parent_now.st_dev, parent_now.st_ino)
            != (parent_opened.st_dev, parent_opened.st_ino)
            or (quarantine_now.st_dev, quarantine_now.st_ino)
            != (quarantine_opened.st_dev, quarantine_opened.st_ino)
        ):
            raise CutoverError("legacy_link_integrity")
        try:
            _rename_noreplace(
                path.name,
                path.name,
                source_dir=parent_directory,
                destination_dir=quarantine_directory,
            )
            move_completed = True
        except FileExistsError as error:
            raise CutoverError(
                "legacy_link_integrity",
                details={
                    "quarantine_collision_path": str(destination),
                    "source_preserved": True,
                },
            ) from error
        moved = os.stat(
            path.name, dir_fd=quarantine_directory, follow_symlinks=False
        )
        moved_target = (
            os.readlink(path.name, dir_fd=quarantine_directory)
            if stat.S_ISLNK(moved.st_mode)
            else None
        )
        os.fsync(parent_directory)
        os.fsync(quarantine_directory)
        if (
            not stat.S_ISLNK(moved.st_mode)
            or moved.st_uid != os.getuid()
            or moved.st_dev != expected.get("device")
            or moved.st_ino != expected.get("inode")
            or stat.S_IMODE(moved.st_mode) != expected.get("mode")
            or moved_target != expected_target
        ):
            raise CutoverError(
                "legacy_link_integrity",
                details={
                    "quarantine_recovery_path": str(destination),
                    "quarantined_kind": (
                        "directory"
                        if stat.S_ISDIR(moved.st_mode)
                        else "regular"
                        if stat.S_ISREG(moved.st_mode)
                        else "symlink"
                        if stat.S_ISLNK(moved.st_mode)
                        else "other"
                    ),
                    "source_preserved": True,
                },
            )
        return {
            "source": str(path),
            "destination": str(destination),
            "device": moved.st_dev,
            "inode": moved.st_ino,
            "target": moved_target,
        }
    except CutoverError:
        raise
    except OSError as error:
        details: dict[str, object] = {}
        if move_completed and destination is not None:
            details["quarantine_recovery_path"] = str(destination)
            details["source_preserved"] = True
        elif quarantine_path is not None:
            details["quarantine_directory"] = str(quarantine_path)
        raise CutoverError("legacy_link_integrity", details=details) from error
    finally:
        if quarantine_directory is not None:
            os.close(quarantine_directory)
        os.close(parent_directory)


def apply_cutover(
    repo: Path,
    report: Mapping[str, Any],
    *,
    home: Path | None = None,
    process_snapshot: str | None = None,
    abandonment_file: Path | None = None,
    runtime_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    repository = _validate_absolute_repo(Path(repo))
    operator_home = Path(home or Path.home()).resolve(strict=True)
    if git_branch(repository) != "main":
        raise CutoverError("main_branch_required")
    if report.get("repository", {}).get("head") != git_head(repository):
        raise CutoverError("report_stale")
    _require_fresh_zero(
        repository,
        report,
        home=operator_home,
        process_snapshot=process_snapshot,
        abandonment_file=abandonment_file,
        runtime_identity=runtime_identity,
    )
    _validate_cutover_sources(repository)
    removal_identities = _prevalidate_links(repository, operator_home)
    links = _link_paths(operator_home)
    additions = (
        ("codex", NEW_NAMES[0]),
        ("claude", NEW_NAMES[1]),
    )
    for provider, name in additions:
        destination = links[f"{provider}:{name}"]
        fact = _lstat_fact(destination)
        if fact["kind"] == "absent":
            atomic_symlink(_legacy_skill_dir(repository, name), destination)
        elif (
            fact["kind"] != "symlink"
            or fact.get("owner_uid") != os.getuid()
            or fact.get("target") != str(_legacy_skill_dir(repository, name))
        ):
            raise CutoverError("legacy_link_integrity")
    quarantined: list[dict[str, object]] = []
    for provider in ("codex", "claude"):
        for name in LEGACY_NAMES:
            path = links[f"{provider}:{name}"]
            expected = removal_identities.get(str(path))
            if expected is not None:
                try:
                    quarantined.append(
                        quarantine_legacy_entry(
                            path,
                            expected,
                            expected_target=str(
                                _legacy_skill_dir(repository, name)
                            ),
                        )
                    )
                except CutoverError as error:
                    details = dict(error.details)
                    details["completed_quarantine_moves"] = list(quarantined)
                    raise CutoverError(
                        error.reason_code,
                        error.exit_code,
                        details=details,
                    ) from error
    return {
        "status": "applied",
        "installed": [str(links[f"{provider}:{name}"]) for provider, name in additions],
        "removed": [move["source"] for move in quarantined],
        "quarantined_legacy_links": quarantined,
    }


def _tracked_legacy_paths(repo: Path) -> list[str]:
    result = _run(
        (
            "git",
            "ls-files",
            "--",
            *(f"skills/_legacy/{name}" for name in LEGACY_NAMES),
        ),
        cwd=repo,
    )
    if result.returncode != 0:
        raise CutoverError("repository_integrity")
    return [line for line in result.stdout.splitlines() if line]


def _validate_cache_root(root: Path) -> None:
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise CutoverError("source_integrity") from error
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.getuid()
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        raise CutoverError("source_integrity")
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(root)
        inside_cache = any(part in {".venv", "__pycache__"} for part in relative.parts)
        for name in list(directories):
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise CutoverError("source_integrity")
            if not inside_cache and name not in {".venv", "__pycache__"}:
                raise CutoverError("source_integrity")
        for name in files:
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise CutoverError("source_integrity")
            if not inside_cache and name != ".DS_Store" and not name.endswith(".pyc"):
                raise CutoverError("source_integrity")


def quarantine_legacy_caches(
    repo: Path,
    report: Mapping[str, Any],
    *,
    home: Path | None = None,
    process_snapshot: str | None = None,
    abandonment_file: Path | None = None,
    runtime_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    repository = _validate_absolute_repo(Path(repo))
    operator_home = Path(home or Path.home()).resolve(strict=True)
    if git_branch(repository) != "main":
        raise CutoverError("main_branch_required")
    if report.get("repository", {}).get("head") != git_head(repository):
        raise CutoverError("report_stale")
    _require_fresh_zero(
        repository,
        report,
        home=operator_home,
        process_snapshot=process_snapshot,
        abandonment_file=abandonment_file,
        runtime_identity=runtime_identity,
    )
    if _tracked_legacy_paths(repository):
        raise CutoverError("source_integrity")
    sources = _source_paths(repository)
    roots = [sources[name] for name in LEGACY_NAMES]
    for root in roots:
        _validate_cache_root(root)
    present = [root for root in roots if _lstat_fact(root)["kind"] != "absent"]
    if not present:
        return {"status": "nothing_to_quarantine", "moves": []}
    trash = operator_home / ".Trash"
    trash.mkdir(mode=0o700, exist_ok=True)
    _require_owned_directory(trash)
    destination_root = trash / (
        "Archive-plan-runner-legacy-cache-"
        + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + "-"
        + uuid.uuid4().hex
    )
    destination_root.mkdir(mode=0o700)
    moves = [
        {"source": str(root), "destination": str(destination_root / root.name)}
        for root in present
    ]
    for move in moves:
        os.replace(move["source"], move["destination"])
    directory = os.open(trash, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"status": "quarantined", "moves": moves}


def _parser() -> argparse.ArgumentParser:
    parser = ContractArgumentParser(prog="plan-runner-cutover")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--repo", required=True)
    audit.add_argument("--output", required=True)
    audit.add_argument("--abandonment-file")
    apply = subparsers.add_parser("apply")
    apply.add_argument("--repo", required=True)
    apply.add_argument("--audit-report", required=True)
    apply.add_argument("--abandonment-file")
    quarantine = subparsers.add_parser("quarantine-legacy-caches")
    quarantine.add_argument("--repo", required=True)
    quarantine.add_argument("--audit-report", required=True)
    quarantine.add_argument("--abandonment-file")
    subparsers.add_parser("self-test")
    return parser


def _path(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise InvocationError("path_must_be_absolute")
    return path


def _self_test() -> int:
    tests = (
        Path(__file__).with_name("test_plan_runner_cutover.py"),
        Path(__file__).with_name("test_plan_runner_live_canary.py"),
    )
    result = subprocess.run(
        [sys.executable, "-m", "unittest", *(str(path) for path in tests), "-v"],
        check=False,
    )
    return result.returncode


def _print_result(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "self-test":
            return _self_test()
        repository = _path(arguments.repo)
        assert repository is not None
        abandonment = _path(arguments.abandonment_file)
        if arguments.command == "audit":
            output = _path(arguments.output)
            assert output is not None
            report = audit_repository(
                repository, abandonment_file=abandonment
            )
            write_audit_report(output, report)
            _print_result(
                {
                    "status": (
                        "zero_use_confirmed"
                        if not report["blocker_codes"]
                        else "cutover_pending_legacy_runs"
                    ),
                    "report": str(output),
                    "report_sha256": report["report_sha256"],
                    "blocker_codes": report["blocker_codes"],
                }
            )
            if not report["blocker_codes"]:
                return 0
            return (
                65
                if any(code in INTEGRITY_BLOCKERS for code in report["blocker_codes"])
                else 3
            )
        report_path = _path(arguments.audit_report)
        assert report_path is not None
        report = read_report(report_path)
        if arguments.command == "apply":
            result = apply_cutover(
                repository, report, abandonment_file=abandonment
            )
        else:
            result = quarantine_legacy_caches(
                repository, report, abandonment_file=abandonment
            )
        _print_result(result)
        return 0
    except InvocationError as error:
        _print_result({"status": "failed", "reason_code": str(error)})
        return 64
    except CutoverError as error:
        result: dict[str, object] = {
            "status": "blocked",
            "reason_code": error.reason_code,
        }
        if error.details:
            result["details"] = error.details
        _print_result(result)
        return error.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
