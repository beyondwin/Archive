# CPE v2.22 Operational Run Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recent CPE runs easier to trust, resume, and audit by recording effective delegation policy, richer bootstrap preflight evidence, execution-worktree provenance, and read-only run-quality summaries.

**Architecture:** Preserve the existing CPE model: repository mutations stay in `~/.codex/worktrees/<run_id>`, state stays in `~/.codex/orchestrator/<run_id>`, and validators remain the completion gate. Add optional v2.22 state fields, deterministic scripts, and eval coverage before tightening documentation.

**Tech Stack:** Python 3 standard library, JSON state under `~/.codex/orchestrator/<run_id>`, Markdown docs, existing CPE deterministic eval harness.

---

## Source Documents

- Spec: `skills/kws-codex-plan-executor/docs/experiments/v2.22-operational-run-quality/IMPLEMENTATION.md`
- Skill contract: `skills/kws-codex-plan-executor/SKILL.md`
- State validator: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Dispatch preflight: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Local env preflight: `skills/kws-codex-plan-executor/scripts/preflight_local_env.py`
- Run inspection: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`

## Scope

Included:

- Effective delegation policy fields and deterministic dispatch fallback.
- Bootstrap preflight report with suggested commands and capability detection.
- Run-quality inspection for recent, stale, and validation-drifted states.
- Optional v2.22 state schema validation.
- Deterministic evals and docs updates.

Excluded:

- Real subagent spawning implementation.
- Automatic dependency install/bootstrap execution.
- Automatic mutation of stale historical run state.
- Changing the default `mode=interactive`.
- Widening task write globs.

## File Structure

Create:

- `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py` - deterministic tests for v2.22 state validation and inspection summaries.

Modify:

- `skills/kws-codex-plan-executor/scripts/parse_invocation_args.py` - expose explicit delegation intent.
- `skills/kws-codex-plan-executor/evals/check_invocation_args.py` - cover explicit delegation intent and default-source reporting.
- `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py` - accept spawn policy args and emit deterministic policy fallback.
- `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py` - cover explicit-request-required local fallback.
- `skills/kws-codex-plan-executor/scripts/preflight_local_env.py` - add bootstrap plan and capability detection.
- `skills/kws-codex-plan-executor/evals/check_local_env_preflight.py` - cover pnpm, bun, Gradle, Android/Rust/AgentLens capability fields.
- `skills/kws-codex-plan-executor/scripts/inspect_runs.py` - add recent/all-plans/stale/validation/quality/jsonl report modes.
- `skills/kws-codex-plan-executor/evals/check_inspect_runs.py` - cover new report modes while keeping old plan lookup behavior.
- `skills/kws-codex-plan-executor/scripts/validate_state.py` - validate optional v2.22 fields.
- `skills/kws-codex-plan-executor/evals/check_state_schema.py` - add v2.22 state fixtures.
- `skills/kws-codex-plan-executor/evals/static_execution_runner.py` - emit v2.22 fields in deterministic fixture state.
- `skills/kws-codex-plan-executor/evals/run.sh` - run the new eval.
- `skills/kws-codex-plan-executor/SKILL.md` - add operational run-quality invariants.
- `skills/kws-codex-plan-executor/README.md` - list new eval and design note.
- `skills/kws-codex-plan-executor/ARCHITECTURE.md` - describe effective delegation policy and worktree provenance.
- `skills/kws-codex-plan-executor/HISTORY.md` - add v2.22.0 entry.
- `skills/kws-codex-plan-executor/references/state-schema.md` - document v2.22 optional fields.
- `skills/kws-codex-plan-executor/references/local-env-preflight.md` - document bootstrap plan/capabilities.
- `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md` - document spawn-policy fallback.
- `skills/kws-codex-plan-executor/docs/state-and-logging.md` - document `run_quality` and provenance fields.
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md` - list `check_operational_run_quality.py`.
- `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md` - record v2.22 deferrals.
- `skills/kws-codex-plan-executor/docs/verification-log.md` - append verification evidence when implementation completes.

## Acceptance Criteria

- `python3 evals/check_operational_run_quality.py` passes.
- Existing deterministic checks still pass through `bash evals/run.sh`.
- `python3 -m py_compile scripts/*.py evals/*.py` passes.
- `bash -n evals/run.sh` passes.
- `git diff --check` passes.
- Existing single-plan `inspect_runs.py --plan ...` behavior remains compatible.
- New `inspect_runs.py --all-plans --recent 40 --validate-state --quality-report` returns aggregate summary fields without mutating state.
- Finished v2.22 state fixtures validate, while older v2.19-v2.21 fixtures still validate.

## Tasks

### Task 1: Add Invocation Delegation Intent

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/parse_invocation_args.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_invocation_args.py`

- [ ] **Step 1: Write failing eval assertions**

In `evals/check_invocation_args.py`, add these checks after the existing default
subagent check:

```python
    checks["default_has_no_explicit_delegation_intent"] = (
        default_result.returncode == 0
        and default_payload.get("intent", {}).get("explicit_delegation_request") is False
        and default_payload.get("intent", {}).get("delegation_hint") is None
    )
    if not checks["default_has_no_explicit_delegation_intent"]:
        failures.append("default subagents=on should not be treated as explicit user delegation intent")

    parallel_result, parallel_payload = run_args("plan=a.md 병렬")
    checks["nl_parallel_sets_explicit_delegation_intent"] = (
        parallel_result.returncode == 0
        and parallel_payload.get("values", {}).get("subagents") == "on"
        and parallel_payload.get("intent", {}).get("explicit_delegation_request") is True
        and parallel_payload.get("intent", {}).get("delegation_hint") == "병렬"
    )
    if not checks["nl_parallel_sets_explicit_delegation_intent"]:
        failures.append("NL 병렬 should mark explicit delegation intent")

    explicit_result, explicit_payload = run_args("plan=a.md subagents=on")
    checks["explicit_subagents_on_sets_delegation_intent"] = (
        explicit_result.returncode == 0
        and explicit_payload.get("sources", {}).get("subagents") == "subagents=value"
        and explicit_payload.get("intent", {}).get("explicit_delegation_request") is True
        and explicit_payload.get("intent", {}).get("delegation_hint") == "subagents=on"
    )
    if not checks["explicit_subagents_on_sets_delegation_intent"]:
        failures.append("explicit subagents=on should mark explicit delegation intent")
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_invocation_args.py
```

Expected: FAIL with missing `intent` fields.

- [ ] **Step 3: Implement intent output**

In `scripts/parse_invocation_args.py`, initialize:

```python
    intent = {"explicit_delegation_request": False, "delegation_hint": None}
```

When processing explicit key/value tokens, after `explicit[key] = value`, add:

```python
            if key == "subagents" and value == "on":
                intent["explicit_delegation_request"] = True
                intent["delegation_hint"] = "subagents=on"
```

When processing NL hints, after `nl[key] = (value, source)`, add:

```python
        if key == "subagents" and value == "on":
            intent["explicit_delegation_request"] = True
            intent["delegation_hint"] = token
```

Return:

```python
    return {"values": values, "sources": sources, "intent": intent, "echo": echo}
```

- [ ] **Step 4: Run eval to verify it passes**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_invocation_args.py
```

Expected: JSON output with `"passed": true`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/parse_invocation_args.py \
  skills/kws-codex-plan-executor/evals/check_invocation_args.py
git commit -m "feat(cpe): record explicit delegation intent"
```

### Task 2: Make Dispatch Policy Fallback Deterministic

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

- [ ] **Step 1: Write failing dispatch eval**

In `evals/check_preflight_dispatch.py`, change `run_dispatch` to accept extra
CLI args:

```python
def run_dispatch(repo: Path, state_path: Path, packet_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
```

Append `*extra` to the subprocess command after `--output`.

Add this check near the clean delegate case:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--spawn-policy",
            "explicit-request-required",
            "--explicit-delegation-requested",
            "false",
            "--requested-subagents",
            "on",
            "--requested-source",
            "default",
        )
        checks["spawn_policy_requires_explicit_request_local_fallback"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "spawn_policy_requires_explicit_user_request" in data.get("failed_prerequisites", [])
            and data.get("delegation_policy", {}).get("effective_mode") == "local_fallback"
        )
        if not checks["spawn_policy_requires_explicit_request_local_fallback"]:
            failures.append("explicit-request-required spawn policy without explicit delegation intent should local_fallback")
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: FAIL because the new args are unrecognized.

- [ ] **Step 3: Add dispatch args and policy object**

In `scripts/preflight_dispatch.py`, add parser arguments:

```python
    parser.add_argument("--spawn-policy", choices=["available", "unavailable", "explicit-request-required", "unknown"], default="unknown")
    parser.add_argument("--explicit-delegation-requested", choices=["true", "false"], default="false")
    parser.add_argument("--requested-subagents", choices=["on", "auto", "off"], default="on")
    parser.add_argument("--requested-source", choices=["default", "explicit", "natural_language", "resume_state"], default="default")
```

After `write_scope = args.write_scope`, add:

```python
    explicit_requested = args.explicit_delegation_requested == "true"
    delegation_policy = {
        "requested_mode": args.requested_subagents,
        "requested_source": args.requested_source,
        "explicit_user_delegation_request": explicit_requested,
        "spawn_policy": args.spawn_policy,
        "effective_mode": "delegate",
        "reason": "Delegation prerequisites are still being evaluated.",
    }
    if args.requested_subagents == "off":
        failed.append("subagents_off")
        decision = "local_fallback"
        reason = "subagents=off requests local-only execution"
    elif args.spawn_policy == "unavailable":
        failed.append("spawn_policy_unavailable")
        decision = "local_fallback"
        reason = "spawn_agent tool is unavailable in this session"
    elif args.spawn_policy == "explicit-request-required" and not explicit_requested:
        failed.append("spawn_policy_requires_explicit_user_request")
        decision = "local_fallback"
        reason = "spawn_agent tool policy requires explicit user delegation intent"
```

Before building the payload, set:

```python
    delegation_policy["effective_mode"] = "delegate" if decision == "delegate" else decision
    delegation_policy["reason"] = reason
```

Add `delegation_policy` to `decision_payload` and to `state_updates`.

- [ ] **Step 4: Run dispatch eval**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: JSON output with `"passed": true`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "feat(cpe): make delegation policy fallback deterministic"
```

### Task 3: Expand Local Environment Preflight

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/preflight_local_env.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_local_env_preflight.py`

- [ ] **Step 1: Add failing pnpm and capability evals**

In `evals/check_local_env_preflight.py`, add a temp repo case:

```python
    with tempfile.TemporaryDirectory(prefix="codex-preflight-") as temp:
        repo = Path(temp) / "stale-pnpm"
        repo.mkdir()
        init_repo(repo)
        touch(repo / "package.json", -20)
        touch(repo / "pnpm-lock.yaml", 20)
        touch(repo / "node_modules/.modules.yaml", -20)
        result, data = run_preflight(repo)
        warnings = data.get("warnings", [])
        checks["stale_pnpm_dependencies"] = (
            result.returncode == 0
            and any(item.get("kind") == "dependencies_likely_stale" and item.get("lockfile") == "pnpm-lock.yaml" for item in warnings)
            and any(item.get("command") == "pnpm install --frozen-lockfile" for item in data.get("bootstrap_plan", []))
        )
        if not checks["stale_pnpm_dependencies"]:
            failures.append("pnpm-lock newer than node_modules/.modules.yaml should emit pnpm bootstrap plan")

        capabilities = data.get("environment_capabilities", {})
        checks["capabilities_object_present"] = isinstance(capabilities, dict) and "pnpm" in capabilities and "agentlens" in capabilities
        if not checks["capabilities_object_present"]:
            failures.append("preflight should include environment_capabilities with pnpm and agentlens keys")
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_local_env_preflight.py
```

Expected: FAIL because `bootstrap_plan` and capabilities are not emitted.

- [ ] **Step 3: Implement bootstrap plan helpers**

In `scripts/preflight_local_env.py`, add:

```python
import shutil
```

Add:

```python
def command_presence(name: str) -> str:
    return "present" if shutil.which(name) else "absent"


def environment_capabilities(root: Path) -> dict:
    android_home = bool(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT"))
    return {
        "node": command_presence("node"),
        "bun": command_presence("bun"),
        "pnpm": command_presence("pnpm"),
        "gradle_wrapper": "present" if (root / "gradlew").exists() else "absent",
        "android_sdk": "present" if android_home else "unknown",
        "adb": command_presence("adb"),
        "cargo": command_presence("cargo"),
        "agentlens": command_presence("agentlens"),
    }
```

Import `os` with the other imports.

Add a `bootstrap_plan` list to `build_report()`:

```python
    bootstrap_plan = bootstrap_steps_for_warnings(warnings)
    return {
        "schema_version": "1",
        "warnings": warnings,
        "bootstrap_plan": bootstrap_plan,
        "environment_capabilities": environment_capabilities(root),
    }
```

Implement package-manager-specific stale markers:

```python
NODE_MANAGERS = (
    ("package-lock.json", "node_modules/.package-lock.json", "npm install"),
    ("npm-shrinkwrap.json", "node_modules/.package-lock.json", "npm install"),
    ("pnpm-lock.yaml", "node_modules/.modules.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "node_modules/.yarn-integrity", "yarn install --frozen-lockfile"),
    ("bun.lock", "node_modules/.bun-install", "bun install"),
    ("bun.lockb", "node_modules/.bun-install", "bun install"),
)
```

Use those tuples in `dependency_warnings()`. Store each command in the warning as
`suggested_command`.

Implement:

```python
def bootstrap_steps_for_warnings(warnings: list[dict]) -> list[dict]:
    steps = []
    seen = set()
    for warning in warnings:
        command = warning.get("suggested_command")
        if not isinstance(command, str) or not command or command in seen:
            continue
        seen.add(command)
        steps.append(
            {
                "id": command.replace(" ", "-").replace("/", "-"),
                "command": command,
                "reason": warning.get("suggestion", warning.get("kind", "")),
                "auto_run": False,
            }
        )
    return steps
```

- [ ] **Step 4: Run local env eval**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_local_env_preflight.py
```

Expected: JSON output with `"passed": true`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/preflight_local_env.py \
  skills/kws-codex-plan-executor/evals/check_local_env_preflight.py
git commit -m "feat(cpe): expand fresh worktree preflight evidence"
```

### Task 4: Add Operational Run Quality Validation

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Create: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

- [ ] **Step 1: Write failing v2.22 schema checks**

Create `evals/check_operational_run_quality.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
    with tempfile.TemporaryDirectory(prefix="cpe-run-quality-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run([sys.executable, str(script), str(state_path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def v222_state() -> dict:
    state = check_state_schema.v220_state()
    state["source_workspace"] = "/tmp/source"
    state["execution_worktree"] = state["worktree"]
    state["command_cwd_evidence"] = [
        {
            "command": "python3 scripts/preflight_local_env.py --repo-root \"$WORKTREE_ABS\"",
            "cwd": state["worktree"],
            "phase": "preflight",
            "status": "passed",
        }
    ]
    state["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    state["preflight_bootstrap"] = {
        "schema_version": "1",
        "warnings": [],
        "bootstrap_plan": [],
        "environment_capabilities": {"node": "present", "agentlens": "absent"},
    }
    state["run_quality"] = {
        "schema_version": "1",
        "validation_status": "passed",
        "terminal_state": "finished",
        "stale": False,
        "workspace_matches_execution_worktree": True,
        "schema_drift": [],
        "open_followups": [],
        "summary": "Run finished with validated state.",
    }
    return state


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = run_validator(v222_state())
    checks["valid_v222_state_passes"] = valid.returncode == 0
    if not checks["valid_v222_state_passes"]:
        failures.append("valid v2.22 state should pass: " + (valid.stderr or valid.stdout))

    bad_policy = v222_state()
    bad_policy["delegation_policy"]["effective_mode"] = "maybe"
    invalid = run_validator(bad_policy)
    checks["invalid_delegation_policy_fails"] = invalid.returncode != 0 and "delegation_policy.effective_mode" in invalid.stderr
    if not checks["invalid_delegation_policy_fails"]:
        failures.append("invalid delegation_policy.effective_mode should fail")

    bad_worktree = v222_state()
    bad_worktree["execution_worktree"] = "/tmp/not-a-codex-worktree"
    invalid_worktree = run_validator(bad_worktree)
    checks["invalid_execution_worktree_fails"] = invalid_worktree.returncode != 0 and "execution_worktree" in invalid_worktree.stderr
    if not checks["invalid_execution_worktree_fails"]:
        failures.append("execution_worktree outside .codex/worktrees/<run_id> should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
```

Expected: FAIL because `validate_state.py` does not validate these fields yet.

- [ ] **Step 3: Implement v2.22 validators**

In `scripts/validate_state.py`, add enum constants:

```python
VALID_DELEGATION_REQUESTED_SOURCES = {"default", "explicit", "natural_language", "resume_state"}
VALID_SPAWN_POLICIES = {"available", "unavailable", "explicit-request-required", "unknown"}
VALID_DELEGATION_EFFECTIVE_MODES = {"delegate", "local_fallback", "off", "blocked"}
VALID_RUN_QUALITY_VALIDATION_STATUSES = {"passed", "failed", "unreadable", "not_checked"}
```

Add `_validate_operational_run_quality(data, errors)` with checks described in
the spec:

```python
def _validate_operational_run_quality(data: dict, errors: list[str]) -> None:
    run_id = data.get("run_id")
    source_workspace = data.get("source_workspace")
    if source_workspace is not None and not isinstance(source_workspace, str):
        errors.append("source_workspace must be a string")
    execution_worktree = data.get("execution_worktree")
    if execution_worktree is not None:
        if not isinstance(execution_worktree, str) or not execution_worktree.strip():
            errors.append("execution_worktree must be a non-empty string")
        elif isinstance(run_id, str) and not _has_codex_suffix(execution_worktree, "worktrees", run_id):
            errors.append("execution_worktree must end with .codex/worktrees/<run_id>")
        if isinstance(data.get("worktree"), str) and execution_worktree != data.get("worktree"):
            errors.append("execution_worktree must equal worktree when both are present")

    evidence = data.get("command_cwd_evidence", [])
    if evidence is not None:
        if not isinstance(evidence, list):
            errors.append("command_cwd_evidence must be a list")
        else:
            for index, item in enumerate(evidence):
                prefix = f"command_cwd_evidence[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                for key in ("command", "cwd", "phase", "status"):
                    if not _has_substantive_value(item.get(key)):
                        errors.append(f"{prefix}.{key} must be non-empty")

    policy = data.get("delegation_policy")
    if policy is not None:
        if not isinstance(policy, dict):
            errors.append("delegation_policy must be an object")
        else:
            if policy.get("requested_mode") not in {"on", "auto", "off"}:
                errors.append("delegation_policy.requested_mode must be on, auto, or off")
            if policy.get("requested_source") not in VALID_DELEGATION_REQUESTED_SOURCES:
                errors.append("delegation_policy.requested_source invalid")
            if not isinstance(policy.get("explicit_user_delegation_request"), bool):
                errors.append("delegation_policy.explicit_user_delegation_request must be a boolean")
            if policy.get("spawn_policy") not in VALID_SPAWN_POLICIES:
                errors.append("delegation_policy.spawn_policy invalid")
            if policy.get("effective_mode") not in VALID_DELEGATION_EFFECTIVE_MODES:
                errors.append("delegation_policy.effective_mode invalid")
            if policy.get("effective_mode") in {"local_fallback", "blocked"} and not _has_substantive_value(policy.get("reason")):
                errors.append("delegation_policy.reason must explain local_fallback or blocked mode")

    bootstrap = data.get("preflight_bootstrap")
    if bootstrap is not None:
        if not isinstance(bootstrap, dict):
            errors.append("preflight_bootstrap must be an object")
        else:
            if bootstrap.get("schema_version") != "1":
                errors.append("preflight_bootstrap.schema_version must be 1")
            for key in ("warnings", "bootstrap_plan"):
                if not isinstance(bootstrap.get(key, []), list):
                    errors.append(f"preflight_bootstrap.{key} must be a list")
            if not isinstance(bootstrap.get("environment_capabilities", {}), dict):
                errors.append("preflight_bootstrap.environment_capabilities must be an object")

    quality = data.get("run_quality")
    if quality is not None:
        if not isinstance(quality, dict):
            errors.append("run_quality must be an object")
        else:
            if quality.get("schema_version") != "1":
                errors.append("run_quality.schema_version must be 1")
            if quality.get("validation_status") not in VALID_RUN_QUALITY_VALIDATION_STATUSES:
                errors.append("run_quality.validation_status invalid")
            for key in ("stale", "workspace_matches_execution_worktree"):
                if key in quality and not isinstance(quality[key], bool):
                    errors.append(f"run_quality.{key} must be a boolean")
            for key in ("schema_drift", "open_followups"):
                if key in quality and not isinstance(quality[key], list):
                    errors.append(f"run_quality.{key} must be a list")
```

Call it from `validate(data)` after `_validate_progress_and_trajectory`.

- [ ] **Step 4: Add schema fixture coverage**

In `evals/check_state_schema.py`, import the new helper or add an equivalent
`v222_state()` fixture and assert:

```python
    v222 = v220_state()
    v222["source_workspace"] = "/tmp/source"
    v222["execution_worktree"] = v222["worktree"]
    v222["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    result = run_validator(script, v222)
    checks["v222_optional_fields_pass"] = result.returncode == 0
```

- [ ] **Step 5: Run schema evals**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
python3 evals/check_state_schema.py
```

Expected: both return JSON with `"passed": true`.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat(cpe): validate operational run quality state"
```

### Task 5: Extend Run Inspection

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

- [ ] **Step 1: Add failing inspection evals**

In `evals/check_inspect_runs.py`, add a helper:

```python
def inspect_all(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "inspect_runs.py"
    output = codex_home / "report.json"
    cmd = [
        sys.executable,
        str(script),
        "--codex-home",
        str(codex_home),
        "--all-plans",
        "--recent",
        "10",
        "--output",
        str(output),
        *extra,
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data
```

Add:

```python
    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "active-old", "docs/plan-a.md")
        write_state(home, "finished-new", "docs/plan-b.md", outcome="finished")
        result, data = inspect_all(home, "--validate-state", "--quality-report", "--stale-hours", "0")
        summary = data.get("summary", {})
        checks["all_plans_quality_summary_reported"] = (
            result.returncode == 0
            and summary.get("total") == 2
            and summary.get("finished") == 1
            and summary.get("non_terminal") == 1
            and summary.get("stale_non_terminal") == 1
        )
        if not checks["all_plans_quality_summary_reported"]:
            failures.append("all-plans quality report should summarize finished, non-terminal, and stale runs")
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_inspect_runs.py
```

Expected: FAIL because `--all-plans`, `--recent`, and quality flags are unknown.

- [ ] **Step 3: Implement report mode**

In `scripts/inspect_runs.py`:

1. Add `import time` and `from typing import Any`.
2. Add optional import fallback for validator:

```python
try:
    import validate_state
except Exception:
    validate_state = None
```

3. Add parser args:

```python
    parser.add_argument("--all-plans", action="store_true")
    parser.add_argument("--recent", type=int)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--validate-state", action="store_true")
    parser.add_argument("--quality-report", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
```

4. Make `--plan` optional only when `--all-plans` is present.
5. Sort state files by `stat().st_mtime` descending when `--recent` is used.
6. Add:

```python
def validation_result(state: dict, enabled: bool) -> tuple[str, list[str]]:
    if not enabled:
        return "not_checked", []
    if validate_state is None:
        return "unreadable", ["validate_state import failed"]
    errors = validate_state.validate(state)
    return ("passed" if not errors else "failed", errors)
```

7. Add per-run quality:

```python
def run_quality(state: dict, state_path: Path, codex_home: Path, stale_hours: float, validate: bool) -> dict:
    outcome = state.get("lifecycle_outcome")
    terminal = outcome in FINISHED_OUTCOMES
    age_hours = (time.time() - state_path.stat().st_mtime) / 3600
    validation_status, errors = validation_result(state, validate)
    workspace = state.get("workspace")
    execution_worktree = state.get("execution_worktree") or state.get("worktree")
    workspace_matches = bool(workspace and execution_worktree and str(workspace) == str(execution_worktree))
    return {
        "schema_version": "1",
        "validation_status": validation_status,
        "terminal_state": outcome or "none",
        "stale": (not terminal and age_hours >= stale_hours),
        "workspace_matches_execution_worktree": workspace_matches,
        "schema_drift": errors,
        "open_followups": [],
        "summary": "terminal" if terminal else "non-terminal",
    }
```

8. Build `summary` counters from the selected records.
9. If `--jsonl` is set, write one compact record per line instead of one JSON
   object.

- [ ] **Step 4: Run inspection eval**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_inspect_runs.py
```

Expected: JSON output with `"passed": true`.

- [ ] **Step 5: Smoke real recent report manually**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans --recent 5 --validate-state --quality-report
```

Expected: JSON object with `summary.total` equal to `5`. Do not require all
historical states to validate.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/inspect_runs.py \
  skills/kws-codex-plan-executor/evals/check_inspect_runs.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat(cpe): summarize recent run quality"
```

### Task 6: Emit v2.22 Fields In Static Execution Fixtures

**Files:**

- Modify: `skills/kws-codex-plan-executor/evals/static_execution_runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_execution.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

- [ ] **Step 1: Add failing fixture assertion**

In `evals/check_operational_run_quality.py`, add a temp fixture path that runs
`static_execution_runner.py` and asserts the generated `state.json` contains:

```python
checks["static_runner_emits_v222_fields"] = (
    state.get("execution_worktree") == state.get("worktree")
    and isinstance(state.get("delegation_policy"), dict)
    and isinstance(state.get("preflight_bootstrap"), dict)
    and isinstance(state.get("run_quality"), dict)
)
```

- [ ] **Step 2: Run eval to verify it fails**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
```

Expected: FAIL because static fixture state lacks v2.22 fields.

- [ ] **Step 3: Update static fixture state**

In `evals/static_execution_runner.py`, add these top-level state fields in
`build_state()`:

```python
        "source_workspace": str(repo),
        "execution_worktree": str(worktree),
        "command_cwd_evidence": [
            {
                "command": "static_execution_runner fixture simulation",
                "cwd": str(repo),
                "phase": "fixture",
                "status": "passed",
            }
        ],
        "delegation_policy": {
            "requested_mode": "on",
            "requested_source": "default",
            "explicit_user_delegation_request": False,
            "spawn_policy": "available",
            "effective_mode": "delegate" if changed_files else "local_fallback",
            "reason": "Deterministic fixture uses an accepted simulated subagent when repository files change.",
        },
        "preflight_bootstrap": {
            "schema_version": "1",
            "warnings": [],
            "bootstrap_plan": [],
            "environment_capabilities": {},
        },
        "run_quality": {
            "schema_version": "1",
            "validation_status": "not_checked",
            "terminal_state": "finished",
            "stale": False,
            "workspace_matches_execution_worktree": False,
            "schema_drift": [],
            "open_followups": [],
            "summary": "Deterministic fixture finished.",
        },
```

- [ ] **Step 4: Run fixture eval**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
```

Expected: JSON output with `"passed": true`.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/evals/static_execution_runner.py \
  skills/kws-codex-plan-executor/evals/check_execution.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "test(cpe): emit operational quality fields in fixtures"
```

### Task 7: Update Skill Docs And Eval Harness

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/local-env-preflight.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

- [ ] **Step 1: Wire new eval**

In `evals/run.sh`, add:

```bash
python3 "$EVAL_DIR/check_operational_run_quality.py" >/dev/null
```

Place it after `check_progress_ledger.py` or near the other state-quality
checks.

- [ ] **Step 2: Update SKILL.md invariants**

Add Core Invariant bullets:

```markdown
- Execution runs distinguish `source_workspace` from `execution_worktree` when
  both are known. New tooling should treat `execution_worktree` as the command
  and edit boundary; `workspace` remains backward-compatible state.
- Execution runs record `delegation_policy` after invocation parsing and before
  dispatch. If the active spawn policy requires explicit user delegation intent,
  local fallback is recorded deterministically through
  `scripts/preflight_dispatch.py`, not as an ad hoc task note.
- Fresh-worktree preflight records `preflight_bootstrap` with warnings,
  suggested commands, and environment capability evidence. Bootstrap commands
  are suggestions only and are never auto-run by CPE.
- Run inspection supports recent all-plan quality reports for stale
  non-terminal state, validation drift, and worktree provenance.
```

- [ ] **Step 3: Update README validation commands**

Add:

```bash
python3 evals/check_operational_run_quality.py
```

Add this Design Note:

```markdown
- `docs/experiments/v2.22-operational-run-quality/PLAN.md`
- `docs/experiments/v2.22-operational-run-quality/IMPLEMENTATION.md`
```

- [ ] **Step 4: Update detailed references**

In `references/state-schema.md`, add a v2.22 section with the JSON from the
implementation spec.

In `references/local-env-preflight.md`, add:

```markdown
## Bootstrap Plan

`bootstrap_plan` contains suggested commands only. CPE does not run these
commands automatically.
```

In `references/pre-dispatch-pipeline.md`, add the `--spawn-policy` command
arguments and state that `spawn_policy_requires_explicit_user_request` is a
local fallback, not a task failure.

- [ ] **Step 5: Update maintainer docs**

In `docs/state-and-logging.md`, add sections for:

- `delegation_policy`
- `preflight_bootstrap`
- `run_quality`
- `command_cwd_evidence`

In `docs/evals-and-verification.md`, add the new eval command and describe that
it checks v2.22 optional state and inspection summaries.

In `docs/risks-limitations-deferrals.md`, add:

```markdown
- v2.22 records effective delegation policy, but Python helpers cannot detect
  every host spawn policy without the parent agent passing it in.
- v2.22 bootstrap preflight suggests commands and capability status; it never
  installs dependencies or asks for secrets automatically.
```

- [ ] **Step 6: Update history**

In `HISTORY.md`, add:

```markdown
## 2.22.0 - 2026-06-09

- Added operational run-quality state for source workspace vs execution
  worktree provenance, effective delegation policy, bootstrap preflight
  evidence, command cwd evidence, and recent run-quality inspection.
- Added deterministic dispatch fallback for spawn policies that require
  explicit user delegation intent.
- Extended local environment preflight with package-manager-specific bootstrap
  suggestions and capability detection.
- Extended run inspection with recent all-plan quality reports, stale
  non-terminal detection, and optional state validation.
```

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/local-env-preflight.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "docs(cpe): document operational run quality"
```

### Task 8: Final Verification And Verification Log

**Files:**

- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`

- [ ] **Step 1: Run deterministic eval suite**

Run:

```bash
cd skills/kws-codex-plan-executor
bash evals/run.sh
```

Expected: baseline JSON is written and every fixture has `"passed": true`.

- [ ] **Step 2: Run Python compile check**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
```

Expected: command exits 0.

- [ ] **Step 3: Run shell syntax check**

Run:

```bash
cd skills/kws-codex-plan-executor
bash -n evals/run.sh
```

Expected: command exits 0.

- [ ] **Step 4: Run real recent report smoke**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans --recent 10 --validate-state --quality-report
```

Expected: command exits 0 and prints JSON with `summary.total` equal to `10` or
the number of available states if fewer than 10 exist.

- [ ] **Step 5: Run repository whitespace check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 6: Append verification log**

Append to `skills/kws-codex-plan-executor/docs/verification-log.md`:

```markdown
## 2026-06-09 KST - v2.22 operational run quality

- Branch: the value printed by `git branch --show-current` during final
  verification
- Scope: effective delegation policy, bootstrap preflight, run-quality
  inspection, optional v2.22 state validation, and docs.
- `bash evals/run.sh`: passed
- `python3 -m py_compile scripts/*.py evals/*.py`: passed
- `bash -n evals/run.sh`: passed
- `python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans --recent 10 --validate-state --quality-report`: passed
- `git diff --check`: passed
- Residual risk: helper scripts rely on the parent agent to pass the active
  spawn policy; bootstrap commands remain suggestions and are not auto-run.
```

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/docs/verification-log.md \
  skills/kws-codex-plan-executor/evals/baselines/v2.22.0.json
git commit -m "test(cpe): verify operational run quality"
```

## Execution Order

Sequential:

1. Task 1 must land before Task 2 because dispatch policy needs parsed intent.
2. Task 2 and Task 3 can be implemented independently after Task 1.
3. Task 4 should land before Task 5 so inspection can reuse validation results.
4. Task 6 should land after Task 4 because fixture state must pass the new
   validator.
5. Task 7 should land after behavior is stable.
6. Task 8 is final verification only.

Parallel-safe after Task 1:

- Task 2 dispatch policy.
- Task 3 local environment preflight.

## Review Checklist

- Confirm no new script mutates repository files except explicit state/report
  outputs requested by CLI args.
- Confirm bootstrap commands are suggestions only.
- Confirm `inspect_runs.py` read-only modes do not modify state files.
- Confirm old state fixtures still pass.
- Confirm local fallback under explicit-request spawn policy is not reported as
  source failure.
- Confirm docs state that `workspace` is backward compatible and
  `execution_worktree` is the preferred edit/command boundary.

## Completion Criteria

Implementation is complete only when:

- All eight tasks are checked off.
- The deterministic suite passes.
- The verification log contains the final commands and results.
- The final diff contains behavior, tests, docs, and baseline changes together.
