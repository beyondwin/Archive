#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_plan_executability.py"


CURRENT_PLAN_MARKDOWN = """# Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exercise the CPE plan executability audit.

**Architecture:** The fixture keeps raw plan text current enough for the CPE gate while parsed JSON drives the individual task cases.

**Tech Stack:** Python 3 standard library.

## Global Constraints

- Keep fixture edits scoped to the temporary repository.

---

### Task 1: Fixture Task

**Files:**
- Modify: `src/app.py`

```bash
python3 -m pytest
```
"""


def legacy_plan_markdown() -> str:
    return """# Legacy Fixture Plan

> **For agentic workers:** Implement task-by-task. Keep edits scoped.

### Task 1: Legacy Task

**Files:**
- Modify: `src/app.py`

```bash
python3 -m pytest
```
"""


def write_plan_json(path: Path, tasks: list[dict], *, plan_markdown: str | None = None) -> None:
    markdown_path = path.with_suffix(".md")
    markdown_path.write_text(plan_markdown if plan_markdown is not None else CURRENT_PLAN_MARKDOWN, encoding="utf-8")
    path.write_text(
        json.dumps({"plan": str(markdown_path), "mode": "interactive", "tasks": tasks}, indent=2),
        encoding="utf-8",
    )


def task(
    task_id: str,
    files: list[str],
    *,
    acceptance_command: str | None = "python3 -m pytest",
    title: str = "Task",
    depends_on: list[str] | None = None,
) -> dict:
    return {
        "id": task_id,
        "number": 1,
        "title": title,
        "line": 1,
        "body": title,
        "body_line_start": 1,
        "body_line_end": 1,
        "files": files,
        "file_line_numbers": {item: 1 for item in files},
        "spec_refs": [],
        "depends_on": depends_on or [],
        "yaml_task_id": None,
        "has_acceptance_criteria": acceptance_command is not None,
        "acceptance_command": acceptance_command,
        "acceptance_source": "plan.acceptance_section" if acceptance_command else "missing",
    }


def write_packet(
    packet_dir: Path,
    task_id: str,
    files: list[str],
    *,
    command: str | None = "python3 -m pytest",
    fallback_used: bool = False,
) -> None:
    packet_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task_id,
        "files": files,
        "depends_on": [],
        "risk_markers": [],
        "acceptance": {
            "has_acceptance_criteria": command is not None,
            "command": command,
            "source": "plan.acceptance_section" if command else "missing",
        },
        "spec": {"fallback_used": fallback_used},
        "context_budget": {"status": "green", "estimated_chars": 1000, "max_chars": 60000},
        "write_policy": {"allowed_write_globs": files, "forbidden_write_globs": [".git/**", "graphify-out/**"]},
    }
    (packet_dir / f"{task_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_audit(repo: Path, plan_json: Path, *, packet_dir: Path | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "plan_executability_audit.json"
    command = [
        sys.executable,
        str(SCRIPT),
        "--plan-json",
        str(plan_json),
        "--repo-root",
        str(repo),
        "--output",
        str(output),
    ]
    if packet_dir is not None:
        command.extend(["--task-packet-dir", str(packet_dir)])
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, payload


def init_repo(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs/example.md").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("print('base')\n", encoding="utf-8")
    (repo / "skills" / "kws-codex-plan-executor" / "scripts").mkdir(parents=True)
    (repo / "skills" / "kws-codex-plan-executor" / "scripts" / "tool.py").write_text("print('base')\n", encoding="utf-8")
    (repo / "bun.lock").write_text("base\n", encoding="utf-8")


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-green-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(
            plan_json,
            [task("task_1", ["skills/kws-codex-plan-executor/scripts/tool.py"], title="Add audit helper")],
        )
        packet_dir = repo / "task_packets"
        write_packet(packet_dir, "task_1", ["skills/kws-codex-plan-executor/scripts/tool.py"])
        result, payload = run_audit(repo, plan_json, packet_dir=packet_dir)
        checks["green_superpowers_plan_passes"] = (
            result.returncode == 0 and payload.get("grade") == "green" and payload.get("passed") is True
        )
        if not checks["green_superpowers_plan_passes"]:
            failures.append("green plan with packet should pass")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-yellow-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["docs/example.md"], acceptance_command=None, title="Polish docs")])
        result, payload = run_audit(repo, plan_json)
        kinds = {issue for item in payload.get("tasks", []) for issue in item.get("fixable_issues", [])}
        task_audit = payload.get("tasks", [{}])[0]
        checks["yellow_fixable_acceptance"] = (
            result.returncode == 0
            and payload.get("grade") == "yellow"
            and task_audit.get("plan_support") == "cpe_fixable_metadata"
            and "acceptance_command_missing" in kinds
        )
        if not checks["yellow_fixable_acceptance"]:
            failures.append("docs-only task without acceptance should be yellow and fixable")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-red-files-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", [], title="Missing files")])
        result, payload = run_audit(repo, plan_json)
        task_audit = payload.get("tasks", [{}])[0]
        checks["red_missing_files"] = (
            result.returncode == 1
            and payload.get("grade") == "red"
            and task_audit.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("subagent_reason") == "blocked_unsupported_plan_shape"
        )
        if not checks["red_missing_files"]:
            failures.append("missing files should produce red audit")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-broad-scope-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["**/*"], title="Broad scope")])
        result, payload = run_audit(repo, plan_json)
        blockers = {issue for item in payload.get("tasks", []) for issue in item.get("blocking_issues", [])}
        checks["red_broad_scope"] = result.returncode == 1 and "write_scope_too_broad" in blockers
        if not checks["red_broad_scope"]:
            failures.append("broad write scope should produce red audit")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-acceptance-block-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(
            plan_json,
            [task("task_1", ["src/app.py"], acceptance_command=None, title="App change without acceptance")],
        )
        result, payload = run_audit(repo, plan_json)
        task_audit = payload.get("tasks", [{}])[0]
        checks["block_reason_prioritizes_acceptance_missing"] = (
            result.returncode == 1
            and payload.get("grade") == "red"
            and task_audit.get("plan_support") == "current_superpowers_compatible"
            and task_audit.get("subagent_fit") == "block"
            and task_audit.get("subagent_reason") == "acceptance_command_missing"
            and "acceptance_command_missing" in task_audit.get("blocking_issues", [])
        )
        if not checks["block_reason_prioritizes_acceptance_missing"]:
            failures.append("non-docs missing acceptance should block with acceptance_command_missing reason")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-unsupported-header-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(
            plan_json,
            [task("task_1", ["src/app.py"], title="Legacy header shape")],
            plan_markdown=legacy_plan_markdown(),
        )
        result, payload = run_audit(repo, plan_json)
        task_audit = payload.get("tasks", [{}])[0]
        checks["unsupported_plan_shape_missing_required_header"] = (
            result.returncode == 1
            and payload.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("subagent_fit") == "block"
            and task_audit.get("subagent_reason") == "blocked_unsupported_plan_shape"
            and "blocked_unsupported_plan_shape" in task_audit.get("blocking_issues", [])
        )
        if not checks["unsupported_plan_shape_missing_required_header"]:
            failures.append("legacy header should be blocked as unsupported current Superpowers/CPE plan shape")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-risk-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["bun.lock"], title="Update lockfile")])
        result, payload = run_audit(repo, plan_json)
        blockers = {issue for item in payload.get("tasks", []) for issue in item.get("blocking_issues", [])}
        task_audit = payload.get("tasks", [{}])[0]
        checks["risk_marker_operator_review"] = (
            result.returncode == 1
            and "risk_marker_requires_operator_review" in blockers
            and task_audit.get("plan_support") == "operator_review_required"
            and task_audit.get("subagent_reason") == "risk_marker_requires_operator_review"
        )
        if not checks["risk_marker_operator_review"]:
            failures.append("lockfile path should require operator review")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-summary-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(
            plan_json,
            [
                task("task_1", ["src/app.py"], title="App change"),
                task("task_2", ["docs/example.md"], acceptance_command=None, title="Docs change"),
            ],
        )
        result, payload = run_audit(repo, plan_json)
        summary = payload.get("summary", {})
        checks["thin_bridge_summary_counts"] = (
            result.returncode == 0
            and payload.get("grade") == "yellow"
            and summary.get("route") == "thin_stateful_bridge"
            and summary.get("task_count") == 2
            and summary.get("fixable_issue_count") == 1
        )
        if not checks["thin_bridge_summary_counts"]:
            failures.append("summary should include thin bridge route and task counts")

    output = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
