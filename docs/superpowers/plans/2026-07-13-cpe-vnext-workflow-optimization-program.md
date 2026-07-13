# CPE vNext Quality-First Workflow Optimization Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one clean-cut CPE vNext runtime that closes the release trust boundary, supports one spec with one or many plans, removes duplicate review and verification work, and proves the final checkpoint once.

**Architecture:** Three sequential implementation plans share one approved design and one final program gate. Plan 1 establishes immutable trust and closure contracts, Plan 2 replaces the runtime with one PlanGraph-driven lifecycle, and Plan 3 deduplicates quality work and executes the only final R3/R2 proof sequence.

**Tech Stack:** Python 3 standard library, Git objects/worktrees, JSON/JSONL, Codex CLI, Bash eval harness, Bun repository checks, Graphify.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-13-cpe-vnext-quality-first-workflow-optimization-design.md` at or after commit `80b9850`.
- Required order: Plan 1, then Plan 2, then Plan 3, then the Program Final Gate contained in Plan 3.
- Complete every approved task. Local work, tests, and elapsed time have no success-producing budget.
- Credentialed proof retains the `2/4/6` safety ceilings and requires fresh explicit authority at execution time.
- Do not migrate, resume, validate, reconcile, or repair v3 or v4 runs with vNext.
- Support both one spec plus one plan and one spec plus multiple plans with an optional program plan.
- Active model routes remain exactly `gpt-5.6-sol/high` for core work and `gpt-5.6-terra/high` for bounded read-only scouting.
- The 50 percent efficiency reduction is measured and reported; it is not a release gate.
- P0/P1 detection, false-success, privacy, state, evidence, duplicate-call, and release-truth requirements are hard gates.
- Work in an isolated worktree during execution; preserve unrelated user changes and stage exact task files.

## Authoritative Execution Order

| Stage | Plan | Deliverable | Depends on |
| --- | --- | --- | --- |
| 1 | `2026-07-13-cpe-vnext-plan-1-release-trust-foundation.md` | Git-object TrustRoot, closure transaction, four-lane review contracts | Approved design |
| 2 | `2026-07-13-cpe-vnext-plan-2-runtime-multiplan-simplification.md` | Single vNext lifecycle, DocumentSet, PlanGraph, multi-plan checkpoints | Stage 1 verified checkpoint |
| 3 | `2026-07-13-cpe-vnext-plan-3-quality-deduplication-measurement.md` | Invariant review, exact evidence reuse, metrics, representative evals | Stage 2 verified checkpoint |
| 4 | Plan 3 Program Final Gate | Final R3 review, one fix wave, cost-free gate, R2 staged proof, metadata closeout | Stage 3 frozen checkpoint and current credential authority |

No stage may use a credentialed call before Stage 4. A Stage 4 finding that changes runtime returns to the affected plan task, creates a new frozen checkpoint, and reruns cost-free evidence before any credentialed proof.

## Spec Coverage Map

| Spec sections | Owning stage |
| --- | --- |
| S1.8 release trust and closure machinery | Plan 1 |
| S1.7 DocumentSet and PlanGraph | Plan 2 Tasks 1-3 |
| S1.9 runtime, validation, test simplification | Plan 2 Tasks 4-6 |
| S1.10 quality deduplication and measurement | Plan 3 Tasks 1-4 |
| S1.11 hard quality gates | Plan 3 Tasks 4-5 and Program Final Gate |
| S1.12 error and recovery policy | Plans 1-3 typed outcomes |
| S1.13 verification matrix | Focused tasks plus Program Final Gate |
| S1.14 artifact shape | This program plan and three implementation plans |
| S1.15 completion criteria | Program Final Gate |

## File Ownership Map

- Plan 1 owns release policy/object loading, release transaction state, release review schemas, and their focused evals.
- Plan 2 owns plan/spec compilation, manifest/task identities, kernel/projector/scheduler/validation cutover, old-path removal, and multi-plan evals.
- Plan 3 owns invariant review, verification planning, prompt deduplication, metrics, representative comparison, and final-gate orchestration.
- Shared files such as `scripts/cpe.py`, `evals/maintained-checks.json`, active docs, and Graphify transfer ownership in stage order. A later plan may change them only for its declared interface.

## Checkpoint Contract

- Each implementation plan ends with a real verified Git checkpoint and records its commit, tree, plan hash, spec hash, and upstream checkpoint.
- Plan 2 compiles these documents into one `PlanGraph` dogfood fixture.
- Plan 3 freezes the final runtime checkpoint before R3.
- Program success requires all three plan checkpoints, one global integration gate, one terminal release generation, and one metadata-only closeout descendant.

## Final Handoff Contract

The program is complete only when the final report records:

- Plan 1, 2, and 3 checkpoint commits and graph hashes;
- R1 closed before runtime cutover;
- final-checkpoint R3 four-lane verdict with no unresolved P0/P1 findings;
- cost-free CPE and repository checks passing;
- R2 terminal staged proof or an honest current-authority blocker;
- proof checkpoint and metadata-only closeout commit;
- measured model, review, suite, token, retry, and wall-clock comparison;
- truthful R4, R5, and R6 residual status.
