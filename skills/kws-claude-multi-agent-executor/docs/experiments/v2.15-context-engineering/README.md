# v2.15 — Context Engineering

**Status**: planned · **Predecessor**: v2.14 (forensics & cost) · **Successor**: TBD (v2.16 candidate evaluation)

## One-line

Stop sending the *full spec text* to every Implementer dispatch. Stop re-deciding settled architectural choices. Reset the Orchestrator's own context window before drift sets in. Measure the savings using v2.14's cost ledger.

## Why now

GSD 2's context engineering rests on three things our skill does NOT have:

1. **Tiered Context Injection** — only the spec sections this unit needs are inlined. (GSD reports 65%+ token reduction.)
2. **Decisions Register cross-injection** — settled architectural choices follow the project, not the dep graph. Task 17 sees task 8's decision even if task 17 doesn't list task 8 as a dep.
3. **Compaction-driven session reset** — at slice boundaries, GSD actually starts a *new* session. Our Phase Transition T3 says "drop prior context" but is prose-only discipline — there's no mechanism forcing it.

These directly cause measurable waste in our skill today:
- Spec re-inlined every dispatch → no cache hit across sub-agents → 100% input token cost per task.
- Cross-task FAIL with reason "doesn't match existing pattern" because the decision wasn't surfaced.
- 25+ task chain runs show Orchestrator quality drifting after the second compaction.

v2.14 ships first because we need the cost ledger to measure v2.15's effect — A/B against a known plan.

## Bundle members

| # | Feature | Surface | New artifacts |
|---|---------|---------|---------------|
| C1 | Spec manifest — per-task section projection | Phase 0 Step 3 + Step 6 patches, Phase 1 Step 1 prompt builder, state.spec_manifest | `scripts/build_spec_manifest.py`, Plan Reviewer rubric extension |
| C2 | Decisions register cross-task injection | Phase 1 Step 4 patch, state.decisions_register, Implementer + Reviewer prompt templates | (no new scripts — pure prompt + state changes) |
| C3 | Compaction trigger lowering — token-based Resume Chain | Resume Chain trigger logic, uses v2.14 F2 token totals | (no new scripts — variable threshold change + token read) |

## Files in this directory

- `README.md` (this file)
- `spec.md` — formal specification
- `plan.md` — implementation plan
- `JOURNAL.md` — execution log
- `decisions/` — ADRs
- `findings/` — A/B measurements vs v2.14 baseline (token cost per dispatch, FAIL reasons, quality_trend)

## Execution

```bash
# Standalone (must run AFTER v2.14 is landed)
/kws-claude-multi-agent-executor \
  plan=docs/experiments/v2.15-context-engineering/plan.md \
  spec=docs/experiments/v2.15-context-engineering/spec.md

# Chained with v2.14 (recommended — landed in one go)
/kws-claude-multi-agent-executor \
  plan=docs/experiments/v2.14-forensics-and-cost/plan.md \
  spec=docs/experiments/v2.14-forensics-and-cost/spec.md \
  plan2=docs/experiments/v2.15-context-engineering/plan.md \
  spec2=docs/experiments/v2.15-context-engineering/spec.md
```

## Hard dependencies

- v2.14 F2 (cost ledger) — C3's token-based trigger reads `state.cost_ledger.totals.input_tokens` to estimate context window usage.
- v2.14 F3 (HTML report) — A/B comparison reports use the chart sections from F3.

## Non-goals

- No change to model selection (Implementer/Reviewer/Verifier still per v2.12 + v2.13 rules).
- No change to retry budgets, parallel dispatch, hook contracts.
- No new sub-agent dispatches (decision injection is a prompt change, not a new agent).
- No automatic decision conflict resolution — register surfaces decisions; Reviewer flags conflicts; Orchestrator routes to spec-edit branch.

## Risks consciously accepted

- Manifest miscompute → Implementer SPEC_BLOCKER ESCALATE → spec-edit branch fires more often initially. Mitigated by Plan Reviewer rubric extension catching missing section refs.
- Decisions register grows unbounded for very long runs (50+ tasks). Mitigated by ≤15-word per-decision cap (existing); register typically <2 KB for 30 tasks.
- Token-based Resume Chain may fire too eagerly on cache-heavy runs (cached tokens count toward input). Mitigated by counting only non-cached input tokens for trigger purposes.
