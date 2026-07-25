from __future__ import annotations

import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    CONTRACT_VERSION,
    FORMAT_VERSION,
    ExitCode,
    canonical_json,
    require_digest,
    require_full_sha,
    sha256_json,
)
from .evidence import EvidenceStore
from .git_ops import GitWorkspace, WorktreeObservation
from .helper import HelperDescriptor, HelperServer
from .provider import (
    DENY_TOOLS,
    ClaudeAdapter,
    ProviderOutcome,
    ProviderRequest,
)
from .recovery import (
    ActivityLease,
    ProgressSnapshot,
    RecoveryPolicy,
    strategy_note_digest,
)
from .runtime import (
    RuntimeIdentity,
    RuntimeUnavailable,
    require_compatible_runtime,
)
from .storage import (
    RunLock,
    StateStore,
    atomic_private_write,
)


IMPLEMENTATION_PROMPT = """Read the execution packet and immutable source documents.
Use Superpowers to implement CURRENT_PLAN only. Superpowers owns engineering
judgment, TDD, internal review, and progress tracking. The controller owns only
immutable inputs, Git identity, bounded recovery, exact verification, and the
handoff. Use the supplied helper for handoff verification. Do not merge, push,
deploy, or leave WORKTREE. Return only the enforced structured result."""

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
_RUN_ID_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789"


@dataclass(frozen=True)
class RuntimePaths:
    state_home: Path
    worktree_home: Path
    runner_script: Path
    skill_root: Path

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            value = Path(getattr(self, field.name))
            if not value.is_absolute():
                raise ValueError(f"{field.name} must be absolute")
            object.__setattr__(self, field.name, value)


class _SignalGate:
    def __init__(self) -> None:
        self._requested = False
        self._previous: dict[int, Any] = {}

    def requested(self) -> bool:
        return self._requested

    def __enter__(self) -> "_SignalGate":
        for number in (signal.SIGINT, signal.SIGTERM):
            self._previous[number] = signal.getsignal(number)
            signal.signal(number, self._stop)
        return self

    def __exit__(
        self,
        _type: object,
        _value: object,
        _traceback: object,
    ) -> None:
        for number, handler in self._previous.items():
            signal.signal(number, handler)
        self._previous.clear()

    def _stop(self, _number: int, _frame: object) -> None:
        self._requested = True


def _git(workspace: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise ValueError(
            f"git {' '.join(arguments)} failed: {detail or 'unknown error'}"
        )
    return process.stdout.strip()


def _source_head(workspace: Path) -> str:
    return require_full_sha(_git(workspace, "rev-parse", "HEAD"))


def _common_directory(workspace: Path) -> Path:
    raw = _git(workspace, "rev-parse", "--git-common-dir")
    candidate = Path(raw)
    return (
        candidate
        if candidate.is_absolute()
        else workspace / candidate
    ).resolve(strict=True)


def _protected_refs(
    workspace: Path,
    assigned_branch: str,
) -> dict[str, str]:
    assigned = f"refs/heads/{assigned_branch}"
    result: dict[str, str] = {}
    for line in _git(
        workspace,
        "for-each-ref",
        "--format=%(refname)\t%(objectname)",
    ).splitlines():
        name, separator, sha = line.partition("\t")
        if separator and name != assigned:
            result[name] = require_full_sha(sha)
    return result


def _input_fingerprint(
    specs: Sequence[Path],
    plans: Sequence[Path],
) -> str:
    documents = []
    for role, paths in (("spec", specs), ("plan", plans)):
        for position, path in enumerate(paths):
            source = Path(path)
            payload = source.read_bytes()
            payload.decode("utf-8")
            documents.append(
                {
                    "role": role,
                    "position": position,
                    "path": str(source),
                    "content_digest": sha256_json(
                        {"utf8": payload.decode("utf-8")}
                    ),
                }
            )
    return sha256_json(documents)


def _snapshot_fingerprint(state: Mapping[str, object]) -> str:
    documents = []
    inputs = state.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("input snapshots are unavailable")
    for record in inputs:
        if not isinstance(record, Mapping):
            raise ValueError("input snapshot record is invalid")
        path = Path(str(record.get("snapshot_path", "")))
        payload = path.read_bytes()
        payload.decode("utf-8")
        documents.append(
            {
                "role": record.get("role"),
                "position": record.get("input_order"),
                "path": record.get("source_path"),
                "content_digest": sha256_json(
                    {"utf8": payload.decode("utf-8")}
                ),
            }
        )
    return sha256_json(documents)


def _runtime_document(identity: RuntimeIdentity) -> dict[str, object]:
    return dataclasses.asdict(identity)


def _slug(path: Path) -> str:
    lowered = path.stem.lower()
    characters = [
        character if character in _RUN_ID_SAFE else "-"
        for character in lowered
    ]
    value = "".join(characters).strip("-")[:40]
    return value or "plan"


def _artifact_payload(
    store: StateStore,
    reference: Mapping[str, object],
) -> dict[str, object]:
    value = json.loads(
        store.referenced_artifact(reference).read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("artifact payload is invalid")
    return value


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


class PlanRunner:
    def __init__(
        self,
        paths: RuntimePaths,
        *,
        runtime_checker: Callable[[], RuntimeIdentity] | None = None,
        adapter_factory: Callable[..., object] | None = None,
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
        self._environment = dict(
            os.environ if environment is None else environment
        )
        self._clock = clock
        self._event_hook = event_hook
        self._recovery = RecoveryPolicy()
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
        store: StateStore | None = None
        try:
            runtime = self._runtime()
            if not specs or not plans:
                raise ValueError("at least one spec and one plan are required")
            if (
                isinstance(stall_seconds, bool)
                or not isinstance(stall_seconds, (int, float))
                or stall_seconds <= 0
            ):
                raise ValueError("stall-seconds must be positive")
            ordered_specs = tuple(Path(path) for path in specs)
            ordered_plans = tuple(Path(path) for path in plans)
            source = Path(workspace)
            if (
                not source.is_absolute()
                or any(
                    not path.is_absolute()
                    for path in (*ordered_specs, *ordered_plans)
                )
            ):
                raise ValueError("workspace and inputs must be absolute")
            source = source.resolve(strict=True)
            starting_commit = _source_head(source)
            common = _common_directory(source)
            input_digest = _input_fingerprint(
                ordered_specs,
                ordered_plans,
            )
            intent_digest = sha256_json(
                {
                    "provider": "claude",
                    "git_common_dir": str(common),
                    "starting_commit": starting_commit,
                    "input_digest": input_digest,
                }
            )
            lock_home = self.paths.state_home.with_name(
                f".{self.paths.state_home.name}-intent-locks"
            )
            lock_home.mkdir(mode=0o700, parents=True, exist_ok=True)
            with RunLock(lock_home / f"{intent_digest}.lock"):
                match = self._admitted_run(lock_home, intent_digest)
                if match is not None:
                    return self._report_existing(match)
                run_id = f"{_slug(ordered_plans[0])}-{uuid.uuid4()}"
                branch = f"claude-plan/{run_id}"
                worktree = self.paths.worktree_home / run_id
                root = self.paths.state_home / run_id
                self._write_admission(lock_home, intent_digest, run_id)
                store = StateStore.create(
                    root=root,
                    provider="claude",
                    run_id=run_id,
                    source_repository=source,
                    source_commit=starting_commit,
                    worktree=worktree,
                    branch=branch,
                    specs=ordered_specs,
                    plans=ordered_plans,
                    immutable_config={
                        "stall_seconds": float(stall_seconds),
                        "model": model,
                        "permission_mode": "bypassPermissions",
                        "deny_tools_digest": sha256_json(list(DENY_TOOLS)),
                        "input_snapshot_digest": input_digest,
                        "execution_intent_digest": intent_digest,
                        "git_common_dir": str(common),
                        "protected_refs": _protected_refs(source, branch),
                    },
                    runner_runtime=_runtime_document(runtime),
                )
                GitWorkspace.create(source, worktree, branch)
        except RuntimeUnavailable as error:
            return self._runtime_blocked(str(error))
        except (OSError, TypeError, ValueError) as error:
            if store is not None:
                self._mark_failure(
                    store,
                    "state_integrity_failed",
                    str(error),
                )
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
        try:
            root = self.paths.state_home / run_id
            if not root.exists():
                raise FileNotFoundError(f"unknown run: {run_id}")
            store = StateStore.open(root)
            state = store.snapshot()
            if (
                state.get("format_version"),
                state.get("contract_version"),
            ) != (FORMAT_VERSION, CONTRACT_VERSION):
                self._emit_error(
                    "legacy_contract_requires_v1_runner",
                    "version 1 state is inspect-only",
                )
                return int(ExitCode.INVALID)
            self._runtime()
            status = state["status"]
            if status == "ready_for_integration":
                self._emit_summary(state)
                return int(ExitCode.READY)
            if status == "blocked":
                if not retry_blocked:
                    self._emit_summary(state)
                    return int(ExitCode.BLOCKED)
                state["status"] = "resumable"
                state["failure"] = None
                store.commit(state)
            elif retry_blocked:
                raise ValueError("--retry-blocked requires a blocked run")
            if status == "failed":
                if not retry_failed:
                    self._emit_summary(state)
                    return int(ExitCode.FAILED)
                if not isinstance(strategy_note, str) or not strategy_note.strip():
                    raise ValueError(
                        "--retry-failed requires a nonempty --strategy-note"
                    )
                digest = strategy_note_digest(strategy_note)
                prior = (
                    state["failure"].get("strategy_digests", [])
                    if isinstance(state.get("failure"), Mapping)
                    else []
                )
                if digest in prior:
                    raise ValueError("strategy note duplicates a prior strategy")
                state["status"] = "resumable"
                state["failure"] = {
                    "reason_code": "operator_retry",
                    "failure_sequence": [],
                    "next_session_action": "fresh_root",
                    "strategy_digests": [*prior, digest],
                }
                store.commit(state)
            elif retry_failed:
                raise ValueError("--retry-failed requires a failed run")
            return self._execute(store)
        except RuntimeUnavailable as error:
            return self._runtime_blocked(str(error))
        except FileNotFoundError as error:
            self._emit_error("unknown_run", error)
            return int(ExitCode.INVALID)
        except (OSError, TypeError, ValueError) as error:
            self._emit_error("invalid_state", error)
            return int(ExitCode.INTEGRITY)

    def inspect(self, run_id: str) -> int:
        try:
            root = self.paths.state_home / run_id
            if not root.exists():
                raise FileNotFoundError(f"unknown run: {run_id}")
            self._emit_summary(StateStore.open(root).snapshot())
            return int(ExitCode.READY)
        except FileNotFoundError as error:
            self._emit_error("unknown_run", error)
            return int(ExitCode.INVALID)
        except (OSError, ValueError) as error:
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)

    def _runtime(self) -> RuntimeIdentity:
        if self._runtime_checker is None:
            return require_compatible_runtime()
        return require_compatible_runtime(self._runtime_checker())

    def _runtime_blocked(self, reason: str) -> int:
        reason_code = (
            reason
            if reason in {"runtime_missing", "runtime_incompatible"}
            else "runtime_incompatible"
        )
        self._output(
            json.dumps(
                {
                    "status": "blocked",
                    "reason_code": reason_code,
                    "detail": "uv-managed CPython 3.13 is unavailable",
                },
                sort_keys=True,
            )
        )
        return int(ExitCode.BLOCKED)

    def _execute(self, store: StateStore) -> int:
        try:
            with self._signals, RunLock(store.root / "run.lock"):
                state = store.snapshot()
                if (
                    _snapshot_fingerprint(state)
                    != state["immutable_config"]["input_snapshot_digest"]
                ):
                    raise ValueError("input snapshot digest changed")
                repository = state["repository"]
                workspace = GitWorkspace.open(
                    Path(repository["source_repository"]),
                    Path(repository["worktree"]),
                    repository["branch"],
                )
                self._require_git(state, workspace)
                reconciled = self._reconcile_controller(store, workspace)
                if reconciled is not None:
                    return reconciled
                state = store.snapshot()
                failure = (
                    state.get("failure")
                    if isinstance(state.get("failure"), Mapping)
                    else {}
                )
                recorded_session = (
                    failure.get("session_id")
                    if failure.get("next_session_action") == "resume_root"
                    and isinstance(failure.get("session_id"), str)
                    else None
                )
                while (
                    store.snapshot()["current_plan_index"]
                    < len(store.snapshot()["plans"])
                ):
                    result = self._execute_plan(
                        store,
                        workspace,
                        session_id=recorded_session,
                        resume_session=recorded_session is not None,
                    )
                    recorded_session = None
                    if result is not None:
                        return result
                state = store.snapshot()
                state["status"] = "ready_for_integration"
                state["failure"] = None
                store.commit(state)
                self._emit_summary(store.snapshot())
                return int(ExitCode.READY)
        except ValueError as error:
            self._mark_failure(
                store,
                "state_integrity_failed",
                str(error),
            )
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)
        except RuntimeError as error:
            self._mark_failure(
                store,
                "controller_transport_failed",
                str(error),
            )
            self._emit_error("controller_transport_failed", error)
            return int(ExitCode.INTERNAL)
        except Exception as error:
            self._mark_failure(store, "internal_error", str(error))
            self._emit_error("internal_error", error)
            return int(ExitCode.INTERNAL)

    def _require_git(
        self,
        state: Mapping[str, object],
        workspace: GitWorkspace,
    ) -> WorktreeObservation:
        config = state["immutable_config"]
        if str(workspace._common_dir) != config["git_common_dir"]:
            raise ValueError("Git common directory drift detected")
        if workspace.protected_refs() != config["protected_refs"]:
            raise ValueError("protected ref mutation detected")
        observed = workspace.require_identity()
        _git(
            workspace.worktree,
            "merge-base",
            "--is-ancestor",
            state["repository"]["source_commit"],
            observed.head,
        )
        if observed.clean:
            return observed
        failure = state.get("failure")
        sealed = (
            failure.get("partial_worktree")
            if isinstance(failure, Mapping)
            else None
        )
        expected = {
            "version": 1,
            "plan_index": state.get("current_plan_index"),
            **dataclasses.asdict(observed),
        }
        if sealed != expected:
            raise ValueError("dirty worktree identity is not sealed")
        return observed

    def _execute_plan(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        *,
        session_id: str | None = None,
        resume_session: bool = False,
    ) -> int | None:
        state = store.snapshot()
        index = state["current_plan_index"]
        plan = state["plans"][index]
        observed = self._require_git(state, workspace)
        plan["status"] = "running"
        state["status"] = "running"
        attempt_id = str(uuid.uuid4())
        state["attempts"].append(
            {
                "attempt_id": attempt_id,
                "mode": "implementation",
                "plan_index": index,
                "completed": False,
                "session_action": (
                    "resume_root" if resume_session else "fresh_root"
                ),
            }
        )
        store.commit(state)
        root_session = session_id or str(uuid.uuid4())
        outcome = self._launch(
            store,
            workspace,
            index=index,
            candidate_head=observed.head,
            session_id=root_session,
            resume_session=resume_session,
            attempt_id=attempt_id,
        )
        self._complete_attempt(store, attempt_id, outcome)
        if outcome.kind == "controller_stopped":
            return self._pause(
                store,
                workspace,
                outcome,
                reconciled_attempt_id=attempt_id,
            )
        if outcome.kind == "blocked":
            return self._block(
                store,
                outcome,
                reconciled_attempt_id=attempt_id,
            )
        if outcome.kind == "implemented":
            try:
                self._accept_implemented(
                    store,
                    workspace,
                    index,
                    outcome,
                )
            except ValueError as error:
                self._mark_failure(
                    store,
                    "state_integrity_failed",
                    str(error),
                )
                return int(ExitCode.INTEGRITY)
            return None
        return self._recover(
            store,
            workspace,
            index,
            outcome,
            reconciled_attempt_id=attempt_id,
        )

    def _launch(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        *,
        index: int,
        candidate_head: str,
        session_id: str,
        resume_session: bool,
        attempt_id: str,
    ) -> ProviderOutcome:
        state = store.snapshot()
        evidence = EvidenceStore(store, workspace, self._environment)
        lease = ActivityLease(
            state["immutable_config"]["stall_seconds"],
            self._clock(),
        )
        client_argv = (
            str(Path(sys.executable).resolve()),
            str(self.paths.runner_script.resolve()),
            "_helper",
        )
        with HelperServer(
            run_id=state["run_id"],
            worktree=workspace.worktree,
            evidence_store=evidence,
            client_argv=client_argv,
            state_store=store,
            on_command_started=lease.cover_command_until,
            on_command_finished=lease.command_finished,
        ) as helper:
            packet = self._packet(
                store.snapshot(),
                index,
                candidate_head,
                helper.descriptor,
            )
            request = ProviderRequest(
                worktree=workspace.worktree,
                prompt=(
                    IMPLEMENTATION_PROMPT
                    + "\nEXECUTION_PACKET="
                    + canonical_json(packet).decode("utf-8")
                ),
                output_schema=json.loads(
                    (
                        self.paths.skill_root
                        / "templates"
                        / "plan-result.schema.json"
                    ).read_text(encoding="utf-8")
                ),
                session_id=session_id,
                resume=resume_session,
                model=state["immutable_config"].get("model"),
            )
            if self._signals.requested():
                return ProviderOutcome(
                    "controller_stopped",
                    None,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            adapter = self._adapter(
                state["run_id"],
                helper.descriptor,
                workspace,
            )
            return adapter.launch(
                request,
                lease,
                on_session_id=lambda captured: self._record_session(
                    store,
                    attempt_id=attempt_id,
                    plan_index=index,
                    session_id=captured,
                    candidate_head=candidate_head,
                ),
            )

    def _packet(
        self,
        state: Mapping[str, object],
        index: int,
        current_head: str,
        helper: HelperDescriptor,
    ) -> dict[str, object]:
        specifications = [
            {
                "snapshot_path": record["snapshot_path"],
                "sha256": record["sha256"],
            }
            for record in state["inputs"]
            if record["role"] == "spec"
        ]
        plan = state["plans"][index]
        prior_handoffs = [
            prior["handoff_digest"]
            for prior in state["plans"][:index]
            if prior.get("handoff_digest") is not None
        ]
        prior_sets = []
        for digest in prior_handoffs:
            reference = next(
                reference
                for reference in state["artifact_refs"]
                if reference["kind"] == "plan_handoff"
                and reference["digest"] == digest
            )
            handoff = _artifact_payload(
                StateStore.open(
                    self.paths.state_home / state["run_id"]
                ),
                reference,
            )
            prior_sets.append(handoff["verification_set_digest"])
        is_final = index == len(state["plans"]) - 1
        return {
            "packet_version": 2,
            "mode": "implementation",
            "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"],
            "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"],
            "current_head": current_head,
            "specifications": specifications,
            "current_plan": {
                "index": index,
                "total": len(state["plans"]),
                "snapshot_path": plan["snapshot_path"],
                "sha256": plan["sha256"],
            },
            "implemented_plan_handoffs": prior_handoffs,
            "prior_verification_sets": prior_sets,
            "is_final_plan": is_final,
            "final_review_requirements": (
                [
                    {
                        "snapshot_path": record["snapshot_path"],
                        "sha256": record["sha256"],
                    }
                    for record in state["inputs"]
                ]
                if is_final
                else None
            ),
            "checkpoint_revision": state["revision"],
            "recovery_context": self._recovery_context(
                state,
                current_head=current_head,
            ),
            "helper": {
                "protocol_version": helper.protocol_version,
                "socket_path": str(helper.socket_path),
                "nonce": helper.nonce,
                "client_argv": list(helper.client_argv),
            },
            "integration_policy": "keep",
        }

    def _accept_implemented(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        index: int,
        outcome: ProviderOutcome,
    ) -> None:
        result = self._validated_plan_result(outcome.result)
        if result["status"] != "implemented":
            raise ValueError("implemented transport returned blocked result")
        state = store.snapshot()
        observed = workspace.require_clean_ancestor(
            state["repository"]["source_commit"]
        )
        if workspace.protected_refs() != state["immutable_config"]["protected_refs"]:
            raise ValueError("protected refs changed during provider handoff")
        if result["head_commit"] != observed.head:
            raise ValueError("provider handoff HEAD does not match clean worktree")
        digest = require_digest(result["verification_set_digest"])
        artifact_kind = (
            "run_verification_set"
            if index == len(state["plans"]) - 1
            else "plan_verification_set"
        )
        evidence = EvidenceStore(store, workspace, self._environment)
        evidence.require_successful_verification_set(
            digest,
            candidate_head=observed.head,
            artifact_kind=artifact_kind,
            plan_index=index,
        )
        result_artifact = store.put_artifact(
            "provider_result",
            dict(result),
        )
        handoff = store.put_artifact(
            "plan_handoff",
            {
                "plan_index": index,
                "plan_id": state["plans"][index]["plan_id"],
                "plan_sha256": state["plans"][index]["sha256"],
                "head_commit": observed.head,
                "starting_commit": state["repository"]["source_commit"],
                "verification_artifact_kind": artifact_kind,
                "verification_set_digest": digest,
                "summary": result["summary"],
            },
        )
        state = store.snapshot()
        for artifact in (result_artifact, handoff):
            if artifact.as_dict() not in state["artifact_refs"]:
                state["artifact_refs"].append(artifact.as_dict())
        state["plans"][index]["status"] = "implemented"
        state["plans"][index]["handoff_digest"] = handoff.digest
        state["current_plan_index"] = index + 1
        state["status"] = "resumable"
        state["failure"] = None
        store.commit(state)

    @staticmethod
    def _validated_plan_result(value: object) -> dict[str, object]:
        required = {
            "status",
            "head_commit",
            "summary",
            "verification_set_digest",
            "blocker",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise ValueError("plan result shape is invalid")
        result = dict(value)
        status = result["status"]
        if status not in {"implemented", "blocked"}:
            raise ValueError("plan result status is invalid")
        require_full_sha(result["head_commit"])
        if (
            not isinstance(result["summary"], str)
            or not result["summary"].strip()
        ):
            raise ValueError("plan result summary is invalid")
        blocker = result["blocker"]
        if status == "implemented":
            require_digest(result["verification_set_digest"])
            if blocker is not None:
                raise ValueError("implemented result cannot include a blocker")
        else:
            if result["verification_set_digest"] is not None:
                raise ValueError("blocked result cannot include verification")
            if (
                not isinstance(blocker, Mapping)
                or set(blocker) != {"kind", "detail"}
                or blocker.get("kind") not in _AUTHORITY_BLOCKERS
                or not isinstance(blocker.get("detail"), str)
                or not blocker["detail"].strip()
            ):
                raise ValueError("blocked result blocker is invalid")
        return result

    def _recover(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        index: int,
        outcome: ProviderOutcome,
        *,
        controller_alive: bool = True,
        reconciled_attempt_id: str | None = None,
    ) -> int | None:
        state = store.snapshot()
        progress = self._progress(store, workspace)
        prior_failure = (
            state.get("failure")
            if isinstance(state.get("failure"), Mapping)
            else {}
        )
        sequence = list(prior_failure.get("failure_sequence", []))
        reason = outcome.provider_code or "controller_transport_failed"
        note = (
            "continue the recorded Claude root after a simple interruption"
            if not sequence
            else "start one fresh Claude root with changed recovery context"
        )
        decision = self._recovery.decide(
            {
                "controller_alive": controller_alive,
                "input_digest": state["immutable_config"][
                    "input_snapshot_digest"
                ],
                "session_id": outcome.session_id,
                "session_health": "healthy",
                "resume_failed": outcome.kind == "resume_failed",
                "failure_sequence": tuple(sequence),
                "failure_baseline_progress": progress,
                "observed_tree_digests": (
                    progress.git_tree_digest,
                ),
            },
            {
                "reason_code": reason,
                "provider_code": outcome.provider_code,
                "command_identity": None,
                "candidate_head": workspace.observe().head,
                "input_digest": state["immutable_config"][
                    "input_snapshot_digest"
                ],
                "interruption": outcome.kind,
                "strategy_note": note,
                "progress": progress,
            },
        )
        sequence.append(
            {
                "failure_signature": decision.failure_signature,
                "strategy_note_digest": strategy_note_digest(note),
                "fresh_root_attempted": (
                    decision.session_action == "fresh_root"
                ),
            }
        )
        state["status"] = decision.run_status
        state["failure"] = {
            "reason_code": decision.reason_code,
            "provider_code": outcome.provider_code,
            "outcome_kind": outcome.kind,
            "return_code": outcome.return_code,
            "failure_signature": decision.failure_signature,
            "failure_sequence": sequence,
            "next_strategy": decision.session_action,
            "next_session_action": decision.session_action,
            "session_id": (
                outcome.session_id
                if decision.session_action == "resume_root"
                else None
            ),
        }
        self._mark_reconciled(
            state,
            reconciled_attempt_id,
            "recorded_completed_failure",
        )
        store.commit(state)
        if decision.action == "resume":
            self._emit_summary(store.snapshot())
            return int(ExitCode.RESUMABLE)
        if decision.action != "recover":
            self._emit_summary(store.snapshot())
            return int(ExitCode.FAILED)
        if decision.session_action == "resume_root" and outcome.session_id:
            return self._execute_plan(
                store,
                workspace,
                session_id=outcome.session_id,
                resume_session=True,
            )
        return self._execute_plan(
            store,
            workspace,
            session_id=None,
            resume_session=False,
        )

    def _pause(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        *,
        reconciled_attempt_id: str | None = None,
    ) -> int:
        state = store.snapshot()
        observed = workspace.observe()
        prior_failure = (
            state.get("failure")
            if isinstance(state.get("failure"), Mapping)
            else {}
        )
        sequence = list(prior_failure.get("failure_sequence", []))
        state["status"] = "resumable"
        state["failure"] = {
            "reason_code": "controller_transport_failed",
            "provider_code": outcome.provider_code,
            "outcome_kind": outcome.kind,
            "return_code": outcome.return_code,
            "failure_sequence": sequence,
            "next_strategy": "resume_root",
            "next_session_action": "resume_root",
            "session_id": outcome.session_id,
            "partial_worktree": (
                None
                if observed.clean
                else {
                    "version": 1,
                    "plan_index": state["current_plan_index"],
                    **dataclasses.asdict(observed),
                }
            ),
        }
        self._mark_reconciled(
            state,
            reconciled_attempt_id,
            "recorded_completed_stop",
        )
        store.commit(state)
        self._emit_summary(store.snapshot())
        return int(ExitCode.RESUMABLE)

    def _block(
        self,
        store: StateStore,
        outcome: ProviderOutcome,
        *,
        reconciled_attempt_id: str | None = None,
    ) -> int:
        result = (
            self._validated_plan_result(outcome.result)
            if outcome.result is not None
            else None
        )
        reason = (
            result["blocker"]["kind"]
            if result is not None
            else outcome.provider_code or "external_authority_required"
        )
        state = store.snapshot()
        state["status"] = "blocked"
        state["failure"] = {
            "reason_code": reason,
            "provider_code": outcome.provider_code,
            "outcome_kind": outcome.kind,
            "return_code": outcome.return_code,
            "next_strategy": "block",
            "next_session_action": "none",
        }
        self._mark_reconciled(
            state,
            reconciled_attempt_id,
            "recorded_completed_blocker",
        )
        store.commit(state)
        self._emit_summary(store.snapshot())
        return int(ExitCode.BLOCKED)

    def _progress(
        self,
        store: StateStore,
        workspace: GitWorkspace,
    ) -> ProgressSnapshot:
        state = store.snapshot()
        observed = workspace.observe()
        return ProgressSnapshot(
            sha256_json(
                {
                    "head": observed.head,
                    "tree": observed.tree_digest,
                }
            ),
            EvidenceStore(
                store,
                workspace,
                self._environment,
            ).successful_receipt_digests(),
            tuple(
                plan["handoff_digest"]
                for plan in state["plans"]
                if plan.get("handoff_digest") is not None
            ),
        )

    def _recovery_context(
        self,
        state: Mapping[str, object],
        *,
        current_head: str,
    ) -> dict[str, object]:
        workspace = GitWorkspace.open(
            Path(state["repository"]["source_repository"]),
            Path(state["repository"]["worktree"]),
            state["repository"]["branch"],
        )
        store = StateStore.open(
            self.paths.state_home / state["run_id"]
        )
        progress = self._progress(store, workspace)
        return {
            "current_head": current_head,
            "git_tree_digest": progress.git_tree_digest,
            "successful_receipt_digests": list(
                progress.successful_receipt_digests
            ),
            "plan_handoff_digests": list(
                progress.plan_handoff_digests
            ),
        }

    def _record_session(
        self,
        store: StateStore,
        *,
        attempt_id: str,
        plan_index: int,
        session_id: str,
        candidate_head: str,
    ) -> None:
        state = store.snapshot()
        if not any(
            session.get("session_id") == session_id
            and session.get("plan_index") == plan_index
            for session in state["sessions"]
            if isinstance(session, Mapping)
        ):
            state["sessions"].append(
                {
                    "mode": "implementation",
                    "plan_index": plan_index,
                    "session_id": session_id,
                    "candidate_head": candidate_head,
                    "health": "healthy",
                    "root_attempt_id": attempt_id,
                }
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
        if not isinstance(attempt, dict):
            raise ValueError("captured session attempt is unavailable")
        attempt["session_id"] = session_id
        attempt["session_health"] = "healthy"
        store.commit(state)

    def _complete_attempt(
        self,
        store: StateStore,
        attempt_id: str,
        outcome: ProviderOutcome,
    ) -> None:
        state = store.snapshot()
        attempt = next(
            item
            for item in reversed(state["attempts"])
            if item["attempt_id"] == attempt_id
        )
        attempt["completed"] = True
        attempt["outcome"] = outcome.kind
        attempt["provider_code"] = outcome.provider_code
        attempt["return_code"] = outcome.return_code
        attempt["session_id"] = outcome.session_id
        attempt["result_artifact"] = None
        if outcome.result is not None:
            result_artifact = store.put_artifact(
                "provider_result",
                _plain_json(outcome.result),
            )
            if result_artifact.as_dict() not in state["artifact_refs"]:
                state["artifact_refs"].append(result_artifact.as_dict())
            attempt["result_artifact"] = result_artifact.as_dict()
        store.commit(state)

    def _reconcile_controller(
        self,
        store: StateStore,
        workspace: GitWorkspace,
    ) -> int | None:
        state = store.snapshot()
        if state["current_plan_index"] >= len(state["plans"]):
            return
        attempts = state.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return
        index = state["current_plan_index"]
        attempt = next(
            (
                item
                for item in reversed(attempts)
                if isinstance(item, dict)
                and item.get("mode") == "implementation"
                and item.get("plan_index") == index
                and item.get("reconciled") is None
            ),
            None,
        )
        if not isinstance(attempt, dict):
            return
        if attempt.get("completed") is not True:
            session_id = attempt.get("session_id")
            if not isinstance(session_id, str):
                return
            attempt["reconciled"] = "controller_not_live"
            prior_failure = (
                state.get("failure")
                if isinstance(state.get("failure"), Mapping)
                else {}
            )
            sequence = list(prior_failure.get("failure_sequence", []))
            state["status"] = "resumable"
            state["failure"] = {
                **dict(prior_failure),
                "reason_code": "controller_transport_failed",
                "failure_sequence": sequence,
                "next_strategy": "resume_root",
                "next_session_action": "resume_root",
                "session_id": session_id,
            }
            store.commit(state)
            return
        outcome_kind = attempt.get("outcome")
        if not isinstance(outcome_kind, str) or not outcome_kind:
            raise ValueError("completed provider outcome is invalid")
        result_reference = attempt.get("result_artifact")
        result = None
        if result_reference is not None:
            if (
                not isinstance(result_reference, Mapping)
                or result_reference.get("kind") != "provider_result"
            ):
                raise ValueError("completed provider result is not durable")
            result = _artifact_payload(store, result_reference)
        if outcome_kind == "implemented" and result is None:
            raise ValueError("completed provider result is not durable")
        outcome = ProviderOutcome(
            outcome_kind,
            attempt.get("return_code"),
            attempt.get("session_id"),
            result,
            attempt.get("provider_code"),
            {},
            (),
            "",
        )
        attempt_id = attempt["attempt_id"]
        if outcome.kind == "controller_stopped":
            return self._pause(
                store,
                workspace,
                outcome,
                reconciled_attempt_id=attempt_id,
            )
        if outcome.kind == "blocked":
            return self._block(
                store,
                outcome,
                reconciled_attempt_id=attempt_id,
            )
        if outcome.kind != "implemented":
            return self._recover(
                store,
                workspace,
                index,
                outcome,
                controller_alive=False,
                reconciled_attempt_id=attempt_id,
            )
        self._accept_implemented(store, workspace, index, outcome)
        state = store.snapshot()
        reconciled = next(
            item
            for item in reversed(state["attempts"])
            if isinstance(item, dict)
            and item.get("attempt_id") == attempt["attempt_id"]
        )
        reconciled["reconciled"] = "accepted_completed_result"
        store.commit(state)
        return None

    @staticmethod
    def _mark_reconciled(
        state: dict[str, object],
        attempt_id: str | None,
        disposition: str,
    ) -> None:
        if attempt_id is None:
            return
        attempt = next(
            (
                item
                for item in reversed(state["attempts"])
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            ),
            None,
        )
        if not isinstance(attempt, dict):
            raise ValueError("completed provider attempt is unavailable")
        attempt["reconciled"] = disposition

    def _adapter(
        self,
        run_id: str,
        helper: HelperDescriptor,
        workspace: GitWorkspace,
    ) -> object:
        values = {
            "source_env": self._environment,
            "remotes": tuple(
                line
                for line in _git(workspace.worktree, "remote").splitlines()
                if line
            ),
            "run_id": run_id,
            "helper": helper,
            "stop_requested": self._signals.requested,
        }
        if self._adapter_factory is not None:
            return self._adapter_factory(**values)
        return ClaudeAdapter(**values)

    def _admitted_run(
        self,
        lock_home: Path,
        intent_digest: str,
    ) -> dict[str, object] | None:
        path = lock_home / f"{intent_digest}.json"
        if not path.exists():
            return None
        raw = path.read_bytes()
        document = json.loads(raw)
        if (
            not isinstance(document, dict)
            or raw != canonical_json(document)
            or set(document)
            != {
                "schema_version",
                "intent_digest",
                "run_id",
                "record_digest",
            }
            or document["schema_version"] != 1
            or document["intent_digest"] != intent_digest
            or document["record_digest"]
            != sha256_json(
                {
                    "schema_version": 1,
                    "intent_digest": intent_digest,
                    "run_id": document.get("run_id"),
                }
            )
        ):
            raise ValueError("execution-intent admission record is invalid")
        run_id = document["run_id"]
        if not isinstance(run_id, str):
            raise ValueError("execution-intent admission run is invalid")
        state = StateStore.open(self.paths.state_home / run_id).snapshot()
        if (
            state["immutable_config"].get("execution_intent_digest")
            != intent_digest
        ):
            raise ValueError("execution-intent state binding is invalid")
        return state

    @staticmethod
    def _write_admission(
        lock_home: Path,
        intent_digest: str,
        run_id: str,
    ) -> None:
        body = {
            "schema_version": 1,
            "intent_digest": intent_digest,
            "run_id": run_id,
        }
        atomic_private_write(
            lock_home / f"{intent_digest}.json",
            canonical_json(
                {
                    **body,
                    "record_digest": sha256_json(body),
                }
            ),
        )

    def _report_existing(self, state: Mapping[str, object]) -> int:
        status = state["status"]
        action = (
            f"./skills/kws-claude-plan-runner/scripts/runner resume "
            f"--run-id {state['run_id']}"
            if status in {"resumable", "running", "recovering"}
            else "inspect existing run; replay is refused"
        )
        self._output(
            json.dumps(
                {
                    "status": status,
                    "run_id": state["run_id"],
                    "reason": "matching_run_exists",
                    "recommended_action": action,
                },
                sort_keys=True,
            )
        )
        return {
            "ready_for_integration": int(ExitCode.READY),
            "blocked": int(ExitCode.BLOCKED),
            "failed": int(ExitCode.FAILED),
        }.get(status, int(ExitCode.RESUMABLE))

    @staticmethod
    def _mark_failure(
        store: StateStore,
        reason_code: str,
        detail: str,
    ) -> None:
        try:
            state = store.snapshot()
            state["status"] = "failed"
            state["failure"] = {
                "reason_code": reason_code,
                "detail": str(detail)[:512],
                "next_strategy": "block",
                "next_session_action": "none",
            }
            store.commit(state)
        except (OSError, ValueError):
            pass

    def _emit_summary(self, state: Mapping[str, object]) -> None:
        self._output(
            json.dumps(
                {
                    "status": state["status"],
                    "run_id": state["run_id"],
                    "current_plan_index": state["current_plan_index"],
                    "plan_count": len(state["plans"]),
                    "integration": state["integration"],
                    "failure": state.get("failure"),
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
                    "detail": str(detail)[:512],
                },
                sort_keys=True,
            )
        )
