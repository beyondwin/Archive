# D004 — J5 shelf-trigger evaluator (analyze_shelf_triggers.py): design + start condition (P1)

**Date**: 2026-06-08
**Status**: Designed — not implemented this round (P1 design-only)

## Context

`docs/deferred-candidates.md` lists data-gated candidates (Haiku LOW-tiering,
context_health active management, plan pre-mortem) whose revisit triggers are
*empirical* conditions (e.g. "LOW-task verifier_retry distribution is narrow and P4
QUALITY fail-rate < 5%"). Today a human guesses whether those conditions are met.
v2.29 shipped `run_report.json` + `events.jsonl` + `failure_summary`, and v2.24
took a 35-run corpus baseline (`aggregate_runs.py`), so the empirical inputs now
exist for the first time.

## Options considered

- **A — Keep guessing.** Humans read the corpus ad hoc. Error-prone; the whole
  point of the deferred-candidates triggers is to be evaluated, not eyeballed.
- **B — Build a read-only evaluator now.** A `scripts/analyze_shelf_triggers.py`
  that consumes the corpus and emits `MET | NOT_MET | INSUFFICIENT_DATA` + evidence
  per candidate. Observation-only (no orchestrator control-flow coupling —
  Goodhart guard).
- **C — Build the evaluator AND act on it now (e.g. auto-enable Haiku tiering).**
  Rejected outright: couples a measurement to a behavior change in one step,
  exactly the Goodhart trap the skill guards against elsewhere.

## Analysis

B is the right shape but is P1, and the user scoped this round to P0-full /
P1-P2-design-only. The design is concrete enough to commit:

```
usage: analyze_shelf_triggers.py [--corpus-glob '<glob>'] [--json]
inputs: the corpus aggregate_runs.py reads + v2.29 run_report.json files
output (per candidate): {candidate, status: MET|NOT_MET|INSUFFICIENT_DATA, evidence:{...}}
```

Evaluation rules (1:1 with deferred-candidates.md triggers):
- **Haiku LOW-tier**: LOW-task `verifier_retry` distribution narrow (e.g. p90≤1)
  AND P4 QUALITY fail-rate < 5% AND sample ≥ N (e.g. LOW tasks ≥ 30) → MET; sample
  short → INSUFFICIENT_DATA.
- **context_health active mgmt**: runs ≥ 10 AND span ≥ 2 weeks AND drift signal
  correlates with quality drop → MET (no correlation → NOT_MET).
- **plan pre-mortem**: `plan_review` WARN/BLOCKER correlates with downstream failure
  → MET.

Ships with a paired `scripts/test_analyze_shelf_triggers.py` using 3 synthetic
corpus fixtures (one per branch: MET / NOT_MET / INSUFFICIENT_DATA).

## Decision

Record the design and the **start condition**: implement J5 in a v2.30.1 pass when
P1 is picked up. It is read-only and orthogonal to orchestrator control flow
(must stay so — Goodhart guard). Output adds a "최근 평가: <status> (<date>)" line
to each candidate in `deferred-candidates.md`.

## Consequences

- Gives J6 (Haiku A/B) a data-driven go/no-go instead of a guess (see D005).
- No runtime/behavior change from J5 itself; it is a decision-support tool.

## Open questions

- The exact sample-size floor N and the p90 retry threshold — calibrate against the
  actual corpus when implementing, not now (avoid speculative constants).
