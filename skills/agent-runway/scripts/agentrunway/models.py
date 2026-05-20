from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


AGENTRUNWAY_VERSION = "0.1.0"
TASK_PACKET_SCHEMA = "agentrunway.task_packet.v1"
RESULT_SCHEMA = "agentrunway.worker_result.v1"
REVIEW_SCHEMA = "agentrunway.review_result.v1"
VERIFICATION_SCHEMA = "agentrunway.verification_result.v1"
EVENT_SCHEMA = "agentrunway.event.v1"

CLAIM_MODES = {"owned", "shared_append", "consumes", "read_only", "forbidden"}
OUTCOMES = {"finished", "simulated_finished", "failed", "blocked", "cancelled", "unknown"}
AGENTLENS_OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}
REASONING_LEVELS = {"lowest", "low", "medium", "high", "highest"}


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    MERGED = "merged"
    SIMULATED_COMPLETED = "simulated_completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkerRole(str, Enum):
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    RECOVERY = "recovery"


class WorkerState(str, Enum):
    QUEUED = "queued"
    WORKTREE_CREATED = "worktree_created"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RESULT_COLLECTED = "result_collected"
    VALIDATED = "validated"
    QUEUED_FOR_REVIEW = "queued_for_review"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    MERGE_READY = "merge_ready"
    MERGED = "merged"
    NOT_SELECTED = "not_selected"
    ADAPTER_CRASHED = "adapter_crashed"
    TIMEOUT = "timeout"
    STALLED = "stalled"
    MALFORMED_RESULT = "malformed_result"
    METHOD_AUDIT_FAILED = "method_audit_failed"
    DIFF_SCOPE_FAILED = "diff_scope_failed"
    MERGE_CONFLICT = "merge_conflict"
    VERIFICATION_FAILED = "verification_failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ProcessState(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    EXITED = "exited"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    MISSING = "missing"


@dataclass(frozen=True)
class WorkerSpec:
    run_id: str
    task_id: str
    worker_id: str
    role: str
    runtime: str
    model: str
    reasoning_effort: str
    prompt_path: str
    packet_path: str
    output_path: str
    worktree_path: str
    artifact_dir: str
    timeout_seconds: int
    attempt: int = 1
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessSnapshot:
    state: str
    pid: int | None
    returncode: int | None = None
    started_at: float | None = None
    ended_at: float | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WorkerResultEnvelope:
    worker_id: str
    task_id: str
    role: str
    runtime: str
    process: ProcessSnapshot
    result_path: str
    result_json: dict[str, Any] | None
    stdout_path: str
    stderr_path: str
    error: str | None = None


@dataclass(frozen=True)
class FileClaim:
    path: str
    mode: Literal["owned", "shared_append", "consumes", "read_only", "forbidden"]


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    risk: Literal["low", "medium", "high"]
    phase: str
    dependencies: tuple[str, ...]
    spec_refs: tuple[str, ...]
    file_claims: tuple[FileClaim, ...]
    acceptance_commands: tuple[str, ...]
    resource_keys: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    serial: bool = False
    objective: str = ""
    line: int = 0


@dataclass(frozen=True)
class ModelAssignment:
    runtime: str
    model: str
    reasoning_effort: str
    reasoning_effort_resolved: str | None = None


@dataclass(frozen=True)
class TaskPacket:
    schema: str
    run_id: str
    task_id: str
    role: str
    objective: str
    spec_refs: tuple[dict[str, str], ...]
    dependencies: tuple[str, ...]
    allowed_write_globs: tuple[str, ...]
    forbidden_write_globs: tuple[str, ...]
    file_claims: tuple[FileClaim, ...]
    required_skills: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    output_schema: str
    model_assignment: ModelAssignment


@dataclass
class WorkerResult:
    schema: str
    worker_id: str
    task_id: str
    role: str
    status: str
    changed_files: list[str]
    commit: str | None
    summary: str
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    method_audit: dict[str, Any] = field(default_factory=dict)
    residual_risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunContract:
    run_id: str
    workspace_id: str
    repo_root: str
    base_commit_sha: str
    spec: dict[str, Any]
    plan: dict[str, Any]
    tasks: tuple[dict[str, Any], ...]
    adapter: str
    model_profile: str
    policy: dict[str, Any]
    coverage: dict[str, list[str]]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactGraphNode:
    id: str
    kind: str
    status: str
    path: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReconciliationAction:
    target: str
    action: str
    reason: str
    writes: bool = False
