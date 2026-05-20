from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .models import TaskSpec
from .plan_parser import PlanParseError, parse_plan
from .spec_refs import SpecRefResolver


FORBIDDEN_OWNED_PREFIXES = ("graphify-out/", ".git/", ".agentrunway/")
VALID_RISKS = {"low", "medium", "high"}


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str
    task_id: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LintResult:
    ok: bool
    errors: list[LintIssue]
    warnings: list[LintIssue]
    task_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "task_count": self.task_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_code_changing(task: TaskSpec) -> bool:
    return any(claim.mode in {"owned", "shared_append"} for claim in task.file_claims)


def _is_broad_glob(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized.endswith("/**") or "/**/" in normalized


def _is_forbidden_owned_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in FORBIDDEN_OWNED_PREFIXES)


def _path_overlaps(left: str, right: str) -> bool:
    left = _normalize_path(left)
    right = _normalize_path(right)
    if left == right:
        return True
    if fnmatch.fnmatchcase(left, right) or fnmatch.fnmatchcase(right, left):
        return True
    if left.endswith("/**") and right.startswith(left[:-3].rstrip("/") + "/"):
        return True
    if right.endswith("/**") and left.startswith(right[:-3].rstrip("/") + "/"):
        return True
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return left_path.match(right) or right_path.match(left)


def _dependency_closure(tasks: list[TaskSpec]) -> dict[str, set[str]]:
    by_id = {task.task_id: task for task in tasks}
    closure: dict[str, set[str]] = {}

    def collect(task_id: str, seen: set[str]) -> set[str]:
        if task_id in closure:
            return set(closure[task_id])
        if task_id in seen or task_id not in by_id:
            return set()
        dependencies: set[str] = set()
        for dependency in by_id[task_id].dependencies:
            dependencies.add(dependency)
            dependencies.update(collect(dependency, {*seen, task_id}))
        closure[task_id] = dependencies
        return set(dependencies)

    for task in tasks:
        collect(task.task_id, set())
    return closure


def _tasks_are_dependency_ordered(left: str, right: str, closure: dict[str, set[str]]) -> bool:
    return left in closure.get(right, set()) or right in closure.get(left, set())


def _dependency_errors(tasks: list[TaskSpec]) -> list[LintIssue]:
    ids = {task.task_id for task in tasks}
    errors: list[LintIssue] = []
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in ids:
                errors.append(
                    LintIssue(
                        code="unknown_dependency",
                        message=f"{task.task_id} depends on missing task {dependency}",
                        task_id=task.task_id,
                    )
                )
    return errors


def _cycle_errors(tasks: list[TaskSpec]) -> list[LintIssue]:
    by_id = {task.task_id: task for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    errors: list[LintIssue] = []

    def visit(task_id: str, chain: list[str]) -> None:
        if task_id in visited or task_id not in by_id:
            return
        if task_id in visiting:
            errors.append(
                LintIssue(
                    code="dependency_cycle",
                    message="dependency cycle: " + " -> ".join([*chain, task_id]),
                    task_id=task_id,
                )
            )
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].dependencies:
            visit(dependency, [*chain, task_id])
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task.task_id, [])
    return errors


def _claim_errors(tasks: list[TaskSpec]) -> list[LintIssue]:
    errors: list[LintIssue] = []
    owned_claims: list[tuple[str, str]] = []
    closure = _dependency_closure(tasks)
    for task in tasks:
        if task.phase == "implementation" and not task.file_claims:
            errors.append(
                LintIssue(
                    code="missing_file_claims",
                    message=f"{task.task_id} is an implementation task but has no file claims",
                    task_id=task.task_id,
                )
            )
        if _is_code_changing(task) and not task.acceptance_commands:
            errors.append(
                LintIssue(
                    code="missing_acceptance_commands",
                    message=f"{task.task_id} changes code but has no acceptance commands",
                    task_id=task.task_id,
                )
            )
        for claim in task.file_claims:
            normalized = _normalize_path(claim.path)
            if claim.mode == "owned" and _is_forbidden_owned_path(normalized):
                errors.append(
                    LintIssue(
                        code="forbidden_owned_path",
                        message=f"{task.task_id} claims forbidden path {claim.path}",
                        task_id=task.task_id,
                        path=claim.path,
                    )
                )
            if claim.mode == "owned" and _is_broad_glob(normalized) and task.risk != "high":
                errors.append(
                    LintIssue(
                        code="broad_glob_requires_high_risk",
                        message=f"{task.task_id} has broad owned claim {claim.path} without high risk",
                        task_id=task.task_id,
                        path=claim.path,
                    )
                )
            if claim.mode == "owned":
                for previous_task_id, previous_path in owned_claims:
                    if previous_task_id != task.task_id and _path_overlaps(previous_path, normalized):
                        if not _tasks_are_dependency_ordered(previous_task_id, task.task_id, closure):
                            errors.append(
                                LintIssue(
                                    code="owned_claim_conflict",
                                    message=(
                                        f"{claim.path} overlaps owned claim {previous_path} "
                                        f"from {previous_task_id}"
                                    ),
                                    task_id=task.task_id,
                                    path=claim.path,
                                )
                            )
                owned_claims.append((task.task_id, normalized))
    return errors


def _canonical_suggestion(resolver: SpecRefResolver, suggestion: str | None) -> str | None:
    if suggestion is None:
        return None
    resolution = resolver.resolve_one(suggestion)
    return resolution.canonical_ref or suggestion


def _spec_ref_errors(tasks: list[TaskSpec], spec_path: Path | None) -> list[LintIssue]:
    if spec_path is None:
        return []
    resolver = SpecRefResolver.from_spec(spec_path)
    errors: list[LintIssue] = []
    for task in tasks:
        for ref in task.spec_refs:
            if not ref:
                continue
            resolution = resolver.resolve_one(ref)
            if resolution.status == "unresolved":
                suggestion = _canonical_suggestion(resolver, resolution.suggestion)
                suggestion_text = f" suggestion={suggestion}" if suggestion else ""
                errors.append(
                    LintIssue(
                        code="unresolved_spec_ref",
                        message=f"unresolved_spec_ref task={task.task_id} ref={ref}{suggestion_text}",
                        task_id=task.task_id,
                    )
                )
    return errors


def lint_plan(*, plan_path: Path, spec_path: Path | None = None) -> LintResult:
    try:
        tasks = parse_plan(plan_path)
    except PlanParseError as exc:
        return LintResult(
            ok=False,
            errors=[LintIssue(code="missing_task_block", message=str(exc))],
            warnings=[],
            task_count=0,
        )

    errors: list[LintIssue] = []
    warnings: list[LintIssue] = []
    if not tasks:
        errors.append(LintIssue(code="missing_task_block", message="plan has no agentrunway-task blocks"))

    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            errors.append(
                LintIssue(
                    code="duplicate_task_id",
                    message=f"duplicate task id {task.task_id}",
                    task_id=task.task_id,
                )
            )
        seen.add(task.task_id)
        if task.risk not in VALID_RISKS:
            errors.append(
                LintIssue(
                    code="invalid_risk",
                    message=f"{task.task_id} has invalid risk {task.risk}",
                    task_id=task.task_id,
                )
            )

    errors.extend(_dependency_errors(tasks))
    errors.extend(_cycle_errors(tasks))
    errors.extend(_claim_errors(tasks))
    errors.extend(_spec_ref_errors(tasks, spec_path))
    return LintResult(ok=not errors, errors=errors, warnings=warnings, task_count=len(tasks))
