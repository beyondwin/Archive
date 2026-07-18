"""Single-worktree sequential execution and plan-level resume."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import socket
import stat
import subprocess
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .capabilities import (
    CapabilityObservation,
    environment_fingerprint,
    typed_blockers,
)
from .compiler import (
    CompiledIndexService,
    default_operator_contract,
    validate_compiled_index,
)
from .evidence import (
    EnvelopeRepair,
    append_execution_event,
    execution_event_digest,
    has_current_unsafe_envelope_failure,
    ingest_plan_evidence,
    prepare_plan_evidence,
    read_private_result,
    read_progress_snapshot,
    repair_result_envelope,
    result_artifact_digest,
    seal_private_result,
    validate_execution_ledger,
)
from .launcher import (
    CodexLauncher,
    LaunchResult,
    StructuredLaunchRequest,
)
from .progress import (
    CheckpointBudget,
    CheckpointDecision,
    ProgressSnapshot,
    decide_child_outcome,
    progress_fingerprint,
)
from .reporting import (
    OptimizationMarkdownError,
    build_optimization_report,
    write_optimization_reports,
)
from .result_validation import (
    WORKFLOW_RECEIPT_FIELDS,
    normalize_result_v2,
    strict_json_object,
)
from .state import PRE_EXECUTION_WORKTREE_BLOCKER, StateStore, atomic_private_write
from .verification import (
    VerificationRequest,
    execute_verification,
    find_reusable_receipt,
    materialize_helper_descriptor,
    validate_recorded_receipt_path,
    verification_cache_key,
)


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}$")
_RUN_COMPLETED_FIELDS = {
    "event_id", "at", "source", "run_id", "category", "action", "head",
}
_COMPLETED_TASK = re.compile(
    r"^Task\s+([1-9][0-9]*):\s+complete\b",
    re.IGNORECASE | re.MULTILINE,
)
_VERIFY_PHASES = {
    "task": {"task_red", "task_green"},
    "affected": {"task_green"},
    "branch_final": {"final_verification"},
}
_VERIFY_POLICIES = {
    "forbidden": {"immutable"},
    "declared_external_state": {"digest_complete", "always_execute"},
}


def _capability_ids(compiled_index: Mapping[str, object]) -> set[str]:
    identifiers: set[str] = set()
    plans = compiled_index.get("plans")
    if not isinstance(plans, list):
        return identifiers
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        capabilities = plan.get("capabilities")
        if not isinstance(capabilities, list):
            continue
        for capability in capabilities:
            if isinstance(capability, Mapping):
                identifier = capability.get("capability_id")
                if isinstance(identifier, str):
                    identifiers.add(identifier)
    return identifiers


def _observe_capabilities(
    workspace: Path,
    compiled_index: Mapping[str, object],
) -> list[CapabilityObservation]:
    """Run only CPE-required probes plus explicitly declared loopback binding."""
    observations: list[CapabilityObservation] = []
    try:
        descriptor = os.open(
            workspace,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        os.close(descriptor)
        repository_outcome, repository_reason = "available", "readable"
    except OSError:
        repository_outcome, repository_reason = "unavailable", "not_readable"
    observations.append(CapabilityObservation(
        "repository_read", "workspace", repository_outcome, repository_reason,
        "parent_observed", {},
    ))

    probe = workspace / f".cpe-write-probe-{uuid.uuid4().hex}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            probe,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        probe.unlink()
        write_outcome, write_reason = "available", "writable"
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        try:
            probe.unlink()
        except OSError:
            pass
        write_outcome, write_reason = "unavailable", "not_writable"
    observations.append(CapabilityObservation(
        "workspace_write", "workspace", write_outcome, write_reason,
        "parent_observed", {},
    ))

    try:
        completed = subprocess.run(
            ["git", "--version"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        git_available = completed.returncode == 0
    except OSError:
        git_available = False
    observations.append(CapabilityObservation(
        "git", "workspace", "available" if git_available else "unavailable",
        "available" if git_available else "command_unavailable",
        "parent_observed", {},
    ))

    if "loopback_bind" in _capability_ids(compiled_index):
        loopback = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            loopback.bind(("127.0.0.1", 0))
            loopback_outcome, loopback_reason = "available", "bound"
        except OSError:
            loopback_outcome, loopback_reason = "unavailable", "permission_denied"
        finally:
            loopback.close()
        observations.append(CapabilityObservation(
            "loopback_bind", "workspace", loopback_outcome, loopback_reason,
            "parent_observed", {"host": "127.0.0.1"},
        ))
    return observations


def _current_head(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "HEAD")


def _resume_preflight(
    state: Mapping[str, object],
    observations: Sequence[CapabilityObservation],
) -> str:
    plans = state.get("plans")
    index = state.get("current_plan_index")
    if not isinstance(plans, list) or not isinstance(index, int) or index >= len(plans):
        return "launch"
    plan = plans[index]
    if not isinstance(plan, Mapping):
        return "launch"
    previous = plan.get("environment_fingerprint")
    blockers = typed_blockers(observations)
    if not blockers or not isinstance(previous, str):
        return "environment_changed" if isinstance(previous, str) else "launch"
    current = environment_fingerprint(observations)
    return (
        "unchanged_environment_blocker"
        if current == previous
        else "environment_changed"
    )


def _record_checkpoint(
    state: dict[str, object],
    decision: CheckpointDecision,
) -> None:
    plans = state["plans"]
    index = state["current_plan_index"]
    assert isinstance(plans, list) and isinstance(index, int)
    plan = plans[index]
    assert isinstance(plan, dict)
    changed = plan["progress_fingerprint"] != decision.progress_fingerprint
    plan["checkpoint_count"] += 1
    if changed:
        plan["progress_checkpoint_count"] += 1
        plan["consecutive_no_progress_slices"] = 0
    else:
        plan["consecutive_no_progress_slices"] += 1
    plan["progress_fingerprint"] = decision.progress_fingerprint


class ProgressLedgerError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _decision_scoped_events(
    store: StateStore,
    action: str,
    decision_id: str,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for line in store.events_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if (
            isinstance(payload, dict)
            and payload.get("action") == action
            and payload.get("decision_id") == decision_id
        ):
            matches.append(payload)
    return matches


def _ensure_decision_scoped_event(
    store: StateStore,
    action: str,
    decision_id: str,
    **details: object,
) -> None:
    matches = _decision_scoped_events(store, action, decision_id)
    if len(matches) > 1:
        raise ValueError(f"{action} event is duplicated")
    expected = {"decision_id": decision_id, **details}
    if matches:
        if any(matches[0].get(name) != value for name, value in expected.items()):
            raise ValueError(f"{action} event does not match decision journal")
    else:
        store.append_event(action, **expected)


def _persist_checkpoint_decision(
    store: StateStore,
    decision: CheckpointDecision,
    *,
    timed_out: bool,
    head: str,
    evidence_manifest_sha256: str | None,
) -> None:
    state = store.state
    plan = state["plans"][state["current_plan_index"]]
    previous = plan["progress_fingerprint"]
    if not isinstance(previous, str):
        raise ValueError("checkpoint decision baseline is unavailable")
    if plan["pending_checkpoint_decision"] is not None:
        raise ValueError("checkpoint decision journal is already pending")
    plan["pending_checkpoint_decision"] = {
        "decision_id": uuid.uuid4().hex,
        "plan_id": plan["plan_id"],
        "attempt": plan["attempt_count"],
        "decision": decision.action,
        "reason": decision.reason_code,
        "progress_fingerprint": decision.progress_fingerprint,
        "previous_progress_fingerprint": previous,
        "timed_out": timed_out,
        "head": head,
        "evidence_manifest_sha256": evidence_manifest_sha256,
    }
    store.save()


def _pre_spawn_budget_decision(
    plan: Mapping[str, object],
    *,
    head: str,
) -> CheckpointDecision | None:
    budget = plan.get("budget")
    if not isinstance(budget, Mapping):
        raise ValueError("plan budget is unavailable")
    reason = None
    if plan.get("progress_checkpoint_count", 0) >= budget["max_progress_checkpoints"]:
        reason = "checkpoint_budget_exhausted"
    elif plan.get("controller_launch_count", 0) >= budget["max_controller_launches"]:
        reason = "launch_budget_exhausted"
    elif plan.get("plan_elapsed_seconds", 0) >= budget["plan_wall_budget_seconds"]:
        reason = "wall_budget_exhausted"
    if reason is None:
        return None
    fingerprint = plan.get("progress_fingerprint")
    if not isinstance(fingerprint, str):
        fingerprint = progress_fingerprint(ProgressSnapshot(head, (), None))
    return CheckpointDecision("stop_budget", reason, fingerprint)


def _launch_plan_slice(
    *,
    runner: "SequentialRunner",
    plan_state: Mapping[str, object],
    request: StructuredLaunchRequest,
) -> LaunchResult:
    budget = plan_state.get("budget")
    if not isinstance(budget, Mapping):
        raise ValueError("plan budget is unavailable")
    timeout = budget.get("controller_slice_timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("controller slice timeout is invalid")
    lock_fd = getattr(runner, "_active_lock_fd", None)
    if not isinstance(lock_fd, int):
        raise RuntimeError("run lock is unavailable for controller launch")
    return runner.launcher._launch_structured(
        replace(request, timeout_seconds=float(timeout)),
        lock_fd,
    )


def _git(repository: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments], check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _ledger_progress(worktree: Path) -> tuple[list[str], str | None]:
    ledger = worktree / ".superpowers" / "sdd" / "progress.md"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            ledger,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return [], None
        remaining = 65_536
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        text = b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return [], None
    finally:
        if descriptor is not None:
            os.close(descriptor)
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

    def reuse_existing() -> Path:
        try:
            existing = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise ValueError("existing recovery capsule is unsafe") from exc
        try:
            metadata = os.fstat(existing)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_size != len(encoded)
            ):
                raise ValueError("existing recovery capsule is unsafe")
            chunks: list[bytes] = []
            remaining = len(encoded) + 1
            while remaining:
                chunk = os.read(existing, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            current = os.fstat(existing)
            visible = os.lstat(path)
            if (
                b"".join(chunks) != encoded
                or not stat.S_ISREG(current.st_mode)
                or stat.S_IMODE(current.st_mode) != 0o600
                or current.st_uid != os.geteuid()
                or current.st_dev != metadata.st_dev
                or current.st_ino != metadata.st_ino
                or current.st_size != metadata.st_size
                or not stat.S_ISREG(visible.st_mode)
                or stat.S_IMODE(visible.st_mode) != 0o600
                or visible.st_uid != os.geteuid()
                or visible.st_dev != metadata.st_dev
                or visible.st_ino != metadata.st_ino
            ):
                raise ValueError("existing recovery capsule does not match")
        except OSError as exc:
            raise ValueError("existing recovery capsule is unsafe") from exc
        finally:
            os.close(existing)
        return path.resolve()

    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        return reuse_existing()

    created = os.fstat(descriptor)

    def remove_created() -> None:
        try:
            visible = os.lstat(path)
            if (
                stat.S_ISREG(visible.st_mode)
                and visible.st_dev == created.st_dev
                and visible.st_ino == created.st_ino
            ):
                os.unlink(path)
        except OSError:
            pass

    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write while persisting recovery capsule")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        remove_created()
        raise

    directory: int | None = None
    try:
        directory = os.open(path.parent, os.O_RDONLY)
        os.fsync(directory)
        os.close(directory)
    except BaseException:
        if directory is not None:
            try:
                os.close(directory)
            except OSError:
                pass
        remove_created()
        raise
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
    if not isinstance(receipt, dict) or set(receipt) != WORKFLOW_RECEIPT_FIELDS:
        return "invalid_workflow_receipt"
    if receipt.get("final_review_head") != _git(worktree, "rev-parse", "HEAD"):
        return "invalid_workflow_receipt"
    if receipt.get("open_finding_ids") != [] or receipt.get("open_obligation_ids") != []:
        return "invalid_workflow_receipt"
    for name in ("ledger_path", "final_review_path"):
        if not _safe_worktree_artifact(worktree, receipt.get(name)):
            return "unsafe_workflow_artifact"
    return None


class SequentialRunner:
    def __init__(
        self,
        *,
        codex_home: Path | None = None,
        launcher: CodexLauncher | None = None,
        compiler: CompiledIndexService | None = None,
    ) -> None:
        self.codex_home = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))).expanduser().resolve()
        schema = Path(__file__).resolve().parents[2] / "templates" / "plan-result-schema.json"
        self.launcher = launcher or CodexLauncher(schema_path=schema)
        self.compiler = compiler or CompiledIndexService(
            compile_once=self.launcher.compile_index
        )

    @staticmethod
    def _branch_handoff_payload(store: StateStore) -> dict[str, object]:
        """Project accepted run facts without claiming external integration."""
        state = store.state
        worktree = Path(state["worktree"])
        try:
            candidate_head = _git(worktree, "rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError):
            candidate_head = ""
        observed_head = candidate_head if _SHA.fullmatch(candidate_head) else None

        plan_results: list[dict[str, object]] = []
        open_finding_ids: set[str] = set()
        open_obligation_ids: set[str] = set()
        run_root = store.root.resolve(strict=True)
        for plan in state["plans"]:
            result_path = Path(str(plan["result_path"]))
            digest = result_artifact_digest(store.root, result_path)
            if digest is None:
                raise ValueError("accepted plan result is unavailable")
            payload = strict_json_object(read_private_result(
                run_root=store.root,
                result_path=result_path,
                expected_digest=digest,
            ))
            if payload is None:
                raise ValueError("accepted plan result is invalid")
            normalized, error = normalize_result_v2(payload)
            if error is not None or normalized is None:
                raise ValueError("accepted plan result is invalid")
            receipt = normalized.get("workflow_receipt")
            verification = normalized.get("verification")
            if normalized.get("status") != "completed" or not isinstance(receipt, dict):
                raise ValueError("accepted plan result is incomplete")
            if not isinstance(verification, list):
                raise ValueError("accepted plan verification is invalid")

            findings = receipt.get("open_finding_ids")
            obligations = receipt.get("open_obligation_ids")
            if not isinstance(findings, list) or not isinstance(obligations, list):
                raise ValueError("accepted workflow receipt is invalid")
            open_finding_ids.update(str(identifier) for identifier in findings)
            open_obligation_ids.update(str(identifier) for identifier in obligations)
            receipt_refs = sorted({
                str(item["receipt_path"])
                for item in verification
                if isinstance(item, dict) and isinstance(item.get("receipt_path"), str)
            })
            try:
                result_ref = result_path.resolve(strict=True).relative_to(
                    run_root
                ).as_posix()
            except (OSError, ValueError) as exc:
                raise ValueError("accepted plan result is outside the run root") from exc
            plan_id = str(plan["plan_id"])
            plan_results.append({
                "plan_id": plan_id,
                "result_ref": result_ref,
                "accepted_commit": plan["accepted_commit"],
                "final_review_ref": receipt["final_review_path"],
                "final_review_head": receipt["final_review_head"],
                "acceptance_evidence_ref": (
                    f"evidence/{plan_id}/evidence-manifest.json"
                ),
                "verification_receipt_refs": receipt_refs,
                "open_finding_ids": list(findings),
                "open_obligation_ids": list(obligations),
            })

        return {
            "format_version": 2,
            "run_id": state["run_id"],
            "branch": state["branch"],
            "saved_worktree": state["worktree"],
            "observed_head": observed_head,
            "last_known_head": state["plans"][-1]["last_known_head"],
            "base_commit": state["source_commit"],
            "plan_results": plan_results,
            "open_finding_ids": sorted(open_finding_ids),
            "open_obligation_ids": sorted(open_obligation_ids),
            "integration": {"status": "not_observed", "receipt": None},
        }

    @staticmethod
    def _materialize_branch_handoff(store: StateStore) -> Path:
        target = store.root / "results" / "branch-handoff.json"
        payload = SequentialRunner._branch_handoff_payload(store)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            visible = os.lstat(target)
        except FileNotFoundError:
            atomic_private_write(target, encoded, mode=0o400)
            return target.resolve(strict=True)
        except OSError as exc:
            raise ValueError("existing branch handoff is unsafe") from exc

        descriptor: int | None = None
        try:
            descriptor = os.open(
                target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = len(encoded) + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if (
                not stat.S_ISREG(visible.st_mode)
                or not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(visible.st_mode) != 0o400
                or stat.S_IMODE(opened.st_mode) != 0o400
                or visible.st_uid != os.geteuid()
                or opened.st_uid != os.geteuid()
                or visible.st_dev != opened.st_dev
                or visible.st_ino != opened.st_ino
                or opened.st_size != len(encoded)
                or b"".join(chunks) != encoded
            ):
                raise ValueError("existing branch handoff does not match")
        except OSError as exc:
            raise ValueError("existing branch handoff is unsafe") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return target.resolve(strict=True)

    @staticmethod
    def _is_pre_execution_worktree_blocked(store: StateStore) -> bool:
        return store.state.get("pre_execution_blocker") == PRE_EXECUTION_WORKTREE_BLOCKER

    @staticmethod
    def _clear_pre_execution_worktree_blocker(store: StateStore) -> None:
        if not SequentialRunner._is_pre_execution_worktree_blocked(store):
            raise ValueError("pre-execution worktree blocker is unavailable")
        state = store.state
        plan = state["plans"][state["current_plan_index"]]
        plan["status"] = "pending"
        state["status"] = "ready"
        state["pre_execution_blocker"] = None
        store.save()

    @staticmethod
    def _record_worktree_creation_blocked(
        store: StateStore,
        *,
        detail: str,
    ) -> dict[str, Any]:
        state = store.state
        plan = state["plans"][state["current_plan_index"]]
        plan["status"] = "blocked"
        state["status"] = "blocked"
        state["pre_execution_blocker"] = dict(PRE_EXECUTION_WORKTREE_BLOCKER)
        store.save()
        store.append_event(
            "run.worktree_creation_blocked",
            plan_id=plan["plan_id"],
            reason=PRE_EXECUTION_WORKTREE_BLOCKER["code"],
            detail=detail,
            **PRE_EXECUTION_WORKTREE_BLOCKER,
        )
        return SequentialRunner._summary(store, error=detail)

    def _create_worktree_or_block(
        self,
        store: StateStore,
    ) -> dict[str, Any] | None:
        try:
            self._create_or_reconcile_worktree(store)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            try:
                self._cleanup_created_worktree(store)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            detail = (str(exc).strip() or type(exc).__name__)[:2000]
            return self._record_worktree_creation_blocked(store, detail=detail)
        return None

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
        if store.state["status"] == "failed":
            return self._summary(store, error="compiled_index_preparation_failed")
        try:
            with _RunLock(store.root / "run.lock") as lock_fd:
                blocked = self._create_worktree_or_block(store)
                if blocked is not None:
                    return blocked
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
                resumed_recorded = False
                if self._is_pre_execution_worktree_blocked(store):
                    if retry_failed:
                        raise ValueError("retry-failed requires a failed run")
                    store.append_event("run.resumed", retry_failed=False)
                    resumed_recorded = True
                    self._clear_pre_execution_worktree_blocker(store)
                    blocked = self._create_worktree_or_block(store)
                    if blocked is not None:
                        return blocked
                elif store.state["status"] in {"preparing", "ready"}:
                    self._create_or_reconcile_worktree(store)
                else:
                    self._verify_worktree(store)
                self._apply_pending_decision(store)
                status = store.state["status"]
                if status == "completed":
                    if retry_failed:
                        raise ValueError("retry-failed requires a failed run")
                    report_error = self._finalize_completed_run(store)
                    return self._summary(store, error=report_error)
                if retry_failed != (status == "failed"):
                    if status == "failed":
                        raise ValueError("failed run requires --retry-failed")
                    raise ValueError("retry-failed requires a failed run")
                if store.state["current_plan_index"] < len(store.state["plans"]):
                    plan = store.state["plans"][store.state["current_plan_index"]]
                    if plan["environment_fingerprint"] is not None:
                        compiled = self._compiled_plan(store)
                        observations = _observe_capabilities(
                            Path(store.state["worktree"]), compiled,
                        )
                        preflight = _resume_preflight(store.state, observations)
                        if preflight == "unchanged_environment_blocker":
                            plan["status"] = "blocked"
                            store.state["status"] = "blocked"
                            store.save()
                            store.append_event(
                                "run.resumed", retry_failed=retry_failed,
                            )
                            store.append_event(
                                "resume.stopped_unchanged_blocker",
                                plan_id=plan["plan_id"],
                                reason=preflight,
                                environment_fingerprint=environment_fingerprint(
                                    observations
                                ),
                            )
                            return self._report_and_summary(store)
                        current_environment = environment_fingerprint(observations)
                        if typed_blockers(observations):
                            plan["environment_fingerprint"] = current_environment
                            plan["capability_probe_ids"] = sorted({
                                observation.capability for observation in observations
                            })
                        else:
                            plan["environment_fingerprint"] = None
                            plan["capability_probe_ids"] = []
                        store.save()
                        store.append_event(
                            "resume.environment_changed",
                            plan_id=plan["plan_id"],
                            reason=preflight,
                            environment_fingerprint=current_environment,
                        )
                if not resumed_recorded:
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

    @staticmethod
    def _compiled_plan(store: StateStore) -> dict[str, object]:
        path = Path(store.state["compiled_run_index_path"])
        compiled = json.loads(path.read_text(encoding="utf-8"))
        plans = compiled.get("plans")
        index = store.state["current_plan_index"]
        if not isinstance(plans, list) or not 0 <= index < len(plans):
            raise ValueError("compiled plan is unavailable")
        return {"plans": [plans[index]]}

    @staticmethod
    def _progress_snapshot(
        store: StateStore,
        *,
        plan_index: int,
        head: str,
    ) -> ProgressSnapshot:
        plan = store.state["plans"][plan_index]
        ledger = (
            Path(store.state["worktree"])
            / ".superpowers"
            / "sdd"
            / "execution-ledger.jsonl"
        )
        if not ledger.exists():
            if plan["execution_ledger_event_digests"]:
                raise ProgressLedgerError("execution_ledger_regressed")
            return ProgressSnapshot(head, (), None)
        try:
            events = validate_execution_ledger(
                ledger, expected_plan_id=plan["plan_id"],
            )
            current_digests = [execution_event_digest(event) for event in events]
            previous_digests = plan["execution_ledger_event_digests"]
            if current_digests[:len(previous_digests)] != previous_digests:
                raise ProgressLedgerError("execution_ledger_regressed")
            snapshot = read_progress_snapshot(
                store.root, plan_index=plan_index, head=head,
            )
        except ProgressLedgerError:
            raise
        except (OSError, ValueError) as exc:
            raise ProgressLedgerError("execution_ledger_invalid") from exc
        plan["execution_ledger_event_digests"] = current_digests
        return snapshot

    @staticmethod
    def _ingest_verification_observations(store: StateStore) -> None:
        """Validate helper receipts and record only parent-observed metadata."""
        state = store.state
        plan_index = state["current_plan_index"]
        if not isinstance(plan_index, int) or not 0 <= plan_index < len(state["plans"]):
            raise ValueError("current plan is unavailable for verification ingest")
        plan = state["plans"][plan_index]
        worktree = Path(state["worktree"]).resolve(strict=True)
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        events = validate_execution_ledger(ledger, expected_plan_id=plan["plan_id"])
        prior = [
            strict_json_object(line)
            for line in store.events_path.read_bytes().splitlines()
        ]
        ingested_child_ids = {
            event.get("child_event_id")
            for event in prior
            if isinstance(event, dict)
            and event.get("action") == "verification.evidence_ingested"
        }
        evidence_root = worktree / ".superpowers" / "sdd" / "verification"
        validated_executions: set[tuple[str, str, str, str]] = set()
        uncached_executions: set[tuple[str, str, str]] = set()
        for event in events:
            event_id = str(event["event_id"])
            if event.get("category") != "verification":
                continue
            if event.get("action") == "executed_uncached":
                uncached_identity = (
                    str(event["command_id"]),
                    str(event["argv_digest"]),
                    str(event["evidence_key"]),
                )
                if uncached_identity in uncached_executions:
                    raise ValueError("uncached verification evidence is duplicated")
                uncached_executions.add(uncached_identity)
                if not event_id.startswith("verification.executed_uncached:"):
                    raise ValueError("uncached verification event identity is invalid")
                if event_id not in ingested_child_ids:
                    store.append_event(
                        "verification.evidence_ingested",
                        child_event_id=event_id,
                        plan_id=plan["plan_id"],
                        command_id=event["command_id"],
                        phase=event["phase"],
                        cache_key=event["evidence_key"],
                        receipt_id=None,
                        receipt_path=None,
                        decision="executed_uncached",
                        exit_code=event["exit_code"],
                        reason=event["reason_code"],
                        semantic_source="child_attested",
                    )
                    ingested_child_ids.add(event_id)
                continue
            if (
                event.get("action") != "verified"
                or event.get("result") != "pass"
                or not event_id.startswith(("verification.reused:", "verification.executed:"))
            ):
                continue
            references = event.get("evidence_refs")
            if (
                not isinstance(references, list)
                or len(references) != 3
                or not all(isinstance(reference, str) for reference in references)
                or not references[0].startswith("verification/receipts/")
            ):
                raise ValueError("verification helper receipt reference is invalid")
            relative = Path(references[0])
            receipt_path = worktree / ".superpowers" / "sdd" / relative
            try:
                resolved_receipt = receipt_path.resolve(strict=True)
                resolved_receipt.relative_to(evidence_root.resolve(strict=True))
                metadata = receipt_path.lstat()
            except (OSError, ValueError) as exc:
                raise ValueError("verification helper receipt is unavailable") from exc
            if (
                receipt_path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > 1024 * 1024
            ):
                raise ValueError("verification helper receipt is unsafe")
            document = json.loads(resolved_receipt.read_text(encoding="utf-8"))
            request_document = document.get("request")
            if not isinstance(request_document, dict):
                raise ValueError("verification helper receipt request is invalid")
            try:
                request = VerificationRequest(
                    run_id=request_document["run_id"],
                    command_id=request_document["command_id"],
                    argv=tuple(request_document["argv"]),
                    cwd=Path(request_document["cwd"]),
                    head=request_document["head"],
                    environment_fingerprint=request_document["environment_fingerprint"],
                    phase=request_document["phase"],
                    input_digest=request_document["input_digest"],
                    deterministic=request_document["deterministic"],
                    mutable_input_policy=request_document["mutable_input_policy"],
                    required_artifact_paths=tuple(
                        request_document["required_artifact_paths"]
                    ),
                    timeout_seconds=request_document["timeout_seconds"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("verification helper receipt request is invalid") from exc
            receipt = validate_recorded_receipt_path(
                evidence_root,
                request,
                Path(*relative.parts[1:]).as_posix(),
            )
            argv_digest = hashlib.sha256(
                json.dumps(
                    list(request.argv), separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            if (
                receipt is None
                or resolved_receipt.name != f"{receipt.receipt_id}.json"
                or receipt.receipt_id != document.get("receipt_id")
                or event.get("command_id") != request.command_id
                or event.get("argv_digest") != argv_digest
                or event.get("evidence_key") != receipt.cache_key
                or references[1:] != [
                    f"verification/{receipt.stdout_path}",
                    f"verification/{receipt.stderr_path}",
                ]
            ):
                raise ValueError("verification helper receipt binding is invalid")
            decision = "reused" if event_id.startswith("verification.reused:") else "executed"
            lifecycle = (
                receipt.receipt_id,
                receipt.cache_key,
                request.command_id,
                argv_digest,
            )
            if decision == "reused" and (
                not request.deterministic
                or request.mutable_input_policy == "always_execute"
                or lifecycle not in validated_executions
            ):
                raise ValueError(
                    "reused verification lacks a prior validated executed lifecycle"
                )
            if decision == "executed":
                validated_executions.add(lifecycle)
            if event_id not in ingested_child_ids:
                store.append_event(
                    "verification.evidence_ingested",
                    child_event_id=event_id,
                    plan_id=plan["plan_id"],
                    command_id=request.command_id,
                    phase=request.phase,
                    cache_key=receipt.cache_key,
                    receipt_id=receipt.receipt_id,
                    receipt_path=references[0],
                    decision=decision,
                    semantic_source="child_attested",
                )
                ingested_child_ids.add(event_id)

    def _apply_pending_decision(self, store: StateStore) -> str | None:
        """Idempotently apply one journaled decision and clear it atomically."""
        state = store.state
        index = state["current_plan_index"]
        if not isinstance(index, int) or index >= len(state["plans"]):
            return None
        plan = state["plans"][index]
        pending = plan["pending_checkpoint_decision"]
        if pending is None:
            return None
        decision = CheckpointDecision(
            pending["decision"],
            pending["reason"],
            pending["progress_fingerprint"],
        )
        decision_id = pending["decision_id"]
        _ensure_decision_scoped_event(
            store,
            "plan.checkpoint_decided",
            decision_id,
            plan_id=pending["plan_id"],
            attempt=pending["attempt"],
            decision=pending["decision"],
            reason=pending["reason"],
            progress_fingerprint=pending["progress_fingerprint"],
            timed_out=pending["timed_out"],
        )
        if plan["progress_fingerprint"] != pending["previous_progress_fingerprint"]:
            raise ValueError("checkpoint decision journal baseline changed")

        if decision.action == "finish":
            publication_started = time.monotonic()
            try:
                ingest_plan_evidence(
                    run_root=store.root,
                    worktree=Path(state["worktree"]),
                    plan_id=plan["plan_id"],
                    accepted_head=pending["head"],
                    expected_manifest_sha256=pending["evidence_manifest_sha256"],
                )
                self._ingest_verification_observations(store)
                repaired_digest = self._repaired_result_digest(store, plan)
                self._seal_result(
                    Path(plan["result_path"]),
                    run_root=store.root,
                    expected_digest=repaired_digest,
                )
            except (OSError, ValueError) as exc:
                reason = (str(exc).strip() or type(exc).__name__)[:2000]
                _ensure_decision_scoped_event(
                    store,
                    "plan.evidence_failed",
                    decision_id,
                    plan_id=plan["plan_id"],
                    reason=reason,
                )
                plan["status"] = "failed"
                state["status"] = "failed"
                plan["pending_checkpoint_decision"] = None
                store.save()
                return "evidence_failed"
            plan["plan_elapsed_seconds"] += math.ceil(
                time.monotonic() - publication_started
            )
            _ensure_decision_scoped_event(
                store,
                "plan.completed",
                decision_id,
                plan_id=plan["plan_id"],
                head=pending["head"],
            )

        block_details: tuple[bool, str | None, list[str]] | None = None
        if decision.action == "block":
            existing = _decision_scoped_events(
                store, "plan.blocked", decision_id,
            )
            if len(existing) > 1:
                raise ValueError("plan.blocked event is duplicated")
            if existing:
                event = existing[0]
                parent_confirmed = event.get("parent_confirmed")
                fingerprint = event.get("environment_fingerprint")
                probe_ids = event.get("capability_probe_ids")
                if (
                    event.get("plan_id") != plan["plan_id"]
                    or not isinstance(parent_confirmed, bool)
                    or (
                        parent_confirmed
                        and (not isinstance(fingerprint, str) or len(fingerprint) != 64)
                    )
                    or (not parent_confirmed and fingerprint is not None)
                    or not isinstance(probe_ids, list)
                    or not all(isinstance(value, str) for value in probe_ids)
                    or len(probe_ids) != len(set(probe_ids))
                ):
                    raise ValueError(
                        "plan.blocked event does not match decision journal"
                    )
                block_details = (
                    parent_confirmed, fingerprint, list(probe_ids),
                )
            else:
                probe_started = time.monotonic()
                observations = _observe_capabilities(
                    Path(state["worktree"]), self._compiled_plan(store),
                )
                blockers = typed_blockers(observations)
                fingerprint = (
                    environment_fingerprint(observations) if blockers else None
                )
                probe_ids = (
                    sorted({observation.capability for observation in observations})
                    if blockers else []
                )
                plan["plan_elapsed_seconds"] += math.ceil(
                    time.monotonic() - probe_started
                )
                block_details = (bool(blockers), fingerprint, probe_ids)
                _ensure_decision_scoped_event(
                    store,
                    "plan.blocked",
                    decision_id,
                    plan_id=plan["plan_id"],
                    parent_confirmed=bool(blockers),
                    environment_fingerprint=fingerprint,
                    capability_probe_ids=probe_ids,
                )

        _record_checkpoint(state, decision)
        plan["last_known_head"] = pending["head"]

        if decision.action == "finish":
            plan["status"] = "completed"
            plan["accepted_commit"] = pending["head"]
            state["current_plan_index"] += 1
            state["status"] = (
                "completed"
                if state["current_plan_index"] == len(state["plans"])
                else "running"
            )
        elif decision.action == "continue":
            _ensure_decision_scoped_event(
                store,
                "plan.continuation_scheduled",
                decision_id,
                plan_id=plan["plan_id"],
                reason=decision.reason_code,
                head=pending["head"],
            )
            plan["status"] = "checkpointed"
            state["status"] = "checkpointed"
        elif decision.action == "checkpoint":
            _ensure_decision_scoped_event(
                store,
                "plan.checkpointed",
                decision_id,
                plan_id=plan["plan_id"],
                head=pending["head"],
            )
            plan["status"] = "checkpointed"
            state["status"] = "checkpointed"
        elif decision.action == "fail":
            _ensure_decision_scoped_event(
                store,
                "plan.failed",
                decision_id,
                plan_id=plan["plan_id"],
                attempts=plan["attempt_count"],
            )
            plan["status"] = "failed"
            state["status"] = "failed"
        elif decision.action == "block":
            assert block_details is not None
            _, fingerprint, probe_ids = block_details
            plan["environment_fingerprint"] = fingerprint
            plan["capability_probe_ids"] = probe_ids
            _ensure_decision_scoped_event(
                store,
                "plan.recovery_stopped",
                decision_id,
                plan_id=plan["plan_id"],
                reason=decision.reason_code,
                failure_signature=decision.progress_fingerprint,
            )
            plan["status"] = "blocked"
            state["status"] = "blocked"
        else:
            plan["result_path"] = str(self._controller_stop_result(
                store, plan, decision, pending["head"],
            ))
            _ensure_decision_scoped_event(
                store,
                "plan.recovery_stopped",
                decision_id,
                plan_id=plan["plan_id"],
                reason=decision.reason_code,
                failure_signature=decision.progress_fingerprint,
            )
            plan["status"] = "blocked"
            state["status"] = "blocked"

        plan["pending_checkpoint_decision"] = None
        if decision.action == "finish" and state["status"] == "completed":
            self._materialize_branch_handoff(store)
        store.save()
        return decision.action

    @staticmethod
    def _checkpoint_budget(plan: Mapping[str, object]) -> CheckpointBudget:
        budget = plan["budget"]
        assert isinstance(budget, Mapping)
        return CheckpointBudget(
            max_progress_checkpoints=int(budget["max_progress_checkpoints"]),
            max_controller_launches=int(budget["max_controller_launches"]),
            plan_wall_seconds=int(budget["plan_wall_budget_seconds"]),
        )

    @staticmethod
    def _controller_stop_result(
        store: StateStore,
        plan: dict[str, Any],
        decision: CheckpointDecision,
        head: str,
    ) -> Path:
        target = (
            store.root
            / "results"
            / f"{plan['plan_id']}-controller-stop-{plan['checkpoint_count']}.json"
        )
        payload = {
            "plan_id": plan["plan_id"],
            "status": "blocked",
            "head_commit": head,
            "verification": [],
            "summary": f"controller stopped recovery: {decision.reason_code}",
            "blocker": {
                "kind": "operator_owned",
                "code": decision.reason_code,
                "resource": plan["plan_id"],
                "operation": "continue_controller",
                "errno": None,
                "retry_condition": "durable progress or operator budget changes",
                "fingerprint": decision.progress_fingerprint,
            },
        }
        _write_private_json(target, payload)
        return target.resolve()

    def inspect(self, *, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        return self._summary(store)

    @staticmethod
    def _verification_helper_descriptor_for_launch(
        store: StateStore,
    ) -> Path | None:
        try:
            return materialize_helper_descriptor(
                store.root,
                Path(__file__).resolve().parent.parent / "cpe.py",
            )
        except (OSError, ValueError) as exc:
            store.append_event(
                "verification.helper_fallback",
                reason="verification_helper_fallback",
                detail=(str(exc).strip() or type(exc).__name__)[:2000],
            )
            return None

    def verify(
        self,
        *,
        run_id: str,
        command_id: str,
        phase: str,
        input_digest: str,
        mutable_input_policy: str,
        cwd: Path,
        argv: Sequence[str],
    ) -> dict[str, object]:
        """Execute one source-declared verification or reuse its exact receipt."""
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run ID contains unsupported characters")
        if phase not in _VERIFY_PHASES or mutable_input_policy not in {
            "immutable", "digest_complete", "always_execute",
        }:
            raise ValueError("verification request enum is invalid")
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("verification command argv must not be empty")

        store = StateStore.open(self.codex_home / "orchestrator" / run_id)
        state = store.state
        if state["status"] not in {"ready", "running"}:
            raise ValueError("verification requires an active run")
        self._verify_worktree(store)
        worktree = Path(state["worktree"]).resolve(strict=True)
        declared_cwd = cwd.absolute()
        resolved_cwd = declared_cwd.resolve(strict=True)
        try:
            relative_cwd = resolved_cwd.relative_to(worktree)
        except ValueError as exc:
            raise ValueError("verification cwd is outside the saved worktree") from exc
        current = worktree
        for component in relative_cwd.parts:
            current /= component
            if current.is_symlink():
                raise ValueError("verification cwd contains a symlink")
        descriptor = store.root / "tools" / "run-and-record.json"
        if not descriptor.exists() or descriptor.is_symlink():
            raise ValueError("verification helper descriptor is unavailable")
        cpe_script = Path(__file__).resolve().parent.parent / "cpe.py"
        materialize_helper_descriptor(store.root, cpe_script)

        contract_path = Path(state["operator_contract_path"])
        compiled_path = Path(state["compiled_run_index_path"])
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if contract != default_operator_contract(state):
            raise ValueError("operator contract no longer matches run state")
        compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
        validate_compiled_index(compiled, state, contract)
        plan_index = state["current_plan_index"]
        plans = compiled["plans"]
        if not isinstance(plan_index, int) or not 0 <= plan_index < len(plans):
            raise ValueError("current compiled plan is unavailable")
        compiled_plan = plans[plan_index]
        candidates = [
            item
            for item in compiled_plan["verifications"]
            if item["command_id"] == command_id
            and item["argv"] == list(argv)
            and bool(set(item["allowed_branch_phases"]) & _VERIFY_PHASES[phase])
            and mutable_input_policy
            in _VERIFY_POLICIES[item["mutable_input_policy"]]
        ]
        if len(candidates) != 1:
            argv_digest = hashlib.sha256(
                json.dumps(list(argv), separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            evidence_key = hashlib.sha256(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "command_id": command_id,
                        "argv_digest": argv_digest,
                        "cwd": str(resolved_cwd),
                        "head": _current_head(worktree),
                        "phase": phase,
                        "input_digest": input_digest,
                        "mutable_input_policy": mutable_input_policy,
                        "reuse_policy": "never",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "schema_version": 1,
                "status": "uncached_command_required",
                "reason": "command_not_exactly_source_declared",
                "reason_code": "uncached_command_required",
                "reused": False,
                "receipt_path": None,
                "command_id": command_id,
                "argv_digest": argv_digest,
                "evidence_key": evidence_key,
                "phase": phase,
            }
        declaration = candidates[0]

        observations = _observe_capabilities(
            worktree, {"plans": [compiled_plan]},
        )
        current_environment = environment_fingerprint(observations)
        saved_environment = state["plans"][plan_index]["environment_fingerprint"]
        if saved_environment is not None and saved_environment != current_environment:
            raise ValueError("verification environment no longer matches saved evidence")
        head = _current_head(worktree)
        request = VerificationRequest(
            run_id=run_id,
            command_id=command_id,
            argv=tuple(argv),
            cwd=resolved_cwd,
            head=head,
            environment_fingerprint=current_environment,
            phase=phase,  # type: ignore[arg-type]
            input_digest=input_digest,
            deterministic=declaration["deterministic"],
            mutable_input_policy=mutable_input_policy,  # type: ignore[arg-type]
            required_artifact_paths=tuple(declaration["required_artifacts"]),
            timeout_seconds=3600,
        )
        dirty_source_inputs = bool(
            _git(
                worktree,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude).superpowers",
                ":(exclude).superpowers/**",
            )
        )
        if dirty_source_inputs:
            request = replace(request, deterministic=False)
        evidence_root = worktree / ".superpowers" / "sdd" / "verification"
        corruption_log = evidence_root / "corruption-events.jsonl"
        corruption_bytes = corruption_log.stat().st_size if corruption_log.exists() else 0
        receipt = (
            None
            if dirty_source_inputs
            else find_reusable_receipt(evidence_root, request)
        )
        fallback = (
            not dirty_source_inputs
            and receipt is None
            and corruption_log.exists()
            and corruption_log.stat().st_size > corruption_bytes
        )
        reused = receipt is not None
        if receipt is None:
            if fallback:
                cache_key = verification_cache_key(request)
                index = evidence_root / "indexes" / f"{cache_key}.json"
                if index.exists():
                    quarantine = evidence_root / "quarantine"
                    quarantine.mkdir(mode=0o700, exist_ok=True)
                    os.replace(
                        index,
                        quarantine / f"{cache_key}-{uuid.uuid4().hex}.json",
                    )
            receipt = execute_verification(
                evidence_root,
                replace(request, deterministic=False) if fallback else request,
            )

        receipt_relative = (
            Path(".superpowers")
            / "sdd"
            / "verification"
            / "receipts"
            / f"{receipt.receipt_id}.json"
        )
        receipt_document = json.loads(
            (worktree / receipt_relative).read_text(encoding="utf-8")
        )
        argv_digest = hashlib.sha256(
            json.dumps(list(argv), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if fallback:
            uncached_exit_code = receipt.exit_code
            if uncached_exit_code is None:
                uncached_exit_code = 124 if receipt.status == "timed_out" else 130
            append_execution_event(
                worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl",
                {
                    "event_id": f"verification.executed_uncached:{uuid.uuid4().hex}",
                    "source": "child_attested",
                    "plan_id": state["plans"][plan_index]["plan_id"],
                    "category": "verification",
                    "action": "executed_uncached",
                    "result": "pass" if receipt.status == "passed" else "fail",
                    "evidence_refs": [],
                    "command_id": command_id,
                    "argv_digest": argv_digest,
                    "evidence_key": receipt.cache_key,
                    "duration_ms": int(receipt_document.get("duration_ms", 0)),
                    "exit_code": uncached_exit_code,
                    "receipt_path": None,
                    "reason_code": "verification_helper_fallback",
                    "phase": phase,
                },
            )
            return {
                "schema_version": 1,
                "reused": False,
                "receipt_path": None,
                "status": receipt.status,
                "cache_key": receipt.cache_key,
                "command_id": command_id,
                "argv_digest": argv_digest,
                "evidence_key": receipt.cache_key,
                "phase": phase,
                "reason": "verification_helper_fallback",
                "reason_code": "verification_helper_fallback",
            }
        decision = "reused" if reused else "executed"
        receipt_reference = receipt_relative.relative_to(
            Path(".superpowers") / "sdd"
        ).as_posix()
        append_execution_event(
            worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            {
                "event_id": f"verification.{decision}:{uuid.uuid4().hex}",
                "source": "child_attested",
                "plan_id": state["plans"][plan_index]["plan_id"],
                "category": "verification",
                "action": "verified",
                "result": "pass" if receipt.status == "passed" else "fail",
                "evidence_refs": [
                    receipt_reference,
                    f"verification/{receipt.stdout_path}",
                    f"verification/{receipt.stderr_path}",
                ],
                "command_id": command_id,
                "argv_digest": argv_digest,
                "evidence_key": receipt.cache_key,
                "duration_ms": int(receipt_document.get("duration_ms", 0)),
            },
        )
        response: dict[str, object] = {
            "schema_version": 1,
            "reused": reused,
            "receipt_path": receipt_relative.as_posix(),
            "receipt_id": receipt.receipt_id,
            "status": receipt.status,
            "cache_key": receipt.cache_key,
        }
        if dirty_source_inputs:
            response["reason"] = "dirty_worktree_requires_execution"
        return response

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
        store = StateStore.create(
            run_root=run_root,
            run_id=run_id,
            source_repository=repository,
            source_commit=source_commit,
            worktree=worktree,
            branch=branch,
            specs=specs,
            plans=plans,
            initial_status="preparing",
        )
        try:
            self.compiler.prepare(store)
            store.state["status"] = "ready"
            store.save()
            store.append_event("run.prepared")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            store.state["status"] = "failed"
            store.save()
            store.append_event(
                "run.preparation_failed",
                reason=(str(exc).strip() or type(exc).__name__)[:2000],
            )
        return store

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
        if prior_status not in {"checkpointed", "blocked", "failed"}:
            prior_status = (
                plan["status"]
                if plan["status"] in {"checkpointed", "blocked", "failed"}
                else "checkpointed"
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

    @staticmethod
    def _repaired_result_digest(
        store: StateStore,
        plan: Mapping[str, object],
    ) -> str | None:
        if not isinstance(plan.get("original_result_path"), str):
            return None
        matches = [
            event for event in (
                strict_json_object(line)
                for line in store.events_path.read_bytes().splitlines()
            )
            if isinstance(event, dict)
            and event.get("action") == "result.envelope_repaired"
            and event.get("plan_id") == plan.get("plan_id")
        ]
        if len(matches) != 1:
            raise ValueError("result envelope repair event is missing or duplicated")
        event = matches[0]
        digest = event.get("repaired_digest")
        if (
            event.get("source") != "parent_observed"
            or event.get("run_id") != store.state["run_id"]
            or event.get("category") != "result"
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("result envelope repair digest is invalid")
        return digest

    @staticmethod
    def _recorded_envelope_repair(
        store: StateStore,
        plan: Mapping[str, object],
        repair: EnvelopeRepair,
    ) -> EnvelopeRepair | None:
        original_raw = plan.get("original_result_path")
        repaired_raw = plan.get("result_path")
        if not isinstance(original_raw, str) or not isinstance(repaired_raw, str):
            return None
        matches = [
            event for event in (
                json.loads(line)
                for line in store.events_path.read_text(encoding="utf-8").splitlines()
            )
            if isinstance(event, dict)
            and event.get("action") == "result.envelope_repaired"
            and event.get("plan_id") == plan.get("plan_id")
        ]
        if len(matches) != 1:
            raise ValueError("result envelope repair event is missing or duplicated")
        event = matches[0]
        original = Path(original_raw)
        repaired = Path(repaired_raw)
        changed = event.get("changed_fields")
        allowed_changes = {
            ("/workflow_receipt/ledger_path",),
            ("/workflow_receipt/final_review_path",),
            (
                "/workflow_receipt/ledger_path",
                "/workflow_receipt/final_review_path",
            ),
        }
        if (
            event.get("source") != "parent_observed"
            or event.get("run_id") != store.state["run_id"]
            or event.get("category") != "result"
            or not isinstance(changed, list)
            or not all(isinstance(field, str) for field in changed)
            or tuple(changed) not in allowed_changes
            or original != repair.original_path
            or repaired != repair.repaired_path
            or event.get("original_digest") != repair.original_digest
            or event.get("repaired_digest") != repair.repaired_digest
            or tuple(changed) != repair.changed_fields
        ):
            raise ValueError("result envelope repair event does not match artifacts")
        return repair

    def _resume_envelope_repair(
        self,
        store: StateStore,
        plan: dict[str, Any],
        *,
        plan_index: int,
    ) -> tuple[str | None, str | None]:
        state = store.state
        repair: EnvelopeRepair | None = None
        original_raw = plan.get("original_result_path")
        if isinstance(original_raw, str):
            expected_repaired_digest = self._repaired_result_digest(store, plan)
            assert expected_repaired_digest is not None
            read_private_result(
                run_root=store.root,
                result_path=Path(str(plan["result_path"])),
                expected_digest=expected_repaired_digest,
            )
            repair = repair_result_envelope(
                run_root=store.root,
                worktree=Path(state["worktree"]),
                original_result_path=Path(original_raw),
            )
            if repair is None:
                raise ValueError(
                    "recorded result envelope repair no longer validates"
                )
            self._recorded_envelope_repair(store, plan, repair)
        else:
            result_raw = plan.get("result_path")
            if not isinstance(result_raw, str):
                return None, None
            candidate = has_current_unsafe_envelope_failure(
                run_root=store.root,
                original_result_path=Path(result_raw),
            )
            repair = repair_result_envelope(
                run_root=store.root,
                worktree=Path(state["worktree"]),
                original_result_path=Path(result_raw),
            )
            if repair is None:
                if candidate:
                    return "failed", "unsafe_workflow_artifact"
                return None, None
            matches = [
                event for event in (
                    json.loads(line)
                    for line in store.events_path.read_text(encoding="utf-8").splitlines()
                )
                if isinstance(event, dict)
                and event.get("action") == "result.envelope_repaired"
                and event.get("plan_id") == plan["plan_id"]
            ]
            expected = {
                "original_digest": repair.original_digest,
                "repaired_digest": repair.repaired_digest,
                "changed_fields": list(repair.changed_fields),
            }
            if len(matches) > 1:
                raise ValueError("result envelope repair event is duplicated")
            if matches:
                if any(matches[0].get(name) != value for name, value in expected.items()):
                    raise ValueError("result envelope repair event does not match artifacts")
            else:
                store.append_event(
                    "result.envelope_repaired",
                    plan_id=plan["plan_id"],
                    **expected,
                )
            plan["original_result_path"] = str(repair.original_path)
            plan["result_path"] = str(repair.repaired_path)
            plan["status"] = "running"
            state["status"] = "running"
            store.save()

        try:
            repaired_bytes = read_private_result(
                run_root=store.root,
                result_path=repair.repaired_path,
                expected_digest=repair.repaired_digest,
            )
        except ValueError:
            plan["status"] = "failed"
            state["status"] = "failed"
            store.save()
            store.append_event(
                "plan.integrity_failed",
                plan_id=plan["plan_id"],
                reason="repaired_result_changed",
            )
            return "failed", "repaired_result_changed"
        payload = strict_json_object(repaired_bytes)
        if payload is None:
            raise ValueError("repaired result is invalid")
        outcome = LaunchResult(
            payload=payload,
            returncode=0,
            timed_out=False,
            forced_cleanup=False,
            discarded_log_bytes=0,
            result_path=repair.repaired_path,
            log_path=store.root / "logs" / f"{plan['plan_id']}-attempt-{plan['attempt_count']}.log",
            duration_ms=0,
            input_tokens=None,
            cached_input_tokens=None,
            output_tokens=None,
            reasoning_output_tokens=None,
            launcher_prompt_bytes=0,
        )
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
            return "failed", integrity_error
        observed_head = _current_head(Path(state["worktree"]))
        try:
            current_snapshot = self._progress_snapshot(
                store, plan_index=plan_index, head=observed_head,
            )
            _, evidence_manifest_sha256 = prepare_plan_evidence(
                worktree=Path(state["worktree"]),
                plan_id=plan["plan_id"],
                accepted_head=str(payload["head_commit"]),
            )
        except ProgressLedgerError as exc:
            plan["status"] = "failed"
            state["status"] = "failed"
            store.save()
            store.append_event(
                "plan.integrity_failed", plan_id=plan["plan_id"], reason=exc.code,
            )
            return "failed", exc.code
        except (OSError, ValueError) as exc:
            reason = (str(exc).strip() or type(exc).__name__)[:2000]
            plan["status"] = "failed"
            state["status"] = "failed"
            store.save()
            store.append_event(
                "plan.evidence_failed", plan_id=plan["plan_id"], reason=reason,
            )
            return "evidence_failed", reason
        decision = decide_child_outcome(
            previous=ProgressSnapshot(observed_head, (), None),
            current=current_snapshot,
            timed_out=False,
            consecutive_no_progress=plan["consecutive_no_progress_slices"],
            progress_checkpoints=plan["progress_checkpoint_count"],
            controller_launches=plan["controller_launch_count"],
            plan_elapsed_seconds=plan["plan_elapsed_seconds"],
            budget=self._checkpoint_budget(plan),
            child_status="completed",
        )
        _persist_checkpoint_decision(
            store,
            decision,
            timed_out=False,
            head=observed_head,
            evidence_manifest_sha256=evidence_manifest_sha256,
        )
        action = self._apply_pending_decision(store)
        return action, (
            "evidence_publication_failed" if action == "evidence_failed" else None
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
            if explicit_retry or plan["original_result_path"] is not None:
                repaired_action, repair_error = self._resume_envelope_repair(
                    store, plan, plan_index=index,
                )
                if repair_error is not None:
                    return self._report_and_summary(store, error=repair_error)
                if repaired_action == "finish":
                    explicit_retry = False
                    continue
                if repaired_action is not None:
                    raise ValueError("result envelope repair did not finish")
            explicit_retry = False
            while True:
                worktree = Path(state["worktree"])
                current_head = _current_head(worktree)
                pre_spawn_stop = _pre_spawn_budget_decision(
                    plan, head=current_head,
                )
                if pre_spawn_stop is not None:
                    plan["result_path"] = str(self._controller_stop_result(
                        store, plan, pre_spawn_stop, current_head,
                    ))
                    plan["status"] = "blocked"
                    plan["last_known_head"] = current_head
                    state["status"] = "blocked"
                    store.save()
                    store.append_event(
                        "plan.pre_spawn_stopped",
                        plan_id=plan["plan_id"],
                        reason=pre_spawn_stop.reason_code,
                        decision=pre_spawn_stop.action,
                        progress_fingerprint=pre_spawn_stop.progress_fingerprint,
                    )
                    store.append_event(
                        "plan.recovery_stopped",
                        plan_id=plan["plan_id"],
                        reason=pre_spawn_stop.reason_code,
                        failure_signature=pre_spawn_stop.progress_fingerprint,
                    )
                    return self._report_and_summary(store)
                if plan["starting_commit"] is None:
                    plan["starting_commit"] = current_head
                previous_snapshot = (
                    self._progress_snapshot(
                        store, plan_index=index, head=current_head,
                    )
                    if plan["progress_fingerprint"] is not None
                    else ProgressSnapshot(current_head, (), None)
                )
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
                if plan["plan_started_at"] is None:
                    plan["plan_started_at"] = datetime.now(timezone.utc).isoformat()
                if plan["progress_fingerprint"] is None:
                    plan["progress_fingerprint"] = progress_fingerprint(
                        previous_snapshot
                    )
                plan["controller_launch_count"] += 1
                plan["last_known_head"] = current_head
                state["status"] = "running"
                store.save()
                store.append_event(
                    "plan.attempt_started",
                    plan_id=plan["plan_id"],
                    attempt=plan["attempt_count"],
                    controller_launch_count=plan["controller_launch_count"],
                    head=current_head,
                    timeout_seconds=plan["budget"]["controller_slice_timeout_seconds"],
                )
                plan_input = next(record for record in state["inputs"] if record["document_id"] == plan["plan_id"])
                spec_paths = [Path(record["snapshot_path"]) for record in state["inputs"] if record["role"] == "spec"]
                verification_helper_descriptor = (
                    self._verification_helper_descriptor_for_launch(store)
                )
                request = StructuredLaunchRequest(
                    command=self.launcher._command(worktree, result_path),
                    cwd=worktree,
                    prompt=self.launcher._prompt(
                        worktree=worktree,
                        plan_id=plan["plan_id"],
                        plan_path=Path(plan_input["snapshot_path"]),
                        spec_paths=spec_paths,
                        starting_commit=plan["starting_commit"],
                        current_commit=current_head,
                        recovery_path=recovery_path,
                        compiled_run_index=Path(state["compiled_run_index_path"]),
                        execution_ledger=(
                            worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
                        ),
                        verification_helper_descriptor=verification_helper_descriptor,
                    ),
                    result_path=result_path,
                    log_path=log_path,
                    timeout_seconds=self.launcher.timeout_seconds,
                )
                self._active_lock_fd = lock_fd
                try:
                    outcome = _launch_plan_slice(
                        runner=self,
                        plan_state=plan,
                        request=request,
                    )
                finally:
                    del self._active_lock_fd
                parent_active_started = time.monotonic()
                store.append_event(
                    "plan.attempt_finished",
                    plan_id=plan["plan_id"],
                    attempt=plan["attempt_count"],
                    returncode=outcome.returncode,
                    timed_out=outcome.timed_out,
                    forced_cleanup=outcome.forced_cleanup,
                    discarded_log_bytes=outcome.discarded_log_bytes,
                    duration_ms=outcome.duration_ms,
                    input_tokens=outcome.input_tokens,
                    cached_input_tokens=outcome.cached_input_tokens,
                    output_tokens=outcome.output_tokens,
                    reasoning_output_tokens=outcome.reasoning_output_tokens,
                    launcher_prompt_bytes=outcome.launcher_prompt_bytes,
                )
                plan["result_path"] = (
                    str(outcome.result_path.resolve())
                    if outcome.payload is not None
                    else str(self._synthetic_result(store, plan, outcome))
                )
                observed_head = _current_head(worktree)
                plan["plan_elapsed_seconds"] += math.ceil(
                    outcome.duration_ms / 1000
                )
                plan["plan_elapsed_seconds"] += math.ceil(
                    time.monotonic() - parent_active_started
                )
                plan["last_known_head"] = observed_head

                integrity_error = None
                if not (outcome.timed_out and outcome.payload is None):
                    integrity_error = self._handoff_error(store, plan, outcome)
                if integrity_error is not None:
                    plan["status"] = "failed"
                    state["status"] = "failed"
                    store.save()
                    failure_fields: dict[str, object] = {}
                    if integrity_error == "unsafe_workflow_artifact":
                        result_path = Path(str(plan["result_path"]))
                        digest = result_artifact_digest(store.root, result_path)
                        if digest is not None:
                            failure_fields = {
                                "attempt": plan["attempt_count"],
                                "original_result_path": str(result_path.resolve()),
                                "original_result_sha256": digest,
                            }
                    store.append_event(
                        "plan.integrity_failed",
                        plan_id=plan["plan_id"],
                        reason=integrity_error,
                        **failure_fields,
                    )
                    return self._report_and_summary(
                        store, error=integrity_error,
                    )

                payload = outcome.payload
                payload_status = (
                    payload.get("status") if isinstance(payload, dict) else None
                )
                try:
                    current_snapshot = self._progress_snapshot(
                        store, plan_index=index, head=observed_head,
                    )
                except ProgressLedgerError as exc:
                    plan["status"] = "failed"
                    state["status"] = "failed"
                    store.save()
                    store.append_event(
                        "plan.integrity_failed",
                        plan_id=plan["plan_id"],
                        reason=exc.code,
                    )
                    return self._report_and_summary(store, error=exc.code)

                evidence_manifest_sha256 = None
                if payload_status == "completed":
                    try:
                        _, evidence_manifest_sha256 = prepare_plan_evidence(
                            worktree=worktree,
                            plan_id=plan["plan_id"],
                            accepted_head=payload["head_commit"],
                        )
                    except (OSError, ValueError) as exc:
                        reason = (str(exc).strip() or type(exc).__name__)[:2000]
                        plan["status"] = "failed"
                        state["status"] = "failed"
                        store.save()
                        store.append_event(
                            "plan.evidence_failed",
                            plan_id=plan["plan_id"],
                            reason=reason,
                        )
                        return self._report_and_summary(store, error=reason)
                decision = decide_child_outcome(
                    previous=previous_snapshot,
                    current=current_snapshot,
                    timed_out=outcome.timed_out,
                    consecutive_no_progress=plan["consecutive_no_progress_slices"],
                    progress_checkpoints=plan["progress_checkpoint_count"],
                    controller_launches=plan["controller_launch_count"],
                    plan_elapsed_seconds=plan["plan_elapsed_seconds"],
                    budget=self._checkpoint_budget(plan),
                    child_status=payload_status,
                )
                _persist_checkpoint_decision(
                    store,
                    decision,
                    timed_out=outcome.timed_out,
                    head=observed_head,
                    evidence_manifest_sha256=evidence_manifest_sha256,
                )
                applied_action = self._apply_pending_decision(store)

                if applied_action == "finish":
                    break
                if applied_action == "continue":
                    continue
                if applied_action == "evidence_failed":
                    return self._report_and_summary(
                        store, error="evidence_publication_failed",
                    )
                return self._report_and_summary(store)

        if state["status"] != "completed":
            state["status"] = "completed"
            store.save()
        report_error = self._finalize_completed_run(store)
        if report_error is not None:
            return self._summary(store, error=report_error)
        return self._summary(store)

    def _finalize_completed_run(self, store: StateStore) -> str | None:
        """Materialize one durable completion event and both derived reports."""
        state = store.state
        plans = state["plans"]
        if (
            state["status"] != "completed"
            or state["current_plan_index"] != len(plans)
            or not plans
        ):
            raise ValueError("run completion state is invalid")
        expected_head = plans[-1]["accepted_commit"]
        if not isinstance(expected_head, str) or not _SHA.fullmatch(expected_head):
            raise ValueError("run completion head is invalid")
        observed_head = _current_head(Path(state["worktree"]))
        if observed_head != expected_head:
            raise ValueError("run.completed head does not match completed run")
        self._materialize_branch_handoff(store)

        matches: list[dict[str, object]] = []
        for line in store.events_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if isinstance(event, dict) and event.get("action") == "run.completed":
                matches.append(event)
        if len(matches) > 1:
            raise ValueError("run.completed event is duplicated")
        if matches:
            event = matches[0]
            timestamp = event.get("at")
            try:
                parsed_at = (
                    datetime.fromisoformat(timestamp)
                    if isinstance(timestamp, str) and 1 <= len(timestamp) <= 64
                    else None
                )
                timestamp_is_aware = (
                    parsed_at is not None
                    and parsed_at.tzinfo is not None
                    and parsed_at.utcoffset() is not None
                )
            except (ValueError, OverflowError):
                timestamp_is_aware = False
            if (
                set(event) != _RUN_COMPLETED_FIELDS
                or not isinstance(event.get("event_id"), str)
                or not _EVENT_ID.fullmatch(event["event_id"])
                or not timestamp_is_aware
                or event.get("source") != "parent_observed"
                or event.get("run_id") != state["run_id"]
                or event.get("category") != "run"
                or event.get("action") != "run.completed"
                or event.get("head") != expected_head
            ):
                raise ValueError("run.completed event does not match completed run")
        else:
            store.append_event("run.completed", head=expected_head)
        return self._update_reports(store)

    def _report_and_summary(
        self, store: StateStore, *, error: str | None = None
    ) -> dict[str, Any]:
        report_error = self._update_reports(store)
        return self._summary(store, error=report_error or error)

    @staticmethod
    def _update_reports(store: StateStore) -> str | None:
        try:
            events: list[dict[str, object]] = []
            for line in store.events_path.read_text(encoding="utf-8").splitlines():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
            findings = [
                {
                    "signal": str(event.get("action")),
                    "source": "derived",
                    "impact": "terminal plan outcome",
                    "action": "inspect referenced run evidence",
                    "outcome": str(event.get("status", event.get("reason", "recorded"))),
                    "recurrence": "unavailable",
                    "recommendation": "review before changing execution policy",
                    "evidence_refs": [f"events.jsonl:{position}"],
                }
                for position, event in enumerate(events, 1)
                if event.get("action") in {"plan.integrity_failed", "plan.evidence_failed", "plan.failed", "plan.blocked"}
            ]
            report = build_optimization_report(
                run_id=store.state["run_id"],
                events=events,
                findings=findings,
                sdd_root=(
                    Path(store.state["worktree"])
                    / ".superpowers" / "sdd"
                ),
            )
            write_optimization_reports(reports_root=store.root / "reports", report=report)
        except OptimizationMarkdownError as exc:
            store.append_event("report.derivative_failed", reason=str(exc)[:2000])
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            reason = (str(exc).strip() or type(exc).__name__)[:2000]
            store.state["status"] = "failed"
            store.save()
            store.append_event("report.failed", reason=reason)
            return reason
        return None

    def _handoff_error(self, store: StateStore, plan: dict[str, Any], outcome: LaunchResult) -> str | None:
        payload = outcome.payload
        normalized, validation_error = normalize_result_v2(payload)
        if validation_error is not None or normalized is None:
            return validation_error or "invalid_result"
        assert isinstance(payload, dict)
        payload.clear()
        payload.update(normalized)
        status = payload.get("status")
        if payload.get("plan_id") != plan["plan_id"]:
            return "invalid_result"
        head = payload.get("head_commit")
        verification = payload.get("verification")
        assert isinstance(head, str) and isinstance(verification, list)
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
        if outcome.timed_out:
            return "timed_out"
        if outcome.forced_cleanup:
            return "forced_cleanup"
        if outcome.returncode != 0:
            return "nonzero_exit"
        if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
            return "dirty_handoff"
        if not verification or any(item["exit_code"] != 0 for item in verification):
            return "verification_failed"
        return None

    @staticmethod
    def _seal_result(
        path: Path,
        *,
        run_root: Path | None = None,
        expected_digest: str | None = None,
    ) -> None:
        if expected_digest is not None:
            if run_root is None:
                raise ValueError("private result root is required")
            seal_private_result(
                run_root=run_root,
                result_path=path,
                expected_digest=expected_digest,
            )
            return
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
        status = "checkpointed" if outcome.timed_out else "failed"
        payload = {
            "plan_id": plan["plan_id"], "status": status, "head_commit": observed,
            "verification": [],
            "summary": f"child produced no valid result; returncode={outcome.returncode}; timed_out={outcome.timed_out}; log={outcome.log_path}",
        }
        if outcome.timed_out:
            payload.update(
                checkpoint={
                    "reason": "timeout_progress",
                    "progress_fingerprint": "0" * 64,
                    "completed_task_ids": [],
                    "current_task_id": None,
                },
            )
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        target.chmod(0o600)
        return target.resolve()

    @staticmethod
    def _summary(store: StateStore, *, error: str | None = None) -> dict[str, Any]:
        state = store.state
        worktree = Path(state["worktree"])
        observed_head = None
        if worktree.is_dir():
            try:
                observed_head = _git(worktree, "rev-parse", "HEAD")
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        last_known_head = observed_head
        if last_known_head is None and state["plans"]:
            index = min(state["current_plan_index"], len(state["plans"]) - 1)
            last_known_head = state["plans"][index]["last_known_head"]
        visible_plans = state["plans"][:100]
        result = {
            "run_id": state["run_id"], "status": state["status"], "source_commit": state["source_commit"],
            "worktree": state["worktree"], "branch": state["branch"],
            "observed_head": observed_head, "last_known_head": last_known_head,
            "current_plan_index": state["current_plan_index"],
            "plan_count": len(state["plans"]),
            "plans_truncated": len(state["plans"]) > len(visible_plans),
            "plans": [
                {key: plan[key] for key in ("plan_id", "status", "starting_commit", "accepted_commit", "attempt_count", "result_path", "original_result_path")}
                for plan in visible_plans
            ],
        }
        last_decision = None
        try:
            events = [
                json.loads(line)
                for line in store.events_path.read_text(encoding="utf-8").splitlines()
            ]
            last_decision = next(
                (
                    event.get("reason")
                    for event in reversed(events)
                    if event.get("action") in {
                        "plan.checkpoint_decided",
                        "plan.recovery_stopped",
                        "resume.environment_changed",
                        "resume.stopped_unchanged_blocker",
                        "run.worktree_creation_blocked",
                    }
                    and isinstance(event.get("reason"), str)
                ),
                None,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        if last_decision is not None:
            result["last_decision_reason"] = last_decision
        try:
            compiled = json.loads(
                Path(state["compiled_run_index_path"]).read_text(encoding="utf-8")
            )
            advisories = sorted({
                advisory
                for plan in compiled.get("plans", [])
                if isinstance(plan, dict)
                for advisory in plan.get("execution_advisories", [])
                if isinstance(advisory, str)
            })
            if advisories:
                result["execution_advisories"] = advisories
        except (OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        if error:
            result["error"] = error
        return result

    def _busy_summary(self, store: StateStore) -> dict[str, Any]:
        result = self._summary(store, error="run_busy")
        result["status"] = "checkpointed"
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
            "checkpointed",
        }:
            return self._summary(store)
        index = store.state["current_plan_index"]
        if index < len(store.state["plans"]):
            current = store.state["plans"][index]
            if current["status"] == "running":
                current["status"] = "checkpointed"
                current["last_known_head"] = _git(Path(store.state["worktree"]), "rev-parse", "HEAD")
        store.state["status"] = "checkpointed"
        store.save()
        store.append_event("run.interrupted", plan_index=index)
        return self._summary(store)
