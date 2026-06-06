# JOURNAL — Instrumentation integrity (v2.28)

Chronological log. Update **as you go**, not at the end.

---

## 2026-06-07

### Three post-v2.27 runs reviewed (retrospective → fix)

Reviewed the three most recent `kws-claude-multi-agent-executor` runs, all
`interactive_attached` and **all started after v2.27 shipped** (commit `13461bb`,
2026-06-06 09:15 UTC):

- `session-package-decomposition-…205440` (run 3, 16 tasks COMPLETE) — `status:null`,
  `current_task=16` still set: it hit the v2.27 blocking cost FAIL, did **not** waive,
  and simply **wedged** — never finalized. `task_1..5` carried `timing.started` nine
  hours *after* `timing.completed` (KST literal + bogus `Z`). `finalize_run.py --check`
  today → `passed:false` on `cost_dispatches_zero` (unfixable).
- `readmates-resilience-…214931` (run 2, 2-plan chain, 7+ COMPLETE) — `status:null`,
  set `cost_tracking_waived=true` reflexively; 5 tasks `timing.started:null`. `--check`
  → `passed:true` (5× timing WARN under the waive).
- `target-type-polymorphism-…235331` (run 1, 7 COMPLETE) — `status:COMPLETE`, waived
  cost; keyed tasks `"1".."6"`+`"riskclose"`; `quality_trend:[]` despite 7 reviewed
  tasks. `--check` → `passed:true` (cost+timing waived).

All three left `agentlens_orchestration_run:null`. Common shape: a value that must be
recorded lives as prose the attached orchestrator performs by hand, and under context
pressure it is skipped or improvised — the v2.16/v2.26/v2.27 lesson, again. v2.27
attacked it at the finalize boundary only and added a waive; that bred a reflexive
waive (runs 1 & 2) or a wedge (run 3), never cost data.

### Design approved — the five gaps, three ADRs

Two root causes the boundary-only fix could not reach: (1) mandating the impossible
(cost on the Agent-tool path, which returns no `usage`) breeds reflexive waiving;
(2) detection that keys on a prose-set "done" signal cannot detect that signal's
absence (the run-3 wedge). Design landed as five deliverables under three ADRs:

- **D001** — honest cost auto-waive on the all-agent attached path (Phase 0 Step 7
  sets `cost_tracking_waived`/`cost_tracking_waive_reason`); remove the false
  "subscription dispatches still report usage" prose.
- **D002** — Stop-gate all-terminal trigger: a third `elif [ "${TOTAL:-0}" -gt 0 ]`
  DONE=1 branch so every declared task terminal forces finalization even when Phase 2
  never ran.
- **D003** — value-sanity FAIL + coverage WARNs + task-key WARN: un-waivable
  `timing_inverted` FAIL (`_parse_iso` in `finalize_run.py`); `quality_trend_sparse`
  + `agentlens_run_absent` WARNs; `quality_trend` moved to `phase_boundary.py`
  task-complete (single writer); `task_key_noncanonical` WARN (`TASK_KEY_RE` in
  `validate_state_schema.py`).

Spec + plan written under the superpowers convention
(`docs/superpowers/specs/2026-06-07-…-design.md`,
`docs/superpowers/plans/2026-06-07-….md`); this experiment folder is the field-evidence
record pointing at them.

### Execution (8-task plan)

- **Task 0** — captured the three regression fixtures from the real `state.json`
  files so the new severities can be replayed before/after.
- **Task 1 (D001)** — Phase 0 Step 7 now auto-sets `cost_tracking_waived=true` +
  `cost_tracking_waive_reason="agent-dispatch-no-usage"` when every gate is `"agent"`
  and mode is `interactive_attached`; `agent-dispatch.md` / `phase-1-task-cycle.md` /
  `state-schema.md` corrected; both fields preserved across resume / plan_chain swap /
  Resume Chain handoff.
- **Task 2 (D002)** — `finalization-stop-gate.sh.template` gained the all-terminal
  DONE=1 branch.
- **Task 3 (D003)** — `timing_inverted` un-waivable blocking FAIL + `_parse_iso` in
  `finalize_run.py`.
- **Task 4 (D003)** — `quality_trend` write moved into `phase_boundary.py`
  task-complete (single writer); `quality_trend_sparse` + `agentlens_run_absent`
  coverage WARNs added to `finalize_run.py`.
- **Task 5 (D003)** — `TASK_KEY_RE` + `task_key_noncanonical` WARN in
  `validate_state_schema.py`.
- **Task 6 (this closeout)** — added the `v228_*` checks to
  `evals/check_skill_contract.py` (helper-token presence per file, Stop-gate
  all-terminal branch, `cost_tracking_waive_reason` wired in the corpus, the false
  usage claim gone); bumped SKILL.md to `2.28.0` with +5 Guardrails rows; synced
  HISTORY / ARCHITECTURE / decision-log / experiments-index; wrote this JOURNAL +
  `findings/F01-close-out.md`; ran the doc-freshness gate.
- **Task 7** — regression replay of the three fixtures + Stop-gate integration is the
  remaining real proof (separate task).

Contract check after Task 6: `passed: true` with all six `v228_*` checks true. Suite
unchanged at 219 passed / 0 failed (Task 6 changed no script behavior — only the
contract checker, which is itself a test, and docs).
