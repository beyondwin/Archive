# Instrumentation integrity — attached-mode root causes (v2.28)

**Status**: Design — pending implementation — 2026-06-07
**Branch**: `main` (in-repo skill change, following the v2.26 / v2.27 precedent)
**Production baseline**: v2.27.0 (SKILL.md frontmatter at experiment start)

> **Spec (design)**: [`docs/superpowers/specs/2026-06-07-executor-instrumentation-integrity-design.md`](../../../../../../docs/superpowers/specs/2026-06-07-executor-instrumentation-integrity-design.md)
> **Plan (implementation)**: [`docs/superpowers/plans/2026-06-07-executor-instrumentation-integrity.md`](../../../../../../docs/superpowers/plans/2026-06-07-executor-instrumentation-integrity.md)
>
> This README is the **experiment record** — the field evidence and the
> hypothesis that motivate the change. The *design* (goals, non-goals, the six
> deliverables, data flow, remaining risks) lives in the spec; the *per-task
> edits + tests + ordering* live in the plan. This follows the superpowers
> convention used by v2.26
> ([`…/specs/2026-06-04-executor-finalization-enforcement-design.md`](../../../../../../docs/superpowers/specs/2026-06-04-executor-finalization-enforcement-design.md)
> + [`…/plans/2026-06-04-executor-finalization-enforcement.md`](../../../../../../docs/superpowers/plans/2026-06-04-executor-finalization-enforcement.md)),
> rather than embedding the spec in this file.

## Goal

v2.27 ("close interactive_attached enforcement gaps") shipped 2026-06-06 at
09:15 UTC (commit `13461bb`). It diagnosed the right disease — prose-driven
bookkeeping gets skipped in attached mode — but treated it almost entirely at the
*finalize boundary* rather than at the *recording site*, and added a
`cost_tracking_waived` / `timing_tracking_waived` escape hatch.

Three real runs executed **after** v2.27 was in place prove the boundary-only
treatment did not hold. All three are `interactive_attached`, all three started
after 09:15 UTC, and **all three still produced an empty cost ledger** — the
blocking FAIL produced a *reflexive waive* (runs 1 & 2) or a *wedged, unfinalized
run* (run 3), never cost data.

Ground truth, from running today's `finalize_run.py --check` /
`validate_state_schema.py` against the three actual `state.json` files:

| Run | started (UTC) | tasks | `status` | cost `dispatches` | `cost_tracking_waived` | timing health | finalize `--check` today |
|-----|---------------|-------|----------|-------------------|------------------------|---------------|--------------------------|
| `session-package-decomposition-…205440` (run 3) | 11:57 | 16 COMPLETE | **null** | 0 | (unset) | task_1..5 `started` > `completed` (TZ-garbage) | **passed:false** — `cost_dispatches_zero` (unfixable) |
| `readmates-resilience-…214931` (run 2, 2-plan chain) | 12:55 | 7+ COMPLETE | **null** | 0 | **true** | 5 tasks `started:null` | passed:true (5× timing WARN) |
| `target-type-polymorphism-…235331` (run 1) | 14:55 | 7 COMPLETE | COMPLETE | 0 | **true** | late tasks fabricated round-number + out-of-order | passed:true (cost+timing waived) |

> All three started after v2.27 shipped, so this is not "the fix wasn't in yet" —
> it is the fix's predicted failure mode in production. Run 3 is the clearest: it
> did **not** waive, so the blocking FAIL fired, and the run simply never
> finalized (`status:null`, `current_task=16` still set). The gate blocked the
> close but offered no path forward. Runs 1 & 2 took the other branch — set
> `cost_tracking_waived=true` and move on. Either way the cost ledger is empty and
> v2.16's per-dispatch accounting is dead.

**Success**: a default-path (attached + all-`agent`) run no longer FAILs finalize
on cost and no longer needs a hand-typed waive; a run whose every task is terminal
can no longer end without Phase 2; inverted/fabricated timestamps become a
blocking FAIL; empty telemetry and non-canonical task keys surface (WARN) instead
of staying silent — and the clean legacy `interactive_session` baseline plus any
metered `api`/`p` run still pass every gate (`pytest scripts/` + `./evals/run.sh`
green). The full success criteria and the no-regression argument are in the spec.

## The five gaps (one line each; full grounding in the spec)

1. **Cost is structurally impossible on the default dispatch path, yet mandated.**
   The Agent tool returns only the sub-agent's final text — no `usage` object — so
   no dispatch on the v2.25 all-`agent` default can feed `accumulate_cost.py`;
   `dispatches:0` is a law of physics, not a skip. `agent-dispatch.md:38-42` /
   `phase-1-task-cycle.md:347-369` falsely claim "subscription dispatches still
   report usage." → **D001** (honest auto-waive).
2. **Finalization is still not forced for a run that never enters Phase 2.** The
   v2.26 Stop gate only treats a run as "done" via `status==COMPLETE` or
   `current_task==null`, both prose-set by Phase 2 — but the failure mode *is*
   Phase 2 never running (run 3: all-terminal, `status:null`, `current_task=16`).
   → **D002** (all-terminal trigger).
3. **Timing is fabricated/inverted; the gate only checks presence.** Run 3's
   `task_1..5` have `started` nine hours *after* `completed` (KST literal + bogus
   `Z`); `finalize_run.py:104-115` only checks non-null. → **D003** (`timing_inverted` FAIL).
4. **Telemetry coverage is silently near-zero.** `quality_trend:[]` (run 1, 7
   reviewed tasks); `agentlens_orchestration_run:null` on all three; nothing
   surfaces "telemetry was dark." → **D003** (move the write into `task-complete`
   + coverage WARNs).
5. **Task-key naming is uncanonical and unchecked.** Run 1 keyed tasks `"1".."6"`
   + `"riskclose"`; `validate_state_schema.py` has no task-key check. → **D003**
   (`task_key_noncanonical` WARN).

The common shape across 1, 3, 4, 5 is the v2.16 / v2.26 / v2.27 lesson: **a value
that must be recorded lives as prose the attached orchestrator performs by hand,
and under context pressure it is skipped or improvised.** v2.27 attacked this at
the finalize boundary only; v2.28 attacks it at the recording site (where
feasible) and makes the system *honest* about the one place recording is
impossible by construction (cost on the agent path) instead of mandating the
impossible.

## Hypothesis

Two root causes the boundary-only fix could not reach:

1. **Mandating the impossible breeds reflexive waiving.** A "MANDATORY" step that
   cannot be satisfied on the default path teaches the orchestrator to waive or
   stall. Replacing it with an *automatic, reasoned* waive (gap 1) removes both the
   manual waive and the wedge, and makes the limitation honest and discoverable.
2. **Detection that keys on a prose-set signal cannot detect that signal's
   absence.** The Stop gate's "done" test depends on Phase 2 having run; the
   failure is Phase 2 not running. A *structural* trigger (all tasks terminal —
   gap 2), plus moving `quality_score` into the unskippable task-complete write
   (gap 4) and adding value-sanity (gap 3) and shape (gap 5) checks to the gates
   the Stop hook already runs, converts silent drift into a loud, self-correcting
   halt — the v2.26 philosophy applied to the data the v2.27 gate did not inspect.

The clean `interactive_session` baseline and any `api`/`p` metered run prove the
new severities and the auto-waive do not over-fire.

## Status / quick links

- **Spec (design)** — [`…/specs/2026-06-07-executor-instrumentation-integrity-design.md`](../../../../../../docs/superpowers/specs/2026-06-07-executor-instrumentation-integrity-design.md)
- **Plan (implementation, per-task edits + tests)** — [`…/plans/2026-06-07-executor-instrumentation-integrity.md`](../../../../../../docs/superpowers/plans/2026-06-07-executor-instrumentation-integrity.md)
- [decisions/](./decisions/) — ADRs per major decision
- [JOURNAL.md](./JOURNAL.md) — chronological log (created at implementation time)
- [findings/](./findings/) — close-out + replay proof (created at close-out)

## Decisions index

- D001 — Honest auto-waive for cost on the agent path (vs. mandate / out-of-band capture) — [link](./decisions/D001-cost-auto-waive-on-agent-path.md)
- D002 — Stop-gate trigger on "all declared tasks terminal" — [link](./decisions/D002-finalize-trigger-all-terminal.md)
- D003 — Timing value-sanity + telemetry-coverage + task-key checks (severities) — [link](./decisions/D003-timing-sanity-coverage-keys.md)

## Findings index

- F01 — Close-out: what shipped + ship decision + carried-forward remaining risks — [link](./findings/F01-close-out.md)

## Phase status

The canonical detailed docs are the superpowers
[spec](../../../../../../docs/superpowers/specs/2026-06-07-executor-instrumentation-integrity-design.md)
(design: goals, the five gaps, deliverables A–F, data flow, remaining risks) and
[plan](../../../../../../docs/superpowers/plans/2026-06-07-executor-instrumentation-integrity.md)
(per-task edits + tests + ordering). This table tracks landing status only.

| Task | Status | Notes |
|------|--------|-------|
| Spec + plan (superpowers convention) + D001-D003 | done | spec + plan in `docs/superpowers/`; this record points to them |
| C1 cost auto-waive + doc corrections + tests | done | D001 — Phase 0 Step 7 sets `cost_tracking_waived`/`cost_tracking_waive_reason`; false "still report usage" prose removed |
| C2 Stop-gate all-terminal trigger + tests | done | D002 — `elif [ "${TOTAL:-0}" -gt 0 ]` DONE=1 branch in the Stop-gate template |
| C3 timing sanity FAIL + anti-pattern prose + tests | done | D003 — un-waivable `timing_inverted` FAIL + `_parse_iso` in `finalize_run.py` |
| C4 quality_trend into task-complete + coverage WARNs + tests | done | D003 — `quality_trend` single-writer in `phase_boundary.py`; `quality_trend_sparse` + `agentlens_run_absent` WARNs |
| C5 task-key canonicalization WARN + tests | done | D003 — `TASK_KEY_RE` + `task_key_noncanonical` WARN in `validate_state_schema.py` |
| Regression replay (3 fixtures) + Stop-gate integration | pending | the real proof — Task 7 |
| Version bump + HISTORY/ARCHITECTURE/decision-log | done | 2.28.0; `v228_*` contract checks added; see findings/F01 |
| findings/F01 close-out | done | [findings/F01-close-out.md](./findings/F01-close-out.md) |
