from __future__ import annotations

import dataclasses
import json
import os
import signal
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExitCode, canonical_json, sha256_json
from .evidence import EvidenceStore
from .git_ops import GitIdentity, GitWorkspace, VOLATILE_REF_POLICY_VERSION, configured_git_identity, protected_refs, validate_commit_identities
from .helper import HelperDescriptor, HelperServer
from .provider import CodexAdapter, ProviderOutcome, ProviderRequest
from .recovery import ActivityLease, ProgressSnapshot, RecoveryPolicy, strategy_note_digest
from .runtime import RuntimeIdentity, RuntimeUnavailable, require_compatible_runtime
from .storage import (
    IntentLock,
    IntentMatch,
    RunLock,
    StateStore,
    execution_intent_digest,
    find_execution_intent,
    write_intent_admission,
)


IMPLEMENTATION_PROMPT = """Read the execution packet and immutable source documents.
Use Superpowers to implement CURRENT_PLAN only. Superpowers owns task discovery,
TDD, review, and its own progress ledger. Use the supplied helper only for the
exact handoff verification. Do not merge, push, deploy, or leave WORKTREE.
Return only the enforced structured handoff result."""

_AUTHORITY_BLOCKERS = frozenset({
    "credentials_unavailable", "destructive_authorization_required",
    "external_authority_required", "external_state_unavailable",
    "irreconcilable_requirements", "permission_required",
    "host_permission_blocked", "provider_auth_blocked",
    "provider_capability_blocked", "provider_unavailable",
    "provider_usage_blocked", "sandbox_capability_blocked",
})
_RUNNER_COMMAND = "./skills/kws-codex-plan-runner/scripts/runner"


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
        self._requested = False
        self._previous: dict[int, object] = {}

    def requested(self) -> bool:
        return self._requested

    def __enter__(self) -> "_SignalGate":
        self._requested = False
        for number in (signal.SIGINT, signal.SIGTERM):
            self._previous[number] = signal.getsignal(number)
            signal.signal(number, self._stop)
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        for number, handler in self._previous.items():
            signal.signal(number, handler)
        self._previous.clear()

    def _stop(self, _number: int, _frame: object) -> None:
        self._requested = True


class PlanRunner:
    def __init__(
        self, paths: RuntimePaths, *, runtime_checker: Callable[[], RuntimeIdentity] | None = None,
        adapter_factory: Callable[..., object] | None = None, output: Callable[[str], None] | None = None,
        environment: Mapping[str, str] | None = None, event_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.paths = paths
        self._runtime_checker = runtime_checker
        self._adapter_factory = adapter_factory
        self._output = output or print
        self._environment = dict(os.environ if environment is None else environment)
        self._event_hook = event_hook
        self._recovery = RecoveryPolicy()
        self._signals = _SignalGate()

    def _event(self, stage: str) -> None:
        if self._event_hook is not None:
            self._event_hook(stage)

    def create_run(self, *, specs: Sequence[Path], plans: Sequence[Path], workspace: Path,
                   stall_seconds: float, sandbox: str, model: str | None = None) -> int:
        store: StateStore | None = None
        root: Path | None = None
        try:
            runtime = self._runtime()
            if not specs or not plans or sandbox not in {"workspace-write", "danger-full-access"}:
                raise ValueError("specs, plans, and sandbox are invalid")
            if not isinstance(stall_seconds, (int, float)) or stall_seconds <= 0:
                raise ValueError("stall-seconds must be positive")
            source = Path(workspace).resolve(strict=True)
            if any(not Path(path).is_absolute() for path in (*specs, *plans)):
                raise ValueError("inputs must be absolute")
            identity = configured_git_identity(source)
            source_head = self._git_head(source)
            common_dir = self._git_common_dir(source)
            ordered_specs = tuple(Path(path) for path in specs)
            ordered_plans = tuple(Path(path) for path in plans)
            intent_digest = execution_intent_digest(
                source_common_dir=common_dir,
                starting_commit=source_head,
                specs=ordered_specs,
                plans=ordered_plans,
            )
            lock_home = self.paths.state_home.with_name(
                f".{self.paths.state_home.name}-intent-locks"
            )
            self._event("intent_admission_ready")
            with IntentLock(lock_home, intent_digest):
                matching = find_execution_intent(
                    self.paths.state_home, intent_digest
                )
                if matching is not None:
                    return self._refuse_matching_run(matching)

                run_id = f"{self._slug(ordered_plans[0].stem)}-{uuid.uuid4()}"
                root = self.paths.state_home / run_id
                branch = f"codex-plan/{run_id}"
                worktree_path = self.paths.worktree_home / run_id
                write_intent_admission(
                    lock_home=lock_home,
                    intent_digest=intent_digest,
                    run_id=run_id,
                    run_root=root,
                    branch=branch,
                    worktree=worktree_path,
                )
                store = StateStore.create(
                    root=root, provider="codex", run_id=run_id,
                    source_repository=source, source_commit=source_head,
                    worktree=worktree_path, branch=branch,
                    specs=ordered_specs, plans=ordered_plans,
                    immutable_config={
                        "stall_seconds": float(stall_seconds),
                        "sandbox": sandbox,
                        "model": model,
                        "git_identity": identity.as_dict(),
                        "git_common_dir": str(common_dir),
                        "protected_refs": protected_refs(source, branch),
                        "volatile_ref_policy_version":
                            VOLATILE_REF_POLICY_VERSION,
                        "input_snapshot_digest":
                            self._input_digest(ordered_specs, ordered_plans),
                        "execution_intent_digest": intent_digest,
                    },
                    runner_runtime=self._runtime_document(runtime),
                )
                GitWorkspace.create(source, worktree_path, branch)
            return self._execute(store)
        except RuntimeUnavailable as error:
            self._emit_error(str(error), "required managed Python runtime is unavailable")
            return int(ExitCode.BLOCKED)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            if root is not None and root.exists():
                try:
                    failed = StateStore.open(root)
                    state = failed.snapshot()
                    state["status"] = "failed"
                    state["failure"] = {
                        "reason_code": "state_integrity_failed",
                        "detail": str(error)[:512],
                        "next_strategy": "block",
                        "next_session_action": "none",
                    }
                    failed.commit(state)
                except (OSError, ValueError):
                    pass
                self._emit_error("state_integrity_failed", error)
                return int(ExitCode.INTEGRITY)
            if root is not None:
                self._emit_error("state_integrity_failed", error)
                return int(ExitCode.INTEGRITY)
            self._emit_error("invalid_invocation", error)
            return int(ExitCode.INVALID)

    def _refuse_matching_run(self, match: IntentMatch) -> int:
        state = match.state
        if state is None:
            self._emit_matching_run(
                reason="matching_run_unproven",
                run_id=match.run_id,
                status="invalid",
                branch=match.branch,
                worktree=match.worktree,
                recommended_action="preserve evidence and stop",
                detail=match.invalid_detail,
            )
            return int(ExitCode.INTEGRITY)

        run_id = state["run_id"]
        status = state["status"]
        repository = state["repository"]
        reason = "matching_run_exists"
        detail: object | None = None
        if status in {"running", "recovering", "ready_for_integration"}:
            action = f"{_RUNNER_COMMAND} inspect --run-id {run_id}"
            code = (
                ExitCode.READY
                if status == "ready_for_integration"
                else ExitCode.RESUMABLE
            )
        elif status == "resumable":
            action = f"{_RUNNER_COMMAND} resume --run-id {run_id}"
            code = ExitCode.RESUMABLE
        elif status == "blocked":
            action = (
                "fix the named blocker, then "
                f"{_RUNNER_COMMAND} resume --run-id {run_id} --retry-blocked"
            )
            code = ExitCode.BLOCKED
        elif status == "failed" and self._is_retryable_failed_state(
            state.get("failure")
        ):
            action = (
                f"{_RUNNER_COMMAND} resume --run-id {run_id} "
                "--retry-failed --strategy-note TEXT"
            )
            code = ExitCode.FAILED
        else:
            reason = "matching_run_unproven"
            action = "preserve evidence and stop"
            failure = state.get("failure")
            detail = (
                failure.get("detail")
                if isinstance(failure, Mapping)
                else None
            )
            code = ExitCode.INTEGRITY
        self._emit_matching_run(
            reason=reason,
            run_id=run_id,
            status=status,
            branch=repository["branch"],
            worktree=repository["worktree"],
            recommended_action=action,
            detail=detail,
        )
        return int(code)

    @staticmethod
    def _is_retryable_failed_state(failure: object) -> bool:
        return (
            isinstance(failure, Mapping)
            and failure.get("reason_code") == "recovery_exhausted"
            and failure.get("next_strategy")
            in {"fresh_root", "resume_root", "block"}
        )

    def _emit_matching_run(
        self,
        *,
        reason: str,
        run_id: object,
        status: object,
        branch: object,
        worktree: object,
        recommended_action: str,
        detail: object | None = None,
    ) -> None:
        response = {
            "reason": reason,
            "run_id": str(run_id)[:128],
            "status": str(status)[:64],
            "branch": str(branch)[:256],
            "worktree": str(worktree)[:1024],
            "recommended_action": recommended_action[:2048],
        }
        if detail is not None:
            response["detail"] = str(detail)[:512]
        self._output(json.dumps(response, sort_keys=True))

    def resume(self, run_id: str, *, retry_blocked: bool, retry_failed: bool,
               strategy_note: str | None, sandbox: str | None = None, model: str | None = None) -> int:
        try:
            self._runtime()
            store = StateStore.open(self.paths.state_home / run_id)
            state = store.snapshot()
            if state.get("format_version") == 1:
                self._emit_error("legacy_contract_requires_v1_runner", "version 1 execution is inspect-only")
                return int(ExitCode.INVALID)
            if state["status"] == "ready_for_integration":
                self._emit_summary(state)
                return int(ExitCode.READY)
            if state["status"] == "blocked" and not retry_blocked:
                self._emit_summary(state)
                return int(ExitCode.BLOCKED)
            if state["status"] == "failed" and not retry_failed:
                self._emit_summary(state)
                return int(ExitCode.FAILED)
            return self._execute(store)
        except FileNotFoundError:
            self._emit_error("unknown_run", run_id)
            return int(ExitCode.INVALID)
        except (OSError, ValueError, RuntimeError) as error:
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)

    def inspect(self, run_id: str) -> int:
        try:
            store = StateStore.open(self.paths.state_home / run_id)
            self._emit_summary(store.snapshot())
            return int(ExitCode.READY)
        except FileNotFoundError:
            self._emit_error("unknown_run", run_id)
            return int(ExitCode.INVALID)
        except (OSError, ValueError) as error:
            self._emit_error("state_integrity_failed", error)
            return int(ExitCode.INTEGRITY)

    def repair(self, run_id: str, *, expected_revision: int, repair_kind: str,
               strategy_note: str, attempt_id: str | None) -> int:
        try:
            state = StateStore.open(self.paths.state_home / run_id).snapshot()
            if state.get("format_version") == 1:
                self._emit_error("legacy_contract_requires_v1_runner", "version 1 repair is not supported")
                return int(ExitCode.INVALID)
            if repair_kind != "volatile-codex-turn-refs" or attempt_id is not None:
                raise ValueError("unsupported repair")
            self._emit_summary(state)
            return int(ExitCode.INTEGRITY)
        except FileNotFoundError:
            self._emit_error("unknown_run", run_id)
            return int(ExitCode.INVALID)
        except (OSError, ValueError) as error:
            self._emit_error("repair_refused", error)
            return int(ExitCode.INTEGRITY)

    def _execute(self, store: StateStore) -> int:
        try:
            with self._signals, RunLock(store.root / "run.lock"):
                state = store.snapshot()
                repository = state["repository"]
                workspace = GitWorkspace.open(Path(repository["source_repository"]), Path(repository["worktree"]), repository["branch"])
                self._require_git(state, workspace)
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
                while state["current_plan_index"] < len(state["plans"]):
                    code = self._execute_plan(
                        store,
                        workspace,
                        session_id=recorded_session,
                        resume_session=recorded_session is not None,
                    )
                    recorded_session = None
                    if code is not None:
                        return code
                    state = store.snapshot()
                state["status"] = "ready_for_integration"
                state["failure"] = None
                store.commit(state)
                self._emit_summary(store.snapshot())
                return int(ExitCode.READY)
        except (OSError, RuntimeError, ValueError) as error:
            self._fail_closed(store, error)
            return int(ExitCode.INTEGRITY)

    def _require_git(
        self, state: Mapping[str, object], workspace: GitWorkspace
    ):
        observation = workspace.observe()
        if workspace.protected_refs() != state["immutable_config"]["protected_refs"]:
            raise ValueError("protected refs changed during provider execution")
        import subprocess
        if subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                str(state["repository"]["source_commit"]),
                observation.head,
            ],
            cwd=workspace.worktree,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            raise ValueError("starting commit is not an ancestor")
        if observation.clean:
            return observation
        failure = state.get("failure")
        sealed = (
            failure.get("partial_worktree")
            if isinstance(failure, Mapping)
            else None
        )
        if sealed != dataclasses.asdict(observation):
            raise ValueError("dirty worktree identity is not sealed")
        return observation

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
        observation = self._require_git(state, workspace)
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
        outcome = self._launch(
            store,
            workspace,
            index,
            observation.head,
            session_id=session_id,
            attempt_id=attempt_id,
        )
        self._complete_attempt(store, attempt_id, outcome)
        if outcome.kind == "controller_stopped":
            return self._pause(store, workspace, outcome, attempt_id)
        if outcome.kind == "blocked":
            state = store.snapshot()
            state["status"] = "blocked"
            state["failure"] = {"reason_code": outcome.provider_code or "external_authority_required", "next_strategy": "block", "next_session_action": "none"}
            store.commit(state)
            self._emit_summary(store.snapshot())
            return int(ExitCode.BLOCKED)
        if outcome.kind != "implemented" or outcome.result is None:
            return self._recover(store, workspace, outcome, index)
        try:
            self._accept_implemented(store, workspace, index, outcome)
        except ValueError as error:
            self._fail_closed(store, error)
            return int(ExitCode.INTEGRITY)
        return None

    def _launch(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        index: int,
        head: str,
        *,
        session_id: str | None = None,
        attempt_id: str,
    ) -> ProviderOutcome:
        state = store.snapshot()
        evidence = EvidenceStore(store, workspace, self._environment)
        lease = ActivityLease(float(state["immutable_config"]["stall_seconds"]), time.monotonic())
        client_argv = (str(Path(sys.executable).resolve()), str(self.paths.runner_script.resolve()), "_helper")
        with HelperServer(run_id=state["run_id"], worktree=workspace.worktree, evidence_store=evidence,
                          client_argv=client_argv, state_store=store) as helper:
            packet = self._packet(store.snapshot(), index, head, helper.descriptor)
            request = ProviderRequest(
                worktree=workspace.worktree, git_common_dir=workspace._common_dir,
                git_identity=GitIdentity.from_mapping(state["immutable_config"]["git_identity"]),
                prompt=IMPLEMENTATION_PROMPT + "\nEXECUTION_PACKET=" + canonical_json(packet).decode(),
                output_schema=(self.paths.skill_root / "templates" / "plan-result.schema.json").resolve(),
                output_path=store.root / f".provider-{uuid.uuid4().hex}.json",
                sandbox=state["immutable_config"]["sandbox"], model=state["immutable_config"].get("model"), session_id=session_id,
            )
            adapter = self._adapter(state["run_id"], helper.descriptor, workspace)
            outcome = adapter.launch(
                request,
                lease,
                on_session_id=lambda session: self._record_session(
                    store, index, session, head
                ),
                on_process_observation=lambda process: self._record_process(
                    store, attempt_id, process
                ),
            )
        return outcome

    def _packet(self, state: Mapping[str, object], index: int, head: str, helper: HelperDescriptor) -> dict[str, object]:
        specs = [{"snapshot_path": item["snapshot_path"], "sha256": item["sha256"]} for item in state["inputs"] if item["role"] == "spec"]
        plan = state["plans"][index]
        return {
            "packet_version": 2, "mode": "implementation", "run_id": state["run_id"],
            "worktree": state["repository"]["worktree"], "branch": state["repository"]["branch"],
            "starting_commit": state["repository"]["source_commit"], "current_head": head,
            "specifications": specs,
            "current_plan": {"index": index, "total": len(state["plans"]), "snapshot_path": plan["snapshot_path"], "sha256": plan["sha256"]},
            "implemented_plan_handoffs": [plan["handoff_digest"] for plan in state["plans"][:index] if plan.get("handoff_digest")],
            "prior_verification_sets": [ref["digest"] for ref in state["artifact_refs"] if ref.get("kind") == "plan_verification_set"],
            "is_final_plan": index == len(state["plans"]) - 1,
            "final_review_requirements": ([{"snapshot_path": item["snapshot_path"], "sha256": item["sha256"]} for item in state["inputs"]] if index == len(state["plans"]) - 1 else None),
            "checkpoint_revision": state["revision"], "recovery_context": self._recovery_context(state, workspace_head=head),
            "helper": {"protocol_version": helper.protocol_version, "socket_path": str(helper.socket_path), "nonce": helper.nonce, "client_argv": list(helper.client_argv)},
            "integration_policy": "keep",
        }

    def _accept_implemented(self, store: StateStore, workspace: GitWorkspace, index: int, outcome: ProviderOutcome) -> None:
        result = outcome.result
        self._validated_plan_result(result)
        assert isinstance(result, Mapping)
        state = store.snapshot()
        observation = workspace.require_clean_ancestor(state["repository"]["source_commit"])
        if workspace.protected_refs() != state["immutable_config"]["protected_refs"]:
            raise ValueError("protected refs changed during provider execution")
        if result["head_commit"] != observation.head:
            raise ValueError("implementation HEAD mismatch")
        validate_commit_identities(workspace.worktree, state["repository"]["source_commit"], observation.head, GitIdentity.from_mapping(state["immutable_config"]["git_identity"]))
        digest = result["verification_set_digest"]
        assert isinstance(digest, str)
        EvidenceStore(store, workspace, self._environment).require_successful_verification_set(
            digest, candidate_head=observation.head,
            kind="run_verification_set" if index == len(state["plans"]) - 1 else "plan_verification_set", plan_index=index,
        )
        result_artifact = store.put_artifact("provider_result", dict(result))
        handoff = store.put_artifact("plan_handoff", {"plan_index": index, "head_commit": observation.head, "summary": result["summary"], "verification_set_digest": digest})
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

    def _recover(self, store: StateStore, workspace: GitWorkspace, outcome: ProviderOutcome, index: int) -> int | None:
        state = store.snapshot()
        progress = self._progress(state, workspace)
        failure = state.get("failure") if isinstance(state.get("failure"), Mapping) else {}
        decision = self._recovery.decide(
            {"controller_alive": True, "input_digest": state["immutable_config"]["input_snapshot_digest"],
             "session_id": outcome.session_id, "session_health": "healthy", "resume_failed": outcome.kind == "resume_failed",
             "failure_sequence": tuple(failure.get("failure_sequence", [])), "failure_baseline_progress": progress,
             "observed_tree_digests": (progress.git_tree_digest,)},
            {"reason_code": outcome.provider_code or "controller_transport_failed", "provider_code": outcome.provider_code,
             "command_identity": None, "candidate_head": workspace.observe().head, "input_digest": state["immutable_config"]["input_snapshot_digest"],
             "interruption": outcome.kind, "strategy_note": "resume same plan", "progress": progress},
        )
        sequence = list(failure.get("failure_sequence", []))
        sequence.append({"failure_signature": decision.failure_signature, "strategy_note_digest": strategy_note_digest("resume same plan"), "fresh_session_attempted": decision.session_action == "fresh_session"})
        next_strategy = {"explicit_resume": "resume_root", "fresh_session": "fresh_root"}.get(decision.session_action, "block")
        state["status"] = decision.run_status
        state["failure"] = {"reason_code": decision.reason_code, "failure_signature": decision.failure_signature,
                            "failure_sequence": sequence, "next_strategy": next_strategy, "next_session_action": decision.session_action}
        store.commit(state)
        if decision.action == "recover":
            resume_session = outcome.session_id if decision.session_action == "explicit_resume" else None
            return self._execute_plan(
                store,
                workspace,
                session_id=resume_session,
                resume_session=resume_session is not None,
            )
        self._emit_summary(store.snapshot())
        return int(ExitCode.FAILED)

    def _progress(self, state: Mapping[str, object], workspace: GitWorkspace) -> ProgressSnapshot:
        observation = workspace.observe()
        return ProgressSnapshot(
            sha256_json({"head": observation.head, "tree": observation.tree_digest}),
            tuple(ref["digest"] for ref in state["artifact_refs"] if ref.get("kind") == "verification_receipt"),
            tuple(plan["handoff_digest"] for plan in state["plans"] if plan.get("handoff_digest")),
        )

    @staticmethod
    def _validated_plan_result(value: object) -> None:
        if not isinstance(value, Mapping) or set(value) != {"status", "head_commit", "summary", "verification_set_digest", "blocker"}:
            raise ValueError("plan result shape is invalid")
        status, head, summary = value["status"], value["head_commit"], value["summary"]
        digest, blocker = value["verification_set_digest"], value["blocker"]
        if status not in {"implemented", "blocked"} or not isinstance(head, str) or len(head) not in {40, 64} or not isinstance(summary, str) or not summary.strip():
            raise ValueError("plan result contract is invalid")
        if status == "implemented" and (not isinstance(digest, str) or len(digest) != 64 or blocker is not None):
            raise ValueError("implemented result contract is invalid")
        if status == "blocked" and (digest is not None or not isinstance(blocker, Mapping) or blocker.get("kind") not in _AUTHORITY_BLOCKERS):
            raise ValueError("blocked result contract is invalid")

    def _record_session(self, store: StateStore, index: int, session_id: str, head: str) -> None:
        state = store.snapshot()
        state["sessions"].append({"mode": "implementation", "plan_index": index, "session_id": session_id, "candidate_head": head, "health": "healthy"})
        for attempt in reversed(state["attempts"]):
            if attempt.get("plan_index") == index and attempt.get("completed") is False:
                attempt["session_id"] = session_id
                attempt["session_health"] = "healthy"
                break
        store.commit(state)

    def _record_process(
        self,
        store: StateStore,
        attempt_id: str,
        process: Mapping[str, object],
    ) -> None:
        state = store.snapshot()
        attempt = next(
            item
            for item in reversed(state["attempts"])
            if item.get("attempt_id") == attempt_id
        )
        for name in ("provider_pid", "provider_pgid", "descendant_pids"):
            attempt[name] = process[name]
        store.commit(state)

    def _complete_attempt(
        self, store: StateStore, attempt_id: str, outcome: ProviderOutcome
    ) -> None:
        state = store.snapshot()
        attempt = next(
            item
            for item in reversed(state["attempts"])
            if item.get("attempt_id") == attempt_id
        )
        attempt.update(
            {
                "completed": True,
                "outcome": outcome.kind,
                "provider_code": outcome.provider_code,
                "return_code": outcome.return_code,
                "session_id": outcome.session_id,
            }
        )
        store.commit(state)

    def _pause(
        self,
        store: StateStore,
        workspace: GitWorkspace,
        outcome: ProviderOutcome,
        attempt_id: str,
    ) -> int:
        state = store.snapshot()
        observation = workspace.observe()
        state["status"] = "resumable"
        state["failure"] = {
            "reason_code": "controller_transport_failed",
            "provider_code": outcome.provider_code,
            "next_strategy": "resume_root",
            "next_session_action": "resume_root",
            "session_id": outcome.session_id,
            "partial_attempt_id": attempt_id,
            "partial_mode": "implementation",
            "partial_worktree": (
                dataclasses.asdict(observation)
                if not observation.clean
                else None
            ),
        }
        store.commit(state)
        self._emit_summary(state)
        return int(ExitCode.RESUMABLE)

    def _adapter(self, run_id: str, helper: HelperDescriptor, workspace: GitWorkspace):
        values = {"source_env": self._environment, "provider_auth_prefixes": ("OPENAI_", "CODEX_"), "remotes": ("origin",), "run_id": run_id, "helper": helper, "stop_requested": self._signals.requested}
        return self._adapter_factory(**values) if self._adapter_factory else CodexAdapter(**values)

    def _recovery_context(self, state: Mapping[str, object], *, workspace_head: str) -> dict[str, object]:
        progress = self._progress(state, GitWorkspace.open(Path(state["repository"]["source_repository"]), Path(state["repository"]["worktree"]), state["repository"]["branch"]))
        return {"current_head": workspace_head, "tree_digest": progress.git_tree_digest, "successful_receipt_digests": list(progress.successful_receipt_digests), "plan_handoff_digests": list(progress.plan_handoff_digests)}

    def _fail_closed(self, store: StateStore, error: object) -> None:
        state = store.snapshot()
        state["status"] = "failed"
        state["failure"] = {"reason_code": "state_integrity_failed", "detail": str(error)[:512], "next_strategy": "block", "next_session_action": "none"}
        store.commit(state)
        self._emit_summary(state)

    def _runtime(self) -> RuntimeIdentity:
        return require_compatible_runtime(self._runtime_checker()) if self._runtime_checker else require_compatible_runtime()

    @staticmethod
    def _runtime_document(runtime: RuntimeIdentity) -> dict[str, object]:
        return {"uv_version": runtime.uv_version, "implementation": runtime.implementation, "python_version": runtime.python_version, "executable": runtime.executable, "architecture": runtime.architecture, "gil_disabled": runtime.gil_disabled}

    @staticmethod
    def _input_digest(specs: Sequence[Path], plans: Sequence[Path]) -> str:
        return sha256_json([Path(path).read_text(encoding="utf-8") for path in (*specs, *plans)])

    @staticmethod
    def _slug(value: str) -> str:
        return "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-") or "plan"

    @staticmethod
    def _git_head(path: Path) -> str:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()

    @staticmethod
    def _git_common_dir(path: Path) -> Path:
        import subprocess
        value = Path(
            subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not value.is_absolute():
            value = path / value
        return value.resolve(strict=True)

    def _emit_summary(self, state: Mapping[str, object]) -> None:
        self._output(json.dumps({"run_id": state["run_id"], "status": state["status"], "integration": state["integration"], "current_plan_index": state["current_plan_index"], "plan_count": len(state["plans"])}, sort_keys=True))

    def _emit_error(self, reason_code: str, detail: object) -> None:
        self._output(json.dumps({"status": "failed", "reason_code": reason_code, "detail": str(detail)[:512]}, sort_keys=True))
