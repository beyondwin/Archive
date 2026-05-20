from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import ModelProfile
from .models import RESULT_SCHEMA, TASK_PACKET_SCHEMA, TaskPacket, TaskSpec


DEFAULT_FORBIDDEN_GLOBS = (".git/**", "graphify-out/**", ".agentrunway/**")


def build_task_packet(run_id: str, task: TaskSpec, spec_refs: list[dict[str, str]], profile: ModelProfile) -> TaskPacket:
    allowed = tuple(claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"})
    model = profile.workers.get("default", profile.orchestrator)
    return TaskPacket(
        schema=TASK_PACKET_SCHEMA,
        run_id=run_id,
        task_id=task.task_id,
        role="implementer",
        objective=task.objective or task.title,
        spec_refs=tuple(spec_refs),
        dependencies=task.dependencies,
        allowed_write_globs=allowed,
        forbidden_write_globs=DEFAULT_FORBIDDEN_GLOBS,
        file_claims=task.file_claims,
        required_skills=task.required_skills,
        acceptance_commands=task.acceptance_commands,
        output_schema=RESULT_SCHEMA,
        model_assignment=model,
    )


def packet_to_json(packet: TaskPacket) -> str:
    return json.dumps(asdict(packet), ensure_ascii=False, indent=2, sort_keys=True)


def materialize_prompt(packet: TaskPacket, prompt_dir: Path) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{packet.task_id}.implementer.prompt.txt"
    path.write_text(
        "Use using-superpowers and test-driven-development. Return only worker_result JSON matching this packet.\n\n"
        "```json\n"
        + packet_to_json(packet)
        + "\n```\n",
        encoding="utf-8",
    )
    return path


def materialize_worker_prompt(
    packet: TaskPacket,
    packet_path: Path,
    output_path: Path,
    prompt_dir: Path,
    context: dict[str, object] | None = None,
) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    worker_id = output_path.parent.name if output_path.parent.name else packet.role
    path = prompt_dir / f"{packet.task_id}.{worker_id}.{packet.role}.prompt.txt"
    context_text = ""
    if context:
        context_text = (
            "\nRetry context JSON:\n"
            "```json\n"
            + json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```\n"
        )
    path.write_text(
        "You are an AgentRunway worker. Complete the task described by the task packet below.\n"
        f"Packet path: {packet_path}\n"
        f"Output path: {output_path}\n"
        "Use using-superpowers. Code-changing implementers must use test-driven-development.\n"
        "Commit your changes before writing the result artifact.\n"
        "Write worker_result JSON to the output path with required fields: "
        "schema, worker_id, task_id, role, status, changed_files, summary, method_audit.\n"
        f"Use schema value {packet.output_schema!r}; status must be success, simulated_success, failed, blocked, or malformed.\n\n"
        "```json\n"
        + packet_to_json(packet)
        + "\n```\n"
        + context_text,
        encoding="utf-8",
    )
    return path


def materialize_role_prompt(
    *,
    role: str,
    task: TaskSpec,
    worker_id: str,
    packet_path: Path,
    output_path: Path,
    prompt_dir: Path,
    context: dict[str, object],
) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    schema = "agentrunway.review_result.v1" if role == "reviewer" else "agentrunway.verification_result.v1"
    path = prompt_dir / f"{task.task_id}.{role}.{worker_id}.prompt.txt"
    role_instructions = (
        "Reviewer statuses are approved, changes_requested, rejected, or needs_context. "
        "Include review_mode as diff or full_tree.\n"
        if role == "reviewer"
        else ""
    )
    path.write_text(
        f"You are an AgentRunway {role}. Use using-superpowers.\n"
        f"Task: {task.task_id} - {task.title}\n"
        f"Packet path: {packet_path}\n"
        f"Output path: {output_path}\n"
        f"Write JSON with schema {schema}.\n"
        f"{role_instructions}"
        "Context JSON:\n"
        "```json\n"
        + json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n",
        encoding="utf-8",
    )
    return path
