# Design: Instrumentation Integrity for kws-claude-multi-agent-executor (v2.28)

**Date:** 2026-06-07
**Status:** Design — pending implementation
**Target skill:** `skills/kws-claude-multi-agent-executor/`
**Production baseline:** v2.27.0 (SKILL.md frontmatter at experiment start)
**ADRs:** [D001](../../../skills/kws-claude-multi-agent-executor/docs/experiments/v2.28-instrumentation-integrity/decisions/D001-cost-auto-waive-on-agent-path.md),
[D002](../../../skills/kws-claude-multi-agent-executor/docs/experiments/v2.28-instrumentation-integrity/decisions/D002-finalize-trigger-all-terminal.md),
[D003](../../../skills/kws-claude-multi-agent-executor/docs/experiments/v2.28-instrumentation-integrity/decisions/D003-timing-sanity-coverage-keys.md)

## Motivation

v2.27 ("close interactive_attached enforcement gaps", commit `13461bb`, shipped
2026-06-06 09:15 UTC) diagnosed the right disease — prose-driven bookkeeping gets
skipped in attached mode — but treated it almost entirely at the **finalize
boundary** ("block a drifted run from finishing silently green") rather than at
the **recording site**, and added a `cost_tracking_waived` / `timing_tracking_waived`
escape hatch.

Three real runs executed **after** v2.27 was in place prove the boundary-only
treatment did not hold. All three are `interactive_attached`, all three started
after 09:15 UTC, and **all three still produced an empty cost ledger** —
`finalize_run.py`'s blocking FAIL did not produce cost data, it produced a
**reflexive waive** (runs 1 & 2) or a **wedged, unfinalized run** (run 3).

Ground truth, from running today's `finalize_run.py --check` /
`validate_state_schema.py` against the three actual `state.json` files:

| Run | started (UTC) | tasks | `status` | cost `dispatches` | `cost_tracking_waived` | timing health | finalize `--check` today |
|-----|---------------|-------|----------|-------------------|------------------------|---------------|--------------------------|
| `session-package-decomposition-…205440` (run 3) | 11:57 | 16 COMPLETE | **null** | 0 | (unset) | task_1..5 `started` > `completed` (TZ-garbage) | **passed:false** — `cost_dispatches_zero` (unfixable) |
| `readmates-resilience-…214931` (run 2, 2-plan chain) | 12:55 | 7+ COMPLETE | **null** | 0 | **true** | 5 tasks `started:null` | passed:true (5× timing WARN) |
| `target-type-polymorphism-…235331` (run 1) | 14:55 | 7 COMPLETE | COMPLETE | 0 | **true** | late tasks fabricated round-number + out-of-order | passed:true (cost+timing waived) |

Run 3 is the clearest: it did **not** waive, so the blocking FAIL fired — and the
run simply never finalized (`status:null`, `current_task=16` still set). The gate
blocked the close but offered no path forward, so the run dangles. Runs 1 & 2 took
the other branch: set `cost_tracking_waived=true` and move on. Either way the cost
ledger is empty and v2.16's per-dispatch accounting is dead.

### The five gaps (all code-grounded)

1. **Cost tracking is structurally impossible on the default dispatch path, yet
   mandated.** `references/cross-cutting/agent-dispatch.md:38-42` and
   `references/phases/phase-1-task-cycle.md:347-369` both instruct the
   orchestrator to *"extract `usage` from the Agent return envelope … Subscription
   dispatches still report usage, so the ledger stays populated."* **This is
   factually false.** The Agent tool returns only the sub-agent's final text
   message to the orchestrator turn; there is no `usage` object the orchestrator
   can read. Since v2.25 made `"agent"` the default for every role gate, and the
   Implementer + Combined Reviewer are *always* Agent-tool dispatches, **no
   dispatch on the default path can feed `accumulate_cost.py`** → `dispatches:0`
   is structural, not a skip. `finalize_run.py:79-85` then makes `dispatches==0`
   a blocking FAIL unless waived — so the only reachable outcomes on the default
   path are *waive* or *wedge*.

2. **Finalization is still not forced for a run that never enters Phase 2.** 2 of
   3 runs ended `status:null` (never set COMPLETE). The v2.26 Stop gate
   (`references/hooks/finalization-stop-gate.sh.template:68-74`) only treats a run
   as "done" when `status==COMPLETE` **or** `current_task==null && last_completed_task!=null`.
   Run 3 has every task terminal but `status:null` and `current_task=16` (never
   cleared) → matches neither → the cheap short-circuit `exit 0`s and the session
   ends unfinalized. The end-signal the gate keys on is exactly the thing Phase 2
   sets, but the failure mode *is* "Phase 2 never ran," so the gate cannot see it.

3. **Timing data is fabricated/inverted, and the gate only checks presence.**
   `phase_boundary.py task-start` (line 98-105) already stamps a correct atomic
   UTC `timing.started`. The corruption is the orchestrator **hand-writing
   timestamps instead of calling it**: run 3's `task_1..5` have
   `started=2026-06-06T21:00:00Z` (local KST wall-clock with a bogus `Z`) while
   `completed=2026-06-06T12:02:06Z` — completed *nine hours before* started.
   `finalize_run.py:103-106` only checks `timing.started` is **non-null**, so all
   of this garbage passes (and `timing_tracking_absent` never fires for run 3 —
   its timestamps are present, just impossible).

4. **Telemetry coverage is silently near-zero.** `quality_trend` is `[]` for run 1
   (7 reviewed tasks, 0 entries) — the append at `phase-1-task-cycle.md:200` is
   prose and drifts. `agentlens_orchestration_run` is `null` for all three — the
   entire AgentLens pipeline emitted nothing, and every emit site no-op'd in
   silence. Nothing surfaces "telemetry was dark" to the user.

5. **Task-key naming is uncanonical and unchecked.** Run 1 keyed tasks `"1".."6"`
   + `"riskclose"`; runs 2/3 used canonical `task_N`. `validate_state_schema.py`
   has no task-key check, so bare-int and ad-hoc keys pass. Prefix-based consumers
   (`validate_method_audit.py`, ISSUE_KEY matching, Monitor jq) risk silently
   missing `"riskclose"`-style keys.

The common shape across 1, 3, 4, 5 is identical to the v2.16 / v2.26 / v2.27
lesson: **a value that must be recorded lives as prose the attached orchestrator
performs by hand, and under context pressure it is skipped or improvised.** v2.27
attacked this at the finalize boundary only. This experiment attacks it at the
recording site (where feasible) and fixes the one place where the recording is
*impossible by construction* (cost on the agent path) by making the system
**honest about it** instead of mandating the impossible.

## Goals

1. Stop the cost gate from firing on the default path where an empty ledger is a
   law of physics — by setting the waive **automatically and honestly** at Phase 0
   (with a machine-readable reason), and correcting the false "usage is available"
   prose. A metered (`api`/`p`) run is left un-waived and must accumulate real cost.
2. Force finalization on a structural signal (every declared task terminal), not
   only on the prose-set end-signal the failure itself suppresses.
3. Catch *physically impossible* timing (`started > completed`) as a blocking,
   un-waivable FAIL — distinct from the *absence* case the v2.27 hatch governs.
4. Move `quality_score` recording into the already-unskippable boundary write, and
   surface residual telemetry holes (sparse trend, dark AgentLens) as WARN.
5. Surface non-canonical task keys at the gate the Stop hook already runs.
6. No regression: clean `interactive_session` runs and any metered run still pass
   every gate; `pytest scripts/` and `./evals/run.sh` stay green.

## Non-goals

- **Reconstructing cost out-of-band** (parsing the host session's ccusage-style
  telemetry to back-fill the ledger). Explicitly **deferred**, not refused forever
  — recorded as the rejected alternative in [D001](../../../skills/kws-claude-multi-agent-executor/docs/experiments/v2.28-instrumentation-integrity/decisions/D001-cost-auto-waive-on-agent-path.md)
  so a future experiment can revisit it deliberately. v2.28 delivers *honesty*
  (the state and summary say "cost not tracked because the transport can't observe
  it"), not recovered cost data.
- **Removing `task_summaries`.** v2.28 documents it as a legacy read-mirror (no new
  writes) but does not delete it — a larger change, deferred.
- **Promoting `task_key_noncanonical` to a hard violation.** It ships as WARN;
  promotion is deferred until the prose that *writes* keys is itself tightened
  (blocking on a shape the skill's own prose still allows to drift is premature).
- Reconstructing missing `timing.started` retroactively (impossible from a finished
  run), or changing dispatch transports, risk tiers, or scoring.

## Deliverable A — Honest cost on the agent path (gap 1) — [D001]

The `cost_dispatches_zero` FAIL in `finalize_run.py:79-85` stays **exactly** as
v2.27 wrote it (already suppressed by `cost_tracking_waived`). No severity change.
The fix is upstream — make the waive *automatic and honest*, not manual:

- **Phase 0 (`references/phases/phase-0-setup.md` Step 7 state init) + resume
  path**: after `dispatch_config` is resolved, if the run is `interactive_attached`
  **and** no role gate is `api`/`p` (Implementer/Reviewer are always `agent`), set
  `cost_tracking_waived = true` and a new run-level
  `cost_tracking_waive_reason = "agent-dispatch-no-usage"` via `state_set.py`.
  Deterministic — derived from `dispatch_config`, not a prose judgement. A run with
  any metered gate is left un-waived. Resume/chain handoff must **preserve** an
  existing waive (same rule as the other run-level cost fields).
- **Doc corrections**: rewrite `agent-dispatch.md:38-42` and
  `phase-1-task-cycle.md:347-369` to state the truth — the Agent tool result does
  **not** expose `usage`; per-dispatch cost is unavailable on the agent path; that
  is *why* agent-default runs auto-waive; to get cost/budget enforcement, opt a
  gate into `api`/`p`. Remove the "call the helper with `{0,0}`" instruction (never
  followed; the auto-waive supersedes its intent).
- **Final Summary (`phase-2-finalization.md` Step 2 template)**: render
  `Cost tracking: WAIVED — agent-dispatch-no-usage` when the reason is set, instead
  of an unexplained `$0.00`.

**Honest limitation (must be stated in spec + summary):** auto-waiving cost also
disables `budget_cap_usd` enforcement and the token-based chain-resume trigger on
the default path, because both read the now-empty ledger. This is the accepted cost
of the agent-pool default; users who need budget enforcement opt a gate into
`api`/`p`.

## Deliverable B — Force finalization on "all tasks terminal" (gap 2) — [D002]

- **`references/hooks/finalization-stop-gate.sh.template`**: add a third `DONE=1`
  branch after the existing two (lines 68-74) — `[ "${TOTAL:-0}" -gt 0 ]`. With
  `NONTERM==0` already asserted at line 63 (early `exit 0` otherwise), this makes
  "every declared task terminal at Stop time" sufficient evidence the run must
  finalize, independent of the prose-set end-signal. The `TOTAL>0` guard preserves
  the fresh-run exemption (a run with no tasks is never "done").
- Because the Stop hook fires **only when the session is genuinely ending**, an
  all-terminal state at Stop time unambiguously means Phase 2 was skipped (a run
  about to run Phase 2 does not Stop). No false positive on the legitimate path:
  that run sets `status=COMPLETE`, which the existing first condition catches.
- **`phase-0-setup.md:161` + `safety-hooks.md` + SKILL.md Guardrails**: document
  the third trigger condition.

**Honest limitation:** the trigger fires `DONE=1`, then runs the **existing** full
gates. It is a *detection* fix (catch the skipped-Phase-2 shape), not a new
finalizer — if those gates have gaps, this surfaces the run to them but inherits
their limits.

## Deliverable C — Timing value sanity (gap 3) — [D003]

- **`scripts/finalize_run.py`** (per-tree task loop, around line 92-106): for each
  terminal task where both `timing.started` and `timing.completed` parse as
  ISO-8601, add a blocking FAIL `timing_inverted` when `started > completed`. Add a
  tolerant `_parse_iso(s) -> datetime | None` helper (returns None on unparseable,
  so malformed data falls through to the existing null/absence path rather than
  crashing).
- **Un-waivable by design.** `timing_inverted` is **not** gated by
  `timing_tracking_waived` — that hatch governs the *absence* case (all-null
  `timing.started`, the v2.27 `timing_tracking_absent` FAIL). An inverted timestamp
  is a different claim: timing *is* present and *physically impossible*. Waiving "I
  am not tracking timing" must not also waive "my data is corrupt."
- **`references/phases/phase-1-task-cycle.md`** (task-start ~line 40-47;
  task-complete ~line 379-385): add a one-line anti-pattern note — the orchestrator
  MUST NOT type a `timing.*` literal into state.json; the only sanctioned writers
  are `phase_boundary.py task-start` / `task-complete` (UTC, atomic). This addresses
  the *cause*; the FAIL is the *detection backstop*.

## Deliverable D — Telemetry coverage backstop (gap 4) — [D003]

- **Move the writer (`scripts/phase_boundary.py cmd_task_complete`, ~line 119-127)**:
  when the passed result object carries a `quality_score`, append it to
  `<active>.quality_trend` (cap 10, drop oldest) inside the *same atomic write* that
  already records the task result — the exact pattern that fixed `timing.completed`.
  The skippable prose append at `phase-1-task-cycle.md:200` is then removed (single
  unskippable writer).
- **Detect residual holes (`scripts/finalize_run.py`, run-level, after the cost
  block ~line 85)**: two **WARN**-level findings (never FAIL — telemetry is
  best-effort by the v2.10 / v2.17 policy): `quality_trend_sparse` when
  `len(quality_trend) < terminal_tasks_with_review`, and `agentlens_run_absent`
  when `agentlens_orchestration_run` is null.
- **Final Summary**: an "Observability" row — AgentLens run id (or `dark — agentlens
  unavailable at run-open`) + quality_trend coverage — so a dark run is visible at
  close-out rather than discovered by forensics weeks later.

**Severity rationale:** WARN never FAIL — a missing AgentLens record or a sparse
trend means observability degraded, not that the *code work* is wrong. Blocking a
correctly-implemented run because its telemetry is thin would be the over-firing
this experiment argues against.

## Deliverable E — Task-key canonicalization check (gap 5) — [D003]

- **`scripts/validate_state_schema.py`** (per-tree loop, ~line 72-101): add a
  module-level `TASK_KEY_RE = re.compile(r"^task_\d+(_[a-z0-9-]+)?$")` and a WARN
  `task_key_noncanonical` listing any `tasks{}` key that does not match (canonical:
  `task_3`, `task_7_remediation`). WARN, not violation: a finished run whose keys
  merely deviate should surface the drift at the Stop gate without being
  hard-blocked.
- **`references/phases/phase-0-setup.md` / `phase-1-task-cycle.md:391`**: reinforce
  that `tasks{}` keys are always `task_<N>`; remediation/inserted tasks use
  `task_<N>_<suffix>`, never a bare integer or free-form label. Note `task_summaries`
  is a legacy read-mirror (no new writes).
- `task_summaries_alongside_tasks` stays a WARN (unchanged).

## Deliverable F — bookkeeping + experiment record

Version bump to **2.28.0**; SKILL.md Guardrails rows (cost auto-waive, all-terminal
Stop trigger, `timing_inverted`); HISTORY.md v2.28 entry; ARCHITECTURE.md sync
(new `cost_tracking_waive_reason` field; finalize/telemetry checks);
`docs/decision-log.md` D001-D003 pointers; `docs/experiments/README.md` index;
the v2.28 experiment folder's JOURNAL + findings close-out; `evals/check_skill_contract.py`
wiring checks so the new prose can't rot.

## Data flow

```
Phase 0 Step 7:  dispatch_config resolved
                 └─ attached & no api/p gate ─> state_set cost_tracking_waived=true
                                                + cost_tracking_waive_reason

Per task:        phase_boundary task-complete (atomic):
                 result written ─> timing.completed stamped
                                ─> quality_score appended to quality_trend (cap 10)
                                ─> kws-cme.task_completed emitted

Session Stop:    finalization-stop-gate.sh
                 NONTERM>0 ───────────────────────────────> exit 0 (mid-flight)
                 NONTERM==0 & (status COMPLETE | cur null
                   | TOTAL>0 [v2.28]) ─> finalize_run --check + validate_state_schema
                                          │ pass ─> exit 0
                                          └ FAIL ─> exit 2 (block; run Phase 2)

Phase 2 Step 2:  finalize_run --check
                 ├─ cost_dispatches_zero  (FAIL unless waived; auto-waived on default)
                 ├─ timing_inverted       (FAIL, un-waivable)            [v2.28]
                 ├─ quality_trend_sparse  (WARN)                         [v2.28]
                 ├─ agentlens_run_absent  (WARN)                         [v2.28]
                 └─ validate_state_schema: task_key_noncanonical (WARN)  [v2.28]
```

Each unit is independently testable: the validators take a state.json path and emit
JSON + exit code; `phase_boundary` is driven by `tmp_path` fixtures; the prose
wiring is verified by the contract eval; none depends on a live orchestrator or
network.

## Remaining risks

- **Auto-waive hides cost on a run the user *did* want tracked.** Mitigation: only
  fires when no `api`/`p` gate is set AND mode is attached; any metered gate
  disables it; rendered loudly in the Final Summary + D001.
- **`timing_inverted` false-positive on legitimate clock skew.** Requires
  `started > completed` on the *same* task (one monotonic clock per run); sub-second
  skew cannot invert. The tolerant parser returns None on anything non-ISO, so only
  clearly-bad data fails.
- **All-terminal Stop trigger blocks a user who intentionally paused after the last
  task.** That is the intended behavior — finalize is mandatory. The gate's stderr
  prints the `finalize_run --fix` command; fail-open on any hook-internal error
  keeps it from trapping a broken session.
- **Skipped Phase 2 *and* a disabled Stop hook** would still bypass everything —
  the Stop trigger only helps when the hook is wired (the v2.27 D003 `hooks_not_wired`
  finalize backstop covers the wiring case). A run that strips both is out of scope.
- **`quality_trend_sparse` noisy on docs-only runs.** Counts only tasks with a
  `review_tier`/`review`; docs-only tasks without review are excluded from the
  denominator. WARN-only, never blocks.
