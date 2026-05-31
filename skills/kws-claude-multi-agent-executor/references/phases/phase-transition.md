# Phase Transition

> **Loaded by**: `SKILL.md` Phase Transition entry stub — orchestrator MUST
> `Read` this file when it reaches a compaction point (after Agent Cleanup of the
> boundary task, before starting the next task).
>
> **Scope**: Step T1.2 Combined Transition Dispatch (batch Verifier for
> accumulated LOW tasks + Phase Docs Updater, merged into one dispatch invoking
> both tools — v2.22 §2.A2), and Step T3 state anchor + context drop (including
> the token-health evaluation and Resume Chain trigger that lets a long run
> exceed one subprocess context). The Resume Chain *procedure* itself lives in
> `references/phases/phase-minus-1-args-and-spawn.md`.
>
> **Why extracted**: Phase Transition fires only at compaction points; keeping it
> out of the per-task hot path keeps the resident prefix smaller. v2.21 D005.

---

## Phase Transition

Execute at each compaction point, after Agent Cleanup of the boundary task and before starting the next task.

### Step T1.2: Combined Transition Dispatch

v2.22 §2.A2 merges the former T1 (batch Verifier) and T2 (Phase Docs Updater) — which used to run back-to-back — into ONE dispatch. The sub-agent calls BOTH tools, `verify_low_batch` and `update_phase_docs`, in a single turn. This saves ~50% of compaction wall time. The combined result is a single JSON `{verify:{...}, docs:{...}}` contracted in `references/_schemas/transition_combined_result.schema.json` and written to `<orch_dir>/transition_results/<plan_idx>_<compaction_index>.json` (helper: `scripts/dispatch_transition_combined.py`).

Build the prompt from the **Combined Transition Prompt Template** (`references/transition-prompt.md`) with:
- Risk level: `LOW (BATCH)`
- Files changed (verify): all files from all accumulated LOW tasks since the last compaction point
- Files changed (docs): all files from state file tasks since `last_compaction_after_task`
- Baseline: from Phase 0
- `{test_command}`: from state.json
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: `<orch_dir>/transition_results/<plan_idx>_<compaction_index>.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<orch_dir>/transition_prompts/<plan_idx>_<compaction_index>.txt`. Missing/malformed result → ENV_BLOCKER ESCALATE.

**Batch Verifier dispatch path (v2.22 §2.B2).** When `state.dispatch_config.verifier_batch == "api"`, the batch Verifier portion is dispatched through `scripts/dispatch_via_api.py --role verifier` (structured tool `report_verifier`, `tool_choice`-forced), and its `verify` result is validated against `references/_schemas/verifier_result.schema.json` before being consumed below. When `== "p"`, fall back to the legacy `claude -p` dispatch described above. The gate selects only the dispatch transport; the consumed `verify` shape (PASS/FAIL/ESCALATE) is identical either way.

Consume the combined result via `parse_combined_result` → `{verify, docs}`, then:

**`verify` PASS** → clear `low_tasks_pending_verification` in the state file; the `docs` commit stands.

**`verify` FAIL** → **guardrail:** the `docs` result is still consumed, but set `state.transition_blocked = true` and **skip the docs commit** until the verifier is re-dispatched and passes. Then apply this recovery algorithm:
0. **Pre-filter** (docs-only exclusion): For each task in `<active>.low_tasks_pending_verification`, read its entry under `<active>.tasks.task_N`. The task is docs-only if **either**:
   - `files_test` is present and equals `[]`, **or**
   - `files_test` is missing/null AND every entry in `files` ends with `.md` (heuristic fallback for legacy state.json).

   Docs-only tasks: exclude from batch test mapping. Run `markdownlint` (if available) on the changed `.md` files; if markdownlint is unavailable, run a syntax sanity check via `git diff --check` on the same files. Failures here count toward the task's `verifier_retries`.

   Tasks with test files proceed to the standard test-mapping algorithm below.
1. From the batch FAIL output, identify which test files failed.
2. Map each failing test file to the LOW task that last modified it (use `git log --oneline <worktree>` and task commit messages which include `Files:` lines).
3. If two LOW tasks both modified the same file and that file's tests fail: treat the LATER task as the likely cause — reset only that task to its `pre_task_sha`, re-implement it, then re-run the full batch.
4. If a single task is clearly responsible: reset that task's `pre_task_sha`, re-implement, re-run batch.
5. If responsibility is ambiguous after mapping: reset ALL tasks in this batch to the first batch task's `pre_task_sha`, then re-run them sequentially with per-task Verifier (treat as MID for this retry).
6. Apply `verifier_retries` counter per affected task. If any task hits limit: halt.

When a verifier re-dispatch later passes, clear `state.transition_blocked` and commit the held docs.

**`docs` ESCALATE** (missing/malformed docs result) → record `phase_docs_skipped` in state.json. The Final Docs Updater in Phase 2 will recover.

### Step T3: State Anchor + Context Drop

1. Flush the compaction anchor to the state file (both per-active, via `state_set.py`):
   ```bash
   python3 <skill_dir>/scripts/state_set.py --state "$ORCH_DIR/state.json" --field last_compaction_after_task --value "<current_task>"
   python3 <skill_dir>/scripts/state_set.py --state "$ORCH_DIR/state.json" --field low_tasks_pending_verification --value '[]'
   ```
   Each is a flock-guarded, active-tree-resolved, atomic write with readback (`--field` resolves under `<active>` by default). A non-zero exit is a hard halt per the state-file write guardrail.

1.1. **`kws-cme.compaction` event via `phase_boundary.py` (v2.17; helper-wired v2.21):** after the anchor write succeeds, emit the compaction boundary event. This marks a phase boundary in the AgentLens event stream so downstream viewers can segment per-phase metrics.

   ```bash
   COMPLETED=$(jq -r 'if .plan_chain then .plan_chain[.active_plan] else . end | [.tasks[] | select(.status=="COMPLETE")] | length' "$ORCH_DIR/state.json" 2>/dev/null || echo 0)
   python3 <skill_dir>/scripts/phase_boundary.py phase-emit \
     --state "$ORCH_DIR/state.json" \
     --run-id "${ORCH_RUN_ID:-}" \
     --type compaction \
     --payload-json "$(jq -nc \
       --argjson idx "<compaction_index>" \
       --argjson after_task "<current_task>" \
       --argjson completed "${COMPLETED:-0}" \
       '{compaction_index:$idx, after_task:$after_task, completed_tasks:$completed}')"
   ```

   For `--type compaction` the helper emits only (no run-level timestamp stamp — unlike `phase_0_started`/`phase_2_complete`). Emit is best-effort (empty `--run-id` → no-op; non-zero `agentlens` exit swallowed). The `context_health` candidate JSON in step 3 below remains unchanged — the `compaction` event is in addition to (not replacing) `context_health`. Step 3.5's candidate drain publishes `context_health` to AgentLens; this `compaction` emit is the explicit orchestrator-boundary event distinct from passive snapshots.

1.5. **Project decisions to DECISIONS.md (C2):** render `<orch_dir>/DECISIONS.md` from `<active>.decisions_register`. Format: a markdown table with columns `[Task, Decision, Files, Made at, Supersedes]`. Sort by `made_at` ascending. Group superseded entries (`supersedes != null`) at the bottom in a separate subsection. Use an atomic write: write to `DECISIONS.md.tmp`, then `mv` over `DECISIONS.md`. The file is included in the archive tarball (F1). Empty register → write a stub file with header `# Decisions register (empty)`. Failure → log warning, continue (best-effort like the register itself).

2. **Actively drop prior task context:** from this point forward, do not reference individual task details from before this compaction point. Work only from your structured task summary (what you have in internal notes from Agent Cleanup steps). If you need details from an earlier task, re-read the state file — do not hold raw sub-agent output in active context.

3. **Emit `context_health` passive snapshot (v2.10, v2.17 cutover):** write a candidate JSON to `<orch_dir>/learning_events/transition_<compaction_index>-orchestrator.json`. The Phase 1 Step 3.5 candidate-drain loop will publish it to AgentLens as `kws-cme.context_health` on the next orchestrator cycle. The event is informational — never alters control flow. Fields per `references/learning-log.md` "`context_health` (v2.10) — passive observation contract". Minimum body:
   ```json
   {
     "schema_version": "1",
     "phase": "phase_transition",
     "risk_tier": null,
     "event_type": "context_health",
     "severity": "low",
     "execution": {"task_id": "transition_<compaction_index>", "issue_key": "context_health_snapshot"},
     "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
     "summary": "Phase Transition T3 passive context-health snapshot.",
     "context": {
       "user_intent": "Observe context-management state across compactions.",
       "agent_expectation": "Counters captured at compaction boundary.",
       "actual_outcome": "Snapshot recorded.",
       "root_cause": "Routine emit point — not a failure.",
       "evidence": [{"kind": "issue_key", "value": "context_health_snapshot"}],
       "compaction_index": <index>,
       "completed_tasks_count": <count>,
       "resume_chain_handoffs": <handoffs>
     },
     "improvement": {
       "target": "references/learning-log.md",
       "proposal": "Aggregate context_health events to derive empirical thresholds.",
       "experiment_link": null
     },
     "privacy": {"redacted": true, "notes": "Counters only — no path/content."}
   }
   ```
   Append failure is silent (`|| true`) per the learning-log failure policy. **Do not use these counters to alter orchestrator behavior** — Goodhart's-law guard. Behavior changes require a follow-on experiment.

3.5. **Emit `chain_trigger_eval` (C3 — v2.15):** compute the trigger result via the should_chain logic (Resume Chain "Trigger (v2.15 — token-aware)" section). Update `state.context_budget.last_evaluation_tokens = session_input_tokens` and `state.context_budget.last_evaluation_at = <iso8601 now>`. Then write a candidate event to `<orch_dir>/learning_events/trigger_<compaction_index>-orchestrator.json`:

   ```json
   {
     "schema_version": "1",
     "phase": "phase_transition",
     "event_type": "context_health",
     "severity": "low",
     "execution": {"task_id": "transition_<compaction_index>", "issue_key": "chain_trigger_eval"},
     "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
     "summary": "Chain trigger eval: <chained|not_chained> | tokens=<N>/<threshold> | compactions=<N>/2 | completed=<N>/8",
     "context": {
       "trigger_decision": "chained" | "not_chained",
       "trigger_reason": "token_threshold" | "legacy_floor" | "none",
       "session_input_tokens": <int>,
       "threshold_tokens": <int>,
       "compactions_reached": <int>,
       "completed_count": <int>
     },
     "privacy": {"redacted": true, "notes": "Counters only — no path/content."}
   }
   ```

   Append silently (`|| true`). One event PER Phase Transition T3 regardless of decision — enables post-hoc A/B analysis of token-vs-legacy trigger lift. If `trigger_decision == "chained"`: proceed with the existing Resume Chain procedure (Phase 0 Step 0 Resume Chain section). If `not_chained`: continue execution.

4. **Evaluate budget (F2):** governed by spec §F2.4. Placement is **after** the state-anchor write (step 1) **and after** the `context_health` snapshot (step 3) — the spec timing supersedes the plan's "step 2.5" label.

   ```
   If state.budget_action == "off" OR state.budget_cap_usd is None: skip.
   Else if state.cost_ledger.totals.cost_usd >= state.budget_cap_usd:
     If state.budget_action == "warn":
       Emit a context_health learning event with severity=high, issue_key=budget_warning,
       summary="Budget warning: ${totals} of ${cap} cap consumed."
       Continue execution.
     If state.budget_action == "pause":
       Call close-run --outcome=blocked.
       Write HEADLESS_HALTED.txt with first line "reason: budget_exceeded".
       Exit orchestrator (headless child) or halt (interactive).
   ```

   The `warn` event is written as a candidate JSON under `<orch_dir>/learning_events/transition_<compaction_index>-budget.json` and drained to AgentLens by the Phase 1 Step 3.5 candidate-drain loop on the next orchestrator cycle — same pattern as the `context_health` snapshot in step 3, but with `severity: "high"` and `execution.issue_key: "budget_warning"`. Emit failure is silent.

   The `pause` branch emits a blocker event + closes the AgentLens run:
   ```bash
   if [ -n "${ORCH_RUN_ID:-}" ]; then
     agentlens event append --run "$ORCH_RUN_ID" \
       --type kws-cme.blocker \
       --payload-json '{"reason":"budget_exceeded"}' 2>/dev/null || true
     agentlens run-close --run "$ORCH_RUN_ID" --outcome blocked 2>/dev/null || true
   fi
   printf 'reason: budget_exceeded\n' > <orch_dir>/HEADLESS_HALTED.txt
   ```
   Then exit (headless child) or halt (interactive). The Monitor watcher will surface the HALTED line on its next loop.

**Phase Transition failure handling:**
- If T1.2 `verify` FAIL exceeds retries for any task: halt that task, record SKIPPED in state.json, continue Phase Transition.
- If T1.2 `docs` sends ESCALATE: skip docs for this phase. Record `phase_docs_skipped: [<phase_id>]` in state.json. The Final Docs Updater in Phase 2 will recover.
- If T3 state file write fails (Write tool error or Read-back fails): close the AgentLens run with `outcome=blocked` (best-effort, silent on failure) and then **hard halt immediately** — 'State file write failed at <path>. Risk of state corruption. Manual inspection required.' Do not proceed.
  ```bash
  if [ -n "${ORCH_RUN_ID:-}" ]; then
    agentlens run-close --run "$ORCH_RUN_ID" --outcome blocked 2>/dev/null || true
  fi
  ```
