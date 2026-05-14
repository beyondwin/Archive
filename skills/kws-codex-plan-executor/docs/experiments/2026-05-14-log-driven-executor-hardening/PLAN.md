# Log-Driven Executor Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the latest `kws-codex-plan-executor` learning-log findings into deterministic executor safeguards, reporting fixes, and verification policy updates.

**Architecture:** Keep the executor skill-local and file-based. Improve the existing learning-log helper, add a read-only health reporter, and tighten execution guidance around isolated worktree setup, verification serialization, resource triage, and carry-forward acceptance evidence.

**Tech Stack:** Python 3 standard library, JSON/JSONL learning logs, Markdown references, existing deterministic evals, `.codex-orchestrator/runs/<run_id>/state.json`.

---

## Source Basis

This plan is based on the five latest user-local run records under:

```text
~/.codex/learning/kws-codex-plan-executor/
```

The reviewed runs were:

| Run | Repo | Final status | Notable events |
| --- | --- | --- | --- |
| `20260514T020039Z-gasstation-codex-build-test-speed-improvements-d767526dd815-b2327a` | GasStation | stale or unclosed | Android SDK `local.properties` missing in isolated worktree |
| `20260513T194459Z-fixthis-codex-test-speed-optimization-49b3bb4189ef-cec3bf` | FixThis | success | Android SDK `local.properties` missing in isolated worktree |
| `20260513T193815Z-fixthis-codex-ui-ux-polish-49b3bb4189ef-0174ce` | FixThis | success | zero notable events, which is normal for routine success |
| `20260513T193445Z-readmates-codex-readmates-build-optimization-20260-43f6856ca32c-01cd1b` | ReadMates | success | dependency bootstrap, Docker memory, router lazy tests, bundle-size carry-forward |
| `20260513T193443Z-readmates-codex-readmates-test-runtime-optimizatio-43f6856ca32c-2c4b36` | ReadMates | success | parallel Gradle test output collision |

## 2026-05-15 Correction

The later PromptGate adapter-runtime run showed that the original stale-run
interpretation was too aggressive. `meta.pid` is written by the short-lived
`append_learning_event.py init-run` helper process, not by a durable Codex
executor session. A dead helper pid is expected after initialization and must
not classify a run as stale by itself.

For run lifecycle reporting, prefer the narrower plan in
`../2026-05-14-run-lifecycle-drift-hardening/PLAN.md`. This broader hardening
plan remains valid for local-env preflight, verification serialization,
resource triage, carry-forward acceptance, and method audit, but stale
classification must be project-state-aware.

## Problems To Solve

1. `index.jsonl` keeps the initial `outcome=unknown` even when a run later writes `final.json` with `outcome=success`.
2. A run can be ambiguous after writing `meta.json` but before `close-run`,
   leaving `ended_at=null` and no `final.json`; helper-pid liveness is not
   enough to decide whether it is abandoned.
3. New isolated worktrees do not carry ignored local environment files such as Android `local.properties`, which can make baseline checks fail before touching project code.
4. Verification command parallelization can collide when Gradle Test tasks share output directories in the same worktree.
5. Docker build failures can look like project compile failures when the actual cause is container OOM.
6. Sequential tasks can share one acceptance metric, such as bundle size, and an earlier task may need a `yellow` carry-forward state instead of being treated as fully green.
7. React Router lazy-route work has predictable test harness fallout that should be part of the allowed edit scope.
8. `event_count=0` is a valid routine-success signal, not a warning by itself.
9. Current run records prove command outcomes and artifacts, but they do not prove whether the required phase methods were actually applied. For example, a review phase should show review findings or a no-findings risk statement, and an implementation phase that claims TDD should show RED/GREEN evidence.

## Non-Goals

- Do not replace the existing learning-log sharding layout.
- Do not make learning-log failure block primary implementation work.
- Do not introduce a database, daemon, UI dashboard, or external dependency.
- Do not auto-copy secret or private env files.
- Do not make all verification serial; serialize only commands with conflicting resource keys.
- Do not make bundle-size carry-forward a generic failure. It should be a tracked unresolved criterion when a dependent task remains.
- Do not record every skill mention or command as method usage. The audit should cover required phase methods only, with evidence references.
- Do not change prompt or handoff export behavior except where it references these runtime policies.

## File Map

| File | Responsibility |
| --- | --- |
| `scripts/append_learning_event.py` | Keep `index.jsonl`, `meta.json`, and `final.json` outcome fields coherent when runs close. |
| `scripts/check_learning_log_health.py` | New read-only reporter for latest runs, stale detection, event-count semantics, and index/final mismatches. |
| `evals/check_learning_log.py` | Deterministic tests for close-run index coherence, stale-run classification, and zero-event success handling. |
| `references/learning-log.md` | Canonical source-of-truth rules for index, meta, final, stale runs, and routine success. |
| `references/execution-cycle.md` | Worktree local-env preflight, Gradle verification serialization, Docker OOM triage, and acceptance carry-forward rules. |
| `references/headless-runner.md` | Same runtime cautions for fresh `codex exec` processes. |
| `references/state-schema.md` | Optional state shape for carried acceptance criteria and verification resource evidence. |
| `scripts/validate_state.py` | Enforce method-audit evidence when required methods are declared. |
| `references/common-mistakes.md` | Known interpretation mistakes from recent logs. |
| `docs/state-and-logging.md` | Maintainer explanation of learning-log health and source-of-truth precedence. |
| `docs/evals-and-verification.md` | Commands and fixture expectations for the new deterministic checks. |
| `docs/risks-limitations-deferrals.md` | Durable limitations: env files are detected, not copied automatically; stale detection is diagnostic. |
| `docs/verification-log.md` | Evidence for the implementation run. |
| `ARCHITECTURE.md` | Stable description if the learning-log close/report contract changes. |
| `HISTORY.md` | Versioned summary if behavior changes ship. |
| `SKILL.md` | Short invariant updates only if execution-cycle requirements become mandatory runtime contract. |

## Design Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Learning-log source of truth | `final.json` wins for terminal outcome; `meta.json` mirrors it; `index.jsonl` must be updated or clearly marked as append-only start index | Current analysis is misleading if it reads only `index.jsonl`. |
| Stale run handling | Resolve terminal `final.json` first, then project-local state, then classify old inactive state as `stale_candidate` | Avoids treating active runs as abandoned because the helper pid has exited. |
| Local env files | Detect and report missing repo-specific ignored files; do not auto-copy by default | These files may contain machine-local paths or secrets. |
| Verification parallelization | Add command resource keys and serialize conflicting keys | Keeps safe parallelism while avoiding Gradle Test output collisions. |
| Docker OOM triage | Inspect OOM evidence before root-causing as compile failure | Recent ReadMates failure was environment memory, not source code. |
| Acceptance carry-forward | Add explicit `carried_acceptance` evidence for sequential metrics | Prevents premature green status when a later task must finish the criterion. |
| Method audit | Record required phase methods as evidence-backed `applied`, `missing`, or `waived` entries | This proves whether TDD, review, and completion verification were actually applied instead of merely requested. |
| Zero-event success | Treat as normal when `final.outcome=success` and helper did not report logging failure | Learning events are notable-boundary-only, not routine task logs. |

## Milestones

### Milestone 1: Learning-Log Outcome Coherence

Make closed runs easy to summarize correctly.

Acceptance:

- `close-run --outcome success` updates `meta.json` and `final.json` as today.
- A health reporter resolves the terminal outcome from `final.json` when present.
- If index entries remain append-only, docs and report output label them as start records, not terminal state.
- Deterministic tests cover a run whose index says `unknown` but final says `success`.

### Milestone 2: Stale Run Health Reporting

Detect likely abandoned or interrupted runs without mutating them and without
false-staling active project state.

Acceptance:

- `check_learning_log_health.py --latest 5` prints JSON with
  `status=success|blocked|error|in_progress|needs_finalization|unknown|stale_candidate`.
- A run with no `final.json` but readable active project-local state reports
  `in_progress` or `needs_finalization`.
- `meta.pid` or `meta.helper_pid` liveness is informational only and never the
  primary stale signal.
- `stale_candidate` requires no `final.json`, no active project-state progress,
  an old `timestamps.updated_at` or equivalent state-age signal, and no cleaner
  explanation such as pending final verification.
- Missing `events.jsonl` is not an error.

### Milestone 3: Isolated Worktree Local-Env Preflight

Prevent baseline failures caused by missing ignored local config.

Acceptance:

- Execution docs require a local-env preflight immediately after worktree creation and before baseline verification.
- Android projects check for `local.properties` or an honest substitute.
- Node/front-end projects check dependency install state before baseline build.
- The policy states that agents should ask or report before copying ignored files.

### Milestone 4: Verification Resource Serialization

Avoid known command-level output collisions.

Acceptance:

- Execution docs define resource keys for verification commands.
- Gradle Test commands sharing the same project and task output directory must run serially.
- Commands with distinct resource keys can still run in parallel.
- State can record the chosen serialization reason when parallelism is skipped.

### Milestone 5: Resource Failure Triage

Add deterministic triage steps for Docker/Gradle failures that often masquerade as source failures.

Acceptance:

- Docker build failure triage includes checking container OOM evidence when a builder container exists.
- Gradle daemon disappearance triage distinguishes OOM, metaspace, daemon crash, and compile failure.
- The executor records the root-cause category in learning-log events when notable.

### Milestone 6: Carry-Forward Acceptance Evidence

Track sequential metrics without prematurely closing them.

Acceptance:

- State schema allows an optional `carried_acceptance` object per task.
- The object includes `metric`, `current_value`, `baseline_value`, `reason`, `depends_on_task`, and `next_action`.
- Finished runs cannot leave carried acceptance unresolved unless a later task resolves it or completion audit explains why the final state is still acceptable.

### Milestone 7: Route-Lazy Test Harness Guidance

Document the predictable allowed-edit expansion for React Router lazy route tasks.

Acceptance:

- Route lazy tasks can include route tests and test harness helpers in `allowed_edits`.
- Execution docs mention `hydrateFallbackElement`, async route rendering, and request shim timing as expected verification concerns.
- The guidance remains framework-specific and does not affect non-React projects.

### Milestone 8: Phase Method Audit

Record whether required work methods were actually applied in each execution
phase.

Acceptance:

- State schema allows a top-level `method_audit` object with `required`,
  `applied`, `missing`, and `waived` lists.
- Applied entries must include `skill`, `phase`, `status=applied`, and evidence
  references to task state, review findings, or verification evidence.
- `test-driven-development` cannot be marked applied without RED and GREEN
  evidence references.
- `review` cannot be marked applied without findings or an explicit no-findings
  residual-risk statement.
- `verification-before-completion` cannot be marked applied without command
  evidence.
- Missing required methods fail validation for `lifecycle_outcome=finished`
  unless they are explicitly waived with a reason.

### Milestone 9: Docs, Evals, And Release Alignment

Keep behavior, references, and checks synchronized.

Acceptance:

- `check_learning_log.py` covers the new log-health and outcome cases.
- `check_skill_contract.py` covers any mandatory wording added to `SKILL.md`, prompt export, or runtime references.
- `HISTORY.md`, `ARCHITECTURE.md`, and maintainer docs are updated for behavior changes.
- `docs/verification-log.md` records the implementation evidence.

## Task Plan

### Task 1: Add Learning-Log Health Fixtures

**Files:**
- Modify: `evals/check_learning_log.py`
- Create: fixture data inside temporary directories created by the eval script.

- [ ] Add a fixture for `index_unknown_final_success`.
- [ ] Add a fixture for `zero_event_success`.
- [ ] Add a fixture for `active_project_state_dead_helper_pid`.
- [ ] Add a fixture for `old_project_state_stale_candidate`.
- [ ] Run `python3 evals/check_learning_log.py`.
- [ ] Commit: `test: cover learning log health cases`.

### Task 2: Make Outcome Resolution Deterministic

**Files:**
- Modify: `scripts/append_learning_event.py`
- Create: `scripts/check_learning_log_health.py`
- Modify: `references/learning-log.md`
- Modify: `docs/state-and-logging.md`

- [ ] Add an `outcome` resolver that prefers `final.json`, then `meta.json`, then index start record.
- [ ] Add `check_learning_log_health.py --latest N --json`.
- [ ] Document that index entries are start records unless explicitly rewritten.
- [ ] Run `python3 scripts/check_learning_log_health.py --latest 5 --json`.
- [ ] Run `python3 evals/check_learning_log.py`.
- [ ] Commit: `feat: report learning log terminal outcomes`.

### Task 3: Add Stale Run Detection

**Files:**
- Modify: `scripts/check_learning_log_health.py`
- Modify: `evals/check_learning_log.py`
- Modify: `references/learning-log.md`
- Modify: `docs/risks-limitations-deferrals.md`

- [ ] Add dead-pid detection using `os.kill(pid, 0)` with permission-aware fallback.
- [ ] Add `--stale-after-minutes` with a conservative default of `30`.
- [ ] Classify stale only when no final outcome exists.
- [ ] Record stale detection as diagnostic and non-mutating.
- [ ] Run `python3 evals/check_learning_log.py`.
- [ ] Commit: `feat: detect stale executor learning runs`.

### Task 4: Add Local-Env Preflight Guidance

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `references/common-mistakes.md`
- Modify: `docs/evals-and-verification.md`

- [ ] Add a post-worktree, pre-baseline preflight section.
- [ ] Include Android `local.properties` detection with no automatic copy.
- [ ] Include Node dependency install-state detection.
- [ ] Include Docker memory note for build tasks.
- [ ] Run `python3 evals/check_skill_contract.py --skill SKILL.md` if contract wording is changed.
- [ ] Commit: `docs: add worktree local environment preflight`.

### Task 5: Add Verification Resource-Key Policy

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/state-schema.md`
- Modify: `docs/how-it-works.md`

- [ ] Define `verification_resource_key` examples for Gradle, Node, Docker, and browser commands.
- [ ] Require serial execution for identical Gradle Test output keys in one worktree.
- [ ] Add optional state evidence for serialization decisions.
- [ ] Run `python3 evals/check_state_schema.py` if state shape changes.
- [ ] Commit: `docs: define verification resource serialization`.

### Task 6: Add Docker And Gradle Failure Triage

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/common-mistakes.md`
- Modify: `docs/evals-and-verification.md`

- [ ] Add Docker OOM triage commands with redaction-safe evidence.
- [ ] Add Gradle daemon disappearance triage categories.
- [ ] Add guidance for when to append `verification_failure`, `recurring_issue`, or `successful_workaround`.
- [ ] Commit: `docs: add resource failure triage guidance`.

### Task 7: Add Carried Acceptance State Contract

**Files:**
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`

- [ ] Write failing state-schema tests for unresolved carried acceptance on finished runs.
- [ ] Add optional `tasks.<id>.carried_acceptance`.
- [ ] Permit unresolved carry-forward during intermediate phases.
- [ ] Require final resolution or completion-audit explanation for finished outcomes.
- [ ] Run `python3 evals/check_state_schema.py`.
- [ ] Commit: `feat: validate carried acceptance evidence`.

### Task 8: Add Route-Lazy Allowed-Edit Guidance

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/common-mistakes.md`

- [ ] Add route-lazy risk note for React Router tasks.
- [ ] Mention `hydrateFallbackElement`, async assertions, and request shim updates.
- [ ] Keep the guidance scoped to frontend route lazy work.
- [ ] Commit: `docs: document route lazy verification risks`.

### Task 9: Add Phase Method Audit State Contract

**Files:**
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`
- Modify: `references/execution-cycle.md`
- Modify: `references/headless-runner.md`
- Modify: `docs/state-and-logging.md`

- [ ] Write failing state-schema tests for a finished implementation run that requires TDD but has no RED/GREEN evidence.
- [ ] Add top-level `method_audit.required`, `method_audit.applied`, `method_audit.missing`, and `method_audit.waived`.
- [ ] Validate `test-driven-development` evidence references for implementation work.
- [ ] Validate review evidence for review phases and verification evidence before completion.
- [ ] Permit docs-only or read-only analysis runs to waive implementation methods with explicit rationale.
- [ ] Run `python3 evals/check_state_schema.py`.
- [ ] Commit: `feat: validate phase method audit evidence`.

### Task 10: Align Package Docs And Verification Log

**Files:**
- Modify: `ARCHITECTURE.md`
- Modify: `HISTORY.md`
- Modify: `README.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/verification-log.md`
- Modify: `SKILL.md` only if new runtime invariants are promoted to the top-level contract.

- [ ] Update stable docs for behavior changes.
- [ ] Add verification-log entry with commands and skipped checks.
- [ ] Run:

```bash
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 scripts/append_learning_event.py --help
python3 scripts/check_learning_log_health.py --help
python3 evals/check_learning_log.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

- [ ] Commit: `chore: document log-driven executor hardening`.

## Final Verification

Run from `skills/kws-codex-plan-executor/`:

```bash
python3 evals/check_learning_log.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

If any check is skipped, record the reason in `docs/verification-log.md` with an honest substitute.

## Self-Review Notes

- The plan is scoped to the learning-log and execution policies surfaced by the latest five logs.
- It does not require changing user project code.
- It separates diagnostics from mutation: stale detection and local-env checks report; they do not auto-fix.
- It preserves the notable-boundary-only learning-log policy.
- It does not require subagents, external services, or network access.
