# D005 — J6 Haiku LOW-tier A/B harness deferred, conditional on J5=MET (P1)

**Date**: 2026-06-08
**Status**: Deferred (record-only) — conditional on D004 (J5) returning MET

## Context

Routing LOW-risk single-file tasks to Haiku is ~5× cheaper than Sonnet, but it was
shelved because nobody measured whether Haiku-implemented LOW tasks stably pass the
P4 QUALITY threshold (0.75). `deferred-candidates.md` §Haiku records this as a
data-gated candidate.

## Options considered

- **A — Build the A/B harness now.** Premature: without J5's empirical verdict we'd
  be measuring on a guess that the trigger is met. Burns paid eval budget possibly
  for nothing.
- **B — Defer, gate on J5.** Build the bench only when `analyze_shelf_triggers.py`
  (D004) returns `MET` for the Haiku LOW-tier candidate. Otherwise update
  `deferred-candidates.md` with the data and a "still skip (trigger not met: …)".
- **C — Abandon Haiku tiering.** Too strong — the cost upside is real; only the
  evidence is missing.

## Analysis

This is a straightforward dependency: J6 has no defensible go/no-go until J5 exists
and runs against the real corpus. Building J6 first inverts the data-driven
discipline this round is built on. When triggered, reuse the v2.12
`implementer-bench` pattern (`bench/`), swapping its 2×SMALL/2×MED/2×LARGE matrix
for N LOW single-file tasks, measuring Haiku vs Sonnet on P4 pass-rate, retry count,
and cost Δ.

## Decision

**Option B.** Defer J6. Start condition: D004's evaluator returns `MET` for the
Haiku LOW-tier candidate. On `NOT_MET`/`INSUFFICIENT_DATA`, the honest deliverable
is a `deferred-candidates.md` update recording the evidence and "still skip" — a
negative result is a valid outcome.

## Consequences

- No code this round. The path to adoption is now explicit and evidence-gated.
- Prevents a speculative, possibly-wasted paid A/B run.

## Open questions

- If `INSUFFICIENT_DATA` persists, how long to wait for the corpus to grow before
  re-evaluating. Tie to J5's sample-size floor (D004 open question).
