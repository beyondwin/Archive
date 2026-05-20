from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Mapping

from .models import RunContract, TaskSpec
from .plan_parser import canonical_hash, parse_spec_manifest
from .spec_refs import SpecRefResolver


class ContractError(ValueError):
    pass


NON_LOCAL_ADAPTERS = {"codex", "claude"}


def parse_spec_manifest_sections(spec_path: Path) -> dict[str, str]:
    manifest = parse_spec_manifest(spec_path)
    sections = {
        section_id: data["title"]
        for section_id, data in manifest["sections"].items()
    }
    if not sections:
        raise ContractError(f"spec manifest is missing or empty: {spec_path}")
    return sections


def _task_to_contract(task: TaskSpec) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "risk": task.risk,
        "phase": task.phase,
        "dependencies": list(task.dependencies),
        "spec_refs": list(task.spec_refs),
        "file_claims": [{"path": claim.path, "mode": claim.mode} for claim in task.file_claims],
        "acceptance_commands": list(task.acceptance_commands),
        "resource_keys": list(task.resource_keys),
        "required_skills": list(task.required_skills),
        "serial": task.serial,
        "line": task.line,
    }


def _load_manifest_sections(spec_path: Path) -> dict[str, dict[str, object]]:
    manifest = parse_spec_manifest(spec_path)
    sections = manifest["sections"]
    if not sections:
        raise ContractError(f"spec manifest is missing or empty: {spec_path}")
    return sections


def _canonicalize_task_refs(
    tasks: list[TaskSpec],
    sections: Mapping[str, Mapping[str, object]],
) -> tuple[list[TaskSpec], list[tuple[str, str]]]:
    resolver = SpecRefResolver(sections)
    canonical_tasks: list[TaskSpec] = []
    missing_refs: list[tuple[str, str]] = []
    for task in tasks:
        canonical_refs: list[str] = []
        for ref in task.spec_refs:
            resolution = resolver.resolve_one(ref)
            if resolution.status == "unresolved" or resolution.canonical_ref is None:
                missing_refs.append((task.task_id, ref))
                continue
            if not resolution.text.strip():
                raise ContractError(f"empty spec_ref text: {task.task_id} -> {resolution.canonical_ref}")
            canonical_refs.append(resolution.canonical_ref)
        canonical_tasks.append(replace(task, spec_refs=tuple(canonical_refs)))
    return canonical_tasks, missing_refs


def canonicalize_task_spec_refs(tasks: list[TaskSpec], spec_path: Path | None) -> list[TaskSpec]:
    if spec_path is None:
        return tasks
    sections = _load_manifest_sections(spec_path)
    canonical_tasks, missing_refs = _canonicalize_task_refs(tasks, sections)
    if missing_refs:
        by_task: dict[str, list[str]] = {}
        for task_id, ref in missing_refs:
            by_task.setdefault(task_id, []).append(ref)
        first_task_id, refs = next(iter(by_task.items()))
        raise ContractError(f"missing spec_refs: {first_task_id} -> {', '.join(refs)}")
    return canonical_tasks


def _validate_tasks(tasks: list[TaskSpec], manifest_sections: dict[str, str]) -> tuple[dict[str, list[str]], tuple[str, ...]]:
    covered: set[str] = set()
    warnings: list[str] = []
    for task in tasks:
        if not task.acceptance_commands or any(not command.strip() for command in task.acceptance_commands):
            raise ContractError(f"{task.task_id} has no acceptance commands")
        if task.phase == "implementation" and not task.file_claims:
            raise ContractError(f"{task.task_id} has no file claims")
        for claim in task.file_claims:
            if claim.path in {"*", "**", "**/*"}:
                warnings.append(f"{task.task_id} has broad file claim {claim.path}")
        covered.update(task.spec_refs)
    unreferenced = sorted(set(manifest_sections) - covered)
    warnings.extend(f"unreferenced spec section {ref}" for ref in unreferenced)
    return {"covered": sorted(covered), "partial": [], "blocked": [], "unreferenced": unreferenced}, tuple(warnings)


def build_run_contract(
    *,
    run_id: str,
    workspace_id: str,
    repo_root: Path,
    spec_path: Path | None,
    plan_path: Path,
    base_commit_sha: str,
    tasks: list[TaskSpec],
    adapter: str,
    model_profile: str,
    allow_dirty_source: bool,
    apply_to_source: bool,
) -> RunContract:
    if spec_path is None:
        if adapter in NON_LOCAL_ADAPTERS:
            raise ContractError(f"non-local adapter requires --spec: adapter={adapter}")
        coverage = {"covered": [], "partial": [], "blocked": [], "unreferenced": []}
        warnings: tuple[str, ...] = ()
        spec_entry: dict[str, object] = {"path": None, "hash": None, "manifest_sections": {}}
    else:
        sections = _load_manifest_sections(spec_path)
        manifest_sections = {section_id: str(data["title"]) for section_id, data in sections.items()}
        tasks, missing_refs = _canonicalize_task_refs(tasks, sections)
        if missing_refs:
            by_task: dict[str, list[str]] = {}
            for task_id, ref in missing_refs:
                by_task.setdefault(task_id, []).append(ref)
            first_task_id, refs = next(iter(by_task.items()))
            raise ContractError(f"missing spec_refs: {first_task_id} -> {', '.join(refs)}")
        coverage, warnings = _validate_tasks(tasks, manifest_sections)
        spec_entry = {
            "path": str(spec_path),
            "hash": canonical_hash(spec_path),
            "manifest_sections": manifest_sections,
        }
    return RunContract(
        run_id=run_id,
        workspace_id=workspace_id,
        repo_root=str(repo_root),
        base_commit_sha=base_commit_sha,
        spec=spec_entry,
        plan={
            "path": str(plan_path),
            "hash": canonical_hash(plan_path),
            "task_count": len(tasks),
        },
        tasks=tuple(_task_to_contract(task) for task in tasks),
        adapter=adapter,
        model_profile=model_profile,
        policy={
            "allow_dirty_source": bool(allow_dirty_source),
            "apply_to_source": bool(apply_to_source),
        },
        coverage=coverage,
        warnings=warnings,
    )


def write_contract(run_dir: Path, contract: RunContract) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "contract.json"
    if path.exists():
        raise ContractError(f"contract already exists: {path}")
    path.write_text(json.dumps(asdict(contract), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
