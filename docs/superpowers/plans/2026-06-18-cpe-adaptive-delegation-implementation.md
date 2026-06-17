# CPE Adaptive Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kws-codex-plan-executor` choose subagent delegation only when it has clear value, while preserving the existing quality gates for local fast path work.

**Architecture:** Keep the public `subagents=on` default. Extend `preflight_dispatch.py` so it separates safety gates from delegation-value scoring, then records adaptive policy evidence in the existing dispatch payload. Extend state validation and docs so adaptive local fast path is treated as an intentional audited outcome, not as a failed delegation.

**Tech Stack:** Python 3 standard library, deterministic CPE eval scripts, Markdown skill docs, git/Graphify verification.

---

## Source Spec

- `docs/superpowers/specs/2026-06-18-cpe-adaptive-delegation-design.md`

## File Structure

- Modify `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  - Owns safety gate checks, adaptive value scoring, deterministic reason strings, and dispatch JSON output.
- Modify `skills/kws-codex-plan-executor/scripts/validate_state.py`
  - Owns state schema validation for adaptive dispatch decisions and finished local fast path records.
- Modify `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
  - Owns direct dispatch policy coverage for local fast path, delegate, and block outcomes.
- Modify `skills/kws-codex-plan-executor/evals/check_state_schema.py`
  - Owns finished-state validation coverage for adaptive local fast path fields.
- Modify CPE docs and references:
  - `skills/kws-codex-plan-executor/SKILL.md`
  - `skills/kws-codex-plan-executor/README.md`
  - `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  - `skills/kws-codex-plan-executor/HISTORY.md`
  - `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
  - `skills/kws-codex-plan-executor/references/execution-cycle.md`
  - `skills/kws-codex-plan-executor/references/state-schema.md`
  - `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - `skills/kws-codex-plan-executor/docs/how-it-works.md`
  - `skills/kws-codex-plan-executor/docs/verification-log.md`
- Possibly modify tracked Graphify outputs after `graphify update .`:
  - `graphify-out/GRAPH_REPORT.md`
  - `graphify-out/graph.json`

## Implementation Rules

- Keep `subagents=on` as the public default in this iteration.
- Do not remove worktree isolation, task contracts, TDD/RED-GREEN requirements, diff scope checks, reconciliation, or state validation.
- Keep `preflight_dispatch.py` output backward-compatible: existing fields must stay present.
- New adaptive fields must be optional in `validate_state.py` so older v2.20-v2.22 states remain valid.
- Every changed runtime behavior starts with a failing deterministic eval.
- Commit after each task.

---

### Task 1: Add Adaptive Dispatch Evals

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

- [ ] **Step 1: Add packet knobs for file count, risk markers, and dependency count**

In `write_packet`, add these keyword arguments and fields:

```python
def write_packet(
    path: Path,
    files: list[str],
    *,
    allowed_write_globs: list[str] | None = None,
    context_status: str = "green",
    acceptance_command: str | None = "python3 evals/check_preflight_dispatch.py",
    fallback_used: bool = False,
    estimated_chars: int = 10,
    max_chars: int = 60000,
    dependencies: list[str] | None = None,
    risk_markers: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "task_0",
                "task_title": "Task",
                "files": files,
                "dependencies": dependencies or [],
                "risk_markers": risk_markers or [],
                "sha256": "packet-sha",
                "context_budget": {
                    "status": context_status,
                    "estimated_chars": estimated_chars,
                    "max_chars": max_chars,
                },
                "acceptance": {"has_acceptance_criteria": acceptance_command is not None, "command": acceptance_command},
                "spec": {"fallback_used": fallback_used},
                "write_policy": {
                    "allowed_write_globs": allowed_write_globs or ["docs/example.md"],
                    "forbidden_write_globs": [".git/**", "graphify-out/**"],
                },
            }
        ),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Run the focused eval and verify the current baseline still passes**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: PASS. The new parameters are not used yet, so this proves the fixture helper change is neutral.

- [ ] **Step 3: Change the existing clean small task expectation to local fast path**

Replace the first check body with:

```python
        checks["clean_small_task_uses_local_fast_path"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and data.get("reason") == "adaptive_policy_local_fast_path_docs_only"
            and data.get("delegation_policy", {}).get("policy_kind") == "adaptive"
            and data.get("delegation_policy", {}).get("value_gate") == "local_fast_path"
            and data.get("state_updates", {}).get("subagent_strategy", {}).get("mode") == "local_fallback"
        )
        if not checks["clean_small_task_uses_local_fast_path"]:
            failures.append("clean small docs task should use adaptive local fast path")
```

- [ ] **Step 4: Add a multi-file independent delegate fixture**

Append this block after the small-task fixture:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "evals").mkdir()
        (repo / "scripts/tool.py").write_text("print('base')\n", encoding="utf-8")
        (repo / "evals/check_tool.py").write_text("print('base')\n", encoding="utf-8")
        subprocess.run(["git", "add", "scripts/tool.py", "evals/check_tool.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add tool"], cwd=repo, check=True)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["scripts/tool.py", "evals/check_tool.py"],
            allowed_write_globs=["scripts/*.py", "evals/*.py"],
            estimated_chars=18000,
            dependencies=[],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--write-scope",
            "scripts/*.py",
            "--write-scope",
            "evals/*.py",
            "--spawn-policy",
            "available",
            "--requested-subagents",
            "on",
            "--requested-source",
            "default",
        )
        checks["multi_file_independent_task_delegates"] = (
            result.returncode == 0
            and data.get("decision") == "delegate"
            and data.get("delegation_policy", {}).get("value_gate") == "delegate"
        )
        if not checks["multi_file_independent_task_delegates"]:
            failures.append("multi-file independent task should delegate when spawn policy is available")
```

- [ ] **Step 5: Add a risky small task fixture**

Append this block after the delegate fixture:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "bun.lock").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "bun.lock"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add lockfile"], cwd=repo, check=True)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["bun.lock"],
            allowed_write_globs=["bun.lock"],
            risk_markers=["lockfile"],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--write-scope",
            "bun.lock",
            "--spawn-policy",
            "available",
        )
        checks["risky_lockfile_task_blocks"] = (
            result.returncode != 0
            and data.get("decision") == "block"
            and "risk_marker_requires_operator_review" in data.get("failed_prerequisites", [])
        )
        if not checks["risky_lockfile_task_blocks"]:
            failures.append("lockfile risk marker should block adaptive dispatch")
```

- [ ] **Step 6: Run the eval and verify it fails for the new adaptive behavior**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: FAIL with failures mentioning `clean small docs task should use adaptive local fast path`, and possibly the new delegate/risk checks. This is the RED step.

- [ ] **Step 7: Commit the failing eval**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "test(cpe): define adaptive dispatch policy"
```

---

### Task 2: Implement Adaptive Dispatch Policy

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Test: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

- [ ] **Step 1: Add adaptive reason constants and risk markers**

Near the imports, add:

```python
ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY = "adaptive_policy_local_fast_path_docs_only"
ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE = "adaptive_policy_local_fast_path_small_scope"
ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK = "adaptive_policy_local_fast_path_linear_task"
ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE = "adaptive_policy_local_fast_path_low_parallel_value"
RISK_MARKER_REQUIRES_OPERATOR_REVIEW = "risk_marker_requires_operator_review"

RISKY_PATH_FRAGMENTS = (
    "migration",
    "migrations",
    "auth",
    "security",
    "infra",
    "terraform",
    "pulumi",
)
RISKY_EXACT_FILES = {"bun.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
```

- [ ] **Step 2: Add signal helpers**

Add these helpers below `write_scope_too_broad`:

```python
def packet_list(packet: dict, key: str) -> list[str]:
    value = packet.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def packet_context_status(packet: dict) -> str:
    budget = packet.get("context_budget") if isinstance(packet, dict) else {}
    if not isinstance(budget, dict):
        return "unknown"
    status = budget.get("status")
    return status if isinstance(status, str) and status.strip() else "unknown"


def packet_estimated_chars(packet: dict) -> int:
    budget = packet.get("context_budget") if isinstance(packet, dict) else {}
    if not isinstance(budget, dict):
        return 0
    value = budget.get("estimated_chars", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def path_risk_markers(files: list[str], explicit_markers: list[str]) -> list[str]:
    markers: set[str] = {marker for marker in explicit_markers if marker}
    for file_path in files:
        normalized = file_path.strip().lstrip("./")
        if normalized in RISKY_EXACT_FILES:
            markers.add("lockfile")
        lowered = normalized.lower()
        for fragment in RISKY_PATH_FRAGMENTS:
            if fragment in lowered:
                markers.add(fragment)
    return sorted(markers)
```

- [ ] **Step 3: Add value scoring**

Add this function below the signal helpers:

```python
def adaptive_value_decision(packet: dict, write_scope: list[str], explicit_requested: bool) -> tuple[str, str, dict]:
    files = packet_list(packet, "files")
    dependencies = packet_list(packet, "dependencies")
    explicit_risks = packet_list(packet, "risk_markers")
    allowed = []
    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    if isinstance(policy, dict):
        allowed = [item for item in policy.get("allowed_write_globs", []) if isinstance(item, str) and item.strip()]
    context_status = packet_context_status(packet)
    estimated_chars = packet_estimated_chars(packet)
    risk_markers = path_risk_markers(files + write_scope, explicit_risks)
    docs_only = bool(files) and all(path.startswith("docs/") and path.endswith(".md") for path in files)
    small_file_count = 0 < len(files) <= 3
    narrow_scope = 0 < len(allowed) <= 3 and 0 < len(write_scope) <= 3
    low_parallel_value = small_file_count and narrow_scope and len(dependencies) <= 1 and estimated_chars <= 12000
    signals = {
        "declared_file_count": len(files),
        "allowed_write_glob_count": len(allowed),
        "write_scope_count": len(write_scope),
        "dependency_count": len(dependencies),
        "packet_budget_status": context_status,
        "estimated_chars": estimated_chars,
        "explicit_user_delegation_request": explicit_requested,
        "risk_markers": risk_markers,
        "docs_only": docs_only,
        "low_parallel_value": low_parallel_value,
    }
    if risk_markers:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW, signals
    if docs_only and context_status in {"green", "yellow"} and narrow_scope:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY, signals
    if low_parallel_value and context_status in {"green", "yellow"}:
        if len(dependencies) == 1:
            return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK, signals
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE, signals
    if not explicit_requested and estimated_chars <= 20000 and narrow_scope:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE, signals
    return "delegate", "all pre-dispatch prerequisites passed", signals
```

- [ ] **Step 4: Extend `decision_payload` without removing existing fields**

Change the signature and returned payload to include optional adaptive evidence:

```python
def decision_payload(
    task_id: str,
    decision: str,
    reason: str,
    write_scope: list[str],
    failed: list[str],
    delegation_policy: dict,
) -> dict:
    mode = "delegated" if decision == "delegate" else "local_fallback"
    return {
        "schema_version": "1",
        "task_id": task_id,
        "decision": decision,
        "reason": reason,
        "write_scope": write_scope,
        "failed_prerequisites": failed,
        "delegation_policy": delegation_policy,
        "state_updates": {
            "delegation_policy": delegation_policy,
            "subagent_strategy": {
                "mode": mode,
                "reason": reason,
                "run_ids": [],
            }
        },
    }
```

This currently matches the existing shape. The adaptive fields live inside `delegation_policy`, so no caller breaks.

- [ ] **Step 5: Initialize adaptive policy metadata in `main`**

Replace the initial `delegation_policy` block with:

```python
    delegation_policy = {
        "requested_mode": args.requested_subagents,
        "requested_source": args.requested_source,
        "explicit_user_delegation_request": explicit_requested,
        "spawn_policy": args.spawn_policy,
        "effective_mode": "delegate",
        "reason": "Delegation prerequisites are still being evaluated.",
        "policy_kind": "adaptive",
        "safety_gate": "pending",
        "value_gate": "pending",
        "signals": {},
    }
```

- [ ] **Step 6: Apply the value gate after safety checks and before payload creation**

Immediately before:

```python
    if failed and decision == "delegate":
        decision = "local_fallback"
        reason = failed[0]
```

insert:

```python
    if not failed and decision == "delegate":
        value_gate, value_reason, signals = adaptive_value_decision(packet, write_scope, explicit_requested)
        delegation_policy["signals"] = signals
        delegation_policy["value_gate"] = value_gate
        if value_gate == "local_fast_path":
            decision = "local_fallback"
            reason = value_reason
        elif value_gate == "block":
            failed.append(value_reason)
            decision = "block"
            reason = value_reason
        else:
            reason = value_reason
    else:
        delegation_policy["signals"] = {}
        delegation_policy["value_gate"] = "skipped"

    delegation_policy["safety_gate"] = "failed" if failed else "passed"
```

- [ ] **Step 7: Ensure block decisions return nonzero and failed prerequisites are complete**

Keep the existing return line:

```python
    return 0 if decision in {"delegate", "local_fallback"} else 1
```

Expected behavior: `risk_marker_requires_operator_review`, dirty overlap, broad scope, and hash mismatch return nonzero with `decision=block`.

- [ ] **Step 8: Run focused eval to verify GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: PASS with checks including `clean_small_task_uses_local_fast_path`, `multi_file_independent_task_delegates`, and `risky_lockfile_task_blocks`.

- [ ] **Step 9: Commit adaptive dispatch implementation**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/preflight_dispatch.py skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "feat(cpe): add adaptive dispatch policy"
```

---

### Task 3: Validate Adaptive Local Fast Path State

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`

- [ ] **Step 1: Add allowed adaptive reason constants to `validate_state.py`**

Near the existing delegation constants, add:

```python
VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS = {
    "adaptive_policy_local_fast_path_small_scope",
    "adaptive_policy_local_fast_path_docs_only",
    "adaptive_policy_local_fast_path_linear_task",
    "adaptive_policy_local_fast_path_low_parallel_value",
    "spawn_policy_requires_explicit_user_request",
}
VALID_DELEGATION_POLICY_KINDS = {"legacy", "adaptive"}
VALID_DELEGATION_SAFETY_GATES = {"pending", "passed", "failed"}
VALID_DELEGATION_VALUE_GATES = {"pending", "delegate", "local_fast_path", "block", "skipped"}
```

- [ ] **Step 2: Extend delegation policy validation**

Inside `_validate_operational_run_quality`, in the `policy is not None` branch after the existing `reason` validation, add:

```python
            policy_kind = policy.get("policy_kind")
            if policy_kind is not None and policy_kind not in VALID_DELEGATION_POLICY_KINDS:
                errors.append("delegation_policy.policy_kind must be legacy or adaptive")
            safety_gate = policy.get("safety_gate")
            if safety_gate is not None and safety_gate not in VALID_DELEGATION_SAFETY_GATES:
                errors.append("delegation_policy.safety_gate invalid")
            value_gate = policy.get("value_gate")
            if value_gate is not None and value_gate not in VALID_DELEGATION_VALUE_GATES:
                errors.append("delegation_policy.value_gate invalid")
            signals = policy.get("signals")
            if signals is not None and not isinstance(signals, dict):
                errors.append("delegation_policy.signals must be an object")
            if (
                policy.get("effective_mode") == "local_fallback"
                and policy.get("value_gate") == "local_fast_path"
                and policy.get("reason") not in VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS
            ):
                errors.append("delegation_policy.reason must be a known adaptive local fast path reason")
```

- [ ] **Step 3: Add a helper that validates task-level adaptive strategy reasons**

Below `_reviewed_completed_subagent_run_ids`, add:

```python
def _validate_subagent_strategy(task_id: str, task: dict, outcome: object, subagents_requested: object, errors: list[str]) -> None:
    strategy = task.get("subagent_strategy")
    completed = str(task.get("status", "")).lower() in {"complete", "completed", "done", "verified", "pass", "passed"}
    if outcome == "finished" and completed and subagents_requested is True:
        manifest = task.get("unit_manifest")
        write_capable = isinstance(manifest, dict) and manifest.get("tool_policy") in {"implementation", "docs"}
        if write_capable and not isinstance(strategy, dict):
            errors.append(f"{task_id}: completed write-capable task missing subagent_strategy")
            return
    if strategy is None:
        return
    if not isinstance(strategy, dict):
        errors.append(f"{task_id}: subagent_strategy must be an object")
        return
    if strategy.get("mode") not in VALID_SUBAGENT_STRATEGY_MODES:
        errors.append(f"{task_id}: subagent_strategy.mode invalid")
    if strategy.get("mode") == "local_fallback":
        reason = strategy.get("reason")
        if not _has_substantive_value(reason):
            errors.append(f"{task_id}: subagent_strategy.reason must explain local_fallback")
        if isinstance(reason, str) and reason.startswith("adaptive_policy_") and reason not in VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS:
            errors.append(f"{task_id}: subagent_strategy.reason must be a known adaptive local fast path reason")
        run_ids = strategy.get("run_ids", [])
        if run_ids not in ([], None):
            errors.append(f"{task_id}: local_fallback subagent_strategy.run_ids must be empty")
```

- [ ] **Step 4: Call the strategy helper from `_validate_tasks`**

At the end of each task loop in `_validate_tasks`, after carried acceptance validation, add:

```python
        _validate_subagent_strategy(task_id, task, outcome, data.get("subagents_requested"), errors)
```

- [ ] **Step 5: Add state schema eval coverage**

In `evals/check_state_schema.py`, add a case after the existing local fallback case:

```python
    adaptive_local_fast_path = v220_state()
    adaptive_local_fast_path["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "available",
        "effective_mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "policy_kind": "adaptive",
        "safety_gate": "passed",
        "value_gate": "local_fast_path",
        "signals": {
            "declared_file_count": 1,
            "allowed_write_glob_count": 1,
            "packet_budget_status": "green",
            "risk_markers": [],
        },
    }
    adaptive_local_fast_path["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "run_ids": [],
    }
    result = run_validator(script, adaptive_local_fast_path)
    checks["finished_adaptive_local_fast_path_passes"] = result.returncode == 0
    if not checks["finished_adaptive_local_fast_path_passes"]:
        failures.append("finished adaptive local fast path should pass: " + (result.stderr or result.stdout))
```

- [ ] **Step 6: Add a negative schema eval for unknown adaptive reason**

Immediately after the positive case, add:

```python
    bad_adaptive_reason = v220_state()
    bad_adaptive_reason["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "available",
        "effective_mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_unlisted",
        "policy_kind": "adaptive",
        "safety_gate": "passed",
        "value_gate": "local_fast_path",
        "signals": {},
    }
    bad_adaptive_reason["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_unlisted",
        "run_ids": [],
    }
    result = run_validator(script, bad_adaptive_reason)
    checks["finished_unknown_adaptive_reason_fails"] = (
        result.returncode != 0 and "known adaptive local fast path reason" in (result.stderr + result.stdout)
    )
    if not checks["finished_unknown_adaptive_reason_fails"]:
        failures.append("unknown adaptive local fast path reason should fail")
```

- [ ] **Step 7: Run state schema eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
```

Expected: PASS.

- [ ] **Step 8: Commit validator changes**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/validate_state.py skills/kws-codex-plan-executor/evals/check_state_schema.py
git commit -m "fix(cpe): validate adaptive local fast path state"
```

---

### Task 4: Update Skill Contract And Reference Docs

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/how-it-works.md`

- [ ] **Step 1: Update `SKILL.md` hard boundary language**

Replace the current subagent default paragraph in `Hard Boundary` with:

```markdown
Use `spawn_agent` for eligible executable tasks when the resolved invocation has
`subagents=on` and deterministic adaptive dispatch says delegation has value.
`subagents=on` remains the default and means subagents are allowed and preferred
when the task is parallel-worthy, independently scoped, and safe to delegate.
Use `spawn_agent` for `subagents=auto` only when the user explicitly requested
subagents, delegation, or parallel agent work. Do not spawn subagents when
`subagents=auto` lacks explicit delegation intent, when `subagents=off`, or when
`scripts/preflight_dispatch.py` selects `local_fallback` for an adaptive local
fast path.
```

- [ ] **Step 2: Add a `SKILL.md` invariant for local fast path**

Add this bullet to `Core Invariants` near the dispatch bullet:

```markdown
- Adaptive local fast path is a quality-preserving local execution decision, not
  a verification skip. It may choose `local_fallback` for small, low-risk,
  linear tasks, but the task still requires the task contract, unit manifest,
  diff-scope review, acceptance evidence, reconciliation, and state validation.
```

- [ ] **Step 3: Update `references/pre-dispatch-pipeline.md`**

Replace the opening paragraph with:

```markdown
`subagents=on` is adaptive subagent-first. The executor first checks whether
delegation is safe, then checks whether delegation has value. Safe but small,
linear, low-risk tasks may use adaptive local fast path and record
`subagent_strategy.mode = local_fallback` with an adaptive reason. This is a
policy decision, not a failed dispatch.
```

Add this decision table after the numbered pipeline:

```markdown
| Decision | Meaning | Required follow-through |
| --- | --- | --- |
| `delegate` | Delegation is safe and useful. | Spawn from task packet, then parent reviews diff and state. |
| `local_fallback` with adaptive reason | Local fast path is safer or cheaper for a small linear task. | Execute locally with task contract, diff check, acceptance, reconcile, and validate. |
| `local_fallback` with policy/tool reason | Delegation is unavailable or not explicitly allowed. | Execute locally and record the concrete policy reason. |
| `block` | Safety gate failed. | Do not execute until dirty scope, packet drift, broad write scope, or risky scope is resolved. |
```

- [ ] **Step 4: Update `references/execution-cycle.md` step 12**

Replace step 12 with:

```markdown
12. Run `scripts/preflight_dispatch.py` before each eligible write-capable task.
    Dispatch only when the decision is `delegate`. When the decision is
    `local_fallback` with an adaptive local fast path reason, run the task
    locally but keep the same quality gates: task contract, unit manifest,
    RED/GREEN when applicable, post-diff review, acceptance command,
    reconciliation, and state validation. When the decision is `block`, stop
    before editing and record the blocker.
```

- [ ] **Step 5: Update `references/state-schema.md`**

Add this section near the delegation policy description:

```markdown
Adaptive dispatch may add optional fields to `delegation_policy`:

- `policy_kind`: `adaptive` or `legacy`.
- `safety_gate`: `pending`, `passed`, or `failed`.
- `value_gate`: `pending`, `delegate`, `local_fast_path`, `block`, or `skipped`.
- `signals`: object with deterministic inputs such as declared file count,
  allowed write glob count, packet budget status, explicit delegation intent,
  and risk markers.

Known adaptive local fast path reasons are
`adaptive_policy_local_fast_path_small_scope`,
`adaptive_policy_local_fast_path_docs_only`,
`adaptive_policy_local_fast_path_linear_task`, and
`adaptive_policy_local_fast_path_low_parallel_value`. Finished runs may use
these reasons only when the task still records unit manifest, diff scope, and
verification evidence.
```

- [ ] **Step 6: Update `ARCHITECTURE.md` delegation paragraph**

Replace the paragraph beginning `Subagents are the default implementation path` with:

```markdown
Subagents remain available by default through `subagents=on`, but dispatch is
adaptive. CPE first proves delegation is safe, then checks whether it has value.
Small, low-risk, linear tasks may use local fast path and record
`subagent_strategy.mode = local_fallback` with an adaptive reason. Larger
parallel-worthy tasks still delegate from task packets with disjoint write
scopes and parent review. Finished state cannot retain running or unreviewed
subagent records.
```

- [ ] **Step 7: Update `README.md` defaults section**

Replace the `subagents=on` paragraph with:

```markdown
`subagents=on` is the adaptive subagent-first default. CPE delegates when the
task is safe and delegation has value. Small, low-risk, linear tasks may run
through local fast path with the same task contract, diff review, acceptance,
reconciliation, and state validation gates. Pass `subagents=auto` for
conservative spawning only after explicit delegation intent, or `subagents=off`
for local-only execution.
```

- [ ] **Step 8: Update `docs/how-it-works.md`**

Replace the subagent paragraph with:

```markdown
With the default `subagents=on`, CPE uses adaptive dispatch. Eligible
write-capable tasks first pass safety checks, then a value check decides whether
to delegate or run local fast path. Local fast path skips only the subagent
spawn/review loop; it keeps task contracts, RED/GREEN evidence when applicable,
diff policy checks, acceptance commands, reconciliation, and state validation.
```

- [ ] **Step 9: Run contract and focused evals**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
```

Expected: all PASS.

- [ ] **Step 10: Commit contract/docs changes**

```bash
cd /Users/kws/source/private/Archive
git add \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/how-it-works.md
git commit -m "docs(cpe): describe adaptive local fast path"
```

---

### Task 5: Update Verification Docs, History, And Full Validation

**Files:**
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Possibly modify: `graphify-out/GRAPH_REPORT.md`
- Possibly modify: `graphify-out/graph.json`

- [ ] **Step 1: Add a new unreleased history entry**

At the top of `HISTORY.md`, below the title, add:

```markdown
## 2.23.0 - Unreleased

- Added adaptive dispatch policy evidence so `subagents=on` delegates only when
  the task is safe and delegation has value.
- Added local fast path reasons for small docs-only, small-scope, linear, and
  low-parallel-value tasks while preserving task contract, diff review,
  acceptance, reconciliation, and state validation gates.
- Extended state validation and deterministic evals for adaptive local fast
  path, delegate, and block outcomes.
```

- [ ] **Step 2: Update `docs/evals-and-verification.md`**

Add this paragraph after the existing pre-dispatch sentence:

```markdown
Adaptive dispatch evals cover docs-only local fast path, small-scope local fast
path, multi-file delegation when spawn policy is available, dirty overlap
blocking, broad write-scope blocking, packet hash mismatch blocking, and risky
lockfile blocking.
```

- [ ] **Step 3: Add verification log entry**

At the top of `docs/verification-log.md`, add:

````markdown
## 2026-06-18

Scope:

- Adaptive dispatch policy for `subagents=on`.
- Local fast path as an audited local fallback for small, low-risk, linear
  tasks.
- State validation for adaptive local fast path reasons and delegation policy
  evidence.

Commands:

```bash
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --update-ran --output /tmp/cpe-adaptive-delegation-graphify-audit.json
git diff --check
```

Result:

- Replace this two-line result block in Step 7 with the exact pass/fail bullets
  from the command outcomes observed in Steps 4-6.
````

- [ ] **Step 4: Run focused verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
```

Expected: all PASS.

- [ ] **Step 5: Run full deterministic verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Expected: all PASS. If `./evals/run.sh` updates `evals/baselines/v2.22.0.json` only by timestamp, include that baseline change only if the project convention expects the latest eval timestamp in the committed baseline. If it is a local run artifact, revert that timestamp before committing.

- [ ] **Step 6: Refresh Graphify**

Run:

```bash
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root /Users/kws/source/private/Archive \
  --update-ran \
  --output /tmp/cpe-adaptive-delegation-graphify-audit.json
```

Expected: graphify completes. The freshness audit JSON has no blocking `errors`.

- [ ] **Step 7: Update verification log result with actual outcomes**

Edit the `Result:` section added in Step 3 so it lists actual outcomes. Use this shape:

```markdown
Result:

- Focused adaptive dispatch, state schema, and skill contract evals: pass.
- Full deterministic fixture harness: pass.
- Python compile and shell syntax: pass.
- Graphify update: pass; tracked output changed or unchanged as observed.
- Graphify freshness audit: pass with no blocking errors.
- Diff whitespace check: pass.
```

- [ ] **Step 8: Run final diff check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
git status --short --branch --untracked-files=all
```

Expected: no whitespace errors. Status shows only intended CPE docs/code/eval files and possible tracked Graphify outputs.

- [ ] **Step 9: Commit final docs and verification evidence**

```bash
cd /Users/kws/source/private/Archive
git add \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/verification-log.md \
  graphify-out/GRAPH_REPORT.md \
  graphify-out/graph.json
git commit -m "chore(cpe): record adaptive dispatch verification"
```

If Graphify outputs are ignored or unchanged, omit those paths from `git add` and mention the observed state in the final response.

---

## Final Verification

Run these commands after all tasks are complete:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
git status --short --branch --untracked-files=all
```

Expected:

- All CPE eval commands pass.
- Python compile exits 0.
- Shell syntax check exits 0.
- `git diff --check` prints no output.
- Status contains only intentional changes after the last task commit.

## Self-Review

- Spec coverage: adaptive delegation policy is covered by Tasks 1-2; local fast path quality gates are covered by Tasks 2 and 4; validation automation is covered by Task 3; docs and Graphify evidence are covered by Tasks 4-5.
- Placeholder scan: this plan contains no unfinished placeholder markers or open-ended implementation instructions.
- Type consistency: new dispatch evidence fields use `delegation_policy.policy_kind`, `safety_gate`, `value_gate`, and `signals` consistently across scripts, state validation, evals, and docs.
- Scope check: the plan stays inside `skills/kws-codex-plan-executor`, `docs/superpowers/plans`, and optional tracked Graphify outputs. It does not change Waygent runtime or the public `subagents=on` default.
