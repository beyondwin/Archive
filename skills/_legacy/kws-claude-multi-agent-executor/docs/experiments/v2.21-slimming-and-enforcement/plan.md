# v2.21 plan — helper contracts, eval checks, and split mechanics

Design rationale lives in the ADRs (D001–D005). This file is the build checklist
and the contracts not fully spelled out in the ADRs.

## New scripts

| Script | ADR | Depends on | Tests |
|--------|-----|-----------|-------|
| `scripts/state_set.py` | D001 | stdlib only | `scripts/test_state_set.py` |
| `scripts/phase_boundary.py` | D002 | state_set, accumulate_cost | `scripts/test_phase_boundary.py` |
| `scripts/migrate_legacy_state.py` | D004 | stdlib only | fixture-based test |

## `state_set.py` test matrix (D001)

- single-plan (no plan_chain): `tasks.task_0.status` → top-level `tasks`
- multi-plan (plan_chain, active=1): same field → `plan_chain[1].tasks`
- run-scope: `--plan-scope run` field `timestamps.completed_at` → top-level
- `--now`, `--inc` (missing→0), `--append-json` (missing→[]), `--setdefault-json`
- missing intermediate path auto-creates objects
- flock: two concurrent writers don't corrupt (serialize)
- readback failure → non-zero exit
- legacy plan2_state (pre-D004): active=="plan2" → plan2_state (then removed)

## `phase_boundary.py` subcommands (D002)

- `task-start`   : timing.started + current_pre_task_sha
- `task-complete`: task result write + timing.completed + last_completed pointers + emit task_completed (cost stays per-dispatch in accumulate_cost.py — see D002 refinement)
- `phase-emit`   : phase_0_started | compaction | phase_2_complete (+ paired stamp)

All AgentLens emits internal, `2>/dev/null || true`; non-emit work must succeed.

## AgentLens health probe (item 5, D005 delta 3)

At Phase -1 step b (run-open) / Phase 0: probe `agentlens` reachability once.
- Write `state.agentlens_healthy: bool` (run-level).
- If false (CLI missing OR run-open failed OR ORCH_RUN_ID empty): emit ONE stderr
  warning to the interactive parent: `WARN: AgentLens unreachable — this run will
  produce no observability events.` Run proceeds (never blocks).
- Recorded so post-run audit can distinguish "no events because nothing happened"
  from "no events because emits silently no-op'd".

## eval / contract additions

- `evals/check_skill_contract.py`: assert SKILL.md (or phase refs) reference
  `phase_boundary.py` at each documented emit site, and `state_set.py` for task
  writes (analogous to the v2.8.1 marker check).
- `evals/check_doc_freshness.py`: runs as-is; ensure new ADRs indexed in
  `docs/decision-log.md` and HISTORY.md has a v2.21 entry.

## Doc sync (item, task 8)

ARCHITECTURE.md: new scripts in tooling list; `state.agentlens_healthy` field;
note the helper-enforced emit/timing/cost. HISTORY.md §1 v2.21 entry + §3 index.
docs/snapshots/v2.21.md. docs/decision-log.md: index D001–D005.
docs/experiments/README.md + AGENTS.md experiment index.

## Regression

Free, after each extraction step: `python3 evals/check_skill_contract.py`,
`python3 evals/check_doc_freshness.py`, helper unit tests.
Paid, once at the end (USER APPROVAL REQUIRED): `evals/run.sh` on 1–2 fixtures
(suggest 02-three-file-refactor + 04-cross-plan-handoff to exercise multi-plan).
