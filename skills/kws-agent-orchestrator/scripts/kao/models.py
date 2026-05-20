from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


KAO_VERSION = "0.1.0"
TASK_PACKET_SCHEMA = "kws.kao.task_packet.v1"
RESULT_SCHEMA = "kws.kao.worker_result.v1"
REVIEW_SCHEMA = "kws.kao.review_result.v1"
VERIFICATION_SCHEMA = "kws.kao.verification_result.v1"
EVENT_SCHEMA = "kws.kao.event.v1"

CLAIM_MODES = {"owned", "shared_append", "consumes", "read_only", "forbidden"}
OUTCOMES = {"finished", "failed", "blocked", "cancelled", "unknown"}
AGENTLENS_OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}
REASONING_LEVELS = {"lowest", "low", "medium", "high", "highest"}


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    MERGED = "merged"
    FAILED = "failed"
    BLOCKED = "blocked"


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
