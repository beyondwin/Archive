# Phase 1: Per-Task Cycle — v3.0 (kernel-owned)

> **v3.0 cutover.** The per-task cycle is no longer prose the orchestrator
> interprets. The deterministic kernel (`scripts/kernel/`) owns every decision that
> used to live here: which role to dispatch, the review tier (computed from
> spec_score/quality_score, NOT the sub-agent's self-status), retry accounting
> (review/verifier/escalation/spec-clarification budgets), the `git reset --hard`
> directive before verifier re-dispatch, LOW→PENDING_BATCH routing, `quality_trend`
> appends, and timing stamps.

**How the cycle runs now:** drive the `SKILL.md §③` loop —
`kernel.py next → perform the returned action → kernel.py submit` — and handle each
action per the `SKILL.md §④` action-handling table. There is nothing to "decide"
here; run `next` and do exactly what it returns.

Reference map (kernel owners that replaced this doc's decision logic):

| Former prose step | Kernel owner |
|-------------------|--------------|
| Step 1 Dispatch Implementer | `transitions.decide` → `dispatch` action; `dispatch.build` writes the substituted prompt |
| Step 2 Combined Reviewer (tier, spec-edit branch, retry) | `transitions.apply_result` (`_apply_reviewer`, `_compute_review_tier`) |
| Step 3 Verifier (MID/HIGH) + reset-on-FAIL | `transitions.apply_result` (`_apply_verifier`); `run_command purpose=reset` |
| Step 4 Agent Cleanup (latest pointers, timing, cost) | `kernel.py submit` (`ledger.record`, `transitions.record_timing`) |

The Implementer/Reviewer/Verifier prompt templates in `references/` are still the
sub-agent contracts; the kernel substitutes them at dispatch time. Escalations are
routed via the kernel's `escalate_to_user` action — see
[`phase-1-escalation.md`](phase-1-escalation.md). Parallel waves (an `execution_plan`
group of size ≥ 2) are launched by the orchestrator — see
[`phase-1-parallel-subflow.md`](phase-1-parallel-subflow.md).
