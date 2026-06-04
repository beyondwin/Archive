# v2.25 — Subscription-pool dispatch via in-session Agent tool ("agent" gate)

**Status**: In progress — design approved 2026-06-04, plan pending
**Branch**: `feature/v2.25-subscription-agent-dispatch`
**Production baseline**: v2.24 (data-driven cost tiering) on main

## Goal

Let the executor run the Verifier, Docs Updater, and Plan Reviewer roles on the
Claude **subscription pool** (Max/Pro) instead of metered API credits, without
losing autonomous (set-and-forget) execution. Success = a bare invocation runs
every role in-session on the subscription with `$0` metered spend; failure =
any role still hits `claude -p` / the Messages API on the default path.

## Motivation

Both existing dispatch transports for the headless roles are **metered**:

- `claude -p` headless (`dispatch_config.<gate> == "p"`) — billed against the
  CLI's API credits; its billing structure is changing.
- API-direct (`dispatch_config.<gate> == "api"`, the v2.22 default) —
  `scripts/dispatch_via_api.py` calls `anthropic.Anthropic()` with
  `ANTHROPIC_API_KEY`: pure pay-per-token.

The **only** dispatch path that runs on the subscription pool is the in-session
**Agent tool**, already used by the Implementer and Combined Reviewer (Phase 1
Steps 1–2). The six headless/API role gates plus the Phase 2 final sweep are the
metered leak:

```
plan_reviewer · verifier_per_task · verifier_batch ·
transition_combined · docs_updater_phase · docs_updater_final · final_sweep
```

Switching `-p` → `api` only changes *which* meter runs; it does not reach the
subscription. The subscription pool is only reachable by dispatching these roles
the same way Implementer/Reviewer are dispatched: as in-session Agent-tool
sub-agents.

## Design (approved 2026-06-04)

### 1. New gate value `"agent"`

Each role gate becomes `"p" | "api" | "agent"`. `final_sweep` becomes
`"api" | "batch" | "agent"`.

### 2. Default flip → subscription by default

All seven gate defaults flip `"api"` → `"agent"`. A bare invocation therefore
runs every role on the subscription pool. Metered transports remain available by
explicitly setting a gate to `"api"` or `"p"`. (See [D001](./decisions/D001-agent-gate-subscription-default.md).)

### 3. Agent dispatch pattern (prose, not a script)

The `-p`/`api` paths are **script-driven** (`claude -p`,
`scripts/dispatch_via_api.py`). The `"agent"` path is fundamentally different —
it is an **inline Agent-tool call the orchestrator model makes itself**, exactly
like the Implementer/Reviewer dispatch. It therefore cannot be a helper script;
it is a dispatch pattern defined in the phase prose.

When a gate resolves to `"agent"`:

1. **Build the SAME role prompt the `-p` path uses** — the `.txt` body with
   `{result_json_path}` and the other placeholders filled. No new prompt file.
   All three role prompts already instruct the sub-agent to *write its
   structured result to `{result_json_path}`* (verified:
   `plan-reviewer-prompt.md:130`, `verifier-prompt.md:67`,
   `docs-updater-prompts.md:63,130`).
2. **Dispatch via the Agent tool** on the role's model:
   - Verifier → `sonnet`
   - Docs Updater → `sonnet`
   - Plan Reviewer → `opus` (set via `dispatch_config.plan_reviewer_model`;
     overrides the prior `claude-haiku-4-5` default — user preference, the
     "Opus-everywhere" stance for this executor).
3. **Sub-agent writes the result JSON** to `{result_json_path}`, then returns.
4. **Orchestrator reads + schema-validates the file** exactly as the `-p`/`api`
   paths do (`verifier_result.schema.json`, `docs_updater_result.schema.json`,
   `report_plan_reviewer`). Downstream parsing is **unchanged** — the
   result-file seam is the integration point.
5. **Cost accumulation** — extract `usage` from the Agent return envelope and
   call the existing `scripts/accumulate_cost.py` (Phase 1 Step 4 already
   handles Agent-tool usage). Subscription dispatches still report usage tokens,
   so the ledger/observability stays populated.

### 4. Combined transition stays combined

For `transition_combined`, a **single** Agent sub-agent runs the `-p` combined
prompt and writes the combined `{verify, docs}` JSON. No split into two
dispatches — the v2.22 combined design is preserved.

### 5. detach conflict handling

`"agent"` gates only reach the subscription when the orchestrator runs
**attached**. Under `detach=true` the orchestrator is itself a `claude -p`
process, so its Agent sub-agents bill against that metered parent. Resolution
(evaluated in Phase -1 args parsing, right after mode determination; result
written into `state.dispatch_config`):

| Situation | Action |
|-----------|--------|
| `detach=true` + gate at **agent default** (not explicitly set) | Fall those gates back to `"api"` + one-line warning. Behaves exactly as pre-feature; the default never causes surprise metering. |
| `detach=true` + gate **explicitly** `"agent"` | Warn + proceed (respect explicit intent; no halt). |

See [D002](./decisions/D002-detach-conflict-handling.md).

### 6. Autonomous error handling — run to completion, never ask

User directive: on a recoverable error, do **not** prompt the user — judge the
best path and finish the run. (See [D003](./decisions/D003-autonomous-error-handling.md).)

**Agent-dispatch failure ladder (no user prompt):**

1. **Retry once** — re-dispatch the same role as a fresh sub-agent. Transient
   failures (missing result file, sub-agent crash) clear here.
2. **Auto-fallback to `api`** for that one dispatch — logged +
   `kws-cme.dispatch_fallback`. The single dispatch re-meters, but completion
   outweighs one metered call. Deliberate, scoped exception to the "no
   automatic fallback on API errors" guardrail: **`agent` → `api` direction
   only, after the retry.**
3. **`api` also fails** (after its own retry budget):
   - **Advisory role (Plan Reviewer):** warn + proceed (existing "absence is not
     a halt" policy).
   - **Load-bearing role (Verifier / Docs):** record a `verification_gap` /
     `docs_gap` marker in state + `kws-cme.blocker`, **continue the run**, and
     surface it prominently in the Final Summary Report. No halt, no prompt.

**Escalation autonomy (runtime AMBIGUITY / SPEC_BLOCKER):** instead of marking
the task SKIPPED and reporting, the orchestrator picks the **most defensible
interpretation**, records the rationale in `spec_edits` (with `fault` +
reasoning), proceeds without skipping, and surfaces the interpretation in the
Final Report.

### 7. Halt boundary — the two cases that still stop the run

Best judgment includes knowing when guessing is unsafe. Hard-halt is retained
**only** for:

1. **Data-integrity failures** — `state.json` write failure, `git reset`
   failure, worktree missing. Ignoring these corrupts the run.
2. **Phase 0 pre-flight structural/config errors** — out-of-repo file paths,
   missing `Files:` blocks, no task headers. The plan *input* is malformed;
   guessing (e.g. where an out-of-repo file should land) risks writing outside
   the repo. Setup-time structural errors halt; runtime ambiguity does not.

## Affected skill surface (for the implementation plan)

| File | Change |
|------|--------|
| `SKILL.md` | `dispatch_config` guardrail row + "API-direct default" row: add `"agent"` value, flip default; new gate-description + escalation-autonomy rows |
| `references/cross-cutting/state-schema.md` | gate enum `+ "agent"`, defaults → `"agent"`, `final_sweep` enum, detach-fallback note |
| `references/phases/phase-minus-1-args-and-spawn.md` | detach-conflict evaluation + warning |
| `references/phases/phase-0-setup.md` | plan_reviewer `"agent"` branch; state-init `dispatch_config` block (currently only in state-schema.md); plan_reviewer model → opus |
| `references/phases/phase-1-task-cycle.md` | verifier_per_task `"agent"` branch; autonomous failure ladder; agent-path cost note |
| `references/phases/phase-transition.md` | verifier_batch / transition_combined / docs_updater_phase `"agent"` branch (single combined sub-agent) |
| `references/phases/phase-2-finalization.md` | docs_updater_final + final_sweep `"agent"` branch |
| `references/phases/phase-1-escalation.md` | AMBIGUITY / SPEC_BLOCKER best-judgment autonomy; halt boundary |
| tests | agent dispatch branch, fallback ladder, detach fallback, schema roundtrip; `evals/run.sh` regression |

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log
- [decisions/](./decisions/) — ADRs
- [findings/](./findings/) — data + close-out

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| Design | DONE | Approved 2026-06-04 |
| Implementation plan | pending | via superpowers:writing-plans |
| Implementation | pending | |
| Close-out | pending | |

## Decisions index

- D001 — agent gate value + subscription-by-default — [link](./decisions/D001-agent-gate-subscription-default.md)
- D002 — detach conflict handling — [link](./decisions/D002-detach-conflict-handling.md)
- D003 — autonomous error handling + escalation autonomy + halt boundary — [link](./decisions/D003-autonomous-error-handling.md)

## Findings index

(none yet)
