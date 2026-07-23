from __future__ import annotations

import dataclasses
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ExitCode, TASK_STATUSES, canonical_json, sha256_json
from .evidence import EvidenceStore
from .git_ops import GitWorkspace, WorktreeObservation
from .helper import HelperDescriptor, HelperServer
from .provider import ClaudeAdapter, DENY_TOOLS, ProviderOutcome, ProviderRequest
from .recovery import (
    ActivityLease,
    normalize_strategy_note,
    ProgressSnapshot,
    RecoveryPolicy,
    strategy_note_digest,
)
from .runtime import RuntimeIdentity, RuntimeUnavailable, require_compatible_runtime
from .storage import ArtifactRef, RunLock, StateStore, atomic_private_write


IMPLEMENTATION_PROMPT = """Read the execution packet and immutable source documents.
Use Superpowers to implement CURRENT_PLAN only.
All SPECIFICATIONS are source-of-truth context; there is no positional
spec-to-plan pairing.
Choose implementation, tests, reviews, subagents, and technical recovery
strategies yourself. Quality and completion outrank token use.
Resolve ordinary defects autonomously. Do not ask the user.
Use the supplied helper for verification. Do not merge, push, deploy, or
modify files outside WORKTREE.
Return only the enforced structured result."""

FINALIZATION_PROMPT = """This is a fresh finalization context for CANDIDATE_HEAD.
Review the full starting-commit-to-candidate diff against every immutable spec
and plan. First declare the complete final verification set through the
helper, then execute every declared command through the helper, then return
one structured whole-branch review. Do not modify the worktree and do not
repeat existing exact successful evidence."""

FINAL_REVIEW_FIX_PROMPT = """This is a fresh implementation context for bundled
whole-branch review findings at CANDIDATE_HEAD. Fix only the supplied
REVIEW_FINDINGS against the immutable specifications and already implemented
plans. Preserve the implemented-plan ledger and do not invent plans, tasks, or
verification requirements. Resolve the findings autonomously through
Superpowers, use the supplied helper for focused verification, and return only
the enforced structured result. Do not merge, push, deploy, or modify files
outside WORKTREE."""

_RUN_SLUG = re.compile(r"[^a-z0-9]+")
_AUTHORITY_BLOCKERS = frozenset(
    {
        "credentials_unavailable",
        "destructive_authorization_required",
        "external_authority_required",
        "external_state_unavailable",
        "irreconcilable_requirements",
        "permission_required",
        "provider_auth_blocked",
        "provider_unavailable",
        "provider_usage_blocked",
    }
)
_CONTAMINATED_OUTCOMES = frozenset(
    {
        "abnormal_compaction",
        "context_overflow",
        "failed",
        "resume_failed",
        "session_damage",
        "session_missing",
        "stalled",
    }
)


@dataclass(frozen=True)
class RuntimePaths:
    state_home: Path
    worktree_home: Path
    runner_script: Path
    skill_root: Path

    def __post_init__(self) -> None:
        for name in ("state_home", "worktree_home", "runner_script", "skill_root"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                raise ValueError(f"{name} must be absolute")
            object.__setattr__(self, name, value)


class _SignalGate:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._previous: dict[int, object] = {}

    def requested(self) -> bool:
        return self._event.is_set()

    def __enter__(self) -> "_SignalGate":
        self._event.clear()
        if threading.current_thread() is not threading.main_thread():
            return self
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._request_stop)
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)
        self._previous.clear()

    def _request_stop(self, _signum: int, _frame: object) -> None:
        self._event.set()


def _runtime_document(identity: RuntimeIdentity) -> dict[str, object]:
    return dataclasses.asdict(identity)


def _run_id(first_plan: Path) -> str:
    slug = _RUN_SLUG.sub("-", first_plan.stem.lower()).strip("-")[:48] or "plan"
    return f"{slug}-{uuid.uuid4()}"


def _git_text(workspace: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _source_head(workspace: Path) -> str:
    return _git_text(workspace, "rev-parse", "HEAD")


def _git_common_dir(workspace: Path) -> Path:
    value = Path(_git_text(workspace, "rev-parse", "--git-common-dir"))
    if not value.is_absolute():
        value = workspace / value
    return value.resolve(strict=True)


def _protected_refs(workspace: Path, assigned_branch: str) -> dict[str, str]:
    result: dict[str, str] = {}
    assigned = f"refs/heads/{assigned_branch}"
    raw = _git_text(
        workspace, "for-each-ref", "--format=%(refname)%09%(objectname)"
    )
    for line in raw.splitlines():
        name, separator, value = line.partition("\t")
        if separator and name != assigned:
            result[name] = value
    return result


def _input_digest(specs: Sequence[Path], plans: Sequence[Path]) -> str:
    import hashlib

    records = []
    for role, paths in (("spec", specs), ("plan", plans)):
        for index, path in enumerate(paths):
            payload = Path(path).read_bytes()
            records.append(
                {
                    "role": role,
                    "input_order": index,
                    "source_path": str(Path(path).absolute()),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_length": len(payload),
                }
            )
    return sha256_json(records)


def _snapshot_input_digest(state: Mapping[str, object]) -> str:
    records = []
    inputs = state.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("input records are invalid")
    for item in inputs:
        if not isinstance(item, Mapping):
            raise ValueError("input record is invalid")
        records.append(
            {
                "role": item.get("role"),
                "input_order": item.get("input_order"),
                "source_path": item.get("source_path"),
                "sha256": item.get("sha256"),
                "byte_length": item.get("byte_length"),
            }
        )
    return sha256_json(records)


def _descriptor_document(descriptor: HelperDescriptor) -> dict[str, object]:
    return {
        "protocol_version": descriptor.protocol_version,
        "socket_path": str(descriptor.socket_path),
        "nonce": descriptor.nonce,
        "client_argv": list(descriptor.client_argv),
    }


def _artifact_payload(store: StateStore, reference: Mapping[str, object]) -> object:
    return json.loads(store.referenced_artifact(reference).read_text(encoding="utf-8"))


def _json_array(value: object) -> bool:
    """Accept immutable provider tuples as JSON arrays without accepting text."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _plain_json(value: object) -> object:
    """Thaw provider-owned immutable JSON before durable serialization."""
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if _json_array(value):
        return [_plain_json(item) for item in value]
    return value


class PlanRunner:
    def __init__(
        self,
        paths: RuntimePaths,
        *,
        runtime_checker: Callable[[], RuntimeIdentity] | None = None,
        adapter_factory: Callable[..., Any] | None = None,
        output: Callable[[str], None] = print,
        environment: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        event_hook: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(paths, RuntimePaths):
            raise TypeError("paths must be RuntimePaths")
        self.paths = paths
        self._runtime_checker = runtime_checker
        self._adapter_factory = adapter_factory
        self._output = output
        self._environment = dict(os.environ if environment is None else environment)
        self._clock = clock
        self._recovery = RecoveryPolicy()
        self._event_hook = event_hook
        self._signals = _SignalGate()

    def _event(self, stage: str) -> None:
        if self._event_hook is not None:
            self._event_hook(stage)

    def create_run(
        self,
        *,
        specs: Sequence[Path],
        plans: Sequence[Path],
        workspace: Path,
        stall_seconds: float,
        model: str | None = None,
    ) -> int:
        try:
            if not specs or not plans:
                raise ValueError("at least one spec and one plan are required")
            if (
                not isinstance(stall_seconds, (int, float))
                or isinstance(stall_seconds, bool)
                or stall_seconds <= 0
            ):
                raise ValueError("stall-seconds must be positive")
            ordered_specs = tuple(Path(item) for item in specs)
            ordered_plans = tuple(Path(item) for item in plans)
            workspace = Path(workspace)
            for path in (*ordered_specs, *ordered_plans, workspace):
                if not path.is_absolute():
                    raise ValueError("all input and workspace paths must be absolute")
            runtime = self._require_runtime()
        except RuntimeUnavailable as error:
            return self._runtime_blocked(str(error))
        except (OSError, ValueError, TypeError) as error:
            self._emit_error("invalid_invocation", error)
            return int(ExitCode.INVALID)

        run_id = _run_id(ordered_plans[0])
        branch = f"claude-plan/{run_id}"
        worktree = self.paths.worktree_home / run_id
        root = self.paths.state_home / run_id
        try:
            starting_commit = _source_head(workspace)
            common_dir = _git_common_dir(workspace)
            input_digest = _input_digest(ordered_specs, ordered_plans)
            immutable_config = {
                "stall_seconds": float(stall_seconds),
                "model": model,
                "permission_mode": "bypassPermissions",
                "deny_tools_digest": sha256_json(list(DENY_TOOLS)),
                "input_snapshot_digest": input_digest,
                "git_common_dir": str(common_dir),
                "protected_refs": _protected_refs(workspace, branch),
            }
            store = StateStore.create(
                root=root,
                provider="claude",
                run_id=run_id,
                source_repository=workspace,
                source_commit=starting_commit,
                worktree=worktree,
                branch=branch,
                specs=ordered_specs,
                plans=ordered_plans,
                immutable_config=immutable_config,
                runner_runtime=_runtime_document(runtime),
            )
            # The runtime identity is now durable. No worktree or provider
            # mutation occurs before this point.
            GitWorkspace.create(workspace, worktree, branch)
        except (OSError, ValueError, TypeError) as error:
            if root.exists():
                try:
                    store = StateStore.open(root)
                    state = store.snapshot()
                    state["status"] = "failed"
                    state["failure"] = {
                        "reason_code": "state_integrity_failed",
                        "detail": str(error)[:512],
                    }
                    store.commit(state)
                except (OSError, ValueError):
                    pass
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)
        return self._execute(store)

    def resume(
        self,
        run_id: str,
        *,
        retry_blocked: bool,
        retry_failed: bool,
        strategy_note: str | None,
    ) -> int:
        if strategy_note is not None and not retry_failed:
            self._emit_error(
                "invalid_invocation", "--strategy-note requires --retry-failed"
            )
            return int(ExitCode.INVALID)
        if retry_failed and (not isinstance(strategy_note, str) or not strategy_note.strip()):
            self._emit_error(
                "invalid_invocation",
                "--retry-failed requires a nonempty --strategy-note",
            )
            return int(ExitCode.INVALID)
        try:
            self._require_runtime()
            run_root = self.paths.state_home / run_id
            if not run_root.exists():
                raise FileNotFoundError(f"unknown run: {run_id}")
            store = StateStore.open(run_root)
            state = store.snapshot()
            status = state["status"]
            if status == "ready_for_integration":
                self._emit_summary(state)
                return int(ExitCode.READY)
            if status == "blocked" and not retry_blocked:
                self._emit_summary(state)
                return int(ExitCode.BLOCKED)
            if status == "failed":
                if not retry_failed:
                    self._emit_summary(state)
                    return int(ExitCode.FAILED)
                failure = state.get("failure")
                failure_signature = (
                    failure.get("failure_signature")
                    if isinstance(failure, Mapping)
                    else None
                )
                prior = (
                    failure.get("strategy_digests", [])
                    if isinstance(failure, Mapping)
                    else []
                )
                for reference in state["artifact_refs"]:
                    if (
                        not isinstance(reference, Mapping)
                        or reference.get("kind") != "strategy_note"
                    ):
                        continue
                    payload = _artifact_payload(store, reference)
                    if (
                        isinstance(payload, Mapping)
                        and payload.get("failure_signature") == failure_signature
                        and isinstance(payload.get("strategy_note_digest"), str)
                    ):
                        prior = [*prior, payload["strategy_note_digest"]]
                digest = strategy_note_digest(strategy_note)
                if digest in prior:
                    raise ValueError("strategy note duplicates a prior strategy")
                normalized_note = normalize_strategy_note(strategy_note)
                audit_artifact = store.put_artifact(
                    "recovery_audit",
                    {
                        "run_id": state["run_id"],
                        "failed_revision": state["revision"],
                        "failure": (
                            dict(failure) if isinstance(failure, Mapping) else None
                        ),
                    },
                )
                strategy_artifact = store.put_artifact(
                    "strategy_note",
                    {
                        "run_id": state["run_id"],
                        "failure_signature": failure_signature,
                        "strategy_note": normalized_note,
                        "strategy_note_digest": digest,
                    },
                )
                for artifact in (audit_artifact, strategy_artifact):
                    if artifact.as_dict() not in state["artifact_refs"]:
                        state["artifact_refs"].append(artifact.as_dict())
                state["status"] = "resumable"
                state["failure"] = {
                    "reason_code": (
                        failure.get("reason_code")
                        if isinstance(failure, Mapping)
                        else "recovery_exhausted"
                    ),
                    "failure_signature": failure_signature,
                    "failure_sequence": [],
                    "operator_strategy_note": normalized_note,
                    "operator_strategy_artifact": strategy_artifact.as_dict(),
                    "recovery_audit_artifact": audit_artifact.as_dict(),
                    "required_strategy_change": True,
                    "strategy_digests": [digest],
                    "next_session_action": "fresh_session",
                }
                store.commit(state)
            elif retry_failed:
                raise ValueError("--retry-failed is valid only for a failed run")
            elif status == "blocked":
                state["status"] = "resumable"
                store.commit(state)
            elif retry_blocked:
                raise ValueError("--retry-blocked is valid only for a blocked run")
            return self._execute(store)
        except RuntimeUnavailable as error:
            return self._runtime_blocked(str(error))
        except FileNotFoundError as error:
            self._emit_error("unknown_run", error)
            return int(ExitCode.INVALID)
        except ValueError as error:
            message = str(error)
            code = (
                ExitCode.INVALID
                if "input snapshot digest" in message
                or "unknown run" in message
                or "strategy" in message
                or "--retry" in message
                else ExitCode.INTEGRITY
            )
            self._emit_error(
                "input_changed_requires_new_run"
                if code == ExitCode.INVALID and "input snapshot" in message
                else "invalid_state",
                error,
            )
            return int(code)
        except Exception as error:
            self._emit_error("internal_error", error)
            return int(ExitCode.INTERNAL)

    def inspect(self, run_id: str) -> int:
        try:
            run_root = self.paths.state_home / run_id
            if not run_root.exists():
                raise FileNotFoundError(f"unknown run: {run_id}")
            store = StateStore.open(run_root)
            self._emit_summary(store.snapshot())
            return int(ExitCode.READY)
        except FileNotFoundError as error:
            self._emit_error("unknown_run", error)
            return int(ExitCode.INVALID)
        except (OSError, ValueError) as error:
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)

    def _require_runtime(self) -> RuntimeIdentity:
        if self._runtime_checker is None:
            return require_compatible_runtime()
        return require_compatible_runtime(self._runtime_checker())

    def _runtime_blocked(self, reason: str) -> int:
        reason_code = (
            reason
            if reason in {"runtime_missing", "runtime_incompatible"}
            else "runtime_incompatible"
        )
        document = {
            "status": "blocked",
            "reason_code": reason_code,
            "detail": "required uv-managed CPython 3.13 runtime is unavailable",
        }
        # Preserve a bounded preflight record without snapshotting inputs or
        # creating a worktree.
        try:
            self.paths.state_home.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_private_write(
                self.paths.state_home / "last-runtime-blocked.json",
                canonical_json(document),
            )
        except OSError:
            pass
        self._output(json.dumps(document, sort_keys=True))
        return int(ExitCode.BLOCKED)

    def _execute(self, store: StateStore) -> int:
        try:
            with self._signals, RunLock(store.root / "run.lock"):
                state = store.snapshot()
                self._reconcile_controller(store, state)
                state = store.snapshot()
                if (
                    _snapshot_input_digest(state)
                    != state["immutable_config"].get("input_snapshot_digest")
                ):
                    raise ValueError("input snapshot digest changed")
                repository = state["repository"]
                workspace = GitWorkspace.open(
                    Path(repository["source_repository"]),
                    Path(repository["worktree"]),
                    repository["branch"],
                )
                self._require_git_contract(state, workspace)
                self._reconcile_completed_attempt(store, workspace)
                state = store.snapshot()
                while state["current_plan_index"] < len(state["plans"]):
                    code = self._execute_current_plan(store, workspace)
                    if code is not None:
                        return code
                    state = store.snapshot()
                if self._pending_review_fix(state):
                    finalization = state["finalization"]
                    code = self._recover_review_findings(
                        store,
                        workspace,
                        finalization["review_findings"],
                        initialize=False,
                    )
                    if code is not None:
                        return code
                return self._finalize(store, workspace)
        except ValueError as error:
            if "input snapshot digest" in str(error):
                self._emit_error("input_changed_requires_new_run", error)
                return int(ExitCode.INVALID)
            self._fail_closed(store, "state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)
        except RuntimeError as error:
            self._fail_closed(store, "controller_transport_failed", error)
            return int(ExitCode.INTERNAL)
        except Exception as error:
            self._fail_closed(store, "internal_error", error)
            return int(ExitCode.INTERNAL)

    def _require_git_contract(
        self,
        state: Mapping[str, object],
        workspace: GitWorkspace,
    ) -> WorktreeObservation:
        config = state["immutable_config"]
        if str(workspace._common_dir) != config.get("git_common_dir"):
            raise ValueError("Git common directory drift detected")
        if workspace.protected_refs() != config.get("protected_refs"):
            raise ValueError("protected ref mutation detected")
        observation = workspace.require_identity()
        _git_text(
            workspace.worktree,
            "merge-base",
            "--is-ancestor",
            state["repository"]["source_commit"],
            observation.head,
        )
        if observation.clean:
            return observation
        self._require_sealed_partial_worktree(state, observation)
        return observation

    @staticmethod
    def _require_sealed_partial_worktree(
        state: Mapping[str, object], observation: WorktreeObservation
    ) -> None:
        failure = state.get("failure")
        sealed = (
            failure.get("partial_worktree")
            if isinstance(failure, Mapping)
            else None
        )
        expected_keys = {
            "version",
            "attempt_id",
            "mode",
            "plan_index",
            "head",
            "branch",
            "porcelain_digest",
            "tree_digest",
            "clean",
        }
        if not isinstance(sealed, Mapping) or set(sealed) != expected_keys:
            raise ValueError("dirty worktree has no exact resumable checkpoint")
        identity = dataclasses.asdict(observation)
        if any(sealed.get(key) != value for key, value in identity.items()):
            raise ValueError("sealed partial worktree identity drift detected")
        if sealed.get("version") != 1 or sealed.get("clean") is not False:
            raise ValueError("sealed partial worktree checkpoint is invalid")
        if sealed.get("mode") not in {"implementation", "final_review_fix"}:
            raise ValueError("dirty worktree mode is not resumable")
        attempts = state.get("attempts")
        attempt = next(
            (
                item
                for item in reversed(attempts)
                if isinstance(item, Mapping)
                and item.get("attempt_id") == sealed.get("attempt_id")
            ),
            None,
        ) if isinstance(attempts, list) else None
        if (
            not isinstance(attempt, Mapping)
            or attempt.get("mode") != sealed.get("mode")
            or attempt.get("plan_index") != sealed.get("plan_index")
            or attempt.get("outcome") != "controller_stopped"
        ):
            raise ValueError("sealed partial worktree attempt is invalid")

    @staticmethod
    def _pending_review_fix(state: Mapping[str, object]) -> bool:
        finalization = state.get("finalization")
        findings = (
            finalization.get("review_findings")
            if isinstance(finalization, Mapping)
            else None
        )
        return (
            isinstance(finalization, Mapping)
            and finalization.get("pending_mode") == "final_review_fix"
            and _json_array(findings)
            and bool(findings)
            and state.get("current_plan_index") == len(state.get("plans", []))
        )

    def _reconcile_controller(
        self, store: StateStore, state: dict[str, object]
    ) -> None:
        if state["status"] not in {"running", "recovering"}:
            return
        attempts = state.get("attempts")
        active = attempts[-1] if isinstance(attempts, list) and attempts else None
        if isinstance(active, dict) and not active.get("completed", False):
            state["status"] = "resumable"
            active["reconciled"] = "controller_not_live"
            store.commit(state)
            return
        if (
            not isinstance(active, dict)
            or active.get("completed") is not True
            or active.get("outcome") in {"implemented", "reviewed"}
        ):
            return
        outcome_kind = str(active.get("outcome") or "transport_failed")
        reason = str(
            active.get("provider_code") or "controller_transport_failed"
        )
        strategy = (
            f"controller crash recovery after {outcome_kind}: "
            "start a fresh provider session with a changed strategy"
        )
        signature = sha256_json(
            {
                "reason_code": reason,
                "provider_code": active.get("provider_code"),
                "mode": active.get("mode"),
                "plan_index": active.get("plan_index"),
                "input_digest": state["immutable_config"].get(
                    "input_snapshot_digest"
                ),
            }
        )
        strategy_ref = store.put_artifact(
            "strategy_note",
            {
                "run_id": state["run_id"],
                "strategy_note": strategy,
                "failure_signature": signature,
                "strategy_note_digest": strategy_note_digest(strategy),
            },
        )
        state = store.snapshot()
        active = state["attempts"][-1]
        active["reconciled"] = "completed_nonterminal"
        if strategy_ref.as_dict() not in state["artifact_refs"]:
            state["artifact_refs"].append(strategy_ref.as_dict())
        baseline = active.get("baseline_progress")
        tree_digest = (
            baseline.get("git_tree_digest")
            if isinstance(baseline, Mapping)
            else None
        )
        sequence_entry = {
            "failure_signature": signature,
            "strategy_note_digest": strategy_note_digest(strategy),
            "tree_digest": tree_digest,
        }
        state["status"] = "recovering"
        state["failure"] = {
            "reason_code": reason,
            "failure_signature": signature,
            "failure_sequence": [sequence_entry],
            "baseline_progress": baseline,
            "required_strategy_change": True,
            "next_session_action": "fresh_session",
            "strategy_digests": [strategy_note_digest(strategy)],
        }
        store.commit(state)

    def _execute_current_plan(
        self, store: StateStore, workspace: GitWorkspace
    ) -> int | None:
        state = store.snapshot()
        index = state["current_plan_index"]
        plan = state["plans"][index]
        if plan["status"] == "implemented":
            state["current_plan_index"] = index + 1
            store.commit(state)
            return None
        plan["status"] = "running"
        state["status"] = "running"
        state["failure"] = state.get("failure")
        attempt_id = str(uuid.uuid4())
        state["attempts"].append(
            {
                "attempt_id": attempt_id,
                "mode": "implementation",
                "plan_index": index,
                "controller_pid": os.getpid(),
                "completed": False,
                "baseline_progress": dataclasses.asdict(
                    self._progress(state, workspace)
                ),
            }
        )
        store.commit(state)
        observation = self._require_git_contract(state, workspace)
        session_id = self._implementation_session(state, index)
        outcome = self._launch(
            store,
            workspace,
            mode="implementation",
            observation_head=observation.head,
            current_plan_index=index,
            session_id=session_id,
            attempt_id=attempt_id,
        )
        self._event("provider_outcome_received")
        if outcome.kind == "implemented":
            return self._accept_implemented(
                store, workspace, outcome, index, attempt_id
            )
        if outcome.kind == "controller_stopped":
            return self._pause_resumable(
                store, workspace, outcome, attempt_id, index, "implementation"
            )
        self._checkpoint_outcome(store, outcome, attempt_id, index, "implementation")
        if outcome.kind == "blocked":
            return self._block(store, outcome)
        return self._recover(store, workspace, outcome, index)

    def _implementation_session(
        self, state: Mapping[str, object], index: int
    ) -> str | None:
        failure = state.get("failure")
        if (
            isinstance(failure, Mapping)
            and failure.get("next_session_action") == "fresh_session"
        ):
            return None
        sessions = state.get("sessions")
        if not isinstance(sessions, list):
            return None
        for session in reversed(sessions):
            if (
                isinstance(session, Mapping)
                and session.get("mode") == "implementation"
                and session.get("plan_index") == index
                and session.get("health") == "healthy"
                and isinstance(session.get("session_id"), str)
            ):
                return session["session_id"]
        return None

    def _launch(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        *,
        mode: str,
        observation_head: str,
        current_plan_index: int | None,
        session_id: str | None,
        attempt_id: str,
    ) -> ProviderOutcome:
        state = store.snapshot()
        client_argv = (
            str(Path(sys.executable).resolve()),
            str(self.paths.runner_script.resolve()),
            "_helper",
        )
        evidence = EvidenceStore(store, workspace, self._environment)
        finalization = state.get("finalization")
        sealed_digest = (
            finalization.get("verification_set_digest")
            if mode == "finalization" and isinstance(finalization, Mapping)
            else None
        )
        sealed_head = (
            finalization.get("candidate_head")
            if isinstance(sealed_digest, str)
            and isinstance(finalization, Mapping)
            else None
        )
        lease = ActivityLease(
            state["immutable_config"]["stall_seconds"], self._clock()
        )
        with HelperServer(
            run_id=state["run_id"],
            worktree=workspace.worktree,
            evidence_store=evidence,
            client_argv=client_argv,
            state_store=store,
            sealed_final_set_digest=sealed_digest,
            sealed_candidate_head=sealed_head,
            on_command_started=lease.cover_command_until,
            on_command_finished=lease.command_finished,
        ) as helper:
            if mode == "implementation":
                packet = self._implementation_packet(
                    store.snapshot(),
                    observation_head,
                    current_plan_index,
                    helper.descriptor,
                )
                prompt = IMPLEMENTATION_PROMPT
                schema = self.paths.skill_root / "templates" / "plan-result.schema.json"
            elif mode == "final_review_fix":
                packet = self._final_review_fix_packet(
                    store.snapshot(), observation_head, helper.descriptor
                )
                prompt = FINAL_REVIEW_FIX_PROMPT
                schema = self.paths.skill_root / "templates" / "plan-result.schema.json"
            else:
                packet = self._finalization_packet(
                    store.snapshot(), observation_head, helper.descriptor
                )
                prompt = FINALIZATION_PROMPT
                schema = (
                    self.paths.skill_root
                    / "templates"
                    / "finalization-result.schema.json"
                )
            adapter = self._make_adapter(
                state["run_id"], helper.descriptor, workspace
            )
            request = ProviderRequest(
                worktree=workspace.worktree,
                prompt=prompt
                + "\nEXECUTION_PACKET="
                + canonical_json(packet).decode("utf-8"),
                output_schema=json.loads(schema.read_text(encoding="utf-8")),
                model=state["immutable_config"]["model"],
                session_id=session_id or str(uuid.uuid4()),
                resume=session_id is not None,
            )
            if self._signals.requested():
                return ProviderOutcome(
                    "controller_stopped",
                    None,
                    None,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            return adapter.launch(
                request,
                lease,
                on_session_id=lambda captured: self._capture_session(
                    store,
                    attempt_id=attempt_id,
                    mode=mode,
                    plan_index=current_plan_index,
                    session_id=captured,
                    candidate_head=observation_head,
                ),
            )

    def _make_adapter(
        self, run_id: str, helper: HelperDescriptor, workspace: GitWorkspace
    ) -> Any:
        values = {
            "source_env": self._environment,
            "run_id": run_id,
            "helper": helper,
            "remotes": tuple(
                line
                for line in _git_text(workspace.worktree, "remote").splitlines()
                if line
            ),
            "stop_requested": self._signals.requested,
        }
        if self._adapter_factory is None:
            return ClaudeAdapter(**values)
        return self._adapter_factory(**values)

    def _implementation_packet(
        self,
        state: Mapping[str, object],
        current_head: str,
        current_index: int,
        helper: HelperDescriptor,
    ) -> dict[str, object]:
        specs = [
            item
            for item in state["inputs"]
            if item["role"] == "spec"
        ]
        plan = state["plans"][current_index]
        handoffs = self._artifact_summaries(state, "plan_handoff")
        receipts = self._artifact_summaries(state, "verification_receipt")
        failure = state.get("failure")
        operator_notes = self._operator_strategy_notes(state)
        return {
            "packet_version": 1,
            "mode": "implementation",
            "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"],
            "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"],
            "current_head": current_head,
            "specifications": [
                {
                    "snapshot_path": item["snapshot_path"],
                    "sha256": item["sha256"],
                }
                for item in specs
            ],
            "current_plan": {
                "index": current_index,
                "total": len(state["plans"]),
                "snapshot_path": plan["snapshot_path"],
                "sha256": plan["sha256"],
            },
            "implemented_plan_handoffs": handoffs,
            "task_ledger": state["task_ledger"],
            "verification_receipts": receipts,
            "checkpoint_revision": state["revision"],
            "recovery_context": self._recovery_context(
                state,
                current_head=current_head,
                current_index=current_index,
                operator_notes=operator_notes,
            ),
            "required_strategy_change": bool(
                isinstance(failure, Mapping)
                and failure.get("required_strategy_change")
            ) or bool(operator_notes),
            "operator_strategy_notes": operator_notes,
            "helper": _descriptor_document(helper),
            "quality_profile": "quality_first",
            "integration": "not_observed",
        }

    def _finalization_packet(
        self,
        state: Mapping[str, object],
        candidate_head: str,
        helper: HelperDescriptor,
    ) -> dict[str, object]:
        finalization = state.get("finalization")
        failure = state.get("failure")
        operator_notes = self._operator_strategy_notes(state)
        return {
            "packet_version": 1,
            "mode": "finalization",
            "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"],
            "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"],
            "candidate_head": candidate_head,
            "sealed_verification_set_digest": (
                finalization.get("verification_set_digest")
                if isinstance(finalization, Mapping)
                and finalization.get("candidate_head") == candidate_head
                else None
            ),
            "required_strategy_change": bool(
                isinstance(failure, Mapping)
                and failure.get("required_strategy_change")
            ) or bool(operator_notes),
            "operator_strategy_notes": operator_notes,
            "specifications": [
                {
                    "snapshot_path": item["snapshot_path"],
                    "sha256": item["sha256"],
                }
                for item in state["inputs"]
                if item["role"] == "spec"
            ],
            "plans": [
                {
                    "snapshot_path": item["snapshot_path"],
                    "sha256": item["sha256"],
                }
                for item in state["plans"]
            ],
            "implemented_plan_handoffs": self._artifact_summaries(
                state, "plan_handoff"
            ),
            "verification_receipts": self._artifact_summaries(
                state, "verification_receipt"
            ),
            "checkpoint_revision": state["revision"],
            "helper": _descriptor_document(helper),
            "quality_profile": "quality_first",
            "integration": "not_observed",
        }

    def _final_review_fix_packet(
        self,
        state: Mapping[str, object],
        candidate_head: str,
        helper: HelperDescriptor,
    ) -> dict[str, object]:
        failure = state.get("failure")
        finalization = state.get("finalization")
        findings = (
            finalization.get("review_findings")
            if isinstance(finalization, Mapping)
            else None
        )
        if not isinstance(findings, list) and isinstance(failure, Mapping):
            findings = failure.get("review_findings")
        if not isinstance(findings, list) or not findings:
            raise ValueError("bundled review findings are unavailable")
        operator_notes = self._operator_strategy_notes(state)
        return {
            "packet_version": 1,
            "mode": "final_review_fix",
            "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"],
            "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"],
            "candidate_head": candidate_head,
            "review_findings": [_plain_json(item) for item in findings],
            "specifications": [
                {
                    "snapshot_path": item["snapshot_path"],
                    "sha256": item["sha256"],
                }
                for item in state["inputs"]
                if item["role"] == "spec"
            ],
            "implemented_plans": [
                {
                    "plan_id": item["plan_id"],
                    "status": item["status"],
                    "snapshot_path": item["snapshot_path"],
                    "sha256": item["sha256"],
                }
                for item in state["plans"]
            ],
            "implemented_plan_handoffs": self._artifact_summaries(
                state, "plan_handoff"
            ),
            "task_ledger": state["task_ledger"],
            "verification_receipts": self._artifact_summaries(
                state, "verification_receipt"
            ),
            "invalidated_final_verification_set_digest": (
                state["finalization"].get("verification_set_digest")
                if isinstance(state.get("finalization"), Mapping)
                else None
            ),
            "checkpoint_revision": state["revision"],
            "required_strategy_change": True,
            "operator_strategy_notes": operator_notes,
            "helper": _descriptor_document(helper),
            "quality_profile": "quality_first",
            "integration": "not_observed",
        }

    @staticmethod
    def _artifact_summaries(
        state: Mapping[str, object], kind: str
    ) -> list[dict[str, object]]:
        references = state.get("artifact_refs")
        if not isinstance(references, list):
            return []
        return [
            {
                "kind": item["kind"],
                "digest": item["digest"],
                "relative_path": item["relative_path"],
            }
            for item in references
            if isinstance(item, Mapping) and item.get("kind") == kind
        ]

    @staticmethod
    def _operator_strategy_notes(
        state: Mapping[str, object],
    ) -> list[dict[str, object]]:
        inputs = state.get("inputs")
        references = state.get("artifact_refs")
        if not isinstance(inputs, list) or not inputs or not isinstance(references, list):
            return []
        run_root = Path(inputs[0]["snapshot_path"]).parent.parent.resolve()
        notes: list[dict[str, object]] = []
        for reference in references:
            if (
                not isinstance(reference, Mapping)
                or reference.get("kind") != "strategy_note"
            ):
                continue
            path = (run_root / reference["relative_path"]).resolve()
            if run_root not in path.parents:
                raise ValueError("strategy note artifact escapes run root")
            raw = path.read_bytes()
            payload = json.loads(raw)
            if (
                canonical_json(payload) != raw
                or sha256_json(payload) != reference.get("digest")
                or not isinstance(payload.get("strategy_note"), str)
                or not isinstance(payload.get("strategy_note_digest"), str)
                or re.fullmatch(
                    r"[0-9a-f]{64}", payload["strategy_note_digest"]
                ) is None
            ):
                raise ValueError("strategy note artifact is invalid")
            notes.append(
                {
                    "digest": reference["digest"],
                    "snapshot_path": str(path),
                    "strategy_note": payload["strategy_note"],
                    "strategy_note_digest": payload["strategy_note_digest"],
                    "failure_signature": payload.get("failure_signature"),
                }
            )
        return notes

    @staticmethod
    def _recovery_context(
        state: Mapping[str, object],
        *,
        current_head: str,
        current_index: int,
        operator_notes: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        failure = state.get("failure")
        if not isinstance(failure, Mapping):
            failure = {}
        signature = failure.get("failure_signature")
        if (
            not isinstance(signature, str)
            or re.fullmatch(r"[0-9a-f]{64}", signature) is None
        ):
            signature = None
        reason = failure.get("reason_code")
        if isinstance(reason, str) and reason.strip():
            reason = normalize_strategy_note(reason)
            reason = reason.encode("utf-8")[:256].decode("utf-8", "ignore")
        else:
            reason = None
        known_digests = (
            {
                digest
                for digest in failure.get("strategy_digests", [])
                if isinstance(digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", digest)
            }
            if isinstance(failure.get("strategy_digests"), list)
            else set()
        )
        attempted: list[dict[str, object]] = []
        for note in operator_notes:
            text = note.get("strategy_note")
            digest = note.get("strategy_note_digest")
            if (
                not isinstance(text, str)
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                continue
            normalized = normalize_strategy_note(text)
            if (
                digest not in known_digests
                or note.get("failure_signature") != signature
            ):
                continue
            attempted.append(
                {
                    "failure_signature": signature,
                    "strategy_note": normalized,
                    "strategy_note_digest": digest,
                }
            )
        return {
            "failure_reason": reason,
            "failure_signature": signature,
            "attempted_strategies": attempted[-3:],
            "required_strategy_change": bool(
                failure.get("required_strategy_change")
            ),
            "next_session_action": (
                failure.get("next_session_action")
                if failure.get("next_session_action")
                in {"explicit_resume", "fresh_session", "none"}
                else None
            ),
            "checkpoint": {
                "revision": state["revision"],
                "head": current_head,
                "plan_index": current_index,
            },
        }

    def _checkpoint_outcome(
        self,
        store: StateStore,
        outcome: ProviderOutcome,
        attempt_id: str,
        plan_index: int | None,
        mode: str,
    ) -> None:
        result_artifact = (
            store.put_artifact("provider_result", _plain_json(outcome.result))
            if outcome.kind == "reviewed"
            and isinstance(outcome.result, Mapping)
            else None
        )
        state = store.snapshot()
        for attempt in reversed(state["attempts"]):
            if attempt.get("attempt_id") == attempt_id:
                attempt["completed"] = True
                attempt["outcome"] = outcome.kind
                attempt["provider_code"] = outcome.provider_code
                if result_artifact is not None:
                    attempt["result_artifact"] = result_artifact.as_dict()
                break
        if (
            result_artifact is not None
            and result_artifact.as_dict() not in state["artifact_refs"]
        ):
            state["artifact_refs"].append(result_artifact.as_dict())
        session = next(
            (
                item
                for item in reversed(state["sessions"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        attempt = next(
            (
                item
                for item in reversed(state["attempts"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if session is None:
            if attempt is not None:
                attempt["session_missing"] = True
        elif outcome.session_id is not None:
            if session.get("session_id") != outcome.session_id:
                raise ValueError("provider outcome session does not match capture")
            session["phase"] = "completed"
            session["health"] = (
                "invalid"
                if outcome.kind in _CONTAMINATED_OUTCOMES
                else "healthy"
            )
            if mode == "finalization":
                candidate_head = session.get("candidate_head")
                declaration = (
                    self._existing_final_set(store, candidate_head)
                    if isinstance(candidate_head, str)
                    else None
                )
                if declaration is not None:
                    session["verification_set_digest"] = declaration
                    state["finalization"] = {
                        "candidate_head": candidate_head,
                        "verification_set_digest": declaration,
                    }
        if isinstance(outcome.result, Mapping) and isinstance(
            outcome.result.get("task_ledger"), list
        ):
            state["task_ledger"] = self._validated_task_ledger(
                outcome.result["task_ledger"]
            )
        store.commit(state)

    def _capture_session(
        self,
        store: StateStore,
        *,
        attempt_id: str,
        mode: str,
        plan_index: int | None,
        session_id: str,
        candidate_head: str,
    ) -> None:
        state = store.snapshot()
        attempt = next(
            (
                item
                for item in reversed(state["attempts"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if attempt is None:
            raise ValueError("provider attempt is unavailable at session capture")
        existing = next(
            (
                item
                for item in reversed(state["sessions"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if existing is not None:
            if existing.get("session_id") != session_id:
                raise ValueError("provider session changed within one attempt")
            return
        attempt["session_id"] = session_id
        finalization = state.get("finalization")
        state["sessions"].append(
            {
                "attempt_id": attempt_id,
                "mode": mode,
                "plan_index": plan_index,
                "session_id": session_id,
                "phase": "captured",
                "health": "healthy",
                "candidate_head": candidate_head,
                "verification_set_digest": (
                    finalization.get("verification_set_digest")
                    if mode == "finalization"
                    and isinstance(finalization, Mapping)
                    else None
                ),
            }
        )
        store.commit(state)

    def _pause_resumable(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        attempt_id: str,
        plan_index: int | None,
        mode: str,
    ) -> int:
        state = store.snapshot()
        attempt = next(
            (
                item
                for item in reversed(state["attempts"])
                if isinstance(item, Mapping)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if not isinstance(attempt, dict):
            raise ValueError("provider attempt is unavailable at signal checkpoint")
        if attempt.get("mode") != mode or attempt.get("plan_index") != plan_index:
            raise ValueError("provider attempt changed at signal checkpoint")
        attempt["completed"] = True
        attempt["outcome"] = "controller_stopped"
        attempt["provider_code"] = outcome.provider_code
        session = next(
            (
                item
                for item in reversed(state["sessions"])
                if isinstance(item, Mapping)
                and item.get("attempt_id") == attempt_id
                and item.get("health") == "healthy"
                and isinstance(item.get("session_id"), str)
            ),
            None,
        )
        if session is None:
            attempt["session_missing"] = True
        elif outcome.session_id is not None:
            if session.get("session_id") != outcome.session_id:
                raise ValueError("provider outcome session does not match capture")
            session["phase"] = "completed"
            session["health"] = "healthy"
        observation = workspace.require_identity()
        partial = None
        if not observation.clean:
            if mode not in {"implementation", "final_review_fix"}:
                raise ValueError("provider modified worktree in non-mutating mode")
            partial = {
                "version": 1,
                "attempt_id": attempt_id,
                "mode": mode,
                "plan_index": plan_index,
                **dataclasses.asdict(observation),
            }
        state["status"] = "resumable"
        state["failure"] = {
            "reason_code": "controller_transport_failed",
            "detail": "controller_signal",
            "required_strategy_change": session is None,
            "next_session_action": (
                "explicit_resume" if session is not None else "fresh_session"
            ),
            "pending_mode": mode,
            "partial_worktree": partial,
        }
        if mode == "final_review_fix":
            finalization = dict(state.get("finalization") or {})
            finalization["pending_mode"] = mode
            state["finalization"] = finalization
        store.commit(state)
        self._emit_summary(store.snapshot())
        return int(ExitCode.RESUMABLE)

    def _accept_implemented(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        index: int,
        attempt_id: str,
    ) -> int | None:
        result = outcome.result
        if not isinstance(result, Mapping):
            return self._integrity_failure(store, "missing implementation result")
        observation = workspace.require_clean_ancestor(
            store.snapshot()["repository"]["source_commit"]
        )
        if result.get("head_commit") != observation.head:
            return self._integrity_failure(store, "implementation HEAD mismatch")
        ledger = self._validated_task_ledger(result.get("task_ledger"))
        self._require_all_tasks_reported_done(ledger)
        obligations = result.get("open_obligation_ids")
        if not _json_array(obligations) or obligations:
            return self._integrity_failure(store, "implementation obligations remain")
        state = store.snapshot()
        result_artifact = store.put_artifact(
            "provider_result", _plain_json(result)
        )
        handoff_artifact = store.put_artifact(
            "plan_handoff",
            {
                "plan_index": index,
                "head_commit": observation.head,
                "summary": str(result.get("summary", ""))[:4096],
                "task_ledger": ledger,
            },
        )
        state = store.snapshot()
        for artifact in (result_artifact, handoff_artifact):
            if artifact.as_dict() not in state["artifact_refs"]:
                state["artifact_refs"].append(artifact.as_dict())
        attempt = next(
            (
                item
                for item in reversed(state["attempts"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if attempt is None:
            raise ValueError("implementation attempt is unavailable")
        attempt.update(
            {
                "completed": True,
                "outcome": "implemented",
                "provider_code": outcome.provider_code,
                "result_artifact": result_artifact.as_dict(),
            }
        )
        session = next(
            (
                item
                for item in reversed(state["sessions"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if session is None and outcome.session_id is not None:
            session = {
                "attempt_id": attempt_id,
                "mode": "implementation",
                "plan_index": index,
                "session_id": outcome.session_id,
            }
            state["sessions"].append(session)
        if session is not None:
            session["phase"] = "completed"
            session["health"] = "healthy"
        state["task_ledger"] = ledger
        state["plans"][index]["status"] = "implemented"
        state["current_plan_index"] = index + 1
        state["status"] = "resumable"
        state["failure"] = None
        store.commit(state)
        return None

    def _reconcile_completed_attempt(
        self, store: StateStore, workspace: GitWorkspace
    ) -> None:
        state = store.snapshot()
        index = state["current_plan_index"]
        if index >= len(state["plans"]):
            return
        plan = state["plans"][index]
        if plan["status"] != "running":
            return
        attempts = state.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return
        attempt = attempts[-1]
        if (
            not isinstance(attempt, Mapping)
            or attempt.get("plan_index") != index
            or attempt.get("mode") != "implementation"
            or attempt.get("completed") is not True
            or attempt.get("outcome") != "implemented"
            or not isinstance(attempt.get("result_artifact"), Mapping)
        ):
            return
        result = _artifact_payload(store, attempt["result_artifact"])
        if not isinstance(result, Mapping):
            raise ValueError("completed provider result artifact is invalid")
        session_id = attempt.get("session_id")
        outcome = ProviderOutcome(
            "implemented",
            0,
            session_id if isinstance(session_id, str) else None,
            result,
            None,
            {},
            (),
            "",
        )
        self._accept_implemented(
            store,
            workspace,
            outcome,
            index,
            attempt["attempt_id"],
        )

    @staticmethod
    def _validated_task_ledger(value: object) -> list[dict[str, object]]:
        if not _json_array(value):
            raise ValueError("task ledger must be a list")
        result: list[dict[str, object]] = []
        seen: set[str] = set()
        for entry in value:
            if not isinstance(entry, Mapping):
                raise ValueError("task ledger entry is invalid")
            task_id = entry.get("task_id")
            status = entry.get("status")
            evidence = entry.get("evidence_digests")
            if (
                not isinstance(task_id, str)
                or not task_id
                or task_id in seen
                or status not in TASK_STATUSES
                or not _json_array(evidence)
                or any(
                    not isinstance(item, str)
                    or re.fullmatch(r"[0-9a-f]{64}", item) is None
                    for item in evidence
                )
            ):
                raise ValueError("task ledger entry is invalid")
            seen.add(task_id)
            result.append(
                {
                    "task_id": task_id,
                    "status": status,
                    "evidence_digests": list(evidence),
                }
            )
        return result

    @staticmethod
    def _require_all_tasks_reported_done(
        ledger: Sequence[Mapping[str, object]],
    ) -> None:
        if any(entry.get("status") != "reported_done" for entry in ledger):
            raise ValueError("all submitted tasks must be reported_done")

    def _block(self, store: StateStore, outcome: ProviderOutcome) -> int:
        result = outcome.result
        blocker = result.get("blocker") if isinstance(result, Mapping) else None
        kind = blocker.get("kind") if isinstance(blocker, Mapping) else None
        reason = outcome.provider_code or kind
        if reason not in _AUTHORITY_BLOCKERS:
            return self._integrity_failure(store, "unapproved blocker kind")
        state = store.snapshot()
        state["status"] = "blocked"
        state["failure"] = {
            "reason_code": reason,
            "blocker": dict(blocker) if isinstance(blocker, Mapping) else None,
        }
        store.commit(state)
        self._emit_summary(store.snapshot())
        return int(ExitCode.BLOCKED)

    def _progress(
        self, state: Mapping[str, object], workspace: GitWorkspace
    ) -> ProgressSnapshot:
        observation = workspace.observe()
        done = tuple(
            entry["task_id"]
            for entry in state["task_ledger"]
            if isinstance(entry, Mapping) and entry.get("status") == "reported_done"
        )
        receipts = tuple(
            item["digest"]
            for item in state["artifact_refs"]
            if isinstance(item, Mapping)
            and item.get("kind") == "verification_receipt"
        )
        return ProgressSnapshot(
            sha256_json(
                {
                    "head": observation.head,
                    "worktree": observation.tree_digest,
                }
            ),
            done,
            receipts,
            (),
        )

    def _recover(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        index: int,
        *,
        continue_execution: bool = True,
    ) -> int | None:
        state = store.snapshot()
        failure = state.get("failure")
        sequence = (
            list(failure.get("failure_sequence", []))
            if isinstance(failure, Mapping)
            else []
        )
        baseline_document = (
            failure.get("baseline_progress")
            if isinstance(failure, Mapping)
            else None
        )
        if baseline_document is None:
            attempts = state.get("attempts")
            if isinstance(attempts, list) and attempts:
                baseline_document = attempts[-1].get("baseline_progress")
        baseline = (
            ProgressSnapshot(
                baseline_document["git_tree_digest"],
                tuple(baseline_document["reported_done_ids"]),
                tuple(baseline_document["successful_receipt_digests"]),
                tuple(baseline_document["resolved_finding_ids"]),
            )
            if isinstance(baseline_document, Mapping)
            else self._progress(state, workspace)
        )
        current = self._progress(state, workspace)
        progress_reset = self._is_material_progress(
            baseline, current, sequence
        )
        active_sequence = [] if progress_reset else sequence
        reason = outcome.provider_code or "controller_transport_failed"
        result = outcome.result if isinstance(outcome.result, Mapping) else {}
        strategy = result.get("strategy_note")
        if not isinstance(strategy, str) or not strategy.strip():
            strategy = (
                f"controller recovery {len(active_sequence) + 1}: "
                + (
                    "start a fresh provider session"
                    if outcome.kind in _CONTAMINATED_OUTCOMES
                    else "resume the explicit healthy session"
                )
            )
        decision = self._recovery.decide(
            {
                "controller_alive": True,
                "input_digest": state["immutable_config"]["input_snapshot_digest"],
                "session_id": outcome.session_id,
                "session_health": (
                    "healthy"
                    if outcome.kind not in _CONTAMINATED_OUTCOMES
                    else "invalid"
                ),
                "resume_failed": outcome.kind == "resume_failed",
                "failure_sequence": tuple(active_sequence),
                "failure_baseline_progress": baseline,
                "reported_done_evidence": self._reported_done_evidence(state),
                "observed_tree_digests": tuple(
                    entry.get("tree_digest")
                    for entry in sequence
                    if isinstance(entry.get("tree_digest"), str)
                )
                or (baseline.git_tree_digest,),
            },
            {
                "reason_code": reason,
                "provider_code": outcome.provider_code,
                "command_identity": None,
                "candidate_head": workspace.observe().head,
                "input_digest": state["immutable_config"]["input_snapshot_digest"],
                "interruption": (
                    "stall" if outcome.kind == "stalled" else outcome.kind
                ),
                "strategy_note": strategy,
                "progress": current,
                "reported_done_evidence": self._reported_done_evidence(state),
            },
        )
        if decision.action != "recover":
            unavailable = reason == "provider_unavailable"
            state["status"] = "blocked" if unavailable else "failed"
            state["failure"] = {
                "reason_code": reason if unavailable else decision.reason_code,
                "failure_signature": decision.failure_signature,
                "failure_sequence": active_sequence,
                "strategy_digests": [
                    item["strategy_note_digest"]
                    for item in active_sequence
                    if item.get("strategy_note_digest")
                ],
            }
            store.commit(state)
            self._emit_summary(store.snapshot())
            return int(ExitCode.BLOCKED if unavailable else ExitCode.FAILED)
        active_sequence.append(
            {
                "failure_signature": decision.failure_signature,
                "strategy_note_digest": strategy_note_digest(strategy),
                "tree_digest": current.git_tree_digest,
            }
        )
        strategy_artifact = store.put_artifact(
            "strategy_note",
            {
                "run_id": state["run_id"],
                "failure_signature": decision.failure_signature,
                "strategy_note": normalize_strategy_note(strategy),
                "strategy_note_digest": strategy_note_digest(strategy),
            },
        )
        if strategy_artifact.as_dict() not in state["artifact_refs"]:
            state["artifact_refs"].append(strategy_artifact.as_dict())
        state["status"] = "recovering"
        state["failure"] = {
            "reason_code": reason,
            "failure_signature": decision.failure_signature,
            "failure_sequence": active_sequence,
            "baseline_progress": dataclasses.asdict(current),
            "required_strategy_change": decision.required_strategy_change,
            "next_session_action": decision.session_action,
            "strategy_digests": [
                item["strategy_note_digest"] for item in active_sequence
            ],
        }
        store.commit(state)
        if continue_execution:
            return self._execute_current_plan(store, workspace)
        return None

    @staticmethod
    def _reported_done_evidence(
        state: Mapping[str, object],
    ) -> dict[str, str]:
        return {
            entry["task_id"]: entry["evidence_digests"][0]
            for entry in state["task_ledger"]
            if isinstance(entry, Mapping)
            and entry.get("status") == "reported_done"
            and isinstance(entry.get("evidence_digests"), list)
            and entry["evidence_digests"]
        }

    @staticmethod
    def _is_material_progress(
        baseline: ProgressSnapshot,
        current: ProgressSnapshot,
        sequence: Sequence[Mapping[str, object]],
    ) -> bool:
        observed_trees = {
            baseline.git_tree_digest,
            *(
                item["tree_digest"]
                for item in sequence
                if isinstance(item.get("tree_digest"), str)
            ),
        }
        return (
            (
                current.git_tree_digest != baseline.git_tree_digest
                and current.git_tree_digest not in observed_trees
            )
            or bool(
                set(current.reported_done_ids)
                - set(baseline.reported_done_ids)
            )
            or bool(
                set(current.successful_receipt_digests)
                - set(baseline.successful_receipt_digests)
            )
            or bool(
                set(current.resolved_finding_ids)
                - set(baseline.resolved_finding_ids)
            )
        )

    def _finalize(
        self, store: StateStore, workspace: GitWorkspace
    ) -> int:
        while True:
            state = store.snapshot()
            candidate = workspace.require_clean_ancestor(
                state["repository"]["source_commit"]
            )
            self._require_git_contract(state, workspace)
            outcome = self._completed_review_outcome(store, candidate.head)
            if outcome is None:
                failure = state.get("failure")
                force_fresh = (
                    isinstance(failure, Mapping)
                    and failure.get("next_session_action") == "fresh_session"
                )
                existing_declaration = (
                    None
                    if force_fresh
                    else self._existing_final_set(store, candidate.head)
                )
                if force_fresh:
                    state["finalization"] = {
                        "candidate_head": candidate.head,
                        "verification_set_digest": None,
                    }
                elif existing_declaration is not None:
                    state["finalization"] = {
                        "candidate_head": candidate.head,
                        "verification_set_digest": existing_declaration,
                    }
                session_id = self._finalization_resume_session(
                    state, candidate.head
                )
                attempt_id = str(uuid.uuid4())
                state["status"] = "running"
                state["finalization"] = {
                    "candidate_head": candidate.head,
                    "verification_set_digest": (
                        state["finalization"].get("verification_set_digest")
                        if isinstance(state.get("finalization"), Mapping)
                        and state["finalization"].get("candidate_head")
                        == candidate.head
                        else None
                    ),
                }
                state["attempts"].append(
                    {
                        "attempt_id": attempt_id,
                        "mode": "finalization",
                        "plan_index": None,
                        "controller_pid": os.getpid(),
                        "completed": False,
                    }
                )
                store.commit(state)
                outcome = self._launch(
                    store,
                    workspace,
                    mode="finalization",
                    observation_head=candidate.head,
                    current_plan_index=None,
                    session_id=session_id,
                    attempt_id=attempt_id,
                )
                self._event("provider_outcome_received")
                if outcome.kind == "controller_stopped":
                    return self._pause_resumable(
                        store,
                        workspace,
                        outcome,
                        attempt_id,
                        None,
                        "finalization",
                    )
                self._checkpoint_outcome(
                    store, outcome, attempt_id, None, "finalization"
                )
            if outcome.kind != "reviewed" or not isinstance(
                outcome.result, Mapping
            ):
                if outcome.kind == "blocked":
                    return self._block(store, outcome)
                recovery_code = self._recover_finalization(
                    store, workspace, outcome, candidate.head
                )
                if recovery_code is not None:
                    return recovery_code
                continue
            result = outcome.result
            try:
                verification_receipts = self._validate_final_result(
                    store, workspace, candidate.head, result
                )
            except ValueError as error:
                return self._integrity_failure(store, str(error))
            important = [
                item
                for item in result["open_findings"]
                if item["severity"] in {"Critical", "Important"}
            ]
            if important:
                previous_head = candidate.head
                code = self._recover_review_findings(
                    store, workspace, important
                )
                if code is not None:
                    return code
                if workspace.observe().head == previous_head:
                    return self._integrity_failure(
                        store,
                        "review recovery did not produce a new candidate HEAD",
                    )
                continue
            review_receipt = store.put_artifact(
                "final_review_receipt",
                {
                    "run_id": state["run_id"],
                    "candidate_head": candidate.head,
                    "review_session_id": outcome.session_id,
                    **_plain_json(result),
                },
            )
            handoff = store.put_artifact(
                "branch_handoff",
                {
                    "run_id": state["run_id"],
                    "status": "ready_for_integration",
                    "branch": state["repository"]["branch"],
                    "worktree": state["repository"]["worktree"],
                    "starting_commit": state["repository"]["source_commit"],
                    "candidate_head": candidate.head,
                    "runner_identity": dict(state["runner_runtime"]),
                    "provider_identity": {
                        "provider": state["provider"],
                        "model": state["immutable_config"]["model"],
                    },
                    "plan_implementations": self._plan_implementation_summaries(
                        store, state
                    ),
                    "non_blocking_observations": [
                        _plain_json(item)
                        for item in result["open_findings"]
                        if item["severity"] == "Minor"
                    ],
                    "verification_set_digest": result[
                        "verification_set_digest"
                    ],
                    "review_head": result["review_head"],
                    "review_receipt": review_receipt.as_dict(),
                    "verification_receipts": verification_receipts,
                    "integration": "not_observed",
                },
            )
            state = store.snapshot()
            if review_receipt.as_dict() not in state["artifact_refs"]:
                state["artifact_refs"].append(review_receipt.as_dict())
            if handoff.as_dict() not in state["artifact_refs"]:
                state["artifact_refs"].append(handoff.as_dict())
            state["finalization"] = {
                "candidate_head": candidate.head,
                "verification_set_digest": result[
                    "verification_set_digest"
                ],
                "review_head": result["review_head"],
                "review_session_id": outcome.session_id,
            }
            state["status"] = "ready_for_integration"
            store.commit(state)
            self._emit_summary(store.snapshot())
            return int(ExitCode.READY)

    @staticmethod
    def _completed_review_outcome(
        store: StateStore, candidate_head: str
    ) -> ProviderOutcome | None:
        state = store.snapshot()
        for attempt in reversed(state["attempts"]):
            if (
                not isinstance(attempt, Mapping)
                or attempt.get("mode") != "finalization"
                or attempt.get("completed") is not True
                or attempt.get("outcome") != "reviewed"
                or not isinstance(attempt.get("result_artifact"), Mapping)
            ):
                continue
            result = _artifact_payload(store, attempt["result_artifact"])
            if (
                not isinstance(result, Mapping)
                or result.get("review_head") != candidate_head
            ):
                continue
            session_id = attempt.get("session_id")
            return ProviderOutcome(
                "reviewed",
                0,
                session_id if isinstance(session_id, str) else None,
                result,
                attempt.get("provider_code"),
                {},
                (),
                "",
            )
        return None

    @staticmethod
    def _plan_implementation_summaries(
        store: StateStore, state: Mapping[str, object]
    ) -> list[dict[str, object]]:
        handoffs: dict[int, tuple[Mapping[str, object], Mapping[str, object]]] = {}
        for reference in state["artifact_refs"]:
            if (
                not isinstance(reference, Mapping)
                or reference.get("kind") != "plan_handoff"
            ):
                continue
            payload = _artifact_payload(store, reference)
            index = payload.get("plan_index") if isinstance(payload, Mapping) else None
            if isinstance(index, int) and not isinstance(index, bool):
                handoffs[index] = (reference, payload)
        summaries: list[dict[str, object]] = []
        for index, plan in enumerate(state["plans"]):
            if index not in handoffs:
                raise ValueError("implemented plan handoff is missing")
            reference, payload = handoffs[index]
            summaries.append(
                {
                    "plan_index": index,
                    "plan_id": plan["plan_id"],
                    "status": plan["status"],
                    "snapshot_path": plan["snapshot_path"],
                    "sha256": plan["sha256"],
                    "head_commit": payload["head_commit"],
                    "summary": payload["summary"],
                    "handoff": dict(reference),
                }
            )
        return summaries

    @staticmethod
    def _existing_final_set(
        store: StateStore, candidate_head: str
    ) -> str | None:
        for reference in reversed(store.snapshot()["artifact_refs"]):
            if (
                not isinstance(reference, Mapping)
                or reference.get("kind") != "final_verification_set"
            ):
                continue
            payload = _artifact_payload(store, reference)
            if (
                isinstance(payload, Mapping)
                and payload.get("candidate_head") == candidate_head
                and isinstance(reference.get("digest"), str)
            ):
                return reference["digest"]
        return None

    def _finalization_resume_session(
        self, state: Mapping[str, object], candidate_head: str
    ) -> str | None:
        finalization = state.get("finalization")
        failure = state.get("failure")
        if (
            not isinstance(finalization, Mapping)
            or finalization.get("candidate_head") != candidate_head
            or (
                isinstance(failure, Mapping)
                and failure.get("next_session_action") == "fresh_session"
            )
        ):
            return None
        declaration = finalization.get("verification_set_digest")
        for session in reversed(state["sessions"]):
            if (
                isinstance(session, Mapping)
                and session.get("mode") == "finalization"
                and session.get("health") == "healthy"
                and session.get("candidate_head") == candidate_head
                and session.get("verification_set_digest") == declaration
                and isinstance(session.get("session_id"), str)
            ):
                return session["session_id"]
        return None

    def _recover_finalization(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        candidate_head: str,
    ) -> int | None:
        state = store.snapshot()
        self._require_git_contract(state, workspace)
        if workspace.observe().head != candidate_head:
            return self._integrity_failure(
                store, "finalization changed the candidate HEAD"
            )
        failure = state.get("failure")
        sequence = (
            list(failure.get("failure_sequence", []))
            if isinstance(failure, Mapping)
            else []
        )
        baseline_document = (
            failure.get("baseline_progress")
            if isinstance(failure, Mapping)
            else None
        )
        baseline = (
            ProgressSnapshot(
                baseline_document["git_tree_digest"],
                tuple(baseline_document["reported_done_ids"]),
                tuple(baseline_document["successful_receipt_digests"]),
                tuple(baseline_document["resolved_finding_ids"]),
            )
            if isinstance(baseline_document, Mapping)
            else self._progress(state, workspace)
        )
        current = self._progress(state, workspace)
        progress_reset = self._is_material_progress(
            baseline, current, sequence
        )
        active_sequence = [] if progress_reset else sequence
        reason = outcome.provider_code or "controller_transport_failed"
        result = outcome.result if isinstance(outcome.result, Mapping) else {}
        strategy = result.get("strategy_note")
        if not isinstance(strategy, str) or not strategy.strip():
            strategy = (
                f"finalization recovery {len(active_sequence) + 1}: "
                + (
                    "start a fresh finalization session"
                    if outcome.kind in _CONTAMINATED_OUTCOMES
                    else "resume the explicit healthy finalization session"
                )
            )
        decision = self._recovery.decide(
            {
                "controller_alive": True,
                "input_digest": state["immutable_config"][
                    "input_snapshot_digest"
                ],
                "session_id": outcome.session_id,
                "session_health": (
                    "healthy"
                    if outcome.kind not in _CONTAMINATED_OUTCOMES
                    else "invalid"
                ),
                "resume_failed": outcome.kind == "resume_failed",
                "failure_sequence": tuple(active_sequence),
                "failure_baseline_progress": baseline,
                "reported_done_evidence": self._reported_done_evidence(state),
                "observed_tree_digests": tuple(
                    item.get("tree_digest")
                    for item in sequence
                    if isinstance(item.get("tree_digest"), str)
                )
                or (baseline.git_tree_digest,),
            },
            {
                "reason_code": reason,
                "provider_code": outcome.provider_code,
                "command_identity": None,
                "candidate_head": candidate_head,
                "input_digest": state["immutable_config"][
                    "input_snapshot_digest"
                ],
                "interruption": (
                    "stall" if outcome.kind == "stalled" else outcome.kind
                ),
                "strategy_note": strategy,
                "progress": current,
                "reported_done_evidence": self._reported_done_evidence(state),
            },
        )
        if decision.action != "recover":
            unavailable = reason == "provider_unavailable"
            state["status"] = "blocked" if unavailable else "failed"
            state["failure"] = {
                "reason_code": reason if unavailable else decision.reason_code,
                "failure_signature": decision.failure_signature,
                "failure_sequence": active_sequence,
                "strategy_digests": [
                    item["strategy_note_digest"]
                    for item in active_sequence
                    if item.get("strategy_note_digest")
                ],
            }
            store.commit(state)
            self._emit_summary(store.snapshot())
            return int(ExitCode.BLOCKED if unavailable else ExitCode.FAILED)
        active_sequence.append(
            {
                "failure_signature": decision.failure_signature,
                "strategy_note_digest": strategy_note_digest(strategy),
                "tree_digest": current.git_tree_digest,
            }
        )
        strategy_artifact = store.put_artifact(
            "strategy_note",
            {
                "run_id": state["run_id"],
                "failure_signature": decision.failure_signature,
                "strategy_note": normalize_strategy_note(strategy),
                "strategy_note_digest": strategy_note_digest(strategy),
            },
        )
        if strategy_artifact.as_dict() not in state["artifact_refs"]:
            state["artifact_refs"].append(strategy_artifact.as_dict())
        state["status"] = "recovering"
        state["failure"] = {
            "reason_code": reason,
            "failure_signature": decision.failure_signature,
            "failure_sequence": active_sequence,
            "baseline_progress": dataclasses.asdict(current),
            "required_strategy_change": decision.required_strategy_change,
            "next_session_action": decision.session_action,
            "strategy_digests": [
                item["strategy_note_digest"] for item in active_sequence
            ],
        }
        store.commit(state)
        return None

    def _validate_final_result(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        candidate_head: str,
        result: Mapping[str, object],
    ) -> list[dict[str, str]]:
        state = store.snapshot()
        ledger = self._validated_task_ledger(state["task_ledger"])
        self._require_all_tasks_reported_done(ledger)
        if result.get("status") != "reviewed":
            raise ValueError("review status is invalid")
        if result.get("review_head") != candidate_head:
            raise ValueError("review HEAD does not match candidate HEAD")
        digest = result.get("verification_set_digest")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("verification set digest is invalid")
        findings = result.get("open_findings")
        obligations = result.get("open_obligation_ids")
        if not _json_array(findings) or not _json_array(obligations):
            raise ValueError("review findings or obligations are invalid")
        if obligations:
            raise ValueError("final obligations remain open")
        for finding in findings:
            if (
                not isinstance(finding, Mapping)
                or set(finding) != {"id", "severity", "summary", "evidence"}
                or finding.get("severity")
                not in {"Critical", "Important", "Minor"}
            ):
                raise ValueError("review finding is invalid")
        references = [
            item
            for item in state["artifact_refs"]
            if isinstance(item, Mapping)
            and item.get("kind") == "final_verification_set"
            and item.get("digest") == digest
        ]
        if len(references) != 1:
            raise ValueError("final verification declaration is missing")
        declaration = _artifact_payload(store, references[0])
        if (
            not isinstance(declaration, Mapping)
            or declaration.get("candidate_head") != candidate_head
        ):
            raise ValueError("final verification declaration HEAD mismatch")
        evidence = EvidenceStore(store, workspace, self._environment)
        receipt_refs: list[dict[str, str]] = []
        if declaration.get("kind") == "commands":
            commands = declaration.get("commands")
            if not isinstance(commands, list) or not commands:
                raise ValueError("final verification commands are missing")
            for index in range(len(commands)):
                command = evidence.load_final_command(digest, index)
                identity = evidence.identity_digest(
                    command, candidate_head=candidate_head
                )
                receipt = evidence.reusable_success(identity)
                if receipt is None or receipt.outcome != "success":
                    raise ValueError("successful final verification receipt is missing")
                receipt_refs.append(receipt.artifact.as_dict())
            if result.get("no_applicable_verification_approved") is not False:
                raise ValueError("verification approval flag is inconsistent")
        elif declaration.get("kind") == "no_applicable_verification":
            if (
                not isinstance(declaration.get("rationale"), str)
                or not declaration["rationale"].strip()
                or result.get("no_applicable_verification_approved") is not True
            ):
                raise ValueError(
                    "no-applicable verification lacks review approval"
                )
        else:
            raise ValueError("final verification declaration is invalid")
        self._require_git_contract(state, workspace)
        if workspace.observe().head != candidate_head:
            raise ValueError("candidate HEAD changed during finalization")
        return receipt_refs

    def _recover_review_findings(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        findings: Sequence[Mapping[str, object]],
        *,
        initialize: bool = True,
    ) -> int | None:
        if initialize:
            state = store.snapshot()
            finalization = dict(state.get("finalization") or {})
            finalization["review_findings"] = [
                _plain_json(item) for item in findings
            ]
            finalization["pending_mode"] = "final_review_fix"
            state["finalization"] = finalization
            state["status"] = "recovering"
            state["failure"] = {
                "reason_code": "review_failed",
                "required_strategy_change": True,
                "next_session_action": "fresh_session",
                "pending_mode": "final_review_fix",
                "review_findings": [_plain_json(item) for item in findings],
            }
            store.commit(state)
        index = len(store.snapshot()["plans"]) - 1
        while True:
            state = store.snapshot()
            candidate_head = workspace.observe().head
            session_id = self._review_fix_resume_session(state, candidate_head)
            attempt_id = str(uuid.uuid4())
            state["attempts"].append(
                {
                    "attempt_id": attempt_id,
                    "mode": "final_review_fix",
                    "plan_index": index,
                    "controller_pid": os.getpid(),
                    "completed": False,
                    "review_recovery": True,
                    "baseline_progress": dataclasses.asdict(
                        self._progress(state, workspace)
                    ),
                }
            )
            store.commit(state)
            outcome = self._launch(
                store,
                workspace,
                mode="final_review_fix",
                observation_head=candidate_head,
                current_plan_index=index,
                session_id=session_id,
                attempt_id=attempt_id,
            )
            self._event("provider_outcome_received")
            if outcome.kind == "controller_stopped":
                return self._pause_resumable(
                    store,
                    workspace,
                    outcome,
                    attempt_id,
                    index,
                    "final_review_fix",
                )
            self._checkpoint_outcome(
                store, outcome, attempt_id, index, "final_review_fix"
            )
            if outcome.kind == "blocked":
                return self._block(store, outcome)
            if outcome.kind != "implemented":
                code = self._recover(
                    store,
                    workspace,
                    outcome,
                    index,
                    continue_execution=False,
                )
                if code is not None:
                    return code
                continue
            result = outcome.result
            try:
                review_ledger = self._validated_task_ledger(
                    result.get("task_ledger")
                    if isinstance(result, Mapping)
                    else None
                )
                self._require_all_tasks_reported_done(review_ledger)
            except ValueError as error:
                return self._integrity_failure(store, str(error))
            current_state = store.snapshot()
            observation = workspace.require_clean_ancestor(
                current_state["repository"]["source_commit"]
            )
            if (
                not isinstance(result, Mapping)
                or result.get("head_commit") != observation.head
                or not _json_array(result.get("open_obligation_ids"))
                or result.get("open_obligation_ids")
            ):
                return self._integrity_failure(
                    store, "review recovery result is invalid"
                )
            state = store.snapshot()
            state["failure"] = None
            state["status"] = "resumable"
            state["finalization"] = None
            store.commit(state)
            return None

    @staticmethod
    def _review_fix_resume_session(
        state: Mapping[str, object], candidate_head: str
    ) -> str | None:
        failure = state.get("failure")
        if (
            isinstance(failure, Mapping)
            and failure.get("next_session_action") == "fresh_session"
        ):
            return None
        for session in reversed(state.get("sessions", [])):
            if (
                isinstance(session, Mapping)
                and session.get("mode") == "final_review_fix"
                and session.get("health") == "healthy"
                and session.get("candidate_head") == candidate_head
                and isinstance(session.get("session_id"), str)
            ):
                return session["session_id"]
        return None

    def _integrity_failure(self, store: StateStore, detail: object) -> int:
        self._fail_closed(store, "state_integrity_failed", detail)
        return int(ExitCode.INTEGRITY)

    def _fail_closed(
        self, store: StateStore, reason_code: str, detail: object
    ) -> None:
        try:
            state = store.snapshot()
            state["status"] = "failed"
            state["failure"] = {
                "reason_code": reason_code,
                "detail": str(detail)[:512],
            }
            store.commit(state)
            self._emit_summary(store.snapshot())
        except (OSError, ValueError):
            self._emit_error(reason_code, detail)

    def _emit_summary(self, state: Mapping[str, object]) -> None:
        self._output(
            json.dumps(
                {
                    "run_id": state["run_id"],
                    "status": state["status"],
                    "integration": state["integration"],
                    "current_plan_index": state["current_plan_index"],
                    "plan_count": len(state["plans"]),
                },
                sort_keys=True,
            )
        )

    def _emit_error(self, reason_code: str, detail: object) -> None:
        self._output(
            json.dumps(
                {
                    "status": "failed",
                    "reason_code": reason_code,
                    "detail": str(detail).replace("\n", " ")[:512],
                },
                sort_keys=True,
            )
        )
