# JOURNAL — Attached-mode enforcement gaps (v2.27)

Chronological log. Update **as you go**, not at the end.

---

## 2026-06-06

### Three runs reviewed (retrospective → fix)

Reviewed the three most recent `kws-claude-multi-agent-executor` runs:
`per-role-confidence-calibration-20260606-005019`,
`readmates-host-prep-pace-20260606-003707` (both `interactive_attached`), and
`plan-20260604-234058` (legacy `interactive_session`). Two enforcement gaps that
v2.26 did not close:

1. **Hook-wiring gap** — Phase 0 Step 2.5 hand-writes settings.json with no merge.
   ReadMates' pre-existing `.claude/settings.json` (permissions allowlist) meant
   the hand-write left `permissions` but added **no** hooks → all four safety hooks
   absent, including the v2.26 Stop gate. Degraded finish went unblocked.
2. **Bookkeeping drift** — `phase_boundary.py task-start` + `accumulate_cost.py`
   are prose-mandated; attached orchestrator skips them. `finalize_run.py` treats
   the resulting empty-ledger / null-timing as WARN, so the run finalized green.

Confirmed by reading the code: `phase-0-setup.md:141` (literal JSON write, no
merge), `finalize_run.py:49,66` (both WARN). Run 3 (`interactive_session`) clean on
every gate — gaps are attached-path specific.

### Design approved

User approved the three design decisions: (1)/(3) unified into a deterministic
`materialize_worktree_hooks.py` (deep-merge + self-assert + `--check` preflight);
(2) elevate cost/timing drift from WARN to blocking FAIL with `cost_tracking_waived`
/ new `timing_tracking_waived` escape hatches; docs under
`docs/experiments/v2.27-attached-mode-enforcement/`. See README for the full design
and verification plan. ADRs D001, D002.

(advisor tool not available in this environment — proceeding per AGENTS.md record
protocol; noted for close-out.)

### Implemented + verified (TDD)

Built all five plan tasks TDD-first:

1. `scripts/materialize_worktree_hooks.py` + 15 tests — `build_hooks` /
   `merge_settings` / `check_problems` / `do_write` / `do_check` / `main`. RED
   (ModuleNotFoundError) → GREEN. Includes the ReadMates-shape regression
   (`permissions` + `$schema` preserved AND 4 hooks present), idempotency, and
   unparseable-refusal. `chmod +x`.
2. `finalize_run.py` — `cost_dispatches_zero` WARN→FAIL (unless
   `cost_tracking_waived`); new `timing_tracking_absent` aggregate FAIL (every
   terminal task null `timing.started`, unless `timing_tracking_waived`); per-task
   `timing_started_missing` WARN retained; `verifier_pending_batch` loop given a
   `continue` so non-terminal tasks aren't double-counted. Updated 2 existing
   tests + 5 new; 13 pass.
3. `test_finalization_stop_gate.py` — `DRIFT_ONLY` blocks (exit 2),
   `DRIFT_WAIVED` allows (exit 0); 9 pass.
4. Prose wiring — phase-0-setup.md Step 2.5 → script call + hard halt;
   phase-1-task-cycle.md run-once Task-1 `--check` preflight; safety-hooks.md note.
5. Bookkeeping — SKILL.md 2.27.0 + 2 Guardrails rows; HISTORY §1 + §3;
   ARCHITECTURE; decision-log D001/D002; experiments index; F01 close-out.

**Real before/after replay** (committed HEAD vs new `finalize_run.py --check`
against the three actual run state.json):
- run-1 (per-role-confidence): `passed:true` → **`passed:false`**
  (`FAIL:timing_tracking_absent`; cost suppressed by its `cost_tracking_waived`).
- run-2 (readmates): `passed:true` → **`passed:false`**
  (`FAIL:cost_dispatches_zero` + `FAIL:timing_tracking_absent`; schema was already
  FAIL `missing_cost_ledger`).
- run-3 (plan-20260604, clean `interactive_session`): `passed:true` →
  `passed:true` — **no false positive**.

Full suite: `pytest scripts/` 197 pass; `git diff --check` clean.

### D003 — finalize-time hooks-wired backstop (residual close)

Closing the last "Remaining risk" item from the first close-out pass. The Step 2.5
write and the Phase 1 `--check` preflight are both prose; a run that skips Step 2.5
entirely wires **no** Stop gate, so nothing in-band catches it. Added a finalize-time
backstop that rides the Phase 2 Step 2 `finalize_run.py --fix` site (a distinct skip
from Step 2.5):

- `finalize_run.py` — new `hooks_not_wired` blocking FAIL. Reuses
  `materialize_worktree_hooks.check_problems` against `<worktree>/.claude/settings.json`;
  suppressed by new `hooks_wiring_waived`. **Skips silently** (returns `None`, never
  FAILs) when the helper is unavailable, no `worktree` key, or the file is
  absent/unparseable — so replays and cleaned worktrees never false-positive.
- 5 new `test_finalize_run.py` tests (unwired-FAIL, wired-pass, waive-suppresses,
  absent-settings-skips, no-worktree-key-skips) → 18 pass; 2 new
  `test_finalization_stop_gate.py` tests (unwired-blocks, unwired-waived-allows) →
  11 pass. Full suite `pytest scripts/` → 204 pass; `git diff --check` clean.

**Replay (HEAD/v2.26 vs new):** BEFORE all three `passed:true`. AFTER — run-1
`FAIL:timing_tracking_absent`; run-2 `FAIL:cost_dispatches_zero` +
`timing_tracking_absent` + **`hooks_not_wired`** (its worktree wired zero hooks —
now caught at finalize, not only at materialization); run-3 `passed:true`,
no findings (the legacy `interactive_session` run *did* wire all four hooks).

ADR D003. Folds into the unreleased v2.27.0 (no version bump). README version bump
+ `docs/snapshots/v2.27.0.md` + decision-log D003 row + safety-hooks.md /
SKILL.md notes synced.

(advisor tool still unavailable — recorded per AGENTS.md.)

---

## On close-out

See [findings/F01-close-out.md](./findings/F01-close-out.md) — SHIP.
