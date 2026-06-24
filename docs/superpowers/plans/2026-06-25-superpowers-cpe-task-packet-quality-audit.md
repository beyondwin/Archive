# Superpowers CPE Task Packet Quality Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic CPE executability audit that scores Superpowers plans and task packets before interactive execution while preserving the thin-stateful-bridge route.

**Architecture:** Add a new read-only `audit_plan_executability.py` script that consumes parsed plan JSON plus optional task packets, emits a stable JSON payload, and reuses existing CPE dispatch reason vocabulary. Wire its summary into state/run-quality validation and document the readiness summary contract without replacing Superpowers `subagent-driven-development`.

**Tech Stack:** Python 3 standard library, Markdown docs, existing CPE eval scripts under `skills/kws-codex-plan-executor/evals`, existing CPE state validation under `skills/kws-codex-plan-executor/scripts/validate_state.py`.

## Global Constraints

- Preserve `brainstorming` hard gate: no implementation starts before approved spec and plan.
- Preserve CPE thin stateful bridge: Superpowers owns the approved interactive implementation loop when compatibility audit recommends `thin_stateful_bridge`.
- Do not weaken TDD, task contract, worktree isolation, dispatch safety, prompt audit, Graphify audit, state reconciliation, or completion audit requirements.
- New audit is read-only. It must not create worktrees, mutate repository files, mutate state, spawn subagents, or execute plan tasks.
- Reuse existing dispatch reason strings where possible: `adaptive_policy_local_fast_path_docs_only`, `adaptive_policy_local_fast_path_small_scope`, `adaptive_policy_local_fast_path_linear_task`, `adaptive_policy_local_fast_path_low_parallel_value`, and `risk_marker_requires_operator_review`.
- Runtime artifacts stay under `~/.codex/orchestrator/<run_id>/`; code worktrees stay under `~/.codex/worktrees/<run_id>`.
- Follow `skills/kws-codex-plan-executor/references/change-protocol.md`: update deterministic eval coverage first, update docs/contracts with behavior, run evals, run py_compile, run `bash -n evals/run.sh`.

---

## File Structure

- `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
  New read-only audit script. It accepts `--plan-json`, optional `--task-packet-dir`, `--repo-root`, optional `--output`, and emits the deterministic JSON payload described in the spec.
- `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
  New focused deterministic eval for green, yellow, red, risk-marker, and thin-bridge summary cases.
- `skills/kws-codex-plan-executor/scripts/validate_state.py`
  Validate optional `plan_executability_audit` state summary and ensure finished operational state keeps run-quality/readiness shape coherent.
- `skills/kws-codex-plan-executor/evals/check_state_schema.py`
  Add positive/negative state schema coverage for `plan_executability_audit`.
- `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
  Add stable follow-up helper for plan executability fixable issues.
- `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
  Add run-quality coverage proving plan executability follow-ups can turn grade yellow without failing completion.
- `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
  Add contract checks for the new audit script, readiness summary, state field, and eval harness inclusion.
- `skills/kws-codex-plan-executor/evals/run.sh`
  Wire `check_plan_executability_audit.py` into the focused eval list.
- `skills/kws-codex-plan-executor/SKILL.md`
  Document the new audit in Core Invariants, Workflow, and Validation Matrix.
- `skills/kws-codex-plan-executor/README.md`
  Add the new eval command and a short user-facing explanation.
- `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  Add the plan executability audit node to the thin bridge flow.
- `skills/kws-codex-plan-executor/references/execution-cycle.md`
  Insert audit after task packet creation/readiness and before task contracts or edits.
- `skills/kws-codex-plan-executor/references/state-schema.md`
  Document `plan_executability_audit`.
- `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
  Add Korean operator guidance for the readiness summary.
- `skills/kws-codex-plan-executor/HISTORY.md`
  Add an unreleased entry for the new audit.

## Task 1: Add Executability Audit Script And Focused RED Eval

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
- Create: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`

**Interfaces:**
- Consumes: parsed plan JSON from `scripts/parse_plan.py`, optional task packet JSON files from `scripts/build_task_packet.py`, repository root path.
- Produces: JSON payload with `schema_version`, `passed`, `grade`, `summary`, `tasks`, `global_followups`, and optional output file.

- [ ] **Step 1: Write the failing focused eval**

Create `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_plan_executability.py"


def write_plan_json(path: Path, tasks: list[dict]) -> None:
    path.write_text(json.dumps({"plan": str(path.with_suffix(".md")), "mode": "interactive", "tasks": tasks}, indent=2), encoding="utf-8")


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


def write_packet(packet_dir: Path, task_id: str, files: list[str], *, command: str | None = "python3 -m pytest", fallback_used: bool = False) -> None:
    packet_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task_id,
        "files": files,
        "depends_on": [],
        "risk_markers": [],
        "acceptance": {"has_acceptance_criteria": command is not None, "command": command, "source": "plan.acceptance_section" if command else "missing"},
        "spec": {"fallback_used": fallback_used},
        "context_budget": {"status": "green", "estimated_chars": 1000, "max_chars": 60000},
        "write_policy": {"allowed_write_globs": files, "forbidden_write_globs": [".git/**", "graphify-out/**"]},
    }
    (packet_dir / f"{task_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        write_plan_json(plan_json, [task("task_1", ["skills/kws-codex-plan-executor/scripts/tool.py"], title="Add audit helper")])
        packet_dir = repo / "task_packets"
        write_packet(packet_dir, "task_1", ["skills/kws-codex-plan-executor/scripts/tool.py"])
        result, payload = run_audit(repo, plan_json, packet_dir=packet_dir)
        checks["green_superpowers_plan_passes"] = result.returncode == 0 and payload.get("grade") == "green" and payload.get("passed") is True
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
        checks["yellow_fixable_acceptance"] = result.returncode == 0 and payload.get("grade") == "yellow" and "acceptance_command_missing" in kinds
        if not checks["yellow_fixable_acceptance"]:
            failures.append("docs-only task without acceptance should be yellow and fixable")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-red-files-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", [], title="Missing files")])
        result, payload = run_audit(repo, plan_json)
        checks["red_missing_files"] = result.returncode == 1 and payload.get("grade") == "red"
        if not checks["red_missing_files"]:
            failures.append("missing files should produce red audit")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-risk-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["bun.lock"], title="Update lockfile")])
        result, payload = run_audit(repo, plan_json)
        blockers = {issue for item in payload.get("tasks", []) for issue in item.get("blocking_issues", [])}
        checks["risk_marker_operator_review"] = result.returncode == 1 and "risk_marker_requires_operator_review" in blockers
        if not checks["risk_marker_operator_review"]:
            failures.append("lockfile path should require operator review")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-summary-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["src/app.py"], title="App change"), task("task_2", ["docs/example.md"], acceptance_command=None, title="Docs change")])
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
```

- [ ] **Step 2: Run the new eval and confirm RED**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
```

Expected: FAIL because `scripts/audit_plan_executability.py` does not exist.

- [ ] **Step 3: Add the audit script**

Create `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py` with this content:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any


ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY = "adaptive_policy_local_fast_path_docs_only"
ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE = "adaptive_policy_local_fast_path_small_scope"
ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK = "adaptive_policy_local_fast_path_linear_task"
ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE = "adaptive_policy_local_fast_path_low_parallel_value"
RISK_MARKER_REQUIRES_OPERATOR_REVIEW = "risk_marker_requires_operator_review"

RISKY_PATH_FRAGMENTS = ("migration", "migrations", "auth", "security", "infra", "terraform", "pulumi")
RISKY_EXACT_FILES = {"bun.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
BROAD_SCOPES = {"", ".", "*", "**", "**/*", "./", "./*", "./**", "./**/*"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def write_scope_too_broad(pattern: str) -> bool:
    return pattern.strip().rstrip("/") in BROAD_SCOPES


def malformed_scope(pattern: str) -> bool:
    stripped = pattern.strip()
    return "," in stripped and not any(char in stripped for char in "[]{}")


def normalized_scopes(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for pattern in patterns:
        parts = [item.strip() for item in pattern.split(",")] if malformed_scope(pattern) else [pattern.strip()]
        for part in parts:
            if part and part not in result:
                result.append(part)
    return result


def path_risk_markers(paths: list[str], explicit: list[str] | None = None) -> list[str]:
    markers = {item for item in (explicit or []) if item}
    for path in paths:
        normalized = path.strip().lstrip("./")
        if normalized in RISKY_EXACT_FILES:
            markers.add("lockfile")
        lowered = normalized.lower()
        for fragment in RISKY_PATH_FRAGMENTS:
            if fragment in lowered:
                markers.add(fragment)
    return sorted(markers)


def files_exist_or_are_declared(files: list[str], repo_root: Path) -> bool:
    if not files:
        return False
    for item in files:
        candidate = (repo_root / item).resolve(strict=False)
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            return False
    return True


def load_packets(packet_dir: Path | None) -> dict[str, dict[str, Any]]:
    if packet_dir is None or not packet_dir.is_dir():
        return {}
    packets: dict[str, dict[str, Any]] = {}
    for packet_path in sorted(packet_dir.glob("*.json")):
        payload = load_json(packet_path)
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
            if isinstance(task_id, str) and task_id.strip():
                packets[task_id] = payload
    return packets


def subagent_fit(files: list[str], depends_on: list[str], acceptance_missing: bool, risks: list[str]) -> tuple[str, str]:
    docs_only = bool(files) and all(path.startswith("docs/") and path.endswith(".md") for path in files)
    if risks:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW
    if docs_only:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY
    if 0 < len(files) <= 2 and len(depends_on) <= 1:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE if not depends_on else ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK
    if acceptance_missing:
        return "local_only", "acceptance_command_missing"
    return "delegate", "all pre-dispatch prerequisites passed"


def audit_task(task: dict[str, Any], packet: dict[str, Any] | None, repo_root: Path) -> dict[str, Any]:
    task_id = str(task.get("id") or task.get("task_id") or "unknown_task")
    files = list_strings(task.get("files"))
    depends_on = list_strings(task.get("depends_on"))
    packet_policy = packet.get("write_policy") if isinstance(packet, dict) and isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(packet_policy.get("allowed_write_globs")) if packet_policy else files
    packet_acceptance = packet.get("acceptance") if isinstance(packet, dict) and isinstance(packet.get("acceptance"), dict) else {}
    acceptance_command = task.get("acceptance_command") or packet_acceptance.get("command")
    acceptance_missing = not isinstance(acceptance_command, str) or not acceptance_command.strip()
    risks = path_risk_markers(files + allowed, list_strings(task.get("risk_markers")))

    fixable: list[str] = []
    blocking: list[str] = []
    suggested = normalized_scopes(allowed or files)

    if not files_exist_or_are_declared(files, repo_root):
        blocking.append("files_missing")
    if not allowed:
        blocking.append("allowed_write_globs_empty")
    if any(write_scope_too_broad(scope) for scope in allowed):
        blocking.append("write_scope_too_broad")
    if any(malformed_scope(scope) for scope in allowed + files):
        fixable.append("write_scope_format_invalid")
    if acceptance_missing:
        docs_only = bool(files) and all(path.startswith("docs/") and path.endswith(".md") for path in files)
        if docs_only:
            fixable.append("acceptance_command_missing")
        else:
            blocking.append("acceptance_command_missing")
    if packet and isinstance(packet.get("spec"), dict) and packet["spec"].get("fallback_used") is True:
        fixable.append("full_spec_fallback")
    if risks:
        blocking.append(RISK_MARKER_REQUIRES_OPERATOR_REVIEW)

    fit, reason = subagent_fit(files, depends_on, acceptance_missing, risks)
    if blocking:
        fit = "block"

    return {
        "task_id": task_id,
        "files_status": "green" if files and "files_missing" not in blocking else "red",
        "acceptance_status": "yellow" if "acceptance_command_missing" in fixable else ("red" if "acceptance_command_missing" in blocking else "green"),
        "write_policy_status": "red" if any(item in blocking for item in ("allowed_write_globs_empty", "write_scope_too_broad")) else ("yellow" if "write_scope_format_invalid" in fixable else "green"),
        "spec_mapping_status": "yellow" if "full_spec_fallback" in fixable else "green",
        "subagent_fit": fit,
        "subagent_reason": reason,
        "risk_markers": risks,
        "fixable_issues": sorted(dict.fromkeys(fixable)),
        "blocking_issues": sorted(dict.fromkeys(blocking)),
        "suggested_write_scopes": suggested,
    }


def build_payload(plan_json: Path, repo_root: Path, packet_dir: Path | None) -> dict[str, Any]:
    plan = load_json(plan_json)
    if not isinstance(plan, dict):
        raise ValueError("plan JSON must be an object")
    packets = load_packets(packet_dir)
    tasks = []
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        tasks.append(audit_task(task, packets.get(task_id), repo_root))

    blocking_count = sum(len(item["blocking_issues"]) for item in tasks)
    fixable_count = sum(len(item["fixable_issues"]) for item in tasks)
    grade = "red" if blocking_count else ("yellow" if fixable_count else "green")
    summary = {
        "route": "thin_stateful_bridge",
        "task_count": len(tasks),
        "delegate_ready_count": sum(1 for item in tasks if item["subagent_fit"] == "delegate"),
        "local_fast_path_count": sum(1 for item in tasks if item["subagent_fit"] == "local_fast_path"),
        "fixable_issue_count": fixable_count,
        "blocking_issue_count": blocking_count,
    }
    return {
        "schema_version": "1",
        "passed": blocking_count == 0,
        "grade": grade,
        "summary": summary,
        "tasks": tasks,
        "global_followups": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Superpowers plan executability before CPE task execution.")
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--task-packet-dir")
    parser.add_argument("--output")
    args = parser.parse_args()

    payload = build_payload(
        Path(args.plan_json).expanduser(),
        Path(args.repo_root).expanduser().resolve(),
        Path(args.task_packet_dir).expanduser() if args.task_packet_dir else None,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused eval and confirm GREEN**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
```

Expected: PASS JSON with `passed: true`.

- [ ] **Step 5: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/scripts/audit_plan_executability.py skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
git commit -m "feat: audit CPE plan executability"
```

## Task 2: Connect Audit Summary To State Validation And Run Quality

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes: optional `state["plan_executability_audit"]` summary.
- Produces: validator errors for malformed audit summary, stable follow-up `plan_executability_fixable_issues`, and yellow run-quality grade when completion passed but audit follow-up remains.

- [ ] **Step 1: Add RED state schema eval cases**

In `skills/kws-codex-plan-executor/evals/check_state_schema.py`, add this helper after `valid_run_quality()`:

```python
def valid_plan_executability_audit() -> dict:
    return {
        "path": f"{run_dir()}/plan_executability_audit.json",
        "grade": "yellow",
        "blocking_issue_count": 0,
        "fixable_issue_count": 1,
    }
```

Then add this block in `main()` after `checks["v222_optional_fields_pass"]`:

```python
    valid_plan_audit = v220_state()
    valid_plan_audit["agentlens_orchestration_run"] = "agentlens-run-123"
    valid_plan_audit["execution_worktree"] = valid_plan_audit["worktree"]
    valid_plan_audit["run_quality"] = valid_run_quality()
    valid_plan_audit["run_quality"]["grade"] = "yellow"
    valid_plan_audit["run_quality"]["open_followups"] = ["plan_executability_fixable_issues"]
    valid_plan_audit["run_quality"]["readiness"]["plan_executability_fixable_issue_count"] = 1
    valid_plan_audit["plan_executability_audit"] = valid_plan_executability_audit()
    result = run_validator(script, valid_plan_audit)
    checks["valid_plan_executability_audit_passes"] = result.returncode == 0
    if not checks["valid_plan_executability_audit_passes"]:
        failures.append("valid plan_executability_audit should pass: " + (result.stderr or result.stdout))

    invalid_plan_audit = v220_state()
    invalid_plan_audit["plan_executability_audit"] = {
        "path": "",
        "grade": "purple",
        "blocking_issue_count": -1,
        "fixable_issue_count": "one",
    }
    result = run_validator(script, invalid_plan_audit)
    checks["invalid_plan_executability_audit_fails"] = (
        result.returncode != 0
        and "plan_executability_audit.path must be non-empty" in (result.stderr + result.stdout)
        and "plan_executability_audit.grade must be green, yellow, or red" in (result.stderr + result.stdout)
        and "plan_executability_audit.blocking_issue_count must be a non-negative integer" in (result.stderr + result.stdout)
        and "plan_executability_audit.fixable_issue_count must be a non-negative integer" in (result.stderr + result.stdout)
    )
    if not checks["invalid_plan_executability_audit_fails"]:
        failures.append("invalid plan_executability_audit should fail")
```

- [ ] **Step 2: Run focused state schema eval and confirm RED**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
```

Expected: FAIL because `validate_state.py` does not validate `plan_executability_audit`.

- [ ] **Step 3: Validate the new state field**

In `skills/kws-codex-plan-executor/scripts/validate_state.py`, add this function before `_validate_operational_run_quality`:

```python
def _validate_plan_executability_audit(data: dict, errors: list[str]) -> None:
    audit = data.get("plan_executability_audit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        errors.append("plan_executability_audit must be an object")
        return
    if not _has_substantive_value(audit.get("path")):
        errors.append("plan_executability_audit.path must be non-empty")
    elif isinstance(data.get("run_dir"), str) and not _path_is_under(audit["path"], data["run_dir"]):
        errors.append("plan_executability_audit.path must live under run_dir")
    if audit.get("grade") not in {"green", "yellow", "red"}:
        errors.append("plan_executability_audit.grade must be green, yellow, or red")
    for key in ("blocking_issue_count", "fixable_issue_count"):
        value = audit.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"plan_executability_audit.{key} must be a non-negative integer")
    if data.get("lifecycle_outcome") == "finished" and audit.get("grade") == "red":
        errors.append("finished state cannot retain red plan_executability_audit")
```

Then call it in `validate(data)` after `_validate_graphify_audit(data, errors)`:

```python
    _validate_plan_executability_audit(data, errors)
```

- [ ] **Step 4: Add run-quality follow-up helper**

In `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`, add:

```python
PLAN_EXECUTABILITY_FIXABLE_ISSUES = "plan_executability_fixable_issues"
```

Add it to `STABLE_FOLLOWUP_ORDER` after `READINESS_FIXABLE_ISSUES`:

```python
    PLAN_EXECUTABILITY_FIXABLE_ISSUES,
```

Add this helper:

```python
def _plan_executability_fixable_count(state: dict[str, Any]) -> int:
    audit = state.get("plan_executability_audit")
    if not isinstance(audit, dict):
        return 0
    value = audit.get("fixable_issue_count")
    return value if isinstance(value, int) and value > 0 else 0
```

Then in `stable_followups(state, missing_execution_worktree=False)`, after the readiness check, add:

```python
    if _plan_executability_fixable_count(state) > 0:
        found.add(PLAN_EXECUTABILITY_FIXABLE_ISSUES)
```

- [ ] **Step 5: Add operational run-quality eval coverage**

In `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`, add a case named `plan_executability_fixable_yellow_quality`. Use the existing valid v2.22 state factory in that file and set:

```python
    state["plan_executability_audit"] = {
        "path": f"{state['run_dir']}/plan_executability_audit.json",
        "grade": "yellow",
        "blocking_issue_count": 0,
        "fixable_issue_count": 1,
    }
    state["run_quality"]["grade"] = "yellow"
    state["run_quality"]["open_followups"] = ["plan_executability_fixable_issues"]
    state["run_quality"]["readiness"]["plan_executability_fixable_issue_count"] = 1
```

Expected check:

```python
checks["plan_executability_fixable_yellow_quality"] = result.returncode == 0
```

- [ ] **Step 6: Run focused evals and confirm GREEN**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: both PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/scripts/validate_state.py skills/kws-codex-plan-executor/evals/check_state_schema.py skills/kws-codex-plan-executor/scripts/run_quality_debt.py skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat: track CPE plan executability quality"
```

## Task 3: Document Contract And Wire Eval Harness

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: audit behavior from Tasks 1 and 2.
- Produces: documented CPE contract, focused contract eval, and full eval harness inclusion.

- [ ] **Step 1: Add RED skill contract checks**

In `skills/kws-codex-plan-executor/evals/check_skill_contract.py`, after the existing `pre_dispatch = (skill_dir / "references" / "pre-dispatch-pipeline.md").read_text(encoding="utf-8")` line, read the new script and user guide:

```python
    plan_executability = (skill_dir / "scripts" / "audit_plan_executability.py").read_text(encoding="utf-8")
    user_guide = (skill_dir / "docs" / "user-guide.ko.md").read_text(encoding="utf-8")
```

Add these checks to the `checks` dictionary:

```python
        "plan_executability_audit_contract": all(
            token in runtime
            for token in (
                "audit_plan_executability.py",
                "plan_executability_audit",
                "thin_stateful_bridge",
                "before task contracts or edits",
            )
        ),
        "plan_executability_script_reuses_reason_vocabulary": all(
            token in plan_executability
            for token in (
                "adaptive_policy_local_fast_path_docs_only",
                "adaptive_policy_local_fast_path_small_scope",
                "adaptive_policy_local_fast_path_linear_task",
                "adaptive_policy_local_fast_path_low_parallel_value",
                "risk_marker_requires_operator_review",
            )
        ),
        "plan_executability_eval_in_harness": "check_plan_executability_audit.py" in eval_run,
        "korean_user_guide_mentions_readiness_summary": "readiness summary" in user_guide and "plan_executability_audit" in user_guide,
```

- [ ] **Step 2: Run contract eval and confirm RED**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected: FAIL until docs and harness are updated.

- [ ] **Step 3: Update `SKILL.md`**

In `skills/kws-codex-plan-executor/SKILL.md`, add this Core Invariants bullet after the run readiness audit bullet:

```markdown
- Execution runs produce a read-only plan executability audit before task
  contracts or edits. The audit records `plan_executability_audit` evidence,
  summarizes `thin_stateful_bridge` readiness, and classifies task-level
  `delegate`, `local_fast_path`, `operator_review`, or `block` fit without
  mutating worktrees, state, or repository files.
```

In Workflow, insert after the Superpowers compatibility step:

```markdown
4. Before task contracts or edits, run `scripts/audit_plan_executability.py`
   against parsed plan JSON and generated task packets when present. Store the
   JSON under the run directory and copy its summary into state as
   `plan_executability_audit`.
```

Renumber the following workflow items.

In the Validation Matrix `interactive` row, include:

```text
plan executability audit
```

- [ ] **Step 4: Update reference docs**

In `skills/kws-codex-plan-executor/references/execution-cycle.md`, add after task packet/run readiness creation:

```markdown
11. Run `scripts/audit_plan_executability.py` against the parsed plan JSON and
    `$RUN_DIR/task_packets` when packets exist. Save the JSON as
    `$RUN_DIR/plan_executability_audit.json`, print the short readiness summary,
    and copy `grade`, `blocking_issue_count`, and `fixable_issue_count` into
    state as `plan_executability_audit`. Blocking audit issues stop execution
    before task contracts or edits.
```

Renumber following steps.

In `skills/kws-codex-plan-executor/references/state-schema.md`, add after the Graphify audit paragraph:

```markdown
- `plan_executability_audit` records read-only output from
  `scripts/audit_plan_executability.py`. When present, `path` must live under
  `run_dir`, `grade` is `green|yellow|red`, and issue counts are non-negative
  integers. Finished states cannot retain a red plan executability audit.
```

Add this JSON example near v2.22 operational fields:

```json
"plan_executability_audit": {
  "path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/plan_executability_audit.json",
  "grade": "yellow",
  "blocking_issue_count": 0,
  "fixable_issue_count": 1
}
```

- [ ] **Step 5: Update README, ARCHITECTURE, Korean guide, and HISTORY**

In `skills/kws-codex-plan-executor/README.md`, add the new eval command to Validation:

```bash
python3 evals/check_plan_executability_audit.py
```

Add this paragraph after the Superpowers compatibility paragraph:

```markdown
Plan executability is checked with `scripts/audit_plan_executability.py`. It
summarizes whether Superpowers plan tasks are ready for CPE task packets, local
fast path, delegation, or operator review before task contracts or edits.
```

In `skills/kws-codex-plan-executor/ARCHITECTURE.md`, update the diagram flow from:

```markdown
Packet --> Compat["Superpowers compatibility audit"]
Compat --> Gate["packet quality and dispatch gate"]
```

to:

```markdown
Packet --> Compat["Superpowers compatibility audit"]
Compat --> ExecAudit["plan executability audit"]
ExecAudit --> Gate["packet quality and dispatch gate"]
```

In `skills/kws-codex-plan-executor/docs/user-guide.ko.md`, add:

```markdown
Interactive 실행은 task contract 전에 plan executability readiness summary를
보여줍니다. 이 summary는 `thin_stateful_bridge` route, delegate-ready task 수,
local-fast-path task 수, fixable issue, blocker, Graphify 같은 증거 요구를 짧게
요약합니다. 세부 JSON은 `plan_executability_audit`로 run directory에 보존됩니다.
```

In `skills/kws-codex-plan-executor/HISTORY.md`, add under `2.24.0 - 2026-06-25`:

```markdown
- Added read-only Superpowers plan executability audit design and runtime
  contract for CPE task packet readiness summaries.
```

- [ ] **Step 6: Wire full eval harness**

In `skills/kws-codex-plan-executor/evals/run.sh`, add after `check_run_readiness.py`:

```bash
python3 "$EVAL_DIR/check_plan_executability_audit.py" >/dev/null
```

- [ ] **Step 7: Run focused contract/harness checks and confirm GREEN**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
bash -n skills/kws-codex-plan-executor/evals/run.sh
```

Expected: both PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/SKILL.md skills/kws-codex-plan-executor/README.md skills/kws-codex-plan-executor/ARCHITECTURE.md skills/kws-codex-plan-executor/references/execution-cycle.md skills/kws-codex-plan-executor/references/state-schema.md skills/kws-codex-plan-executor/docs/user-guide.ko.md skills/kws-codex-plan-executor/HISTORY.md skills/kws-codex-plan-executor/evals/check_skill_contract.py skills/kws-codex-plan-executor/evals/run.sh
git commit -m "docs: document CPE plan executability audit"
```

## Task 4: Full Verification And Graphify Evidence

**Files:**
- Modify: `graphify-out/GRAPH_REPORT.md` only if `graphify update .` updates tracked Graphify output.

Note: no source files should be edited in this task unless verification exposes a defect in Tasks 1-3.

**Interfaces:**
- Consumes: all changes from Tasks 1-3.
- Produces: final verification evidence and clean diff hygiene.

- [ ] **Step 1: Run focused evals**

```bash
python3 skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
python3 skills/kws-codex-plan-executor/evals/check_superpowers_compatibility.py
python3 skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
```

Expected: all return exit 0 and print JSON with `passed: true` where applicable.

- [ ] **Step 2: Run full CPE eval harness**

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh
```

Expected: exit 0.

- [ ] **Step 3: Run Python and shell syntax checks**

```bash
python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py
bash -n skills/kws-codex-plan-executor/evals/run.sh
```

Expected: both commands return exit 0.

- [ ] **Step 4: Run repo-level hygiene**

```bash
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 5: Handle Graphify instructions**

If `graphify-out/GRAPH_REPORT.md` exists, run:

```bash
graphify update .
git status --short --untracked-files=all
```

Expected: command exits 0. If Graphify output is ignored or unchanged, record that in final evidence. If tracked Graphify output changes, inspect the diff and include it in the Task 4 commit.

- [ ] **Step 6: Commit verification-only updates if needed**

If Graphify produced tracked changes or a verification fix was required:

```bash
git add graphify-out/GRAPH_REPORT.md
git commit -m "chore: refresh CPE graphify evidence"
```

If there are no tracked verification-only changes, do not create an empty commit.

## Self-Review Checklist For Implementer

- [ ] Every task in the approved spec maps to one of Tasks 1-4.
- [ ] The new audit is read-only and does not mutate state or worktrees.
- [ ] `thin_stateful_bridge` remains the preferred interactive route when compatibility audit passes.
- [ ] Risky lockfile/security/infra paths block or require operator review before edits.
- [ ] Low-risk docs-only missing acceptance can be yellow/local-fast-path, not hard failure.
- [ ] Finished state cannot retain red `plan_executability_audit`.
- [ ] Full eval harness includes `check_plan_executability_audit.py`.
- [ ] Docs and behavior changed together.
