"""Fresh, bounded Codex child-process launcher for schema-4 CPE roles."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .contracts import (
    AUTHORITY_CODES,
    CHILD_ROLES,
    WRITE_ROLES,
    ChildResult,
    normalize_relative_path,
    validate_child_result,
)
from .store import RunStore
from .worktree import Worktree


_SECRET_ENV = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
    }
)
_FINAL_ROLES = frozenset({"document_auditor", "program_final_integrator"})
_FIX_ROLES = frozenset({"task_agent", "fix_agent", "integration_fix_agent"})


@dataclass(frozen=True)
class ChildRequest:
    role: str
    item_id: str
    goal: str
    input_paths: tuple[Path, ...]
    repository: Path
    worktree: Path
    outbox: Path
    report_path: str
    applicable_skills: tuple[str, ...]
    done_when: tuple[str, ...]


@dataclass(frozen=True)
class LaunchOutcome:
    result: ChildResult
    event_digest: str
    elapsed_ms: int


def _bounded_text(value: object, name: str, limit: int = 4000) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or "\x00" in value
    ):
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value.strip()


def _resolved_directory(path: Path, name: str) -> Path:
    if not isinstance(path, Path):
        raise ValueError(f"{name} must be a pathlib.Path")
    declared = path.expanduser()
    if declared.is_symlink():
        raise ValueError(f"{name} must be a real directory, not a symlink")
    try:
        resolved = declared.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{name} is unavailable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise ValueError(f"{name} must be a real directory")
    return resolved


def _validate_or_normalize_child_result(
    payload: object, *, expected_role: str, expected_item_id: str
) -> ChildResult:
    """Turn only a structurally valid non-allowlisted authority into failure."""

    try:
        return validate_child_result(
            payload,
            expected_role=expected_role,
            expected_item_id=expected_item_id,
        )
    except ValueError:
        if not isinstance(payload, Mapping):
            raise
        authority_id = payload.get("authority_id")
        if (
            payload.get("status") != "waiting_authority"
            or not isinstance(authority_id, str)
            or not authority_id.strip()
            or authority_id in AUTHORITY_CODES
        ):
            raise
        normalized = dict(payload)
        normalized["status"] = "failed"
        normalized["failure_code"] = "invalid_authority_handoff"
        normalized["authority_id"] = None
        normalized["affected_document_ids"] = []
        return validate_child_result(
            normalized,
            expected_role=expected_role,
            expected_item_id=expected_item_id,
        )


class ChildLauncher:
    def __init__(
        self,
        *,
        schema_path: Path,
        codex_bin: str = "codex",
        timeout_seconds: float = 1800,
        terminate_grace_seconds: float = 2,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        try:
            self.schema_path = schema_path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError("child-result schema is unavailable") from exc
        if not self.schema_path.is_file() or self.schema_path.is_symlink():
            raise ValueError("child-result schema must be a regular file")
        try:
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("child-result schema is invalid JSON") from exc
        if not isinstance(schema, dict) or schema.get("additionalProperties") is not False:
            raise ValueError("child-result schema must be the strict shared schema")
        if not isinstance(codex_bin, str) or not codex_bin:
            raise ValueError("codex_bin must be a non-empty executable name")
        if timeout_seconds <= 0 or terminate_grace_seconds <= 0:
            raise ValueError("child timeouts must be positive")
        self.codex_bin = codex_bin
        self.timeout_seconds = float(timeout_seconds)
        self.terminate_grace_seconds = float(terminate_grace_seconds)
        self.environ = dict(os.environ if environ is None else environ)
        self._writer_lease = threading.RLock()
        self._writer_lifecycle_state = threading.local()

    @contextmanager
    def writer_lifecycle(self, store: RunStore) -> Iterator[None]:
        """Own one run's writer lifecycle through durable result publication."""

        lease_path = str(store.paths.writer_lease)
        depth = getattr(self._writer_lifecycle_state, "depth", 0)
        if depth:
            if getattr(self._writer_lifecycle_state, "lease_path", None) != lease_path:
                raise ValueError("nested writer lifecycle names a different run")
            self._writer_lifecycle_state.depth = depth + 1
            try:
                yield
            finally:
                self._writer_lifecycle_state.depth -= 1
            return

        if not self._writer_lease.acquire(blocking=False):
            raise ValueError("another write role already holds the writer lease")
        descriptor = -1
        try:
            descriptor = os.open(
                store.paths.writer_lease,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise ValueError("run-owned writer lease must remain a private regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another write role already holds the writer lease") from exc
            self._writer_lifecycle_state.depth = 1
            self._writer_lifecycle_state.lease_path = lease_path
            yield
        finally:
            self._writer_lifecycle_state.depth = 0
            self._writer_lifecycle_state.lease_path = None
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
            self._writer_lease.release()

    def _validate_request(
        self, request: ChildRequest, worktree: Worktree, store: RunStore
    ) -> tuple[tuple[Path, ...], Path, str]:
        if not isinstance(request, ChildRequest):
            raise ValueError("child request must use the fixed ChildRequest contract")
        if request.role not in CHILD_ROLES:
            raise ValueError("child request role is not allowlisted")
        _bounded_text(request.item_id, "item_id", 256)
        _bounded_text(request.goal, "goal")
        if _resolved_directory(request.repository, "repository") != worktree.source:
            raise ValueError("child repository does not match worktree ownership")
        if _resolved_directory(request.worktree, "worktree") != worktree.root:
            raise ValueError("child worktree does not match worktree ownership")
        outbox = _resolved_directory(request.outbox, "outbox")
        try:
            relative_outbox = outbox.relative_to(store.paths.outbox.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise ValueError("child outbox is outside the run-owned outbox") from exc
        if len(relative_outbox.parts) != 1 or relative_outbox.parts[0] in {"", ".", ".."}:
            raise ValueError("child outbox must be one allocated attempt directory")
        report_path = normalize_relative_path(request.report_path)
        if report_path == ".child-result.json":
            raise ValueError("report path conflicts with the launcher result path")

        inputs: list[Path] = []
        for input_path in request.input_paths:
            if not isinstance(input_path, Path) or input_path.is_symlink():
                raise ValueError("child input paths must be real pathlib files")
            try:
                resolved = input_path.expanduser().resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"child input path is unavailable: {input_path}") from exc
            if not resolved.is_file():
                raise ValueError("child input paths must be regular files")
            if resolved in inputs:
                raise ValueError("child input paths must be unique")
            inputs.append(resolved)
        if not inputs:
            raise ValueError("child request needs at least one exact input path")
        for skill in request.applicable_skills:
            _bounded_text(skill, "applicable skill", 128)
        if not request.done_when:
            raise ValueError("child request needs at least one Done when condition")
        for condition in request.done_when:
            _bounded_text(condition, "Done when condition", 1000)
        worktree.verify_identity()
        return tuple(inputs), outbox, report_path

    @staticmethod
    def _prompt(
        request: ChildRequest,
        *,
        input_paths: tuple[Path, ...],
        repository: Path,
        worktree: Path,
        outbox: Path,
        report_path: str,
    ) -> str:
        skills = list(request.applicable_skills)
        if request.role in _FIX_ROLES:
            for required in ("using-superpowers", "test-driven-development"):
                if required not in skills:
                    skills.append(required)
        if request.role in _FINAL_ROLES and "verification-before-completion" not in skills:
            skills.append("verification-before-completion")

        lines = [
            f"CPE_ROLE: {request.role}",
            f"ITEM: {request.item_id}",
            "",
            "Goal:",
            request.goal.strip(),
            "",
            "Exact input paths:",
        ]
        lines.extend(f"- {path}" for path in input_paths)
        lines.extend(
            [
                "",
                "Repository and isolated worktree:",
                f"- repository: {repository}",
                f"- worktree: {worktree}",
                "",
                "Write boundary:",
                (
                    "- You may edit product files only in the isolated worktree and may "
                    "write durable handoff artifacts only below the attempt outbox."
                    if request.role in WRITE_ROLES
                    else "- Read-only role: do not change Git HEAD, the index, tracked files, "
                    "or untracked files; write only handoff artifacts below the attempt outbox."
                ),
                f"- attempt outbox: {outbox}",
                f"OUTBOX_REPORT_PATH: {report_path}",
                "",
                "Applicable Superpowers skills:",
            ]
        )
        lines.extend(f"- {skill}" for skill in skills or ("using-superpowers",))
        if request.role in _FIX_ROLES:
            lines.extend(
                [
                    "- Invoke using-superpowers before work.",
                    "- Use test-driven-development for every behavior change.",
                    "- Run focused covering checks, self-review the changed scope, create "
                    "exactly one commit, and leave full Git status clean.",
                ]
            )
        if request.role == "reviewer":
            lines.append(
                "- Review the supplied evidence and diff; do not rerun the implementer's "
                "identical focused tests on the same revision."
            )
        if request.role in _FINAL_ROLES:
            lines.append(
                "- Invoke verification-before-completion before making any terminal claim."
            )
        lines.extend(
            [
                "",
                "Fixed result contract:",
                "- Return exactly these fields: role, status, item_id, commit, verdict, "
                "failure_code, authority_id, strategy_key, affected_document_ids, "
                "artifact_paths, summary.",
                f"- role must be {request.role}; item_id must be {request.item_id}.",
                "- artifact_paths are normalized POSIX paths relative to the attempt outbox.",
                "- Put detailed reasoning and logs in the outbox report, not in summary.",
                "",
                "Standing autonomy:",
                "- Resolve ordinary defects, failing tests, review findings, internal technical "
                "choices, and recoverable tool problems autonomously within approved scope.",
                "- Prefer explicit requirements, repository conventions, the smallest reversible "
                "change, lowest risk, strongest testability, and least machinery, in that order.",
                "",
                "User authority is limited to exactly these six codes:",
            ]
        )
        lines.extend(f"- {code}" for code in sorted(AUTHORITY_CODES))
        lines.extend(["", "Done when:"])
        lines.extend(f"- {condition}" for condition in request.done_when)
        return "\n".join(lines) + "\n"

    def _environment(self) -> dict[str, str]:
        environment = {
            key: value for key, value in self.environ.items() if key not in _SECRET_ENV
        }
        if "PATH" not in environment or "CODEX_HOME" not in environment:
            raise ValueError("child environment must preserve PATH and CODEX_HOME")
        return environment

    @staticmethod
    def _event_digest(stdout: str) -> str:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("Codex child stdout is not JSONL") from exc
            if not isinstance(event, dict):
                raise ValueError("Codex child event must be a JSON object")
        return hashlib.sha256(stdout.encode("utf-8")).hexdigest()

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        return True

    def _terminate_process_group(
        self, process: subprocess.Popen[str], pgid: int
    ) -> None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            pass

        if self._process_group_exists(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=self.terminate_grace_seconds)
            except subprocess.TimeoutExpired as reap_exc:
                raise RuntimeError("could not reap timed-out Codex child") from reap_exc
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def launch(
        self,
        request: ChildRequest,
        *,
        worktree: Worktree,
        store: RunStore,
        ingest_artifacts: bool = True,
    ) -> LaunchOutcome:
        if request.role not in WRITE_ROLES:
            return self._launch_once(
                request,
                worktree=worktree,
                store=store,
                ingest_artifacts=ingest_artifacts,
            )
        with self.writer_lifecycle(store):
            return self._launch_once(
                request,
                worktree=worktree,
                store=store,
                ingest_artifacts=ingest_artifacts,
            )

    def _launch_once(
        self,
        request: ChildRequest,
        *,
        worktree: Worktree,
        store: RunStore,
        ingest_artifacts: bool = True,
    ) -> LaunchOutcome:
        if not isinstance(ingest_artifacts, bool):
            raise ValueError("ingest_artifacts must be a boolean")
        input_paths, outbox, report_path = self._validate_request(request, worktree, store)
        before_head = worktree.head()
        before_status = worktree.status()
        if before_status:
            raise ValueError("child launch requires a clean isolated worktree")

        environment = self._environment()
        codex_bin = shutil.which(self.codex_bin, path=environment["PATH"])
        if codex_bin is None:
            raise ValueError("codex executable was not found in inherited PATH")
        last_message = outbox / ".child-result.json"
        if last_message.exists() or last_message.is_symlink():
            raise ValueError("child result path already exists")
        argv = [
            codex_bin,
            "exec",
            "--ignore-user-config",
            "--json",
            "--sandbox",
            "workspace-write" if request.role in WRITE_ROLES else "read-only",
            "-C",
            str(worktree.root),
            "--add-dir",
            str(outbox),
            "--output-schema",
            str(self.schema_path),
            "--output-last-message",
            str(last_message),
            "-",
        ]
        prompt = self._prompt(
            request,
            input_paths=input_paths,
            repository=worktree.source,
            worktree=worktree.root,
            outbox=outbox,
            report_path=report_path,
        )
        started = time.monotonic()
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
            start_new_session=True,
        )
        pgid = process.pid
        try:
            stdout, stderr = process.communicate(prompt, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_group(process, pgid)
            raise TimeoutError(
                f"Codex child timed out after {self.timeout_seconds:g} seconds"
            ) from exc

        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        event_digest = self._event_digest(stdout)
        if process.returncode != 0:
            detail = stderr.strip()[-2000:]
            raise ValueError(
                f"Codex child exited with {process.returncode}: {detail or 'no stderr'}"
            )
        try:
            if last_message.is_symlink() or not last_message.is_file():
                raise ValueError("Codex child did not write a regular last message")
            payload = json.loads(last_message.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Codex child last message is invalid") from exc
        result = _validate_or_normalize_child_result(
            payload,
            expected_role=request.role,
            expected_item_id=request.item_id,
        )

        if request.role in WRITE_ROLES:
            if result.status == "completed":
                assert result.commit is not None
                worktree.verify_write_handoff(result.commit)
            elif result.commit is None:
                worktree.verify_read_only_handoff(before_head, before_status)
            else:
                worktree.verify_write_handoff(result.commit)
        else:
            worktree.verify_read_only_handoff(before_head, before_status)

        if ingest_artifacts:
            attempt_id = outbox.name
            ingested = store.ingest_outbox(attempt_id, result.artifact_paths)
            if ingested != result.artifact_paths:
                raise ValueError("ingested artifacts differ from the child result")
        return LaunchOutcome(result=result, event_digest=event_digest, elapsed_ms=elapsed_ms)
