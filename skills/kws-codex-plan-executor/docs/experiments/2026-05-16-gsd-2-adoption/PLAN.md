# GSD-2 Codex Plan Executor Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the high-leverage orchestration ideas from `gsd-build/gsd-2` to `kws-codex-plan-executor` without copying GSD's database, dashboard, or full product runtime.

**Architecture:** Keep Codex execution file-based and skill-local: `.codex-orchestrator/runs/<run_id>/state.json` remains the run source of truth, with project-local JSONL events and deterministic Python checks around it. Adopt GSD-2's unit manifest, pre-dispatch gates, drift reconciliation, context budgeting, structured headless result, and opt-in subagent run tracking as small contracts layered onto the existing executor.

**Tech Stack:** Python 3 standard library, Markdown reference contracts, JSON/JSONL run artifacts, deterministic eval scripts, Codex skill metadata, existing `kws-codex-plan-executor` docs/evals.

---

## Source Basis

Analyzed source:

| Item | Value |
| --- | --- |
| Repository | `https://github.com/gsd-build/gsd-2` |
| Local analysis clone | `/tmp/gsd-2-analysis` |
| Source commit | `74bba52ac2af5960d7caf8c8720ed0249d4ee6b5` |
| Commit date observed | `2026-05-15 23:19:09 -0500` |
| Package latest observed | `gsd-pi@3.0.0` |
| Analysis date | `2026-05-16` |

Primary GSD-2 files reviewed:

| Source | Why it matters |
| --- | --- |
| `README.md` | GSD-2 product framing and Pi SDK packaging. |
| `docs/dev/architecture.md` | Runtime architecture, loader, extension runtime, and mode layer. |
| `docs/user-docs/auto-mode.md` | User-facing auto-mode loop and command behavior. |
| `docs/user-docs/parallel-orchestration.md` | Parallel orchestration and worker lifecycle ideas. |
| `docs/user-docs/token-optimization.md` | Context packing and budget behavior. |
| `docs/user-docs/dynamic-model-routing.md` | Task complexity and model routing design. |
| `docs/dev/ADR-009-orchestration-kernel-refactor.md` | Six-plane orchestration split: Plan, Execution, Model, Gate, GitOps, Audit. |
| `docs/dev/ADR-016-worktree-lifecycle-and-projection.md` | Separate worktree lifecycle from state projection. |
| `docs/dev/ADR-017-state-reconciliation-drift-driven.md` | Drift detection and idempotent repair loop. |
| `docs/dev/ADR-013-memory-store-consolidation.md` | Canonical memory store with projected human docs. |
| `src/resources/extensions/gsd/unit-context-manifest.ts` | Declarative per-unit context and tool policy. |
| `src/resources/extensions/gsd/bootstrap/write-gate.ts` | Tool/write policy enforcement by unit type. |
| `src/resources/extensions/gsd/context-budget.ts` | Context budget allocation and truncation. |
| `src/resources/extensions/gsd/workflow-events.ts` | Event vocabulary and orchestration observability. |
| `src/resources/extensions/gsd/journal.ts` | JSONL journal mechanics. |
| `src/resources/extensions/gsd/auto/workflow-kernel.ts` | Auto-mode dispatch and validation pipeline. |
| `src/resources/extensions/subagent/run-store.ts` | Subagent run persistence shape. |

Important source caution:

- GSD-2 current docs and ADRs make `.gsd/gsd.db` the canonical runtime source of truth, with Markdown files as projections.
- An older `gsd-orchestrator/SKILL.md` still says checkboxes on disk are the source of truth.
- For Codex, this plan intentionally keeps JSON files authoritative. It borrows the drift-reconciliation idea, not GSD's SQLite authority model.

## Current Executor Baseline

`kws-codex-plan-executor` already has several patterns that overlap with GSD-2:

| Existing capability | Current file surface |
| --- | --- |
| Dedicated `codex/...` worktree before edits | `SKILL.md`, `references/execution-cycle.md`, `references/headless-runner.md` |
| Per-run source-of-truth state | `.codex-orchestrator/runs/<run_id>/state.json`, `references/state-schema.md`, `scripts/validate_state.py` |
| Context source snapshot | `scripts/build_context_snapshot.py`, `references/state-schema.md` |
| `context_health` resumability signal | `references/state-schema.md`, `scripts/validate_state.py` |
| Completion audit | `references/state-schema.md`, `scripts/validate_state.py` |
| Learning log for cross-repo process notes | `references/learning-log.md`, `scripts/append_learning_event.py`, `scripts/check_learning_log_health.py` |
| TDD and verification-before-completion contract | `SKILL.md`, `references/execution-cycle.md`, `templates/fresh-session-prompt.txt` |
| Advisory execution DAG parsing | `scripts/parse_plan.py`, `evals/parser-fixtures/*` |
| Dirty related/unrelated file classification | `SKILL.md`, `references/execution-cycle.md`, headless fixtures |

This means the useful work is not a rewrite. The implementation should add missing control planes and checks around the existing state contract.

## Adoption Map

| GSD-2 pattern | Codex adoption | Priority | Target surface |
| --- | --- | --- | --- |
| Unit Context Manifest | Add a manifest per task/unit describing required skills, context mode, allowed tools, artifact policy, and write scope. | P0 | `references/unit-context-manifest.md`, `references/state-schema.md`, `scripts/validate_state.py` |
| Pre-dispatch invariant pipeline | Require a compact gate sequence before each task contract: version, state, dirty files, context, manifest, worktree, dispatch decision. | P0 | `references/pre-dispatch-pipeline.md`, `SKILL.md`, `references/execution-cycle.md` |
| Write/tool policy by unit type | Convert allowed edits and task type into a machine-checkable policy. Codex cannot hook every tool call, so enforce pre-contract and post-diff. | P0 | `scripts/check_run_diffs.py`, `scripts/validate_state.py`, `references/unit-context-manifest.md` |
| Project-local event journal | Add `.codex-orchestrator/runs/<run_id>/events.jsonl` for replayable run events separate from user-local learning logs. | P0 | `scripts/append_run_event.py`, `references/event-journal.md`, `scripts/validate_state.py` |
| Drift-driven reconciliation | Add read-only/repair modes for state drift: stale root pointer, missing context hash, missing completion evidence, stale health timestamp, open task mismatch. | P1 | `scripts/reconcile_state.py`, `references/drift-reconciliation.md`, `evals/check_state_reconciliation.py` |
| Context budget and packing | Extend context snapshots with section-level metadata and budget status instead of only hashing source files. | P1 | `scripts/build_context_snapshot.py`, `references/context-budget.md`, `evals/check_context_snapshot.py` |
| Structured headless result | Define a stable final result schema with status, artifacts, verification, blockers, and residual risk. | P1 | `templates/headless-output-schema.json`, `references/headless-result-schema.md`, `references/headless-runner.md` |
| Subagent run store | Track opt-in subagents as state artifacts with ownership, fork mode, result path, and merge/review status. | P2 | `references/subagent-run-store.md`, `references/state-schema.md`, `scripts/validate_state.py` |
| Command observation taxonomy | Record command failures as typed observations before assigning root cause. | P2 | `references/command-observations.md`, `references/execution-cycle.md`, `scripts/validate_state.py` |
| Model routing | Document manual routing hints only. Runtime model choice remains under Codex/app policy, not this skill. | P3 | `docs/risks-limitations-deferrals.md`, optional reference note |
| SQLite canonical runtime | Do not adopt. File/JSON authority is simpler and fits Codex skill distribution. | Rejected | `docs/decisions.md` when behavior ships |
| Web dashboard / daemon / MCP server | Do not adopt in this skill. | Rejected | None |

## Non-Goals

- Do not port GSD-2's TypeScript extension runtime, Pi SDK, TUI, daemon, Studio, or MCP server.
- Do not introduce SQLite or a long-running background process.
- Do not make subagents default; current explicit opt-in policy remains.
- Do not add model auto-routing that overrides the user's active Codex model or app policy.
- Do not replace `state.json`; enrich and validate it.
- Do not treat user-local learning logs as execution source of truth.
- Do not block low-risk docs-only work behind heavy multi-agent orchestration.
- Do not claim any new behavior is active until deterministic evals and runtime docs are updated.

## File Map

### New Files

| File | Responsibility |
| --- | --- |
| `references/unit-context-manifest.md` | Canonical task/unit manifest schema, unit types, context policy, tool/write policy examples. |
| `references/pre-dispatch-pipeline.md` | Gate sequence before each task dispatch and before each headless task prompt. |
| `references/event-journal.md` | Project-local JSONL event schema and event vocabulary. |
| `references/drift-reconciliation.md` | DriftRecord types, detect/repair rules, and terminal blocking semantics. |
| `references/context-budget.md` | Context packing, source section metadata, budget statuses, and truncation rules. |
| `references/headless-result-schema.md` | Stable structured result contract for `codex exec` final output. |
| `references/subagent-run-store.md` | Opt-in subagent record schema and merge/review lifecycle. |
| `references/command-observations.md` | Command failure taxonomy and evidence fields. |
| `templates/headless-output-schema.json` | JSON Schema passed to `codex exec --output-schema` when available. |
| `scripts/append_run_event.py` | Append one project-local run event and maintain sequence metadata. |
| `scripts/check_run_diffs.py` | Compare changed files against task contract and manifest write policy. |
| `scripts/reconcile_state.py` | Detect and optionally repair safe state drift. |
| `evals/check_event_journal.py` | Deterministic event journal append/sequence/redaction checks. |
| `evals/check_state_reconciliation.py` | Drift detection and safe repair fixtures. |
| `evals/check_context_snapshot.py` | Context snapshot budget and section metadata fixtures. |
| `evals/check_headless_result.py` | JSON Schema validity and sample result validation. |

### Modified Files

| File | Responsibility |
| --- | --- |
| `SKILL.md` | Add only short invariants for manifest, pre-dispatch gates, event journal, and drift checks. |
| `ARCHITECTURE.md` | Describe new control planes once behavior ships. |
| `README.md` | Update public reading path after behavior ships. |
| `HISTORY.md` | Add version entry after behavior ships. |
| `references/execution-cycle.md` | Insert manifest creation, pre-dispatch gates, event appends, diff check, and drift check into interactive flow. |
| `references/headless-runner.md` | Mirror runtime contracts for fresh `codex exec` processes and output schema usage. |
| `references/prompt-export-checklist.md` | Ensure prompt/handoff export includes new runtime invariants. |
| `references/state-schema.md` | Document optional and required state fields as each milestone lands. |
| `templates/fresh-session-prompt.txt` | Mirror active runtime invariants for exported prompts. |
| `scripts/build_context_snapshot.py` | Add optional section metadata and budget summary. |
| `scripts/validate_state.py` | Validate new schema fields and terminal requirements. |
| `evals/check_state_schema.py` | Add positive and negative fixtures for new state fields. |
| `evals/check_skill_contract.py` | Prevent SKILL/template/reference drift. |
| `evals/run.sh` | Add new deterministic checks to the package eval suite. |
| `docs/decisions.md` | Record accepted/rejected GSD-2 patterns after implementation. |
| `docs/evals-and-verification.md` | Document new checks and expected commands. |
| `docs/how-it-works.md` | Explain the new flow in maintainer terms. |
| `docs/risks-limitations-deferrals.md` | Record non-adopted GSD features and residual limitations. |
| `docs/state-and-logging.md` | Explain event journal vs learning log vs state. |
| `docs/verification-log.md` | Append compact evidence for every implementation pass. |

## Target Runtime Shape

The target executor keeps one authoritative state file per run:

```text
.codex-orchestrator/runs/<run_id>/
  state.json
  context.json
  events.jsonl
  headless-result.json        # headless only, when available
  subagents/                  # only when subagents=on
```

State remains the source of truth. `events.jsonl` is replay/audit evidence. User-local learning logs remain cross-repo process notes.

### State Additions

The target top-level shape adds these fields:

```json
{
  "source_basis": {
    "executor_skill_version": "1.9.0",
    "state_schema_version": "2",
    "gsd_2_analysis": {
      "repo": "https://github.com/gsd-build/gsd-2",
      "commit": "74bba52ac2af5960d7caf8c8720ed0249d4ee6b5",
      "analyzed_at": "2026-05-16"
    }
  },
  "event_journal_path": ".codex-orchestrator/runs/<run_id>/events.jsonl",
  "last_event_seq": 0,
  "dispatch_gates": [],
  "drift": {
    "last_checked_at": null,
    "records": [],
    "unrepaired_blockers": []
  },
  "context_budget": {
    "status": "green",
    "max_chars": 120000,
    "estimated_chars": 0,
    "included_sections": [],
    "omitted_sections": []
  },
  "subagent_runs": []
}
```

Each task may add:

```json
{
  "task_2": {
    "unit_manifest": {
      "unit_type": "execute-task",
      "context_mode": "focused",
      "required_skills": ["using-superpowers", "test-driven-development"],
      "tool_policy": "implementation",
      "allowed_write_globs": ["scripts/*.py", "evals/*.py", "references/*.md"],
      "forbidden_write_globs": [".git/**", "graphify-out/**"],
      "artifact_policy": "inline-summary",
      "max_context_chars": 60000
    },
    "dispatch_gate_result": {
      "status": "passed",
      "checked_at": "2026-05-16T07:30:00Z",
      "gates": ["version", "state", "worktree", "dirty-files", "context", "manifest"]
    },
    "command_observations": []
  }
}
```

## Milestones

### Milestone 1: Source Basis And Contract Documents

Acceptance:

- The GSD-2 source basis is documented in this experiment.
- New reference contracts are introduced as docs before runtime changes.
- Non-adopted GSD-2 patterns are explicit.
- No runtime behavior is changed in this milestone.

### Milestone 2: Unit Context Manifest And Diff Policy

Acceptance:

- Each executable task can carry `unit_manifest`.
- Terminal state validation rejects malformed manifests.
- `scripts/check_run_diffs.py` can check changed files against `allowed_edits` and manifest write globs.
- Prompt/handoff export tells fresh sessions to maintain the manifest.

### Milestone 3: Pre-Dispatch Gate Pipeline

Acceptance:

- Interactive and headless flows define the same pre-dispatch gate sequence.
- State records per-task `dispatch_gate_result`.
- Finished runs cannot contain a failed or missing gate for completed tasks.
- Gate failure produces `lifecycle_outcome=blocked` or a concrete `handoff_reason`.

### Milestone 4: Project-Local Event Journal

Acceptance:

- `events.jsonl` exists for interactive and headless execution after preflight.
- Event sequence numbers are monotonic per run.
- Events contain `run_id`, `seq`, `type`, `timestamp`, and redacted payload.
- `state.last_event_seq` matches the last journal event before terminal completion.
- User-local learning logs remain optional and separate.

### Milestone 5: Drift Reconciliation

Acceptance:

- `scripts/reconcile_state.py --check` reports deterministic drift records without mutating files.
- `scripts/reconcile_state.py --repair-safe` repairs only idempotent safe drift.
- Terminal `finished` validation blocks unrepaired critical drift.
- Drift records are written into state and journaled.

### Milestone 6: Context Budget Snapshot

Acceptance:

- `context.json` includes source sections, estimated char counts, included/omitted sections, and budget status.
- Budget red/yellow/green rules are documented.
- Finished runs with red context budget require either a repair or a clear residual-risk entry.

### Milestone 7: Structured Headless Result

Acceptance:

- `templates/headless-output-schema.json` validates sample success, blocked, failed, and cancelled results.
- Headless docs use the schema when `codex exec --output-schema` is available.
- `headless-result.json` is referenced in state and completion audit when present.

### Milestone 8: Opt-In Subagent Run Store

Acceptance:

- `subagent_runs` records only exist when the user explicitly requested subagents.
- Each record has owner task, write scope, status, result summary, changed files, and review outcome.
- Finished runs cannot leave subagent changes unreviewed.

### Milestone 9: Command Observation Taxonomy

Acceptance:

- Verification failures can be classified before root cause is claimed.
- Command observations distinguish source failure, missing local env, dependency/bootstrap failure, resource/OOM, timeout/hang, flaky test, permission/sandbox, and unknown.
- Completion audit cites unresolved observations or proves they were resolved.

### Milestone 10: Release Docs And Full Eval Pass

Acceptance:

- `SKILL.md`, `ARCHITECTURE.md`, `README.md`, `HISTORY.md`, runtime references, prompt template, and maintainer docs agree.
- Deterministic eval suite includes all new checks.
- Verification log records command evidence.
- Graphify update is run only if code files in Archive root are modified; skill docs-only changes do not require it.

## Task Plan

### Task 1: Add Contract-Only Reference Documents

**Files:**
- Create: `references/unit-context-manifest.md`
- Create: `references/pre-dispatch-pipeline.md`
- Create: `references/event-journal.md`
- Create: `references/drift-reconciliation.md`
- Create: `references/context-budget.md`
- Create: `references/headless-result-schema.md`
- Create: `references/subagent-run-store.md`
- Create: `references/command-observations.md`
- Modify: `docs/decisions.md`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 1.1: Write the reference docs**

Each reference doc must include:

```text
Purpose
Runtime status
Schema
Required fields
Validation rules
Examples
Failure behavior
Prompt-export impact
```

- [ ] **Step 1.2: Record GSD-2 adoption decision**

Update `docs/decisions.md` with this table:

```md
## Why GSD-2 Adoption Is Selective

| Pattern | Decision | Reason |
| --- | --- | --- |
| Unit Context Manifest | Adopt | It makes task context and write policy explicit without requiring a new runtime. |
| Pre-dispatch gates | Adopt | They turn hidden execution assumptions into resumable state. |
| Project-local event journal | Adopt | It gives replayable evidence separate from cross-repo learning logs. |
| Drift reconciliation | Adopt | It handles stale or inconsistent state without switching to a database. |
| Context budget | Adopt | It prevents overpacked prompts and vague continuation state. |
| Structured headless result | Adopt | It makes detached execution reviewable. |
| Subagent run store | Adopt opt-in only | It preserves current user-control policy. |
| SQLite canonical runtime | Reject | Codex skill distribution is simpler with JSON files. |
| Dashboard/daemon/MCP server | Reject | Too much product runtime for this skill. |
| Automatic model routing | Defer | Model selection belongs to Codex/app policy unless user asks otherwise. |
```

- [ ] **Step 1.3: Verify docs-only contract**

Run:

```bash
rg -n "[T]BD|[T]ODO|fill[ -]in|implement[ -]later|Similar to [T]ask" references docs/experiments/2026-05-16-gsd-2-adoption docs/decisions.md docs/risks-limitations-deferrals.md || true
git diff --check -- skills/kws-codex-plan-executor
```

Expected:

```text
No placeholder matches in the new docs.
No whitespace errors.
```

- [ ] **Step 1.4: Commit**

```bash
git add skills/kws-codex-plan-executor
git commit -m "docs: plan gsd-2 adoption for codex executor"
```

### Task 2: Add Unit Manifest State Validation

**Files:**
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 2.1: Write failing state-schema fixtures**

Add fixtures to `evals/check_state_schema.py` for:

| Fixture | Expected |
| --- | --- |
| `valid_unit_manifest_passes` | valid task manifest passes |
| `invalid_unit_type_fails` | unknown unit type fails |
| `invalid_tool_policy_fails` | unknown tool policy fails |
| `finished_missing_unit_manifest_for_completed_task_fails` | finished run with completed task missing manifest fails |
| `implementation_manifest_without_allowed_write_globs_fails` | implementation policy must declare write globs |

Run:

```bash
python3 evals/check_state_schema.py
```

Expected before implementation:

```text
At least one new check fails because validate_state.py does not yet validate unit_manifest.
```

- [ ] **Step 2.2: Implement manifest validation**

Add constants and a validator in `scripts/validate_state.py`:

```python
VALID_UNIT_TYPES = {
    "research",
    "plan",
    "execute-task",
    "reactive-execute",
    "validate",
    "complete",
    "docs",
    "review",
    "handoff",
}
VALID_CONTEXT_MODES = {"minimal", "focused", "expanded", "full"}
VALID_TOOL_POLICIES = {"read-only", "planning", "implementation", "docs", "verification"}
VALID_ARTIFACT_POLICIES = {"inline", "inline-summary", "excerpt", "on-demand"}
REQUIRED_UNIT_MANIFEST_FIELDS = {
    "unit_type",
    "context_mode",
    "required_skills",
    "tool_policy",
    "allowed_write_globs",
    "forbidden_write_globs",
    "artifact_policy",
    "max_context_chars",
}
```

Validation behavior:

```text
completed task in finished run -> unit_manifest required
unit_type not in VALID_UNIT_TYPES -> error
context_mode not in VALID_CONTEXT_MODES -> error
tool_policy not in VALID_TOOL_POLICIES -> error
artifact_policy not in VALID_ARTIFACT_POLICIES -> error
required_skills, allowed_write_globs, forbidden_write_globs must be lists
max_context_chars must be positive integer
tool_policy=implementation requires non-empty allowed_write_globs
tool_policy=read-only requires empty allowed_write_globs
```

- [ ] **Step 2.3: Update runtime docs and prompt**

Add one compact invariant to `SKILL.md` only after validation is implemented:

```md
- Each completed execution task records a `unit_manifest` that declares unit type, context mode, required skills, tool policy, write globs, artifact policy, and max context size.
```

Mirror the same contract in `references/execution-cycle.md`, `references/headless-runner.md`, and `templates/fresh-session-prompt.txt`.

- [ ] **Step 2.4: Verify**

Run:

```bash
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Expected:

```text
check_state_schema.py passes all manifest checks.
check_skill_contract.py returns passed=true.
quick_validate.py prints Skill is valid!
```

- [ ] **Step 2.5: Commit**

```bash
git add SKILL.md references scripts evals templates docs
git commit -m "feat: validate task unit manifests"
```

### Task 3: Add Diff Policy Check

**Files:**
- Create: `scripts/check_run_diffs.py`
- Create: `evals/check_run_diffs.py`
- Modify: `references/unit-context-manifest.md`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 3.1: Write diff policy eval**

`evals/check_run_diffs.py` must create a temp git repo, write a state file with a task contract and manifest, modify files, and assert:

| Case | Expected |
| --- | --- |
| changed file inside contract and manifest glob | pass |
| changed file outside `allowed_edits` | fail |
| changed file matching `forbidden_write_globs` | fail |
| read-only manifest with no changed files | pass |
| docs policy changing `docs/**` | pass |

Run:

```bash
python3 evals/check_run_diffs.py
```

Expected before implementation:

```text
Fails because scripts/check_run_diffs.py does not exist.
```

- [ ] **Step 3.2: Implement `check_run_diffs.py`**

Command shape:

```bash
python3 scripts/check_run_diffs.py --repo-root . --state .codex-orchestrator/runs/<run_id>/state.json --task task_2
```

Exit behavior:

```text
0 -> changed files obey contract and manifest
1 -> changed files violate allowed or forbidden policy
2 -> unreadable state, missing task, or git command failure
```

The script must read changed files using:

```bash
git diff --name-only
git diff --cached --name-only
git ls-files --others --exclude-standard
```

Policy:

```text
allowed if file matches task.contract.allowed_edits OR task.unit_manifest.allowed_write_globs
forbidden if file matches task.contract.forbidden_edits OR task.unit_manifest.forbidden_write_globs
forbidden wins over allowed
```

- [ ] **Step 3.3: Document post-diff gate**

Add to `references/execution-cycle.md`:

```md
After each implementation step and before claiming task completion, run the diff policy check for the active task. Treat a violation as a blocker unless the plan is updated and a new task contract is recorded before further edits.
```

- [ ] **Step 3.4: Verify**

Run:

```bash
python3 evals/check_run_diffs.py
python3 -m py_compile scripts/check_run_diffs.py evals/check_run_diffs.py
git diff --check -- skills/kws-codex-plan-executor
```

Expected:

```text
Diff policy eval passes.
Python compile passes.
No whitespace errors.
```

- [ ] **Step 3.5: Commit**

```bash
git add scripts/check_run_diffs.py evals/check_run_diffs.py references docs
git commit -m "feat: check executor diffs against unit policy"
```

### Task 4: Add Project-Local Event Journal

**Files:**
- Create: `scripts/append_run_event.py`
- Create: `evals/check_event_journal.py`
- Modify: `references/event-journal.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 4.1: Add journal eval cases**

Cases:

| Case | Expected |
| --- | --- |
| first event creates `events.jsonl` and state seq 1 | pass |
| second event increments seq | pass |
| wrong run id rejected | fail |
| payload with secret-looking key rejected or redacted | pass with redaction |
| finished state with stale `last_event_seq` fails validation | fail |

- [ ] **Step 4.2: Implement append script**

Command shape:

```bash
python3 scripts/append_run_event.py --state .codex-orchestrator/runs/<run_id>/state.json --type task_contract_recorded --payload '{"task_id":"task_2"}'
```

Event shape:

```json
{
  "schema_version": "1",
  "run_id": "<run_id>",
  "seq": 1,
  "timestamp": "2026-05-16T07:30:00Z",
  "type": "task_contract_recorded",
  "payload": {"task_id": "task_2"}
}
```

Allowed event types:

```text
run_started
context_snapshot_created
pre_dispatch_checked
dispatch_gate_failed
task_contract_recorded
task_started
task_completed
verification_started
verification_passed
verification_failed
drift_detected
drift_repaired
blocked
failed
finished
```

- [ ] **Step 4.3: Add state validation**

Finished runs require:

```text
event_journal_path points to .codex-orchestrator/runs/<run_id>/events.jsonl
last_event_seq is a positive integer
completion_audit.verification_evidence is not empty
```

The validator should not read the journal file by default. The event journal eval should verify file contents.

- [ ] **Step 4.4: Verify**

Run:

```bash
python3 evals/check_event_journal.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/append_run_event.py evals/check_event_journal.py scripts/validate_state.py
```

Expected:

```text
Event journal checks pass.
State schema checks pass.
Python compile passes.
```

- [ ] **Step 4.5: Commit**

```bash
git add scripts/append_run_event.py evals/check_event_journal.py references docs scripts/validate_state.py evals/check_state_schema.py
git commit -m "feat: add project-local executor event journal"
```

### Task 5: Add Drift Reconciliation

**Files:**
- Create: `scripts/reconcile_state.py`
- Create: `evals/check_state_reconciliation.py`
- Modify: `references/drift-reconciliation.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 5.1: Write drift fixtures**

Drift cases:

| Drift type | Safe repair |
| --- | --- |
| `stale-root-state-pointer` | update root compatibility pointer when per-run state is valid |
| `missing-context-health-timestamp` | set timestamp to `timestamps.updated_at` only when health content is otherwise valid |
| `missing-event-journal-path` | set expected path when file exists |
| `stale-last-event-seq` | set seq from journal tail |
| `finished-with-open-carried-acceptance` | no repair, blocking |
| `completed-task-missing-unit-manifest` | no repair, blocking |
| `context-basis-hash-mismatch` | no repair, blocking |

- [ ] **Step 5.2: Implement `reconcile_state.py`**

Command shapes:

```bash
python3 scripts/reconcile_state.py --state .codex-orchestrator/runs/<run_id>/state.json --check
python3 scripts/reconcile_state.py --state .codex-orchestrator/runs/<run_id>/state.json --repair-safe
```

Output shape:

```json
{
  "passed": false,
  "state_path": ".codex-orchestrator/runs/<run_id>/state.json",
  "records": [
    {
      "type": "stale-last-event-seq",
      "severity": "repairable",
      "message": "state.last_event_seq is 3 but events.jsonl ends at 4",
      "repair": "set state.last_event_seq to 4"
    }
  ],
  "repaired": []
}
```

- [ ] **Step 5.3: Add terminal validation**

`scripts/validate_state.py` should reject `lifecycle_outcome=finished` when:

```text
drift.unrepaired_blockers is non-empty
drift.records contains severity=blocking
drift.last_checked_at is older than timestamps.updated_at
```

- [ ] **Step 5.4: Verify**

Run:

```bash
python3 evals/check_state_reconciliation.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/reconcile_state.py evals/check_state_reconciliation.py scripts/validate_state.py
```

Expected:

```text
Drift reconciliation checks pass.
State schema checks pass.
Python compile passes.
```

- [ ] **Step 5.5: Commit**

```bash
git add scripts/reconcile_state.py evals/check_state_reconciliation.py references docs scripts/validate_state.py evals/check_state_schema.py
git commit -m "feat: reconcile executor state drift"
```

### Task 6: Add Context Budget Snapshot

**Files:**
- Modify: `scripts/build_context_snapshot.py`
- Create: `evals/check_context_snapshot.py`
- Modify: `references/context-budget.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 6.1: Write context snapshot eval**

Cases:

| Case | Expected |
| --- | --- |
| small plan under budget | `context_budget.status=green` |
| source near budget | `context_budget.status=yellow` |
| source over budget | `context_budget.status=red` and omitted section records |
| section hashes stable | repeated run produces same `basis_hash` |

- [ ] **Step 6.2: Extend snapshot output**

Add optional arguments:

```bash
python3 scripts/build_context_snapshot.py --repo-root . --run-id <run_id> --plan plan.md --output context.json --max-chars 120000
```

Add output fields:

```json
{
  "context_budget": {
    "status": "green",
    "max_chars": 120000,
    "estimated_chars": 42100,
    "included_sections": [
      {"role": "plan", "path": "plan.md", "section": "Task 1", "estimated_chars": 1200, "sha256": "<hash>"}
    ],
    "omitted_sections": []
  }
}
```

- [ ] **Step 6.3: Update validation and docs**

Validation:

```text
context_budget.status must be green, yellow, or red
max_chars must be positive
estimated_chars must be non-negative
finished run with red context_budget must include completion_audit.residual_risk explaining the risk
```

- [ ] **Step 6.4: Verify**

Run:

```bash
python3 evals/check_context_snapshot.py
python3 evals/check_state_schema.py
python3 -m py_compile scripts/build_context_snapshot.py evals/check_context_snapshot.py scripts/validate_state.py
```

Expected:

```text
Context snapshot checks pass.
State schema checks pass.
Python compile passes.
```

- [ ] **Step 6.5: Commit**

```bash
git add scripts/build_context_snapshot.py evals/check_context_snapshot.py references docs scripts/validate_state.py evals/check_state_schema.py
git commit -m "feat: track executor context budget"
```

### Task 7: Add Structured Headless Result

**Files:**
- Create: `templates/headless-output-schema.json`
- Create: `references/headless-result-schema.md`
- Create: `evals/check_headless_result.py`
- Modify: `references/headless-runner.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 7.1: Add schema and sample eval**

Schema must accept statuses:

```text
success
blocked
failed
cancelled
```

Required fields:

```text
status
run_id
state_path
summary
changed_files
verification
open_gaps
residual_risk
next_action
```

- [ ] **Step 7.2: Update headless runner docs**

Document the launch shape:

```bash
codex exec --json --output-last-message --output-schema templates/headless-output-schema.json < prompt.txt
```

When `--output-schema` is unavailable, the headless runner must still ask for the same JSON shape and save the last message for review.

- [ ] **Step 7.3: Verify**

Run:

```bash
python3 evals/check_headless_result.py
python3 evals/check_skill_contract.py --skill SKILL.md
git diff --check -- skills/kws-codex-plan-executor
```

Expected:

```text
Headless result schema checks pass.
Skill contract checks pass.
No whitespace errors.
```

- [ ] **Step 7.4: Commit**

```bash
git add templates/headless-output-schema.json references/headless-result-schema.md evals/check_headless_result.py references/headless-runner.md templates/fresh-session-prompt.txt evals/check_skill_contract.py docs
git commit -m "feat: define structured headless executor result"
```

### Task 8: Add Opt-In Subagent Run Store

**Files:**
- Create: `references/subagent-run-store.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 8.1: Add state fixtures**

Cases:

| Case | Expected |
| --- | --- |
| no subagent runs when subagents off | pass |
| completed subagent with reviewed result | pass |
| completed subagent missing changed files | fail |
| subagent result unreviewed in finished run | fail |
| subagent write scope overlapping current task without rationale | fail |

- [ ] **Step 8.2: Implement validation**

Record shape:

```json
{
  "id": "agent_123",
  "owner_task": "task_4",
  "mode": "fork_context",
  "write_scope": ["docs/**"],
  "status": "completed",
  "result_summary": "Updated docs wording.",
  "changed_files": ["docs/example.md"],
  "review_status": "accepted",
  "merged_at": "2026-05-16T07:40:00Z"
}
```

Terminal rules:

```text
finished run cannot include status=running subagent
finished run cannot include review_status=unreviewed
changed_files must stay inside write_scope
subagent_runs require explicit subagents=on or user request recorded in state
```

- [ ] **Step 8.3: Verify**

Run:

```bash
python3 evals/check_state_schema.py
python3 -m py_compile scripts/validate_state.py evals/check_state_schema.py
```

Expected:

```text
State schema checks pass.
Python compile passes.
```

- [ ] **Step 8.4: Commit**

```bash
git add references/subagent-run-store.md references/state-schema.md scripts/validate_state.py evals/check_state_schema.py references/execution-cycle.md templates/fresh-session-prompt.txt docs
git commit -m "feat: track opt-in subagent runs"
```

### Task 9: Add Command Observation Taxonomy

**Files:**
- Create: `references/command-observations.md`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/verification-log.md`

- [ ] **Step 9.1: Add observation schema fixtures**

Allowed categories:

```text
source_failure
missing_local_env
dependency_bootstrap
resource_oom
timeout_or_hang
flaky_test
permission_or_sandbox
tooling_bug
unknown
```

Finished runs may include `unknown` only when `completion_audit.residual_risk` mentions the command.

- [ ] **Step 9.2: Add validation and docs**

Observation shape:

```json
{
  "command": "pnpm test",
  "status": "failed",
  "category": "dependency_bootstrap",
  "evidence": "node_modules missing; install command not yet run",
  "next_action": "Run pnpm install before retrying tests"
}
```

Add execution-cycle policy:

```md
Before claiming root cause for a failed verification command, record a command observation with category, evidence, and next_action. If the category remains unknown at completion, cite it in residual risk.
```

- [ ] **Step 9.3: Verify**

Run:

```bash
python3 evals/check_state_schema.py
python3 -m py_compile scripts/validate_state.py evals/check_state_schema.py
git diff --check -- skills/kws-codex-plan-executor
```

Expected:

```text
State schema checks pass.
Python compile passes.
No whitespace errors.
```

- [ ] **Step 9.4: Commit**

```bash
git add references/command-observations.md references/execution-cycle.md references/headless-runner.md references/state-schema.md scripts/validate_state.py evals/check_state_schema.py docs
git commit -m "feat: classify executor command observations"
```

### Task 10: Release Integration And Full Verification

**Files:**
- Modify: `SKILL.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `HISTORY.md`
- Modify: `docs/how-it-works.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/future-agent-guide.md`
- Modify: `docs/verification-log.md`
- Modify: `evals/run.sh`

- [ ] **Step 10.1: Update release docs**

Update public and maintainer docs only after implementation checks pass:

```text
SKILL.md -> short invariants and validation matrix
ARCHITECTURE.md -> stable control-plane architecture
README.md -> user-facing behavior summary
HISTORY.md -> versioned release note
docs/how-it-works.md -> walkthrough
docs/state-and-logging.md -> state vs journal vs learning logs
docs/evals-and-verification.md -> commands and expected evidence
docs/risks-limitations-deferrals.md -> rejected/deferred GSD-2 features
docs/future-agent-guide.md -> how to continue this work
```

- [ ] **Step 10.2: Add checks to eval suite**

Add these commands to `evals/run.sh`:

```bash
python3 evals/check_event_journal.py
python3 evals/check_run_diffs.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
```

- [ ] **Step 10.3: Run package checks**

Run:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 evals/check_prompt.py --help
python3 evals/check_execution.py --help
python3 evals/check_parse_plan.py --help
python3 evals/check_state_schema.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_event_journal.py
python3 evals/check_run_diffs.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check -- skills/kws-codex-plan-executor
```

Expected:

```text
All deterministic checks pass.
quick_validate.py prints Skill is valid!
git diff --check reports no whitespace errors.
```

- [ ] **Step 10.4: Decide whether to run full headless fixtures**

Run `bash evals/run.sh` when the change touched headless runner behavior, prompt template behavior, or fixture harness behavior.

Use this skip rationale only when appropriate:

```text
Skipped bash evals/run.sh because this pass modified only schema validators, references, and docs. Headless fixture orchestration was not changed.
```

- [ ] **Step 10.5: Commit**

```bash
git add skills/kws-codex-plan-executor
git commit -m "feat: adopt gsd-2 executor control planes"
```

## Implementation Risks

| Risk | Mitigation |
| --- | --- |
| The executor becomes too heavy for small docs-only tasks. | Keep manifest compact and allow docs/read-only policies with low ceremony. |
| JSON state becomes hard to edit by hand. | Keep validation errors precise and add safe repair for mechanical drift. |
| Event journal duplicates learning log. | Make journal project-local execution evidence; keep learning log user-local process learning. |
| Diff policy cannot prevent writes before they happen. | Codex tool hooks are not available inside this skill; enforce pre-contract and post-diff checks. |
| Context budget estimates differ from actual model tokens. | Treat budget as approximate char-based safety, not exact tokenizer truth. |
| Subagent run store encourages accidental parallelism. | Keep opt-in invariant and validate explicit user request/subagents flag. |
| GSD-2 source docs drift after this analysis. | Record commit basis and do not claim latest GSD behavior without re-checking. |

## Completion Definition

The GSD-2 adoption is complete only when:

- Runtime docs, prompt export, state schema, scripts, evals, and maintainer docs agree.
- New state fields are mechanically validated.
- New scripts have deterministic eval coverage.
- `SKILL.md` version and `HISTORY.md` are updated for the behavior release.
- `docs/verification-log.md` contains exact command evidence.
- Final summary clearly states which GSD-2 patterns were adopted, rejected, and deferred.
