# How it works — a guided walkthrough

A narrative explanation of one plan execution end-to-end. For the formal
contract see [`../SKILL.md`](../SKILL.md); for system-level design see
[`../ARCHITECTURE.md`](../ARCHITECTURE.md). This document focuses on the
*sequence of what happens* so a reader can build a mental model.

## The actors

1. **You (the user)** — invoke the skill with a plan path and spec path.
2. **Claude Code (Opus orchestrator)** — loads SKILL.md, runs the 3-phase
   lifecycle.
3. **Sub-agents (Sonnet)** — dispatched by the orchestrator per task.
4. **The git worktree** — isolated repo state where all plan work lives.
5. **The learning log** — user-local JSONL recording notable boundaries
   across all runs.

## A run, step by step

### Phase 0 — Setup (once per run)

The user invokes:
```
/kws-claude-multi-agent-executor plan=docs/plans/2026-05-12-foo.md spec=docs/specs/2026-05-12-foo-design.md
```

The orchestrator:

1. **Reads invocation parameters** and parses the plan + spec files. Detects
   task list, risk tiers, dependencies, plan2 chaining, docs scope.
2. **Creates a git worktree** under `<repo>/../worktrees/plan-<timestamp>/`
   (or `<repo>/.claude/worktrees/...` depending on mode).
3. **Writes `state.json`** at `<worktree>/.orchestrator/state.json` with
   initial task statuses (`pending`), risk tiers, plan/spec paths, run
   identifiers.
4. **Step 7.5 — MANDATORY init-run** (v2.8.1+). Runs `append_learning_event.py
   init-run ...` and exports `MAE_LEARNING_RUN_ID`. Prints either
   `LEARNING_LOG_INIT: RUN_ID=<id>` (success) or `LEARNING_LOG_INIT:
   SKIPPED (...)` (helper missing/broken). This marker is the post-run
   adherence audit signal.
5. **Optional Plan Reviewer dispatch** if plan is `mid` or `high` risk —
   sub-agent emits PASS/WARN/FAIL on the plan itself before any Implementer
   work starts. Catches structural plan defects early.

After Phase 0, the run is "live": worktree exists, state is committed,
learning-log run dir exists with `outcome=unknown`.

### Phase 1 — Per-task cycle (repeated for each task)

For each task in the plan:

1. **Risk-tier dispatch**. Reads risk from plan or invocation override.
   `low` → relaxed TDD, single retry. `mid` → TDD required, 2 retries.
   `high` → strict TDD, 3 retries + spec-edit branch on consistent SPEC_FAULT.
2. **Implementer dispatch (Agent tool)**. Sends `implementer-prompt.md`
   template with:
   - exact spec excerpt
   - exact plan task block
   - relevant context (existing files to read, conventions)
   - `effort_guidance` substring derived from task_complexity (SMALL/MEDIUM/LARGE)
   The Implementer writes code, runs tests, emits FILES_CHANGED + commit
   message + ESCALATE marker if blocked.
3. **Combined Reviewer dispatch**. Sends `reviewer-prompt.md` with the same
   spec excerpt + the diff from Implementer's commit. Reviewer:
   - Invokes `Skill("superpowers:requesting-code-review")` for checklist grounding (v2.8+)
   - Emits **`SPEC_COVERAGE_WALK:`** block (v2.9.0+) — sub-step A enumerate
     stated bullets, sub-step B adversarial generation from meta-rules
   - Scores SPEC_SCORE + QUALITY_SCORE (P4 0.0-1.0, 0.1 quantized)
   - Diagnoses SPEC_FAULT (`spec_contradicts | unclear | implementer_omitted | none`)
   - Lists SPEC_ISSUES and QUALITY_ISSUES with file:line + ISSUE_KEY
4. **Retry loop**. If SPEC_STATUS=FAIL or QUALITY_STATUS=FAIL, orchestrator
   dispatches a fresh Implementer with `previous_issues` from the Reviewer.
   Retry budget is risk-tier dependent. If exhausted → ESCALATE.
5. **Step 3.5 — learning-event candidate scan** (v2.8+). Orchestrator
   scans `<worktree>/.orchestrator/learning_events/` for JSON candidates
   left by sub-agents (Reviewer writes when WARN/FAIL; Verifier when
   verification_failure; Implementer when escalation/workaround). For each
   candidate, orchestrator runs `append_learning_event.py append --run-id
   $MAE_LEARNING_RUN_ID` and deletes the candidate file.
6. **Verifier dispatch** (after Reviewer PASS, before commit). Sends
   `verifier-prompt.md` with the spec acceptance criteria. Verifier:
   - Invokes `Skill("superpowers:verification-before-completion")` for checklist (v2.8+)
   - Re-runs acceptance criteria independently
   - Emits PASS/FAIL with concrete evidence
7. **Commit on success**. Orchestrator commits the task's changes to the
   worktree branch with a descriptive message and updates `state.json`.

The cycle repeats for each task. On any unrecoverable ESCALATE → orchestrator
calls `close-run --outcome blocked` and halts.

### Phase 2 — Cleanup (once at end, on success path)

1. **Docs Updater dispatch**. Sub-agent reads the final diff and updates
   docs listed in `docs_scope` (typically README / CHANGELOG / ADR-class
   docs). Emits per-file change set.
2. **Final commit** consolidating docs updates onto the worktree branch.
3. **Step 2 — `close-run --outcome success`**. Updates `meta.json` with
   `ended_at`, `outcome=success`, `event_count=<N>`.
4. **Reports to the user**: branch name, commit list, test results, score
   summary, learning-events summary (if any), and an indication of whether
   to merge.

### Exit paths summary

| Exit path | `meta.outcome` | When |
|-----------|----------------|------|
| Phase 2 reached normally | `success` | All tasks complete + docs updated |
| ESCALATE that halts run | `blocked` | Retries exhausted on a non-skippable task |
| State-write failure at Transition T3 | `blocked` | Disk full / permission denied between Phase 1 and Phase 2 |
| User abort / hook denial | `aborted` | `claude -p` hook blocks a tool call mid-run |
| Hard crash / unhandled exception | `unknown` | Orchestrator process died before close-run |

## Concurrency

Multiple plan runs can execute in parallel:
- Different repos: trivially fine, isolated worktrees + isolated learning-log run dirs.
- Same repo, different plans: each gets its own worktree (`plan-<timestamp>`)
  + its own run_id + its own MAE_LEARNING_RUN_ID. No shared state.
- Resume Chain inheritance: the chained `claude -p` subprocess inherits
  `MAE_LEARNING_RUN_ID` via `env MAE_LEARNING_RUN_ID=... nohup claude -p ...`.
  It calls `append-session-id` (not `init-run`), adding to `meta.session_ids[]`.

## Replay — debugging a past run

Each session writes a transcript at
`~/.claude/projects/<encoded-cwd>/<full-uuid>.jsonl`.
The learning-log `meta.json` records `session_ids[]` linking to those
transcripts. To debug a run:

1. Locate the run dir: `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/`
2. Open `meta.json` to get `session_ids` and `worktree_path`.
3. Open the transcript JSONL at `~/.claude/projects/<encoded>/<session_id>.jsonl`.
4. Open `<worktree>/.orchestrator/state.json` to see the recorded task statuses.
5. If `events.jsonl` is non-empty, inspect each event's `context.evidence` for
   pointers to file/line/issue.

The eval harness's `run.jsonl` is a separate transcript artifact at
`<tmpdir>/.harness/run.jsonl`. Useful for measuring adherence (grep for
`LEARNING_LOG_INIT:`), Reviewer output (parse Agent tool results), and
tool-call count.

## Why this design — quick rationale pointers

These choices have history. For the "why" behind each, see:

- 3-phase lifecycle (vs continuous loop): [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §11
- Combined Reviewer (vs separate spec + quality reviewers): [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 + v2.6 history
- Per-run sharded learning log (vs single events.jsonl): `experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Q1
- Single-writer contract on the helper: same D001 §Q4 (advisor patch)
- Spec Coverage Walk with adversarial generation: `experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md` §Q3
- Step 7.5 MANDATORY framing: HISTORY.md v2.8.1 entry + F001-smoke.md PARTIAL audit

A full index is in [`decision-log.md`](./decision-log.md).
