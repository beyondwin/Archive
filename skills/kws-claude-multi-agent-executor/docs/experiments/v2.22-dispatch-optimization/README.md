# v2.22 — Dispatch Optimization

Replace `claude -p --dangerously-skip-permissions` headless dispatches with
Anthropic Messages API direct calls. Add prompt caching, merge co-located
dispatches, cheapen mechanical reviewers.

## Files

- `spec.md` — problem statement, 3-phase plan, risks, validation
- `plan.md` — 18 executor-ready tasks across 5 waves
- `JOURNAL.md` — per-task ship log (populated as work lands)
- `decisions/` — ADRs D001–D007 (populated in Task 18)

## Phase summary

| Phase | Scope | Tasks | ETA |
|-------|-------|-------|-----|
| A | Quick wins: Haiku Plan Reviewer + T1/T2 merge + cost helper | 1–3 | 1–2 days |
| B | API-direct dispatch + caching (core value) | 4–12 | 1 week |
| C | Batch API for final sweep + Self-Spawn simplification | 13–14 | 3–4 days |
| Evals | Haiku-vs-Sonnet agreement + merge parity + baseline regression | 15–17 | 1 day |
| Docs | HISTORY, decisions, changelog | 18 | 0.5 day |

## Success criteria

- Mean per-dispatch wall_ms ≤ 40% of v2.21 baseline
- Mean per-dispatch input cost ≤ 20% of v2.21 baseline (cache-driven)
- Zero new ENV_BLOCKER false-positives in 10-run regression
- All guardrails preserved (no risk/method-audit/retry semantic change)

## How to execute

```
/kws-claude-multi-agent-executor \
  plan=/Users/kws/.claude/skills/kws-claude-multi-agent-executor/docs/experiments/v2.22-dispatch-optimization/plan.md \
  spec=/Users/kws/.claude/skills/kws-claude-multi-agent-executor/docs/experiments/v2.22-dispatch-optimization/spec.md
```

Defaults apply (implementer_model=sonnet, parallel=on, mode auto-detected).
