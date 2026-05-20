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
