"""Single-worktree sequential execution and plan-level resume."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Any, Sequence

from .launcher import CodexLauncher, LaunchResult
from .state import StateStore


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RESULT_REQUIRED_FIELDS = {
    "plan_id",
    "status",
    "head_commit",
    "verification",
    "summary",
}
_RECOVERY_RESULT_FIELDS = {
    "retryable",
    "failure_signature",
    "next_strategy",
}
_RESULT_OPTIONAL_FIELDS = {
    "workflow_receipt",
    *_RECOVERY_RESULT_FIELDS,
}
_WORKFLOW_RECEIPT_FIELDS = {
    "mode",
    "progress_ledger",
    "task_reviews",
    "final_review",
    "final_review_artifact",
    "duplicate_verification",
}
_COMPLETED_TASK = re.compile(
    r"^Task\s+([1-9][0-9]*):\s+complete\b",
    re.IGNORECASE | re.MULTILINE,
)


def _git(repository: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments], check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _ledger_progress(worktree: Path) -> tuple[list[str], str | None]:
    ledger = worktree / ".superpowers" / "sdd" / "progress.md"
    if ledger.is_symlink() or not ledger.is_file():
        return [], None
    try:
        text = ledger.read_bytes()[:65_536].decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return [], None
    numbers = sorted({int(match) for match in _COMPLETED_TASK.findall(text)})
    completed = [f"Task {number}" for number in numbers]
    current = 1
    known = set(numbers)
    while current in known:
        current += 1
    return completed, f"Task {current}"


def _write_private_json(path: Path, payload: dict[str, object]) -> Path:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write while persisting recovery capsule")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return path.resolve()


def _recovery_decision(
    *,
    payload: dict[str, object] | None,
    timed_out: bool,
    previous_signature: str | None,
    automatic_available: bool,
) -> tuple[bool, str, str, str]:
    status = payload.get("status") if payload is not None else None
    if timed_out:
        signature = "timeout"
        strategy = (
            "resume the first incomplete task from durable evidence "
            "after process timeout"
        )
    elif status == "interrupted":
        signature = "status:interrupted"
        strategy = (
            "resume the first incomplete task from durable evidence "
            "after child interruption"
        )
    elif (
        status == "failed"
        and payload is not None
        and payload.get("retryable") is True
    ):
        signature = str(payload["failure_signature"])
        strategy = str(payload["next_strategy"])
    else:
        return False, "not_retryable", "status:failed", ""
    if signature == previous_signature:
        return False, "repeated_failure_signature", signature, strategy
    if not automatic_available:
        return False, "automatic_limit", signature, strategy
    return True, "eligible", signature, strategy


class RunBusyError(RuntimeError):
    pass


class _RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> int:
        descriptor = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("run lock must be a regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise RunBusyError("run_busy") from exc
        except BaseException:
            os.close(descriptor)
            raise
        self.descriptor = descriptor
        return descriptor

    def __exit__(self, *_: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None


def _safe_worktree_artifact(worktree: Path, declared: object) -> bool:
    if not isinstance(declared, str) or not declared or len(declared) > 500:
        return False
    relative = Path(declared)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    candidate = worktree
    try:
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return False
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(worktree.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return resolved.is_file() and not resolved.is_symlink()


def _workflow_receipt_error(
    worktree: Path,
    receipt: object,
) -> str | None:
    if not isinstance(receipt, dict) or set(receipt) != _WORKFLOW_RECEIPT_FIELDS:
        return "invalid_workflow_receipt"
    expected = {
        "mode": "subagent-driven-lean",
        "task_reviews": "complete",
        "final_review": "approved",
        "duplicate_verification": "none",
    }
    if any(receipt.get(name) != value for name, value in expected.items()):
        return "invalid_workflow_receipt"
    for name in ("progress_ledger", "final_review_artifact"):
        if not _safe_worktree_artifact(worktree, receipt.get(name)):
            return "unsafe_workflow_artifact"
    return None


class SequentialRunner:
    def __init__(
        self,
        *,
        codex_home: Path | None = None,
        launcher: CodexLauncher | None = None,
    ) -> None:
        self.codex_home = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))).expanduser().resolve()
        schema = Path(__file__).resolve().parents[2] / "templates" / "plan-result-schema.json"
        self.launcher = launcher or CodexLauncher(schema_path=schema)

    def run(
        self,
        *,
        workspace: Path,
        specs: Sequence[Path],
        plans: Sequence[Path],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = run_id or f"cpe-{uuid.uuid4().hex[:16]}"
        if not _RUN_ID.fullmatch(identifier):
            raise ValueError("run ID contains unsupported characters")
        store = self._initialize_run(
            workspace=workspace,
            specs=specs,
            plans=plans,
            run_id=identifier,
        )
        try:
            with _RunLock(store.root / "run.lock") as lock_fd:
                try:
                    self._create_or_reconcile_worktree(store)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    try:
                        self._cleanup_created_worktree(store)
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                    store.state["status"] = "failed"
                    store.save()
                    reason = (str(exc).strip() or type(exc).__name__)[:2000]
                    store.append_event("run.creation_failed", reason=reason)
                    return self._summary(store, error=reason)
                try:
                    return self._execute(
                        store,
                        explicit_retry=False,
                        lock_fd=lock_fd,
                    )
                except KeyboardInterrupt:
                    return self._record_interrupted(store)
        except RunBusyError:
            return self._busy_summary(store)

    def resume(self, *, run_id: str, retry_failed: bool = False) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        try:
            with _RunLock(store.root / "run.lock") as lock_fd:
                store = StateStore.open(store.root)
                if store.state["status"] == "initializing":
                    self._create_or_reconcile_worktree(store)
                else:
                    self._verify_worktree(store)
                status = store.state["status"]
                if status == "completed":
                    if retry_failed:
                        raise ValueError("retry-failed requires a failed run")
                    return self._summary(store)
                if retry_failed != (status == "failed"):
                    if status == "failed":
                        raise ValueError("failed run requires --retry-failed")
                    if retry_failed:
                        raise ValueError("retry-failed requires a failed run")
                store.append_event("run.resumed", retry_failed=retry_failed)
                try:
                    return self._execute(
                        store,
                        explicit_retry=retry_failed,
                        lock_fd=lock_fd,
                    )
                except KeyboardInterrupt:
                    return self._record_interrupted(store)
        except RunBusyError:
            return self._busy_summary(store)

    def inspect(self, *, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        return self._summary(store)

    @staticmethod
    def _validate_workspace(repository: Path) -> None:
        if (
            not repository.is_dir()
            or _git(repository, "rev-parse", "--is-inside-work-tree") != "true"
        ):
            raise ValueError("workspace must be a Git repository")
        if _git(repository, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("workspace has tracked changes")

    def _initialize_run(
        self,
        *,
        workspace: Path,
        specs: Sequence[Path],
        plans: Sequence[Path],
        run_id: str,
    ) -> StateStore:
        repository = workspace.resolve(strict=True)
        self._validate_workspace(repository)
        source_commit = _git(repository, "rev-parse", "HEAD")
        run_root = self.codex_home / "orchestrator" / run_id
        worktree = self.codex_home / "worktrees" / run_id
        branch = f"codex/{run_id}"
        if run_root.exists():
            raise ValueError("run root already exists")
        if worktree.exists() or worktree.is_symlink():
            raise ValueError("run worktree already exists")
        branch_exists = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            check=False,
        ).returncode == 0
        if branch_exists:
            raise ValueError("run branch already exists")
        return StateStore.create(
            run_root=run_root,
            run_id=run_id,
            source_repository=repository,
            source_commit=source_commit,
            worktree=worktree,
            branch=branch,
            specs=specs,
            plans=plans,
            initial_status="initializing",
        )

    def _add_new_worktree(self, store: StateStore) -> None:
        state = store.state
        worktree = Path(state["worktree"])
        worktree.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        worktree.parent.chmod(0o700)
        subprocess.run(
            [
                "git",
                "-C",
                state["source_repository"],
                "worktree",
                "add",
                "-q",
                "-b",
                state["branch"],
                str(worktree),
                state["source_commit"],
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _cleanup_created_worktree(self, store: StateStore) -> None:
        state = store.state
        source = Path(state["source_repository"])
        worktree = Path(state["worktree"])
        if worktree.exists() or worktree.is_symlink():
            try:
                self._verify_worktree(store, allow_initializing=True)
            except (OSError, ValueError, subprocess.SubprocessError):
                return
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        branch_head = _git(
            source,
            "rev-parse",
            "--verify",
            f"refs/heads/{state['branch']}",
            check=False,
        )
        if branch_head == state["source_commit"]:
            subprocess.run(
                ["git", "-C", str(source), "branch", "-D", state["branch"]],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    def _create_or_reconcile_worktree(self, store: StateStore) -> None:
        state = store.state
        worktree = Path(state["worktree"])
        if worktree.is_symlink():
            raise ValueError("recorded worktree must not be a symlink")
        if not worktree.exists():
            source = Path(state["source_repository"])
            branch_head = _git(
                source,
                "rev-parse",
                "--verify",
                f"refs/heads/{state['branch']}",
                check=False,
            )
            if branch_head and branch_head != state["source_commit"]:
                raise ValueError("initializing branch is not at the source commit")
            if branch_head:
                worktree.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                worktree.parent.chmod(0o700)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(source),
                        "worktree",
                        "add",
                        "-q",
                        str(worktree),
                        state["branch"],
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                self._add_new_worktree(store)
        self._verify_worktree(store, allow_initializing=True)
        state["status"] = "running"
        store.save()
        store.append_event("worktree.ready", head=state["source_commit"])

    def _create_recovery_capsule(
        self,
        store: StateStore,
        plan: dict[str, Any],
        *,
        current_head: str,
        prior_result: Path,
        prior_log: Path | None,
    ) -> Path:
        try:
            payload = json.loads(prior_result.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        prior_status = payload.get("status")
        if prior_status not in {"interrupted", "blocked", "failed"}:
            prior_status = (
                plan["status"]
                if plan["status"] in {"interrupted", "blocked", "failed"}
                else "interrupted"
            )
        signature = payload.get("failure_signature")
        if not isinstance(signature, str) or not signature.strip():
            signature = f"status:{prior_status}"
        strategy = payload.get("next_strategy")
        if not isinstance(strategy, str) or not strategy.strip():
            strategy = (
                "resume the first incomplete task from durable evidence "
                "without redispatching completed tasks"
            )
        completed, current = _ledger_progress(Path(store.state["worktree"]))
        dirty = _git(
            Path(store.state["worktree"]),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ).splitlines()[:100]
        target = (
            store.root
            / "results"
            / f"{plan['plan_id']}-attempt-{plan['attempt_count']}-recovery.json"
        )
        return _write_private_json(
            target,
            {
                "plan_id": plan["plan_id"],
                "attempt": plan["attempt_count"],
                "starting_commit": plan["starting_commit"],
                "current_head": current_head,
                "completed_tasks": completed,
                "current_task": current,
                "prior_status": prior_status,
                "failure_signature": signature[:256],
                "next_strategy": strategy[:1000],
                "dirty_files": dirty,
                "prior_result_path": str(prior_result.resolve()),
                "prior_log_path": (
                    str(prior_log.resolve()) if prior_log is not None else None
                ),
            },
        )

    def _execute(
        self,
        store: StateStore,
        *,
        explicit_retry: bool,
        lock_fd: int,
    ) -> dict[str, Any]:
        state = store.state
        while state["current_plan_index"] < len(state["plans"]):
            index = state["current_plan_index"]
            plan = state["plans"][index]
            if plan["status"] == "completed":
                state["current_plan_index"] += 1
                store.save()
                continue
            automatic_available = (
                plan["attempt_count"] == 0 and not explicit_retry
            )
            operator_attempt = explicit_retry or plan["attempt_count"] > 0
            explicit_retry = False
            while True:
                worktree = Path(state["worktree"])
                current_head = _git(worktree, "rev-parse", "HEAD")
                if plan["starting_commit"] is None:
                    plan["starting_commit"] = current_head
                previous_attempt = plan["attempt_count"]
                prior_result = (
                    Path(plan["result_path"])
                    if plan["result_path"]
                    else None
                )
                prior_log = None
                if previous_attempt:
                    candidate = (
                        store.root
                        / "logs"
                        / f"{plan['plan_id']}-attempt-{previous_attempt}.log"
                    )
                    if candidate.is_file() and not candidate.is_symlink():
                        prior_log = candidate
                recovery_path = (
                    self._create_recovery_capsule(
                        store,
                        plan,
                        current_head=current_head,
                        prior_result=prior_result,
                        prior_log=prior_log,
                    )
                    if prior_result is not None and previous_attempt > 0
                    else None
                )
                plan["attempt_count"] += 1
                result_path, log_path = self.launcher.attempt_paths(
                    store.root / "results",
                    store.root / "logs",
                    plan["plan_id"],
                    plan["attempt_count"],
                )
                descriptor = os.open(
                    result_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                result_directory = os.open(result_path.parent, os.O_RDONLY)
                try:
                    os.fsync(result_directory)
                finally:
                    os.close(result_directory)
                plan["result_path"] = str(result_path.resolve())
                plan["status"] = "running"
                state["status"] = "running"
                store.save()
                store.append_event("plan.attempt_started", plan_id=plan["plan_id"], attempt=plan["attempt_count"], head=current_head)
                plan_input = next(record for record in state["inputs"] if record["document_id"] == plan["plan_id"])
                spec_paths = [Path(record["snapshot_path"]) for record in state["inputs"] if record["role"] == "spec"]
                outcome = self.launcher.launch(
                    worktree=worktree, plan_id=plan["plan_id"], plan_path=Path(plan_input["snapshot_path"]),
                    spec_paths=spec_paths, starting_commit=plan["starting_commit"], current_commit=current_head,
                    result_path=result_path, log_path=log_path, lock_fd=lock_fd,
                    recovery_path=recovery_path,
                )
                store.append_event(
                    "plan.attempt_finished",
                    plan_id=plan["plan_id"],
                    attempt=plan["attempt_count"],
                    returncode=outcome.returncode,
                    timed_out=outcome.timed_out,
                    forced_cleanup=outcome.forced_cleanup,
                    discarded_log_bytes=outcome.discarded_log_bytes,
                )
                plan["result_path"] = (
                    str(outcome.result_path.resolve())
                    if outcome.payload is not None
                    else str(self._synthetic_result(store, plan, outcome))
                )
                if outcome.timed_out:
                    plan["status"] = "interrupted"
                    state["status"] = "interrupted"
                    store.save()
                    store.append_event(
                        "plan.attempt_incomplete",
                        plan_id=plan["plan_id"],
                        status="interrupted",
                        timed_out=True,
                    )
                else:
                    integrity_error = self._handoff_error(store, plan, outcome)
                    if integrity_error is not None:
                        plan["status"] = "failed"
                        state["status"] = "failed"
                        store.save()
                        store.append_event(
                            "plan.integrity_failed",
                            plan_id=plan["plan_id"],
                            reason=integrity_error,
                        )
                        return self._summary(store, error=integrity_error)
                    payload = outcome.payload
                    assert payload is not None
                    status = payload["status"]
                    if status == "completed":
                        self._seal_result(outcome.result_path)
                        plan["status"] = "completed"
                        plan["accepted_commit"] = payload["head_commit"]
                        state["current_plan_index"] += 1
                        state["status"] = (
                            "completed"
                            if state["current_plan_index"]
                            == len(state["plans"])
                            else "running"
                        )
                        store.save()
                        store.append_event(
                            "plan.completed",
                            plan_id=plan["plan_id"],
                            head=payload["head_commit"],
                        )
                        break
                    plan["status"] = status
                    state["status"] = status
                    if status == "blocked":
                        store.save()
                        store.append_event(
                            "plan.blocked",
                            plan_id=plan["plan_id"],
                        )
                        return self._summary(store)
                    store.save()
                    store.append_event(
                        "plan.attempt_incomplete",
                        plan_id=plan["plan_id"],
                        status=status,
                    )

                previous_signature = None
                if prior_result is not None:
                    try:
                        previous_payload = json.loads(
                            prior_result.read_text(encoding="utf-8")
                        )
                    except (
                        OSError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ):
                        previous_payload = {}
                    if isinstance(previous_payload, dict):
                        candidate = previous_payload.get("failure_signature")
                        if isinstance(candidate, str) and candidate.strip():
                            previous_signature = candidate
                        elif previous_payload.get("status") == "interrupted":
                            previous_signature = "status:interrupted"

                retry, reason, signature, strategy = _recovery_decision(
                    payload=outcome.payload,
                    timed_out=outcome.timed_out,
                    previous_signature=previous_signature,
                    automatic_available=(
                        automatic_available and not operator_attempt
                    ),
                )
                if retry:
                    automatic_available = False
                    store.append_event(
                        "plan.recovery_scheduled",
                        plan_id=plan["plan_id"],
                        failure_signature=signature,
                        next_strategy=strategy,
                    )
                    continue
                store.append_event(
                    "plan.recovery_stopped",
                    plan_id=plan["plan_id"],
                    reason=reason,
                    failure_signature=signature,
                )
                plan["status"] = "failed"
                state["status"] = "failed"
                store.save()
                store.append_event(
                    "plan.failed",
                    plan_id=plan["plan_id"],
                    attempts=plan["attempt_count"],
                )
                return self._summary(store)

        state["status"] = "completed"
        store.save()
        store.append_event("run.completed", head=_git(Path(state["worktree"]), "rev-parse", "HEAD"))
        return self._summary(store)

    def _handoff_error(self, store: StateStore, plan: dict[str, Any], outcome: LaunchResult) -> str | None:
        payload = outcome.payload
        if not isinstance(payload, dict):
            return "invalid_result"
        fields = set(payload)
        if (
            not _RESULT_REQUIRED_FIELDS.issubset(fields)
            or fields - _RESULT_REQUIRED_FIELDS - _RESULT_OPTIONAL_FIELDS
        ):
            return "invalid_result"
        if payload.get("plan_id") != plan["plan_id"] or payload.get("status") not in {"completed", "interrupted", "blocked", "failed"}:
            return "invalid_result"
        head = payload.get("head_commit")
        summary = payload.get("summary")
        verification = payload.get("verification")
        if not isinstance(head, str) or not _SHA.fullmatch(head) or not isinstance(summary, str) or not summary.strip() or len(summary) > 2000 or not isinstance(verification, list):
            return "invalid_result"
        recovery_fields = fields & _RECOVERY_RESULT_FIELDS
        if recovery_fields and recovery_fields != _RECOVERY_RESULT_FIELDS:
            return "invalid_result"
        if recovery_fields:
            if (
                not isinstance(payload["retryable"], bool)
                or not isinstance(payload["failure_signature"], str)
                or not payload["failure_signature"].strip()
                or len(payload["failure_signature"]) > 256
                or not isinstance(payload["next_strategy"], str)
                or not payload["next_strategy"].strip()
                or len(payload["next_strategy"]) > 1000
                or payload.get("status") == "completed"
            ):
                return "invalid_result"
        for item in verification:
            if not isinstance(item, dict) or set(item) != {"command", "exit_code"} or not isinstance(item["command"], str) or not item["command"].strip() or not isinstance(item["exit_code"], int) or isinstance(item["exit_code"], bool):
                return "invalid_result"
        worktree = Path(store.state["worktree"])
        observed = _git(worktree, "rev-parse", "HEAD")
        if head != observed:
            return "wrong_head"
        ancestry = subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["starting_commit"], head], check=False).returncode
        if ancestry != 0:
            return "broken_ancestry"
        if payload["status"] == "completed":
            receipt_error = _workflow_receipt_error(
                worktree,
                payload.get("workflow_receipt"),
            )
            if receipt_error is not None:
                return receipt_error
        elif "workflow_receipt" in payload:
            return "invalid_result"
        if payload["status"] != "completed":
            return None
        if outcome.returncode != 0:
            return "nonzero_exit"
        if outcome.timed_out:
            return "timed_out"
        if outcome.forced_cleanup:
            return "forced_cleanup"
        if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
            return "dirty_handoff"
        if not verification or any(item["exit_code"] != 0 for item in verification):
            return "verification_failed"
        return None

    @staticmethod
    def _seal_result(path: Path) -> None:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("accepted result must be a regular file")
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _verify_worktree(
        self,
        store: StateStore,
        *,
        allow_initializing: bool = False,
    ) -> None:
        state = store.state
        worktree = Path(state["worktree"])
        source = Path(state["source_repository"])
        if (
            worktree.is_symlink()
            or not worktree.is_dir()
            or _git(worktree, "rev-parse", "--show-toplevel")
            != str(worktree.resolve())
        ):
            raise ValueError("recorded worktree is missing or changed")
        source_common = Path(_git(source, "rev-parse", "--git-common-dir"))
        worktree_common = Path(_git(worktree, "rev-parse", "--git-common-dir"))
        if not source_common.is_absolute():
            source_common = source / source_common
        if not worktree_common.is_absolute():
            worktree_common = worktree / worktree_common
        if source_common.resolve(strict=True) != worktree_common.resolve(strict=True):
            raise ValueError("recorded worktree belongs to a different repository")
        if _git(worktree, "branch", "--show-current") != state["branch"]:
            raise ValueError("recorded worktree branch changed")
        current_head = _git(worktree, "rev-parse", "HEAD")
        if allow_initializing and current_head != state["source_commit"]:
            raise ValueError("initializing worktree is not at the source commit")
        if subprocess.run(
            ["git", "-C", str(worktree), "merge-base", "--is-ancestor", state["source_commit"], current_head],
            check=False,
        ).returncode != 0:
            raise ValueError("worktree HEAD no longer descends from the source commit")
        for plan in state["plans"]:
            if plan["status"] == "completed":
                if subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["accepted_commit"], "HEAD"], check=False).returncode != 0:
                    raise ValueError("accepted plan commit is not in worktree history")
            elif plan["starting_commit"] is not None and subprocess.run(
                ["git", "-C", str(worktree), "merge-base", "--is-ancestor", plan["starting_commit"], current_head],
                check=False,
            ).returncode != 0:
                raise ValueError("current plan history no longer descends from its starting commit")

    @staticmethod
    def _synthetic_result(store: StateStore, plan: dict[str, Any], outcome: LaunchResult) -> Path:
        target = store.root / "results" / f"{plan['plan_id']}-attempt-{plan['attempt_count']}-synthetic.json"
        worktree = Path(store.state["worktree"])
        observed = _git(worktree, "rev-parse", "HEAD") if worktree.is_dir() else store.state["source_commit"]
        status = "interrupted" if outcome.timed_out else "failed"
        payload = {
            "plan_id": plan["plan_id"], "status": status, "head_commit": observed,
            "verification": [],
            "summary": f"child produced no valid result; returncode={outcome.returncode}; timed_out={outcome.timed_out}; log={outcome.log_path}",
        }
        if outcome.timed_out:
            payload.update(
                retryable=True,
                failure_signature="timeout",
                next_strategy=(
                    "resume the first incomplete task from durable evidence "
                    "after process timeout"
                ),
            )
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        target.chmod(0o600)
        return target.resolve()

    @staticmethod
    def _summary(store: StateStore, *, error: str | None = None) -> dict[str, Any]:
        state = store.state
        worktree = Path(state["worktree"])
        head = _git(worktree, "rev-parse", "HEAD") if worktree.is_dir() else state["source_commit"]
        visible_plans = state["plans"][:100]
        result = {
            "run_id": state["run_id"], "status": state["status"], "source_commit": state["source_commit"],
            "worktree": state["worktree"], "branch": state["branch"], "head_commit": head,
            "current_plan_index": state["current_plan_index"],
            "plan_count": len(state["plans"]),
            "plans_truncated": len(state["plans"]) > len(visible_plans),
            "plans": [
                {key: plan[key] for key in ("plan_id", "status", "starting_commit", "accepted_commit", "attempt_count", "result_path")}
                for plan in visible_plans
            ],
        }
        if error:
            result["error"] = error
        return result

    def _busy_summary(self, store: StateStore) -> dict[str, Any]:
        result = self._summary(store, error="run_busy")
        result["status"] = "interrupted"
        return result

    def _record_interrupted(self, store: StateStore) -> dict[str, Any]:
        try:
            store = StateStore.open(store.root)
        except ValueError:
            pass
        if store.state["status"] in {
            "completed",
            "blocked",
            "failed",
            "interrupted",
        }:
            return self._summary(store)
        index = store.state["current_plan_index"]
        if index < len(store.state["plans"]):
            current = store.state["plans"][index]
            if current["status"] == "running":
                current["status"] = "interrupted"
        store.state["status"] = "interrupted"
        store.save()
        store.append_event("run.interrupted", plan_index=index)
        return self._summary(store)
