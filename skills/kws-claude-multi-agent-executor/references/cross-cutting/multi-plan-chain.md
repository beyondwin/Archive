# Cross-cutting: multi-plan chains & `<active>` resolution

Canonical reference for the v2.13 multi-plan chain feature: how `<active>`
resolves, how the chain advances, and the run-level vs per-plan boundary. SKILL.md
keeps the short resolution table (it is load-bearing for every phase); this file
holds the full mechanics. Written **post-D004** — the legacy `plan2_state`
two-plan path is gone; only the `plan_chain[]` shape exists in live state.

See also: `cross-cutting/state-schema.md` (the field layout),
`references/phases/phase-2-finalization.md` Step -1 (the Cross-Plan Trigger),
`references/phases/phase-minus-1-args-and-spawn.md` (multi-plan arg parsing).

## `<active>` resolution

`<active>` is the JSON path of the currently-active plan's per-plan state:

| State.json shape | `<active>` expands to |
|------------------|------------------------|
| `state.plan_chain` present (multi-plan) | `state.plan_chain[state.active_plan]` |
| Otherwise (single-plan) | `state` (top-level) |

`state.active_plan` is an **integer** index (0, 1, 2, …) whenever `plan_chain` is
present, and the **string** `"plan1"` for a single-plan run. There is no `"plan2"`
string: a legacy v2.12 `plan2_state`-shaped state.json is rewritten into the
`plan_chain` shape by `scripts/migrate_legacy_state.py` at Phase 0 Step 0 **before**
any `<active>` logic runs, so no live state.json reaching Phase 1 carries
`plan2_state`.

bash/jq dispatch (Monitor scripts, helpers):

```bash
if jq -e '.plan_chain' state.json >/dev/null 2>&1; then
  ACTIVE='.plan_chain[.active_plan]'
else
  ACTIVE='.'
fi
```

`scripts/state_set.py --plan-scope active` resolves the same rule in-process; use
`--plan-scope run` for run-level fields. Every read or write to a per-plan field
MUST go through this resolution — hard-coding `state.tasks` for a multi-plan run
silently corrupts the chain (see `cross-cutting/state-schema.md`).

## Detection & construction (Phase -1.0 Pass 2)

The arg parser scans `plan\d*=` keys: `plan=` is index 0, `plan2=` index 1, etc.

- **Gaps halt** (e.g., `plan=` + `plan3=` with no `plan2=`).
- **Missing `specN=`** for a present `planN=` halts.
- **`manifest=`** is mutually exclusive (reserved; halt if combined).
- **Length 1** → v2.12 single-plan schema (top-level per-plan fields,
  `active_plan: "plan1"`).
- **Length ≥ 2** → `plan_chain[]` schema, `active_plan` integer index.

Phase -1 step b constructs the chain: index 0 `status: "running"`; indices ≥ 1
`status: "queued"` with `blocked_until:
"plan_chain[i-1].all_tasks_complete_or_skipped"`. Phase 0 Step 7 fills ONLY the
active entry's per-plan data; queued entries are filled when their swap fires.

## Cross-Plan Trigger (Phase 2 Step -1)

Fires only when `plan_chain` exists and the next entry is `queued`. Advances
`active_plan` from i to i+1:

1. **Verify LOW batch sweep PASSED** for `plan_chain[i]`:
   `low_tasks_pending_verification == []` AND no
   `verifier_results/batch_final_p<i>.json` with `status: FAIL`.
2. **Verify all `plan_chain[i].tasks` are COMPLETE or SKIPPED.** If any remain,
   skip Step -1 and fall through to Step 1 (Final Docs Updater).
3. **Swap pointer:** `active_plan = i+1`; mirror `plan` / `spec` to
   `plan_chain[i+1].plan_path / .spec_path`; set `mode = "plan_chain_running"`.
4. **Reset run-level transient counters:** `current_task=0`,
   `current_step_within_task=1`, `current_pre_task_sha=null`,
   `current_pre_group_sha=null`, `current_review_retries=0`,
   `current_verifier_retries=0`, `current_escalation_count=0`,
   `current_previous_issues=[]`.
5. **Re-run Phase 0 Steps 3, 3.5, 4, 6** against plan i+1; write results INTO
   `plan_chain[i+1]` (NOT top-level). `plan_chain[i]` stays intact for archival.
6. **Re-take baseline** (Phase 0 Step 5) — plan i's changes are now in HEAD, so
   plan i+1's regression reference is measured fresh. Never reuse plan i's
   baseline. Write to `plan_chain[i+1].baseline`.
7. Set `plan_chain[i+1].status = "running"`; `plan_chain[i].status = "complete"`.
8. Begin Phase 1 Task 0 of plan i+1.

After the final plan (no `plan_chain[N]`), the trigger is skipped and execution
falls through to Step 1 (chain-level Final Docs Updater).

## Run-level args propagate across all plans

`implementer_model`, `parallel`, `risk`, `docs_scope` are written run-level and
the Cross-Plan Trigger does NOT reset them — every plan inherits the same model
selection, parallel toggle, etc. Per-plan overrides are deliberately unsupported:
a user wanting different models per plan invokes the skill once per plan.

`cost_ledger` / `budget_cap_usd` / `budget_action` are likewise run-level — one
unified ledger and budget cap span the chain; per-plan totals are derivable from
the `by_task` key prefix `<plan_index>::`.

## Per-plan result-file suffix

Verifier / Docs Updater output JSON under `<orch_dir>/{verifier,docs}_results/`
gets a `_p<index>` suffix in multi-plan runs to avoid cross-plan collision
(`batch_p0_2.json`, `phase_p1_4.json`, `batch_final_p<i>.json`,
`final_chain.json` for the cross-plan summary). Single-plan runs keep un-suffixed
paths. Aggregators must accept both shapes.
