# D002 — Measure the Implementer in isolation, not via full orchestrator runs

**Date**: 2026-06-02
**Status**: Decided

## Context

D001 fixed the primary metric as the Implementer's *first-pass* rejection rate on
fixture-08 meta-rule checks. The existing harness (`evals/run.sh`) runs the **full
orchestrator** (orchestrator + Implementer + Reviewer + Verifier) via `claude -p`,
scores the *end state*, and costs ~$5–15 per run. That harness cannot see first-pass
Implementer output and is dominated by the reviewer-walk retry we want to exclude.

## Options considered

- **A — Reuse `evals/run.sh` full runs.** Highest fidelity to production, but
  ceilinged metric (D001), expensive, and conflates the change with the v2.9 walk.
- **B — Dispatch only the Implementer sub-agent on fixture 08 Task 0, score its
  first output against the fixture rubric.** Directly measures the intervention,
  ~1 dispatch per rep instead of a whole orchestrated run, no reviewer contamination.
- **C — Pure offline prompt diffing / static review (no dispatch).** Free but
  measures nothing real — the whole point is Sonnet's first-pass behavior.

## Analysis

Option B reproduces the v2.9 evidence pattern (v2.9 measured raw Reviewer output on
the same fixture rather than just whether the run shipped buggy code). It is the
cheapest design that still measures the actual model behavior under the changed
prompt. The fixture-08 rubric is already executable (`error_cases` checks return
exit 0 iff `ValueError` is raised), so scoring a first-pass `src/duration.py` is a
matter of running the existing checks against it.

## Decision

Build a small harness under
`docs/experiments/v2.23-implementer-adversarial-selfcheck/bench/` that:
1. Materializes fixture 08's bootstrap repo in a temp dir.
2. Dispatches a single Implementer sub-agent for Task 0 with the control prompt,
   then with the treatment prompt (N reps each).
3. Runs the fixture-08 `error_cases` + `valid_inputs` rubric checks against each
   resulting `src/duration.py`, recording per-check pass/fail and the
   `ADVERSARIAL_SELFCHECK:` line.
4. Emits a JSON result table for the findings doc.

## Consequences

- Enables: cheap, contamination-free measurement of the primary metric.
- Commits: a bench harness that is fixture-08-specific (acceptable — fixture 08 is
  the only fixture with the measured meta-rule miss; generalization is a non-goal).
- Note: dispatch transport (Agent tool vs `claude -p` vs API) should match how a
  real Implementer is dispatched (Agent tool / Sonnet) so the measurement is
  representative; the bench will use the same model + a faithful copy of the
  prompt template with placeholders filled from fixture 08.

## Open questions

- N (reps per arm): v2.7/v2.9 used n=4. Pending user budget confirmation at the GATE.
