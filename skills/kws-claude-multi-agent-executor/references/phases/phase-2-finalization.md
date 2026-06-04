# Phase 2: Final Phase

> **Loaded by**: `SKILL.md` Phase 2 entry stub — orchestrator MUST `Read` this
> file when all tasks are processed (COMPLETE or SKIPPED).
>
> **Scope**: Step -1 Cross-Plan Trigger (`plan_chain` advance), Step 0 LOW batch
> Verifier sweep, Step 1 Final Docs Updater, Step 1.5 Method Audit Validation, and
> Step 2 Generate
> Final Summary Report — which includes the `## Execution Summary` report template
> the orchestrator emits — followed by `agentlens run-close`.
>
> **Why extracted**: finalization runs once at the end of each plan. v2.21 D005.

---

## Phase 2: Final Phase

After all tasks are processed (COMPLETE or SKIPPED):

### Step -1: Cross-Plan Trigger (multi-plan only)

This step fires only when `state.plan_chain` exists (multi-plan run): advance `active_plan` from index i to i+1. If `plan_chain` is absent (single-plan), this step is a no-op — proceed to Step 0. A legacy `plan2_state`-shaped state.json has already been rewritten to `plan_chain` by the migration shim at Phase 0 Step 0, so there is no separate two-plan path here.

If `state.plan_chain` exists and there is some i where `state.active_plan == i` and `state.plan_chain[i+1]` exists with `status: "queued"`:

1. **Verify LOW batch sweep for current plan PASSED.** Read the active tree (`state.plan_chain[i]`). Check `low_tasks_pending_verification == []` AND that any `<orch_dir>/verifier_results/batch_final_p<i>.json` (per-plan suffix; see below) has no `status: FAIL`.

2. **Verify all tasks in `plan_chain[i]` are COMPLETE or SKIPPED.** The `blocked_until` for index i+1 is `"plan_chain[<i>].all_tasks_complete_or_skipped"` — resolve by scanning `plan_chain[i].tasks` for any task whose `status` is neither COMPLETE nor SKIPPED. If any remain: skip Step -1, proceed to Step 1 (Final Docs Updater handles whatever did finish).

3. **Swap pointer:** `state.active_plan = i + 1`. Update `state.plan = plan_chain[i+1].plan_path`, `state.spec = plan_chain[i+1].spec_path`. Update `state.mode = "plan_chain_running"`.

4. **Reset transient counters:** `current_task = 0`, `current_step_within_task = 1`, `current_pre_task_sha = null`, `current_pre_group_sha = null`, `current_review_retries = 0`, `current_verifier_retries = 0`, `current_escalation_count = 0`, `current_previous_issues = []`. These are run-level, not plan-level — same fields v2.12 used.

5. **Re-run Phase 0 Steps 3, 3.5, 4, 6 against Plan i+1.** Write the results (Plan i+1's `risk_levels`, `task_complexity`, `compaction_points`, `execution_plan`, `global_constraints.shared_files`) INTO `plan_chain[i+1]` — NOT top-level. The plan_chain entry for index i+1 keeps `plan_chain[i]`'s contents intact for archival.

6. **Re-take baseline.** Plan i's changes are now in HEAD. Run Phase 0 Step 5 fresh — `test_command` unchanged but counts re-measured. Write to `plan_chain[i+1].baseline`.

7. Set `plan_chain[i+1].status = "running"`. (Keep `plan_chain[i].status = "complete"` after step 2 succeeds; mark `"failed"` if step 1 found unresolved batch failures and recovery doesn't apply.)

8. Begin Phase 1 Task 0 of plan i+1.

**How to write these non-active-index fields:** several steps above touch a plan
entry that is NOT the active tree at the moment of writing — `plan_chain[i+1].*`
in step 3 (before the `active_plan` swap takes effect) and `plan_chain[i].status`
in step 7 (after the swap, i is no longer active). For these, use the dotted
run-scope form `state_set.py --field plan_chain.<index>.<field> --plan-scope run`
(e.g. `--field plan_chain.0.status --value '"complete"'`). The helper navigates
the existing list element in place — it does NOT collapse `plan_chain` into a
dict (see the D001 list-index contract in `scripts/state_set.py`). For writes to
the index that IS active after step 3's swap (steps 5–6, `plan_chain[i+1].*`),
`--plan-scope active` is equivalent and preferred. Never hand-roll a `jq`
`plan_chain[N] = …` reassignment for these — the typed helper is the contract.

After Plan N-1 (final plan in chain) completes Step 0 (LOW batch sweep), this Cross-Plan Trigger is skipped (no `plan_chain[N]` exists) and execution falls through to Step 1 (Final Docs Updater for the whole chain).

**Per-plan result file paths (v2.13):** Verifier and Docs Updater output files under `<orch_dir>/` need a per-plan suffix to avoid collision when one chain has multiple plans. Use `_p<index>` suffix:
- Phase Transition T1 batch: `verifier_results/batch_p<i>_<compaction_index>.json`
- Phase 2 Step 0 final LOW sweep: `verifier_results/batch_final_p<i>.json`
- Phase Transition T2 phase docs: `docs_results/phase_p<i>_<compaction_index>.json`
- Phase 2 Step 1 final docs: `docs_results/final_p<i>.json` PER PLAN, OR `docs_results/final_chain.json` for the cross-plan summary
- For single-plan runs: keep existing un-suffixed paths.

### Step 0: LOW Batch Verifier Sweep

**Phase 2 Step 0 — Budget evaluation (F2):** before dispatching the LOW batch verifier, run the same evaluation as Phase Transition T3 step 4 — this is the last chance to halt before incurring more cost. If `budget_action=pause` AND `state.cost_ledger.totals.cost_usd >= state.budget_cap_usd`: call `close-run --outcome=blocked`, write `<orch_dir>/HEADLESS_HALTED.txt` with first line `reason: budget_exceeded`, and exit. If `budget_action=warn` AND the same threshold is crossed: emit ONE `context_health` learning event (severity=high, issue_key=budget_warning, summary referencing totals/cap) under `<orch_dir>/learning_events/phase2_step0-budget.json` and continue. If `budget_action=off` OR `budget_cap_usd is None`: skip the check. The cap is compared against the run-level totals, so chained plans share one budget.

Read the active tree's `low_tasks_pending_verification` (resolution rule from Phase 0 Step 7: `state.plan_chain[state.active_plan].low_tasks_pending_verification` for multi-plan; top-level for single-plan).

**Short-circuit (avoid double dispatch):** if the list is **empty** AND `<active>.last_compaction_after_task == <final task index>` AND the matching T1 batch result file (`<orch_dir>/verifier_results/batch[_p<active>]_<last_compaction_index>.json`) exists with `status: PASS`: skip dispatch entirely — the final-task compaction point (added by Phase 0 Step 6's "always include final task" rule) already ran the sweep. Record `<active>.phase2_step0_skipped = "covered_by_T1_at_compaction_<index>"` for audit and proceed.

If the list is non-empty (or the short-circuit conditions are not met): dispatch headless batch Verifier (same pattern as Phase Transition T1).

When `state.dispatch_config.final_sweep == "batch"`, this Step 0 sweep dispatches through `scripts/dispatch_final_sweep_batch.py` (Anthropic Message Batches API, one request per LOW task, ~50% cheaper, 24h SLA) instead of synchronous per-task dispatch. The helper submits one batch, polls until it ends, and returns the same PASS/FAIL summary. On timeout (`--timeout`, default 30 min / 1800s) it emits a `kws-cme.batch_timeout` event, WARNs, and falls back to per-task synchronous API dispatch (`dispatch_via_api.dispatch`, `mode == "api_fallback"`). As of v2.25 the `dispatch_config.final_sweep` default is `"agent"` (see below); `"batch"` and `"api"` remain opt-in transports selected via `dispatch_config`.

When `state.dispatch_config.final_sweep == "agent"` (default, v2.25), the Step 0
LOW sweep dispatches each LOW task's Verifier in-session via the Agent tool per
`references/cross-cutting/agent-dispatch.md` (ROLE=verifier, MODEL=sonnet,
RESULT_PATH=`<orch_dir>/verifier_results/<task>.json`). Per-task failure ladder
applies; tasks that cannot be verified after retry+api-fallback are recorded in
`verification_gaps` and surfaced in the Final Report (not halted).

**Result path:** when `state.plan_chain` is in use, use `batch_final_p<active>.json` (consistent with Phase 2 Step -1 check). For single-plan: `batch_final.json` un-suffixed.

On PASS: clear the active tree's list. On FAIL: apply standard `verifier_retries` per affected task. Only after PASS proceed to Step -1 (Cross-Plan Trigger checks whether to advance to the next plan) or to Step 1 (Final Docs Updater) if no next plan.

This guarantees LOW task verification even when `compaction_points=[]` (short plans with no compaction points). The short-circuit above prevents the redundant LLM dispatch in the common case where the final compaction already covered every LOW task.

### Step 1: Final Docs Updater

**Scope rule (v2.13):**

- *Single-plan run* (no `plan_chain`): unchanged from v2.12 — one Final Docs Updater dispatch covering all tasks. Result path: `docs_results/final.json`.
- *Multi-plan run* (`plan_chain` present): TWO-tier behavior. Per-plan Phase Docs Updater already ran at each plan's compaction points (Phase Transition T2 with `_p<i>` suffix). Step 1 here dispatches ONE chain-level Final Docs Updater that summarizes the ENTIRE chain — input is the consolidated `task_summaries` from every `plan_chain[*].task_summaries`. Result path: `docs_results/final_chain.json`. Per-plan docs commits stay intact; the chain-level commit adds a top-level summary to `README.md` / `CHANGELOG.md` only.

If a Phase Docs Updater was NOT dispatched for the last phase of the active plan (no compaction point after the last task): dispatch one now for that plan first (per-plan, with `_p<active>` suffix in multi-plan mode), then proceed to the chain-level summary if multi-plan.

If per-plan updaters already covered all phases: dispatch only the top-level chain summary (multi-plan) or the un-suffixed single-plan final (single-plan).

**Final DECISIONS.md projection (C2):** re-render `<orch_dir>/DECISIONS.md` from the full union of `<active>.decisions_register` across every plan (iterate `state.plan_chain[*]` for multi-plan; top-level for single-plan). Same format and atomic-write contract as Phase Transition T3 step 1.5. This is the canonical, end-of-run snapshot — the per-T3 projections are intermediate.

Build from the **Final Docs Updater Prompt Template** with:
- All files changed: consolidated from state file across all tasks (all plans for chain runs)
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: per scope rule above

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<orch_dir>/docs_prompts/final{_chain | }.txt` and result path matching `{result_json_path}`. Missing/malformed result → ENV_BLOCKER ESCALATE.

**Final Docs Updater dispatch path (v2.22 §2.B2).** When `state.dispatch_config.docs_updater_final == "api"`, dispatch this Final Docs Updater through `scripts/dispatch_via_api.py --role docs_updater` (singular role; structured tool `report_docs_updater`, `tool_choice`-forced; run-wide payload = all files changed during the run across every plan + the final docs scope), and validate its result against `references/_schemas/docs_updater_result.schema.json` before consuming it. When `== "p"`, fall back to the legacy `claude -p` dispatch described above. The gate selects only the dispatch transport; the consumed DONE/ESCALATE shape and the result path are identical either way.

**Final Docs Updater `"agent"` path (v2.25, default).** When
`state.dispatch_config.docs_updater_final == "agent"`, dispatch in-session via
the Agent tool per `references/cross-cutting/agent-dispatch.md` with
ROLE=docs_updater, MODEL=sonnet, PROMPT_TEMPLATE=`references/docs-updater-prompts.md`
(Final section), RESULT_PATH matching the existing `{result_json_path}`. Failure
ladder: retry → api fallback → record `docs_gaps` + `kws-cme.blocker` + proceed.

### Step 1.5: Method Audit Validation (v2.11)

After the Final Docs Updater commit and before generating the Final Summary Report:

```bash
python3 <skill_dir>/scripts/validate_method_audit.py \
  --state <orch_dir>/state.json \
  --active-plan auto
```

**Script contract (required):**
- MUST accept `--active-plan auto` (default behavior): detect `state.plan_chain` presence and iterate every `state.plan_chain[N].tasks`; if absent, iterate top-level `state.tasks` PLUS `state.plan2_state.tasks` when the latter is non-null.
- MUST accept `--active-plan <int|plan1|plan2>` for forced single-plan audit (used by `query_run.sh` historical replays).
- **`plan2_state` read support is retained here (and in the diagnostic-path note below) on purpose** — `query_run.sh` replays *archived* state.json snapshots that may predate the D004 migration shim and were never rewritten in place. Live runs never reach this code with `plan2_state` present (the shim collapses it at Phase 0 Step 0), but frozen archives can still carry it, so the validator must read it. Do NOT strip it as "dead code."
- MUST exit with status 2 (NOT 1) if the script itself cannot parse state.json — distinguishes "audit failed" (exit 1) from "validator broken" (exit 2). On exit 2 the orchestrator halts with `validate_method_audit broken — manual inspection required` and does NOT close-run.
- If the installed validator does not advertise `--active-plan` in `--help`: halt immediately with `validate_method_audit.py predates v2.13 multi-plan contract; upgrade required before Phase 2 completion.` Multi-plan runs MUST NOT silently skip `plan_chain[1+]` audit because of an outdated validator.

Parse the JSON output:

- `"passed": true` → proceed to Step 2.
- `"passed": false` → for each entry in `failures`, write a learning-log candidate event:

  ```json
  {
    "schema_version": "1",
    "phase": "phase_2",
    "risk_tier": "high",
    "event_type": "method_audit_violation",
    "severity": "high",
    "execution": {"task_id": "<id>", "issue_key": "method_audit_missing"},
    "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
    "summary": "Task <id> missing required methods: <missing list>",
    "context": {
      "user_intent": "Validate that required disciplines were applied.",
      "agent_expectation": "All COMPLETE tasks emit method_audit evidence.",
      "actual_outcome": "Missing methods: <list>",
      "root_cause": "Sub-agent did not emit METHOD_AUDIT lines or evidence was incomplete.",
      "evidence": [{"kind": "missing_methods", "value": "<list>"}]
    },
    "improvement": {"target": "references/implementer-prompt.md",
                    "proposal": "Strengthen METHOD_AUDIT requirement or hook check.",
                    "experiment_link": null},
    "privacy": {"redacted": true, "notes": "Skill names only."}
  }
  ```
  Then halt:

  Substitute `<task_path_prefix>` in the message below per the active-tree resolution:
  - v2.13 multi-plan (`state.plan_chain` present): use `state.plan_chain[<N>].tasks` where `<N>` is the index that owns the failing task. If failures span multiple plans, list each prefix on its own line.
  - v2.12 legacy two-plan: `state.tasks` for `active_plan == "plan1"`, `state.plan2_state.tasks` for `active_plan == "plan2"`.
  - Single-plan: `state.tasks`.
  
  The validator script itself iterates all plans via `--active-plan auto`, but this user-facing diagnostic must point at the correct path so the operator edits the right node.

  ```
  Method audit FAILED for tasks: <comma-separated list>.

  To resolve, either:
    - Re-dispatch the failing task(s) with explicit instructions to emit
      METHOD_AUDIT: lines (see references/implementer-prompt.md).
    - If a method is genuinely not applicable, edit
      <task_path_prefix>.<id>.method_audit.waived in state.json with a reason,
      then re-run Phase 2.

  Validator output:
  <pretty-printed validator JSON>
  ```

  Do NOT call `close-run` — the run remains alive for the user's resolution. Standard hard-halt block applies.

### Step 2: Generate Final Summary Report

Before generating the report, invoke `Skill("superpowers:finishing-a-development-branch")` and include its recommendation in Cleanup Status.

**Stamp `completed_at` + emit `kws-cme.phase_2_complete` (v2.21 — bundled via `phase_boundary.py`):** before close-run, run the `phase-emit --type phase_2_complete` boundary helper. It bundles two writes that pre-v2.21 prose listed as separate, individually-skippable steps: (1) the canonical wall-clock end-marker `state.timestamps.completed_at = <iso8601 now>` (overwrite) that the Final Summary Report's "Total wall time" row depends on, and (2) the `kws-cme.phase_2_complete` AgentLens event. Observed regression the bundling prevents: pre-v2.16 runs left `completed_at: null` even when `meta.json.outcome=success`, because nothing in the Phase 2 prose explicitly wrote it. If the state.json write fails the helper exits non-zero and the standard state-file write guardrail applies (hard halt).

```bash
COMPLETED=$(jq -r '(if .plan_chain then .plan_chain[.active_plan] else . end | [.tasks[] | select(.status=="COMPLETE")] | length)' "$ORCH_DIR/state.json" 2>/dev/null || echo 0)
python3 <skill_dir>/scripts/phase_boundary.py phase-emit \
  --state "$ORCH_DIR/state.json" --run-id "${ORCH_RUN_ID:-}" --type phase_2_complete \
  --payload-json "$(jq -nc --argjson tasks "${COMPLETED:-0}" '{outcome:"success", completed_tasks:$tasks}')"
```

**`run-close` (v2.17) — separate step after the helper emit:** the order is intentional — the helper emits the boundary event first (so it lands in the run before close), then close the AgentLens orchestration run. `run-close` failure is silent and the summary report below still prints unchanged.

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens run-close --run "$ORCH_RUN_ID" --outcome success 2>/dev/null || true
fi
```

Idempotency note: `agentlens run-close` is idempotent — a re-entered Phase 2 Step 2 (e.g., chained meta-run where the final child reaches Step 2 after a chain handoff) calling it again is a no-op.

The hard-halt branches above (escalation exhaustion, budget pause, T3 state-write failure) similarly emit `kws-cme.blocker` and call `agentlens run-close --outcome aborted|blocked` per the spec §6.2 event taxonomy. v2.17 cutover (Task 11) removed the parallel legacy `append_learning_event.py close-run` calls.

Output:

```markdown
## Execution Summary

**Plan:** <path>
**Spec:** <path>
**Branch:** <branch name>
**Worktree:** <worktree path>
**State file:** <orch_dir>/state.json
**Models:** Orchestrator=Opus, Sub-agents=Sonnet
**Date:** <YYYY-MM-DD>

### Tasks
| Task | Status | Risk | Size | Spec | Quality | Tier | Escalations | Review Retries | Verifier Retries | Spec Clarifications | Duration |
|------|--------|------|------|------|---------|------|-------------|----------------|------------------|---------------------|----------|
| Task 0 | COMPLETE | low | SMALL | 0.95 | 0.90 | PASS | 0 | 0 | — (batch) | 0 | <M> min |

The `Spec Clarifications` column is sourced from `<active>.tasks.task_<N>.spec_clarifications` (the spec-edit-branch counter, distinct from `review_retries`). Non-zero values indicate the spec was edited mid-task to resolve a SPEC_BLOCKER or unclear contract — useful signal for plan-author feedback even when the task ultimately succeeded.

### Risk overrides (A5)

If `<active>.risk_override_warnings` is non-empty across any plan (resolve via the active-tree rule for each `state.active_plan` value), list each entry as one row:
- `task_<id>` — override=<level>, suggested=high, keywords=[<matched words>], ts=<iso8601>

If none across all plans: "Risk overrides: 0".

### WARN-tier tasks (P4)

For each task across every plan's task tree (`<active>.tasks` for each value of `state.active_plan` — iterate over `state.plan_chain[*].tasks` for multi-plan; top-level `state.tasks` for single-plan) where `review_tier == "WARN"`, list one row:
- `task_<id>` — spec=<score>, quality=<score> — warnings: <one-line summary from task_summaries.task_N.warnings>

If none: "WARN-tier tasks: 0".

### Dispatch gaps (D003)

If `verification_gaps` or `docs_gaps` are non-empty for any plan (aggregate
across the chain: iterate `state.plan_chain[*].{verification_gaps,docs_gaps}` for
multi-plan, top-level for single-plan), list each:
- **Unverified (agent+api both failed):** `task_<id>` — <reason> (ts)
- **Undocumented (agent+api both failed):** <scope> — <reason> (ts)

If both arrays are empty across all plans, omit this section entirely.

### Quality trend (P4)

- First 5 task quality_score mean: <X.XX>
- Last 5 task quality_score mean: <Y.YY>
- Delta: <signed>
- Note: <"stable" | "declining — review recent tasks" | "improving">

(Pull from each plan's quality_trend — iterate `state.plan_chain[*].quality_trend` for multi-plan, top-level for single-plan.)

### Performance
- Total wall time: <HH:MM from timestamps.started_at to completed_at>
- Longest task: Task N (<M> min)
- Total retries: <review_retries sum> review, <verifier_retries sum> verifier

### Changes Made
- `<file path>`: <one-line description>

### Verification Results
| Scope | Risk Level | Tests Run | Result |
|-------|------------|-----------|--------|

### Docs Updated
- `<file>`: <what was updated>

### Cleanup Status
- Worktree: **active** — branch `<name>` at `<path>`. Merge or delete when ready.
- Debug artifacts: none found
- Temp files: none found

### Remaining Risks
- <risk description>: <mitigation taken or "accepted">
```
