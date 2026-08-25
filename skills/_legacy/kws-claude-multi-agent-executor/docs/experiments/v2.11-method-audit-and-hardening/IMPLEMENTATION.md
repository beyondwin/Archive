# v2.11 — Method Audit + Codex-Inspired Hardening Implementation Details

This document expands `PLAN.md` into concrete implementation guidance. It is written for a future implementation pass against `kws-claude-multi-agent-executor`; it does not claim the changes are already applied.

## Implementation Order

1. **Task 1 — Fixtures first.** Both `check_method_audit.py` and the extended `check_learning_log.py` cases give us a measurable bar before any source change.
2. **Task 2 — Helper-side outcome rewrite.** Shared with `kws-codex-plan-executor`; lands in the helper script so both skills benefit. Verified by Task 1 fixtures.
3. **Task 3 — Sub-agent prompt outputs.** Sub-agents must emit structured `METHOD_AUDIT:` / `REVIEW_FINDINGS:` lines before any populator or validator can read them.
4. **Task 4 — SubagentStop hook gate.** Adds per-task enforcement at runtime; prevents the common skip path.
5. **Task 5 — Validator + Phase 2 gate.** Reads the state populated by later orchestration steps; runtime-enforced at run end.
6. **Task 6 — Orchestrator populator.** Wires Phase 1 Step 4 to parse the sub-agent outputs and populate state.
7. **Task 7 — ENV_BLOCKER categories.** Independent of method audit; pure docs + optional learning-log field.
8. **Task 8 — Local-env preflight.** SKILL.md addition; report-only.
9. **Task 9 — Resource-key partition.** SKILL.md + Plan Reviewer audit; preserves backward compatibility.
10. **Task 10 — Docs, history, experiment folder.** Lock in the changes.

The dependency ordering: 1 → 2 (verified by 1), 1 → 3, 3 → 4, {3, 6} → 5, 7, 8, 9 in any order, then 10.

## Task 1: Method Audit Fixtures + Learning-Log Outcome Fixtures

**Files:**
- Create: `evals/check_method_audit.py`
- Modify: `evals/check_learning_log.py`

### Step 1.1: Create `evals/check_method_audit.py` Skeleton

```python
#!/usr/bin/env python3
"""Deterministic checks for state.tasks.<id>.method_audit."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


EXECUTABLE_REQUIRED = ["test-driven-development", "verification-before-completion", "code-review-pass"]
DOCS_ONLY_REQUIRED = ["verification-before-completion"]


def _is_docs_only(task: dict[str, Any]) -> bool:
    files = task.get("files", [])
    files_test = task.get("files_test")
    if files_test == []:
        return True
    if files_test is None and files and all(f.endswith(".md") for f in files):
        return True
    return False


def _required_for(task: dict[str, Any]) -> list[str]:
    return DOCS_ONLY_REQUIRED if _is_docs_only(task) else EXECUTABLE_REQUIRED


def _audit_task(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") != "COMPLETE":
        return {"task_audited": False, "reason": "not_complete"}
    audit = task.get("method_audit") or {}
    required = set(_required_for(task))
    applied = {entry.get("skill") for entry in (audit.get("applied") or [])}
    waived = {entry.get("skill") for entry in (audit.get("waived") or [])}
    missing = sorted(required - applied - waived)
    return {
        "task_audited": True,
        "required": sorted(required),
        "applied": sorted(applied),
        "waived": sorted(waived),
        "missing": missing,
        "passed": missing == [],
    }


def _make_state(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "active_plan": "plan1",
        "tasks": {"task_0": task},
    }
```

### Step 1.2: Add the Four Fixtures + Runner

Append to the same file:

```python
FIXTURES = {
    "applied_with_evidence": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "required": EXECUTABLE_REQUIRED,
                "applied": [
                    {"skill": "test-driven-development",
                     "evidence": {"red": "pytest tests/test_foo.py::test_bar",
                                  "green": "pytest tests/test_foo.py::test_bar",
                                  "tests": ["tests/test_foo.py::test_bar"]}},
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["pytest", "ruff check"]}},
                    {"skill": "code-review-pass",
                     "evidence": {"findings_count": 0,
                                  "residual_risk": "no shared state touched"}},
                ],
                "missing": [],
                "waived": [],
            },
        },
        "expect_passed": True,
    },
    "missing_tdd_on_executable": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "applied": [
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["pytest"]}},
                    {"skill": "code-review-pass",
                     "evidence": {"findings_count": 0}},
                ],
                "waived": [],
            },
        },
        "expect_passed": False,
        "expect_missing": ["test-driven-development"],
    },
    "docs_only_waived": {
        "input": {
            "status": "COMPLETE",
            "risk": "low",
            "files": ["docs/runbook.md"],
            "files_test": [],
            "method_audit": {
                "applied": [
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["markdownlint docs/runbook.md"]}},
                ],
                "waived": [
                    {"skill": "test-driven-development", "reason": "docs-only-task"},
                    {"skill": "code-review-pass", "reason": "docs-only-task"},
                ],
            },
        },
        "expect_passed": True,
    },
    "mid_risk_no_verification": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "applied": [
                    {"skill": "test-driven-development",
                     "evidence": {"red": "x", "green": "x", "tests": ["x"]}},
                ],
                "waived": [],
            },
        },
        "expect_passed": False,
        "expect_missing": ["code-review-pass", "verification-before-completion"],
    },
}


def run() -> int:
    failures: list[str] = []
    for name, case in FIXTURES.items():
        result = _audit_task(case["input"])
        if not result.get("task_audited"):
            failures.append(f"{name}: task not audited ({result})")
            continue
        if result["passed"] != case["expect_passed"]:
            failures.append(f"{name}: expected passed={case['expect_passed']}, got {result}")
            continue
        if not case["expect_passed"]:
            if result["missing"] != case["expect_missing"]:
                failures.append(f"{name}: expected missing={case['expect_missing']}, got {result['missing']}")
    if failures:
        print(json.dumps({"passed": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"passed": True, "fixtures": list(FIXTURES.keys())}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run())
```

### Step 1.3: Extend `evals/check_learning_log.py`

Locate the existing `FIXTURES` (or test-case) section and add the four new cases. The shape depends on the existing eval; treat the cases as a brief extension. The minimum the eval must demonstrate is:

```python
def fixture_index_unknown_final_success(log_root: Path) -> dict:
    run_id = "20260514T010000Z-test-success-aaaa-aaaaaa"
    run_dir = log_root / "runs" / "2026-05-14" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (log_root / "index.jsonl").write_text(json.dumps({
        "schema_version": "1", "run_id": run_id, "outcome": "unknown",
    }) + "\n", encoding="utf-8")
    (run_dir / "final.json").write_text(json.dumps({
        "schema_version": "1", "run_id": run_id, "outcome": "success",
    }), encoding="utf-8")
    return {"expected_status": "success", "expected_warnings": ["index_outcome_stale"]}
```

Mirror the pattern for `zero_event_success`, `dead_pid_unclosed_run`, `live_pid_unclosed_run`. Use `os.getpid()` for the live case and `999999` for the dead case (with a fallback skip if `os.kill(999999, 0)` raises PermissionError — that means the test host genuinely has that PID).

### Step 1.4: Run the Evals

```bash
python3 evals/check_method_audit.py
python3 evals/check_learning_log.py
```

Expected: both print `"passed": true`. The fixtures are passing in pure-data form; no orchestration code path exercised yet.

### Step 1.5: Commit

```text
test: cover method audit and learning-log outcome fixtures
```

## Task 2: Learning-Log `close-run` Index Rewrite + Outcome Resolver

**Files:**
- Modify: `scripts/append_learning_event.py`
- Modify: `references/learning-log.md`

### Step 2.1: Add `_rewrite_index_outcome` Helper

Locate the existing `close_run` function. Above it, add:

```python
import fcntl
import os
import tempfile

def _rewrite_index_outcome(log_root: Path, run_id: str, outcome: str) -> bool:
    """Atomic rewrite of index.jsonl: update the matching run_id row's outcome.

    Returns True on rewrite, False if no matching row was found.
    """
    index_path = log_root / "index.jsonl"
    if not index_path.is_file():
        return False

    # Hold a lock on the index across read + write to avoid interleaving with
    # concurrent init-run / append calls from other skills (e.g., parallel
    # codex-plan-executor runs).
    with index_path.open("r+", encoding="utf-8") as src:
        fcntl.flock(src.fileno(), fcntl.LOCK_EX)
        rows = []
        rewritten = False
        for line in src:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append(line)
                continue
            if row.get("run_id") == run_id:
                row["outcome"] = outcome
                rewritten = True
            rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))

        if not rewritten:
            return False

        tmp = tempfile.NamedTemporaryFile("w", delete=False,
                                          dir=index_path.parent,
                                          prefix=".index.", suffix=".tmp")
        try:
            tmp.write("\n".join(rows) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, index_path)
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise
        return True
```

### Step 2.2: Wire into `close-run`

In the existing `close_run` function (after `final.json` and `meta.json` writes succeed):

```python
    try:
        _rewrite_index_outcome(log_root, run_id, outcome)
    except OSError as exc:
        # Index rewrite is best-effort; surface to stderr but don't abort.
        # The resolver will still find the outcome via final.json.
        print(f"warning: failed to rewrite index outcome for {run_id}: {exc}",
              file=sys.stderr)
```

### Step 2.3: Add `resolve-outcome` Subcommand

In the `argparse` block:

```python
    sub_resolve = subparsers.add_parser("resolve-outcome",
        help="Resolve terminal outcome for a run (final.json > meta.json > index.jsonl)")
    sub_resolve.add_argument("--run-id", required=True)
    sub_resolve.add_argument("--log-root", default=None,
                             help="Default: ~/.claude/learning/kws-claude-multi-agent-executor")
    sub_resolve.add_argument("--json", action="store_true",
                             help="Print full resolution metadata as JSON")
```

Handler:

```python
def cmd_resolve_outcome(args) -> int:
    log_root = Path(args.log_root or DEFAULT_LOG_ROOT).expanduser()
    run_id = args.run_id
    date_dir = log_root / "runs" / f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}"
    run_dir = date_dir / run_id

    sources_checked = []
    outcome = None
    source = None

    final_path = run_dir / "final.json"
    if final_path.is_file():
        sources_checked.append(str(final_path))
        try:
            data = json.loads(final_path.read_text(encoding="utf-8"))
            outcome = data.get("outcome")
            source = "final.json"
        except (json.JSONDecodeError, OSError):
            pass

    if outcome is None:
        meta_path = run_dir / "meta.json"
        if meta_path.is_file():
            sources_checked.append(str(meta_path))
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                outcome = data.get("outcome")
                source = "meta.json" if outcome and outcome != "unknown" else source
                if outcome == "unknown":
                    outcome = None
            except (json.JSONDecodeError, OSError):
                pass

    if outcome is None:
        index_path = log_root / "index.jsonl"
        if index_path.is_file():
            sources_checked.append(str(index_path))
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("run_id") == run_id:
                    outcome = row.get("outcome")
                    source = "index.jsonl"
                    break

    payload = {
        "run_id": run_id,
        "outcome": outcome or "unknown",
        "source": source,
        "sources_checked": sources_checked,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(outcome or "unknown")
    return 0
```

Add the dispatch line in the main entrypoint.

### Step 2.4: Update `references/learning-log.md`

Add a "Source of truth" section near the top:

```markdown
## Source of truth for terminal outcome

Precedence (highest first):

1. `runs/<date>/<run_id>/final.json` — written by `close-run`. Authoritative once present.
2. `runs/<date>/<run_id>/meta.json` — mirrors `final.json` outcome when close-run runs; remains `unknown` until then.
3. `index.jsonl` — start records by default. **As of v2.11**, `close-run` rewrites the matching row's `outcome` field atomically. Older runs prior to this change still have stale `index.jsonl` entries; use `resolve-outcome` to query.

Use `scripts/append_learning_event.py resolve-outcome --run-id <id>` instead of reading `index.jsonl` directly when reporting on closed runs.

A run with `event_count == 0` AND `final.outcome == "success"` is **normal** for routine successful work — learning events are notable-boundary-only, not routine task logs.
```

### Step 2.5: Run Evals

```bash
python3 evals/check_learning_log.py
python3 scripts/append_learning_event.py resolve-outcome --help
```

### Step 2.6: Commit

```text
feat: harden learning-log outcome resolution and index rewrite
```

## Task 3: Method Audit Output Block in Sub-Agent Prompts

**Files:**
- Modify: `references/implementer-prompt.md`
- Modify: `references/reviewer-prompt.md`
- Modify: `references/verifier-prompt.md`

### Step 3.1: Implementer — Output Section

Find the existing Output schema (the section that lists `STATUS:`, `SUMMARY:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:`, `COMMIT:`). Append the new requirement:

```markdown
### METHOD_AUDIT lines (v2.11 — required when STATUS=DONE)

For each skill in the "Required Skills" section that applies to this task, emit one line:

```
METHOD_AUDIT: <skill-short-name> applied [evidence-kv pairs]
METHOD_AUDIT: <skill-short-name> waived reason=<short rationale>
```

Skill short names:

| Skill | Short name | Evidence pairs |
|-------|-----------|----------------|
| `superpowers:test-driven-development` | `tdd` | `red="<command>"`, `green="<command>"`, `tests=<path[::test]>` |
| `superpowers:verification-before-completion` | `verification` | `commands_run=<comma-separated>` |
| Combined Reviewer pass (downstream) | `code-review-pass` | Filled by the orchestrator from Reviewer output; you should NOT emit this line. |

Examples:

```
METHOD_AUDIT: tdd applied red="pytest tests/test_foo.py::test_bar" green="pytest tests/test_foo.py::test_bar" tests=tests/test_foo.py::test_bar
METHOD_AUDIT: verification applied commands_run="pytest -q,ruff check src/"
METHOD_AUDIT: tdd waived reason=docs-only-task
```

**Fabricating evidence is grounds for re-dispatch.** Commands listed under `red` / `green` / `commands_run` must be commands you actually executed in this task. The orchestrator may sample-replay them or check tool-call history if a method_audit_violation is suspected. Fabricated evidence triggers a `method_audit_violation` learning-log event (severity=high).

**TDD waive conditions:** the only legitimate reasons are `docs-only-task`, `config-only-task`, `generated-only-task`. If you waive TDD with another reason, the orchestrator validator will fail the run.
```

### Step 3.2: Reviewer — Output Section

Find the existing Output schema. Append:

```markdown
### REVIEW_FINDINGS line (v2.11 — required)

Emit exactly one line in your final output:

```
REVIEW_FINDINGS: count=<N> locations=<file:line[,file:line...]>
```

OR when no findings:

```
REVIEW_FINDINGS: no-findings residual-risk="<one-sentence statement of what could still go wrong>"
```

The `residual-risk` statement should name a class of concern you considered and decided was acceptable (e.g., "no concurrency tests added but the change is single-threaded by construction"). A blank residual-risk is not acceptable — emit at least one sentence.

The orchestrator parses this line to populate `state.tasks.task_N.method_audit.applied` for the `code-review-pass` skill.
```

### Step 3.3: Verifier — Document `commands_run` and `category`

Find the result-JSON schema description. Update the `PASS` / `FAIL` shape:

```markdown
### Result JSON (v2.11)

```json
{
  "status": "PASS" | "FAIL" | "ESCALATE",
  "commands_run": ["<cmd1>", "<cmd2>", ...],
  "exit_codes": [0, 0, ...],
  "issues": [...],          // on FAIL
  "category": "docker_oom" | "gradle_daemon_disappearance" |
              "gradle_metaspace" | "node_heap_oom" |
              "service_unreachable" | "other",   // on FAIL; optional, default "other"
  "blocker": "...",         // on ESCALATE
  "options": {...}          // on ESCALATE
}
```

`commands_run` is the verification-evidence list. The orchestrator harvests it into `state.tasks.task_N.method_audit.applied` for the `verification-before-completion` skill.

`category` is optional on FAIL. When present, it must be one of the ENV_BLOCKER triage categories from `references/escalation-playbook.md`. Used to populate `root_cause_category` on the `verification_failure` learning-log event.
```

### Step 3.4: Re-Read and Commit

```bash
# Sanity re-read; ensure no inconsistencies introduced
grep -n "METHOD_AUDIT" references/implementer-prompt.md
grep -n "REVIEW_FINDINGS" references/reviewer-prompt.md
grep -n "commands_run" references/verifier-prompt.md
python3 evals/check_skill_contract.py --skill SKILL.md
```

Commit:

```text
feat: require structured method-audit evidence from sub-agents
```

## Task 4: SubagentStop Hook Extension

**Files:**
- Modify: `references/hooks/check-implementer-output.sh.template`

### Step 4.1: Add METHOD_AUDIT Check

The template reads the sub-agent's final output (provided by Claude Code via `$CLAUDE_TOOL_INPUT` or similar — confirm the exact env var used by the existing checks; that pattern is the canonical reference here). After the existing STATUS / SUMMARY / FILES_CHANGED / FILES_TEST_CHANGED block, add:

```bash
# v2.11: METHOD_AUDIT block required on STATUS=DONE
if [[ "$STATUS" == "DONE" ]]; then
  if ! grep -qE '^METHOD_AUDIT:' <<<"$OUTPUT"; then
    cat >&2 <<EOF
SubagentStop hook: missing METHOD_AUDIT block.
STATUS=DONE requires at least one METHOD_AUDIT: line.
See references/implementer-prompt.md "METHOD_AUDIT lines" section.
EOF
    exit 2
  fi

  # If any test files were touched, require either tdd applied or tdd waived
  if [[ -n "$FILES_TEST_CHANGED" && "$FILES_TEST_CHANGED" != "[]" ]]; then
    if ! grep -qE '^METHOD_AUDIT: tdd (applied|waived)' <<<"$OUTPUT"; then
      cat >&2 <<EOF
SubagentStop hook: test files changed but no METHOD_AUDIT: tdd line.
Either emit METHOD_AUDIT: tdd applied red=... green=... tests=...
or METHOD_AUDIT: tdd waived reason=<docs-only-task|config-only-task|generated-only-task>.
EOF
      exit 2
    fi
  fi

  # Sanity: tdd applied must have all three evidence keys
  if grep -qE '^METHOD_AUDIT: tdd applied' <<<"$OUTPUT"; then
    line=$(grep -E '^METHOD_AUDIT: tdd applied' <<<"$OUTPUT" | head -1)
    for key in red green tests; do
      if ! grep -qE "${key}=" <<<"$line"; then
        echo "SubagentStop hook: METHOD_AUDIT: tdd applied missing key '${key}=' on line: $line" >&2
        exit 2
      fi
    done
  fi
fi
```

The shell variable names (`STATUS`, `OUTPUT`, `FILES_TEST_CHANGED`) must match what the existing template already parses. If the existing template parses differently (e.g., line-by-line into associative arrays), match its style.

### Step 4.2: Test Hook Behavior

Run synthetic inputs:

```bash
# Case 1: well-formed DONE with audit
cat > /tmp/in1.txt <<'EOF'
STATUS: DONE
SUMMARY: implemented foo
FILES_CHANGED: src/foo.py
FILES_TEST_CHANGED: tests/test_foo.py
COMMIT: abc1234
METHOD_AUDIT: tdd applied red="pytest tests/test_foo.py" green="pytest tests/test_foo.py" tests=tests/test_foo.py
METHOD_AUDIT: verification applied commands_run="pytest -q"
EOF

# Case 2: DONE with test files but no METHOD_AUDIT
cat > /tmp/in2.txt <<'EOF'
STATUS: DONE
SUMMARY: implemented foo
FILES_CHANGED: src/foo.py
FILES_TEST_CHANGED: tests/test_foo.py
COMMIT: abc1234
EOF

# Case 3: DONE with malformed audit (missing keys)
cat > /tmp/in3.txt <<'EOF'
STATUS: DONE
SUMMARY: implemented foo
FILES_CHANGED: src/foo.py
FILES_TEST_CHANGED: tests/test_foo.py
COMMIT: abc1234
METHOD_AUDIT: tdd applied red="pytest"
EOF

# Adapt to the hook's actual invocation contract; the test runner script
# will need to set the env variables the real hook reads.
CLAUDE_TOOL_INPUT="$(cat /tmp/in1.txt)" bash references/hooks/check-implementer-output.sh.template
echo "case1 exit: $?"   # expect 0
CLAUDE_TOOL_INPUT="$(cat /tmp/in2.txt)" bash references/hooks/check-implementer-output.sh.template
echo "case2 exit: $?"   # expect 2
CLAUDE_TOOL_INPUT="$(cat /tmp/in3.txt)" bash references/hooks/check-implementer-output.sh.template
echo "case3 exit: $?"   # expect 2
```

### Step 4.3: Commit

```text
feat: enforce method-audit block via SubagentStop hook
```

## Task 5: Method-Audit Validator + Phase 2 Gate

**Files:**
- Create: `scripts/validate_method_audit.py`
- Modify: `SKILL.md` (Phase 2 Step 1.5, Guardrails)

### Step 5.1: Create `scripts/validate_method_audit.py`

```python
#!/usr/bin/env python3
"""Validate method_audit fields on a completed kws-claude-multi-agent-executor run.

Exit 0: all completed tasks have required methods applied or waived.
Exit 1: at least one task is missing a required method without a waiver.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXECUTABLE_REQUIRED = ["test-driven-development", "verification-before-completion", "code-review-pass"]
DOCS_ONLY_REQUIRED = ["verification-before-completion"]


def _is_docs_only(task: dict[str, Any]) -> bool:
    files = task.get("files", [])
    files_test = task.get("files_test")
    if files_test == []:
        return True
    if files_test is None and files and all(str(f).endswith(".md") for f in files):
        return True
    return False


def _required_for(task: dict[str, Any]) -> set[str]:
    return set(DOCS_ONLY_REQUIRED if _is_docs_only(task) else EXECUTABLE_REQUIRED)


def _audit(task_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
    if task.get("status") != "COMPLETE":
        return None
    audit = task.get("method_audit") or {}
    required = _required_for(task)
    applied = {entry.get("skill") for entry in (audit.get("applied") or [])}
    waived = {entry.get("skill") for entry in (audit.get("waived") or [])}
    missing = sorted(required - applied - waived)
    return {
        "task_id": task_id,
        "risk": task.get("risk"),
        "files_test": task.get("files_test"),
        "required": sorted(required),
        "applied": sorted(applied),
        "waived": sorted(waived),
        "missing": missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--active-plan", default="auto",
                    choices=["plan1", "plan2", "auto"])
    args = ap.parse_args()

    state = json.loads(args.state.read_text(encoding="utf-8"))
    active = args.active_plan
    if active == "auto":
        active = state.get("active_plan", "plan1")

    if active == "plan2":
        tasks = (state.get("plan2_state") or {}).get("tasks") or {}
    else:
        tasks = state.get("tasks") or {}

    failures = []
    audited = []
    for task_id, task in tasks.items():
        audit = _audit(task_id, task)
        if audit is None:
            continue
        audited.append(audit)
        if audit["missing"]:
            failures.append(audit)

    payload = {
        "passed": failures == [],
        "active_plan": active,
        "audited_count": len(audited),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
```

Mark executable:

```bash
chmod +x scripts/validate_method_audit.py
```

### Step 5.2: Insert Phase 2 Step 1.5 in `SKILL.md`

Locate Phase 2 in `SKILL.md`. The current sequence is:

- Step -1: Cross-Plan Trigger
- Step 0: LOW Batch Verifier Sweep
- Step 1: Final Docs Updater
- Step 2: Generate Final Summary Report

Insert between Step 1 and Step 2:

```markdown
### Step 1.5: Method Audit Validation (v2.11)

After the Final Docs Updater commit and before generating the Final Summary Report:

```bash
python3 <skill_dir>/scripts/validate_method_audit.py \
  --state <worktree>/.orchestrator/state.json
```

Parse the JSON output:

- `"passed": true` → proceed to Step 2.
- `"passed": false` → for each entry in `failures`, write a learning-log candidate event:

  ```json
  {
    "schema_version": "1",
    "phase": "phase_2",
    "risk_tier": "high",
    "event_type": "method_audit_violation",
    "severity": "high",
    "execution": {"task_id": "<id>", "issue_key": "method_audit_missing"},
    "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
    "summary": "Task <id> missing required methods: <missing list>",
    "context": {
      "user_intent": "Validate that required disciplines were applied.",
      "agent_expectation": "All COMPLETE tasks emit method_audit evidence.",
      "actual_outcome": "Missing methods: <list>",
      "root_cause": "Sub-agent did not emit METHOD_AUDIT lines or evidence was incomplete.",
      "evidence": [{"kind": "missing_methods", "value": "<list>"}]
    },
    "improvement": {"target": "references/implementer-prompt.md",
                    "proposal": "Strengthen METHOD_AUDIT requirement or hook check.",
                    "experiment_link": null},
    "privacy": {"redacted": true, "notes": "Skill names only."}
  }
  ```
  Then halt:

  ```
  Method audit FAILED for tasks: <comma-separated list>.

  To resolve, either:
    - Re-dispatch the failing task(s) with explicit instructions to emit
      METHOD_AUDIT: lines (see references/implementer-prompt.md).
    - If a method is genuinely not applicable, edit
      state.tasks.<id>.method_audit.waived in state.json with a reason,
      then re-run Phase 2.

  Validator output:
  <pretty-printed validator JSON>
  ```

  Do NOT call `close-run` — the run remains alive for the user's resolution. Standard hard-halt block applies.
```

### Step 5.3: Update Guardrails Table

Add new rows to the Guardrails table in `SKILL.md`:

```markdown
| **Method audit must pass before Phase 2 close-run** | Phase 2 Step 1.5 runs `scripts/validate_method_audit.py`. A task is `applied` only when it has evidence references (RED command, GREEN command, commands_run, findings_count). FAIL halts before close-run; user re-dispatches or edits `state.tasks.<id>.method_audit.waived` with a reason. |
| **Method audit fields populated at Phase 1 Step 4** | Orchestrator parses `METHOD_AUDIT:` from Implementer, `REVIEW_FINDINGS:` from Combined Reviewer, `commands_run` from Verifier result JSON. Written under the active task tree (`state.tasks` or `state.plan2_state.tasks` per `active_plan`). |
| **TDD waive reasons are restricted** | `METHOD_AUDIT: tdd waived` accepts only `reason=docs-only-task`, `config-only-task`, or `generated-only-task`. Other reasons fail validation. |
```

### Step 5.4: Commit

```text
feat: gate Phase 2 close-run on method-audit validation
```

## Task 6: SKILL.md Phase 1 Step 4 Audit Population

**Files:**
- Modify: `SKILL.md` (Phase 1 Step 4)

### Step 6.1: Extend Phase 1 Step 4 Step 2

Locate Phase 1 Step 4 "Agent Cleanup" → sub-step 2 "Update state file". The current task entry shape has fields ending with `timing`. Add `method_audit` at the same level:

```json
   "task_N": {
     "status": "COMPLETE",
     "risk": "<level>",
     "complexity": "<SMALL|MEDIUM|LARGE>",
     "files": ["<file1>", "..."],
     "files_test": ["<test_file1>", "..."],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "spec_clarifications": 0,
     "spec_score": <float>,
     "quality_score": <float>,
     "review_tier": "PASS | WARN",
     "method_audit": {
       "required": ["test-driven-development", "verification-before-completion", "code-review-pass"],
       "applied": [
         {"skill": "test-driven-development",
          "evidence": {"red": "<cmd>", "green": "<cmd>", "tests": ["<path>"]}},
         {"skill": "verification-before-completion",
          "evidence": {"commands_run": ["<cmd1>", "<cmd2>"]}},
         {"skill": "code-review-pass",
          "evidence": {"findings_count": <N>, "locations": ["<file:line>"]}}
       ],
       "missing": [],
       "waived": []
     },
     "timing": { ... }
   }
```

### Step 6.2: Add Population Sub-Step

Insert before the `task_summaries` write:

```markdown
**v2.11 — Populate `method_audit`:**

1. Read the Implementer's final output (captured in this turn's Agent tool result). Parse each `METHOD_AUDIT:` line:
   - `<skill> applied <kv pairs>` → append `{"skill": <skill>, "evidence": <parsed kv>}` to `method_audit.applied`.
   - `<skill> waived reason=<text>` → append `{"skill": <skill>, "reason": <text>}` to `method_audit.waived`.
2. Read the Combined Reviewer's output. Parse the `REVIEW_FINDINGS:` line:
   - `count=<N> locations=<list>` → append `{"skill": "code-review-pass", "evidence": {"findings_count": <N>, "locations": <list>}}` to `method_audit.applied`.
   - `no-findings residual-risk=<text>` → append `{"skill": "code-review-pass", "evidence": {"findings_count": 0, "residual_risk": <text>}}` to `method_audit.applied`.
3. Read the Verifier result JSON (if dispatched — Phase 1 Step 3 for MID/HIGH; deferred to Phase Transition T1 or Phase 2 Step 0 for LOW). Append `{"skill": "verification-before-completion", "evidence": {"commands_run": <list>}}` to `method_audit.applied`. For LOW tasks awaiting batch verification, write the populator note `pending_batch_verification: true` in `method_audit` and resolve it in T1 / Phase 2 Step 0.
4. Compute `required` from the docs-only heuristic: `files_test == []` OR (`files_test` missing AND all `files` end with `.md`) → `["verification-before-completion"]`. Else → `["test-driven-development", "verification-before-completion", "code-review-pass"]`.
5. Compute `missing = required - applied_skills - waived_skills`. (This is informational — Phase 2 Step 1.5 is authoritative.)
```

### Step 6.3: Commit

```text
feat: populate method_audit during Agent Cleanup
```

## Task 7: ENV_BLOCKER Triage Categories

**Files:**
- Modify: `references/escalation-playbook.md`
- Modify: `references/common-mistakes.md`
- Modify: `references/learning-log.md`

### Step 7.1: Extend `escalation-playbook.md`

After the existing 4-step ENV_BLOCKER triage, add:

```markdown
## ENV_BLOCKER Category Triage (v2.11)

When the 4-step generic triage produces a clear root cause, classify it into a category. The category becomes the `root_cause_category` field on the `verification_failure` learning event.

| Category | Symptom signature | Diagnostic | Resolution |
|----------|-------------------|------------|------------|
| `docker_oom` | Container exit code 137, "Killed" in build log, BuildKit step terminated without error message after long pause | `docker inspect <container-id> --format '{{.State.OOMKilled}}'` — `true` confirms; `docker stats` snapshot if container still alive | Increase Docker Desktop memory or set `--memory` flag higher; do NOT re-classify as compile failure |
| `gradle_daemon_disappearance` | "Daemon disappeared", "Gradle build daemon disappeared unexpectedly", "Could not connect to Gradle daemon" | Read `~/.gradle/daemon/<version>/daemon-*.out.log`; last 50 lines reveal sub-cause | If log says OOMError → `gradle_metaspace` (below) or heap; if "JVM crashed" → daemon crash, retry once with `--no-daemon` |
| `gradle_metaspace` | "java.lang.OutOfMemoryError: Metaspace" in daemon log or stderr | grep daemon log for `Metaspace` | Set `org.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=1g` in `gradle.properties`; retry |
| `node_heap_oom` | "JavaScript heap out of memory", "FATAL ERROR: Reached heap limit Allocation failed" | `node --version`; `echo $NODE_OPTIONS` | `export NODE_OPTIONS=--max-old-space-size=4096`; retry |
| `service_unreachable` | "ECONNREFUSED", "connection refused", "no route to host", "host unreachable" | `nc -z <host> <port>`; `curl --max-time 2 <url>` | Start the service or escalate to user with the unreachable host:port pair |
| `other` | None of the above patterns match | n/a | Fall through to standard SKIPPED with full diagnostic log |

**Recording:** When a category resolves an ENV_BLOCKER, write the resolution to the learning log via a candidate event with `event_type: "verification_failure"` and `context.root_cause_category: "<category>"`. The orchestrator's standard Phase 1 Step 3.5 scan forwards it.

**Never re-classify based on a category:** `docker_oom` is not a code defect, regardless of how the build error reads in the log. If the category is established, do not Implementer-retry as a code issue.
```

### Step 7.2: Update `references/learning-log.md`

In the `verification_failure` event-type section, add:

```markdown
### Optional fields (v2.11)

- `context.root_cause_category`: one of `docker_oom`, `gradle_daemon_disappearance`, `gradle_metaspace`, `node_heap_oom`, `service_unreachable`, `other`. Set when ENV_BLOCKER triage from `references/escalation-playbook.md` identifies a category. Absent or `other` means uncategorized.
```

### Step 7.3: Update `common-mistakes.md`

Append two entries:

```markdown
### Docker exit 137 mistaken for compile failure

When a multi-stage Docker build fails after the compilation step with no compiler error and an exit code of 137, the container was OOM-killed by the kernel, not the build. Check `docker inspect ... .State.OOMKilled`. Re-running with more memory resolves it; treating it as a compile failure burns Implementer retries.

### Gradle daemon disappearance without category check

"Daemon disappeared" is a symptom, not a cause. The cause lives in `~/.gradle/daemon/<version>/daemon-*.out.log`. Categorize as `gradle_metaspace`, OOM, or daemon crash *before* assuming the project's code broke the daemon.
```

### Step 7.4: Commit

```text
docs: expand env_blocker triage categories
```

## Task 8: Local-Env Preflight

**Files:**
- Modify: `SKILL.md` (insert Phase 0 Step 4.7)
- Modify: `references/common-mistakes.md`

### Step 8.1: Insert Phase 0 Step 4.7

Locate Phase 0 in `SKILL.md`. The current sequence has Step 4 (Assign risk levels) → Step 5 (Take baseline test snapshot). Insert between them:

```markdown
### Step 4.7: Local-env preflight (v2.11)

After risk assignment, before baseline test. Detection-only — never halts, never auto-copies.

1. **Unfilled local-config counterpart scan:**
   ```bash
   cd <worktree_path>
   for tmpl in $(find . -maxdepth 3 -type f \( -name '*.example' -o -name '*.template' -o -name '*.dist' \) 2>/dev/null); do
     real="${tmpl%.example}"
     real="${real%.template}"
     real="${real%.dist}"
     if [ ! -e "$real" ] && git check-ignore -q "$real" 2>/dev/null; then
       echo "MISSING_LOCAL_CONFIG: counterpart=$real template=$tmpl"
     fi
   done
   ```
   Each `MISSING_LOCAL_CONFIG:` line becomes a warning entry:
   ```json
   {"kind": "missing_local_config", "file": "<counterpart>", "template": "<template>",
    "suggestion": "Copy <template> to <counterpart> and fill in the local values",
    "detected_at": "<iso8601>"}
   ```

2. **Stale-dependency detection** — check each manifest/lockfile pair against its install marker:
   | Manifest | Lockfile | Install marker |
   |----------|----------|----------------|
   | `package.json` | `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` | `node_modules/.package-lock.json` |
   | `pyproject.toml` | `poetry.lock` / `uv.lock` | `.venv/pyvenv.cfg` or `venv/pyvenv.cfg` |
   | `Cargo.toml` | `Cargo.lock` | `target/.rustc_info.json` |
   | `build.gradle` / `build.gradle.kts` | `gradle/wrapper/gradle-wrapper.properties` | `.gradle/<version>/` or `build/` |

   For each pair: if lockfile mtime > install-marker mtime + 1s OR install-marker missing while lockfile exists → warning entry:
   ```json
   {"kind": "dependencies_likely_stale", "manifest": "<manifest>", "lockfile": "<lockfile>",
    "suggestion": "Run install before baseline (e.g., `npm install`, `poetry install`, `cargo fetch`).",
    "detected_at": "<iso8601>"}
   ```

3. **Record into state.json:**
   ```json
   "preflight_warnings": [<warning entries>]
   ```
   Always present; empty list when clean.

4. **One-line summary to user:**
   - clean → `Preflight: clean`
   - warnings → `Preflight: <N> warnings (see state.preflight_warnings)` followed by the bulleted list with `kind` + `file` + `suggestion`.

5. Never halt on preflight. ENV_BLOCKER triage (`references/escalation-playbook.md`) cross-references `state.preflight_warnings` when baseline or task tests fail — a `dependencies_likely_stale` warning matches a `module not found` symptom and short-circuits dependency-install triage.
```

### Step 8.2: Cross-Reference from Escalation Playbook

In `escalation-playbook.md` ENV_BLOCKER Step 2 (dependency check), add a one-liner:

```markdown
   **Before running install:** check `state.preflight_warnings` for `dependencies_likely_stale` — if present, the suggested install command is pre-identified; run it directly.
```

### Step 8.3: Add Common-Mistakes Entry

```markdown
### Missing local-config counterpart causes mystery baseline failures

A worktree freshly created from `git worktree add` inherits the tracked files only. If `.env.example` is tracked but `.env` is gitignored and absent, baseline tests reading `process.env.SECRET_KEY` will fail before any task touches code. Phase 0 Step 4.7 surfaces these as `missing_local_config` warnings; honor them before treating baseline failures as regressions.
```

### Step 8.4: Commit

```text
feat: add framework-agnostic local-env preflight
```

## Task 9: Resource-Key Plan Annotation + Partition

**Files:**
- Modify: `SKILL.md` (Phase 0 Step 6 partition algorithm)
- Modify: `references/plan-reviewer-prompt.md`

### Step 9.1: Document the Annotation in SKILL.md Phase 0 Step 6

Locate Phase 0 Step 6 "Build dependency graph and identify compaction points" → the sub-section that builds `execution_plan`. After the existing partition rules (file-disjointness merge, `serial: true` check), add:

```markdown
**v2.11 — `resource_key` partition rule:**

A task may declare `**Resource Key:** <slug>` in its task body (similar to `**Files:**`). Slug is lowercased and whitespace-stripped. Examples: `gradle-test-output`, `db-port-5432`, `playwright-browser`.

After file-disjointness merging, before finalizing the wave's parallel groups:

1. Build a `resource_key → [task_ids]` map for tasks in this wave.
2. For each key with ≥ 2 task IDs in the same wave:
   - Move each affected task to its own singleton group within the wave. If a multi-task group contained two collision-tagged tasks, split into singletons.
   - Annotate each resulting singleton group in `state.execution_plan` with `"serialization_reason": "resource_key=<key>"`.

The wave still respects the file-disjointness invariant (groups within a wave never share files). Splits only widen serialization — they never merge file-overlapping tasks.

Tasks with no `Resource Key:` block are unaffected. The annotation is opt-in.
```

### Step 9.2: Extend Plan Reviewer

In `references/plan-reviewer-prompt.md`, locate the "Audit Rules" section. Add:

```markdown
### Resource-Key Collision (WARN)

For each task, parse `**Resource Key:** <slug>` if present (case-insensitive header match; slug lowercased; whitespace stripped).

Using the supplied `execution_plan` YAML (waves and groups), identify any wave with ≥ 2 tasks sharing a non-null `resource_key`.

For each such wave, emit:

```json
{
  "severity": "WARN",
  "category": "resource_key_collision",
  "task_ids": ["<id1>", "<id2>"],
  "description": "Tasks <id1>, <id2> share resource_key '<key>' in wave <N>. They will be forced into separate parallel groups (serial execution within the wave).",
  "suggested_fix": "Either accept the serialization (no action) or add an explicit dependency to push one task to a later wave."
}
```

WARN only — never BLOCKER. The runtime partition rule (Phase 0 Step 6) handles correctness automatically; the WARN exists so the plan author is aware that the declared parallelism is reduced.
```

### Step 9.3: Commit

```text
feat: honor plan resource_key in parallel partition
```

## Task 10: Docs, History, Architecture, Experiment Folder, Final Verification

**Files:**
- Modify: `HISTORY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `evals/check_skill_contract.py`
- Modify: `SKILL.md` (Guardrails table — done in Task 5; here only verify completeness)
- Create: `docs/experiments/v2.11-method-audit-and-hardening/README.md`
- Create: `docs/experiments/v2.11-method-audit-and-hardening/JOURNAL.md`

### Step 10.1: HISTORY.md Entry

Prepend a v2.11 section:

```markdown
## v2.11 — Method audit and codex-cross-pollinated hardening (YYYY-MM-DD)

Five features, drawn from sibling `kws-codex-plan-executor` learning-log review (commit `1d10f13`) plus an MAE-internal gap analysis:

1. **Phase Method Audit** — `state.tasks.<id>.method_audit = {required, applied, missing, waived}`. Validated at Phase 2 Step 1.5 by `scripts/validate_method_audit.py` before close-run. SubagentStop hook gates Implementer output. Closes the gap between MAE's *required* TDD / review / verification disciplines and actual *validation* of them.
2. **Learning-log outcome coherence** — `scripts/append_learning_event.py close-run` now rewrites the matching `index.jsonl` row's `outcome` atomically. New `resolve-outcome` subcommand returns the authoritative outcome (final.json > meta.json > index.jsonl).
3. **ENV_BLOCKER triage categories** — five named root-cause buckets (`docker_oom`, `gradle_daemon_disappearance`, `gradle_metaspace`, `node_heap_oom`, `service_unreachable`) added to `references/escalation-playbook.md`. Recorded as optional `root_cause_category` on `verification_failure` learning events.
4. **Local-env preflight** — new Phase 0 Step 4.7 detects unfilled `*.example` / `*.template` / `*.dist` counterparts and stale dependency manifests. Records warnings to `state.preflight_warnings`; never halts, never auto-copies.
5. **Resource-key serialization** — plan tasks may declare `**Resource Key:** <slug>`; Phase 0 Step 6 partition forces same-key tasks into different parallel groups within a wave. Plan Reviewer (Step 6.5) emits a WARN on collisions.

Backward compatible. No state-schema breaking changes; new fields are additive.
```

### Step 10.2: ARCHITECTURE.md Sections

Add three sections:

```markdown
## Method Audit (v2.11)

MAE requires sub-agents to invoke `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and code-review-pass disciplines, but prior to v2.11 it did not verify the disciplines were actually applied. v2.11 adds:

- Structured output blocks (`METHOD_AUDIT:`, `REVIEW_FINDINGS:`, Verifier `commands_run`) emitted by sub-agents.
- Orchestrator populator at Phase 1 Step 4 — parses and writes `state.tasks.<id>.method_audit`.
- SubagentStop hook (`references/hooks/check-implementer-output.sh.template`) — runtime gate on Implementer output shape.
- Validator script (`scripts/validate_method_audit.py`) — semantic gate at Phase 2 Step 1.5 before close-run.

Required-methods derivation: executable task → TDD + verification + code-review-pass; docs-only task (`files_test == []` or all `.md` files) → verification only. TDD waiver reasons are restricted to `docs-only-task`, `config-only-task`, `generated-only-task`.

Fabricated evidence is grounds for re-dispatch and a `method_audit_violation` learning-log event (severity=high).

## Local-Env Preflight (v2.11)

Phase 0 Step 4.7 runs between risk assignment and baseline test. Two detection rules:

1. **Unfilled local-config counterpart** — for every `*.example` / `*.template` / `*.dist` in the worktree, the suffix-stripped counterpart is checked for existence + gitignored status.
2. **Stale dependencies** — manifest/lockfile/install-marker mtime triple per language ecosystem.

Both are detection-only. Warnings are written to `state.preflight_warnings`. The orchestrator does not auto-copy gitignored files (potential secret / machine-specific path leakage).

ENV_BLOCKER triage cross-references preflight warnings before running generic dependency install.

## Resource-Key Serialization (v2.11)

A task may declare `**Resource Key:** <slug>` in its plan body. Phase 0 Step 6 partition algorithm builds the resource-key map per wave and splits any same-key collisions into singleton groups. The wave's file-disjointness invariant is preserved; only serialization widens.

`state.execution_plan` group entries record `serialization_reason: "resource_key=<key>"` when applied.

Plan Reviewer (Phase 0 Step 6.5) emits WARN issues for same-wave collisions so the plan author sees the reduced parallelism. WARN, not BLOCKER — runtime correctness is automatic.
```

### Step 10.3: README.md One-Liner

Under "Recent changes" or equivalent:

```markdown
- **v2.11** — Method audit gate at Phase 2; ENV_BLOCKER triage categories; local-env preflight; `resource_key` plan annotation; learning-log outcome coherence.
```

### Step 10.4: Extend `evals/check_skill_contract.py`

Add assertions:

```python
REQUIRED_WORDING = [
    # v2.11 additions
    ("Phase 1 Step 4", "method_audit"),
    ("Phase 2 Step 1.5", "method_audit"),
    ("Phase 0 Step 4.7", "Local-env preflight"),
    ("Phase 0 Step 6", "resource_key"),
    ("Guardrails", "Method audit must pass before Phase 2 close-run"),
    ("Guardrails", "Resource-key collisions force serialization in same wave"),
]
```

Implementation detail: the existing eval likely already has a `REQUIRED_WORDING` or equivalent list of `(section_anchor, substring)` tuples. Append the new tuples; do not refactor.

### Step 10.5: Experiment README + JOURNAL

```bash
cp docs/experiments/_template/README.md \
   docs/experiments/v2.11-method-audit-and-hardening/README.md
cp docs/experiments/_template/JOURNAL.md \
   docs/experiments/v2.11-method-audit-and-hardening/JOURNAL.md
```

Edit `README.md`:

```markdown
# v2.11 — Method Audit + Codex-Inspired Hardening

**Status**: In progress
**Branch**: `<your branch>`
**Production baseline**: v2.10.1

## Goal

Close MAE's gap between *required* sub-agent disciplines (TDD, review, verification) and actual *validation* of those disciplines, plus four smaller hardening items from `kws-codex-plan-executor` commit `1d10f13`.

## Hypothesis

Adding structured `METHOD_AUDIT:` evidence to sub-agent output + an orchestrator-side validator will catch the case where a task ships `COMPLETE` without TDD evidence, without adding per-task overhead beyond ~50 tokens of structured output and ~5 grep operations.

## Status / quick links

- [PLAN.md](./PLAN.md) — detailed implementation plan
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) — concrete code/edit guidance per task
- [JOURNAL.md](./JOURNAL.md) — chronological log

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| Task 1 (Fixtures) | Not started | |
| Task 2 (Outcome resolver) | Not started | |
| Task 3 (Sub-agent prompts) | Not started | |
| Task 4 (Hook) | Not started | |
| Task 5 (Validator + gate) | Not started | |
| Task 6 (Populator) | Not started | |
| Task 7 (ENV_BLOCKER categories) | Not started | |
| Task 8 (Preflight) | Not started | |
| Task 9 (Resource key) | Not started | |
| Task 10 (Docs + verify) | Not started | |

## Decisions index

(One line per ADR. Add as you make decisions.)

## Findings index

(One line per finding doc.)
```

`JOURNAL.md` — start with a single entry:

```markdown
# Journal

## YYYY-MM-DD — Plan + implementation docs created

Wrote `PLAN.md` and `IMPLEMENTATION.md` based on sibling commit `1d10f13`
(`kws-codex-plan-executor`) plus MAE-internal gap analysis. Five features queued
across 10 tasks. No code changes yet.
```

### Step 10.6: Final Verification

```bash
cd /Users/kws/source/private/Archive/skills/kws-claude-multi-agent-executor

python3 evals/check_method_audit.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_doc_freshness.py
python3 scripts/append_learning_event.py resolve-outcome --help
python3 scripts/validate_method_audit.py --help

# Confirm hook script parses cleanly
bash -n references/hooks/check-implementer-output.sh.template

# Markdown lint pass (optional but recommended)
markdownlint docs/experiments/v2.11-method-audit-and-hardening/ 2>/dev/null || \
  echo "markdownlint not installed; skipped"
```

All evals must print `"passed": true`. Helper `--help` commands must exit 0 with usage output.

### Step 10.7: Commit

```text
chore: document v2.11 method audit and codex-inspired hardening
```

## Cross-Task Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Sub-agents fabricate `METHOD_AUDIT: tdd applied` evidence without actually running TDD | The hook checks shape only. Fabrication is a known residual risk. Mitigation: orchestrator may sample-replay commands listed in `evidence.red` and confirm exit code matches (failing). Out of scope for v2.11; tracked as a v2.12 candidate. |
| `index.jsonl` rewrite races with concurrent `init-run` from a parallel orchestrator run | `fcntl.flock` on the index file across the read+rewrite cycle. Cross-process safe on POSIX. |
| Local-env preflight false positives flood the user (e.g., monorepo with many `*.example`) | Limit `find` depth to 3 and add `--exclude` for `node_modules`, `.venv`, `target`, `build`. Document the depth limit in SKILL.md. |
| `resource_key` collision in a single wave with all tasks marked WARN — plan author ignores → still serial → wasted wall-clock | WARN is intentional. The runtime forces correctness; the WARN is informational. No mitigation needed; user can re-plan if WARN density is high. |
| Hook script `check-implementer-output.sh.template` regex too strict and rejects valid TDD evidence formats | Test the three synthetic inputs in Task 4 Step 4.2 before commit. Add at least one fixture covering multi-test `tests=` lists with commas. |

## Self-Review Notes

- The implementation order ensures every layer is tested before the next layer depends on it (fixtures first, helper second, validator after population).
- Method audit fields are entirely additive — older runs without `method_audit` are skipped by the validator (since they have no `COMPLETE` tasks in the v2.11 sense). This is intentional; the gate applies prospectively.
- The hook (Task 4) and validator (Task 5) form defense-in-depth. Either alone could be bypassed (hook by disabling settings.json, validator by editing state.json); together they require coordinated bypass.
- No changes to the chain-resume protocol, P2 parallel sub-flow, or Plan 2 cross-plan trigger. The `active_plan` pointer rule is preserved throughout (validator and populator both consult it).
- Documentation updates in Task 10 are last-not-first so HISTORY.md entries can reference the actual commit shas from Tasks 1–9.
- All evals are deterministic — no live subprocess runs, no network, no real `claude -p` invocations during eval. Live integration testing happens via the existing `bash evals/run.sh` (out of scope for this plan; covered by the existing v2.10.1 fixture suite).
