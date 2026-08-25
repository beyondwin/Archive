# v2.22 — Dispatch Optimization

**Status: SHIPPED (2026-05-31).** Tasks 1–18 complete across Phases A/B/C plus
evals and docs.

Replaced `claude -p --dangerously-skip-permissions` headless dispatches for the
mechanical roles with Anthropic Messages API direct calls. Added prompt caching
(scaffold/payload split), merged co-located dispatches (Transition T1+T2), and
cheapened the mechanical Plan Reviewer (Sonnet → Haiku 4.5).

## Files

- `spec.md` — problem statement, 3-phase plan, risks, validation
- `plan.md` — 18 executor-ready tasks across 5 waves
- `JOURNAL.md` — per-task / per-phase ship log (all shipped 2026-05-31)
- `decisions/` — ADRs D001–D005 + D007 (D006 is pending; indexed in
  `../../decision-log.md` only)

## Phase summary

| Phase | Scope | Tasks | Status |
|-------|-------|-------|--------|
| A | Quick wins: Haiku Plan Reviewer + T1/T2 merge + cost helper | 1–3 | shipped |
| B | API-direct dispatch + caching (core value) | 4–12 | shipped |
| C | Batch API for final sweep + Self-Spawn attached-by-default | 13–14 | shipped |
| Evals | Haiku-vs-Sonnet agreement + merge parity + baseline regression | 15–17 | shipped |
| Docs | HISTORY, decision log, README, ADRs | 18 | shipped |

## Decisions

- D001 Plan Reviewer → Haiku 4.5 (A1, shipped)
- D002 Transition T1 + T2 merge (A2, shipped)
- D003 `dispatch_via_api.py` single helper (B1, shipped)
- D004 Scaffold/payload byte-stability lint at Phase 0 Step 6.7 (B3, shipped)
- D005 No `-p` fallback / no forbidden mixed-path retry (B6, shipped)
- D006 Cache TTL stays ephemeral for v2.22 (open Q2, **pending** — no ADR body)
- D007 Self-Spawn default flips to attached + deprecation warning (C2, shipped)

## Success criteria

- Mean per-dispatch wall_ms ≤ 40% of v2.21 baseline
- Mean per-dispatch input cost ≤ 20% of v2.21 baseline (cache-driven)
- Zero new ENV_BLOCKER false-positives in 10-run regression
- All guardrails preserved (no risk/method-audit/retry semantic change)

## Shipped baseline

`evals/baselines/v2.22.0.json`: input_tokens_mean 3550, cache_hit_ratio_mean
0.66, output_quality_mean 0.88, escalate_count 0. Compare with
`scripts/cost_compare.py` against the v2.21 baseline.

## How to execute

```
/kws-claude-multi-agent-executor \
  plan=/Users/kws/.claude/skills/kws-claude-multi-agent-executor/docs/experiments/v2.22-dispatch-optimization/plan.md \
  spec=/Users/kws/.claude/skills/kws-claude-multi-agent-executor/docs/experiments/v2.22-dispatch-optimization/spec.md
```

Defaults apply (implementer_model=sonnet, parallel=on, mode auto-detected).
