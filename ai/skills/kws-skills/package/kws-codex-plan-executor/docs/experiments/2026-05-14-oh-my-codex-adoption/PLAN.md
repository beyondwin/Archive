# OMX-Inspired Executor Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the highest-value `oh-my-codex` workflow patterns into `kws-codex-plan-executor` without importing OMX's tmux/HUD/runtime stack.

**Architecture:** Keep `kws-codex-plan-executor` as a skill-local, Codex App-safe plan executor. Add stronger parsing, context grounding, completion proof, and lifecycle metadata as small deterministic contracts around the existing `.codex-orchestrator/runs/<run_id>/` state model.

**Tech Stack:** Python 3 standard library, Markdown plans, JSON state files, existing skill references/evals, Codex skill package metadata.

---

## Source Basis

This plan is based on a local clone of `Yeachan-Heo/oh-my-codex` at commit
`148effde4e7c6a35f5bdde3ecd5db3488b3156b5` dated `2026-05-12T15:55:29+09:00`.

High-value OMX patterns reviewed:

- Markdown visible-text scanning: `src/planning/markdown-structure.ts`
- Context snapshot / context pack readiness: `skills/ralph/SKILL.md`, `skills/ralplan/SKILL.md`, `src/planning/context-pack-status.ts`
- Completion audit evidence gate: `skills/ralph/SKILL.md`, `src/ralph/completion-audit.ts`
- Explicit terminal lifecycle outcomes: `docs/STATE_MODEL.md`, `docs/contracts/explicit-terminal-stop-model.md`
- Repo-aware DAG handoff: `docs/contracts/repo-aware-team-dag-decomposition.md`, `src/team/dag-schema.ts`
- Adversarial high-risk QA matrix: `skills/ultraqa/SKILL.md`

Existing KWS surfaces to preserve:

- Runtime trigger and mode selection stay in `SKILL.md`.
- Detailed contracts stay in `references/`.
- Reusable deterministic checks stay in `scripts/` and `evals/`.
- Primary run state remains `.codex-orchestrator/runs/<run_id>/state.json`.
- Root `.codex-orchestrator/state.json` remains compatibility-only.
- Subagents stay opt-in.
- Headless runs continue to bootstrap `using-superpowers` and `test-driven-development`.

## Adoption Decisions

| OMX pattern | Decision | Reason |
|---|---|---|
| Visible Markdown scanner | Adopt | Prevents plan parser false positives from fenced code, comments, and indented code. |
| Context snapshot / source basis hashes | Adopt | Makes resume and handoff grounded in stable inputs instead of implicit session memory. |
| Completion audit | Adopt | Prevents false completion when tests pass but prompt/plan requirements are not mapped to artifacts. |
| Terminal lifecycle outcome | Adopt | Separates internal phase from user-facing handoff state. |
| Team DAG | Adopt as optional execution DAG only | Useful for dependency and verification-lane planning without importing team runtime. |
| UltraQA matrix | Adopt only for high-risk verification guidance | Full adversarial QA would make the executor too heavy for normal tasks. |
| tmux/HUD/native hooks/team workers | Reject | These are runtime products, not skill-local executor contracts. |
| Mandatory deslop / architect review | Reject as mandatory | Too heavy for all plan execution. Keep final cleanup/review as risk-scaled optional guidance. |
| Ralplan-first gate | Reject | This executor starts from an explicit `plan=` and should not own plan creation. |

## Target Outcomes

1. `parse_plan.py` ignores hidden Markdown regions while preserving the current task and file-block contract.
2. Every execution run can record a `context.json` snapshot that captures source paths and source hashes.
3. Every finished execution run records a `completion_audit` with prompt-to-artifact checklist and verification evidence.
4. State validation can distinguish `current_phase` from `lifecycle_outcome`.
5. Optional execution DAG metadata can be parsed, validated, and stored without changing subagent policy.
6. High-risk tasks receive adversarial verification prompts without forcing expensive QA on low-risk tasks.
7. Prompt export, headless runner docs, evals, and skill contract checks stay aligned.

## Non-Goals

- Do not add an `omx` dependency.
- Do not add tmux, HUD, native hook, or team runtime assumptions.
- Do not make subagents the default.
- Do not replace `.codex-orchestrator/runs/<run_id>/state.json`.
- Do not require external network or model calls for deterministic validation.
- Do not make every task run a full adversarial QA matrix.
- Do not mutate root docs indexes because these documents are package-internal experiment docs, not Archive library notes.

## File Map

| File | Responsibility |
|---|---|
| `scripts/parse_plan.py` | Visible Markdown parsing, task extraction, file-block extraction, optional DAG marker extraction. |
| `scripts/build_context_snapshot.py` | New deterministic helper to write `.codex-orchestrator/runs/<run_id>/context.json`. |
| `scripts/validate_state.py` | Enforce lifecycle, context, completion audit, and optional DAG state shape. |
| `evals/parser-fixtures/*.yaml` | Parser regression fixtures for hidden Markdown and DAG markers. |
| `evals/check_parse_plan.py` | Fixture runner expectations for visible parsing and optional DAG output. |
| `evals/check_state_schema.py` | State schema tests for lifecycle, context, and completion audit fields. |
| `evals/check_execution.py` | Execution fixture checks for completion audit, context snapshot, and lifecycle outcome. |
| `evals/check_skill_contract.py` | Drift checks that runtime docs, prompt export, and state schema mention the new contracts. |
| `references/state-schema.md` | Canonical state contract. |
| `references/execution-cycle.md` | Interactive run lifecycle and final completion proof. |
| `references/headless-runner.md` | Headless artifacts and context/completion requirements. |
| `references/prompt-export-checklist.md` | Prompt/handoff export checklist aligned with runtime behavior. |
| `references/common-mistakes.md` | Failure modes to avoid after adopting these contracts. |
| `templates/fresh-session-prompt.txt` | Prompt export runtime instructions. |
| `ARCHITECTURE.md` | Stable design update after behavior changes. |
| `HISTORY.md` | Versioned summary after behavior changes. |
| `SKILL.md` | Short invariant and workflow updates only. |

## Milestones

### Milestone 1: Parser Safety

Harden plan parsing before adding new state contracts. This prevents hidden plan text from triggering execution tasks or file scopes.

Acceptance:

- Existing parser fixtures pass.
- New fixtures prove hidden `Task` and `Files` markers are ignored.
- Visible file aliases in English and Korean still parse.
- Out-of-repo path rejection still works.

### Milestone 2: Context Snapshot

Add a deterministic source-basis artifact per run. It records what inputs were used, their hashes, and the minimal grounding fields needed for resume.

Acceptance:

- `build_context_snapshot.py --help` works.
- Context JSON includes `schema_version`, `run_id`, `workspace`, `sources`, and `basis_hash`.
- Missing required source files fail fast.
- State can reference the snapshot path and basis hash.

### Milestone 3: Completion Audit

Add a required final proof object for successful completion. This object maps prompt/plan requirements to changed artifacts and verification evidence.

Acceptance:

- Completed runs without `completion_audit.passed=true` fail state validation.
- Audit evidence must include non-empty `prompt_to_artifact_checklist` and `verification_evidence`.
- Blocked/error runs may omit the passing audit but must set a non-success lifecycle outcome.

### Milestone 4: Lifecycle Outcome

Add `lifecycle_outcome` as a canonical terminal handoff field while keeping `current_phase` as internal progress.

Acceptance:

- Valid outcomes are `finished`, `blocked`, `failed`, `userinterlude`, and `askuserQuestion`.
- Finished runs require completion audit proof.
- Blocked and failed runs require a `handoff_reason`.
- Prompt export tells future agents to report the lifecycle outcome explicitly.

### Milestone 5: Optional Execution DAG

Support optional DAG metadata as a planning aid. The DAG must never bypass current task execution contracts.

Acceptance:

- DAG node ids are unique.
- `depends_on` references existing node ids.
- Cycles are rejected.
- DAG absence keeps current behavior.
- DAG presence stores metadata in state and parsed-plan output only.

### Milestone 6: High-Risk Verification Matrix

Add risk-scaled adversarial verification guidance for high-risk tasks.

Acceptance:

- High-risk tasks prompt for relevant scenarios: stale state, dirty worktree, hung command, misleading success output, malformed input, and resume/cancel when applicable.
- Low-risk tasks do not inherit the full matrix.
- Verification records which scenarios ran, were skipped, or were blocked with a safe substitute.

### Milestone 7: Prompt/Docs/Eval Alignment

Update skill docs, prompt template, and deterministic checks so runtime and prompt export cannot drift.

Acceptance:

- `check_skill_contract.py` fails if the new contracts disappear from runtime docs or prompt export.
- `check_state_schema.py` covers valid and invalid lifecycle/completion/context cases.
- `check_execution.py` can enforce context and completion audit expectations in fixtures.
- `HISTORY.md` and `ARCHITECTURE.md` describe the new behavior.

## Task Plan

### Task 1: Harden Plan Parser With Visible Markdown Scanning

**Files:**
- Modify: `scripts/parse_plan.py`
- Modify: `evals/check_parse_plan.py`
- Create: `evals/parser-fixtures/03-hidden-task-in-fence.yaml`
- Create: `evals/parser-fixtures/04-hidden-files-in-comment.yaml`
- Create: `evals/parser-fixtures/05-visible-files-after-fence.yaml`

- [x] Add a visible-Markdown normalizer that preserves line count and blanks hidden fenced code, HTML comments, and indented code.
- [x] Run parser fixtures and confirm current fixtures still pass.
- [x] Add hidden-task fixture and confirm the parser ignores the fenced `Task`.
- [x] Add hidden-files fixture and confirm the parser ignores comment-contained `Files`.
- [x] Add visible-after-fence fixture and confirm normal parsing resumes after a closed fence.

### Task 2: Add Per-Run Context Snapshot Helper

**Files:**
- Create: `scripts/build_context_snapshot.py`
- Modify: `references/state-schema.md`
- Modify: `evals/check_state_schema.py`

- [x] Implement source path validation inside repo root.
- [x] Hash plan/spec/docs source files with SHA-256.
- [x] Write `.codex-orchestrator/runs/<run_id>/context.json`.
- [x] Add state fields `context_snapshot_path` and `context_basis_hash`.
- [x] Add state schema tests for valid, missing, and mismatched context fields.

### Task 3: Add Completion Audit State Contract

**Files:**
- Modify: `scripts/validate_state.py`
- Modify: `references/state-schema.md`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `evals/check_state_schema.py`
- Modify: `evals/check_execution.py`

- [x] Define `completion_audit` shape in state schema.
- [x] Require passing audit only for `lifecycle_outcome=finished`.
- [x] Require `prompt_to_artifact_checklist` and `verification_evidence` to be non-empty.
- [x] Allow blocked/failed runs to omit passing audit when `handoff_reason` explains why.
- [x] Add deterministic checks for each outcome.

### Task 4: Add Terminal Lifecycle Outcome

**Files:**
- Modify: `scripts/validate_state.py`
- Modify: `references/state-schema.md`
- Modify: `references/execution-cycle.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`

- [x] Add `lifecycle_outcome` to top-level state.
- [x] Add valid outcome enforcement.
- [x] Add `handoff_reason` requirement for blocked, failed, userinterlude, and askuserQuestion.
- [x] Update final summary instructions to report outcome, evidence, artifacts/state, and handoff.
- [x] Add contract checks that prompt export includes the same lifecycle vocabulary.

### Task 5: Add Optional Execution DAG Metadata

**Files:**
- Modify: `scripts/parse_plan.py`
- Modify: `references/state-schema.md`
- Modify: `evals/check_parse_plan.py`
- Create: `evals/parser-fixtures/08-execution-dag-valid.yaml`
- Create: `evals/parser-fixtures/09-execution-dag-cycle.yaml`

- [x] Parse optional `Depends on:` lines from visible task bodies.
- [x] Validate dependency ids against parsed task ids.
- [x] Reject cycles deterministically.
- [x] Emit `depends_on` in parsed JSON.
- [x] Store optional task dependency metadata in state without changing task status semantics.

### Task 6: Add High-Risk Verification Matrix Guidance

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/prompt-export-checklist.md`
- Modify: `templates/fresh-session-prompt.txt`
- Modify: `evals/check_skill_contract.py`

- [x] Add high-risk verification matrix guidance under risk-scaled verification.
- [x] Require scenario evidence or explicit safe substitute for high-risk tasks.
- [x] Keep low/mid risk verification unchanged except for optional reporting.
- [x] Add prompt-export checks that high-risk verification guidance appears.

### Task 7: Align Skill Runtime Docs And History

**Files:**
- Modify: `SKILL.md`
- Modify: `ARCHITECTURE.md`
- Modify: `HISTORY.md`
- Modify: `references/common-mistakes.md`
- Modify: `ai/skills/kws-skills/manifest.json`
- Modify: `ai/skills/kws-skills/README.md`
- Modify: `ai/skills/kws-skills/CHANGELOG.md`

- [x] Update `SKILL.md` metadata version and short invariants only.
- [x] Record the behavior change in `HISTORY.md`.
- [x] Update `ARCHITECTURE.md` with the new context/completion/lifecycle contracts.
- [x] Add common mistakes for hidden Markdown, missing audit proof, and lifecycle/phase confusion.
- [x] Update package-level metadata after behavior changes.

### Task 8: Run Narrow And Package Validation

**Files:**
- Read: `references/change-protocol.md`
- Read: `evals/run.sh`

- [x] Run `python3 scripts/parse_plan.py --help`.
- [x] Run `python3 scripts/validate_state.py --help`.
- [x] Run `python3 scripts/build_context_snapshot.py --help`.
- [x] Run `python3 evals/check_parse_plan.py --fixture evals/parser-fixtures/03-hidden-task-in-fence.yaml`.
- [x] Run every parser fixture.
- [x] Run `python3 evals/check_state_schema.py`.
- [x] Run `python3 evals/check_execution.py` against affected execution fixtures.
- [x] Run `python3 evals/check_skill_contract.py --skill SKILL.md`.
- [x] Run `python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`.
- [x] Run `../../tests/test-sync.sh`.

## Risk Register

| Risk | Mitigation |
|---|---|
| Parser normalizer changes task body offsets unexpectedly | Preserve line count and parse only normalized text; test visible-after-fence behavior. |
| Completion audit makes blocked runs impossible to report | Gate audit only for `lifecycle_outcome=finished`; require `handoff_reason` for terminal non-success outcomes. |
| Context snapshot stores sensitive or absolute home paths | Store repo-relative source paths and hashes; reject out-of-repo paths. |
| Optional DAG becomes a hidden execution engine | Keep DAG as metadata only; task contracts and status transitions remain unchanged. |
| Prompt export drifts from runtime execution | Extend `check_skill_contract.py` and prompt checklist. |
| High-risk matrix bloats normal execution | Trigger only for `risk=high` or explicit plan acceptance requirements. |

## Self-Review

- Spec coverage: All accepted OMX patterns from the prior analysis map to tasks 1-6. Rejected runtime-heavy OMX features are listed as non-goals.
- Placeholder scan: No unresolved placeholder markers are intentionally present.
- Type consistency: `context_snapshot_path`, `context_basis_hash`, `completion_audit`, `lifecycle_outcome`, and `handoff_reason` are named consistently across tasks.
- Execution readiness: The companion implementation document provides the code-level details needed to implement each task.
