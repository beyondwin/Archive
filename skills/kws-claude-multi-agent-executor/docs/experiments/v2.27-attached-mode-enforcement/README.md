# Attached-mode enforcement gaps (v2.27)

**Status**: SHIPPED — 2026-06-06 (see [findings/F01-close-out.md](./findings/F01-close-out.md))
**Branch**: `main` (in-repo skill change, following the v2.26 precedent)
**Production baseline**: v2.26.0 (SKILL.md frontmatter at experiment start)

## Goal

Three real 2026-06-06 runs, all `interactive_attached` mode (the v2.22 default),
exposed two enforcement gaps that v2.26 did **not** close:

| Run | Hooks wired? | timing.started | cost dispatches | schema (today) | finalize --check (today) |
|-----|-------------|----------------|-----------------|--------|------------------|
| `per-role-confidence-calibration-20260606-005019` | yes (all 4) | all null (7/7) | 0 — `cost_tracking_waived:true` | PASS | **passed:true** (7× WARN) |
| `readmates-host-prep-pace-20260606-003707` | **NO hooks block** | all null (5/5) | ledger **absent** | **FAIL** (`missing_cost_ledger`) | **passed:true** (1 cost + 5 timing WARN) |
| `plan-20260604-234058` (legacy `interactive_session`) | yes | populated (0 null) | 9 | PASS | PASS (clean) |

> Ground truth from running today's `finalize_run.py --check` / `validate_state_schema.py`
> against the three actual `state.json` files (2026-06-06). Note run-1 is *fully*
> green today (it set `cost_tracking_waived`, and null timing is only a WARN) — it is
> the clearest demonstration that a drifted attached run finishes silently green.
> Run-2 is caught only by the schema gate (absent ledger); its finalize is green.

Two distinct root causes:

1. **Hook-wiring gap (run 2).** Phase 0 Step 2.5 instructs the orchestrator to
   **hand-write** `<worktree>/.claude/settings.json` containing only a `hooks`
   key, with **no merge logic**. ReadMates ships its own `.claude/settings.json`
   (a `permissions.allow` allowlist + `$schema`). The hand-write preserved
   `permissions` but never added `hooks` → **none** of the four safety hooks were
   wired, including the v2.26 Stop gate — the very forcing function meant to catch
   a degraded finish was itself absent. The run finished green with a
   non-canonical, unfinalized state and nothing blocked it.

2. **Attached-mode bookkeeping drift (runs 1 & 2).** `phase_boundary.py
   task-start` (stamps `pre-sha` + `timing.started`) and `accumulate_cost.py`
   (per-dispatch cost ledger) are *mandatory* but live as **prose** in
   `phase-1-task-cycle.md`. The in-session attached orchestrator drifts past them
   under context pressure → `timing.started` null on every task, `dispatches: 0`.
   `finalize_run.py` treats both as **WARN**, so even a fully-drifted run reports
   `passed: true` and finalizes silently.

The legacy `interactive_session` run (run 3) is clean on every gate — confirming
the gaps are specific to the attached path, where every action is prose-driven
and skippable.

**Success criteria.** The two observed bad states are caught mechanically:
- A worktree whose source repo already has a `.claude/settings.json` ends up with
  the repo's keys **preserved** AND all four hooks wired; a missing Stop hook is a
  hard halt at materialization time.
- A run that drifts past task-start bookkeeping can no longer finish green: empty
  cost ledger and all-null `timing.started` become **blocking** finalize failures
  (the Stop gate then blocks the stop) unless explicitly waived.
- The clean `interactive_session` run (run 3) still passes — **no false positive.**

## Hypothesis

Both gaps share the v2.26 root shape: enforcement that lives in prose gets skipped
in attached mode. Moving the settings.json write into a deterministic, tested
script (with a self-assertion + a reusable `--check` preflight) eliminates the
hand-write divergence, and elevating the two drift signals from WARN to blocking
FAIL (with explicit waive escape hatches) lets the existing v2.26 Stop gate catch
the drift it currently lets through. The clean run proves the elevated severities
do not over-fire.

## Design

### Component 1 — `scripts/materialize_worktree_hooks.py` (NEW) — closes #1, provides #3

Replaces the hand-written JSON block in Phase 0 Step 2.5.

- **write mode** `--worktree <p> --orch-dir <p> --skill-dir <p>`:
  read `<worktree>/.claude/settings.json` if present (tolerate absent → `{}`);
  deep-merge so **all** existing top-level keys survive
  (`merged = {**existing}`), and the four hook events we own win
  (`merged["hooks"] = {**existing.get("hooks", {}), **our_four_events}`) —
  preserving the repo's `permissions`, `$schema`, and any *other* hook event types
  it defined. Atomic write (tmp + `os.replace`). Then run the same assertion as
  `--check`; a failed assertion is a non-zero exit.
- **`--check` mode** `--worktree <p>`: assert the four events
  (`PreToolUse`/`PostToolUse`/`SubagentStop`/`Stop`) are present and the `Stop`
  command references `finalization-stop-gate.sh`. Exit 0 if wired; exit 1 naming
  the missing hook(s) on stderr. No write. This is the **#3 preflight** — Phase 1
  calls it before Task 1 dispatch; non-zero is a hard halt (re-run Step 2.5).

Merge-policy note: for the four events we manage, our entry wins (a repo's own
PreToolUse/Stop under those keys is replaced — our safety hooks must run). Any
*other* hook event the repo defines (e.g. a `UserPromptSubmit`) is preserved. The
common real case (run 2) is "no `hooks` key at all," which reduces to "add hooks,
keep `permissions` + `$schema`."

### Component 2 — `finalize_run.py` severity changes — closes #2

- `cost_dispatches_zero`: **WARN → FAIL** (the existing `cost_tracking_waived`
  guard already suppresses it entirely when set — only the level changes).
- New aggregate check: if there is ≥1 terminal task AND **every** terminal task has
  null `timing.started` AND `not state.timing_tracking_waived` → **FAIL**
  `timing_tracking_absent`. The existing per-task WARN `timing_started_missing`
  stays for *partial* cases (some-but-not-all null), so a single docs-only task
  without timing does not fail an otherwise-tracked run.
- New `timing_tracking_waived` escape hatch (mirror of `cost_tracking_waived`).

**Honest limitation.** At Stop time the lost `timing.started`/cost data cannot be
reconstructed. Blocking does not *recover* data — it prevents a drifted run from
finishing **silently green**, forcing the orchestrator to either fix (re-run with
bookkeeping) or explicitly waive with a reason. This is the v2.26 philosophy
("loud, self-correcting halt"), not a data-recovery mechanism.

### Component 3 — prose / wiring changes

- **`phase-0-setup.md` Step 2.5**: replace the literal "Write this JSON" block with
  "run `materialize_worktree_hooks.py --worktree … --orch-dir … --skill-dir …`;
  non-zero exit = hard halt." The canonical JSON shape stays documented in
  `safety-hooks.md` as the reference the script emits.
- **`phase-1-task-cycle.md`**: add a one-line attached-mode preflight before Task 1
  dispatch — `materialize_worktree_hooks.py --check --worktree …`; non-zero = hard
  halt.
- **`safety-hooks.md`**: note that settings.json is now script-materialized and
  merged (not hand-written), and that sub-worktree byte-identical copy (Parallel
  Sub-Flow P.1) is unchanged.
- **SKILL.md Guardrails**: update the settings.json / Stop-gate rows; add the
  blocking cost/timing severity.

### Component 4 — bookkeeping

Version bump to **2.27.0**; HISTORY.md v2.27 entry; ARCHITECTURE.md sync;
`docs/decision-log.md` + `docs/experiments/README.md` index; this experiment's
JOURNAL + decisions + findings.

## Verification plan ("진짜 개선됐는지")

1. **Unit — script** (`test_materialize_worktree_hooks.py`):
   (a) no settings.json → 4 hooks created, `--check` passes;
   (b) **ReadMates shape** (`permissions.allow` + `$schema` only) → after merge,
   both preserved AND 4 hooks present — *the run-2 regression test*;
   (c) repo with its own `hooks.PostToolUse`/custom event → our 4 win, custom event
   preserved; (d) `--check` on a Stop-missing settings → exit 1 naming Stop;
   (e) idempotency: two writes → byte-stable.
2. **Unit — finalize** (extend `test_finalize_run.py`): dispatches==0 non-waived →
   FAIL; waived → no finding; all-null timing non-waived → `timing_tracking_absent`
   FAIL; waived → none; partial-null → WARN only, `passed` stays true.
3. **Regression replay (the real proof).** Copy the actual run-1 / run-2 / run-3
   `state.json` into fixtures. Expected, given the ground truth above:

   | Run | finalize today | finalize after #2 | why |
   |-----|----------------|-------------------|-----|
   | run-1 | passed:true | **passed:false** | `timing_tracking_absent` (7/7 null); cost stays suppressed by `cost_tracking_waived` — proves the waive hatch works |
   | run-2 | passed:true | **passed:false** | `cost_dispatches_zero` FAIL + `timing_tracking_absent` (also already schema-FAIL) |
   | run-3 | passed:true | passed:true | dispatches 9, 0 null timing — **no false positive** |

   run-1 is the headline: today it is *fully green* (it even set
   `cost_tracking_waived`), and only the null-timing drift remains to catch it.
4. **Stop-gate integration** (extend `test_finalization_stop_gate.py`): a "done"
   state with dispatches==0 + null timing → gate exit 2 (blocks); with both waives
   set → exit 0; run-3 shape → exit 0.
5. `pytest scripts/` + `./evals/run.sh` + `git diff --check` for no regressions.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis (close-out = the 구현문서)

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| Design doc + experiment scaffold | done | this record |
| materialize_worktree_hooks.py + tests (#1+#3) | done | 15 tests, ReadMates regression |
| finalize_run.py severity + tests (#2) | done | 13 tests |
| Prose wiring (Step 2.5 + Task-1 preflight) | done | |
| Regression replay + Stop-gate integration | done | the real proof — see F01 |
| Version bump + HISTORY/ARCHITECTURE/decision-log | done | 2.27.0 |
| findings/F01 close-out | done | the 구현문서 |
| D003 finalize hooks-wired backstop + tests + replay | done | closes the skipped-Step-2.5 residual; README/snapshot/decision-log synced |

## Decisions index

- D001 — Script-materialized + deep-merged worktree settings.json — [link](./decisions/D001-script-materialized-settings.md)
- D002 — Elevate drift signals (cost/timing) from WARN to blocking FAIL — [link](./decisions/D002-blocking-drift-severity.md)
- D003 — Finalize-time hooks-wired backstop (closes the skipped-Step-2.5 residual) — [link](./decisions/D003-finalize-hooks-wired-backstop.md)

## Findings index

- F01 — Close-out: what shipped + before/after replay proof — [link](./findings/F01-close-out.md)
