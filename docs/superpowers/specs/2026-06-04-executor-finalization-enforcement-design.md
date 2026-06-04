# Design: Finalization + Schema Enforcement for kws-claude-multi-agent-executor (v2.26)

**Date:** 2026-06-04
**Status:** Design — pending implementation
**Target skill:** `skills/kws-claude-multi-agent-executor/`

## Motivation

Two real runs on 2026-06-04 (`source-matching-refinement-20260604-210431`,
`readmates-member-reading-experience-20260604-210358`), both `interactive_attached`
mode, completed all tasks functionally but left their `state.json` in an
inconsistent / non-canonical state:

**source-matching (canonical schema, unfinalized):**
- `timestamps.completed_at: null` despite top-level `status: COMPLETE`
- `task_10.verifier == "PENDING_BATCH"` — the final LOW batch sweep never wrote back
- `cost_ledger.totals.dispatches == 0` — `accumulate_cost.py` never invoked
- per-task `timing` carries only `completed`, never `started`
- `current_task: 10, current_step_within_task: 1` — the run stopped right after
  the last task's implement step and never walked Phase 2 (Step 0 sweep → Step 2
  completed_at stamp / report)

**readmates (non-canonical schema):**
- empty `tasks: {}` with all per-task data improvised into `task_summaries: {}`
- `execution_order` instead of the canonical `execution_plan`
- no `cost_ledger`, `dispatch_config`, `spec_manifest`, `quality_trend`
- a `risk_levels` value of `"verify"` (outside the low/mid/high enum)

The helper tooling these fields depend on **already exists**
(`phase_boundary.py phase-emit --type phase_2_complete` stamps `completed_at`;
`accumulate_cost.py` accumulates per-dispatch cost). The gap is **enforcement**:
in attached mode nothing forces the in-session orchestrator to reach Phase 2
finalization or to keep state.json canonical, so prose-mandated steps get skipped
under context pressure. This is the same class of regression the v2.16 guardrails
tried (and, per these logs, failed) to fix with prose alone.

## Goals

1. Detect the above inconsistencies mechanically with two standalone validators.
2. Auto-fix only what is genuinely safe (stamp `completed_at`); report everything
   else loudly without silent mutation.
3. Wire both validators into Phase 2 as gates, and into `evals/check_skill_contract.py`
   so the wiring cannot silently rot.
4. Lock the behavior with unit tests built from the two actual bad states observed
   today.

## Non-goals

- A Stop-hook forcing function (user-declined; cost/intrusiveness). A pure script
  cannot force a phase the orchestrator never enters — see Remaining Risks.
- Reconstructing missing cost data or `timing.started` retroactively (impossible
  from a finished run; reported as WARN only).
- Changing dispatch transports, risk tiers, scoring, or any sub-agent behavior.

## Deliverable A — `scripts/validate_state_schema.py` (check-only)

Active-tree aware (single-plan top-level + `plan_chain[]`). Mirrors the
`validate_method_audit.py` CLI contract: `--state <path>`, `--active-plan auto|<int>|plan1`,
JSON output `{passed, violations[], warnings[], scopes_checked[]}`, exit 0 (pass) /
1 (violations) / 2 (validator broken — cannot parse state.json).

Per active tree, **violations** (exit 1):
- canonical per-task shape: when the execution graph names N tasks, `tasks{}` MUST
  be populated; per-task records improvised into `task_summaries{}` while `tasks{}`
  is empty is a violation (the readmates divergence)
- `execution_order` present **without** `execution_plan` — non-canonical key
- `risk_levels` value outside `{low, mid, high}` (catches `"verify"`)

Run-level **violations**:
- missing any of `dispatch_config`, `cost_ledger`, `risk_levels` (when tasks exist)
- `mode` not in the allowed enum (state-schema.md set)

**warnings** (exit 0, reported): `schema_version != "2"`; `task_summaries` present
AND non-empty alongside a populated `tasks{}` (legacy mirror — tolerated).

Schema is not auto-fixable (no `--fix`); a divergent schema means the orchestrator
improvised and the run needs human inspection.

## Deliverable B — `scripts/finalize_run.py` (`--check` / `--fix`)

Active-tree aware. Same CLI/exit-code contract. Modes: `--check` (default,
read-only report) and `--fix` (apply safe writes, then re-check).

Invariants per active tree (each tagged FAIL or WARN):
1. **FAIL** — every task `status` ∈ {COMPLETE, SKIPPED}; not fixable
2. **FAIL** — no task `verifier == "PENDING_BATCH"`; **not** fixable by `--fix`
   (clearing it would fake verification — needs a real batch sweep), reported with
   the offending task ids
3. **FAIL** — `timestamps.completed_at` non-null; **fixable** — `--fix` stamps it
   via atomic read-modify-write (ISO-8601 now, or `last_completed_at` if present)
4. **WARN** — every task has `timing.started`; not retroactively fixable
5. **WARN** — `cost_ledger.totals.dispatches > 0` unless run-level
   `cost_tracking_waived == true`; not reconstructable
6. **FAIL** — `status` consistency: if `status == "COMPLETE"` then invariants 2 and 3
   must hold (no PENDING_BATCH, completed_at set)

`--fix` performs only invariant-3's stamp. Exit code after `--fix`: 0 iff no
unfixable FAIL remains (WARNs do not fail the gate). New optional run-level field
`cost_tracking_waived: bool` documented in state-schema.md and ARCHITECTURE.md §5.

The atomic write reuses the same pattern as `phase_boundary.py` /`state_set.py`
(read, mutate, write to temp, `os.replace`). `finalize_run.py` does NOT emit
AgentLens events — it is a consistency gate, not a boundary; `phase_boundary.py`
remains the emit site.

## Deliverable C — wiring (prose, additive)

- **Phase 2 Step 1.5** (`references/phases/phase-2-finalization.md`): after method-audit
  validation, run `validate_state_schema.py --state <orch_dir>/state.json --active-plan auto`.
  Exit 1 → halt with the violation list (do NOT close-run); exit 2 → halt
  "validator broken". Schema violations block close-run.
- **Phase 2 Step 2**: after the `phase_boundary.py phase-emit --type phase_2_complete`
  call and before `agentlens run-close`, run `finalize_run.py --check`. A residual
  unfixable FAIL halts before close-run with the report. (The orchestrator may run
  `--fix` first to stamp `completed_at`, then re-check.)
- **SKILL.md Guardrails**: one new row — "Finalization gate is mandatory before
  close-run" — naming both scripts and the no-silent-skip contract.

## Deliverable D — tests + eval

- `scripts/test_finalize_run.py`, `scripts/test_validate_state_schema.py` (pytest,
  matching existing `test_*.py` style: `tmp_path` fixtures, `_write`/`_read` helpers).
- Two regression fixtures derived from the **actual** observed states: (1) the
  source-matching unfinalized shape (PENDING_BATCH + null completed_at + dispatches 0
  + missing timing.started), (2) the readmates non-canonical shape (empty tasks{} +
  execution_order + verify risk). Each asserts the validators flag exactly the
  expected violations, and that `finalize_run --fix` stamps completed_at while still
  failing on the un-fixable PENDING_BATCH.
- Extend `evals/check_skill_contract.py`: helper-exists + CLI-contract checks for
  both scripts; wiring checks that the Phase 2 references mention
  `finalize_run.py --check` and `validate_state_schema.py`; a Guardrails-row wording
  check. `evals/run.sh` preflight runs this, so wiring rot fails CI.

## Deliverable E — docs / experiment record

Per the skill's AGENTS.md (multi-file behavioral change):
- `docs/experiments/v2.26-finalization-enforcement/` (README, JOURNAL, decisions/, findings/)
- ARCHITECTURE.md §5 (new `cost_tracking_waived` field) + §-script-catalog (two new scripts)
- HISTORY.md entry; `docs/decision-log.md` index for any ADRs
- `docs/doc-update-protocol.md` consulted; freshness check run before commit
- SKILL.md `version` bump (and snapshot if the protocol requires for a minor bump)

## Data flow

```
Phase 2 Step 1.5:  state.json ──> validate_state_schema.py --check ──> pass | HALT(violations)
Phase 2 Step 2:    phase_boundary phase-emit (stamps completed_at)
                   state.json ──> finalize_run.py --check ──> pass ──> agentlens run-close
                                              │
                                              └─ FAIL(PENDING_BATCH | completed_at) ──> HALT (no close-run)
```

Each unit is independently testable: validators take a state.json path and emit
JSON + exit code; the prose wiring is verified by the contract eval; neither script
depends on a live orchestrator or network.

## Remaining risks

- **Skipped Phase 2 still bypasses the gate.** If the orchestrator never enters
  Phase 2 (exactly the source-matching failure), nothing invokes `finalize_run.py`.
  This design makes finalization loud and self-correcting *once reached* and keeps
  the wiring honest via CI, but a true forcing function would require the declined
  Stop-hook. Documented; revisit if the failure recurs after this ships.
- **Attached-mode schema improvisation** is reduced (detected at Step 1.5) but not
  prevented at write time — same root cause. The validator turns a silent divergence
  into a hard halt at finalization, which is the best a post-hoc check can do without
  a write-path hook.
