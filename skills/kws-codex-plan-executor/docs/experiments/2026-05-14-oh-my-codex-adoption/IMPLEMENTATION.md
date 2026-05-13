# OMX-Inspired Executor Hardening Implementation Details

This document expands `PLAN.md` into concrete implementation guidance. It is
written for future execution against `kws-codex-plan-executor`; it does not
claim the changes are already applied.

## Implementation Order

1. Parser visible-Markdown hardening.
2. Context snapshot helper.
3. State schema extensions for context, lifecycle, and completion audit.
4. Runtime docs and prompt export alignment.
5. Optional execution DAG metadata.
6. High-risk verification matrix.
7. Package metadata and validation.

This order keeps deterministic parser/state checks green before prompt-level
behavior changes are advertised.

## Task 1: Visible Markdown Parsing

**Files:**
- Modify: `scripts/parse_plan.py`
- Modify: `evals/check_parse_plan.py`
- Create: `evals/parser-fixtures/03-hidden-task-in-fence.yaml`
- Create: `evals/parser-fixtures/04-hidden-files-in-comment.yaml`
- Create: `evals/parser-fixtures/05-visible-files-after-fence.yaml`

### Step 1.1: Add Hidden-Line Normalization

Insert these constants near the current regex definitions in `scripts/parse_plan.py`:

```python
FENCE_RE = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)$")
FENCE_CLOSE_SUFFIX_RE = re.compile(r"^[ \t]*$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
COMMENT_LINE_RE = re.compile(r"^(?: {0,3})<!--")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")
```

Add these helpers below `_die`:

```python
def _advance_comment_depth(depth: int, line: str) -> int:
    if depth == 0 and not COMMENT_LINE_RE.match(line):
        return 0

    index = 0
    active = depth
    while index < len(line):
        next_open = line.find(COMMENT_OPEN, index)
        next_close = line.find(COMMENT_CLOSE, index)
        if next_open == -1 and next_close == -1:
            break
        if next_open != -1 and (next_close == -1 or next_open < next_close):
            active += 1
            index = next_open + len(COMMENT_OPEN)
            continue
        if active > 0:
            active -= 1
        index = next_close + len(COMMENT_CLOSE)
    return active


def _read_fence_marker(line: str) -> tuple[str, int, str] | None:
    match = FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("suffix") or ""


def _visible_markdown(markdown: str) -> str:
    """Blank hidden Markdown regions while preserving line positions."""
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    comment_depth = 0

    for line in markdown.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""

        if fence is not None:
            marker = _read_fence_marker(body)
            if marker and marker[0] == fence[0] and marker[1] >= fence[1] and FENCE_CLOSE_SUFFIX_RE.match(marker[2]):
                fence = None
            visible.append(newline)
            continue

        if comment_depth > 0 or COMMENT_LINE_RE.match(body):
            comment_depth = _advance_comment_depth(comment_depth, body)
            visible.append(newline)
            continue

        if INDENTED_CODE_RE.match(body):
            visible.append(newline)
            continue

        marker = _read_fence_marker(body)
        if marker:
            fence = (marker[0], marker[1])
            visible.append(newline)
            continue

        visible.append(line)

    return "".join(visible)
```

Change `parse_plan` so it runs regexes against normalized visible Markdown:

```python
def parse_plan(plan_path: Path, repo_root: Path, mode: str) -> dict:
    raw_markdown = plan_path.read_text(encoding="utf-8")
    markdown = _visible_markdown(raw_markdown)
    matches = list(TASK_RE.finditer(markdown))
```

Keep the rest of `parse_plan` using `markdown` for task bodies. This means
fenced code no longer appears in task bodies, which is acceptable because the
parser only owns task/file/acceptance metadata, not full prompt reconstruction.

### Step 1.2: Add Parser Fixtures

Create `evals/parser-fixtures/03-hidden-task-in-fence.yaml`:

```yaml
name: hidden-task-in-fence
mode: interactive
plan: |
  ### Task 0: Real task

  Files:
  - Create: docs/real.md

  ```markdown
  ### Task 1: Hidden task

  Files:
  - Create: docs/hidden.md
  ```

  ## Verification
  Run `test -f docs/real.md`.
expected:
  files:
    - docs/real.md
```

Create `evals/parser-fixtures/04-hidden-files-in-comment.yaml`:

```yaml
name: hidden-files-in-comment
mode: interactive
plan: |
  ### Task 0: Real task

  <!--
  Files:
  - Create: docs/hidden.md
  -->

  Files:
  - Create: docs/real.md

  ## Verification
  Run `test -f docs/real.md`.
expected:
  files:
    - docs/real.md
```

Create `evals/parser-fixtures/05-visible-files-after-fence.yaml`:

```yaml
name: visible-files-after-fence
mode: interactive
plan: |
  ### Task 0: Real task

  ```text
  Files:
  - Create: docs/hidden.md
  ```

  Files:
  - Create: docs/real.md

  ## Verification
  Run `test -f docs/real.md`.
expected:
  files:
    - docs/real.md
```

### Step 1.3: Run Parser Checks

Run:

```bash
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/03-hidden-task-in-fence.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/04-hidden-files-in-comment.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/05-visible-files-after-fence.yaml
```

Expected for each command:

```text
"passed": true
```

## Task 2: Context Snapshot Helper

**Files:**
- Create: `scripts/build_context_snapshot.py`
- Modify: `references/state-schema.md`
- Modify: `evals/check_state_schema.py`

### Step 2.1: Add Helper Script

Create `scripts/build_context_snapshot.py`:

```python
#!/usr/bin/env python3
"""Build a per-run context snapshot for kws-codex-plan-executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_relative(path_text: str, repo_root: Path) -> str:
    path = Path(path_text).expanduser()
    resolved = path.resolve(strict=False) if path.is_absolute() else (repo_root / path).resolve(strict=False)
    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        die(f"source is outside repo: {path_text}")
    if any(part == ".." for part in rel.parts):
        die(f"source is outside repo: {path_text}")
    if not resolved.is_file():
        die(f"source is not readable: {path_text}")
    return rel.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(repo_root: Path, run_id: str, plan: str, spec: str | None, docs: list[str]) -> dict:
    sources = []
    for role, raw_path in [("plan", plan), ("spec", spec)]:
        if not raw_path:
            continue
        rel = repo_relative(raw_path, repo_root)
        abs_path = repo_root / rel
        sources.append({"role": role, "path": rel, "sha256": sha256_file(abs_path)})
    for raw_path in docs:
        rel = repo_relative(raw_path, repo_root)
        abs_path = repo_root / rel
        sources.append({"role": "doc", "path": rel, "sha256": sha256_file(abs_path)})

    basis_input = json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "1",
        "run_id": run_id,
        "workspace": str(repo_root),
        "sources": sources,
        "basis_hash": hashlib.sha256(basis_input.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--docs", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        die(f"repo root is not a directory: {repo_root}")
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    snapshot = build_snapshot(repo_root, args.run_id, args.plan, args.spec, docs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(snapshot["basis_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 2.2: State Schema Fields

Add these top-level fields to `references/state-schema.md`:

```json
"context_snapshot_path": ".codex-orchestrator/runs/<run_id>/context.json",
"context_basis_hash": "<sha256-of-source-list>"
```

Document:

- `context_snapshot_path` is required for `interactive` and `headless` execution after preflight initializes.
- `context_basis_hash` must equal the `basis_hash` inside `context.json`.
- Prompt and handoff modes may omit these fields.

### Step 2.3: Validator Rules

In `scripts/validate_state.py`, add these required checks:

- If `mode` is `interactive` or `headless` and `current_phase` is not `preflight`, `context_snapshot_path` must be a non-empty string.
- If `context_snapshot_path` is present, `context_basis_hash` must be a non-empty string.
- `context_snapshot_path` must equal `.codex-orchestrator/runs/<run_id>/context.json`.

Add this helper:

```python
def _required_project_path(run_id: str, name: str) -> str:
    return f".codex-orchestrator/runs/{run_id}/{name}"
```

Use it to validate both state and context paths.

## Task 3: Lifecycle Outcome And Completion Audit

**Files:**
- Modify: `scripts/validate_state.py`
- Modify: `references/state-schema.md`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `evals/check_state_schema.py`
- Modify: `evals/check_execution.py`

### Step 3.1: Define Constants In Validator

Add to `scripts/validate_state.py`:

```python
VALID_LIFECYCLE_OUTCOMES = {
    "finished",
    "blocked",
    "failed",
    "userinterlude",
    "askuserQuestion",
}
TERMINAL_PHASES = {"complete", "completed", "blocked", "error", "failed"}
NON_SUCCESS_OUTCOMES = {"blocked", "failed", "userinterlude", "askuserQuestion"}
```

### Step 3.2: Add Completion Audit Validation

Add helper functions:

```python
def _has_substantive_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return value is True


def _validate_completion_audit(data: dict, errors: list[str]) -> None:
    outcome = data.get("lifecycle_outcome")
    audit = data.get("completion_audit")

    if outcome == "finished":
        if not isinstance(audit, dict):
            errors.append("completion_audit must be present when lifecycle_outcome is finished")
            return
        if audit.get("passed") is not True:
            errors.append("completion_audit.passed must be true when lifecycle_outcome is finished")
        checklist = audit.get("prompt_to_artifact_checklist")
        evidence = audit.get("verification_evidence")
        if not _has_substantive_value(checklist):
            errors.append("completion_audit.prompt_to_artifact_checklist must be non-empty")
        if not _has_substantive_value(evidence):
            errors.append("completion_audit.verification_evidence must be non-empty")
        return

    if outcome in NON_SUCCESS_OUTCOMES and not _has_substantive_value(data.get("handoff_reason")):
        errors.append("handoff_reason must be non-empty for non-success lifecycle_outcome")
```

Call `_validate_completion_audit(data, errors)` near the end of `validate`.

### Step 3.3: Add Lifecycle Validation

Add in `validate`:

```python
if "lifecycle_outcome" in data and data["lifecycle_outcome"] not in VALID_LIFECYCLE_OUTCOMES:
    errors.append(f"lifecycle_outcome must be one of {sorted(VALID_LIFECYCLE_OUTCOMES)}")
```

Document in `references/state-schema.md`:

```json
"lifecycle_outcome": "finished",
"handoff_reason": "",
"completion_audit": {
  "passed": true,
  "prompt_to_artifact_checklist": [
    "Task 0 changed docs/example.md as requested"
  ],
  "verification_evidence": [
    {"command": "pytest tests/example_test.py", "status": "passed"}
  ],
  "open_gaps": [],
  "residual_risk": []
}
```

### Step 3.4: Extend `check_state_schema.py`

Add cases:

- `finished` with passing audit succeeds.
- `finished` without audit fails.
- `finished` with empty evidence fails.
- `blocked` with `handoff_reason` succeeds.
- `blocked` without `handoff_reason` fails.
- Invalid lifecycle value fails.

Use the existing `base_state()` helper. Extend its valid payload with:

```python
"lifecycle_outcome": "finished",
"handoff_reason": "",
"context_snapshot_path": ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3/context.json",
"context_basis_hash": "0" * 64,
"completion_audit": {
    "passed": True,
    "prompt_to_artifact_checklist": ["Task 0 mapped to docs/example.md"],
    "verification_evidence": [{"command": "test -f docs/example.md", "status": "passed"}],
    "open_gaps": [],
    "residual_risk": [],
},
```

## Task 4: Prompt And Runtime Documentation Alignment

**Files:**
- Modify: `SKILL.md`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `references/prompt-export-checklist.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`

### Step 4.1: `SKILL.md` Invariants

Add concise bullets to Core Invariants:

- Execution runs record a `context.json` source snapshot with source hashes before edits.
- Successful terminal runs set `lifecycle_outcome=finished` and include a passing `completion_audit`.
- Blocked or failed terminal runs set a non-success `lifecycle_outcome` and a concrete `handoff_reason`.

Keep detailed field definitions out of `SKILL.md`.

### Step 4.2: Execution Cycle

Update Phase 0:

- Build `context.json` after run id initialization and before task contracts.
- Store `context_snapshot_path` and `context_basis_hash` in state.

Update Phase 2:

- Before claiming completion, write `completion_audit` with checklist and verification evidence.
- Set `lifecycle_outcome` to `finished`, `blocked`, or `failed`.
- Include `handoff_reason` for non-success terminal outcomes.

### Step 4.3: Headless Runner

Add `context.json` to required artifacts:

```text
.codex-orchestrator/runs/<run_id>/context.json
```

Add a line that headless targets must not report completion until `state.json`
contains passing `completion_audit` evidence for `lifecycle_outcome=finished`.

### Step 4.4: Prompt Export Checklist

Add checks:

- Generated execution prompt requires `context.json` creation before edits.
- Final completion requires `completion_audit.passed=true`.
- Final handoff includes `lifecycle_outcome`, evidence, artifacts/state, and handoff reason when not finished.

### Step 4.5: Contract Eval

Extend `evals/check_skill_contract.py` expectations with these tokens:

- `context.json`
- `context_snapshot_path`
- `context_basis_hash`
- `completion_audit`
- `prompt_to_artifact_checklist`
- `verification_evidence`
- `lifecycle_outcome`
- `handoff_reason`

Check both runtime docs and `templates/fresh-session-prompt.txt`.

## Task 5: Optional Execution DAG Metadata

**Files:**
- Modify: `scripts/parse_plan.py`
- Modify: `references/state-schema.md`
- Modify: `evals/check_parse_plan.py`
- Create: `evals/parser-fixtures/08-execution-dag-valid.yaml`
- Create: `evals/parser-fixtures/09-execution-dag-cycle.yaml`

### Step 5.1: Parse Dependencies

Add regex:

```python
DEPENDS_RE = re.compile(r"(?mi)^\s*(?:\*\*)?Depends on\s*:\s*(?P<value>.+?)\s*(?:\*\*)?\s*$")
```

Add helper:

```python
def _extract_depends_on(body: str) -> list[str]:
    match = DEPENDS_RE.search(body)
    if not match:
        return []
    values = []
    for item in re.split(r"[, ]+", match.group("value").strip()):
        normalized = item.strip().removeprefix("task_")
        if normalized.isdigit():
            values.append(f"task_{normalized}")
    return sorted(dict.fromkeys(values))
```

When creating each task payload, add:

```python
"depends_on": _extract_depends_on(body),
```

### Step 5.2: Validate Dependencies

After all tasks are built:

```python
def _validate_task_dependencies(tasks: list[dict]) -> None:
    ids = {task["id"] for task in tasks}
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in ids:
                _die(f"{task['id']} depends on unknown task: {dep}")

    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {task["id"]: task for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            _die(f"cycle detected at task: {task_id}")
        visiting.add(task_id)
        for dep in by_id[task_id].get("depends_on", []):
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task["id"])
```

Call `_validate_task_dependencies(tasks)` before returning parsed payload.

### Step 5.3: Fixtures

Create `evals/parser-fixtures/08-execution-dag-valid.yaml`:

```yaml
name: execution-dag-valid
mode: interactive
plan: |
  ### Task 0: Build base

  Files:
  - Create: src/base.py

  ## Verification
  Run `python -m py_compile src/base.py`.

  ### Task 1: Use base

  Depends on: task_0

  Files:
  - Create: src/use_base.py

  ## Verification
  Run `python -m py_compile src/use_base.py`.
expected:
  files:
    - src/base.py
    - src/use_base.py
```

Create `evals/parser-fixtures/09-execution-dag-cycle.yaml`:

```yaml
name: execution-dag-cycle
mode: interactive
plan: |
  ### Task 0: First

  Depends on: task_1

  Files:
  - Create: src/first.py

  ### Task 1: Second

  Depends on: task_0

  Files:
  - Create: src/second.py
expected:
  error_contains: cycle detected
```

`check_parse_plan.py` already supports `error_contains`, so the cycle fixture
does not need runner changes.

## Task 6: High-Risk Verification Matrix

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/prompt-export-checklist.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`

### Step 6.1: Add Matrix Text

Add under risk-scaled verification:

```markdown
For `risk=high`, maintain a compact verification matrix. Include each relevant
scenario with `status=passed|failed|blocked|not-applicable`, the command or
manual check, and the evidence path or excerpt:

- malformed or unexpected input
- stale state or resume path
- dirty worktree preservation
- hung or long-running command behavior
- misleading success output or skipped tests
- cancellation/interruption recovery when the task changes workflow state

Do not run irrelevant scenarios just to fill the table. Mark them
`not-applicable` with one concrete reason.
```

### Step 6.2: State Recording

Document that task `verification` entries may include:

```json
{
  "type": "high_risk_matrix",
  "scenario": "misleading_success_output",
  "status": "passed",
  "evidence": "raw/task_1-misleading-success.txt"
}
```

No validator enforcement is needed in the first implementation because task
risk assignment remains partly judgment-based.

## Task 7: Package Metadata

**Files:**
- Modify: `SKILL.md`
- Modify: `ARCHITECTURE.md`
- Modify: `HISTORY.md`
- Modify: `references/common-mistakes.md`
- Modify: `ai/skills/kws-skills/manifest.json`
- Modify: `ai/skills/kws-skills/README.md`
- Modify: `ai/skills/kws-skills/CHANGELOG.md`

### Step 7.1: Version

Bump skill metadata from `1.4.0` to `1.5.0` because the change adds runtime
contracts and state schema behavior.

### Step 7.2: History Entry

Add:

```markdown
## v1.5.0 - Add source-grounded completion proof (2026-05-14)

- Hardened plan parsing to ignore hidden Markdown regions such as fenced code,
  HTML comments, and indented code.
- Added per-run `context.json` source snapshots with source hashes.
- Added terminal `lifecycle_outcome` metadata and completion audit proof for
  successful runs.
- Added optional execution dependency metadata and high-risk verification
  matrix guidance without changing subagent opt-in policy.
```

### Step 7.3: Common Mistakes

Add bullets:

- Do not parse executable tasks or file blocks from fenced code, HTML comments, or indented code.
- Do not report `lifecycle_outcome=finished` without a passing `completion_audit`.
- Do not use `current_phase` as a substitute for terminal lifecycle outcome.
- Do not let optional DAG metadata bypass per-task execution contracts.
- Do not store source snapshots outside `.codex-orchestrator/runs/<run_id>/`.

## Task 8: Validation Commands

Run from:

```bash
cd /Users/kws/source/private/Archive/ai/skills/kws-skills/package/kws-codex-plan-executor
```

Commands:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 scripts/build_context_snapshot.py --help
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/03-hidden-task-in-fence.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/04-hidden-files-in-comment.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/05-visible-files-after-fence.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/08-execution-dag-valid.yaml
python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/09-execution-dag-cycle.yaml
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
../../tests/test-sync.sh
```

Expected:

- Help commands exit `0`.
- Parser fixture checks emit `"passed": true`.
- State schema check emits `"passed": true`.
- Skill contract check emits `"passed": true`.
- Quick validation exits `0`.
- Package sync test exits `0`.

## Rollback Plan

If parser hardening causes unexpected failures:

1. Keep the new hidden-region fixtures.
2. Revert only the `_visible_markdown` call site.
3. Re-run parser fixtures to confirm the failure mode is isolated.
4. Reintroduce the normalizer with a narrower hidden-region rule.

If completion audit enforcement blocks valid blocked/error runs:

1. Confirm `lifecycle_outcome` is not `finished`.
2. Add or fix `handoff_reason`.
3. Keep `completion_audit` required only for `finished`.

If prompt export and runtime docs drift:

1. Run `python3 evals/check_skill_contract.py --skill SKILL.md`.
2. Update the missing token in the lower-level reference first.
3. Mirror the same behavior in `templates/fresh-session-prompt.txt`.
