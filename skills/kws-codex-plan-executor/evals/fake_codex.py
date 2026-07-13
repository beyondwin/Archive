#!/usr/bin/env python3
"""Deterministic, network-free Codex boundary for lean schema-4 CPE evals."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path


WRITE_ROLES = frozenset({"task_agent", "fix_agent", "integration_fix_agent"})
VERDICT_ROLES = frozenset(
    {"reviewer", "document_auditor", "program_final_integrator"}
)
SCENARIOS = frozenset(
    {
        "success",
        "review_changes_requested",
        "ordinary_failure",
        "authority",
        "timeout",
        "timeout_leader_exits_descendant_survives",
        "dirty_handoff",
        "wrong_commit",
        "tampered_artifact_path",
        "mapping_success",
        "mapping_unmapped",
        "mapping_conflict",
        "mapping_bad_excerpt",
        "mapping_extra_artifact",
        "mapping_unreported_extra_artifact",
        "mapping_partial_failure",
        "mapping_invalid_companion",
        "mapping_noncompleted_result",
        "mapping_lossy_split",
        "mapping_weaken_candidate",
        "mapping_brief_omits_requirement",
        "mapping_brief_substitutes_requirement",
        "mapping_split_brief_substitutes_requirement",
        "mapping_success_retry_variant",
        "mapping_many_tasks",
        "queue_success",
        "queue_review_fix",
        "queue_ordinary_failure",
        "queue_test_failure",
        "queue_authority",
        "queue_review_crash",
        "queue_fix_review_crash",
        "queue_repeated_review_finding",
        "queue_unchanged_strategy",
        "queue_historical_strategy",
        "queue_invalid_authority",
        "queue_repeated_unusable_strategy",
        "final_success",
        "refresh_success",
        "final_auditor_blocked",
        "final_stale_commit",
        "final_failed_terminal",
        "final_integration_fix",
        "final_integrator_crash",
        "final_integrator_timeout",
        "final_pass_with_finding",
        "final_forged_handoff",
        "writer_hold",
    }
)


def _value(argv: list[str], flag: str) -> str:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"fake codex missing launcher argument: {flag}") from exc


def _prompt_value(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", prompt, flags=re.MULTILINE)
    if match is None:
        raise SystemExit(f"fake codex missing prompt marker: {name}")
    return match.group(1).strip()


def _prompt_inputs(prompt: str) -> list[str]:
    marker = "Exact input paths:\n"
    if marker not in prompt:
        raise SystemExit("fake codex missing exact input paths")
    block = prompt.split(marker, 1)[1].split("\n\n", 1)[0]
    values = [line[2:] for line in block.splitlines() if line.startswith("- ")]
    if not values:
        raise SystemExit("fake codex received no exact input paths")
    return values


def _prompt_strategy(prompt: str) -> str:
    match = re.search(r"^Strategy key:\s*(.+)$", prompt, flags=re.MULTILINE)
    return match.group(1).strip() if match is not None else "initial"


def _git(worktree: Path, *arguments: str) -> str:
    declared = os.environ.get("CPE_FAKE_GIT_BIN")
    git_bin = declared or ("/usr/bin/git" if Path("/usr/bin/git").is_file() else "git")
    completed = subprocess.run(
        [git_bin, "-C", str(worktree), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _write_report(outbox: Path, report_path: str) -> None:
    target = outbox / report_path
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(b"deterministic child report\n")
    target.chmod(0o600)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(outbox: Path, relative_path: str, payload: object) -> None:
    target = outbox / relative_path
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(_canonical_json(payload))
    target.chmod(0o600)


def _log_invocation(argv: list[str], prompt: str) -> None:
    declared = os.environ.get("CPE_FAKE_INVOCATION_LOG")
    if not declared:
        return
    names = {
        "PATH",
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
    }
    payload = {
        "argv": argv,
        "env": {key: value for key, value in os.environ.items() if key in names},
        "prompt": prompt,
        "role": _prompt_value(prompt, "CPE_ROLE"),
        "item_id": _prompt_value(prompt, "ITEM"),
        "input_paths": _prompt_inputs(prompt),
    }
    with Path(declared).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _commit_change(worktree: Path, item_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", item_id)
    relative = f"cpe-{safe}.txt"
    parent = _git(worktree, "rev-parse", "HEAD")
    (worktree / relative).write_text(
        f"deterministic write role change after {parent}\n", encoding="utf-8"
    )
    _git(worktree, "add", "--", relative)
    _git(worktree, "commit", "-q", "-m", f"fake cpe {safe}")
    return _git(worktree, "rev-parse", "HEAD")


def _queue_invocation_number(role: str) -> int:
    declared = os.environ.get("CPE_FAKE_QUEUE_STATE")
    if not declared:
        return 1
    path = Path(declared)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {}
    count = int(payload.get(role, 0)) + 1
    payload[role] = count
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)
    return count


def _append_verification_invocation(revision: str, command: str) -> None:
    declared = os.environ.get("CPE_FAKE_VERIFICATION_LOG")
    if not declared:
        return
    with Path(declared).open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"revision": revision, "command": command}, sort_keys=True
            )
            + "\n"
        )


def _json_inputs(input_paths: list[str]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for value in input_paths:
        path = Path(value)
        if path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _final_audit_result(
    *,
    scenario: str,
    item_id: str,
    input_paths: list[str],
    worktree: Path,
    outbox: Path,
    report_path: str,
) -> tuple[str, str, list[str]]:
    source = Path(input_paths[0]).read_bytes()
    document_map = next(
        (
            payload
            for payload in _json_inputs(input_paths)
            if payload.get("document_id") == item_id
            and isinstance(payload.get("requirements"), list)
        ),
        None,
    )
    if document_map is None:
        raise SystemExit("document auditor received no matching document map")
    requirements = [
        str(requirement["requirement_id"])
        for requirement in document_map["requirements"]
        if isinstance(requirement, dict) and requirement.get("kind") == "normative"
    ]
    blocked = scenario == "final_auditor_blocked" and item_id == "spec-01"
    revision = _git(worktree, "rev-parse", "HEAD")
    audit_verdict = "blocked" if blocked else "pass"
    _write_json(
        outbox,
        report_path,
        {
            "schema_version": 1,
            "document_id": item_id,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "revision": revision,
            "coverage_verdicts": {
                requirement_id: audit_verdict for requirement_id in requirements
            },
            "missing_requirements": requirements if blocked else [],
            "conflicts": [],
            "verdict": audit_verdict,
        },
    )
    return revision, audit_verdict, [report_path]


def _final_integration_result(
    *,
    scenario: str,
    queue_number: int,
    input_paths: list[str],
    worktree: Path,
    outbox: Path,
    report_path: str,
) -> tuple[str, str, str, list[str]]:
    revision = _git(worktree, "rev-parse", "HEAD")
    if scenario == "final_integrator_crash" and queue_number == 1:
        raise SystemExit("deterministic final integrator process interruption")
    audits = [
        payload
        for payload in _json_inputs(input_paths)
        if payload.get("schema_version") == 1
        and isinstance(payload.get("document_id"), str)
        and isinstance(payload.get("coverage_verdicts"), dict)
    ]
    program = next(
        (
            payload
            for payload in _json_inputs(input_paths)
            if isinstance(payload.get("final_verification_commands"), list)
        ),
        None,
    )
    if program is None:
        raise SystemExit("final integrator received no program map")
    whole_paths = [Path(value) for value in input_paths if "whole.patch" in value]
    if len(whole_paths) != 1:
        raise SystemExit("final integrator requires exactly one whole diff")
    artifact_paths = [report_path]
    verification: list[dict[str, object]] = []
    for index, command in enumerate(program["final_verification_commands"], start=1):
        command = str(command)
        _append_verification_invocation(revision, command)
        output_path = (
            f"verification/final/{revision}/commands/command-{index:02d}.log"
        )
        target = outbox / output_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(f"PASS {command}\n", encoding="utf-8")
        target.chmod(0o600)
        artifact_paths.append(output_path)
        verification.append(
            {"command": command, "exit_code": 0, "output_path": output_path}
        )

    if scenario == "final_integration_fix" and queue_number == 1:
        finding_path = f"verification/final/{revision}/integration-findings.json"
        _write_json(
            outbox,
            finding_path,
            {"severity": "Important", "finding": "apply one consolidated fix"},
        )
        artifact_paths.append(finding_path)
        return revision, "changes_requested", "changes_requested", artifact_paths

    if scenario == "final_pass_with_finding":
        finding_path = f"verification/final/{revision}/unexpected-finding.json"
        _write_json(
            outbox,
            finding_path,
            {"severity": "Important", "finding": "must not accompany pass"},
        )
        artifact_paths.append(finding_path)

    terminal_revision = (
        _git(worktree, "rev-parse", "HEAD^")
        if scenario == "final_stale_commit"
        else revision
    )
    _write_json(
        outbox,
        report_path,
        {
            "schema_version": 1,
            "quality_verdict": (
                "failed" if scenario == "final_failed_terminal" else "pass"
            ),
            "revision": terminal_revision,
            "auditor_verdicts": {
                str(audit["document_id"]): str(audit["verdict"])
                for audit in audits
            },
            "verification": (
                [
                    {**record, "exit_code": 1}
                    for record in verification
                ]
                if scenario == "final_failed_terminal"
                else verification
            ),
            "authority_open": [],
            "residual_limitations": [],
            "whole_diff_sha256": hashlib.sha256(whole_paths[0].read_bytes()).hexdigest(),
        },
    )
    if scenario == "final_forged_handoff":
        _write_json(
            outbox,
            f"verification/final/{revision}/integration-handoff.json",
            {"producer": "untrusted-child"},
        )
    return terminal_revision, "completed", "pass", artifact_paths


def _source_entry(
    document_map: dict[str, object], entry: dict[str, object]
) -> dict[str, object]:
    return {
        "document_id": document_map["document_id"],
        "heading": entry["heading"],
        "line_start": entry["line_start"],
        "line_end": entry["line_end"],
        "source_sha256": document_map["source_sha256"],
        "exact_excerpt": entry["exact_excerpt"],
    }


def _bound_statement(
    statement: str, reference: dict[str, object]
) -> dict[str, object]:
    return {
        "statement": statement,
        "source_references": [reference],
        "authority_ids": [],
    }


def _bound_command(command: str, reference: dict[str, object]) -> dict[str, object]:
    return {
        "command": command,
        "source_references": [reference],
        "authority_ids": [],
    }


def _dependency_edge(
    task_id: str, reference: dict[str, object]
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_references": [reference],
        "authority_ids": [],
    }


def _mapping_document_result(
    *, item_id: str, input_paths: list[str], outbox: Path, report_path: str
) -> list[str]:
    snapshots = [
        Path(value)
        for value in input_paths
        if "inputs" in Path(value).parts and Path(value).name != "document-set.json"
    ]
    if len(snapshots) != 1:
        raise SystemExit("document mapper must receive exactly one immutable snapshot")
    snapshot = snapshots[0]
    data = snapshot.read_bytes()
    text = data.decode("utf-8")
    lines = text.splitlines()
    role = "program_plan" if item_id == "program-plan" else item_id.split("-", 1)[0]
    heading = lines[0].lstrip("# ") if lines else item_id
    exact_excerpt = text
    source_ref = {
        "document_id": item_id,
        "heading": heading,
        "line_start": 1,
        "line_end": len(lines),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "exact_excerpt": exact_excerpt,
    }
    requirements: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    verification_commands: list[str] = []
    if role == "spec":
        requirements.append(
            {
                "requirement_id": f"{item_id}:R1",
                "kind": "normative",
                "heading": heading,
                "line_start": 1,
                "line_end": len(lines),
                "exact_excerpt": exact_excerpt,
                "constraints": [
                    _bound_statement(
                        "preserve the immutable approved requirement",
                        source_ref,
                    )
                ],
            }
        )
    elif role == "plan":
        task_numbers = (
            range(1, 61)
            if item_id == "plan-02"
            and os.environ.get("CPE_FAKE_SCENARIO") == "mapping_many_tasks"
            else (1, 2)
            if item_id == "plan-01"
            else (1,)
        )
        for task_number in task_numbers:
            task_id = f"{item_id}:T{task_number}"
            dependency = []
            if task_id == "plan-01:T2":
                dependency = ["plan-01:T1"]
            elif task_id == "plan-02:T1":
                dependency = ["plan-01:T2"]
            candidates.append(
                {
                    "task_id": task_id,
                    "title": f"Implement bounded task {task_id}",
                    "heading": heading,
                    "line_start": 1,
                    "line_end": len(lines),
                    "exact_excerpt": exact_excerpt,
                    "requirement_ids": (
                        ["spec-01:R1"]
                        if task_id == "plan-01:T1"
                        else ["spec-02:R1"]
                        if task_id == "plan-01:T2"
                        else ["spec-01:R1"]
                        if task_id == "plan-02:T1"
                        and os.environ.get("CPE_FAKE_SCENARIO")
                        == "mapping_split_brief_substitutes_requirement"
                        else []
                    ),
                    "dependencies": dependency,
                    "dependency_edges": [
                        _dependency_edge(
                            dependency_id,
                            source_ref,
                        )
                        for dependency_id in dependency
                    ],
                    "acceptance": [
                        _bound_command(
                            "python3 evals/check_lean_mapping.py",
                            source_ref,
                        )
                    ],
                    "global_constraints": [],
                    "upstream_interface_commitments": (
                        [
                            _bound_statement(
                                "preserve the upstream plan-01:T1 interface",
                                source_ref,
                            )
                        ]
                        if task_id == "plan-01:T2"
                        else []
                    ),
                }
            )
    else:
        requirements.append(
            {
                "requirement_id": "program-plan:R1",
                "kind": "decision",
                "heading": heading,
                "line_start": 1,
                "line_end": len(lines),
                "exact_excerpt": exact_excerpt,
                "constraints": [],
            }
        )
        verification_commands = ["python3 evals/check_lean_mapping.py"]
    payload = {
        "schema_version": 1,
        "document_id": item_id,
        "role": role,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "requirements": requirements,
        "task_candidates": candidates,
        "dependencies": [],
        "authority_items": [],
        "verification_commands": verification_commands,
        "plan_wave_graph": {
            "plans": (
                [
                    {
                        "node_id": "plan-01",
                        "member_ids": ["plan-01:T1", "plan-01:T2"],
                        "source_references": [source_ref],
                        "authority_ids": [],
                    },
                    {
                        "node_id": "plan-02",
                        "member_ids": ["plan-02:T1"],
                        "source_references": [source_ref],
                        "authority_ids": [],
                    },
                ]
                if role == "program_plan"
                else []
            ),
            "waves": (
                [
                    {
                        "node_id": "wave-01",
                        "member_ids": ["plan-01"],
                        "source_references": [source_ref],
                        "authority_ids": [],
                    },
                    {
                        "node_id": "wave-02",
                        "member_ids": ["plan-02"],
                        "source_references": [source_ref],
                        "authority_ids": [],
                    },
                ]
                if role == "program_plan"
                else []
            ),
            "edges": (
                [
                    {
                        "predecessor_id": "plan-01",
                        "successor_id": "plan-02",
                        "kind": "plan_order",
                        "source_references": [source_ref],
                        "authority_ids": [],
                    }
                ]
                if role == "program_plan"
                else []
            ),
        },
        "hotspots": (
            [
                {
                    "hotspot_id": f"{item_id}:H1",
                    "kind": "shared_file" if item_id == "plan-01" else "interface",
                    "location": (
                        "src/shared.py" if item_id == "plan-01" else "SharedInterface"
                    ),
                    "task_ids": (
                        ["plan-01:T1", "plan-01:T2"]
                        if item_id == "plan-01"
                        else ["plan-02:T1"]
                    ),
                    "source_references": [source_ref],
                    "authority_ids": [],
                }
            ]
            if item_id in {"plan-01", "plan-02"}
            else []
        ),
        "decisions": (
            [
                {
                    "decision_id": f"{item_id}:D1",
                    "role": role,
                    "kind": "approved",
                    "statement": "preserve the approved immutable requirement",
                    "source_references": [source_ref],
                    "authority_ids": [],
                }
            ]
            if role == "spec"
            else []
        ),
        "constraints": (
            [
                {
                    "constraint_id": f"{item_id}:C1",
                    "role": role,
                    "kind": "global",
                    "affected_ids": [],
                    "statement": "preserve the immutable approved requirement",
                    "source_references": [source_ref],
                    "authority_ids": [],
                }
            ]
            if role == "spec"
            else []
        ),
    }
    if os.environ.get("CPE_FAKE_SCENARIO") == "mapping_bad_excerpt":
        entries = payload["requirements"] or payload["task_candidates"]
        entries[0]["exact_excerpt"] = "not the declared immutable source range"
    _write_json(outbox, report_path, payload)
    return [report_path]


def _mapping_program_result(
    *,
    scenario: str,
    input_paths: list[str],
    outbox: Path,
    report_path: str,
    generation_id: str,
) -> tuple[list[str], list[str]]:
    generation = int(generation_id.removeprefix("generation-"))
    map_paths = [
        Path(value)
        for value in input_paths
        if Path(value).suffix == ".json" and Path(value).parent.name == "documents"
    ]
    if len(map_paths) != 5:
        raise SystemExit("program mapper must receive five document maps")
    maps: dict[str, dict[str, object]] = {}
    map_hashes: dict[str, str] = {}
    for path in map_paths:
        data = path.read_bytes()
        payload = json.loads(data.decode("utf-8"))
        document_id = payload["document_id"]
        maps[document_id] = payload
        map_hashes[document_id] = hashlib.sha256(data).hexdigest()

    candidates = {
        candidate["task_id"]: candidate
        for document_map in maps.values()
        for candidate in document_map["task_candidates"]
    }
    requirements = {
        requirement["requirement_id"]: (document_map, requirement)
        for document_map in maps.values()
        for requirement in document_map["requirements"]
    }
    global_constraint_bindings = [
        {
            "statement": constraint["statement"],
            "source_references": constraint["source_references"],
            "authority_ids": constraint["authority_ids"],
        }
        for document_map in maps.values()
        for constraint in document_map["constraints"]
        if constraint["kind"] == "global" and not constraint["affected_ids"]
    ]
    task_specs = [
        ("plan-01:T1", [], ["plan-01", "spec-01"], ["spec-01:R1"], "plan-01:T1"),
        ("plan-01:T2", ["plan-01:T1"], ["plan-01", "spec-02"], ["spec-02:R1"], "plan-01:T2"),
        ("plan-02:T1", ["plan-01:T2"], ["plan-02", "program-plan"], [], "plan-02:T1"),
    ]
    if scenario == "mapping_many_tasks":
        task_specs.extend(
            (
                f"plan-02:T{task_number}",
                [],
                ["plan-02"],
                [],
                f"plan-02:T{task_number}",
            )
            for task_number in range(2, 61)
        )
    task_splits: list[dict[str, object]] = []
    if scenario in {
        "mapping_lossy_split",
        "mapping_split_brief_substitutes_requirement",
    }:
        split_requirement_ids = (
            ["spec-01:R1"]
            if scenario == "mapping_split_brief_substitutes_requirement"
            else []
        )
        task_specs[-1:] = [
            (
                "plan-02:T1.1",
                ["plan-01:T2"],
                ["plan-02", "program-plan", "spec-01"],
                split_requirement_ids,
                "plan-02:T1",
            ),
            (
                "plan-02:T1.2",
                ["plan-02:T1.1"],
                ["plan-02", "program-plan", "spec-01"],
                split_requirement_ids,
                "plan-02:T1",
            ),
        ]
        task_splits = [
            {
                "source_task_id": "plan-02:T1",
                "split_task_ids": ["plan-02:T1.1", "plan-02:T1.2"],
                "source_references": [_source_entry(maps["plan-02"], candidates["plan-02:T1"])],
                "reason": "bounded context split along an interface boundary",
            }
        ]
    tasks = []
    for task_id, dependencies, document_ids, requirement_ids, source_task_id in task_specs:
        task = {
            "task_id": task_id,
            "title": candidates[source_task_id]["title"],
            "dependencies": dependencies,
            "dependency_edges": [
                _dependency_edge(
                    dependency,
                    _source_entry(maps[source_task_id.split(":", 1)[0]], candidates[source_task_id]),
                )
                for dependency in dependencies
            ],
            "document_ids": document_ids,
            "requirement_ids": requirement_ids,
            "acceptance": (
                []
                if scenario == "mapping_lossy_split"
                and task_id in {"plan-02:T1.1", "plan-02:T1.2"}
                or scenario == "mapping_weaken_candidate"
                and task_id == "plan-01:T2"
                else candidates[source_task_id]["acceptance"]
            ),
            "global_constraints": [
                *candidates[source_task_id]["global_constraints"],
                *global_constraint_bindings,
            ],
            "upstream_interface_commitments": candidates[source_task_id][
                "upstream_interface_commitments"
            ],
            "brief_path": (
                f"briefs/{task_id.replace(':', '-')}.json"
                if generation == 1
                else f"briefs/{generation_id}/{task_id.replace(':', '-')}.json"
            ),
        }
        if generation > 1:
            task["predecessor_task_id"] = task_id
        tasks.append(task)
    if scenario == "mapping_brief_omits_requirement":
        tasks[0]["document_ids"] = ["plan-01"]
    coverage = {
        "spec-01:R1": {
            "disposition": "planned",
            "task_ids": ["plan-01:T1"],
            "reason": None,
            "source_references": [
                _source_entry(*requirements["spec-01:R1"]),
                _source_entry(maps["plan-01"], candidates["plan-01:T1"]),
            ],
            "authority_ids": [],
        },
        "spec-02:R1": {
            "disposition": "planned",
            "task_ids": ["plan-01:T2"],
            "reason": None,
            "source_references": [
                _source_entry(*requirements["spec-02:R1"]),
                _source_entry(maps["plan-01"], candidates["plan-01:T2"]),
            ],
            "authority_ids": [],
        },
    }
    if scenario == "mapping_split_brief_substitutes_requirement":
        coverage["spec-01:R1"]["task_ids"] = [
            "plan-01:T1",
            "plan-02:T1.1",
            "plan-02:T1.2",
        ]
    authority_items: list[dict[str, object]] = []
    if scenario in {"mapping_unmapped", "mapping_conflict"}:
        disposition = "unmapped" if scenario == "mapping_unmapped" else "conflict"
        coverage["spec-01:R1"] = {
            "disposition": disposition,
            "task_ids": ["plan-01:T1"] if disposition == "conflict" else [],
            "reason": "deterministic blocking coverage fixture",
            "source_references": [_source_entry(*requirements["spec-01:R1"])],
            "authority_ids": [],
        }
        if disposition == "unmapped":
            tasks[0]["requirement_ids"] = []
        if disposition == "conflict":
            coverage["spec-01:R1"]["authority_ids"] = ["mapping-conflict-1"]
            authority_items.append(
                {
                    "authority_id": "mapping-conflict-1",
                    "authority_code": "authoritative_document_conflict",
                    "affected_task_ids": ["plan-01:T1"],
                    "question": "Which mutually exclusive approved requirement governs?",
                    "options": ["spec-01", "spec-02"],
                    "recommended": "spec-01",
                    "source_references": [
                        _source_entry(*requirements["spec-01:R1"]),
                        _source_entry(*requirements["spec-02:R1"]),
                    ],
                }
            )
    program = {
        "schema_version": 1,
        "generation": generation,
        "document_map_sha256s": map_hashes,
        "tasks": tasks,
        "coverage": coverage,
        "task_splits": task_splits,
        "plan_wave_graph": maps["program-plan"]["plan_wave_graph"],
        "hotspots": [
            hotspot for document_map in maps.values() for hotspot in document_map["hotspots"]
        ],
        "decisions": [
            decision for document_map in maps.values() for decision in document_map["decisions"]
        ],
        "constraints": [
            constraint for document_map in maps.values() for constraint in document_map["constraints"]
        ],
        "final_verification_commands": ["python3 evals/check_lean_mapping.py"],
        "authority_items": authority_items,
    }
    program_bytes = _canonical_json(program)
    program_sha256 = hashlib.sha256(program_bytes).hexdigest()
    _write_json(outbox, report_path, program)
    artifact_paths = [report_path]
    coverage_path = f"maps/{generation_id}/coverage.json"
    authority_path = f"maps/{generation_id}/authority-queue.json"
    _write_json(
        outbox,
        coverage_path,
        {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "coverage": (
                {"unexpected": "staging companion mismatch"}
                if scenario == "mapping_invalid_companion"
                else coverage
            ),
        },
    )
    _write_json(
        outbox,
        authority_path,
        {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "authority_items": authority_items,
        },
    )
    artifact_paths.extend([coverage_path, authority_path])

    affected_document_ids: list[str] = []
    for task in tasks:
        source_task_id = (
            "plan-02:T1"
            if task["task_id"] in {"plan-02:T1.1", "plan-02:T1.2"}
            else task["task_id"]
        )
        candidate = candidates[source_task_id]
        references = [_source_entry(maps[source_task_id.split(":", 1)[0]], candidate)]
        for requirement_id in task["requirement_ids"]:
            references.append(_source_entry(*requirements[requirement_id]))
        if (
            task["task_id"] == "plan-01:T1"
            and "spec-01" not in {reference["document_id"] for reference in references}
        ):
            references.append(_source_entry(*requirements["spec-01:R1"]))
        if source_task_id == "plan-02:T1":
            references.append(_source_entry(*requirements["program-plan:R1"]))
        if scenario == "mapping_brief_omits_requirement" and task["task_id"] == "plan-01:T1":
            references = [
                reference
                for reference in references
                if reference["document_id"] != "spec-01"
            ]
        if (
            scenario == "mapping_brief_substitutes_requirement"
            and task["task_id"] == "plan-01:T1"
        ) or (
            scenario == "mapping_split_brief_substitutes_requirement"
            and task["task_id"] == "plan-02:T1.2"
        ):
            references = [
                reference
                for reference in references
                if reference != _source_entry(*requirements["spec-01:R1"])
            ]
            spec_map = maps["spec-01"]
            references.append(
                {
                    "document_id": "spec-01",
                    "heading": "Specification A",
                    "line_start": 1,
                    "line_end": 1,
                    "source_sha256": spec_map["source_sha256"],
                    "exact_excerpt": "# Specification A\n",
                }
            )
        brief = {
            "schema_version": 1,
            "task_id": task["task_id"],
            "program_map_sha256": program_sha256,
            "title": task["title"],
            "dependencies": task["dependencies"],
            "dependency_edges": task["dependency_edges"],
            "source_references": references,
            "global_constraints": task["global_constraints"],
            "acceptance": task["acceptance"],
            "upstream_interface_commitments": task[
                "upstream_interface_commitments"
            ],
            "expected_report_path": (
                f"reports/retry-{task['task_id'].replace(':', '-')}.md"
                if scenario == "mapping_success_retry_variant"
                else f"reports/{task['task_id'].replace(':', '-')}.md"
            ),
        }
        _write_json(outbox, task["brief_path"], brief)
        artifact_paths.append(task["brief_path"])
        affected_document_ids.extend(task["document_ids"])
    if scenario in {"mapping_extra_artifact", "mapping_unreported_extra_artifact"}:
        extra_path = "logs/unexpected-mapper-output.json"
        _write_json(outbox, extra_path, {"unexpected": True})
        if scenario == "mapping_extra_artifact":
            artifact_paths.append(extra_path)
    return artifact_paths, sorted(set(affected_document_ids))


def main() -> int:
    argv = sys.argv[1:]
    if argv[:3] != ["exec", "--ignore-user-config", "--json"] or argv[-1:] != ["-"]:
        raise SystemExit("fake codex rejected launcher shape")
    prompt = sys.stdin.read()
    _log_invocation(argv, prompt)

    role = _prompt_value(prompt, "CPE_ROLE")
    item_id = _prompt_value(prompt, "ITEM")
    report_path = _prompt_value(prompt, "OUTBOX_REPORT_PATH")
    scenario = os.environ.get("CPE_FAKE_SCENARIO", "success")
    if scenario not in SCENARIOS:
        raise SystemExit(f"unknown fake scenario: {scenario}")
    worktree = Path(_value(argv, "-C")).resolve(strict=True)
    outbox = Path(_value(argv, "--add-dir")).resolve(strict=True)
    schema = Path(_value(argv, "--output-schema"))
    last_message = Path(_value(argv, "--output-last-message"))
    sandbox = _value(argv, "--sandbox")
    expected_sandbox = "workspace-write" if role in WRITE_ROLES else "read-only"
    if sandbox != expected_sandbox or not schema.is_file():
        raise SystemExit("fake codex rejected sandbox or result schema")
    if any(flag in argv for flag in ("--model", "--profile", "--config")):
        raise SystemExit("fake codex rejected forbidden policy argument")

    if scenario in {"timeout", "timeout_leader_exits_descendant_survives"}:
        child_code = "import time; time.sleep(60)"
        if scenario == "timeout_leader_exits_descendant_survives":
            child_code = (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)"
            )
        descendant = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        declared_pid = os.environ.get("CPE_FAKE_DESCENDANT_PID")
        if declared_pid:
            Path(declared_pid).write_text(str(descendant.pid), encoding="utf-8")
        time.sleep(60)
        return 99

    if scenario == "final_integrator_timeout" and role == "program_final_integrator":
        time.sleep(60)
        return 99

    if scenario == "queue_review_crash" and role == "reviewer":
        raise SystemExit("deterministic reviewer process interruption")

    if scenario.startswith("mapping_") or scenario == "refresh_success" and role in {
        "document_mapper",
        "program_mapper",
    }:
        mapping_scenario = "mapping_success" if scenario == "refresh_success" else scenario
        input_paths = _prompt_inputs(prompt)
        if role == "document_mapper":
            if mapping_scenario == "mapping_partial_failure" and item_id == "plan-02":
                raise SystemExit("deterministic interrupted document mapper")
            artifact_paths = _mapping_document_result(
                item_id=item_id,
                input_paths=input_paths,
                outbox=outbox,
                report_path=report_path,
            )
            affected_document_ids = [item_id]
        elif role == "program_mapper":
            artifact_paths, affected_document_ids = _mapping_program_result(
                scenario=mapping_scenario,
                input_paths=input_paths,
                outbox=outbox,
                report_path=report_path,
                generation_id=item_id,
            )
        else:
            raise SystemExit("mapping scenario requires a mapper role")
        result = {
            "role": role,
            "status": (
                "interrupted"
                if mapping_scenario == "mapping_noncompleted_result"
                and role == "document_mapper"
                and item_id == "spec-01"
                else "completed"
            ),
            "item_id": item_id,
            "commit": None,
            "verdict": None,
            "failure_code": None,
            "authority_id": None,
            "strategy_key": "initial",
            "affected_document_ids": affected_document_ids,
            "artifact_paths": artifact_paths,
            "summary": f"deterministic {mapping_scenario} result",
        }
        last_message.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"type": "thread.started"}, sort_keys=True), flush=True)
        print(json.dumps({"type": "turn.completed"}, sort_keys=True), flush=True)
        return 0

    _write_report(outbox, report_path)
    status = "completed"
    verdict = "pass" if role in VERDICT_ROLES else None
    commit = None
    failure_code = None
    authority_id = None
    artifact_paths = [report_path]

    queue_number = (
        _queue_invocation_number(role)
        if scenario.startswith(("queue_", "final_"))
        else 1
    )

    if (scenario.startswith("final_") or scenario == "refresh_success") and role == "document_auditor":
        commit, verdict, artifact_paths = _final_audit_result(
            scenario="final_success" if scenario == "refresh_success" else scenario,
            item_id=item_id,
            input_paths=_prompt_inputs(prompt),
            worktree=worktree,
            outbox=outbox,
            report_path=report_path,
        )
    elif (scenario.startswith("final_") or scenario == "refresh_success") and role == "program_final_integrator":
        commit, status, verdict, artifact_paths = _final_integration_result(
            scenario="final_success" if scenario == "refresh_success" else scenario,
            queue_number=queue_number,
            input_paths=_prompt_inputs(prompt),
            worktree=worktree,
            outbox=outbox,
            report_path=report_path,
        )
    elif (scenario.startswith("final_") or scenario == "refresh_success") and role in WRITE_ROLES:
        commit = _commit_change(worktree, item_id)
    elif scenario in {"success", "queue_success", "queue_review_crash"} and role in WRITE_ROLES:
        commit = _commit_change(worktree, item_id)
    elif scenario in {
        "queue_review_fix",
        "queue_fix_review_crash",
        "queue_repeated_review_finding",
    }:
        if role in WRITE_ROLES:
            commit = _commit_change(worktree, item_id)
        elif role == "reviewer" and (
            queue_number == 1
            or scenario == "queue_repeated_review_finding" and queue_number == 2
        ):
            status = "changes_requested"
            verdict = "changes_requested"
            finding_path = (
                f"reviews/{item_id.replace(':', '-')}/"
                f"findings-important-{queue_number}.json"
            )
            _write_json(
                outbox,
                finding_path,
                {"severity": "Important", "finding": "consolidate the bounded fix"},
            )
            artifact_paths.append(finding_path)
    elif scenario in {
        "queue_ordinary_failure",
        "queue_test_failure",
        "queue_unchanged_strategy",
    }:
        if role == "task_agent":
            status = "failed"
            failure_code = "test_failure"
        elif role == "investigator":
            pass
        elif role in WRITE_ROLES:
            commit = _commit_change(worktree, item_id)
    elif scenario in {
        "queue_historical_strategy",
        "queue_repeated_unusable_strategy",
    }:
        if role == "investigator":
            pass
        elif role in WRITE_ROLES:
            commit = _commit_change(worktree, item_id)
    elif scenario == "queue_invalid_authority":
        if role == "task_agent":
            status = "waiting_authority"
            authority_id = "test_failure"
        elif role in WRITE_ROLES:
            commit = _commit_change(worktree, item_id)
    elif scenario == "queue_authority" and role == "task_agent":
        status = "waiting_authority"
        authority_id = "credential_required"
    elif scenario == "writer_hold" and role in WRITE_ROLES:
        marker = os.environ.get("CPE_FAKE_WRITER_MARKER")
        if marker:
            Path(marker).write_text("started\n", encoding="utf-8")
        time.sleep(0.35)
        commit = _commit_change(worktree, item_id)
    elif scenario == "review_changes_requested":
        status = "changes_requested"
        verdict = "changes_requested" if role in VERDICT_ROLES else None
    elif scenario == "ordinary_failure":
        status = "failed"
        verdict = None
        failure_code = "test_failure"
    elif scenario == "authority":
        status = "waiting_authority"
        verdict = "blocked" if role in VERDICT_ROLES else None
        authority_id = "credential_required"
    elif scenario == "dirty_handoff":
        (worktree / "fake-dirty-handoff.txt").write_text("dirty\n", encoding="utf-8")
    elif scenario == "wrong_commit":
        if role not in WRITE_ROLES:
            raise SystemExit("wrong_commit requires a write role")
        _commit_change(worktree, item_id)
        commit = _git(worktree, "rev-parse", "HEAD^")
    elif scenario == "tampered_artifact_path":
        artifact_paths = ["../escaped.md"]

    result = {
        "role": role,
        "status": status,
        "item_id": item_id,
        "commit": commit,
        "verdict": verdict,
        "failure_code": failure_code,
        "authority_id": authority_id,
        "strategy_key": (
            "fresh-root-cause-v2"
            if role == "investigator"
            and scenario
            in {
                "queue_ordinary_failure",
                "queue_test_failure",
                "queue_invalid_authority",
            }
            else (
                "strategy-A"
                if scenario == "queue_repeated_unusable_strategy"
                else {1: "strategy-A", 2: "strategy-C"}.get(
                    queue_number, f"strategy-D-{queue_number}"
                )
            )
            if role == "investigator"
            and scenario
            in {"queue_historical_strategy", "queue_repeated_unusable_strategy"}
            else _prompt_strategy(prompt)
        ),
        "affected_document_ids": (
            json.loads(os.environ.get("CPE_FAKE_AFFECTED_DOCUMENT_IDS", '["plan-01"]'))
            if status == "waiting_authority"
            else []
        ),
        "artifact_paths": artifact_paths,
        "summary": f"deterministic {scenario} result",
    }
    if (
        scenario == "queue_fix_review_crash"
        and role == "reviewer"
        and queue_number == 2
    ):
        raise SystemExit("deterministic fresh reviewer process interruption")
    last_message.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"type": "thread.started"}, sort_keys=True), flush=True)
    print(json.dumps({"type": "turn.completed"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
