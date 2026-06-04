# D003 — Autonomous error handling + escalation autonomy + halt boundary

**Date**: 2026-06-04
**Status**: Decided

## Context

User directive: on a mid-run error, do **not** prompt the user — judge the best
path and finish the run. This applies to the new agent-dispatch path and, by
explicit follow-up choice, to the existing runtime escalation cases
(AMBIGUITY, SPEC_BLOCKER) which currently mark a task SKIPPED and report.

The tension: the skill has several hard-halt guardrails (state-write failure,
out-of-repo paths, etc.). Maximum autonomy must not mean ignoring data
corruption or guessing where malformed-input files belong.

## Options considered

- **A**: Keep existing escalate-to-user / SKIP behavior; only the agent path
  self-heals.
- **B**: Full autonomy for *recoverable* errors (retry → fallback → continue),
  best-judgment for runtime ambiguity, hard-halt retained only for integrity +
  malformed-input.
- **C**: Never halt under any circumstance.

## Analysis

A under-delivers on the user's explicit ask. C is unsafe: continuing past a
`state.json` write failure corrupts the run, and guessing where an out-of-repo
file should land can write outside the repo. B threads the needle by classifying
errors: *recoverable dispatch/interpretation* errors self-heal and continue;
*integrity* failures and *malformed pre-flight input* still halt because there is
no safe way to continue.

## Decision

Option **B**.

**Agent-dispatch failure ladder (no user prompt):**
1. Retry once (fresh sub-agent).
2. Auto-fallback to `api` for that one dispatch (logged + `kws-cme.dispatch_fallback`).
   Scoped exception to "no automatic fallback": `agent → api` only, after retry.
3. `api` also fails → advisory role (Plan Reviewer) warns + proceeds;
   load-bearing role (Verifier/Docs) records `verification_gap`/`docs_gap` +
   `kws-cme.blocker`, continues, surfaces in the Final Report.

**Escalation autonomy:** runtime AMBIGUITY / SPEC_BLOCKER → orchestrator adopts
the most defensible interpretation, records rationale in `spec_edits`, proceeds
without SKIP, surfaces in the Final Report.

**Halt boundary (hard-halt retained ONLY for):**
1. Data-integrity failures — `state.json` write, `git reset`, worktree missing.
2. Phase 0 pre-flight structural/config errors — out-of-repo paths, missing
   `Files:` blocks, no task headers (malformed input; guessing is unsafe).

## Consequences

- Recoverable errors never block a run; the run completes with gaps recorded and
  surfaced rather than halting.
- The auto-fallback can re-meter individual dispatches under failure — accepted:
  completion > one metered call.
- Best-judgment interpretation trades a small mis-interpretation risk for higher
  completion; rationale is always recorded for post-run review.
- Verifier/Docs gaps mean a run can complete with unverified/undocumented work —
  must be visible in the Final Report, never silent.

## Open questions

- Exact `verification_gap` / `docs_gap` state shape and Final Report rendering —
  to be pinned in the implementation plan.
