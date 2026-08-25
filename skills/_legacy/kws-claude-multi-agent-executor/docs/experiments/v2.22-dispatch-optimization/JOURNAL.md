# v2.22 Journal

Per-task ship log. Append entries as tasks complete.

## Format

```
## Task N — <title> — <YYYY-MM-DD>
- Result: COMPLETE | WARN | ESCALATED
- Wall time: <duration>
- Key decisions / surprises: <bullet>
- Forensics: <links to AgentLens queries or cost ledger excerpts>
```

## Entries

All v2.22 tasks (1–18) shipped on **2026-05-31**. Phase-grouped below; per-task
results were COMPLETE with no escalations. Observed baseline metrics
(`evals/baselines/v2.22.0.json`): input_tokens_mean 3550, cache_hit_ratio_mean
0.66, output_quality_mean 0.88, escalate_count 0.

## Phase A — Quick wins (Tasks 1–3) — 2026-05-31
- Result: COMPLETE
- Tasks: T1 Plan Reviewer → Haiku 4.5 (D001); T2 Transition T1+T2 merge into
  `transition_combined` (D002); T3 cost helper `combined_roles`.
- Key decisions / surprises: D002 merge gated on the transition-merge parity
  eval; no semantic change to routing or review verdicts.
- Rollback: revert Plan Reviewer model arg to Sonnet; un-merge T1/T2 back to two
  dispatches. Both are localized.
- Forensics: plan-reviewer-rubric + transition-merge evals; cost_ledger
  `combined_roles` rows.

## Phase B — API-direct dispatch + caching (Tasks 4–12) — 2026-05-31
- Result: COMPLETE
- Tasks: T4 `dispatch_via_api.py` skeleton + Plan Reviewer migration (D003);
  T5 scaffold byte-stability linter at Phase 0 Step 6.7 (D004; lint site is
  6.7, not 7.5 — Task 5 deviation); T6 verifier batch (T1) API migration;
  T7 transition_combined API migration; T8 verifier per-task API migration;
  T9 docs updater API migration; T10 cost-ledger cache-token fields;
  T11 AgentLens `dispatch_via_api` event; T12 SKILL.md guardrail prose.
- Key decisions / surprises: D005 — API errors do NOT fall back to `claude -p`
  (forbidden mixed-path retry); dispatch forces `tool_choice`. Step 7.5 was
  already the v2.17 boundary-emit, so the scaffold lint took 6.7.
- Rollback: gate API-direct roles off via run-level `dispatch_config`; the
  headless `claude -p` path remains intact, so a run can fall back wholesale
  (not per-error) by config.
- Forensics: cache_hit_ratio_mean 0.66 and input_tokens_mean 3550 confirm the
  scaffold cache is hitting; AgentLens `dispatch_via_api` events per dispatch.

## Phase C — Batch API + Self-Spawn (Tasks 13–14) — 2026-05-31
- Result: COMPLETE
- Tasks: T13 Message Batches API final sweep
  (`dispatch_final_sweep_batch.py`, `kws-cme.batch_timeout` fallback);
  T14 Self-Spawn attached-by-default (D007; `mode=interactive_attached`,
  opt-in `detach=true`, 2-week deprecation warning).
- Key decisions / surprises: default flip ships with a time-boxed deprecation
  warning rather than silently; headless autonomy preserved behind `detach=true`.
- Rollback: re-flip the self-spawn default to detached headless; disable the
  batch sweep path. Deprecation warning is removable after the 2-week window.
- Forensics: `kws-cme.batch_timeout` events on sweep fallback;
  `state.deprecation_warnings.attach_default` gate.

## Evals + baseline (Tasks 15–17) — 2026-05-31
- Result: COMPLETE
- Tasks: T15 plan-reviewer-rubric (Haiku vs Sonnet agreement);
  T16 transition-merge parity (merge vs split); T17 baseline regression
  `evals/baselines/v2.22.0.json` + `scripts/cost_compare.py`.
- Forensics: baseline metrics block above; cost_compare against the v2.21
  baseline.

## Docs (Task 18) — 2026-05-31
- Result: COMPLETE
- Tasks: HISTORY.md v2.22 entry; decision-log.md D001–D007 index; ADRs
  D001–D005 + D007 under `decisions/`; this JOURNAL; README overview update;
  SKILL.md `mode` enum reconcile (`interactive_attached`).
- Forensics: this experiment directory.
