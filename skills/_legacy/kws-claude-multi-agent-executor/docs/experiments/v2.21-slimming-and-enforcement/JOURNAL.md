# JOURNAL — v2.21 slimming + enforcement hardening

Chronological log. Update as you go.

---

## 2026-05-29

### Opening — problem definition

User (kws) invoked the skill with "이거 개선할부분 제안해줘" (suggest improvements).
Reviewed SKILL.md (1872 lines), references/, scripts/, and the v2.19 token-cost
experiment (F001 size analysis, D001 split boundary — drafted but stalled awaiting
user approval; only Phase -1 extracted so far).

Proposed 6 improvement areas. User approved all 6 ("가장 나은방법으로 대공사라도
... 제안한거 다하자") with experiment records ("기록 동반 (권장)").

Two coupled root problems, both already self-documented in SKILL.md:
1. SKILL.md size (F001: ~65–70% resident-but-not-actively-referenced per cycle).
2. Recurring "prose-only mandatory step silently skipped" regressions
   (phase_0_started, accumulate_cost, timing fields). Each past fix added louder
   prose; the durable fix is runtime enforcement (the P1 hook precedent).

Decision to bundle items 1–6 into one experiment because the split (item 1) and
the enforcement helpers (items 2,3,5) touch the same Phase 0/1/Transition prose —
doing them separately would mean editing those regions twice.

### Plan / sequencing

Safety-first order: additive + unit-tested helpers (state_set, phase-boundary,
health probe) BEFORE the risky SKILL.md split. The split needs paid eval
regression (evals/run.sh) — will checkpoint with user before spending on that.

Working in-place on `main` (not a branch): the Archive monorepo currently has
uncommitted WIP on the sibling kws-codex-plan-executor skill, so a branch switch
would be disruptive. The experiment record carries the institutional memory; this
matches how v2.20 and the sibling skill are being developed (directly on main).

Next: write the 5 draft ADRs, then build state_set.py with tests.

### Build progress — additive helpers landed (items 2, 3, 4-partial, 5, 6)

All five ADRs written (D001–D005). Then, in safety-first order:

- **`scripts/state_set.py` + `test_state_set.py` (item 3, D001).** One helper for
  every active-tree write: dot-path field, value modes (`--value/--now/--inc/
  --append-json/--setdefault-json`), `--plan-scope active|run`, leading `state.`
  run-level escape. flock on a stable `<state>.lock` sibling (not state.json
  itself — the atomic rename swaps state.json's inode, so locking the file would
  let a concurrent writer read a stale inode; the sibling lock serializes
  correctly), temp+fsync+atomic-rename, readback. 19 tests incl. multi-plan
  resolution, concurrent-increment serialization, readback-failure raise.

- **`scripts/phase_boundary.py` + test (item 2, D002).** Subcommands task-start
  (pre-sha + timing.started), task-complete (result write + forced
  timing.completed + last_completed pointers + `kws-cme.task_completed` emit),
  phase-emit (boundary event + paired run-level timestamp stamp). Reuses
  state_set's active-tree resolution (single source). AgentLens emit is
  subprocess-isolated and swallows a missing CLI — every non-emit state write
  must still succeed. **Refinement vs the D002 sketch:** task-complete does NOT
  accumulate cost — cost is a *dispatch*-boundary concern (per role/model/usage),
  so accumulate_cost.py stays per-dispatch; folding it in would double-count or
  drop reviewer/verifier. ADR + plan.md updated to record this. 11 tests.

- **`scripts/migrate_legacy_state.py` + test (item 4, D004).** The resume shim:
  converts a `plan2_state`-shaped state.json (no `plan_chain`) into a
  `plan_chain[]` of length 2, moving the top-level per-plan fields to index 0 and
  `plan2_state` to index 1, coercing `active_plan` to an int, deleting
  `plan2_state`. No-op on already-modern or single-plan state. Idempotent. 12
  tests incl. run-level field preservation + no-aliasing of defaults. **Wired**
  into SKILL.md Phase 0 Step 0 (runs unconditionally on resume; hard-halt on
  non-zero). The actual *deletion* of the scattered `plan2_state` /
  `active_plan == "plan2"` branches is deferred to the SKILL.md split (D005
  delta 2 — multi-plan-chain.md is authored post-D004), since they are dead but
  harmless once the shim runs.

- **AgentLens health probe (item 5, D005 delta 3).** Added run-level
  `agentlens_healthy: bool|null` to the schema (both shapes) + the run-open block
  in phase-minus-1 (sets it from `ORCH_RUN_ID` non-empty, with the reworded
  one-shot WARN) + the resume-backfill setdefault. Lets post-run audit
  distinguish "nothing happened" from "emits silently no-op'd."

- **Headless vs cache (item 6, D003).** Finalized to "keep headless default" but
  **corrected the analysis** after re-reading the user memory: the user's point
  that SessionStart hooks drift the prefix is valid *and applies to this skill's
  headless orchestrator* (it gets SessionStart hooks too) — so headless is
  genuinely worse for cache, not neutral. Decision holds because (a) autonomy is
  the point and (b) the v2.21 slim makes any miss cheap. Documented in
  phase-minus-1 mode-detection; no auto-fan-out added (honors the memory); B
  (interactive default) offered as a non-blocking follow-up. Reject C.

- **Eval/contract (item 8-partial).** Extended `check_skill_contract.py` with
  v2.21 checks: the three helpers exist + carry their CLI tokens, SKILL.md wires
  the migration shim, SKILL.md records `agentlens_healthy`. Indexed v2.19 +
  v2.21 ADRs in `docs/decision-log.md` (closes the doc-freshness ADR-index
  failures). Contract check green; 42/42 helper tests green.

Pre-existing doc-freshness drift NOT touched (out of v2.21 scope): README at
2.17 vs SKILL 2.20, missing `docs/snapshots/v2.20.0.md`. The v2.21 version bump +
snapshot + HISTORY entry + ARCHITECTURE sync are deferred to release (after the
split), since bumping to 2.21 now would advertise an unfinished split.

### CHECKPOINT — remaining work needs a paid eval

What's left is **item 1 (the SKILL.md split)** and the **completion of item 4**
(deleting the now-dead `plan2_state` branches as part of authoring
`cross-cutting/multi-plan-chain.md`), plus the helper-wiring of `state_set.py` /
`phase_boundary.py` into the extracted phase references (D005 delta 1). Per the
plan's regression section this is the step that requires a **user-approved paid
`evals/run.sh` run** (suggested fixtures 02-three-file-refactor +
04-cross-plan-handoff). Extract-verbatim-first then wire-helpers-as-a-separate-
step is the D005 drift mitigation. Paused here for that approval rather than
doing a 1900-line reorganization on compacted context unverified.

---

## 2026-05-29 (cont.) — verbatim split landed (item 1 bulk)

User chose "compact 한다음 지금 전체 분할 진행" (after compacting, do the full split
now). Executed the D005 extraction in verbatim-first order. SKILL.md went from
**1883 → 275 lines**; all phase prose now lives in on-demand references:

| Reference | From SKILL.md lines | Lines |
|-----------|---------------------|-------|
| `phases/phase-0-setup.md` | Phase 0 (Steps 0–7.5) | ~672 |
| `phases/phase-1-task-cycle.md` | Phase 1 Steps 1–4 (incl. P15 spec-edit branch) | ~459 |
| `phases/phase-1-parallel-subflow.md` | Parallel Sub-Flow (P2) | ~105 |
| `phases/phase-transition.md` | T1/T2/T3 | ~180 |
| `phases/phase-1-escalation.md` | Escalation Protocol | ~83 |
| `phases/phase-2-finalization.md` | Phase 2 (Step -1 … Step 2 + report template) | ~274 |

Each SKILL.md phase section is now a thin "Procedure extracted (v2.21 D005) …
Read references/phases/<file>" pointer stub.

**Foundation change first:** `evals/check_skill_contract.py` now searches a
*corpus* (SKILL.md + `references/phases/*.md` + `references/cross-cutting/*.md`)
instead of SKILL.md alone, for both token-presence and the section-anchored
REQUIRED_WORDING checks (each anchor+wording co-locate within one phase file).
This matches the module docstring ("SKILL.md + references + scripts collectively
wire …") and keeps the contract green as prose migrates out. Verified green
*before* any extraction (content still in SKILL.md → no-op) and after every step.

**Deviations from the D005 file list (documented):**
- The P15 **spec-edit branch** stays inline in `phase-1-task-cycle.md` rather
  than becoming a separate `phase-1-spec-edit-branch.md` — it is a sub-branch of
  Step 2's Reviewer FAIL decision table, not a separable phase; splitting it
  would fragment the table.
- The **Escalation Protocol** got its own `phases/phase-1-escalation.md` (not
  enumerated in D005's list). It is a Phase-1/Parallel-triggered procedure; a
  thin stub in SKILL.md keeps the entrypoint uniform. The ESCALATE enum summary
  is intended to stay in the entrypoint Safety Gates section.
- The `## Execution Summary` "section" is actually the report *template* inside
  Phase 2 Step 2's ```markdown fence, so it travelled with
  `phase-2-finalization.md` (not kept separately as "output format").

Free checks after every extraction: `check_skill_contract.py` **green**;
`check_doc_freshness.py` shows only the two pre-existing out-of-scope failures
(README 2.17 vs SKILL 2.20 version drift; missing `docs/snapshots/v2.20.0.md`)
and `internal_links_resolve: true` (every new pointer resolves).

**Still NOT done (deliberately):** the D005 helper-wiring (replacing inline-jq
R-M-W / emit prose in the phase refs with `state_set.py` / `phase_boundary.py`
calls), the `plan2_state` dead-branch deletion (item 4 completion), the
cross-cutting de-dup files, the 2.21 version bump + snapshot + README/HISTORY
sync, and the **paid `evals/run.sh` regression**. Those are the behavioral steps
the plan gates behind a user-approved paid eval — paused here for that approval
rather than stacking unverified behavior changes on compacted context.

---

## 2026-05-29 (cont.) — plan2_state dead-branch deletion (item 4 completion)

User directive: "와이어링·삭제 먼저, 그다음 eval 승인 요청" (wiring + deletion first
with free checks, then request the paid eval). Completed the deletion half.

Cascade-deleted the v2.12 `plan2_state` **live-execution** branches now made dead
by the D004 migration shim (which collapses any legacy `plan2_state` state.json
to `plan_chain` at Phase 0 Step 0, before any `<active>` logic). Touched:

- **SKILL.md** — active-tree resolution table 3→2 rows (dropped the
  `active_plan=="plan2"` → `plan2_state` row); bash dispatch dropped the `plan2`
  elif; added a one-paragraph note that the shim guarantees no live state.json
  reaching Phase 1 carries `plan2_state`. Kept: the Phase 0 pointer-stub mention
  of "legacy `plan2_state` migration" (describes the shim) and `plan2_running` in
  the `mode` guardrail enum.
- **phase-0-setup.md** — deleted the dead "plan2_state initialization" block at
  Step 7 (Phase -1 builds queued `plan_chain[i]` entries; Step 7 never wrote
  plan2_state under v2.13), the two `"plan2_state": null` schema fields, the
  legacy resolution bullet, and the per-field resolution parentheticals.
  Reworded the shim paragraph (L40) so it no longer promises live `plan2_state`
  branches "elsewhere in this file." Kept the shim invocation (L36–40).
- **phase-1-task-cycle.md / phase-1-parallel-subflow.md** — dropped the
  `plan2_state` clauses from the quality_trend / tasks resolution parentheticals
  and the pre-group-sha reset note.
- **phase-minus-1-args-and-spawn.md** — simplified the three Monitor `jq`
  fragments (status snapshot, progress-watcher tree resolution, last_completed
  lookup) to `plan_chain` / top-level only; dropped the `plan2` elif.
- **phase-2-finalization.md** — deleted the entire `#### v2.12 legacy path —
  plan2_state two-plan` Step -1 subsection and the "two code paths" framing
  (Step -1 is now `plan_chain`-only); dropped legacy clauses from the LOW-sweep
  read, result-path, DECISIONS projection, and the WARN/quality-trend report
  iterators.

**Deviation from the JOURNAL's earlier "delete all 17 in phase-2" plan
(documented):** `plan2_state` **read** support is *intentionally kept* in the
`validate_method_audit.py` script contract (the `--active-plan auto` PLUS-clause,
the `<int|plan1|plan2>` flag, and the diagnostic-path note). Reason:
`query_run.sh historical replays` point the validator at *archived* state.json
snapshots, which are frozen and may predate the shim — they were never rewritten
in place, so they can still carry `plan2_state`. The live current run never hits
that code with `plan2_state` present, but archives can, so the validator must
read it. Added an explicit "do NOT strip as dead code" note at the contract so a
future cleanup pass doesn't remove it. The script itself (`validate_method_audit.py`,
4 `plan2_state` refs) is correspondingly left unchanged.

`mode: "plan2_running"` is **kept** as a recognized resume-mode string everywhere
it appears (Phase 0 Step 0 resume dispatch, the `mode` guardrail enum): the shim
does NOT rewrite `mode`, so a migrated state can still read `plan2_running`, and
that string is unrelated to the now-removed `plan2_state` key.

Free checks green after the deletion: `check_skill_contract.py` → `failures: []`;
`check_doc_freshness.py` → only the two pre-existing out-of-scope failures
(README 2.17 vs SKILL 2.20 drift; missing `docs/snapshots/v2.20.0.md`),
`internal_links_resolve: true`.

**Still NOT done (the directive's "wiring" half + the gated paid eval):** the
D005 helper-wiring (replacing inline-jq R-M-W / emit prose with `state_set.py` /
`phase_boundary.py` calls in the phase refs), the cross-cutting de-dup refs, the
2.21 version bump + snapshot + README/HISTORY sync, and the paid `evals/run.sh`
regression.

---

## 2026-05-29 (cont.) — D005 helper-wiring (item 17, the directive's "wiring" half)

Completed the helper-wiring half of the directive ("와이어링·삭제 먼저"). Replaced
inline-jq R-M-W / `agentlens event append` prose with single eval-checkable helper
calls at every mandated boundary across the extracted phase refs:

- **phase-0-setup.md** — Phase 0 start boundary → `phase_boundary.py phase-emit
  --type phase_0_started` (bundles `timestamps.started_at` setdefault).
- **phase-1-task-cycle.md** — `task-start` (pre-sha + `timing.started`; timing
  write intentionally strengthened from non-fatal warning to hard-fail) and
  `task-complete` (result write + `timing.completed` + `last_completed_*` pointers
  + `kws-cme.task_completed` emit, all bundled); `current_task` update →
  `state_set.py --plan-scope run`.
- **phase-transition.md** — T3 anchor writes (`last_compaction_after_task`,
  `low_tasks_pending_verification`) → `state_set.py`; compaction emit →
  `phase-emit --type compaction` (emit-only, no timestamp).
- **phase-2-finalization.md** — `completed_at` stamp + final emit →
  `phase-emit --type phase_2_complete` (bundles the `completed_at` overwrite +
  `kws-cme.phase_2_complete` event); `agentlens run-close` kept as the separate
  following step (emit-before-close ordering preserved).

**Deliberately left inline (no matching helper subcommand):** the escalation dual
counters (`current_escalation_count` / `tasks.*.escalations`) and the
`kws-cme.blocker` abort emit in phase-1-escalation.md; the parallel-group
`current_pre_group_sha` in phase-1-parallel-subflow.md. These are role-specific
fields outside `phase_boundary.py`'s boundary-type set
(phase_0_started/compaction/phase_2_complete + task-start/task-complete).

**Validator delta:** retired the "verified once the split lands" deferral in
`check_skill_contract.py`'s V221 block; added 7 emit-site wiring checks
(`phase_boundary_task_start_wired`, `…task_complete_wired`, `…phase_emit_wired`,
`…phase_0_started_wired`, `…compaction_wired`, `…phase_2_complete_wired`,
`state_set_wired`) that scan the corpus (SKILL.md + phases/*.md + cross-cutting/*.md).

Free checks green: `check_skill_contract.py` → `passed: true`, `failures: []` (all
7 new checks pass); `check_doc_freshness.py` → only the two pre-existing
out-of-scope failures (README 2.17 vs SKILL 2.20 drift; missing
`docs/snapshots/v2.20.0.md`), `internal_links_resolve: true`.

**Done since:** the cross-cutting de-dup refs (item 14 — all 5 files authored:
`state-schema.md`, `multi-plan-chain.md`, `agentlens-emit-sites.md`,
`safety-hooks.md`, `decisions-register.md` — consolidations only, no load-bearing
operational prose removed from phase files); the 2.21 version bump + snapshot +
README/HISTORY sync (item 15 — SKILL frontmatter `2.21.0`, HISTORY §1 v2.21.0
entry, README `현재 버전` line, `docs/snapshots/v2.21.0.md`). Both free checks now
green at 2.21.0: `check_doc_freshness.py` → `passed: true`, `failures: []` (version
drift + missing-snapshot failures resolved); `check_skill_contract.py` →
`passed: true`, `failures: []`.

---

## Paid eval run (item 16) — 2026-05-29, user-approved

Ran `./evals/run.sh fixtures/02 fixtures/04`. Preflight green. Two outcomes,
recorded to `evals/baselines/v2.21.0.json` (means 0.0 / 0.4):

- **Fixture 02 (three-file-refactor) → 0.0:** the headless `claude -p` child
  aborted after 31 turns / 75s / $0.21 on a transient API error — `400 ...
  'thinking' or 'redacted_thinking' blocks in the latest assistant message cannot
  be modified`. Environmental (Claude Code headless thinking-block replay), NOT a
  skill defect; `rubric pass_rate: null` because no state.json was produced. Re-run
  candidate.
- **Fixture 04 (cross-plan-handoff) → 0.4:** ran to completion ($5.67, 61k output
  tokens). The orchestrator's own close-out note surfaced a **real bug**: a
  `state_set.py --field plan_chain.0.status` write *collapsed the `plan_chain` list
  into a dict and dropped plan 0's data*; the run detected it during finalization
  and reconstructed `plan_chain[0]` from the initial snapshot. The eval did its job
  — it caught a data-loss regression in this release's own D001 helper.

**Bug root cause:** `state_set.py:_navigate_create` replaced any non-dict
intermediate path segment with `{}`. For `plan_chain.0.status` that overwrote the
`plan_chain` list itself. **Fix (free, same release):** `_navigate_create` /
`apply_op` / `_read_field` now index existing list elements by integer segment and
raise on a non-container intermediate instead of clobbering it. The Cross-Plan
Trigger (`phase-2-finalization.md`) now names the safe write mechanism for
non-active-index fields (`--field plan_chain.<i>.<field> --plan-scope run`). Five
regression tests added; `test_state_set.py` → 24 passed. HISTORY §1 updated.

## Paid eval RE-RUN (item 16) — 2026-05-29, user-approved (against fixed code)

Re-ran both fixtures on the fixed `state_set.py`. New `evals/baselines/v2.21.0.json`
means: **02 → 0.7 (passed), 04 → 0.5 (failed)**.

- **Fixture 02: 0.0 → 0.7, passed.** The transient API error did not recur; the run
  completed (3 files modified, 3 clean conventional commits, rename confirmed, zero
  review findings). Confirms the earlier 0.0 was environmental. correctness capped
  at 0.7 only because the harness `test_after` couldn't find `tests/`; cost_efficiency
  0.5 (wall-time 120% of budget).
- **Fixture 04: 0.4 → 0.5.** **The bug fix is confirmed — the run's close-out note
  has NO plan_chain-collapse/data-loss mention this time;** it reports "Both plans
  complete and verified; cross-plan chain handoff (active_plan 0→1 with
  re-baselining and contract consumption) executed end-to-end." The residual 0.5 is
  NOT a skill defect — the judge wrote "State verification was impossible —
  captured_task_statuses is null and FILES_CHANGED/diff are empty," i.e. the HARNESS
  failed to read multi-plan state.

**Two harness measurement bugs found (and fixed, free) — both pre-date v2.21:**
1. `run.sh` captured `jq '.tasks'` (top-level), which is `null` for a `plan_chain`
   run — multi-plan tasks live under `plan_chain[N].tasks`. The judge thus saw no
   task statuses and scored correctness/spec/quality blind. Fixed: branch on
   `.plan_chain` and capture `[.plan_chain[].tasks]` + flatten `plan_chain[].tasks[].files`.
2. `run.sh` ran `test_after` and `git diff` in `dirname(dirname(state_file))`, which
   post-v2.18 is `~/.claude/orchestrator` (the orchestrator base), NOT the worktree
   (a sibling under `~/.claude/worktrees/`). This is why `test_after` reported
   "tests/ not found" / `ModuleNotFoundError: src`. Fixed: use `state.worktree` for
   `git_log`, `test_after`, `diff_tail`, and the rubric workdir (`wt`).

`bash -n evals/run.sh` clean. These fixes do not retroactively change the recorded
0.7/0.5 numbers (those were produced by the buggy harness) — they make the NEXT run
measure multi-plan runs correctly.

**Disposition:** the skill is verified correct (both plans end-to-end; data-loss bug
fixed + confirmed gone + regression-tested). The recorded v2.21.0 baseline is
understood: 02=0.7 (harness test_after path), 04=0.5 (harness multi-plan capture) —
both harness artifacts now fixed, not skill regressions.

---

## Paid eval RE-RUN #2 (against the fixed harness) — 2026-05-29, user-approved

Re-ran 02+04 on the harness with the two measurement fixes above. New
`evals/baselines/v2.21.0.json`: **04 → 0.9 (passed), 02 → 0.0 (failed)**.

- **Fixture 04: 0.5 → 0.9, passed (correctness 1.0, spec 1.0).** The multi-plan
  capture fix worked exactly as intended: the judge could now read task statuses
  and the worktree diff, confirmed all expected files touched, 3 commits in range,
  and that Plan 2's `pre_task_sha` chains off Plan 1's final commit (cross-plan
  handoff + baseline retake verified end-to-end). This is the trustworthy number
  the harness fix was meant to unlock.
- **Fixture 02: 0.7 → 0.0 — a THIRD harness bug, not a skill regression.** The
  judge note shows 02's capture contained fixture 04's content (a Greeter class +
  `src/api.py`/`src/cli2.py`, "2 task entries both labeled task_0", total_tokens=0)
  — i.e. the capture grabbed a *foreign* run's `state.json`. Root cause: the
  capture used `ls -t "$HOME"/.claude/orchestrator/*/state.json | head -1`, the
  GLOBAL newest across all runs/sessions, with no scoping to the current fixture.
  When 02's own headless run was degenerate (02 has now scored 0.0 / 0.7 / 0.0
  across three attempts — environmentally flaky via the headless thinking-block
  replay error), the global-newest pick fell through to a leftover multi-plan dir.

**Free proof the skill is correct (no extra spend):** the genuine fixture-02 run
this time was `~/.claude/orchestrator/plan-20260529-222620` (single-plan, 3 tasks).
Inspected directly: all 3 tasks COMPLETE touching exactly `src/calc.py`,
`src/usage.py`, `tests/test_calc.py`; 3 clean conventional commits
(`refactor(calc) rename add_nums→add`, `refactor(usage)`, `test(calc)`); `grep
add_nums src/` returns nothing (rename complete). The skill did the refactor
correctly — only the harness mis-attributed a foreign state to it.

**Harness bug #3 found and fixed (free):** the capture is now scoped to the run
THIS fixture created — snapshot existing orchestrator dirs before the fixture's
`claude -p`, then pick the `state.json` in a dir that appeared after (fall back to
mtime > `start_ts`, then to empty). A degenerate fixture run now scores honestly
(missing state) instead of inheriting another fixture's results. Verified with a
synthetic new-dir + degenerate-dir simulation; `bash -n` clean. Like the first two,
this fix does NOT retroactively change the recorded 0.0/0.9 — it makes the next run
attribute state correctly.

**Disposition:** skill correctness is established for BOTH fixtures — 04=0.9 by the
judge, 02 by direct inspection of its genuine run. The recorded 02=0.0 is a harness
capture artifact (foreign-state attribution), now fixed. No skill defect surfaced by
either re-run; every failing/low number traced to a harness measurement bug.

---

## On close-out

All work complete and green: D001/D002 helper-wiring, D004 plan2_state retirement,
D005 split + cross-cutting refs, version bump, contract enforcement, and the
eval-surfaced `state_set.py` list-collapse fix (+ regression tests). The paid eval
earned its keep across three findings — it caught a real data-loss bug in this
release's own D001 helper (now fixed, confirmed gone) AND exposed three
long-standing eval-harness measurement bugs (multi-plan `.tasks` capture,
post-v2.18 worktree path, and unscoped global-newest `state.json` capture), all now
fixed so future baselines are trustworthy. Skill correctness is established for both
eval fixtures: 04=0.9 by the judge, 02 by direct inspection of its genuine run
(correct three-file rename, 3 clean commits). Every failing/low recorded number
(02=0.0, 04 earlier 0.5) traced to a harness measurement artifact, never a skill
defect. Recorded v2.21.0 baseline is a harness floor, not a skill ceiling. Free
checks all green (`check_skill_contract`, `check_doc_freshness`, 60 script tests;
run.sh `bash -n` clean; harness fixes verified via synthetic state). Ship-ready.
