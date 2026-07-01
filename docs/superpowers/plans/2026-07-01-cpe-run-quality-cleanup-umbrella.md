# CPE Run Quality Cleanup Umbrella Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce repeated CPE `run_quality=yellow` noise by improving task packet spec mapping, audit/state parity, delegation policy classification, and deterministic replay coverage.

**Architecture:** Keep CPE's existing safety gates and thin stateful bridge. Add a small shared audit helper used by readiness, plan executability, and dispatch; improve task packet metadata without breaking older state; then prove finished-run quality through a normalized replay fixture harness.

**Tech Stack:** Python 3 standard library, Bash eval harness, Markdown docs, existing `skills/kws-codex-plan-executor` scripts/evals, Graphify command evidence.

## Global Constraints

- Preserve `brainstorming` hard gate and CPE worktree isolation.
- Do not weaken TDD, task execution contracts, dispatch safety, state reconciliation, prompt audit, Graphify audit, or completion audit.
- Do not bypass `spawn_agent` policy or infer explicit delegation where the user did not request it.
- Do not add non-stdlib Python dependencies.
- Do not import Waygent runtime into CPE.
- Do not make LLM judge or external Harness CLI part of the default eval gate.
- Default eval runs must not rewrite tracked baseline files.
- New runtime artifacts belong under `~/.codex/orchestrator/<run_id>/`; repository worktrees must not receive CPE state artifacts.
- Follow `skills/kws-codex-plan-executor/references/change-protocol.md`: eval coverage first, docs/contracts with behavior, deterministic eval suite, `py_compile`, `bash -n`.

---

## File Structure

- `skills/kws-codex-plan-executor/scripts/cpe_audit_common.py`
  New shared Python helper for dependency aliases, write-scope normalization, risky path markers, and stable reason constants.
- `skills/kws-codex-plan-executor/scripts/parse_plan.py`
  Extend YAML task parsing to support `spec_refs`.
- `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
  Use manifest `task_to_sections`, emit `dependencies` alias, and include mapping evidence.
- `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
  Use shared helper for malformed scope and dependency semantics.
- `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
  Use shared helper and preserve raw/effective audit count semantics.
- `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  Use shared helper for dependency count and malformed scope detection.
- `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
  Split expected local fallback from prevented delegation.
- `skills/kws-codex-plan-executor/scripts/validate_state.py`
  Validate plan audit parity, delegation evidence, and structured residual risk.
- `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
  New deterministic normalized replay generator.
- `skills/kws-codex-plan-executor/evals/parser-fixtures/17-yaml-spec-refs.yaml`
  Fixture for YAML task `spec_refs`.
- `skills/kws-codex-plan-executor/evals/check_parse_plan.py`
  Assert YAML `spec_refs` parsing.
- `skills/kws-codex-plan-executor/evals/check_task_packet.py`
  Assert manifest mapping and dependency alias emission.
- `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
  Assert newline/comma write-scope formatting suggestions use shared helper.
- `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
  Assert shared dependency/scope policy and raw/effective summary shape.
- `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
  Assert dependency alias compatibility and malformed scope behavior.
- `skills/kws-codex-plan-executor/evals/check_state_schema.py`
  Assert state parity and structured residual risk validation.
- `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
  Assert delegation follow-up classification.
- `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
  New normalized replay eval.
- `skills/kws-codex-plan-executor/evals/run.sh`
  Wire `check_cpe_replay.py` into the focused eval list.
- `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`
  New CPE eval coverage map.
- `skills/kws-codex-plan-executor/SKILL.md`, `README.md`, `ARCHITECTURE.md`,
  `HISTORY.md`, `docs/user-guide.ko.md`, `docs/evals-and-verification.md`,
  `docs/state-and-logging.md`, `references/state-schema.md`,
  `references/pre-dispatch-pipeline.md`, `references/execution-cycle.md`
  Contract documentation updates.

## Task 1: Shared Audit Semantics Helper

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_audit_common.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`

**Interfaces:**
- Produces:
  - `list_strings(value: object) -> list[str]`
  - `dependency_list(payload: dict) -> list[str]`
  - `malformed_scope(pattern: str) -> bool`
  - `normalized_scopes(patterns: list[str]) -> list[str]`
  - `path_risk_markers(paths: list[str], explicit: list[str] | None = None) -> list[str]`
  - constants for adaptive reason strings.
- Consumes: existing packet/task dictionaries from readiness, plan audit, and dispatch scripts.

- [ ] **Step 1: Add failing helper contract tests**

In `skills/kws-codex-plan-executor/evals/check_run_readiness.py`, add checks that create a packet with newline-joined write scopes:

```python
packet["write_policy"]["allowed_write_globs"] = ["src/a.py\nsrc/b.py"]
```

Expected issue:

```python
{
    "kind": "write_scope_format_invalid",
    "suggested_write_scopes": ["src/a.py", "src/b.py"],
}
```

In `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`, add a helper-level subprocess case that passes a packet with only `depends_on` and verifies the value contributes to dependency count.

Expected result:

```python
checks["packet_depends_on_counts_as_dependency"] = (
    data["delegation_policy"]["signals"]["dependency_count"] == 1
)
```

- [ ] **Step 2: Run focused tests to verify RED**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_run_readiness.py
python3 evals/check_preflight_dispatch.py
```

Expected: at least one new check fails because no shared helper handles newline scopes or `depends_on` fallback consistently.

- [ ] **Step 3: Create `cpe_audit_common.py`**

Add:

```python
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY = "adaptive_policy_local_fast_path_docs_only"
ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE = "adaptive_policy_local_fast_path_small_scope"
ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK = "adaptive_policy_local_fast_path_linear_task"
ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE = "adaptive_policy_local_fast_path_low_parallel_value"
RISK_MARKER_REQUIRES_OPERATOR_REVIEW = "risk_marker_requires_operator_review"

RISKY_PATH_FRAGMENTS = ("migration", "migrations", "auth", "security", "infra", "terraform", "pulumi")
RISKY_EXACT_FILES = {"bun.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
BROAD_SCOPES = {"", ".", "*", "**", "**/*", "./", "./*", "./**", "./**/*"}


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def dependency_list(payload: dict[str, Any]) -> list[str]:
    dependencies = list_strings(payload.get("dependencies"))
    if dependencies:
        return dependencies
    return list_strings(payload.get("depends_on"))


def malformed_scope(pattern: str) -> bool:
    stripped = pattern.strip()
    if not stripped:
        return False
    if any(char in stripped for char in "[]{}"):
        return False
    return "," in stripped or "\n" in stripped or "\r" in stripped


def split_scope(pattern: str) -> list[str]:
    if not malformed_scope(pattern):
        return [pattern.strip()] if pattern.strip() else []
    normalized = pattern.replace("\r\n", "\n").replace("\r", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


def normalized_scopes(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for pattern in patterns:
        for part in split_scope(pattern):
            if part not in result:
                result.append(part)
    return result


def write_scope_too_broad(pattern: str) -> bool:
    return pattern.strip().rstrip("/") in BROAD_SCOPES


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


def docs_only(paths: list[str]) -> bool:
    return bool(paths) and all(path.startswith("docs/") and path.endswith(".md") for path in paths)


def small_scope(paths: list[str]) -> bool:
    return 0 < len(paths) <= 2


def path_name_tokens(path: str) -> set[str]:
    pure = PurePosixPath(path)
    tokens: set[str] = set()
    for part in pure.parts:
        tokens.update(item for item in part.replace("-", "_").replace(".", "_").split("_") if item)
    return tokens
```

- [ ] **Step 4: Update existing scripts to import the helper**

Modify `audit_run_readiness.py`, `audit_plan_executability.py`, and `preflight_dispatch.py` to remove duplicate `list_strings`, `malformed_scope`, and `normalized_scopes` implementations.

Use direct import with local script path support:

```python
from cpe_audit_common import dependency_list, list_strings, malformed_scope, normalized_scopes
```

For `preflight_dispatch.py`, replace packet dependency reads with:

```python
dependencies = dependency_list(packet)
signals["dependency_count"] = len(dependencies)
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_preflight_dispatch.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_audit_common.py \
  skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/scripts/audit_plan_executability.py \
  skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py
git commit -m "test: share CPE audit semantics"
```

## Task 2: Spec Mapping And Dependency Alias

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/parser-fixtures/17-yaml-spec-refs.yaml`
- Modify: `skills/kws-codex-plan-executor/scripts/parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_parse_plan.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`

**Interfaces:**
- Produces parsed tasks with `spec_refs` from YAML task blocks.
- Produces packets where `depends_on` and `dependencies` contain the same task ids.
- Produces mapping evidence with `source=explicit|manifest|heuristic|fallback`.

- [ ] **Step 1: Add YAML parser fixture**

Create `skills/kws-codex-plan-executor/evals/parser-fixtures/17-yaml-spec-refs.yaml`:

```yaml
name: yaml task spec refs
input: |
  # Plan

  ```yaml waygent-task
  id: task_1
  title: Packet mapping
  dependencies: []
  spec_refs: ["S1", "S2.1"]
  file_claims:
    - skills/kws-codex-plan-executor/scripts/build_task_packet.py
  ```

  Acceptance:
  python3 evals/check_task_packet.py
expected:
  tasks:
    - id: task_1
      title: Packet mapping
      files:
        - skills/kws-codex-plan-executor/scripts/build_task_packet.py
      spec_refs: ["S1", "S2.1"]
```

- [ ] **Step 2: Add failing parser assertion**

In `evals/check_parse_plan.py`, include fixture `17-yaml-spec-refs.yaml` in the parser fixture loop if fixtures are enumerated explicitly. If the loop is file-glob based, add a named check:

```python
checks["yaml_spec_refs_are_extracted"] = parsed["tasks"][0]["spec_refs"] == ["S1", "S2.1"]
```

- [ ] **Step 3: Add failing packet mapping assertions**

In `evals/check_task_packet.py`, add a manifest with:

```python
"task_to_sections": {"task_1": ["S2"]}
```

Create a task with no explicit `spec_refs` and files that do not match heuristic signals.

Expected:

```python
checks["manifest_task_to_sections_precedes_full_spec_fallback"] = (
    packet["spec"]["fallback_used"] is False
    and packet["spec"]["section_ids"] == ["S2"]
    and packet["spec"]["mapping"]["source"] == "manifest"
)
```

Also assert dependency alias:

```python
checks["packet_emits_dependencies_alias_for_dispatch"] = (
    packet["depends_on"] == ["task_0"]
    and packet["dependencies"] == ["task_0"]
)
```

- [ ] **Step 4: Run tests to verify RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_parse_plan.py
python3 evals/check_task_packet.py
```

Expected: new checks fail.

- [ ] **Step 5: Implement YAML `spec_refs` parsing**

In `parse_plan.py`, when converting YAML task blocks to task dictionaries, read `spec_refs`:

```python
def _yaml_spec_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
```

For YAML tasks:

```python
"spec_refs": _yaml_spec_refs(yaml_payload.get("spec_refs")) or _extract_spec_refs(yaml_body),
```

Keep existing hidden-region safeguards unchanged.

- [ ] **Step 6: Implement manifest mapping in packet builder**

In `build_task_packet.py`, extend `resolve_sections()`:

```python
task_to_sections = manifest.get("task_to_sections") if isinstance(manifest.get("task_to_sections"), dict) else {}
manifest_refs = [
    item for item in task_to_sections.get(str(task.get("id", "")), [])
    if isinstance(item, str) and item.strip()
]
if manifest_refs:
    for section_id in manifest_refs:
        if section_id not in sections:
            die(f"unknown manifest section for {task.get('id')}: {section_id}")
    return manifest_refs, False, {
        "selected_section_ids": manifest_refs,
        "candidate_scores": [{"section_id": section_id, "score": 90, "signals": ["manifest_task_to_sections"]} for section_id in manifest_refs],
        "mapping_reason": "Matched spec manifest task_to_sections.",
        "requires_parent_mapping": False,
        "source": "manifest",
    }
```

Ensure explicit and heuristic branches also include `source`.

- [ ] **Step 7: Emit dependency alias**

When building the packet:

```python
depends_on = [item for item in task.get("depends_on", []) if isinstance(item, str)]
packet["depends_on"] = depends_on
packet["dependencies"] = depends_on
```

- [ ] **Step 8: Verify GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_parse_plan.py
python3 evals/check_task_packet.py
python3 evals/check_preflight_dispatch.py
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/parse_plan.py \
  skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/evals/parser-fixtures/17-yaml-spec-refs.yaml \
  skills/kws-codex-plan-executor/evals/check_parse_plan.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py
git commit -m "feat: improve CPE task packet spec mapping"
```

## Task 3: State Parity, Delegation Policy, And Residual Risk Schema

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes finished `state.json` fields: `plan_executability_audit`, `run_quality`,
  `delegation_policy`, `dispatch_decisions`, `completion_audit.residual_risk`.
- Produces validation failures for audit parity drift and invalid structured residual risk.
- Produces stable follow-ups:
  - `delegation_policy_expected_local_fallback`
  - `delegation_policy_prevented_all_delegation`
  - `delegation_policy_missing_dispatch_evidence`

- [ ] **Step 1: Add failing state schema tests**

In `evals/check_state_schema.py`, add:

```python
checks["plan_executability_summary_mismatch_fails"] = (
    run_validate(invalid_state_with_fixable_mismatch).returncode != 0
    and "plan_executability_audit fixable count must match run_quality readiness" in output
)
```

Add structured residual risk cases:

```python
valid_state["completion_audit"]["residual_risk"] = [
    {
        "owner": "operator",
        "class": "external_credentials",
        "summary": "Production deploy requires VM_PUBLIC_IP.",
        "blocks_release": False,
        "unblocks_when": "Operator provides credentials and reruns deploy smoke.",
        "evidence_ref": "completion_audit.verification_evidence[0]",
    }
]
```

Invalid case:

```python
invalid_state["completion_audit"]["residual_risk"] = [
    {"owner": "operator", "class": "deployment", "summary": "Blocks release", "blocks_release": True}
]
```

Expected invalid output includes:

```text
completion_audit.residual_risk blocks_release=true cannot coexist with finished passed completion
```

- [ ] **Step 2: Add failing run-quality tests**

In `evals/check_operational_run_quality.py`, add:

```python
checks["expected_local_fallback_is_not_prevented_delegation"] = (
    "delegation_policy_expected_local_fallback" in followups
    and "delegation_policy_prevented_all_delegation" not in followups
)
```

Add explicit request case:

```python
checks["explicit_delegation_all_policy_fallback_reports_debt"] = (
    "delegation_policy_prevented_all_delegation" in explicit_followups
)
```

- [ ] **Step 3: Run tests to verify RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
```

Expected: new checks fail.

- [ ] **Step 4: Update `run_quality_debt.py`**

Add constants:

```python
DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK = "delegation_policy_expected_local_fallback"
DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE = "delegation_policy_missing_dispatch_evidence"
```

Classify:

```python
def delegation_followup(state: dict[str, Any]) -> str | None:
    policy = state.get("delegation_policy") if isinstance(state.get("delegation_policy"), dict) else {}
    dispatches = [item for item in state.get("dispatch_decisions", []) if isinstance(item, dict)]
    tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    write_capable = [task_id for task_id, task in tasks.items() if isinstance(task, dict) and task.get("unit_manifest", {}).get("write_capable") is not False]
    if write_capable and not dispatches:
        return DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE
    if policy.get("spawn_policy") == "explicit-request-required" and policy.get("explicit_user_delegation_request") is False:
        return DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK
    if dispatches and all(item.get("decision") == "local_fallback" for item in dispatches):
        reasons = " ".join(str(item.get("reason", "")) for item in dispatches)
        if "explicit" in reasons or "spawn_policy" in reasons:
            return DELEGATION_POLICY_PREVENTED_ALL_DELEGATION
    return None
```

Keep existing stable follow-up ordering deterministic.

- [ ] **Step 5: Update `validate_state.py`**

Add parity check:

```python
readiness = run_quality.get("readiness") if isinstance(run_quality.get("readiness"), dict) else {}
expected = audit.get("fixable_issue_count")
observed = readiness.get("plan_executability_fixable_issue_count")
if expected is not None and observed is not None and expected != observed:
    errors.append("plan_executability_audit fixable count must match run_quality readiness")
```

Add raw/effective checks:

```python
raw_blocking = audit.get("raw_blocking_issue_count")
effective_blocking = audit.get("blocking_issue_count")
if isinstance(raw_blocking, int) and isinstance(effective_blocking, int) and effective_blocking < raw_blocking:
    if not audit.get("operator_reviewed_blocking_issues") or not audit.get("operator_decision"):
        errors.append("plan_executability_audit reduced blocking count requires operator review evidence")
```

Add structured residual risk validation while preserving string items.

- [ ] **Step 6: Verify GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_plan_executability_audit.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat: normalize CPE run quality debt"
```

## Task 4: Normalized Replay Harness And Coverage Map

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Create: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Create: `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`

**Interfaces:**
- `normalize_cpe_run.py --state <path> [--run-dir <path>] [--context <path>] [--final-output <path>]`
- Produces normalized JSON to stdout and optional `--output`.
- Eval asserts stable subset fields and forbidden pattern absence.

- [ ] **Step 1: Add failing replay eval**

Create `evals/check_cpe_replay.py` with synthetic state builders:

```python
def finished_state(run_dir: Path) -> dict:
    return {
        "schema_version": "1",
        "run_id": "synthetic-run",
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "lifecycle_outcome": "finished",
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["implemented requested files"],
            "verification_evidence": ["python3 evals/check_task_packet.py"],
            "residual_risk": [
                {
                    "owner": "operator",
                    "class": "external_credentials",
                    "summary": "Deploy requires VM_PUBLIC_IP.",
                    "blocks_release": False,
                }
            ],
        },
        "run_quality": {
            "grade": "yellow",
            "score": 90,
            "open_followups": ["full_spec_fallback_present"],
            "context_quality": {"full_spec_fallback_count": 1},
            "verification_quality": {"completion_audit_passed": True},
        },
        "tasks": {"task_1": {"fallback_spec_used": True}},
        "dispatch_decisions": [{"task_id": "task_1", "decision": "local_fallback", "reason": "adaptive_policy_local_fast_path_small_scope"}],
        "prompt_audit": {"passed": True, "dynamic_marker_violations": []},
        "graphify_audit": {"fresh": True, "errors": [], "warnings": []},
        "plan_executability_audit": {"grade": "yellow", "fixable_issue_count": 1, "blocking_issue_count": 0},
        "timestamps": {"started_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-01T00:01:00Z", "completed_at": "2026-07-01T00:01:00Z"},
    }
```

Checks:

```python
checks["finished_yellow_replay_normalizes"] = (
    replay["completion_passed"] is True
    and replay["run_quality_grade"] == "yellow"
    and replay["full_spec_fallback_count"] == 1
    and replay["residual_risk_classes"] == ["external_credentials"]
)
checks["forbidden_patterns_detected"] = "sk-" in replay_with_secret["forbidden_patterns_found"]
```

- [ ] **Step 2: Run eval to verify RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cpe_replay.py
```

Expected: FAIL because `scripts/normalize_cpe_run.py` does not exist.

- [ ] **Step 3: Implement `normalize_cpe_run.py`**

Core functions:

```python
def residual_risk_classes(audit: dict[str, object]) -> list[str]:
    result: list[str] = []
    for item in audit.get("residual_risk", []):
        if isinstance(item, dict) and isinstance(item.get("class"), str):
            if item["class"] not in result:
                result.append(item["class"])
        elif isinstance(item, str) and "credential" in item.lower():
            if "external_credentials" not in result:
                result.append("external_credentials")
    return result
```

```python
def forbidden_patterns(texts: list[str]) -> list[str]:
    markers: list[str] = []
    joined = "\n".join(texts)
    if "sk-" in joined:
        markers.append("sk-")
    if "/Users/" in joined:
        markers.append("absolute_home_path")
    if "BEGIN FULL PROMPT" in joined:
        markers.append("full_prompt")
    return markers
```

Replay output must be sorted JSON with stable key order.

- [ ] **Step 4: Add coverage map**

Create `docs/eval-coverage-cpe.md` with a table:

```markdown
# CPE Eval Coverage Map

| Failure mode | Primary eval | Supporting evals |
| --- | --- | --- |
| YAML spec refs hidden/visible parsing | `check_parse_plan.py` | `check_task_packet.py` |
| Manifest task-to-section slicing | `check_task_packet.py` | `check_run_readiness.py` |
| Write-scope formatting | `check_run_readiness.py` | `check_preflight_dispatch.py` |
| Plan audit/state parity | `check_state_schema.py` | `check_operational_run_quality.py` |
| Expected local fallback vs prevented delegation | `check_operational_run_quality.py` | `check_preflight_dispatch.py` |
| Structured residual risk | `check_state_schema.py` | `check_cpe_replay.py` |
| Normalized replay forbidden patterns | `check_cpe_replay.py` | `check_eval_harness.py` |
```

- [ ] **Step 5: Wire eval harness**

In `evals/run.sh`, add:

```bash
python3 "$EVAL_DIR/check_cpe_replay.py" >/dev/null
```

In `check_eval_harness.py`, assert:

```python
checks["cpe_replay_eval_in_harness"] = "check_cpe_replay.py" in run_sh
```

- [ ] **Step 6: Verify GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cpe_replay.py
python3 evals/check_eval_harness.py
./evals/run.sh
```

Expected: all pass and tracked baseline files remain unchanged.

- [ ] **Step 7: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py \
  skills/kws-codex-plan-executor/evals/check_eval_harness.py \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md
git commit -m "test: add CPE normalized replay coverage"
```

## Task 5: Contract Docs And Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`

**Interfaces:**
- Documents new state fields, replay eval, helper ownership, and quality follow-up semantics.
- Keeps docs aligned with checked contract eval.

- [ ] **Step 1: Add failing contract checks**

In `evals/check_skill_contract.py`, assert these strings exist in the relevant docs:

```python
"normalize_cpe_run.py"
"delegation_policy_expected_local_fallback"
"raw_blocking_issue_count"
"structured residual risk"
"eval-coverage-cpe.md"
```

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py
```

Expected: FAIL until docs are updated.

- [ ] **Step 2: Update `SKILL.md`**

Add Core Invariants bullets:

```markdown
- Finished operational-quality states may distinguish raw plan audit counts from
  operator-reviewed effective counts. If effective blocker counts are lower than raw
  counts, the state records `operator_reviewed_blocking_issues` and `operator_decision`.
- Expected local fallback caused by an explicit-request-required spawn policy is recorded
  separately from prevented delegation. Do not report `delegation_policy_prevented_all_delegation`
  when local fallback was the resolved policy before execution.
- Normalized CPE replay checks are deterministic eval evidence. They summarize state,
  audits, dispatch decisions, residual risk classes, and forbidden durable-log patterns
  without storing raw transcripts or full prompts.
```

- [ ] **Step 3: Update state schema docs**

In `references/state-schema.md`, document:

```json
"plan_executability_audit": {
  "grade": "yellow",
  "raw_grade": "red",
  "blocking_issue_count": 0,
  "raw_blocking_issue_count": 2,
  "fixable_issue_count": 3,
  "raw_fixable_issue_count": 3,
  "operator_reviewed_blocking_issues": ["task_1:risk_marker_requires_operator_review"],
  "operator_decision": "Proceed locally after operator review."
}
```

Also document structured residual risk object fields.

- [ ] **Step 4: Update operator docs**

In `docs/user-guide.ko.md`, explain:

- expected local fallback
- prevented delegation
- missing dispatch evidence
- raw versus effective plan audit counts
- normalized replay output

- [ ] **Step 5: Update eval docs and history**

In `docs/evals-and-verification.md`, add:

```bash
python3 evals/check_cpe_replay.py
```

In `HISTORY.md`, add an unreleased entry:

```markdown
## 2.25.0 - Unreleased

- Added shared CPE audit semantics for dependency aliases and write-scope formatting.
- Improved task packet spec mapping with YAML `spec_refs`, manifest task mappings, and dependency aliases.
- Split expected local fallback from prevented delegation in run-quality debt.
- Added normalized CPE replay deterministic eval coverage and fixture coverage map.
```

- [ ] **Step 6: Verify contract docs**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py
```

Expected: pass.

- [ ] **Step 7: Run full verification**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_parse_plan.py
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
python3 evals/check_skill_contract.py
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Expected: all pass.

- [ ] **Step 8: Refresh Graphify evidence**

Run from repo root:

```bash
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran
git diff --check
```

Expected: Graphify check passes. If `graphify-out/` is ignored and no tracked output changes, record command evidence in the final completion audit.

- [ ] **Step 9: Commit**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/docs/user-guide.ko.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/evals/check_skill_contract.py
git commit -m "docs: document CPE run quality cleanup"
```

## Execution Order

- Task 1 must run first because later tasks consume shared helpers.
- Task 2 and Task 3 can run in parallel after Task 1 if their write scopes stay disjoint.
- Task 4 can run in parallel with Task 3 after Task 1.
- Task 5 runs last because it updates user-facing contracts and full verification.

## Self-Review Checklist For Implementer

- Every behavior change starts with a failing deterministic eval.
- No eval reads expected values from hidden harness metadata when acting as target executor.
- No default command rewrites baseline files.
- `completion_audit.passed=true` remains compatible with executor-quality `yellow`.
- Explicit operator review is preserved when raw audit blockers are reduced.
- Structured residual risk does not hide release-blocking product risk.
- New replay artifacts never include raw transcripts, full prompts, home paths, tokens, or secrets.
