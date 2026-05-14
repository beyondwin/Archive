# Log-Driven Executor Hardening Implementation Details

This document expands `PLAN.md` into concrete implementation guidance. It is
written for a future implementation pass against `kws-codex-plan-executor`; it
does not claim the changes are already applied.

## Implementation Order

1. Add deterministic log-health fixtures.
2. Implement read-only log-health reporting.
3. Decide whether `index.jsonl` stays append-only or is rewritten on close.
4. Add stale-run classification.
5. Update execution-cycle guidance for local env, resource serialization, and resource failure triage.
6. Add carried acceptance state validation.
7. Add phase-level method audit validation.
8. Update docs, history, architecture, and verification evidence.

This order makes the logging/reporting problem measurable before changing
runtime guidance.

## Task 1: Learning-Log Health Fixtures

**Files:**
- Modify: `evals/check_learning_log.py`

### Step 1.1: Add Fixture Builder Helpers

Extend the eval so it can create realistic user-local log shards in a temporary
directory. Add helpers shaped like this:

```python
def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def make_run(log_root: Path, run_id: str, *, pid: int, started_at: str, outcome: str = "unknown") -> Path:
    date = f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}"
    run_dir = log_root / "runs" / date / run_id
    meta = {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.7.1",
        "host": "test.local",
        "pid": pid,
        "repo": {"name": "Fixture", "branch": "codex/test", "remote_hash": "abc123"},
        "mode": "interactive",
        "plan_path": "docs/superpowers/plans/test.md",
        "spec_path": None,
        "worktree_path": "/tmp/worktree",
        "project_run_dir": f".codex-orchestrator/runs/{run_id}",
        "state_path": f".codex-orchestrator/runs/{run_id}/state.json",
        "started_at": started_at,
        "ended_at": None,
        "outcome": outcome,
        "event_count": 0,
    }
    write_json(run_dir / "meta.json", meta)
    append_jsonl(log_root / "index.jsonl", {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.7.1",
        "repo": meta["repo"],
        "mode": "interactive",
        "plan_path": meta["plan_path"],
        "project_run_dir": meta["project_run_dir"],
        "state_path": meta["state_path"],
        "started_at": started_at,
        "outcome": "unknown",
    })
    return run_dir
```

### Step 1.2: Add Expected Cases

Create four cases inside the eval:

1. `index_unknown_final_success`: `index.jsonl` says `unknown`; `final.json` says `success`.
2. `zero_event_success`: `final.json` says `success`; `event_count=0`; no `events.jsonl`.
3. `dead_pid_unclosed_run`: no `final.json`; `ended_at=null`; pid is impossible, such as `999999`.
4. `live_pid_unclosed_run`: no `final.json`; `ended_at=null`; pid is `os.getpid()`.

Expected classifications:

| Case | Expected status | Expected warning |
| --- | --- | --- |
| `index_unknown_final_success` | `success` | `index_outcome_stale` |
| `zero_event_success` | `success` | none |
| `dead_pid_unclosed_run` | `stale` | `dead_pid_unclosed` |
| `live_pid_unclosed_run` | `unknown` | none |

### Step 1.3: Run The Eval

Run:

```bash
python3 evals/check_learning_log.py
```

Expected:

```text
learning log checks passed
```

## Task 2: Read-Only Health Reporter

**Files:**
- Create: `scripts/check_learning_log_health.py`
- Modify: `evals/check_learning_log.py`

### Step 2.1: Create Script Skeleton

Create `scripts/check_learning_log_health.py`:

```python
#!/usr/bin/env python3
"""Summarize kws-codex-plan-executor learning-log health."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_LOG_ROOT = Path("~/.codex/learning/kws-codex-plan-executor").expanduser()
TERMINAL_OUTCOMES = {"success", "blocked", "error"}


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    return data


def read_index(log_root: Path) -> list[dict[str, Any]]:
    path = log_root / "index.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def run_dir_for(log_root: Path, run_id: str) -> Path:
    date = f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}"
    return log_root / "runs" / date / run_id


def pid_is_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def count_events(run_dir: Path) -> int:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
```

### Step 2.2: Add Run Summarization

Continue the script:

```python
def summarize_run(log_root: Path, index_row: dict[str, Any], *, now: dt.datetime, stale_after_minutes: int) -> dict[str, Any]:
    run_id = str(index_row["run_id"])
    run_dir = run_dir_for(log_root, run_id)
    meta = read_json(run_dir / "meta.json") or {}
    final = read_json(run_dir / "final.json")
    event_count = count_events(run_dir)
    warnings: list[str] = []

    status = "unknown"
    if final and final.get("outcome"):
        status = str(final["outcome"])
        if index_row.get("outcome") != status:
            warnings.append("index_outcome_stale")
    elif meta.get("outcome") in TERMINAL_OUTCOMES:
        status = str(meta["outcome"])
    elif meta:
        started_at = parse_time(str(meta.get("started_at") or ""))
        ended_at = meta.get("ended_at")
        pid_alive = pid_is_alive(meta.get("pid"))
        old_enough = started_at is not None and now - started_at > dt.timedelta(minutes=stale_after_minutes)
        if ended_at is None and pid_alive is False and old_enough:
            status = "stale"
            warnings.append("dead_pid_unclosed")

    if status == "success" and event_count == 0:
        event_note = "routine_success_no_notable_events"
    else:
        event_note = None

    return {
        "run_id": run_id,
        "status": status,
        "repo": (meta or index_row).get("repo"),
        "plan_path": (meta or index_row).get("plan_path"),
        "started_at": (meta or index_row).get("started_at"),
        "ended_at": (final or meta).get("ended_at") if (final or meta) else None,
        "event_count": event_count,
        "event_note": event_note,
        "warnings": warnings,
        "run_dir": str(run_dir),
    }
```

### Step 2.3: Add CLI

Finish the script:

```python
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    parser.add_argument("--latest", type=int, default=5)
    parser.add_argument("--stale-after-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log_root = Path(args.log_root).expanduser()
    rows = read_index(log_root)[-args.latest :]
    now = dt.datetime.now(dt.UTC)
    summaries = [
        summarize_run(log_root, row, now=now, stale_after_minutes=args.stale_after_minutes)
        for row in rows
    ]

    if args.json:
        print(json.dumps({"schema_version": "1", "runs": summaries}, indent=2, sort_keys=True))
        return 0

    for item in summaries:
        warnings = ",".join(item["warnings"]) if item["warnings"] else "-"
        print(f"{item['status']:8} events={item['event_count']} warnings={warnings} {item['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 2.4: Verify

Run:

```bash
python3 scripts/check_learning_log_health.py --latest 5 --json
python3 evals/check_learning_log.py
```

Expected:

- Latest real runs show terminal outcomes from `final.json` when present.
- Zero-event success is annotated as routine success, not warned.
- The unclosed GasStation-style fixture is `stale` only when the pid is dead and the age threshold is met.

## Task 3: Close-Run Index Coherence

**Files:**
- Modify: `scripts/append_learning_event.py`
- Modify: `evals/check_learning_log.py`
- Modify: `references/learning-log.md`

There are two acceptable approaches. Pick one before implementation and record
the decision in `docs/decisions.md` if it becomes durable.

### Option A: Keep Index Append-Only

Do not mutate `index.jsonl` on close. Instead:

- Rename mental model from "latest state index" to "run start index".
- Require reporters to read `final.json` or `meta.json` for terminal outcome.
- Keep `index_outcome_stale` as an informational warning.

This is safer for append-only logs and avoids rewriting JSONL.

### Option B: Rewrite Index On Close

Add a helper to rewrite matching index rows:

```python
def update_index_outcome(log_root: Path, run_id: str, outcome: str, ended_at: str) -> None:
    path = log_root / "index.jsonl"
    if not path.is_file():
        return
    rows = []
    changed = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("run_id") == run_id:
            row["outcome"] = outcome
            row["ended_at"] = ended_at
            changed = True
        rows.append(row)
    if changed:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
```

Call it at the end of `cmd_close_run` after `final.json` is saved:

```python
update_index_outcome(log_root, args.run_id, args.outcome, meta["ended_at"])
```

Preferred choice: **Option A** unless a human-facing dashboard explicitly uses
`index.jsonl` directly. The reporter already solves the analysis problem and
does not rewrite history.

## Task 4: Stale Run Classification

**Files:**
- Modify: `scripts/check_learning_log_health.py`
- Modify: `references/learning-log.md`
- Modify: `docs/state-and-logging.md`

### Required Semantics

A run is stale when all of these are true:

- `final.json` is absent.
- `meta.json` exists.
- `meta.ended_at` is `null`.
- `meta.pid` is not alive.
- `now - meta.started_at > stale_after_minutes`.

Do not classify these as stale:

- A run with `final.json`.
- A run whose pid is still alive.
- A run whose pid cannot be checked because of permissions.
- A recently started unclosed run under the age threshold.

### Documentation Text

Add this wording to `references/learning-log.md`:

```markdown
`index.jsonl` is a run start index. Terminal outcome is read from
`runs/<date>/<run_id>/final.json` when present, then `meta.json`.

`event_count=0` is normal for routine success because the log records only
notable boundaries.

A stale run is diagnostic, not a terminal lifecycle outcome. It means the
learning-log helper saw an initialized run whose process is no longer alive and
whose run was never closed. Do not mutate project state from the health report.
```

## Task 5: Local Environment Preflight

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `references/common-mistakes.md`

Add this section after dedicated worktree creation and before baseline
verification:

```markdown
### Local Environment Preflight

Before baseline commands in a new dedicated worktree, check for ignored
machine-local files that the project needs but git will not copy.

Examples:

- Android/Gradle: `local.properties` with `sdk.dir`.
- Node/frontend: installed dependencies for the selected package manager.
- Docker build tasks: available Docker memory and daemon reachability.
- Local env templates: `.env.example` exists but `.env` is intentionally absent.

Do not silently copy ignored files. If a missing file blocks baseline
verification, either ask the user, copy only after explicit approval, or record
an honest substitute explaining the environment blocker.
```

For Android plans, suggest this check:

```bash
test -f local.properties || test -f ../main-worktree/local.properties
```

Use actual paths discovered from `git worktree list --porcelain`; do not hardcode
user home paths in docs, state, or learning events.

## Task 6: Verification Resource Keys

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/state-schema.md`

Add a verification scheduling rule:

```markdown
### Verification Resource Keys

Parallel verification is allowed only when commands do not share mutable output
resources.

Use these resource key patterns:

- Gradle Test task: `gradle-test:<project-path>:<task-name>:<test-results-dir>`
- Gradle build task: `gradle-build:<project-path>`
- Node package command: `node:<package-dir>:<command-name>`
- Docker build: `docker-build:<dockerfile-path>:<context-path>:<tag>`
- Browser/E2E command: `browser:<app-url-or-project>:<suite>`

Commands with the same resource key run serially in one worktree. Record the
serialization reason when this changes the verification plan.
```

Optional state shape:

```json
{
  "verification": {
    "resource_serialization": [
      {
        "resource_key": "gradle-test:server:integrationTest:server/build/test-results/integrationTest",
        "commands": [
          "./server/gradlew -p server integrationTest --tests com.example.A",
          "./server/gradlew -p server integrationTest --tests com.example.B"
        ],
        "reason": "Gradle Test XML output is shared inside one worktree.",
        "decision": "serial"
      }
    ]
  }
}
```

## Task 7: Docker And Gradle Resource Triage

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/common-mistakes.md`

Add a resource triage block:

```markdown
### Docker/Gradle Resource Triage

When Docker build fails during Gradle/Kotlin compilation:

1. Identify the failed builder container when available.
2. Check whether Docker reports OOM:

   ```bash
   docker inspect <container-id> --format '{{.State.OOMKilled}}'
   ```

3. If OOM is true, treat it as environment/resource evidence before changing
   project source.
4. For Gradle daemon disappearance, distinguish:
   - container OOM
   - JVM metaspace limit
   - Kotlin daemon memory pressure
   - real compile error
5. If a bounded retry succeeds, record `successful_workaround` with the resource
   constraint and the bounded command.
```

Privacy note: learning events should store shortened container identifiers or a
redacted summary, not full unrelated process details.

## Task 8: Carried Acceptance State

**Files:**
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`

### State Shape

Add optional task-level `carried_acceptance`:

```json
{
  "tasks": {
    "task_6": {
      "status": "completed",
      "carried_acceptance": {
        "status": "open",
        "metric": "front index chunk size",
        "baseline_value": "208.78 kB after task_5",
        "current_value": "221.68 kB after task_6",
        "reason": "Host feature barrel remains statically reachable until task_7.",
        "depends_on_task": "task_7",
        "next_action": "Resolve host barrel coupling and rerun pnpm --dir front build."
      }
    }
  }
}
```

Valid `status` values:

- `open`
- `resolved`
- `accepted_with_rationale`

Validation rules:

- `open` is allowed before terminal `lifecycle_outcome=finished`.
- Finished runs fail validation if any task has `carried_acceptance.status=open`.
- Finished runs pass when all carried acceptance entries are `resolved` or
  `accepted_with_rationale` and the `completion_audit.verification_evidence`
  references the final metric.

### Failing Test Example

Add a state-schema test where:

- `lifecycle_outcome=finished`
- `completion_audit.passed=true`
- `tasks.task_6.carried_acceptance.status=open`

Expected error:

```text
open carried_acceptance is not allowed for lifecycle_outcome=finished
```

## Task 9: Phase Method Audit

**Files:**
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/state-and-logging.md`

### State Shape

Add top-level `method_audit`:

```json
{
  "method_audit": {
    "required": [
      "using-superpowers",
      "test-driven-development",
      "verification-before-completion"
    ],
    "applied": [
      {
        "skill": "test-driven-development",
        "phase": "implementation",
        "status": "applied",
        "evidence_refs": [
          "tasks.task_2.red_evidence",
          "tasks.task_2.green_evidence"
        ],
        "summary": "RED failed before implementation; GREEN passed after the fix."
      },
      {
        "skill": "review",
        "phase": "review",
        "status": "applied",
        "evidence_refs": [
          "review.findings",
          "review.residual_risk"
        ],
        "summary": "Diff reviewed; no blocking findings remained."
      },
      {
        "skill": "verification-before-completion",
        "phase": "verification",
        "status": "applied",
        "evidence_refs": [
          "completion_audit.verification_evidence"
        ],
        "summary": "Completion was claimed only after recorded verification commands passed."
      }
    ],
    "missing": [],
    "waived": [
      {
        "skill": "test-driven-development",
        "phase": "implementation",
        "reason": "Docs-only planning change with no behavior implementation."
      }
    ]
  }
}
```

### Validation Rules

The validator should treat method audit as an evidence-backed phase contract,
not as a command log.

Rules:

- Every skill in `method_audit.required` must appear in exactly one of
  `applied`, `missing`, or `waived`.
- `applied[].status` must be `applied`.
- `applied[].evidence_refs` must be non-empty.
- `missing` entries fail validation when `lifecycle_outcome=finished`.
- `waived` entries must include a non-empty `reason`.
- `test-driven-development` applied during implementation must reference both
  RED and GREEN evidence.
- `review` applied during review must reference findings or an explicit
  no-findings residual-risk statement.
- `verification-before-completion` applied during verification must reference
  `completion_audit.verification_evidence`.
- `using-superpowers` applied as a gate must reference the task contract or
  pre-implementation state where the gate was acknowledged.

### Required Methods By Run Type

Use these defaults:

| Run type | Required method audit entries |
| --- | --- |
| Feature, bugfix, refactor, or behavior implementation | `using-superpowers`, `test-driven-development`, `verification-before-completion` |
| Code review only | `review` |
| Review feedback implementation | `receiving-code-review`, `test-driven-development` when behavior changes, `verification-before-completion` |
| Docs-only planning | `writing-plans` or a waiver explaining why this was a direct document update |
| Prompt export or handoff only | prompt export checklist evidence; no implementation TDD requirement |

Do not require every incidental helper skill. The audit should capture the
methods that materially prove the run followed the required execution contract.

### Failing Test Examples

Add state-schema cases for:

1. Finished implementation run with `test-driven-development` in `required` but
   no matching `applied` or `waived` entry.
2. Finished implementation run with TDD applied but only GREEN evidence.
3. Finished review run with review applied but no findings or residual-risk
   reference.
4. Docs-only run with TDD waived and a non-empty reason.

Expected errors:

```text
required method test-driven-development has no applied or waived evidence
test-driven-development requires RED and GREEN evidence references
review method requires findings or residual-risk evidence
```

### Execution-Cycle Wording

Add this guidance to `references/execution-cycle.md`:

```markdown
### Method Audit

Record phase methods by evidence, not by intent. A method is applied only when
the state points to evidence that the method's contract was followed.

Examples:

- TDD requires RED and GREEN evidence.
- Review requires findings or an explicit no-findings plus residual-risk note.
- Completion verification requires command evidence.

Do not record routine helper skills. Record required methods and explicit
waivers only.
```

## Task 10: Route-Lazy Guidance

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/common-mistakes.md`

Add a scoped note:

```markdown
### React Router Lazy Route Tasks

When a task converts static React Router route objects to lazy route objects,
include route test harness updates in `allowed_edits` unless the plan explicitly
forbids test changes.

Expected verification risks:

- lazy route rendering is asynchronous in tests
- routes may need `hydrateFallbackElement`
- request construction may hit existing test shims
- public navigation/auth tests may need async assertions even when product
  behavior is unchanged
```

Do not apply this guidance to unrelated frontend frameworks.

## Task 11: Documentation And Release Alignment

**Files:**
- Modify: `ARCHITECTURE.md`
- Modify: `HISTORY.md`
- Modify: `README.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/verification-log.md`
- Modify: `SKILL.md` only if a top-level invariant changes.

### Required Documentation Updates

Update `docs/state-and-logging.md` to explain:

- `index.jsonl` is a start index.
- `final.json` is the terminal outcome source.
- `event_count=0` is normal for routine success.
- stale run detection is diagnostic.

Update `docs/evals-and-verification.md` with:

```bash
python3 scripts/check_learning_log_health.py --latest 5 --json
python3 evals/check_learning_log.py
```

Update `docs/risks-limitations-deferrals.md` with:

- local env files are detected but not copied automatically
- stale run health does not mutate project state
- resource-key serialization is guidance unless a future scheduler enforces it

Update `HISTORY.md` if scripts, evals, or runtime contracts change.

## Final Verification Commands

Run from `skills/kws-codex-plan-executor/`:

```bash
python3 scripts/append_learning_event.py --help
python3 scripts/check_learning_log_health.py --help
python3 evals/check_learning_log.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

If only these two planning documents are added and no runtime behavior changes,
run this narrower docs-only check instead:

```bash
test -f docs/experiments/2026-05-14-log-driven-executor-hardening/PLAN.md
test -f docs/experiments/2026-05-14-log-driven-executor-hardening/IMPLEMENTATION.md
```

Record the chosen verification path in `docs/verification-log.md`.

## Completion Checklist

- Learning-log health reporter summarizes the latest runs without misleading
  `unknown` outcomes.
- Stale unclosed runs are visible without mutating state.
- Zero-event success is treated as normal.
- Execution docs prevent known local-env baseline failures.
- Verification docs prevent known Gradle output collisions.
- Resource triage distinguishes Docker/Gradle environment failure from source
  failure.
- Sequential metrics can be carried forward and resolved.
- Method audit records actual phase-method application with evidence references,
  not just skill invocation intent.
- Docs and evals explain the behavior a future agent must follow.
