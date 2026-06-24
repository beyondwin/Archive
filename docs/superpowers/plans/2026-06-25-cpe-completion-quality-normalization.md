# CPE Completion Quality Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten CPE finished-state quality validation so completion audits and operational run quality remain machine-readable after execution.

**Architecture:** Keep state validation as the single deterministic gate. Add failing eval cases first, then update `validate_state.py` and the deterministic static runner to emit the stricter shape. Update skill contract docs in the same change.

**Tech Stack:** Python 3 standard library, Markdown docs, existing `skills/kws-codex-plan-executor/evals/run.sh` harness.

## Global Constraints

- Do not weaken dispatch safety gates.
- Do not migrate archived run state automatically.
- Preserve v2.19/v2.20 compatibility unless v2.22 operational fields are present.
- Keep runtime artifacts under `~/.codex/orchestrator/<run_id>/`.

---

## Task 1: Validate Completion Audit List Shapes

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`

**Interfaces:**
- Consumes: finished `completion_audit` object.
- Produces: validator errors for scalar `residual_risk` and scalar `verification_evidence`.

- [ ] Add failing eval cases for string `completion_audit.residual_risk` and string `completion_audit.verification_evidence`.
- [ ] Run `python3 skills/kws-codex-plan-executor/evals/check_state_schema.py` and confirm RED.
- [ ] Require list-shaped `prompt_to_artifact_checklist`, `verification_evidence`, and `residual_risk` for finished states.
- [ ] Re-run the focused eval and confirm GREEN.

## Task 2: Require Embedded Run Quality For Operational Finished State

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/static_execution_runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`

**Interfaces:**
- Consumes: v2.22 operational fields such as `execution_worktree`, `delegation_policy`, and `preflight_bootstrap`.
- Produces: required embedded `run_quality` with `readiness`, `dispatch_consistency`, `context_quality`, and `verification_quality`.

- [ ] Add failing eval cases for missing `run_quality` and missing `run_quality.verification_quality`.
- [ ] Run `python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py` and confirm RED.
- [ ] Update validator and static runner state output.
- [ ] Re-run focused evals and confirm GREEN.

## Task 3: Sync Contract Docs And Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: implementation behavior from Tasks 1 and 2.
- Produces: documented finished-state completion quality contract.

- [ ] Document list-shaped completion audit fields.
- [ ] Document required embedded operational `run_quality`.
- [ ] Run focused evals, full eval harness, py_compile, shell syntax check, and `git diff --check`.
