from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ExitCode, TASK_STATUSES, canonical_json, sha256_json
from .evidence import EvidenceStore
from .git_ops import GitWorkspace
from .helper import HelperDescriptor, HelperServer
from .provider import CodexAdapter, ProviderOutcome, ProviderRequest
from .recovery import (
    ActivityLease,
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

    def create_run(
        self,
        *,
        specs: Sequence[Path],
        plans: Sequence[Path],
        workspace: Path,
        stall_seconds: float,
        sandbox: str,
        model: str | None = None,
    ) -> int:
        try:
            if not specs or not plans:
                raise ValueError("at least one spec and one plan are required")
            if sandbox not in {"workspace-write", "danger-full-access"}:
                raise ValueError("sandbox is invalid")
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
        branch = f"codex-plan/{run_id}"
        worktree = self.paths.worktree_home / run_id
        root = self.paths.state_home / run_id
        try:
            starting_commit = _source_head(workspace)
            common_dir = _git_common_dir(workspace)
            input_digest = _input_digest(ordered_specs, ordered_plans)
            immutable_config = {
                "stall_seconds": float(stall_seconds),
                "sandbox": sandbox,
                "model": model,
                "input_snapshot_digest": input_digest,
                "git_common_dir": str(common_dir),
                "protected_refs": _protected_refs(workspace, branch),
            }
            store = StateStore.create(
                root=root,
                provider="codex",
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
                prior = (
                    failure.get("strategy_digests", [])
                    if isinstance(failure, Mapping)
                    else []
                )
                digest = strategy_note_digest(strategy_note)
                if digest in prior:
                    raise ValueError("strategy note duplicates a prior strategy")
                state["status"] = "resumable"
                state["failure"] = {
                    **(dict(failure) if isinstance(failure, Mapping) else {}),
                    "operator_strategy_note": strategy_note.strip(),
                    "strategy_digests": [*prior, digest],
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
            with RunLock(store.root / "run.lock"):
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
                while state["current_plan_index"] < len(state["plans"]):
                    code = self._execute_current_plan(store, workspace)
                    if code is not None:
                        return code
                    state = store.snapshot()
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
        self, state: Mapping[str, object], workspace: GitWorkspace
    ) -> None:
        config = state["immutable_config"]
        if str(workspace._common_dir) != config.get("git_common_dir"):
            raise ValueError("Git common directory drift detected")
        if workspace.protected_refs() != config.get("protected_refs"):
            raise ValueError("protected ref mutation detected")
        workspace.require_clean_ancestor(state["repository"]["source_commit"])

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
        observation = workspace.require_clean_ancestor(
            state["repository"]["source_commit"]
        )
        session_id = self._implementation_session(state, index)
        outcome = self._launch(
            store,
            workspace,
            mode="implementation",
            observation_head=observation.head,
            current_plan_index=index,
            session_id=session_id,
        )
        self._checkpoint_outcome(store, outcome, attempt_id, index, "implementation")
        if outcome.kind == "implemented":
            return self._accept_implemented(store, workspace, outcome, index)
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
        with HelperServer(
            run_id=state["run_id"],
            worktree=workspace.worktree,
            evidence_store=evidence,
            client_argv=client_argv,
            state_store=store,
            sealed_final_set_digest=sealed_digest,
            sealed_candidate_head=sealed_head,
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
            output_path = (
                store.root
                / f".provider-{mode}-{uuid.uuid4().hex}-result.json"
            )
            adapter = self._make_adapter(state["run_id"], helper.descriptor)
            request = ProviderRequest(
                worktree=workspace.worktree,
                git_common_dir=workspace._common_dir,
                prompt=prompt
                + "\nEXECUTION_PACKET="
                + canonical_json(packet).decode("utf-8"),
                output_schema=schema.resolve(),
                output_path=output_path,
                sandbox=state["immutable_config"]["sandbox"],
                model=state["immutable_config"]["model"],
                session_id=session_id,
            )
            try:
                return adapter.launch(
                    request,
                    ActivityLease(
                        state["immutable_config"]["stall_seconds"], self._clock()
                    ),
                )
            finally:
                output_path.unlink(missing_ok=True)

    def _make_adapter(
        self, run_id: str, helper: HelperDescriptor
    ) -> Any:
        values = {
            "source_env": self._environment,
            "run_id": run_id,
            "helper": helper,
        }
        if self._adapter_factory is None:
            return CodexAdapter(**values)
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
            "required_strategy_change": bool(
                isinstance(failure, Mapping)
                and failure.get("required_strategy_change")
            ),
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
        return {
            "packet_version": 1,
            "mode": "finalization",
            "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"],
            "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"],
            "candidate_head": candidate_head,
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

    def _checkpoint_outcome(
        self,
        store: StateStore,
        outcome: ProviderOutcome,
        attempt_id: str,
        plan_index: int | None,
        mode: str,
    ) -> None:
        state = store.snapshot()
        for attempt in reversed(state["attempts"]):
            if attempt.get("attempt_id") == attempt_id:
                attempt["completed"] = True
                attempt["outcome"] = outcome.kind
                attempt["provider_code"] = outcome.provider_code
                break
        if outcome.session_id is not None:
            state["sessions"].append(
                {
                    "mode": mode,
                    "plan_index": plan_index,
                    "session_id": outcome.session_id,
                    "health": (
                        "invalid"
                        if outcome.kind
                        in {"stalled", "context_overflow", "resume_failed"}
                        else "healthy"
                    ),
                }
            )
        if isinstance(outcome.result, Mapping) and isinstance(
            outcome.result.get("task_ledger"), list
        ):
            state["task_ledger"] = self._validated_task_ledger(
                outcome.result["task_ledger"]
            )
        store.commit(state)

    def _accept_implemented(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        index: int,
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
        obligations = result.get("open_obligation_ids")
        if not isinstance(obligations, list) or obligations:
            return self._integrity_failure(store, "implementation obligations remain")
        state = store.snapshot()
        artifact = store.put_artifact(
            "plan_handoff",
            {
                "plan_index": index,
                "head_commit": observation.head,
                "summary": str(result.get("summary", ""))[:4096],
                "task_ledger": ledger,
            },
        )
        state = store.snapshot()
        if artifact.as_dict() not in state["artifact_refs"]:
            state["artifact_refs"].append(artifact.as_dict())
        state["task_ledger"] = ledger
        state["plans"][index]["status"] = "implemented"
        state["current_plan_index"] = index + 1
        state["status"] = "resumable"
        state["failure"] = None
        store.commit(state)
        return None

    @staticmethod
    def _validated_task_ledger(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
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
                or not isinstance(evidence, list)
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
        return ProgressSnapshot(observation.tree_digest, done, receipts, ())

    def _recover(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        index: int,
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
        reason = outcome.provider_code or "controller_transport_failed"
        result = outcome.result if isinstance(outcome.result, Mapping) else {}
        strategy = result.get("strategy_note")
        if not isinstance(strategy, str) or not strategy.strip():
            strategy = (
                f"controller recovery {len(sequence) + 1}: "
                + (
                    "start a fresh provider session"
                    if outcome.kind
                    in {"stalled", "context_overflow", "resume_failed", "failed"}
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
                    if outcome.kind
                    not in {"stalled", "context_overflow", "resume_failed"}
                    else "invalid"
                ),
                "resume_failed": outcome.kind == "resume_failed",
                "failure_sequence": tuple(sequence),
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
            state["status"] = "failed"
            state["failure"] = {
                "reason_code": decision.reason_code,
                "failure_signature": decision.failure_signature,
                "failure_sequence": sequence,
                "strategy_digests": [
                    item["strategy_note_digest"]
                    for item in sequence
                    if item.get("strategy_note_digest")
                ],
            }
            store.commit(state)
            self._emit_summary(store.snapshot())
            return int(ExitCode.FAILED)
        sequence.append(
            {
                "failure_signature": decision.failure_signature,
                "strategy_note_digest": strategy_note_digest(strategy),
                "tree_digest": current.git_tree_digest,
            }
        )
        state["status"] = "recovering"
        state["failure"] = {
            "reason_code": reason,
            "failure_signature": decision.failure_signature,
            "failure_sequence": sequence,
            "baseline_progress": dataclasses.asdict(current),
            "required_strategy_change": decision.required_strategy_change,
            "next_session_action": decision.session_action,
            "strategy_digests": [
                item["strategy_note_digest"] for item in sequence
            ],
        }
        store.commit(state)
        return self._execute_current_plan(store, workspace)

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

    def _finalize(
        self, store: StateStore, workspace: GitWorkspace
    ) -> int:
        while True:
            state = store.snapshot()
            candidate = workspace.require_clean_ancestor(
                state["repository"]["source_commit"]
            )
            self._require_git_contract(state, workspace)
            existing_declaration = self._existing_final_set(
                store, candidate.head
            )
            if existing_declaration is not None:
                state["finalization"] = {
                    "candidate_head": candidate.head,
                    "verification_set_digest": existing_declaration,
                }
            session_id = self._finalization_resume_session(state, candidate.head)
            attempt_id = str(uuid.uuid4())
            state["status"] = "running"
            state["finalization"] = {
                "candidate_head": candidate.head,
                "verification_set_digest": (
                    state["finalization"].get("verification_set_digest")
                    if isinstance(state.get("finalization"), Mapping)
                    and state["finalization"].get("candidate_head") == candidate.head
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
            )
            self._checkpoint_outcome(
                store, outcome, attempt_id, None, "finalization"
            )
            if outcome.kind != "reviewed" or not isinstance(
                outcome.result, Mapping
            ):
                if outcome.kind == "blocked":
                    return self._block(store, outcome)
                return self._integrity_failure(
                    store, "finalization did not return a structured review"
                )
            result = outcome.result
            try:
                self._validate_final_result(
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
            handoff = store.put_artifact(
                "branch_handoff",
                {
                    "run_id": state["run_id"],
                    "branch": state["repository"]["branch"],
                    "starting_commit": state["repository"]["source_commit"],
                    "candidate_head": candidate.head,
                    "verification_set_digest": result[
                        "verification_set_digest"
                    ],
                    "review_head": result["review_head"],
                    "integration": "not_observed",
                },
            )
            state = store.snapshot()
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
        if (
            not isinstance(finalization, Mapping)
            or finalization.get("candidate_head") != candidate_head
            or not finalization.get("verification_set_digest")
        ):
            return None
        for session in reversed(state["sessions"]):
            if (
                isinstance(session, Mapping)
                and session.get("mode") == "finalization"
                and session.get("health") == "healthy"
                and isinstance(session.get("session_id"), str)
            ):
                return session["session_id"]
        return None

    def _validate_final_result(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        candidate_head: str,
        result: Mapping[str, object],
    ) -> None:
        if result.get("status") != "reviewed":
            raise ValueError("review status is invalid")
        if result.get("review_head") != candidate_head:
            raise ValueError("review HEAD does not match candidate HEAD")
        digest = result.get("verification_set_digest")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("verification set digest is invalid")
        findings = result.get("open_findings")
        obligations = result.get("open_obligation_ids")
        if not isinstance(findings, list) or not isinstance(obligations, list):
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
            for item in store.snapshot()["artifact_refs"]
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
        self._require_git_contract(store.snapshot(), workspace)
        if workspace.observe().head != candidate_head:
            raise ValueError("candidate HEAD changed during finalization")

    def _recover_review_findings(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        findings: Sequence[Mapping[str, object]],
    ) -> int | None:
        state = store.snapshot()
        index = len(state["plans"]) - 1
        state["status"] = "recovering"
        state["failure"] = {
            "reason_code": "review_failed",
            "required_strategy_change": True,
            "next_session_action": "fresh_session",
            "review_findings": [dict(item) for item in findings],
        }
        attempt_id = str(uuid.uuid4())
        state["attempts"].append(
            {
                "attempt_id": attempt_id,
                "mode": "implementation",
                "plan_index": index,
                "controller_pid": os.getpid(),
                "completed": False,
                "review_recovery": True,
            }
        )
        store.commit(state)
        outcome = self._launch(
            store,
            workspace,
            mode="implementation",
            observation_head=workspace.observe().head,
            current_plan_index=index,
            session_id=None,
        )
        self._checkpoint_outcome(
            store, outcome, attempt_id, index, "implementation"
        )
        if outcome.kind == "blocked":
            return self._block(store, outcome)
        if outcome.kind != "implemented":
            return self._recover(store, workspace, outcome, index)
        result = outcome.result
        observation = workspace.require_clean_ancestor(
            state["repository"]["source_commit"]
        )
        if (
            not isinstance(result, Mapping)
            or result.get("head_commit") != observation.head
            or result.get("open_obligation_ids") != []
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
