# Glossary

Terminology used throughout the skill, prompts, evals, and experiment records.
If you're new to this codebase, skim this first.

## Roles and processes

- **Orchestrator** — the Claude Code session executing `SKILL.md`, running on
  Opus by default. Owns the worktree, the `state.json`, the learning-log run,
  and all sub-agent dispatch. There is exactly one orchestrator per plan run.
- **Sub-agent** — a fresh Claude Code instance dispatched by the orchestrator
  via the `Agent` tool (in-session) or `claude -p` subprocess (Resume Chain).
  Sub-agent roles: Implementer, Reviewer, Verifier, Plan Reviewer, Docs
  Updater. Sonnet by default; the `--model` flag is not currently passed
  (see [`risks-and-limitations.md`](./risks-and-limitations.md) §Headless model gap).
- **Combined Reviewer** — a single Reviewer sub-agent that performs both spec
  compliance review (Part 1) and code quality review (Part 2) in one pass.
  Replaces an earlier two-sub-agent design.
- **Verifier** — sub-agent that re-runs acceptance criteria from the spec
  against the implemented artifact, independent of the Implementer's tests.

## Execution structure

- **Plan** — a markdown file with task-numbered sections; the input to a run.
  Each task has files, acceptance criteria, optional risk override.
- **Task cycle** — Phase 1's per-task loop: Implementer → Reviewer (retry loop)
  → Verifier → commit → state update. One task = one cycle.
- **Phase 0** — Setup. Worktree creation, plan/spec read, state.json init,
  learning-log init-run, optional plan review. Once per run.
- **Phase 1** — Per-task cycle (repeated for each task in the plan).
- **Phase 2** — Cleanup. Docs update, final commit, learning-log close-run.
  Once per run, on the success path.
- **Phase Transition T3** — the boundary between Phase 1 (last task complete)
  and Phase 2 (cleanup). State-write failure here is one of the
  `outcome=blocked` exit paths.

## State and isolation

- **Worktree** — a git worktree under `<repo>/../worktrees/plan-<timestamp>/`
  (or `<repo>/.claude/worktrees/...` depending on mode). The orchestrator
  creates one per run; all task commits land here, isolating the plan run
  from the parent checkout.
- **`state.json`** — the orchestrator's external memory, at
  `<worktree>/.orchestrator/state.json`. Records task statuses, scores,
  cycle counts, escalation history. The orchestrator reads this at the
  start of every step to recover from context compaction.
- **Resume Chain** — when `compaction_points >= 2 AND complete >= 8`, the
  orchestrator launches `claude -p` to continue the run in a new session,
  passing `MAE_LEARNING_RUN_ID` via env so the learning-log run continues.
- **Compaction point** — a Claude Code conversation auto-compaction event.
  Tracked in state.json to trigger Resume Chain at the right threshold.

## Risk and scoring

- **Risk tier** — `low | mid | high`, derived per task from the plan
  (or invocation override). Drives TDD strictness, retry budgets,
  and verification depth — NOT model selection.
- **TDD strictness** — for `mid`/`high` tasks, the Implementer is required
  to write a failing test first, then implement to make it green. For `low`,
  TDD is recommended but not enforced.
- **P4 Generator-Verifier scoring** — Reviewer emits SPEC_SCORE and
  QUALITY_SCORE (0.0-1.0, 0.1 quantized). Thresholds: SPEC PASS iff
  ≥0.85; QUALITY PASS iff ≥0.75. Calibrated against the eval suite.
- **SPEC_FAULT** — Reviewer's diagnosis of *why* a spec fails:
  `spec_contradicts`, `unclear`, `implementer_omitted`, `none`. Drives
  escalation routing.
- **SPEC_COVERAGE_WALK** (v2.9.0+) — Reviewer's deterministic enumeration
  pass: sub-step A (stated bullets), sub-step B (adversarial generation
  from meta-rules). Emits one row per spec bullet + ≥3 adversarial rows
  per meta-rule. See [`../references/reviewer-prompt.md`](../references/reviewer-prompt.md).

## Learning log

- **Run** — one plan execution = one learning-log run. Identified by
  `run_id = <UTC-compact-timestamp>-<session_short>-<pid>` e.g.
  `20260513T143321Z-188042f4-48211`.
- **Run dir** — `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/`,
  contains `meta.json` (always) + `events.jsonl` (when ≥1 event).
- **`meta.json`** — run summary: outcome (`success | blocked | aborted |
  unknown`), event_count, session_ids[], started_at, ended_at, plan_path,
  spec_path, worktree_path (relativized).
- **Event** — one line of JSONL. 10 event types: `blocker`, `error`,
  `verification_failure`, `reviewer_warn_or_fail`, `escalation`,
  `recurring_issue`, `user_correction`, `parallel_dispatch_failure`,
  `successful_workaround`, `completion_learning`. See
  [`../references/learning-log.md`](../references/learning-log.md).
- **Candidate file** — JSON written by sub-agents at
  `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`. The
  orchestrator scans this dir and invokes `append`. Single-writer contract.
- **Adherence marker** — `LEARNING_LOG_INIT: RUN_ID=<id>` (or `SKIPPED`)
  printed by Step 7.5 in run.jsonl. The eval harness greps for this
  marker to detect adherence to v2.8.1's mandatory init-run.

## Eval system

- **Fixture** — a YAML file under `evals/fixtures/` describing a self-
  contained plan + spec + bootstrap + acceptance criteria + optional rubric.
- **Rubric** — deterministic correctness checks (bash one-liners exercising
  the implementation). Authoritative for correctness; LLM judge handles
  subjective axes (quality, cost-efficiency).
- **Judge** — LLM-as-judge (`evals/judge.md` template) scoring four axes:
  correctness, spec_compliance, code_quality, cost_efficiency. Mean of
  the four is the headline number.
- **Baseline** — `evals/baselines/v<version>.json`, the captured judge
  output per fixture for that version. Compared across versions to detect
  regressions.
- **Calibration** — `evals/calibration/`, a controlled test that runs
  good_impl.py vs broken_impl.py against the judge to verify the judge
  can discriminate (v2.7 artifact; revisit if judge accuracy drifts).

## Other terms

- **Superpowers** — the `superpowers:*` skill family. Sub-agents invoke
  these (e.g., `Skill("superpowers:requesting-code-review")` in Reviewer)
  for checklist-grounded reviews. Added in v2.8.
- **Headless mode** — `claude -p --dangerously-skip-permissions`. Used by
  `evals/run.sh` and Resume Chain. No interactive prompts; tools auto-
  approved. Adherence to skill instructions is the main fragility in
  this mode ([`risks-and-limitations.md`](./risks-and-limitations.md) §Adherence).
- **`MAE_LEARNING_RUN_ID`** — env var carrying the current learning-log
  run_id through subprocess and Resume Chain boundaries. Set by Step 7.5;
  read by every helper invocation.
- **Escalation** — when the Implementer-Reviewer retry loop exhausts budget
  on `mid`/`high` tasks, the orchestrator emits an ESCALATE record (in
  state.json + learning log) and either halts (`outcome=blocked`) or
  proceeds with a documented compromise.
- **ESCALATE-type** — `spec_blocked | implementation_blocked | test_blocked`.
  Each maps to an event severity in [`../references/escalation-playbook.md`](../references/escalation-playbook.md).
