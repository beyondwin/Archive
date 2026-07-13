"""Read-only compilation and preflight for CPE v3 runs."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from audit_plan_executability import assert_plan_executable
from audit_superpowers_compatibility import assert_superpowers_compatible
from build_spec_manifest import build_manifest as build_spec_manifest
from parse_plan import parse_plan

from .document_set import DocumentSet, DocumentSetBlocked, compile_document_set
from .manifest import sha256_bytes, sha256_file
from .task_contracts import compile_task_contract


FORBIDDEN_RUNTIME_PATHS = ("run_manifest.json", "events.jsonl", "state.json")
DANGEROUS_COMMAND_RE = re.compile(
    r"^\s*(?:sudo\b|rm\s+-rf\b|git\s+push\b|git\s+reset\s+--hard\b|"
    r"kubectl\s+(?:apply|delete)\b|terraform\s+apply\b|aws\s+.*(?:delete|terminate))",
    re.IGNORECASE,
)
COMMAND_BOUNDARY_RE = re.compile(r"(?:\r\n?|\n|&&|\|\||[;&|])")


@dataclass(frozen=True)
class InputSource:
    role: str
    source_path: Path
    sha256: str
    content: bytes


@dataclass(frozen=True)
class CompiledRun:
    tasks: tuple[dict[str, object], ...]
    spec_manifest: dict[str, object] | None
    sources: tuple[InputSource, ...]
    source_head: str
    source_status: tuple[str, ...]
    document_set: DocumentSet


class CompileBlocked(ValueError):
    def __init__(self, category: str, summary: str, evidence: dict[str, object]):
        super().__init__(summary)
        self.category = category
        self.summary = summary
        self.evidence = evidence


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_git_basis(workspace: Path) -> tuple[str, tuple[str, ...]]:
    workspace = workspace.expanduser().resolve()
    root = _run(["git", "rev-parse", "--show-toplevel"], workspace)
    if root.returncode or Path(root.stdout.strip()).resolve() != workspace:
        raise CompileBlocked(
            "git_basis_invalid",
            "workspace must be a git repository root",
            {"workspace": str(workspace), "stderr": root.stderr.strip()},
        )
    head = _run(["git", "rev-parse", "HEAD"], workspace)
    status = _run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], workspace)
    if head.returncode or status.returncode:
        raise CompileBlocked(
            "git_basis_invalid",
            "git basis could not be read",
            {"head_stderr": head.stderr.strip(), "status_stderr": status.stderr.strip()},
        )
    return head.stdout.strip(), _parse_porcelain_z(status.stdout)


def _parse_porcelain_z(output: str) -> tuple[str, ...]:
    records = output.split("\0")
    parsed: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        if len(record) < 4 or record[2] != " ":
            raise CompileBlocked(
                "git_basis_invalid",
                "git status returned a malformed porcelain record",
                {"record": record},
            )
        status = record[:2]
        parsed.append(f"{status} {record[3:]}")
        index += 1
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise CompileBlocked(
                    "git_basis_invalid",
                    "git status rename record is incomplete",
                    {"record": record},
                )
            parsed.append(f"{status} {records[index]}")
            index += 1
    return tuple(parsed)


def compile_tasks(
    parsed: dict[str, object],
    spec_manifest: dict[str, object] | None,
    spec_content: bytes | None = None,
) -> tuple[dict[str, object], ...]:
    sections = (spec_manifest or {}).get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    plan_path = Path(str(parsed.get("plan", "")))
    plan_hash = sha256_file(plan_path)
    compiled: list[dict[str, object]] = []
    raw_tasks = parsed.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise CompileBlocked("plan_invalid", "parsed plan tasks must be a list", {"plan": str(plan_path)})

    for raw in raw_tasks:
        if not isinstance(raw, dict):
            raise CompileBlocked("plan_invalid", "parsed plan task must be an object", {"task": raw})
        task_id = str(raw.get("id") or "")
        refs = [str(item) for item in raw.get("spec_refs", [])]
        if spec_manifest is not None and not refs:
            raise CompileBlocked(
                "missing_explicit_spec_mapping",
                f"{task_id} has no explicit spec mapping",
                {"task_id": task_id},
            )
        unknown = [ref for ref in refs if ref not in sections]
        if unknown:
            raise CompileBlocked(
                "unknown_spec_refs",
                f"{task_id} references unknown spec sections",
                {"task_id": task_id, "unknown_spec_refs": unknown},
            )
        files = [str(item) for item in raw.get("files", [])]
        if not files:
            raise CompileBlocked("files_missing", f"{task_id} has no file claims", {"task_id": task_id})
        command = str(raw.get("acceptance_command") or "").strip()
        if not command:
            raise CompileBlocked(
                "acceptance_command_missing",
                f"{task_id} has no acceptance command",
                {"task_id": task_id},
            )
        selected_hashes = {
            ref: str(sections[ref].get("sha256", ""))
            for ref in refs
            if isinstance(sections.get(ref), dict)
        }
        selected_sections: list[dict[str, str]] = []
        if refs:
            if spec_content is None:
                raise CompileBlocked(
                    "spec_snapshot_missing",
                    f"{task_id} cannot compile spec excerpts without a spec snapshot",
                    {"task_id": task_id},
                )
            spec_lines = spec_content.decode("utf-8").splitlines(keepends=True)
            for ref in refs:
                section = sections[ref]
                if not isinstance(section, dict):
                    continue
                start = int(section.get("line_start", 1))
                end = int(section.get("line_end", start))
                text = "".join(spec_lines[start - 1 : end])
                actual = sha256_bytes(text.encode("utf-8"))
                if actual != selected_hashes.get(ref):
                    raise CompileBlocked(
                        "spec_section_digest_mismatch",
                        f"{task_id} spec excerpt digest changed",
                        {"task_id": task_id, "spec_ref": ref},
                    )
                selected_sections.append({"id": ref, "sha256": actual, "text": text})
        compiled_task = {
            "id": task_id,
            "title": str(raw.get("title") or task_id),
            "dependencies": [str(item) for item in raw.get("depends_on", [])],
            "file_claims": files,
            "spec_refs": refs,
            "acceptance_command": command,
            "plan_line": raw.get("line"),
            "prompt": str(raw.get("body") or task_id),
            "execution_contract": {
                "allowed_paths": files,
                "forbidden_paths": list(FORBIDDEN_RUNTIME_PATHS),
                "acceptance_command": command,
            },
            "source_hashes": {"plan": plan_hash, "spec_sections": selected_hashes},
            "operator_reviewed": raw.get("operator_reviewed") is True,
            "operator_decision": raw.get("operator_decision"),
            "task_type": raw.get("task_type") or "tdd_implementation",
            "risk_class": raw.get("risk_class"),
            "task_source": raw.get("task_source"),
            "forbidden_paths": raw.get("forbidden_paths") or list(FORBIDDEN_RUNTIME_PATHS),
            "required_methods": raw.get("required_methods") or [],
            "required_evidence": raw.get("required_evidence") or [],
            "checkpoint_message": raw.get("checkpoint_message"),
        }
        try:
            contract = compile_task_contract(
                compiled_task,
                spec_sections=tuple(selected_sections),
                source_hashes=compiled_task["source_hashes"],
            )
        except ValueError as exc:
            raise CompileBlocked(
                "task_contract_invalid",
                f"{task_id} task contract is invalid",
                {"task_id": task_id, "error": str(exc)},
            ) from None
        compiled_task["task_contract"] = contract.body()
        compiled_task["task_contract_sha256"] = contract.contract_sha256
        compiled.append(compiled_task)

    ids = {str(task["id"]) for task in compiled}
    for task in compiled:
        unknown_dependencies = sorted(set(task["dependencies"]) - ids)
        if unknown_dependencies:
            raise CompileBlocked(
                "unknown_dependencies",
                f"{task['id']} has unknown dependencies",
                {"task_id": task["id"], "unknown_dependencies": unknown_dependencies},
            )
    return tuple(compiled)


def assert_safe_commands(tasks: tuple[dict[str, object], ...]) -> None:
    for task in tasks:
        command = str(task.get("acceptance_command") or "")
        segments = (segment for segment in COMMAND_BOUNDARY_RE.split(command) if segment.strip())
        if any(DANGEROUS_COMMAND_RE.search(segment) for segment in segments):
            raise CompileBlocked(
                "operator_review_required",
                f"{task['id']} acceptance command requires operator review",
                {"task_id": task["id"], "acceptance_command": command},
            )


def _dirty_path(status_line: str) -> str | None:
    if len(status_line) < 4:
        return None
    return status_line[3:].split(" -> ")[-1]


def _matches_claim(path: str, claim: str) -> bool:
    if path == claim:
        return True
    if claim.endswith("/**") and path.startswith(claim[:-3].rstrip("/") + "/"):
        return True
    return PurePosixPath(path).match(claim)


def assert_clean_claimed_scope(
    status: tuple[str, ...],
    tasks: tuple[dict[str, object], ...],
) -> None:
    claims = [str(path) for task in tasks for path in task.get("file_claims", [])]
    dirty = [path for line in status if (path := _dirty_path(line))]
    overlap = sorted(path for path in dirty if any(_matches_claim(path, claim) for claim in claims))
    if overlap:
        raise CompileBlocked(
            "related_dirty_scope",
            "claimed task paths already contain source changes",
            {"paths": overlap},
        )


def snapshot_source_bytes(document_set: DocumentSet) -> tuple[InputSource, ...]:
    """Adapt immutable vNext documents for current packet/manifest consumers."""

    role_order = {"plan": 0, "spec": 1, "program": 2, "doc": 3}
    ordered = sorted(
        enumerate(document_set.documents),
        key=lambda item: (role_order[item[1].kind], item[0]),
    )
    return tuple(
        InputSource(document.kind, document.path, document.sha256, document.content)
        for _, document in ordered
    )


def compile_run(
    *,
    plans: tuple[Path, ...] | None = None,
    program_plan: Path | None = None,
    spec: Path | None,
    docs: tuple[Path, ...],
    workspace: Path,
    mode: str,
    **legacy: object,
) -> CompiledRun:
    legacy_plan = legacy.pop("plan", None)
    if legacy:
        unexpected = next(iter(legacy))
        raise TypeError(f"compile_run() got an unexpected keyword argument {unexpected!r}")
    if legacy_plan is not None:
        if plans is not None:
            raise TypeError("compile_run() accepts either plans or legacy plan, not both")
        if not isinstance(legacy_plan, Path):
            raise TypeError("compile_run() legacy plan must be a pathlib.Path")
        plans = (legacy_plan,)
    if plans is None:
        raise TypeError("compile_run() missing required keyword-only argument: 'plans'")
    workspace = workspace.expanduser().resolve()
    plans = tuple(plan.expanduser().resolve() for plan in plans)
    program_plan = program_plan.expanduser().resolve() if program_plan else None
    spec = spec.expanduser().resolve() if spec else None
    docs = tuple(path.expanduser().resolve() for path in docs)
    try:
        document_set = compile_document_set(spec, plans, program_plan, docs)
    except DocumentSetBlocked as exc:
        raise CompileBlocked(
            "document_set_invalid",
            exc.summary,
            {"reason": exc.category, **exc.evidence},
        ) from None
    head, status = read_git_basis(workspace)
    parsed_plans: list[tuple[Path, dict[str, object]]] = []
    for plan in plans:
        try:
            parsed_plans.append((plan, parse_plan(plan, workspace, mode)))
        except SystemExit as exc:
            raise CompileBlocked(
                "plan_parse_failed",
                "plan could not be parsed for execution",
                {"plan": str(plan), "exit_code": exc.code},
            ) from None
    try:
        spec_manifest = build_spec_manifest(spec) if spec else None
    except SystemExit as exc:
        raise CompileBlocked(
            "spec_parse_failed",
            "specification could not be compiled",
            {"spec": str(spec), "exit_code": exc.code},
        ) from None
    sources = snapshot_source_bytes(document_set)
    spec_content = next((source.content for source in sources if source.role == "spec"), None)
    tasks = tuple(
        task
        for _, parsed in parsed_plans
        for task in compile_tasks(parsed, spec_manifest, spec_content)
    )
    assert_safe_commands(tasks)
    assert_clean_claimed_scope(status, tasks)
    for plan, _ in parsed_plans:
        assert_superpowers_compatible(plan, workspace)
        assert_plan_executable(plan, spec, workspace)
    return CompiledRun(tasks, spec_manifest, sources, head, status, document_set)
