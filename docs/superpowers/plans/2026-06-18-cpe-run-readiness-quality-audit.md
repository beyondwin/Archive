# CPE Run Readiness and Quality Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pre-dispatch run readiness auditing and stricter run-quality consistency checks for `kws-codex-plan-executor`.

**Architecture:** Keep the existing task packet and adaptive dispatch flow intact. Add one read-only readiness script that inspects task packets before edits, extend parser metadata so packets carry better acceptance evidence, then tighten state validation so final strategy evidence cannot drift away from dispatch decisions.

**Tech Stack:** Python 3 standard library scripts, Markdown docs, existing `skills/kws-codex-plan-executor/evals/run.sh` harness, existing state JSON schema.

## Global Constraints

- Do not weaken adaptive dispatch safety gates.
- Do not auto-expand allowed write scope from readiness output.
- Preserve compatibility for older state files that do not have `run_quality`.
- Prompt and handoff modes must not create readiness artifacts.
- Existing user changes in `skills/kws-codex-plan-executor/SKILL.md`, `skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json`, and `skills/kws-codex-plan-executor/references/subagent-run-store.md` must be read before editing and must not be reverted.
- After meaningful code or documentation structure changes, run `graphify update .` and record ignored-output behavior if `graphify-out/` is ignored.

---

## File Structure

- `skills/kws-codex-plan-executor/scripts/parse_plan.py`
  - Owns extraction of task files, dependencies, spec refs, and acceptance commands from implementation plans.
  - Add `acceptance_source` beside `acceptance_command`.
- `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
  - Owns per-task packet shape.
  - Preserve parser-provided `acceptance_source` in `packet["acceptance"]["source"]`.
- `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  - Owns per-task dispatch decision.
  - Split malformed write scope from ordinary `write_scope_outside_allowed`.
- `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
  - New read-only aggregate readiness audit over a task packet directory.
  - Produces deterministic JSON for `run_readiness` and future `run_quality`.
- `skills/kws-codex-plan-executor/scripts/validate_state.py`
  - Owns finished-state validation.
  - Add dispatch/strategy consistency and richer `run_quality` shape checks.
- `skills/kws-codex-plan-executor/evals/check_parse_plan.py`
  - Existing parser fixture runner.
  - Add assertions for `acceptance_source`.
- `skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml`
  - New fixture for acceptance extraction priority.
- `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
  - Add write scope format coverage.
- `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
  - New focused eval for aggregate readiness report.
- `skills/kws-codex-plan-executor/evals/check_state_schema.py`
  - Add dispatch/strategy mismatch, override, and `run_quality` schema cases.
- `skills/kws-codex-plan-executor/evals/run.sh`
  - Add `check_run_readiness.py` to the focused checks.
- `skills/kws-codex-plan-executor/SKILL.md`
  - Document readiness audit, consistency validation, and `run_quality`.
- `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
  - Document readiness audit before per-task dispatch.
- `skills/kws-codex-plan-executor/references/execution-cycle.md`
  - Add readiness audit after task packet creation and before task contracts.
- `skills/kws-codex-plan-executor/references/state-schema.md`
  - Document `run_readiness`, `subagent_strategy_override`, and enriched `run_quality`.
- `skills/kws-codex-plan-executor/HISTORY.md`
  - Record the behavior change if this file exists in the current worktree.

## Task 1: Acceptance Extraction and Packet Source Metadata

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_parse_plan.py`
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml`

**Interfaces:**
- Consumes: Markdown task bodies parsed by `parse_plan.parse_plan(plan_path: Path, repo_root: Path, mode: str) -> dict`.
- Produces:
  - `task["acceptance_command"]: str | None`
  - `task["acceptance_source"]: "plan.yaml.verify" | "plan.acceptance_section" | "plan.last_run_block" | "plan.command_fence_fallback" | "missing"`
  - `packet["acceptance"]["source"]` copied from `task["acceptance_source"]`.

- [ ] **Step 1: Write the failing parser fixture**

Create `skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml`:

```yaml
name: acceptance source priority
mode: interactive
plan: |
  ### Task 1: Section Acceptance

  **Files:**
  - Modify: `src/section.py`

  - [ ] Step 1: Run a local probe

  Run:

  ```bash
  python3 scripts/local_probe.py
  ```

  ## Verification

  ```bash
  python3 evals/check_section.py
  ```

  ### Task 2: Last Run Acceptance

  **Files:**
  - Modify: `src/last_run.py`

  - [ ] Step 1: Run focused check

  Run:

  ```bash
  python3 evals/check_first.py
  ```

  - [ ] Step 2: Run final focused check

  실행:

  ```bash
  python3 evals/check_last.py
  ```

  ### Task 3: Fallback Fence Acceptance

  **Files:**
  - Modify: `src/fallback.py`

  ```bash
  python3 evals/check_fallback.py
  ```

  ### Task 4: Missing Acceptance

  **Files:**
  - Modify: `src/missing.py`
expected:
  acceptance_commands:
    task_1: "python3 evals/check_section.py"
    task_2: "python3 evals/check_last.py"
    task_3: "python3 evals/check_fallback.py"
  tasks:
    - id: task_1
      acceptance_source: plan.acceptance_section
    - id: task_2
      acceptance_source: plan.last_run_block
    - id: task_3
      acceptance_source: plan.command_fence_fallback
    - id: task_4
      acceptance_command:
      acceptance_source: missing
```

- [ ] **Step 2: Extend the parser eval to assert `acceptance_source`**

Modify `skills/kws-codex-plan-executor/evals/check_parse_plan.py` in the `expected_tasks` loop so it can compare keys whose expected value is `None`:

```python
    expected_tasks = expected.get("tasks") or []
    if expected_tasks:
        actual_tasks = {task.get("id"): task for task in parsed.get("tasks", [])}
        task_failures = []
        for expected_task in expected_tasks:
            task_id = expected_task.get("id")
            actual_task = actual_tasks.get(task_id)
            if not actual_task:
                task_failures.append(f"missing task {task_id}")
                continue
            for key, expected_value in expected_task.items():
                if key == "id":
                    continue
                if actual_task.get(key) != expected_value:
                    task_failures.append(f"{task_id}.{key}: expected {expected_value!r}, got {actual_task.get(key)!r}")
        checks["tasks_match"] = not task_failures
        failures.extend(task_failures)
```

The current loop already has this shape; keep it if it is unchanged. The fixture in Step 1 is the failing test.

- [ ] **Step 3: Run the parser fixture and verify it fails**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  --fixture skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml
```

Expected: FAIL because `acceptance_source` is missing and the parser does not yet select the last `Run:` block.

- [ ] **Step 4: Add acceptance extraction helpers**

Modify `skills/kws-codex-plan-executor/scripts/parse_plan.py`. Replace the existing `_extract_acceptance_command` function with these helpers:

```python
ACCEPTANCE_SECTION_FENCE_RE = re.compile(
    r"(?mis)^\s*(?:#{2,5}\s*)?"
    r"(?:Acceptance Criteria|Acceptance|Verification|Done when|검증|완료 기준|Eval)"
    r"(?:\b|[ \t]*:).*?"
    r"```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```"
)
ANY_COMMAND_FENCE_RE = re.compile(r"(?ms)```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```")
RUN_BLOCK_COMMAND_RE = re.compile(
    r"(?mis)^\s*(?:Run|실행)\s*:\s*\n\s*```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```"
)


def _commands_from_fence_body(body: str) -> str | None:
    commands: list[str] = []
    for line in body.splitlines():
        command = line.strip()
        if command and not command.startswith("#"):
            commands.append(command)
    return "\n".join(commands) if commands else None


def _extract_acceptance_command_with_source(body: str) -> tuple[str | None, str]:
    section_match = ACCEPTANCE_SECTION_FENCE_RE.search(body)
    if section_match:
        command = _commands_from_fence_body(section_match.group("body"))
        if command:
            return command, "plan.acceptance_section"

    run_matches = list(RUN_BLOCK_COMMAND_RE.finditer(body))
    for match in reversed(run_matches):
        command = _commands_from_fence_body(match.group("body"))
        if command:
            return command, "plan.last_run_block"

    fallback_match = ANY_COMMAND_FENCE_RE.search(body)
    if fallback_match:
        command = _commands_from_fence_body(fallback_match.group("body"))
        if command:
            return command, "plan.command_fence_fallback"

    return None, "missing"


def _extract_acceptance_command(body: str) -> str | None:
    command, _source = _extract_acceptance_command_with_source(body)
    return command
```

- [ ] **Step 5: Preserve source across Markdown and YAML task parsing**

In `parse_plan.py`, add:

```python
def _extract_acceptance_after_line_with_source(raw_markdown: str, start_line: int, end_line: int) -> tuple[str | None, str]:
    raw_section = _slice_lines(raw_markdown, start_line, end_line)
    return _extract_acceptance_command_with_source(raw_section)
```

For YAML task blocks, compute:

```python
                "acceptance_command": _extract_acceptance_command(yaml_body),
                "acceptance_source": "plan.yaml.verify" if _extract_acceptance_command(yaml_body) else "missing",
```

For Markdown task blocks, compute before appending:

```python
        acceptance_command, acceptance_source = _extract_acceptance_after_line_with_source(
            raw_markdown,
            raw_body_start_line,
            raw_body_end_line,
        )
```

Then set:

```python
                "acceptance_command": acceptance_command,
                "acceptance_source": acceptance_source,
```

- [ ] **Step 6: Preserve acceptance source in task packets**

Modify `skills/kws-codex-plan-executor/scripts/build_task_packet.py`:

```python
    acceptance_command = task.get("acceptance_command")
    acceptance_source = task.get("acceptance_source") or ("plan.acceptance" if acceptance_command else "missing")
```

Then replace the packet acceptance object with:

```python
        "acceptance": {
            "has_acceptance_criteria": bool(task.get("has_acceptance_criteria")),
            "command": acceptance_command,
            "source": acceptance_source,
            "honest_substitute_allowed": acceptance_command is None,
        },
```

- [ ] **Step 7: Run the parser fixture and full parser fixture loop**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  --fixture skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml
while IFS= read -r fixture; do
  python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py --fixture "$fixture" >/dev/null
done < <(find skills/kws-codex-plan-executor/evals/parser-fixtures -name '*.yaml' -type f | sort)
```

Expected: PASS. The first command prints JSON with `"passed": true`; the loop exits 0.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/parse_plan.py \
  skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml
git commit -m "feat(cpe): preserve acceptance source in task packets"
```

## Task 2: Readiness Audit Script

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
- Create: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: `state.json`, `task_packets/*.json`, repository root, dispatch policy flags.
- Produces: readiness JSON with `schema_version`, `passed`, `summary`, and `issues`.

- [ ] **Step 1: Write the failing readiness eval**

Create `skills/kws-codex-plan-executor/evals/check_run_readiness.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_run_readiness.py"


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "docs").mkdir()
    (repo / "docs/example.md").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("print('base')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def write_packet(path: Path, task_id: str, files: list[str], *, command: str | None, fallback_used: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task_id,
        "files": files,
        "depends_on": [],
        "acceptance": {
            "has_acceptance_criteria": command is not None,
            "command": command,
            "source": "plan.acceptance_section" if command else "missing",
            "honest_substitute_allowed": command is None,
        },
        "spec": {"fallback_used": fallback_used},
        "context_budget": {"status": "green", "estimated_chars": 1000, "max_chars": 60000},
        "write_policy": {
            "allowed_write_globs": files,
            "forbidden_write_globs": [".git/**", "graphify-out/**"],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_audit(repo: Path, state_path: Path, packet_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "run_readiness.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--task-packet-dir",
            str(packet_dir),
            "--repo-root",
            str(repo),
            "--output",
            str(output),
            "--requested-subagents",
            "on",
            "--requested-source",
            "explicit",
            "--spawn-policy",
            "available",
            "--explicit-delegation-requested",
            "true",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(packet_dir / "task_1.json", "task_1", ["docs/example.md"], command=None, fallback_used=True)
        write_packet(packet_dir / "task_2.json", "task_2", ["src/app.py"], command="python3 -m pytest", fallback_used=False)
        result, data = run_audit(repo, state_path, packet_dir)
        issue_kinds = {issue.get("kind") for issue in data.get("issues", [])}
        checks["missing_acceptance_is_fixable"] = (
            result.returncode == 1
            and data.get("passed") is False
            and "acceptance_command_missing" in issue_kinds
            and data.get("summary", {}).get("fixable_issue_count", 0) >= 1
        )
        if not checks["missing_acceptance_is_fixable"]:
            failures.append("readiness audit should report missing acceptance as fixable")
        checks["full_spec_fallback_is_reported"] = "full_spec_fallback" in issue_kinds
        if not checks["full_spec_fallback_is_reported"]:
            failures.append("readiness audit should report full spec fallback")

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-clean-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(packet_dir / "task_1.json", "task_1", ["docs/example.md"], command="python3 evals/check_docs.py")
        result, data = run_audit(repo, state_path, packet_dir)
        checks["clean_packet_passes"] = (
            result.returncode == 0
            and data.get("passed") is True
            and data.get("summary", {}).get("task_count") == 1
        )
        if not checks["clean_packet_passes"]:
            failures.append("clean readiness audit should pass")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the readiness eval and verify it fails**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_run_readiness.py
```

Expected: FAIL because `scripts/audit_run_readiness.py` does not exist.

- [ ] **Step 3: Implement `audit_run_readiness.py`**

Create `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def issue(task_id: str, severity: str, kind: str, message: str) -> dict:
    return {
        "task_id": task_id,
        "severity": severity,
        "kind": kind,
        "message": message,
    }


def packet_task_id(packet: dict, fallback: str) -> str:
    value = packet.get("task_id")
    return value if isinstance(value, str) and value.strip() else fallback


def list_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def malformed_scope(pattern: str) -> bool:
    return "," in pattern and not any(ch in pattern for ch in "[]{}")


def audit_packet(packet_path: Path) -> tuple[dict, list[dict]]:
    packet = load_json(packet_path)
    if not isinstance(packet, dict):
        return {"task_id": packet_path.stem}, [issue(packet_path.stem, "blocking", "packet_not_object", "Task packet must be a JSON object.")]

    task_id = packet_task_id(packet, packet_path.stem)
    issues: list[dict] = []
    files = list_strings(packet.get("files"))
    acceptance = packet.get("acceptance") if isinstance(packet.get("acceptance"), dict) else {}
    if not acceptance.get("command"):
        issues.append(issue(task_id, "fixable", "acceptance_command_missing", "Task packet has no acceptance command before dispatch."))

    spec = packet.get("spec") if isinstance(packet.get("spec"), dict) else {}
    if spec.get("fallback_used") is True:
        issues.append(issue(task_id, "fixable", "full_spec_fallback", "Task packet uses full spec fallback instead of task-specific spec sections."))

    policy = packet.get("write_policy") if isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(policy.get("allowed_write_globs"))
    if not allowed:
        issues.append(issue(task_id, "blocking", "allowed_write_globs_empty", "Task packet has no allowed write globs."))
    for pattern in allowed + files:
        if malformed_scope(pattern):
            issues.append(issue(task_id, "fixable", "write_scope_format_invalid", "Write scope appears to contain multiple comma-joined paths."))
            break

    budget = packet.get("context_budget") if isinstance(packet.get("context_budget"), dict) else {}
    if budget.get("status") == "red":
        issues.append(issue(task_id, "fixable", "packet_context_budget_red", "Task packet context budget is red before execution."))

    delegate_ready = not any(item["severity"] == "blocking" for item in issues) and not issues
    local_fast_path = len(files) <= 3 and not any(item["severity"] == "blocking" for item in issues)
    summary = {
        "task_id": task_id,
        "delegate_ready": delegate_ready,
        "local_fast_path_candidate": local_fast_path,
        "issue_count": len(issues),
    }
    return summary, issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CPE task packet readiness before execution edits.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-packet-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--requested-subagents", choices=["on", "auto", "off"], default="on")
    parser.add_argument("--requested-source", choices=["default", "explicit", "natural_language", "resume_state"], default="default")
    parser.add_argument("--spawn-policy", choices=["available", "unavailable", "explicit-request-required", "unknown"], default="unknown")
    parser.add_argument("--explicit-delegation-requested", choices=["true", "false"], default="false")
    args = parser.parse_args()

    state_path = Path(args.state)
    packet_dir = Path(args.task_packet_dir)
    repo_root = Path(args.repo_root)
    all_issues: list[dict] = []
    task_summaries: list[dict] = []
    blocking = 0
    fixable = 0

    if not state_path.is_file():
        all_issues.append(issue("__run__", "blocking", "state_missing", "State file is not readable."))
    if not packet_dir.is_dir():
        all_issues.append(issue("__run__", "blocking", "task_packet_dir_missing", "Task packet directory is not readable."))
    if not repo_root.is_dir():
        all_issues.append(issue("__run__", "blocking", "repo_root_missing", "Repository root is not readable."))

    if not all_issues:
        for packet_path in sorted(packet_dir.glob("*.json")):
            summary, issues = audit_packet(packet_path)
            task_summaries.append(summary)
            all_issues.extend(issues)

    for item in all_issues:
        if item.get("severity") == "blocking":
            blocking += 1
        elif item.get("severity") == "fixable":
            fixable += 1

    payload = {
        "schema_version": "1",
        "passed": blocking == 0 and fixable == 0,
        "requested": {
            "subagents": args.requested_subagents,
            "source": args.requested_source,
            "spawn_policy": args.spawn_policy,
            "explicit_delegation_requested": args.explicit_delegation_requested == "true",
        },
        "summary": {
            "task_count": len(task_summaries),
            "delegate_ready_count": sum(1 for item in task_summaries if item.get("delegate_ready") is True),
            "local_fast_path_count": sum(1 for item in task_summaries if item.get("local_fast_path_candidate") is True),
            "fixable_issue_count": fixable,
            "blocking_issue_count": blocking,
        },
        "tasks": task_summaries,
        "issues": all_issues,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the readiness eval to the full eval runner**

Modify `skills/kws-codex-plan-executor/evals/run.sh` after `check_preflight_dispatch.py`:

```bash
python3 "$EVAL_DIR/check_preflight_dispatch.py" >/dev/null
python3 "$EVAL_DIR/check_run_readiness.py" >/dev/null
python3 "$EVAL_DIR/check_recovery_policy.py" >/dev/null
```

- [ ] **Step 5: Run focused readiness checks**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_run_readiness.py
```

Expected: PASS with `"passed": true`.

- [ ] **Step 6: Commit Task 2**

```bash
chmod +x skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py
git add \
  skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat(cpe): audit run readiness before execution"
```

## Task 3: Preflight Write Scope Diagnostics

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

**Interfaces:**
- Consumes: `--write-scope` values and packet `write_policy.allowed_write_globs`.
- Produces:
  - `write_scope_format_invalid` for comma-joined scope strings.
  - Existing `write_scope_outside_allowed` for valid but disallowed scope values.

- [ ] **Step 1: Add a failing eval case**

Append this case before the broad-scope case in `check_preflight_dispatch.py`:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["docs/example.md"],
            allowed_write_globs=["docs/example.md", "docs/other.md"],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            write_scope=["docs/example.md,docs/other.md"],
        )
        checks["comma_joined_write_scope_is_format_invalid"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "write_scope_format_invalid" in data.get("failed_prerequisites", [])
        )
        if not checks["comma_joined_write_scope_is_format_invalid"]:
            failures.append("comma-joined write scope should be reported as a format issue")
```

- [ ] **Step 2: Run the preflight eval and verify it fails**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
```

Expected: FAIL because comma-joined write scope is currently classified as `write_scope_outside_allowed`.

- [ ] **Step 3: Add scope format detection**

Modify `preflight_dispatch.py` after `write_scope_too_broad`:

```python
def write_scope_format_invalid(pattern: str) -> bool:
    stripped = pattern.strip()
    return "," in stripped and not any(char in stripped for char in "[]{}")
```

Modify the write-scope loop:

```python
    for scope in write_scope:
        if write_scope_format_invalid(scope):
            failed.append("write_scope_format_invalid")
            continue
        if allowed and not matches_any(scope, allowed):
            failed.append("write_scope_outside_allowed")
        if forbidden and matches_any(scope, forbidden):
            failed.append("write_scope_matches_forbidden")
```

- [ ] **Step 4: Run focused dispatch checks**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
```

Expected: PASS with `"passed": true`.

- [ ] **Step 5: Commit Task 3**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "fix(cpe): separate malformed write scope diagnostics"
```

## Task 4: State Consistency and Run Quality Validation

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes: `dispatch_decisions`, completed task `subagent_strategy`, optional `subagent_strategy_override`, and optional `run_quality`.
- Produces validation errors when finished state carries unapproved dispatch/strategy drift.

- [ ] **Step 1: Add failing schema eval cases**

Append these cases after `finished_adaptive_local_fast_path_passes` in `check_state_schema.py`:

```python
    mismatch = v220_state()
    mismatch["subagent_runs"] = []
    mismatch["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "acceptance_command_missing",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": ["acceptance_command_missing"],
        }
    ]
    mismatch["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "run_ids": [],
    }
    result = run_validator(script, mismatch)
    checks["dispatch_strategy_mismatch_without_override_fails"] = (
        result.returncode != 0 and "subagent_strategy_override" in (result.stderr + result.stdout)
    )
    if not checks["dispatch_strategy_mismatch_without_override_fails"]:
        failures.append("dispatch/strategy mismatch should require override evidence")

    override = mismatch
    override["tasks"]["task_0"]["subagent_strategy_override"] = {
        "from_reason": "acceptance_command_missing",
        "to_reason": "adaptive_policy_local_fast_path_docs_only",
        "changed_at": "2026-05-19T14:34:30Z",
        "evidence": "Operator replaced a stale dry-run dispatch reason after acceptance was added before execution.",
        "operator_decision": "accept override",
    }
    result = run_validator(script, override)
    checks["dispatch_strategy_mismatch_with_override_passes"] = result.returncode == 0
    if not checks["dispatch_strategy_mismatch_with_override_passes"]:
        failures.append("dispatch/strategy override evidence should pass: " + (result.stderr or result.stdout))
```

- [ ] **Step 2: Add richer run quality eval cases**

In `check_operational_run_quality.py`, extend `v222_state()["run_quality"]` to:

```python
    state["run_quality"] = {
        "schema_version": "1",
        "validation_status": "passed",
        "terminal_state": "finished",
        "stale": False,
        "workspace_matches_execution_worktree": True,
        "score": 92,
        "grade": "green",
        "schema_drift": [],
        "open_followups": [],
        "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
        "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
        "context_quality": {"full_spec_fallback_count": 0},
        "verification_quality": {"completion_audit_passed": True},
        "recommendations": [],
        "summary": "Run finished with validated state.",
    }
```

Add an invalid case:

```python
    bad_quality = v222_state()
    bad_quality["run_quality"]["score"] = 120
    invalid_quality = run_validator(bad_quality)
    checks["invalid_run_quality_score_fails"] = (
        invalid_quality.returncode != 0 and "run_quality.score" in invalid_quality.stderr
    )
    if not checks["invalid_run_quality_score_fails"]:
        failures.append("run_quality.score outside 0..100 should fail")
```

- [ ] **Step 3: Run schema evals and verify they fail**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: FAIL because validator does not yet check dispatch/strategy mismatch or `run_quality.score`.

- [ ] **Step 4: Implement dispatch/strategy consistency validation**

Add helpers to `validate_state.py` near `_reviewed_completed_subagent_run_ids`:

```python
def _latest_dispatch_by_task(data: dict) -> dict[str, dict]:
    decisions = data.get("dispatch_decisions", [])
    latest: dict[str, dict] = {}
    if not isinstance(decisions, list):
        return latest
    for item in decisions:
        if isinstance(item, dict) and isinstance(item.get("task_id"), str):
            latest[item["task_id"]] = item
    return latest


def _expected_strategy_from_dispatch(decision: dict) -> tuple[str | None, str | None]:
    raw_decision = decision.get("decision")
    if raw_decision == "delegate":
        return "delegated", decision.get("reason")
    if raw_decision == "local_fallback":
        return "local_fallback", decision.get("reason")
    return None, None


def _validate_strategy_override(task_id: str, task: dict, errors: list[str]) -> bool:
    override = task.get("subagent_strategy_override")
    if not isinstance(override, dict):
        errors.append(f"{task_id}: subagent_strategy_override required when dispatch decision and final strategy differ")
        return False
    for key in ("from_reason", "to_reason", "changed_at", "evidence", "operator_decision"):
        if not _has_substantive_value(override.get(key)):
            errors.append(f"{task_id}: subagent_strategy_override.{key} must be non-empty")
    if _parse_ts(override.get("changed_at")) is None:
        errors.append(f"{task_id}: subagent_strategy_override.changed_at must be an ISO timestamp")
    return True
```

At the end of `_validate_subagent_strategy`, add:

```python
    latest_dispatch = _latest_dispatch_by_task(data).get(task_id)
    if isinstance(latest_dispatch, dict) and latest_dispatch.get("decision") != "block":
        expected_mode, expected_reason = _expected_strategy_from_dispatch(latest_dispatch)
        if expected_mode and (mode != expected_mode or reason != expected_reason):
            _validate_strategy_override(task_id, task, errors)
```

- [ ] **Step 5: Validate enriched `run_quality` shape**

In `_validate_operational_run_quality`, extend the `quality` block:

```python
            score = quality.get("score")
            if score is not None and (not isinstance(score, int) or score < 0 or score > 100):
                errors.append("run_quality.score must be an integer from 0 to 100")
            grade = quality.get("grade")
            if grade is not None and grade not in {"green", "yellow", "red"}:
                errors.append("run_quality.grade must be green, yellow, or red")
            for key in ("readiness", "dispatch_consistency", "context_quality", "verification_quality"):
                if key in quality and not isinstance(quality[key], dict):
                    errors.append(f"run_quality.{key} must be an object")
            if "recommendations" in quality and not isinstance(quality["recommendations"], list):
                errors.append("run_quality.recommendations must be a list")
```

- [ ] **Step 6: Run focused state quality checks**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: PASS with `"passed": true` from both scripts.

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat(cpe): validate dispatch strategy consistency"
```

## Task 5: Contract Docs, Skill Metadata, and Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md` if present
- May update: `skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json`
- May update ignored output: `graphify-out/`

**Interfaces:**
- Consumes: implemented behavior from Tasks 1 through 4.
- Produces: documented executor contract and full verification evidence.

- [ ] **Step 1: Read current dirty files before editing**

Run:

```bash
git diff -- \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json \
  skills/kws-codex-plan-executor/references/subagent-run-store.md
```

Expected: inspect and preserve existing user changes. Do not revert unrelated hunks.

- [ ] **Step 2: Update `SKILL.md` contract**

Add these bullets under Core Invariants near the dispatch and run quality bullets:

```markdown
- Execution runs produce a read-only run readiness audit after task packet
  creation and before task contracts or edits. Readiness issues classify
  missing acceptance commands, full-spec fallback, packet context budget, and
  write-scope formatting before per-task dispatch.
- Finished runs with both `dispatch_decisions` and completed write-capable
  tasks must keep final `subagent_strategy` aligned with the latest dispatch
  decision for that task. If the operator intentionally overrides a stale or
  superseded dispatch reason, the task records `subagent_strategy_override`
  with `from_reason`, `to_reason`, `changed_at`, `evidence`, and
  `operator_decision`.
- `run_quality` may report yellow operational quality even when
  `completion_audit.passed=true`; this marks executor efficiency or evidence
  quality follow-up, not product verification failure.
```

- [ ] **Step 3: Update pre-dispatch pipeline docs**

Add this paragraph after the opening paragraph in `references/pre-dispatch-pipeline.md`:

```markdown
Before task contracts and edits, run the aggregate readiness audit over the
generated task packets. The audit is read-only and reports fixable metadata
issues such as missing acceptance commands, full-spec fallback, context budget
pressure, and malformed write scopes. It does not expand allowed write globs or
weaken safety gates.
```

- [ ] **Step 4: Update execution cycle docs**

In `references/execution-cycle.md`, insert a new step after task packet/context creation:

```markdown
Before task execution, run `scripts/audit_run_readiness.py` against
`$RUN_DIR/task_packets`. Save the JSON as `$RUN_DIR/run_readiness.json` and
copy its summary into `run_quality.readiness` when finalizing. If it reports
blocking issues, stop before edits; if it reports fixable issues, record the
operator decision before continuing.
```

- [ ] **Step 5: Update state schema docs**

In `references/state-schema.md`, extend the v2.22 example `run_quality` object:

```json
  "run_quality": {
    "schema_version": "1",
    "validation_status": "passed",
    "terminal_state": "finished",
    "stale": false,
    "workspace_matches_execution_worktree": true,
    "score": 92,
    "grade": "green",
    "schema_drift": [],
    "open_followups": [],
    "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
    "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
    "context_quality": {"full_spec_fallback_count": 0},
    "verification_quality": {"completion_audit_passed": true},
    "recommendations": [],
    "summary": "Run finished with validated state."
  }
```

Add this paragraph near the dispatch decision rules:

```markdown
When a finished task's final `subagent_strategy` differs from the latest
non-block dispatch decision for that task, the task must include
`subagent_strategy_override` with `from_reason`, `to_reason`, `changed_at`,
`evidence`, and `operator_decision`. This is for stale or superseded dispatch
evidence only; it is not a way to bypass safety gates.
```

- [ ] **Step 6: Update HISTORY if present**

If `skills/kws-codex-plan-executor/HISTORY.md` exists, add:

```markdown
## Unreleased

- Added run readiness auditing before execution edits.
- Preserved acceptance source metadata in task packets.
- Tightened finished-state validation for dispatch and final subagent strategy consistency.
- Expanded run quality schema for readiness, context quality, dispatch consistency, and verification quality.
```

If the file already has an `Unreleased` section, add the bullets to that section.

- [ ] **Step 7: Run focused checks**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  --fixture skills/kws-codex-plan-executor/evals/parser-fixtures/16-acceptance-source-priority.yaml
python3 skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
python3 skills/kws-codex-plan-executor/evals/check_run_readiness.py
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: all commands exit 0 and print or imply `"passed": true`.

- [ ] **Step 8: Run full skill evals**

Run:

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh
```

Expected: exits 0. If `evals/baselines/v2.22.0.json` changes only by timestamp or run metadata, inspect it and revert that hunk unless the baseline behavior intentionally changed.

- [ ] **Step 9: Refresh Graphify**

Run from repo root:

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran --output /tmp/cpe-graphify-readiness-audit.json
```

Expected: freshness audit exits 0. If `graphify update .` requires `--force` because extracted nodes shrink, run:

```bash
graphify update . --force
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran --output /tmp/cpe-graphify-readiness-audit.json
```

- [ ] **Step 10: Run patch hygiene**

Run:

```bash
git diff --check
```

Expected: exits 0.

- [ ] **Step 11: Commit Task 5**

```bash
git add \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json
git commit -m "docs(cpe): document run readiness quality audit"
```

If `HISTORY.md` does not exist, omit it from `git add`. If the baseline file has only unintended run metadata churn, omit it from `git add`.

## Final Verification

After all task commits:

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh
cd /Users/kws/source/private/Archive && git diff --check
```

Expected:

- `./evals/run.sh` exits 0.
- `git diff --check` exits 0.
- `git status --short --branch --untracked-files=all` shows only intentional changes or a clean working tree.

## Self-Review

- Spec coverage: acceptance extraction is Task 1; readiness audit is Task 2; write scope diagnostics are Task 3; dispatch/strategy consistency and `run_quality` are Task 4; skill contract docs, full evals, and Graphify are Task 5.
- Placeholder scan: no unfinished marker or unspecified test step remains.
- Type consistency: `acceptance_source`, `run_readiness`, `subagent_strategy_override`, and `run_quality` field names match across tasks.
- Scope check: this is a single executor-quality implementation plan and does not modify ReadMates product code.
