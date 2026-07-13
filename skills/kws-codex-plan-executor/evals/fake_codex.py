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
        "mapping_partial_failure",
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
        "input_paths": _prompt_inputs(prompt),
    }
    with Path(declared).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _commit_change(worktree: Path, item_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", item_id)
    relative = f"cpe-{safe}.txt"
    (worktree / relative).write_text("deterministic write role change\n", encoding="utf-8")
    _git(worktree, "add", "--", relative)
    _git(worktree, "commit", "-q", "-m", f"fake cpe {safe}")
    return _git(worktree, "rev-parse", "HEAD")


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


def _mapping_document_result(
    *, item_id: str, input_paths: list[str], outbox: Path, report_path: str
) -> list[str]:
    snapshots = [
        Path(value)
        for value in input_paths
        if Path(value).parent.name == "inputs" and Path(value).name != "document-set.json"
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
                "constraints": ["preserve the immutable approved requirement"],
            }
        )
    elif role == "plan":
        task_numbers = (1, 2) if item_id == "plan-01" else (1,)
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
                    "requirement_ids": [],
                    "dependencies": dependency,
                    "acceptance": ["python3 evals/check_lean_mapping.py"],
                    "global_constraints": [],
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
    }
    if os.environ.get("CPE_FAKE_SCENARIO") == "mapping_bad_excerpt":
        entries = payload["requirements"] or payload["task_candidates"]
        entries[0]["exact_excerpt"] = "not the declared immutable source range"
    _write_json(outbox, report_path, payload)
    return [report_path]


def _mapping_program_result(
    *, scenario: str, input_paths: list[str], outbox: Path, report_path: str
) -> tuple[list[str], list[str]]:
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
    task_specs = [
        ("plan-01:T1", [], ["plan-01", "spec-01"], ["spec-01:R1"]),
        ("plan-01:T2", ["plan-01:T1"], ["plan-01", "spec-02"], ["spec-02:R1"]),
        ("plan-02:T1", ["plan-01:T2"], ["plan-02", "program-plan"], []),
    ]
    tasks = [
        {
            "task_id": task_id,
            "title": candidates[task_id]["title"],
            "dependencies": dependencies,
            "document_ids": document_ids,
            "requirement_ids": requirement_ids,
            "brief_path": f"briefs/{task_id.replace(':', '-')}.json",
        }
        for task_id, dependencies, document_ids, requirement_ids in task_specs
    ]
    coverage = {
        "spec-01:R1": {
            "disposition": "planned",
            "task_ids": ["plan-01:T1"],
            "reason": None,
        },
        "spec-02:R1": {
            "disposition": "planned",
            "task_ids": ["plan-01:T2"],
            "reason": None,
        },
    }
    authority_items: list[dict[str, object]] = []
    if scenario in {"mapping_unmapped", "mapping_conflict"}:
        disposition = "unmapped" if scenario == "mapping_unmapped" else "conflict"
        coverage["spec-01:R1"] = {
            "disposition": disposition,
            "task_ids": [],
            "reason": "deterministic blocking coverage fixture",
        }
        tasks[0]["requirement_ids"] = []
        if disposition == "conflict":
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
        "generation": 1,
        "document_map_sha256s": map_hashes,
        "tasks": tasks,
        "coverage": coverage,
        "task_splits": [],
        "final_verification_commands": ["python3 evals/check_lean_mapping.py"],
        "authority_items": authority_items,
    }
    program_bytes = _canonical_json(program)
    program_sha256 = hashlib.sha256(program_bytes).hexdigest()
    _write_json(outbox, report_path, program)
    artifact_paths = [report_path]
    coverage_path = "maps/generation-0001/coverage.json"
    authority_path = "maps/generation-0001/authority-queue.json"
    _write_json(
        outbox,
        coverage_path,
        {
            "schema_version": 1,
            "program_map_sha256": program_sha256,
            "coverage": coverage,
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
        candidate = candidates[task["task_id"]]
        references = [_source_entry(maps[task["task_id"].split(":", 1)[0]], candidate)]
        for requirement_id in task["requirement_ids"]:
            references.append(_source_entry(*requirements[requirement_id]))
        if (
            task["task_id"] == "plan-01:T1"
            and "spec-01" not in {reference["document_id"] for reference in references}
        ):
            references.append(_source_entry(*requirements["spec-01:R1"]))
        if task["task_id"] == "plan-02:T1":
            references.append(_source_entry(*requirements["program-plan:R1"]))
        brief = {
            "schema_version": 1,
            "task_id": task["task_id"],
            "program_map_sha256": program_sha256,
            "title": task["title"],
            "dependencies": task["dependencies"],
            "source_references": references,
            "global_constraints": [
                reference
                for reference in references
                if str(reference["document_id"]).startswith("spec-")
            ],
            "acceptance": candidate["acceptance"],
            "expected_report_path": f"reports/{task['task_id'].replace(':', '-')}.md",
        }
        _write_json(outbox, task["brief_path"], brief)
        artifact_paths.append(task["brief_path"])
        affected_document_ids.extend(task["document_ids"])
    if scenario == "mapping_extra_artifact":
        extra_path = "logs/unexpected-mapper-output.json"
        _write_json(outbox, extra_path, {"unexpected": True})
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

    if scenario.startswith("mapping_"):
        input_paths = _prompt_inputs(prompt)
        if role == "document_mapper":
            if scenario == "mapping_partial_failure" and item_id == "plan-02":
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
                scenario=scenario,
                input_paths=input_paths,
                outbox=outbox,
                report_path=report_path,
            )
        else:
            raise SystemExit("mapping scenario requires a mapper role")
        result = {
            "role": role,
            "status": "completed",
            "item_id": item_id,
            "commit": None,
            "verdict": None,
            "failure_code": None,
            "authority_id": None,
            "strategy_key": "initial",
            "affected_document_ids": affected_document_ids,
            "artifact_paths": artifact_paths,
            "summary": f"deterministic {scenario} result",
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

    if scenario == "success" and role in WRITE_ROLES:
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
        "strategy_key": "initial",
        "affected_document_ids": [],
        "artifact_paths": artifact_paths,
        "summary": f"deterministic {scenario} result",
    }
    last_message.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"type": "thread.started"}, sort_keys=True), flush=True)
    print(json.dumps({"type": "turn.completed"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
