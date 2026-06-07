# D007 — J8 AC anti-rubber-stamp reviewer cross-check: design, fixture-eval gated (P2)

**Date**: 2026-06-08
**Status**: Designed — not implemented this round (P2 design-only, fixture-eval gated)

## Context

When a task has an `## Acceptance Criteria` block, the Verifier *runs* the AC shell,
but if the AC shell is itself incomplete (a test gap), an intent violation can leak.
The Combined Reviewer does a Spec Coverage Walk (v2.9) but does not explicitly check
each AC item against the diff. Fixture 09 (D002) is the measurement instrument for
exactly this rubber-stamp class.

## Options considered

- **A — No change.** Rely on Verifier AC execution + Spec Walk. Leaves the
  AC-incompleteness gap (the FM-3.3 case fixture 09 probes).
- **B — Add a reviewer sub-step:** when an AC block exists, enumerate each AC item
  and assert the diff satisfies it as `AC[i] :: SATISFIED | UNCOVERED | VIOLATED`;
  any `UNCOVERED`/`VIOLATED` → QUALITY_ISSUE (or SPEC_FAULT). Skip the sub-step when
  no AC block (cost guard). Add a contract token check in `check_skill_contract.py`.
- **C — Make the Verifier do it.** Wrong layer — the Verifier runs oracles; the
  *intent* cross-check belongs to the Reviewer, before the Verifier runs.

## Analysis

B defends the rubber-stamp directly and is cheap (only fires when an AC block is
present). But it edits `references/reviewer-prompt.md` — a sub-agent prompt — so per
principle 4 it is fixture-eval gated. The measurement is already built: fixture 09
(09-spec-intent-uncovered). A before/after run must show the cross-check surfaces the
uncovered AC item that the current pipeline would rubber-stamp. The contract token
check in `check_skill_contract.py` guards against the sub-step silently disappearing
from the prompt later.

## Decision

Record the design + gate. Implement in v2.30.2 alongside J7: (1) add the reviewer
sub-step + the `check_skill_contract.py` token assertion, (2) before/after compare on
fixture 09, (3) experiment record. No prompt edits this round. J8 is the behavioral
complement to J2: J2 measures the gap, J8 closes it.

## Consequences

- When built, AC-bearing tasks get an explicit per-item intent cross-check before
  the Verifier runs — a direct anti-rubber-stamp defense (MAST FM-3.3).
- Cost-guarded (AC-block-only) so non-AC tasks are unaffected.

## Open questions

- Whether `UNCOVERED` should be a WARN (proceed) or a retry-triggering QUALITY_ISSUE.
  Lean WARN first to avoid burning the retry budget on borderline AC phrasing;
  decide from the fixture-09 before/after data.
