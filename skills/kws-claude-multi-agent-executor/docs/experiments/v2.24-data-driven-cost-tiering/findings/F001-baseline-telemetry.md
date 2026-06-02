# F001 — Baseline telemetry (Phase A corpus snapshot)

**Date**: 2026-06-02
**Status**: BASELINE CAPTURED — every number below is measured directly from
`scripts/aggregate_runs.py` output over the live corpus.
**Source command**:

```bash
cd skills/kws-claude-multi-agent-executor
python scripts/aggregate_runs.py --json /tmp/v2.24-all.json --format md
python scripts/aggregate_runs.py --risk low --format md
```

## Per-run corpus summary

| Metric | Measured value |
|--------|----------------|
| Runs in corpus | **35** |
| Total cost (Σ `cost_usd`) | **$269.62** |
| Mean `cache_hit_ratio` (across all 35 runs) | **0.0105** |

Cost is concentrated: a long tail of runs report `cost_usd = 0.0` (cost helper not
called), while a handful (e.g. `20260518T033058Z-nosessio-61291` $41.53,
`20260518T122705Z-fbbd2795-67441` $50.68, `v1-readiness-umbrella-...` $51.78) carry
most of the spend.

## Phase B gate inputs

### LOW-tier verifier-retry distribution

```
LOW (Phase B gate input): {0: 108, 1: 1}
```

(For reference the other tiers: HIGH `{0: 33}`, MID `{0: 148, 1: 3}`,
UNKNOWN `{0: 6}`.)

### B-GATE-1 — ≥90% of LOW tasks complete at 0 verifier retries

- LOW tasks at 0 retries: 108 / (108 + 1) = **99.08%**.
- Threshold: ≥90%.
- **Verdict: B-GATE-1 CLEARS @ 99.08%.** LOW-risk tasks almost never need a verifier
  retry, so the verifier pass on LOW work is near-redundant — consistent with the
  hypothesis that LOW tasks tolerate a cheaper tier.

### B-GATE-2 — QUALITY fail-rate < 5%

- Measured quality fail-rate (P4 proxy): **0.0** (0.00%).
- Threshold: < 5%.
- **Verdict: B-GATE-2 CLEARS** (0.0% < 5%). No recorded P4 quality failure across the
  corpus. Caveat: 5 runs report `quality_trend empty` (see gaps), so the denominator
  is the subset of runs that actually recorded quality scores — fail-rate is 0 among
  recorded scores, not proof that no quality regression is possible.

## Phase C input — production cache_hit_ratio (C1)

- Only **one** run in the entire corpus reports a non-zero `cache_hit_ratio`:
  `20260518T122705Z-fbbd2795-67441` at **0.3662**, started **2026-05-18T12:28:36Z**.
  Every other run reports `cache_hit_ratio = 0.0`.
- v2.22 (dispatch optimization) shipped at the end of May; the only run on the v2.22
  plan, `v2-22-dispatch-optimization-20260531-201758`, reports `cache_hit = 0.0`.
- **No post-v2.22 run with a populated (non-zero) `cache_hit_ratio` exists.** The sole
  non-zero cache sample predates v2.22 by ~two weeks.
- **C1 BLOCKER: YES.** Phase C cannot validate ephemeral-cache cost behaviour against
  production telemetry because no post-v2.22 run has recorded a non-zero cache hit
  ratio. Cache telemetry is effectively not being captured in current runs.

## Observability gaps surfaced

The aggregator flagged **33 gap entries** across the corpus, indicating cost/telemetry
is not consistently recorded:

| Gap class | Runs affected |
|-----------|---------------|
| `dispatches = 0` (cost helper likely not called) | **13** |
| null timestamp (`started_at` and/or `completed_at`) | **13** |
| `quality_trend` empty (no quality scores recorded) | **5** |

13 of 35 runs (~37%) never invoked the cost helper, which is why so many rows show
`cost_usd = 0.0` and the corpus-wide mean `cache_hit_ratio` is dragged to 0.0105.
Recurring ISSUE_KEY signatures: **none recorded**.

## Per-phase recommendation

**Phase B → SHIP.** Both gates clear on real data: B-GATE-1 at **99.08%** (≥90% of
LOW tasks need 0 verifier retries) and B-GATE-2 at a **0.0%** quality fail-rate
(< 5%). The verifier pass on LOW-risk tasks is near-redundant, so moving LOW work to a
cheaper tier (and/or relaxing the LOW verifier) is justified by the measured retry
distribution rather than by assumption.

**Phase C → needs-post-v2.22-run.** The ephemeral-cache cost story cannot be confirmed:
the only non-zero `cache_hit_ratio` sample (0.3662) is a single pre-v2.22 run from
2026-05-18, and **no post-v2.22 run has a populated cache hit ratio** (C1 blocker).
Phase C must wait until at least one post-v2.22 run records non-zero cache telemetry;
until then the cost helper / cache instrumentation gap (13/35 runs with
`dispatches = 0`) is the prerequisite to fix before any C1 decision.
