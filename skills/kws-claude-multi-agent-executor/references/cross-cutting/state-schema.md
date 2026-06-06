# Cross-cutting: `state.json` schema

Canonical reference for the orchestrator state file written to
`<orch_dir>/state.json`. This is the single source of truth for the run; after
each compaction the orchestrator drops raw task detail from context and re-reads
from here. Phase 0 Step 7 (`references/phases/phase-0-setup.md`) is the
operational write site — this file documents the *shape* it produces and the
run-level vs per-plan split that every downstream read must respect.

See also: `cross-cutting/multi-plan-chain.md` (the `<active>` resolution rule),
`cross-cutting/agentlens-emit-sites.md` (the two `agentlens_*` run-level fields),
`cross-cutting/decisions-register.md` (the per-plan `decisions_register`).

## Run-level vs per-plan

Two field classes, dispatched by whether `plan_chain` is present:

- **Run-level** fields live at the TOP of `state.json` and span the entire
  orchestrator invocation, including every plan in a multi-plan chain. They are
  NEVER duplicated inside `plan_chain[i]` and are preserved across plan_chain
  swaps and Resume Chain handoffs.
- **Per-plan** fields live under `<active>` — top-level `state.*` for a
  single-plan run, or `state.plan_chain[state.active_plan].*` for a multi-plan
  run. See `cross-cutting/multi-plan-chain.md`.

| Class | Fields |
|-------|--------|
| **Run-level** | `schema_version`, `mode`, `active_plan`, `plan`, `spec`, `branch`, `worktree`, `orchestrator_dir`, `source_repo`, `test_command`, `implementer_model`, `spec_edits`, `chain_resume`, `current_task`, `current_step_within_task`, `current_pre_task_sha`, `current_pre_group_sha`, `current_review_retries`, `current_verifier_retries`, `current_escalation_count`, `current_previous_issues`, `phase_summaries`, `phase_doc_commits`, `budget_cap_usd`, `budget_action`, `cost_ledger`, `cost_tracking_waived`, `cost_tracking_waive_reason`, `archive`, `agentlens_orchestration_run`, `agentlens_healthy`, `context_budget`, `timestamps`, `plan_chain`, `dispatch_config` |
| **Per-plan** (`<active>`) | `tasks`, `task_summaries`, `quality_trend`, `baseline`, `low_tasks_pending_verification`, `global_constraints`, `compaction_points`, `execution_plan`, `risk_levels`, `task_complexity`, `task_header_prefix`, `last_compaction_after_task`, `last_completed_task`, `last_completed_at`, `plan_review`, `spec_manifest`, `decisions_register`, `verification_gaps`, `docs_gaps` |

Hard-coding a per-plan field at top-level for a multi-plan run silently corrupts
the chain: plan 0's data writes to top-level while plan 1's writes to
`plan_chain[1]`, and the two trees diverge.

## Single-plan shape

```json
{
  "schema_version": "2",
  "mode": "<interactive_session | interactive_attached | headless_running>",
  "active_plan": "plan1",
  "plan": "<plan path>",
  "spec": "<spec path>",
  "branch": "<branch name>",
  "worktree": "<$HOME/.claude/worktrees/<RUN_ID>>",
  "orchestrator_dir": "<$HOME/.claude/orchestrator/<RUN_ID>>",
  "source_repo": "<canonical git common dir of source repo — exclusivity key (v2.20)>",
  "test_command": "<derived in Phase 0 baseline step>",
  "baseline": {"passing": 0, "failing": 0},
  "risk_levels": {},
  "compaction_points": [],
  "execution_plan": [],
  "task_header_prefix": "### ",
  "global_constraints": {"shared_files": {}},
  "plan_review": {"status": "SKIPPED", "warnings": []},
  "implementer_model": {"used": "<sonnet | opus>", "default": "sonnet"},
  "task_complexity": {},
  "quality_trend": [],
  "tasks": {},
  "task_summaries": {},
  "spec_edits": [],
  "low_tasks_pending_verification": [],
  "last_compaction_after_task": -1,
  "last_completed_task": null,
  "last_completed_at": null,
  "current_task": 0,
  "current_step_within_task": 1,
  "current_pre_task_sha": null,
  "current_pre_group_sha": null,
  "current_review_retries": 0,
  "current_verifier_retries": 0,
  "current_escalation_count": 0,
  "current_previous_issues": [],
  "phase_summaries": [],
  "phase_doc_commits": [],
  "chain_resume": null,
  "budget_cap_usd": null,
  "budget_action": "warn",
  "dispatch_config": {
    "plan_reviewer": "agent", "verifier_batch": "agent", "verifier_per_task": "agent",
    "transition_combined": "agent", "docs_updater_phase": "agent", "docs_updater_final": "agent",
    "final_sweep": "agent"
  },
  "cost_ledger": {
    "by_task": {}, "by_role": {}, "by_model": {},
    "totals": {"input_tokens": 0, "output_tokens": 0, "cached_read_tokens": 0,
               "cached_write_tokens": 0, "cache_read_tokens": 0,
               "cache_creation_tokens": 0, "cost_usd": 0.0, "dispatches": 0}
  },
  "archive": null,
  "agentlens_orchestration_run": null,
  "agentlens_healthy": null,
  "context_budget": {
    "effective_input_budget": 170000,
    "threshold_ratio": 0.60,
    "threshold_tokens": 102000,
    "last_evaluation_at": null,
    "last_evaluation_tokens": 0
  },
  "timestamps": {"started_at": null, "completed_at": null}
}
```

For a single-plan run `active_plan` is the **string** `"plan1"` and the per-plan
fields sit at top level. There is no `"plan2"` string in any live state.json: the
v2.12 two-plan legacy shape (`plan2_state` + `active_plan: "plan2"`) is rewritten
into the `plan_chain[]` shape by `scripts/migrate_legacy_state.py` at Phase 0
Step 0 before any `<active>` logic runs.

## Multi-plan shape (`plan_chain`)

```json
{
  "schema_version": "2",
  "mode": "<...>",
  "active_plan": 0,
  "plan": "<plan_path_0 — mirrors plan_chain[0] for legacy readers>",
  "spec": "<spec_path_0 — mirror>",
  "branch": "...",
  "worktree": "<$HOME/.claude/worktrees/<RUN_ID>>",
  "orchestrator_dir": "<$HOME/.claude/orchestrator/<RUN_ID>>",
  "source_repo": "<canonical git common dir — exclusivity key (v2.20)>",
  "test_command": "<shared across all plans — derived once>",
  "implementer_model": {"used": "...", "default": "sonnet"},
  "plan_chain": [
    {
      "index": 0, "plan_path": "...", "spec_path": "...",
      "status": "running", "blocked_until": null,
      "baseline": {"passing": N, "failing": M},
      "tasks": {"task_0": {}}, "task_summaries": {},
      "risk_levels": {}, "task_complexity": {},
      "compaction_points": [], "execution_plan": [],
      "global_constraints": {"shared_files": {}},
      "quality_trend": [], "low_tasks_pending_verification": [],
      "last_compaction_after_task": -1,
      "last_completed_task": null, "last_completed_at": null,
      "plan_review": {"status": "PASS", "warnings": []}
    },
    {
      "index": 1, "plan_path": "...", "spec_path": "...",
      "status": "queued",
      "blocked_until": "plan_chain[0].all_tasks_complete_or_skipped",
      "baseline": null, "tasks": {}, "task_summaries": {}
    }
  ],
  "spec_edits": [],
  "current_task": 0,
  "current_step_within_task": 1
  // ... remaining run-level fields identical to the single-plan shape
}
```

When `plan_chain` is present, `active_plan` is an **integer** index. Per-plan
fields are NOT written at top level; `plan` / `spec` are convenience mirrors of
`plan_chain[active].plan_path / .spec_path`, never the source of truth. Queued
entries (`index ≥ 1`) are constructed by Phase -1 step b with `status: "queued"`;
Phase 0 Step 7 fills only the active entry. Each queued entry is filled with full
per-plan data when its swap fires at Phase 2 Step -1.

## Field-group notes

- **`mode`** is always a non-null string ∈ `{interactive_session,
  interactive_attached, headless_pending, headless_running, headless_chained,
  plan_chain_running, plan2_running}`. The resume protocol (Phase 0 Step 0)
  dispatches on this value. `interactive_attached` is the v2.22.0
  attached-by-default in-session mode (a bare invocation with neither `detach`
  nor `mode` passed runs attached rather than self-spawning headless).
  `plan_chain_running` is written by the Phase 2 Step -1 Cross-Plan Trigger when
  it advances `active_plan` to the next plan in a chain. `plan2_running` is the
  legacy v2.12 equivalent: a migrated state may still read it because the
  legacy-migration shim does NOT rewrite `mode`, so it must stay a recognized
  enum value (it dispatches to the standard resume path).
- **`context_budget`** (v2.15 C3) is run-level. Defaults
  `effective_input_budget=170000`, `threshold_ratio=0.60`,
  `threshold_tokens=102000`. `context_budget=<int>` overwrites the budget,
  `context_threshold=<float>` overwrites the ratio; recompute
  `threshold_tokens = round(budget * ratio)` after either.
- **`cost_ledger` / `budget_cap_usd` / `budget_action` / `archive`** (v2.14) are
  run-level and span the chain. `by_task` is keyed
  `"<plan_index_or_'top'>::<task_id>::<role>"` so one ledger covers the chain.
  `budget_action ∈ {pause, warn, off}`.
- **`cost_tracking_waived: bool`** (default absent/`false`) and the optional
  run-level **`cost_tracking_waive_reason: str`** (v2.28, D001) record that cost
  tracking was intentionally off for this run. Phase 0 Step 7 sets both
  deterministically (`cost_tracking_waived=true`,
  `cost_tracking_waive_reason="agent-dispatch-no-usage"`) when the run is
  `interactive_attached` AND no role gate in `dispatch_config` is `"api"`/`"p"` —
  the Agent tool exposes no `usage`, so an all-`agent` ledger cannot populate.
  When `cost_tracking_waived` is set, `finalize_run.py` suppresses the
  `cost_dispatches_zero` FAIL and the Final Summary renders
  `Cost tracking: WAIVED — {cost_tracking_waive_reason}`. Both fields are
  run-level and **preserved** across plan_chain swap and Resume Chain handoff
  (never recomputed once set). See `cross-cutting/agent-dispatch.md` for the
  budget-enforcement limitation this implies.
- **`dispatch_config`** (v2.22; extended v2.25) is run-level and spans the chain.
  Role gates — `plan_reviewer`, `verifier_batch`, `verifier_per_task`,
  `transition_combined`, `docs_updater_phase`, `docs_updater_final` — each
  `"p" | "api" | "agent"`, default `"agent"` (v2.25). `final_sweep` is
  `"api" | "batch" | "agent"`, default `"agent"`. `"agent"` dispatches the role
  in-session via the Agent tool on the subscription pool; see
  `references/cross-cutting/agent-dispatch.md`. Metered transports (`"api"`,
  `"p"`, `"batch"`) remain selectable per gate.
- **`verification_gaps` / `docs_gaps`** (v2.25) are per-plan arrays, default `[]`.
  They are populated by the agent-dispatch failure ladder (D003) when a
  load-bearing role cannot run after retry+api-fallback; rendered in the Final
  Summary Report.
- **`agentlens_orchestration_run` / `agentlens_healthy`** are run-level and
  preserved across swaps/handoffs — see `cross-cutting/agentlens-emit-sites.md`.
- **`timestamps.started_at`** is stamped at Phase 0 Step 7.5 (setdefault, via
  `phase_boundary.py phase-emit --type phase_0_started`); **`completed_at`** is
  overwritten at Phase 2 Step 2 (via `phase-emit --type phase_2_complete`). Both
  are bundled into the boundary helper so they cannot be silently skipped.
