# AgentRunway Quality-First Hybrid Worktree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement quality-first role-aware worktree lifecycle, summary-first host context, plan linting, preflight checks, and worker lifecycle evidence for AgentRunway.

**Architecture:** Keep AgentRunway's current candidate isolation and run-main merge model. Add pure policy modules first, then route CLI/status/runner/supervisor through them so quality gates remain stronger than resource savings. Host sessions consume compact runner summaries by default, with raw logs available only through explicit deep inspection.

**Tech Stack:** Python 3.11+ stdlib, argparse, sqlite3, dataclasses, pathlib, subprocess, git worktrees, pytest, AgentRunway JSON artifacts, Markdown Superpowers docs.

---

## Source Documents

- Design: `docs/superpowers/specs/2026-05-20-agentrunway-quality-first-hybrid-worktree-design.md`
- Parent design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- Production supervisor design: `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`
- Operations quality design: `docs/superpowers/specs/2026-05-20-agentrunway-operations-quality-engine-design.md`

## Scope Check

This plan covers one coherent operational slice. It has several modules, but
they all serve one flow:

```text
lint plan -> preflight run -> dispatch role-aware workers -> persist evidence
  -> summarize run -> retain or clean worktrees without losing quality evidence
```

Do not rewrite AgentRunway. Do not replace the current run main worktree or
candidate merge queue. The work should land in small commits so a failed slice
can be reverted without losing previous hardening.

## File Structure

### Create

| Path | Responsibility |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/plan_lint.py` | Static plan/spec validation before worker dispatch. |
| `skills/agent-runway/scripts/agentrunway/preflight.py` | Adapter, git, artifact, and worktree write checks before model calls. |
| `skills/agent-runway/scripts/agentrunway/run_summary.py` | Compact bounded summary and fallback reconstruction from SQLite/events. |
| `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py` | Role-aware lifecycle decisions, retention states, and archival evidence contract. |
| `skills/agent-runway/evals/test_plan_lint.py` | Unit tests for plan lint failures and success. |
| `skills/agent-runway/evals/test_preflight.py` | Unit tests for preflight checks. |
| `skills/agent-runway/evals/test_run_summary.py` | Unit tests for summary output and missing `run.json` fallback. |
| `skills/agent-runway/evals/test_worker_timing.py` | Unit tests for worker `started_at` and `ended_at`. |
| `skills/agent-runway/evals/test_worktree_lifecycle.py` | Unit tests for role-aware lifecycle policy. |
| `skills/agent-runway/evals/test_reviewer_lifecycle.py` | Unit tests for diff review and full-tree escalation decisions. |

### Modify

| Path | Change |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | Add `lint-plan` and `summarize`; add `inspect --deep`. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Run lint/preflight before dispatch; write summary after state transitions. |
| `skills/agent-runway/scripts/agentrunway/status.py` | Render summary-first status and AgentLens disabled notice. |
| `skills/agent-runway/scripts/agentrunway/db.py` | Persist worker timing and worktree lifecycle. |
| `skills/agent-runway/scripts/agentrunway/supervisor.py` | Mark worker start/end times; use role-aware reviewer/verifier worktree policy. |
| `skills/agent-runway/scripts/agentrunway/packetizer.py` | Include review mode and bounded artifact refs in role prompts. |
| `skills/agent-runway/scripts/agentrunway/retention.py` | Preserve archived evidence before worktree cleanup. |
| `skills/agent-runway/scripts/agentrunway/result_validation.py` | Accept reviewer `needs_context` and require review mode. |
| `skills/agent-runway/scripts/agentrunway/models.py` | Add worktree lifecycle and review mode constants if enum coverage is preferred. |
| `skills/agent-runway/README.md` | Document hybrid worktree and summary-first operation. |
| `skills/agent-runway/references/context-policy.md` | Document summary-first host context and deep inspect. |
| `skills/agent-runway/references/worktree-policy.md` | Document implementer/reviewer/verifier lifecycle. |
| `skills/agent-runway/references/watchdog.md` | Document worker timing and stale lease diagnosis. |

---

## Task 1: Add Plan Lint CLI

```yaml agentrunway-task
task_id: task_001
title: Add Plan Lint CLI
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.10.3, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/plan_lint.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_plan_lint.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_plan_lint.py -v
  - cd skills/agent-runway && python scripts/agentrunway.py lint-plan --plan ../../docs/superpowers/plans/2026-05-20-agentrunway-quality-first-hybrid-worktree.md --spec ../../docs/superpowers/specs/2026-05-20-agentrunway-quality-first-hybrid-worktree-design.md --json
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/plan_lint.py`
- Create: `skills/agent-runway/evals/test_plan_lint.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`

- [ ] **Step 1: Write failing plan lint tests**

Create `skills/agent-runway/evals/test_plan_lint.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.plan_lint import lint_plan


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _spec(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "design.md",
        "# Design\n\n## Summary\n\nContext.\n\n## API\n\nDetails.\n",
    )


def _valid_plan() -> str:
    fence = "```yaml agentrunway" + "-task"
    return (
        "# Demo Implementation Plan\n\n"
        "### Task 1: First\n\n"
        f"{fence}\n"
        "task_id: task_001\n"
        "title: First\n"
        "risk: medium\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: src/example.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
        "required_skills: [using-superpowers, test-driven-development]\n"
        "serial: true\n"
        "```\n\n"
        "Implement the first task.\n"
    )


def test_valid_plan_has_no_errors(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan())
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is True
    assert result.errors == []


def test_missing_task_block_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", "# Plan\n\n### Task 1: Missing\n")
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is False
    assert any(item.code == "missing_task_block" for item in result.errors)


def test_unknown_dependency_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("dependencies: []", "dependencies: [task_999]"),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "unknown_dependency" for item in result.errors)


def test_missing_acceptance_command_for_owned_file_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace(
            "acceptance_commands: [python -m pytest tests/test_example.py -v]",
            "acceptance_commands: []",
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "missing_acceptance_commands" for item in result.errors)


def test_forbidden_owned_path_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "graphify-out/GRAPH_REPORT.md"),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "forbidden_owned_path" for item in result.errors)


def test_empty_plan_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", "# Empty plan\n")
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is False
    assert any(item.code == "missing_task_block" for item in result.errors)


def test_implementation_task_without_file_claims_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace(
            "file_claims:\n"
            "  - {path: src/example.py, mode: owned}\n",
            "file_claims: []\n",
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "missing_file_claims" for item in result.errors)


def test_glob_owned_claim_overlap_is_error_when_unordered(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "src/**")
        + (
            "\n### Task 2: Second\n\n"
            "```yaml agentrunway-task\n"
            "task_id: task_002\n"
            "title: Second\n"
            "risk: high\n"
            "phase: implementation\n"
            "dependencies: []\n"
            "spec_refs: [S1]\n"
            "file_claims:\n"
            "  - {path: src/foo.py, mode: owned}\n"
            "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
            "required_skills: [using-superpowers, test-driven-development]\n"
            "serial: true\n"
            "```\n\n"
            "Implement the second task.\n"
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "owned_claim_conflict" for item in result.errors)


def test_dependency_ordered_owned_claim_overlap_is_allowed(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "src/**").replace("risk: medium", "risk: high")
        + (
            "\n### Task 2: Second\n\n"
            "```yaml agentrunway-task\n"
            "task_id: task_002\n"
            "title: Second\n"
            "risk: medium\n"
            "phase: implementation\n"
            "dependencies: [task_001]\n"
            "spec_refs: [S1]\n"
            "file_claims:\n"
            "  - {path: src/foo.py, mode: owned}\n"
            "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
            "required_skills: [using-superpowers, test-driven-development]\n"
            "serial: true\n"
            "```\n\n"
            "Implement the second task.\n"
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is True


def test_broad_owned_glob_requires_high_risk(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("src/example.py", "src/**"))
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "broad_glob_requires_high_risk" for item in result.errors)


def test_invalid_risk_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("risk: medium", "risk: banana"))
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "invalid_risk" for item in result.errors)


def test_rootless_numbered_spec_refs_resolve(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "numbered.md",
        "# Design\n\n"
        + "".join(
            f"## {index}. Section\n\nDetails.\n\n"
            + ("### 10.3 Plan Lint\n\nDetails.\n\n" if index == 10 else "")
            for index in range(1, 13)
        ),
    )
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("spec_refs: [S1]", "spec_refs: [S10.3, S12]"))
    result = lint_plan(plan_path=plan, spec_path=spec)

    assert result.ok is True
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_plan_lint.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.plan_lint'`.

- [ ] **Step 3: Implement `plan_lint.py`**

Create `skills/agent-runway/scripts/agentrunway/plan_lint.py`:

Implementation requirements:

- return `missing_task_block` when `parse_plan()` returns no tasks;
- return `missing_file_claims` for implementation-phase tasks without file claims;
- reject invalid `risk` values with `invalid_risk`;
- reject owned broad globs below high risk with `broad_glob_requires_high_risk`;
- detect unsafe owned path overlaps, including glob-to-file overlaps such as `src/**` and `src/foo.py`;
- allow repeated/overlapping ownership only when the tasks are dependency-ordered;
- resolve spec refs both as parser ids such as `S1.10.3` and rootless document ids such as `S10.3`.

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import TaskSpec
from .plan_parser import PlanParseError, parse_plan, parse_spec_manifest


FORBIDDEN_OWNED_PREFIXES = ("graphify-out/", ".git/", ".agentrunway/")


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


def _is_code_changing(task: TaskSpec) -> bool:
    return any(claim.mode in {"owned", "shared_append"} for claim in task.file_claims)


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
    owned_paths: dict[str, str] = {}
    for task in tasks:
        if _is_code_changing(task) and not task.acceptance_commands:
            errors.append(
                LintIssue(
                    code="missing_acceptance_commands",
                    message=f"{task.task_id} changes code but has no acceptance commands",
                    task_id=task.task_id,
                )
            )
        for claim in task.file_claims:
            if claim.mode == "owned" and claim.path.startswith(FORBIDDEN_OWNED_PREFIXES):
                errors.append(
                    LintIssue(
                        code="forbidden_owned_path",
                        message=f"{task.task_id} claims forbidden path {claim.path}",
                        task_id=task.task_id,
                        path=claim.path,
                    )
                )
            if claim.mode == "owned":
                previous = owned_paths.get(claim.path)
                if previous is not None and previous != task.task_id:
                    errors.append(
                        LintIssue(
                            code="owned_claim_conflict",
                            message=f"{claim.path} is owned by both {previous} and {task.task_id}",
                            task_id=task.task_id,
                            path=claim.path,
                        )
                    )
                owned_paths[claim.path] = task.task_id
    return errors


def _spec_ref_errors(tasks: list[TaskSpec], spec_path: Path | None) -> list[LintIssue]:
    if spec_path is None:
        return []
    manifest = parse_spec_manifest(spec_path)
    sections = set(manifest["sections"].keys())
    errors: list[LintIssue] = []
    for task in tasks:
        for ref in task.spec_refs:
            if ref and ref not in sections:
                errors.append(
                    LintIssue(
                        code="unresolved_spec_ref",
                        message=f"{task.task_id} references missing spec section {ref}",
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
        for claim in task.file_claims:
            if claim.path.endswith("/**") and task.risk != "high":
                warnings.append(
                    LintIssue(
                        code="broad_glob_without_high_risk",
                        message=f"{task.task_id} has broad claim {claim.path} without high risk",
                        task_id=task.task_id,
                        path=claim.path,
                    )
                )

    errors.extend(_dependency_errors(tasks))
    errors.extend(_cycle_errors(tasks))
    errors.extend(_claim_errors(tasks))
    errors.extend(_spec_ref_errors(tasks, spec_path))
    return LintResult(ok=not errors, errors=errors, warnings=warnings, task_count=len(tasks))
```

- [ ] **Step 4: Add `lint-plan` to CLI**

Modify `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
COMMANDS = ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean", "lint-plan")
```

Add this parser block after `clean`:

```python
    lint = sub.add_parser("lint-plan", help="lint a AgentRunway plan before dispatch")
    lint.add_argument("--plan", type=Path, required=True)
    lint.add_argument("--spec", type=Path)
    lint.add_argument("--json", action="store_true")
```

Add this branch inside `main` before the final `else`:

```python
        elif args.command == "lint-plan":
            from .plan_lint import lint_plan

            result = lint_plan(plan_path=args.plan.resolve(), spec_path=args.spec.resolve() if args.spec else None)
            payload = result.to_dict()
            if not result.ok:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
                return 1
```

- [ ] **Step 5: Verify tests and CLI**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_plan_lint.py -v
cd skills/agent-runway && python scripts/agentrunway.py lint-plan --plan ../../docs/superpowers/plans/2026-05-20-agentrunway-quality-first-hybrid-worktree.md --spec ../../docs/superpowers/specs/2026-05-20-agentrunway-quality-first-hybrid-worktree-design.md --json
```

Expected: pytest passes. CLI exits `0` and prints JSON with `"ok": true`.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/plan_lint.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/evals/test_plan_lint.py
git commit -m "feat: add AgentRunway plan lint"
```

---

## Task 2: Add Adapter and Workspace Preflight

```yaml agentrunway-task
task_id: task_002
title: Add Adapter and Workspace Preflight
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S1.10.2, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/preflight.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_preflight.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_preflight.py -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/preflight.py`
- Create: `skills/agent-runway/evals/test_preflight.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`

- [ ] **Step 1: Write failing preflight tests**

Create `skills/agent-runway/evals/test_preflight.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentrunway.preflight import PreflightIssue, run_preflight


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "agentrunway@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "AgentRunway Test"], cwd=path, check=True)
    (path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    return path


def test_local_preflight_passes_for_writable_repo_and_run_dir(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    run_dir = tmp_path / "run"
    worktree_root = tmp_path / "worktrees"

    result = run_preflight(adapter_name="local", repo=repo, run_dir=run_dir, worktree_root=worktree_root)

    assert result.ok is True
    assert result.issues == []


def test_preflight_reports_missing_adapter_binary(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    result = run_preflight(adapter_name="codex", repo=repo, run_dir=tmp_path / "run", worktree_root=tmp_path / "worktrees")

    assert result.ok is False
    assert PreflightIssue(code="missing_adapter_binary", detail="codex") in result.issues


def test_preflight_reports_missing_git_identity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path / "home")}

    result = run_preflight(adapter_name="local", repo=repo, run_dir=tmp_path / "run", worktree_root=tmp_path / "worktrees", env=env)

    assert any(issue.code == "git_identity_missing" for issue in result.issues)
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_preflight.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.preflight'`.

- [ ] **Step 3: Implement `preflight.py`**

Create `skills/agent-runway/scripts/agentrunway/preflight.py`:

```python
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    issues: list[PreflightIssue]

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "issues": [issue.to_dict() for issue in self.issues]}


def _run_git(repo: Path, args: list[str], env: Mapping[str, str] | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, env=dict(env or os.environ))


def _check_git_identity(repo: Path, env: Mapping[str, str] | None) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    email = _run_git(repo, ["config", "user.email"], env)
    name = _run_git(repo, ["config", "user.name"], env)
    if email.returncode != 0 or not email.stdout.strip() or name.returncode != 0 or not name.stdout.strip():
        issues.append(PreflightIssue("git_identity_missing", "git user.name and user.email must be configured"))
    return issues


def _check_writable(path: Path, label: str) -> list[PreflightIssue]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".agentrunway-preflight"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return [PreflightIssue("path_not_writable", f"{label}: {exc}")]
    return []


def _check_adapter_binary(adapter_name: str) -> list[PreflightIssue]:
    if adapter_name == "local":
        return []
    binary = {"codex": "codex", "claude": "claude"}.get(adapter_name)
    if binary is None:
        return [PreflightIssue("unsupported_adapter", adapter_name)]
    if shutil.which(binary) is None:
        return [PreflightIssue("missing_adapter_binary", binary)]
    return []


def run_preflight(
    *,
    adapter_name: str,
    repo: Path,
    run_dir: Path,
    worktree_root: Path,
    env: Mapping[str, str] | None = None,
) -> PreflightResult:
    issues: list[PreflightIssue] = []
    issues.extend(_check_adapter_binary(adapter_name))
    issues.extend(_check_writable(run_dir, "run_dir"))
    issues.extend(_check_writable(worktree_root.parent, "worktree_parent"))
    issues.extend(_check_git_identity(repo, env))
    git_dir = _run_git(repo, ["rev-parse", "--git-common-dir"], env)
    if git_dir.returncode != 0 or not git_dir.stdout.strip():
        issues.append(PreflightIssue("git_common_dir_unavailable", git_dir.stderr.strip() or "unknown git error"))
    return PreflightResult(ok=not issues, issues=issues)
```

- [ ] **Step 4: Call preflight before model dispatch**

Modify `skills/agent-runway/scripts/agentrunway/runner.py` near the run setup after `run_dir` and `worktree_root` are created and before `db.create_run`:

```python
    from .preflight import run_preflight

    preflight = run_preflight(adapter_name=args.adapter, repo=repo, run_dir=run_dir, worktree_root=worktree_root)
    if not preflight.ok:
        return {
            "run_id": run_id,
            "status": "preflight_failed",
            "preflight": preflight.to_dict(),
        }
```

Keep `local` adapter fast and side-effect light. Do not create worker worktrees
inside preflight.

- [ ] **Step 5: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_preflight.py -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: preflight tests pass. Full eval suite remains green.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/preflight.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_preflight.py
git commit -m "feat: preflight AgentRunway runs"
```

---

## Task 3: Add Summary-First Status and Missing Run JSON Fallback

```yaml agentrunway-task
task_id: task_003
title: Add Summary-First Status and Missing Run JSON Fallback
risk: high
phase: implementation
dependencies: [task_001, task_002]
spec_refs: [S1.9, S1.10.1, S1.10.6, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_run_summary.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_run_summary.py evals/test_artifact_graph_status.py -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/run_summary.py`
- Create: `skills/agent-runway/evals/test_run_summary.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`

- [ ] **Step 1: Write failing summary tests**

Create `skills/agent-runway/evals/test_run_summary.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.run_summary import build_run_summary, reconstruct_run_json


def _db(path: Path) -> AgentRunwayDb:
    db = AgentRunwayDb.open(path)
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(path.parent),
        plan_path=str(path.parent / "plan.md"),
        spec_path=None,
        plan_hash="sha256:plan",
        spec_hash=None,
        base_commit_sha="abc123",
        model_profile="default",
        allowed_dirty=False,
        apply_to_source=False,
    )
    return db


def test_summary_is_bounded_and_contains_next_action(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    run_json = {"run_id": "run-1", "status": "running", "run_dir": str(run_dir), "state_db": str(run_dir / "state.sqlite"), "tasks": []}

    summary = build_run_summary(run_json=run_json, db=db, event_tail=3)

    assert summary["run_id"] == "run-1"
    assert summary["status"] == "running"
    assert summary["next_action"]
    assert "artifact_refs" in summary


def test_reconstruct_run_json_from_sqlite_when_run_json_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _db(run_dir / "state.sqlite")
    (run_dir / "events.jsonl").write_text(json.dumps({"event_type": "agentrunway.run_started"}) + "\n", encoding="utf-8")

    reconstructed = reconstruct_run_json(run_id="run-1", run_dir=run_dir)

    assert reconstructed["run_id"] == "run-1"
    assert reconstructed["status"] == "created"
    assert reconstructed["run_dir"] == str(run_dir)
    assert "run.json" in reconstructed["reconstructed_from"]
    assert "state.sqlite" in reconstructed["reconstructed_from"]


def test_summary_marks_agentlens_disabled_notice(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    run_json = {"run_id": "run-1", "status": "finished", "run_dir": str(run_dir), "state_db": str(run_dir / "state.sqlite"), "tasks": []}

    summary = build_run_summary(run_json=run_json, db=db)

    assert summary["agentlens_notice"] == "AgentLens disabled; local SQLite and artifacts are authoritative."
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.run_summary'`.

- [ ] **Step 3: Implement `run_summary.py`**

Create `skills/agent-runway/scripts/agentrunway/run_summary.py`:

```python
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .diagnostics import diagnose_run


AGENTLENS_DISABLED_NOTICE = "AgentLens disabled; local SQLite and artifacts are authoritative."


def _safe_events_tail(run_dir: Path, limit: int) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event_type": "malformed_event"})
    return rows


def reconstruct_run_json(*, run_id: str, run_dir: Path) -> dict[str, Any]:
    state_db = run_dir / "state.sqlite"
    reconstructed_from = ["run.json"]
    if not state_db.exists():
        # Do NOT return a state_db path that does not exist; callers will
        # AgentRunwayDb.open(path) and inadvertently create an empty SQLite
        # file as a side effect. Summarize must treat this as terminal.
        return {
            "run_id": run_id,
            "status": "missing",
            "run_dir": str(run_dir),
            "state_db": None,
            "tasks": [],
            "reconstructed_from": reconstructed_from,
            "recovery": "no_state_sqlite",
        }
    db = AgentRunwayDb.open(state_db)
    run = db.get_run(run_id)
    reconstructed_from.append("state.sqlite")
    return {
        "run_id": run_id,
        "status": run.get("status", "unknown"),
        "run_dir": str(run_dir),
        "state_db": str(state_db),
        "tasks": db.list_tasks(),
        "main_worktree": "",
        "reconstructed_from": reconstructed_from,
    }


def build_run_summary(*, run_json: dict[str, Any], db: AgentRunwayDb, event_tail: int = 20) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    tasks = db.list_tasks() if (run_dir / "state.sqlite").exists() else list(run_json.get("tasks") or [])
    task_counts = Counter(str(task.get("status", "unknown")) for task in tasks)
    diagnosis = diagnose_run(run_json=run_json, db=db).to_dict()
    agentlens = db.agentlens_summary()
    blocked_tasks = [
        {"task_id": task.get("task_id"), "status": task.get("status"), "reason": diagnosis.get("reason")}
        for task in tasks
        if str(task.get("status")) == "blocked"
    ]
    ranked_events = [
        event.get("payload", {})
        for event in db.list_events()
        if event.get("event_type") == "agentrunway.candidate_ranked"
    ]
    selected_ids = {
        int(payload.get("selected_candidate_id"))
        for payload in ranked_events
        if payload.get("selected_candidate_id") is not None
    }
    summary = {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "base_commit": run_json.get("base_commit_sha") or run_json.get("base_commit"),
        "task_counts": dict(sorted(task_counts.items())),
        "current_task": blocked_tasks[0]["task_id"] if blocked_tasks else None,
        "next_action": diagnosis["next_action"],
        "selected_candidates": [
            candidate
            for candidate in db.list_merge_candidates()
            if int(candidate.get("id", -1)) in selected_ids or candidate.get("status") == "merged"
        ],
        "blocked_tasks": blocked_tasks,
        "quality_decisions": [
            event.get("payload", {})
            for event in db.list_events()
            if event.get("event_type") == "agentrunway.quality_decision"
        ],
        "residual_risks": [],
        "agentlens": agentlens,
        "agentlens_notice": AGENTLENS_DISABLED_NOTICE if agentlens.get("run_status") == "disabled" else "",
        "event_tail": _safe_events_tail(run_dir, event_tail),
        "artifact_refs": {
            "events": str(run_dir / "events.jsonl"),
            "state": str(run_dir / "state.sqlite"),
            "run": str(run_dir / "run.json"),
        },
    }
    if "reconstructed_from" in run_json:
        summary["reconstructed_from"] = run_json["reconstructed_from"]
    return summary
```

- [ ] **Step 4: Add `summarize` CLI and fallback loading**

Modify `COMMANDS` in `skills/agent-runway/scripts/agentrunway/invocation.py`:

```python
COMMANDS = ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean", "lint-plan", "summarize")
```

Add parser:

```python
    summarize = sub.add_parser("summarize", help="summarize a AgentRunway run")
    summarize.add_argument("--run")
    summarize.add_argument("--last", action="store_true")
    summarize.add_argument("--json", action="store_true")
```

Add main branch:

```python
        elif args.command == "summarize":
            payload = runner.summarize(resolve_run_alias(repo_root, args.run, bool(args.last)))
```

Modify `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
def _load_run_json_or_reconstruct(run_id: str) -> dict[str, Any] | None:
    data = _load_run_json(run_id)
    if data is not None:
        return data
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        return None
    from .run_summary import reconstruct_run_json

    return reconstruct_run_json(run_id=run_id, run_dir=run_dir)
```

Add:

```python
def summarize(run_id: str) -> dict[str, Any]:
    data = _load_run_json_or_reconstruct(run_id)
    if data is None:
        return _missing(run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        # Short-circuit: do not open a non-existent sqlite path, which would
        # create an empty database as a side effect. Return a labeled
        # no-recoverable-state payload instead.
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    from .run_summary import build_run_summary

    db = AgentRunwayDb.open(Path(str(state_db)))
    return build_run_summary(run_json=data, db=db)
```

Update `status` and `inspect` to use `_load_run_json_or_reconstruct(run_id)`
instead of `_load_run_json(run_id)`.

- [ ] **Step 5: Render AgentLens disabled notice**

Modify `skills/agent-runway/scripts/agentrunway/status.py` inside `format_run_status`:

```python
    notice = ""
    if isinstance(agentlens, dict) and agentlens.get("run_status") == "disabled":
        notice = " AgentLens disabled; local SQLite and artifacts are authoritative."
```

Append `notice` to the returned string.

- [ ] **Step 6: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py evals/test_artifact_graph_status.py -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: summary tests pass and the full eval suite remains green.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/run_summary.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/scripts/agentrunway/status.py skills/agent-runway/scripts/agentrunway/invocation.py skills/agent-runway/evals/test_run_summary.py
git commit -m "feat: summarize AgentRunway runs"
```

---

## Task 4: Persist Worker Timing and Lease Evidence

```yaml agentrunway-task
task_id: task_004
title: Persist Worker Timing and Lease Evidence
risk: medium
phase: implementation
dependencies: [task_003]
spec_refs: [S1.8.1, S1.10.4, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_worker_timing.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_worker_timing.py evals/test_supervisor_state.py -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/evals/test_worker_timing.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/run_summary.py`

- [ ] **Step 1: Write failing timing tests**

Create `skills/agent-runway/evals/test_worker_timing.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb


def test_worker_attempt_records_started_and_ended_at(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="local",
        model="local",
        reasoning_effort="n/a",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="worktree_created",
        handle_json={},
    )

    db.mark_worker_started("task_001-implementer-001")
    db.mark_worker_ended("task_001-implementer-001", "validated")
    worker = db.get_worker("task_001-implementer-001")

    assert worker["started_at"]
    assert worker["ended_at"]
    assert worker["state"] == "validated"
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_worker_timing.py -v
```

Expected: `AttributeError: 'AgentRunwayDb' object has no attribute 'mark_worker_started'`.

- [ ] **Step 3: Add DB timing methods**

Modify `skills/agent-runway/scripts/agentrunway/db.py`:

```python
    def mark_worker_started(self, worker_id: str) -> None:
        self.conn.execute(
            """
            UPDATE workers
            SET started_at=COALESCE(started_at, CURRENT_TIMESTAMP),
                state='running',
                updated_at=CURRENT_TIMESTAMP
            WHERE worker_id=?
            """,
            (worker_id,),
        )
        self.conn.commit()

    def mark_worker_ended(self, worker_id: str, state: str) -> None:
        self.conn.execute(
            """
            UPDATE workers
            SET ended_at=COALESCE(ended_at, CURRENT_TIMESTAMP),
                state=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE worker_id=?
            """,
            (state, worker_id),
        )
        self.conn.commit()
```

- [ ] **Step 4: Use timing methods in supervisor**

Modify `skills/agent-runway/scripts/agentrunway/supervisor.py` in
`run_worker_attempt`:

```python
    handle = adapter.start(adapter.prepare(spec))
    db.mark_worker_started(worker_id)
    db.update_worker_handle(worker_id, handle.to_json())
    envelope = adapter.collect(handle)
    db.mark_worker_ended(worker_id, "result_collected")
```

Keep later calls such as `db.set_worker_state(worker_id, "validated")` for state
transitions. Do not clear `ended_at` after result collection.

- [ ] **Step 5: Add timing to summary**

Modify `skills/agent-runway/scripts/agentrunway/run_summary.py` inside
`build_run_summary`:

```python
    workers = db.list_workers()
```

Add to the returned `summary`:

```python
        "worker_durations": [
            {
                "worker_id": worker.get("worker_id"),
                "role": worker.get("role"),
                "started_at": worker.get("started_at"),
                "ended_at": worker.get("ended_at"),
                "state": worker.get("state"),
            }
            for worker in workers
        ],
```

- [ ] **Step 6: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_worker_timing.py evals/test_supervisor_state.py -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: timing tests pass. Full eval suite remains green.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/db.py skills/agent-runway/scripts/agentrunway/supervisor.py skills/agent-runway/scripts/agentrunway/run_summary.py skills/agent-runway/evals/test_worker_timing.py
git commit -m "feat: record AgentRunway worker timing"
```

---

## Task 5: Add Worktree Lifecycle Policy and Evidence Archival

```yaml agentrunway-task
task_id: task_005
title: Add Worktree Lifecycle Policy and Evidence Archival
risk: high
phase: implementation
dependencies: [task_004]
spec_refs: [S1.6, S1.14, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: shared_append}
  - {path: skills/agent-runway/scripts/agentrunway/retention.py, mode: owned}
  - {path: skills/agent-runway/evals/test_worktree_lifecycle.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_worktree_lifecycle.py evals/test_retention_clean.py -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`
- Create: `skills/agent-runway/evals/test_worktree_lifecycle.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/scripts/agentrunway/retention.py`

- [ ] **Step 1: Write failing lifecycle tests**

Create `skills/agent-runway/evals/test_worktree_lifecycle.py`:

```python
from __future__ import annotations

from agentrunway.worktree_lifecycle import (
    WorktreeLifecycle,
    lifecycle_for_worker,
    should_create_reviewer_worktree,
)


def test_implementer_candidate_is_retained_for_apply() -> None:
    state = lifecycle_for_worker(role="implementer", candidate_status="merge_ready", run_status="finished")

    assert state == WorktreeLifecycle.RETAINED_FOR_APPLY


def test_successful_verifier_is_cleanup_eligible_after_evidence_archive() -> None:
    state = lifecycle_for_worker(role="verifier", candidate_status="passed", run_status="finished", evidence_archived=True)

    assert state == WorktreeLifecycle.CLEANUP_ELIGIBLE


def test_failed_verifier_is_retained_for_diagnosis() -> None:
    state = lifecycle_for_worker(role="verifier", candidate_status="failed", run_status="blocked", evidence_archived=True)

    assert state == WorktreeLifecycle.RETAINED_FOR_DIAGNOSIS


def test_reviewer_escalates_for_high_risk() -> None:
    assert should_create_reviewer_worktree(task_risk="high", diff_line_count=20, changed_files=["src/a.py"]) is True


def test_reviewer_uses_diff_mode_for_small_medium_risk_change() -> None:
    assert should_create_reviewer_worktree(task_risk="medium", diff_line_count=20, changed_files=["src/a.py"]) is False
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_worktree_lifecycle.py -v
```

Expected: `ModuleNotFoundError: No module named 'agentrunway.worktree_lifecycle'`.

- [ ] **Step 3: Implement `worktree_lifecycle.py`**

Create `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`:

```python
from __future__ import annotations

from enum import Enum


class WorktreeLifecycle(str, Enum):
    ACTIVE = "active"
    EVIDENCE_ARCHIVED = "evidence_archived"
    RETAINED_FOR_APPLY = "retained_for_apply"
    RETAINED_FOR_DIAGNOSIS = "retained_for_diagnosis"
    CLEANUP_ELIGIBLE = "cleanup_eligible"
    REMOVED = "removed"


REVIEWER_FULL_TREE_EXTENSIONS = (".sql", ".sqlite", ".db", ".lock")
REVIEWER_FULL_TREE_PATH_PARTS = ("/migrations/", "/schema/", "/generated/")


def should_create_reviewer_worktree(
    *,
    task_risk: str,
    diff_line_count: int,
    changed_files: list[str],
    needs_context: bool = False,
    threshold: int = 400,
) -> bool:
    if needs_context or task_risk == "high" or diff_line_count > threshold:
        return True
    for path in changed_files:
        if path.endswith(REVIEWER_FULL_TREE_EXTENSIONS):
            return True
        if any(part in f"/{path}" for part in REVIEWER_FULL_TREE_PATH_PARTS):
            return True
    return False


def lifecycle_for_worker(
    *,
    role: str,
    candidate_status: str,
    run_status: str,
    evidence_archived: bool = False,
) -> WorktreeLifecycle:
    if role == "implementer" and candidate_status in {"merge_ready", "merged"}:
        return WorktreeLifecycle.RETAINED_FOR_APPLY
    if run_status in {"blocked", "failed", "cancelled"}:
        return WorktreeLifecycle.RETAINED_FOR_DIAGNOSIS
    if role in {"reviewer", "verifier"} and evidence_archived:
        return WorktreeLifecycle.CLEANUP_ELIGIBLE
    if evidence_archived:
        return WorktreeLifecycle.EVIDENCE_ARCHIVED
    return WorktreeLifecycle.ACTIVE
```

- [ ] **Step 4: Add DB helper for worktree lifecycle**

Modify `skills/agent-runway/scripts/agentrunway/db.py`:

```python
    def register_worktree(self, *, path: str, workspace_id: str, run_id: str, branch: str, lifecycle: str) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO worktree_registry (path, workspace_id, run_id, branch, lifecycle)
            VALUES (?, ?, ?, ?, ?)
            """,
            (path, workspace_id, run_id, branch, lifecycle),
        )
        self.conn.commit()

    def set_worktree_lifecycle(self, path: str, lifecycle: str) -> None:
        self.conn.execute("UPDATE worktree_registry SET lifecycle=? WHERE path=?", (lifecycle, path))
        self.conn.commit()
```

- [ ] **Step 4b: Wire `register_worktree` into supervisor**

The `worktree_registry` table already exists in `db.py` but no caller populates
it. Without registration, every lifecycle setter call no-ops and the
lifecycle-aware retention branch added below is dead code. Add registration at
the single creation site so all roles get a row with `lifecycle="active"`.

Modify `skills/agent-runway/scripts/agentrunway/supervisor.py` in
`run_worker_attempt`, immediately after `create_worker_worktree(...)`:

```python
    worker_tree = create_worker_worktree(git, worktree_root / "workers" / worker_id, branch, base_commit)
    db.register_worktree(
        path=str(worker_tree),
        workspace_id=str(run_id.split("/")[0]) if "/" in str(run_id) else "default",
        run_id=run_id,
        branch=branch,
        lifecycle="active",
    )
```

Pass the supervisor a real `workspace_id` if it already plumbs one; if not,
fall back to the value the runner uses for the run main worktree. The exact
value matters less than having a row keyed by `path`. Add a regression
assertion in `test_worker_worktrees.py` (or extend an existing
`test_supervisor_state.py` case) that, after `run_worker_attempt`, the
registry contains a row for the new path with `lifecycle="active"`.

- [ ] **Step 5: Make retention lifecycle-aware**

Modify `skills/agent-runway/scripts/agentrunway/retention.py` so worktrees with
a matching run are not always retained. Add this helper:

```python
def _lifecycle_for_worktree(run_dir: Path, worktree_dir: Path) -> str | None:
    db_path = run_dir / "state.sqlite"
    if not db_path.exists():
        return None
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT lifecycle FROM worktree_registry WHERE path=?",
            (str(worktree_dir),),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row else None
```

In `plan_retention_clean`, replace the `matching_run.exists()` block with:

```python
            if matching_run.exists():
                lifecycle = _lifecycle_for_worktree(matching_run, worktree_dir)
                if lifecycle == "cleanup_eligible" and _is_old(worktree_dir, cutoff):
                    candidates.append(_candidate("worktree", worktree_dir, "lifecycle_cleanup_eligible"))
                    continue
                retained.append(_candidate("worktree", worktree_dir, "matching_run_exists"))
                continue
```

- [ ] **Step 6: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_worktree_lifecycle.py evals/test_retention_clean.py -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: lifecycle and retention tests pass. Full eval suite remains green.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py skills/agent-runway/scripts/agentrunway/db.py skills/agent-runway/scripts/agentrunway/retention.py skills/agent-runway/evals/test_worktree_lifecycle.py
git commit -m "feat: add AgentRunway worktree lifecycle policy"
```

---

## Task 6: Add Hybrid Reviewer and Ephemeral Verifier Flow

```yaml agentrunway-task
task_id: task_006
title: Add Hybrid Reviewer and Ephemeral Verifier Flow
risk: high
phase: implementation
dependencies: [task_005]
spec_refs: [S1.6.3, S1.6.4, S1.10.5, S1.12, S1.13]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/packetizer.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/result_validation.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_reviewer_lifecycle.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_reviewer_lifecycle.py evals/test_runner_production_e2e.py::test_reviewer_and_verifier_worktrees_include_candidate_files -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/evals/test_reviewer_lifecycle.py`
- Modify: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/packetizer.py`
- Modify: `skills/agent-runway/scripts/agentrunway/result_validation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Write failing reviewer lifecycle tests**

Create `skills/agent-runway/evals/test_reviewer_lifecycle.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.packetizer import materialize_role_prompt
from agentrunway.result_validation import validate_review_result


def _task(risk: str = "medium") -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Review lifecycle",
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_reviewer_prompt_records_diff_mode(tmp_path: Path) -> None:
    output = tmp_path / "review_result.json"
    prompt = materialize_role_prompt(
        role="reviewer",
        task=_task(),
        worker_id="task_001-reviewer-001",
        packet_path=tmp_path / "packet.json",
        output_path=output,
        prompt_dir=tmp_path,
        context={"review_mode": "diff", "diff": "diff --git a/src/example.py b/src/example.py"},
    )

    text = prompt.read_text(encoding="utf-8")
    assert '"review_mode": "diff"' in text


def test_review_result_accepts_needs_context_status() -> None:
    result = validate_review_result(
        {
            "schema": "agentrunway.review_result.v1",
            "worker_id": "task_001-reviewer-001",
            "task_id": "task_001",
            "reviewed_worker_id": "task_001-implementer-001",
            "status": "needs_context",
            "review_mode": "diff",
            "checks": [{"name": "diff visibility", "status": "blocked"}],
            "findings": [{"severity": "major", "body": "full tree needed"}],
            "method_audit": {"used_superpowers": True},
        }
    )

    assert result["status"] == "needs_context"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_reviewer_lifecycle.py -v
```

Expected: validation fails because `needs_context` and `review_mode` are not accepted yet.

- [ ] **Step 3: Update review result validation**

Modify `skills/agent-runway/scripts/agentrunway/result_validation.py`:

```python
def validate_review_result(payload: dict[str, Any]) -> dict[str, Any]:
    required = {"schema", "worker_id", "task_id", "reviewed_worker_id", "status", "checks", "findings", "method_audit"}
    missing = required - payload.keys()
    if missing:
        raise ResultValidationError("missing review fields: " + ", ".join(sorted(missing)))
    if payload["status"] not in {"approved", "changes_requested", "rejected", "needs_context"}:
        raise ResultValidationError("invalid review status")
    review_mode = payload.get("review_mode", "full_tree")
    if review_mode not in {"diff", "full_tree"}:
        raise ResultValidationError("invalid review mode")
    payload["review_mode"] = review_mode
    findings = payload.get("findings")
    if payload["status"] == "approved" and isinstance(findings, list) and findings:
        raise ResultValidationError("approved review cannot include findings")
    return payload
```

Preserve existing schema checks around this function if the file has nearby
logic added by earlier tasks.

- [ ] **Step 4: Add review mode to prompts**

Modify `skills/agent-runway/scripts/agentrunway/packetizer.py` in
`materialize_role_prompt` so the context JSON includes the review mode exactly
as passed. No special formatting is required because the whole context is
already serialized.

Add this sentence to the reviewer prompt text:

```python
        + ("Review mode must be diff or full_tree. Do not claim full_tree review when review_mode is diff.\n" if role == "reviewer" else "")
```

Place it before `"Context JSON:\n"`.

- [ ] **Step 5: Route reviewer worktree policy**

Modify `skills/agent-runway/scripts/agentrunway/supervisor.py` in
`run_reviewer_attempt`:

```python
    from .worktree_lifecycle import should_create_reviewer_worktree

    changed_file_list = list(task_file for task_file in getattr(task, "file_claims", ()))
    review_mode = "full_tree" if should_create_reviewer_worktree(
        task_risk=task.risk,
        diff_line_count=len(candidate_diff.splitlines()),
        changed_files=[claim.path for claim in task.file_claims],
    ) else "diff"
```

Update the prompt context:

```python
        context={"reviewed_worker_id": reviewed_worker_id, "diff": candidate_diff, "review_mode": review_mode},
```

For v1, keep using `run_worker_attempt` for reviewers even in diff mode. The
next implementation can replace diff-mode reviewer execution with a no-worktree
adapter path. This task must establish the review mode contract and escalation
signals first.

The reviewer prompt must explicitly list `needs_context` as a valid status
alongside `approved`, `changes_requested`, and `rejected`, otherwise reviewers
will never emit it and the escalation in Step 5b is unreachable. Add the
reviewer-only sentence in the prompt body listing all four statuses.

- [ ] **Step 5b: Add `needs_context` escalation in the runner**

Schema acceptance is not enough. `runner.py` currently routes every
non-`approved` review status through `gate_retry_decision`, which would
treat `needs_context` as a normal retry or block. The design requires a
one-shot full-tree re-dispatch when a reviewer returns `needs_context` for a
candidate. Repeated `needs_context` collapses to the normal block path.

Modify `skills/agent-runway/scripts/agentrunway/runner.py` in the review
branch, before the `gate_retry_decision` call:

```python
                if review_status == "needs_context":
                    already_escalated = any(
                        worker.get("task_id") == task.task_id
                        and worker.get("role") == "reviewer"
                        and (worker.get("handle_json") or {}).get("review_mode") == "full_tree"
                        for worker in db.list_workers()
                    )
                    if not already_escalated:
                        journal.record(
                            "agentrunway.review_escalated",
                            build_event_payload(
                                run_id,
                                "review",
                                "partial",
                                "reviewer requested full-tree escalation",
                                task_id=task.task_id,
                                worker_id=str(candidate["worker_id"]),
                            ),
                        )
                        _, escalation_attempt = next_worker_id(db=db, task_id=task.task_id, role="reviewer")
                        review = run_reviewer_attempt(
                            db=db,
                            run_id=run_id,
                            git=git,
                            worktree_root=worktree_root,
                            run_dir=run_dir,
                            task=task,
                            adapter=adapter,
                            runtime=runtime,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            reviewed_worker_id=str(candidate["worker_id"]),
                            candidate_diff=diff,
                            candidate_commits=tuple(candidate["commits"]),
                            attempt=escalation_attempt,
                            timeout_seconds=600,
                            force_full_tree=True,
                        )
                        review_status = str(review["status"])
                        if review_status == "approved":
                            # fall through to verifier dispatch as if first review approved
                            pass
```

This requires a `force_full_tree: bool = False` parameter on
`run_reviewer_attempt` that, when true, bypasses
`should_create_reviewer_worktree` and emits the prompt with
`review_mode="full_tree"`. The track-via-`handle_json` heuristic above is a
v1 mechanism; a follow-up should persist `review_mode` as a column on
`workers` so the escalation-already-used check is not a JSON probe.

Cover this in `evals/test_reviewer_lifecycle.py` with one new test that
constructs a fake reviewer returning `needs_context` first and `approved` on
the escalated full-tree pass, then asserts a single
`agentrunway.review_escalated` event is recorded and that the candidate
proceeds to the verifier dispatch.

- [ ] **Step 6: Keep verifier candidate-head visibility**

Confirm `run_verifier_attempt` uses:

```python
candidate_head = commits[-1] if commits else f"agentrunway/{run_id}/main"
```

If the line differs, restore it. Add a regression assertion to
`test_reviewer_and_verifier_worktrees_include_candidate_files` that every
reviewer/verifier worktree contains the candidate file when `review_mode` is
`full_tree`.

- [ ] **Step 7: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_reviewer_lifecycle.py evals/test_runner_production_e2e.py::test_reviewer_and_verifier_worktrees_include_candidate_files -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: reviewer lifecycle tests pass. Full eval suite remains green.

- [ ] **Step 8: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/supervisor.py skills/agent-runway/scripts/agentrunway/packetizer.py skills/agent-runway/scripts/agentrunway/result_validation.py skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py skills/agent-runway/evals/test_reviewer_lifecycle.py skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: add hybrid reviewer lifecycle"
```

---

## Task 7: Archive Non-Selected Candidate Evidence Before Cleanup

```yaml agentrunway-task
task_id: task_007
title: Archive Non-Selected Candidate Evidence Before Cleanup
risk: medium
phase: implementation
dependencies: [task_005, task_006]
spec_refs: [S1.6.2, S1.6.5, S1.14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py, mode: shared_append}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v
  - cd skills/agent-runway && ./evals/run.sh
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add evidence archive helper**

Modify `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`:

```python
from pathlib import Path
from typing import Any


def archive_candidate_evidence(*, run_dir: Path, candidate: dict[str, Any], worker: dict[str, Any]) -> Path:
    archive_dir = run_dir / "artifacts" / str(candidate["task_id"]) / str(candidate["worker_id"]) / "candidate_evidence"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "commits.json").write_text(
        json.dumps(candidate.get("commits", []), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (archive_dir / "changed_files.json").write_text(
        json.dumps(candidate.get("changed_files", []), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (archive_dir / "worker.json").write_text(
        json.dumps(worker, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return archive_dir
```

Add `import json` at the top of the file.

- [ ] **Step 2: Archive non-selected candidates during ranking**

Modify `skills/agent-runway/scripts/agentrunway/runner.py` in the ranking loop:

```python
                        from .worktree_lifecycle import WorktreeLifecycle, archive_candidate_evidence

                        worker = db.get_worker(str(candidate["worker_id"]))
                        archive_candidate_evidence(run_dir=run_dir, candidate=candidate, worker=worker)
                        if worker.get("worktree_path"):
                            db.set_worktree_lifecycle(str(worker["worktree_path"]), WorktreeLifecycle.EVIDENCE_ARCHIVED.value)
```

Place this before or immediately after:

```python
                        db.set_worker_state(str(candidate["worker_id"]), "not_selected")
```

- [ ] **Step 3: Extend high-risk candidate test**

Modify `skills/agent-runway/evals/test_runner_production_e2e.py` in
`test_high_risk_task_ranks_two_candidates`:

```python
    not_selected = [
        row for row in conn.execute("SELECT * FROM merge_queue ORDER BY id").fetchall()
        if row["status"] == "not_selected"
    ]
    assert not_selected
    evidence_dir = Path(payload["run_dir"]) / "artifacts" / not_selected[0]["task_id"] / not_selected[0]["worker_id"] / "candidate_evidence"
    assert (evidence_dir / "commits.json").exists()
    assert (evidence_dir / "changed_files.json").exists()
```

- [ ] **Step 4: Verify tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v
cd skills/agent-runway && ./evals/run.sh
```

Expected: the high-risk candidate test passes and full eval suite remains green.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: archive non-selected AgentRunway candidates"
```

---

## Task 8: Update Documentation and Final Verification

```yaml agentrunway-task
task_id: task_008
title: Update Documentation and Final Verification
risk: low
phase: documentation
dependencies: [task_001, task_002, task_003, task_004, task_005, task_006, task_007]
spec_refs: [S1.16]
file_claims:
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/context-policy.md, mode: owned}
  - {path: skills/agent-runway/references/worktree-policy.md, mode: owned}
  - {path: skills/agent-runway/references/watchdog.md, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && ./evals/run.sh
  - cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
  - graphify update .
required_skills: [using-superpowers, verification-before-completion]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/context-policy.md`
- Modify: `skills/agent-runway/references/worktree-policy.md`
- Modify: `skills/agent-runway/references/watchdog.md`

- [ ] **Step 1: Update README operations section**

Add this section to `skills/agent-runway/README.md`:

```markdown
## Quality-First Hybrid Worktrees

AgentRunway keeps implementer candidates isolated in their own worktrees because
candidate commits are the merge unit. Reviewers default to bounded diff and
evidence review, and escalate to full-tree worktrees for high-risk tasks, large
diffs, schema or migration changes, broad claims, or explicit `needs_context`
results. Verifiers run against candidate-head worktrees and persist command
evidence before cleanup.

The host session should use `agentrunway summarize --run <run_id>` for normal
follow-up. Raw events, stdout, stderr, and large diffs are deep-inspection
evidence, not normal host context.
```

- [ ] **Step 2: Update context policy**

Replace `skills/agent-runway/references/context-policy.md` with:

```markdown
Source-of-truth: the design document wins when this reference and code disagree.

# Context Policy

The runner stores state, packet hashes, event evidence, worker timing, and
summary artifacts outside conversation context.

Host compaction and rotation are safe because replay state lives in SQLite and
artifacts, not hidden chat state.

Normal host follow-up uses `agentrunway summarize --run <run_id>`. The host does
not read raw stdout, stderr, full event streams, or full worker prompts unless
the operator explicitly asks for deep inspection.

Deep inspection is scoped to a run, task, or worker. It must return evidence
references and bounded excerpts before opening large raw artifacts.
```

- [ ] **Step 3: Update worktree policy**

Replace `skills/agent-runway/references/worktree-policy.md` with:

```markdown
Source-of-truth: the design document wins when this reference and code disagree.

# Worktree Policy

`workspace_id` is derived from the shared git common dir, remote URL, and primary
branch ref.

The dirty source check refuses uncommitted work unless explicitly allowed.
Cross-workspace identity belongs in `registry.sqlite` for production hardening.

AgentRunway uses quality-first hybrid worktrees:

- one persistent run main worktree per run;
- one persistent implementer worktree per code-producing candidate;
- reviewer diff mode by default, with full-tree worktree escalation for risky or
  context-sensitive reviews;
- verifier candidate-head worktrees for real command execution, with evidence
  archived before cleanup;
- selected implementer worktrees retained until apply or explicit cleanup;
- non-selected candidates archived before becoming cleanup eligible.

Worker worktrees never merge into each other. The runner cherry-picks validated
and selected candidates into run main.
```

- [ ] **Step 4: Update watchdog policy**

Append this section to `skills/agent-runway/references/watchdog.md`:

```markdown
## Worker Timing

Every worker attempt records `started_at` when the process is launched and
`ended_at` when result collection reaches a terminal state. Watchdog diagnosis
uses these fields together with process liveness, result artifacts, stdout/stderr
mtime, and merge queue state.

Missing `ended_at` on a dead process is a stale lease signal. Resume must
classify the lease before redispatch and must not duplicate terminal workers.
```

- [ ] **Step 5: Run final verification**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
git diff --check
graphify update .
git status --short
```

Expected:

- eval suite passes;
- py_compile exits `0`;
- `git diff --check` prints no errors;
- `graphify update .` completes;
- `git status --short` shows only intentional files before commit.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/README.md skills/agent-runway/references/context-policy.md skills/agent-runway/references/worktree-policy.md skills/agent-runway/references/watchdog.md
git commit -m "docs: document AgentRunway hybrid worktrees"
```

---

## Audit Notes (2026-05-20)

A code audit of `skills/agent-runway/scripts/agentrunway/` against this plan
surfaced the items below. Tasks above already absorb the high-signal items
(registry wiring in Task 5, `needs_context` escalation in Task 6, summary
short-circuit and ranked-event-based `selected_candidates` in Task 3). The
remaining items are pre-existing defects that should not be quietly absorbed
into this slice's PR. Track them separately:

- `runner.cancel()` rewrites `run.json` with `status="cancelled"` but never
  calls `db.set_run_status(run_id, "cancelled")`. DB drifts from disk.
- The `status` payload exposes the AgentLens disabled notice only inside the
  human-readable string from `format_run_status`. JSON consumers cannot
  detect "AgentLens disabled" without substring matching. Add a structured
  `agentlens_notice` field at the status payload level.
- `worktree_registry` schema is in `db.py` but no production code populates
  it. Without the Task 5 wiring step, lifecycle setters and the
  lifecycle-aware retention branch are dead code.
- Preflight v1 covers adapter-binary presence, git identity, git common-dir
  access, and write probes for run_dir and worktree_parent. The design's
  full bullet list (sandbox write to `.git/worktrees`, actual trial commit
  inside a scratch worktree, adapter-specific env var presence) is post-v1.
  Make `PreflightResult` declare the surface it actually checked so summary
  output can warn when preflight is partial.
- This slice does not actually skip reviewer worktree creation in diff mode;
  it routes through `run_worker_attempt` unchanged. The disk/process savings
  for reviewers land in a follow-up no-worktree adapter slice.

## Final Completion Checklist

Run these commands after all tasks have landed:

```bash
cd /Users/kws/source/private/Archive
cd skills/agent-runway && ./evals/run.sh
cd /Users/kws/source/private/Archive/skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd /Users/kws/source/private/Archive && git diff --check
cd /Users/kws/source/private/Archive && graphify update .
cd /Users/kws/source/private/Archive && git status --short
```

Expected final state:

- all AgentRunway evals pass;
- Python files compile;
- graphify is updated after code changes;
- worktree is clean after the final commit;
- `agentrunway summarize --run <run_id>` is available for host-context-light follow-up;
- reviewer/verifier quality invariants remain covered by tests.
