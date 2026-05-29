# D002 — Phase-boundary enforcement: helper script, not hook

**Date**: 2026-05-29
**Status**: Decided

## Context

The recurring silent-skip regressions (phase_0_started, accumulate_cost,
timing.started/completed) share a shape: a *mandatory* action expressed as prose
scattered across a phase step, performed by the orchestrator by hand, with no
runtime enforcement. Past fixes added "DO NOT SKIP" framing — which v2.8.1's own
findings showed insufficient (47/47 Bash invocations skipped the learning-log
helper despite MANDATORY framing). The durable precedent is P1 (v2.5): move the
gate into the runtime.

The mandatory actions cluster at three boundaries:
- **task start**: stamp `timing.started`, persist `current_pre_task_sha`.
- **task complete**: write task result, stamp `timing.completed`, emit
  `task_completed`, accumulate cost.
- **phase/run boundary**: phase_0_started, compaction, phase_2_complete emits +
  timestamps.completed_at.

## Options considered

- **A — SubagentStop / Stop hook** that auto-stamps timing + emits on every
  sub-agent finish. Truly unskippable. But: a hook fires in the *worktree* claude
  process and does not have the orchestrator's task index / scores / usage in
  scope; it would need to read them from somewhere. Coupling a hook to
  orchestrator working state is fragile (the v2.10.1 note: the freshly-written
  headless.pid self-blocked a check). Hooks are best for *pure local guards*
  (debug-artifact scan) that need no orchestrator state.
- **B — one `phase_boundary.py` helper** the orchestrator calls once per boundary,
  bundling (state_set writes + AgentLens emit + cost accumulate) behind a single
  command. Still skippable in principle, but it collapses six prose paragraphs
  into one call — and a single call site is eval-checkable and far harder to drop
  than six scattered ones.
- **C — keep prose, add eval checks only.** Detects skips post-hoc but doesn't
  prevent them.

## Decision

**B**, layered with **C** for the cases that genuinely fit a hook.

- New `scripts/phase_boundary.py` with subcommands:
  - `task-start --state <p> --task <id> --pre-sha <sha>` → stamps timing.started +
    current_pre_task_sha (via state_set internally).
  - `task-complete --state <p> --task <id> --result-json <f> --run-id <r>`
    → writes task result, stamps `timing.completed`, advances the active
    `last_completed_task`/`last_completed_at` pointers, emits
    `kws-cme.task_completed`.
    **Refinement during build (v2.21):** task-complete does NOT accumulate cost.
    Cost is a *dispatch*-boundary concern (one accumulate per
    implementer/reviewer/verifier dispatch, each with its own role/model/usage),
    not a *task*-boundary one — folding it into the single task-complete call
    would either double-count or drop the reviewer/verifier dispatches. So
    `accumulate_cost.py` stays the per-dispatch helper (already a single call
    site, already skip-resistant) and task-complete keeps the result+timing+emit
    bundle. The `--usage-json/--model` args from the original sketch are dropped.
  - `phase-emit --state <p> --run-id <r> --type <phase_0_started|compaction|phase_2_complete> --payload-json <j>`
    → the explicit orchestrator emit sites + their paired timestamp stamp.
- The existing debug-artifact and check-implementer-output **hooks stay** (they fit
  the pure-local-guard shape). We do NOT move timing/emit into a hook (option A
  rejected) because they need orchestrator-side data.
- Add an `evals/` contract check: SKILL.md must reference `phase_boundary.py` at
  each of the documented emit sites (analogous to the v2.8.1 marker check).

## Consequences

- Six skippable prose steps → three named helper calls. Reduces both the
  regression surface and the SKILL.md prose.
- `phase_boundary.py` depends on `state_set.py` and `accumulate_cost.py` — build
  order: state_set → accumulate (exists) → phase_boundary.
- AgentLens emits stay `2>/dev/null || true` *inside* the helper so observability
  still never blocks execution (the helper's non-emit work must still succeed).

## Open questions

- Should `task-complete` also drain the learning_events candidate dir? Leaning no —
  keep the candidate drain a separate explicit step so a candidate-schema bug
  can't fail the task-complete write. Revisit if dr/emit ordering matters.
