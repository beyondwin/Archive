# JOURNAL — v2.29 quality-uplift

Chronological log. Update **as you go**, not at the end.

---

## 2026-06-07

### Setup — branch + experiment record

Invoked via kws-claude-multi-agent-executor with the two Korean design docs.
Determined the docs are design catalogs (I1–I12), not `### Task N:` plans, and
the plan profile (heavy shared-file contention on phase-1-task-cycle.md /
phase_boundary.py / build_final_report.py, deep coupling I2+I3→I4→I7, explicit
"no added parallelism" mandate §3.1) matches the skill's own single-session
recommendation. User chose **single-session direct (Opus)** execution.

Plan: implement P0→P1→P2 with TDD on new/changed scripts, reference-doc precision
edits for prose items, schema+contract sync, per-bundle commits (v2.29.0/.1/.2),
then resolve remaining risks and merge to main. All changes additive —
`schema_version` stays "2" (plan §0.2).

### Constraints carried in

- AGENTS.md: experiment record required (this dir) for multi-file behavioral change.
- Do not regress closed invariants (plan §2.1): timing_inverted blocking FAIL,
  cost_tracking_waived honesty on all-agent path, Stop-hook finalization,
  materialize_worktree_hooks deep-merge, single quality_trend writer,
  last_completed_task authority, detach+agent reconcile.
- events.jsonl is an orchestrator single-writer local tee, NOT a Lens channel
  (AGENTS.md / CLAUDE.md compliance) — distinct from the v2.17-removed parallel sink.

### P0 (v2.29.0) implemented — I1/I2/I3

- **I1** (doc): phase-1-task-cycle.md Step 2 review-retry + Step 3 verifier-retry
  `>3` branches changed from "halt, manual intervention" to SKIP + verification_gaps
  + blocker emit + SKIPPED-propagation + continue. Verifier branch keeps the
  `git reset --hard <pre_task_sha>` before SKIP (clean tree). SKILL.md guardrail
  rows updated.
- **I2** (code+doc): `phase_boundary._tee_event` appends every boundary emit to
  `<orch_dir>/events.jsonl` (single writer, best-effort, AgentLens-independent).
  Added generic `emit` subcommand for free-form types (blocker). Wired into
  task-complete + phase-emit. Docs: SKILL.md guardrail + agentlens-emit-sites.md.
- **I3** (code+doc): `phase_boundary.cmd_retry_trace` + `retry-trace` subcommand —
  append-only `<active>.tasks.task_N.retry_trace[]` of {attempt, kind, fault,
  recurring_keys, tier, ts}. task-complete preserves an existing retry_trace
  (audit log, not transient). Docs: phase-1-task-cycle.md Step 2/3 retry branches.

Tests: scripts/test_phase_boundary.py +14 cases (32 total). Full scripts suite
242 passed. check_skill_contract + check_doc_freshness green. Version field left
at 2.28.0 during dev; bumped to 2.29.0 at the docs-sync commit.

### P1 (v2.29.1) implemented — I4/I5/I6/I7

- **I5** (code+test+doc): `build_context_slice.py` ports the ~40-line
  `{context_slice}` derivation out of phase-1-task-cycle.md Step 1. deps/files
  passed as args (orchestrator already holds them); task_summaries / shared_files
  / global_constraints read from the active tree. 10 tests. Step 1 doc replaced
  the pseudocode block with a helper call (line-count down).
- **I6** (doc): "re-read full spec after edit" → re-read only changed
  `spec_manifest.sections[<edited_sids>]` (+ dependent), regen manifest on
  structural change. SKILL.md guardrail + phase-1-task-cycle.md spec-edit branch
  + phase-1-escalation.md rule.
- **I4** (code+test+doc): `build_final_report.py` → Execution Summary markdown
  (layout-locked by snapshot test, multi-plan aware) + machine-readable
  `run_report.json` (schema run_report/1, aggregate_runs.py input). phase-2
  Step 2 replaced manual field aggregation with the helper call. 12 tests.
- **I7** (code+test+doc): failure_summary roll-up computed inside
  build_final_report.py (by_class / auto_resolved / escalations / skipped_tasks);
  finalize_run.py gains read-only `failure_summary_mismatch` WARN comparing
  run_report.json against live state gaps (never blocks). +4 finalize tests.

Tests: full scripts suite 268 passed. Contract + freshness green. Decision: the
"snapshot == hand-written prose report" acceptance is interpreted as
structure+derived-field equality (free-form sections — Changes/Verification/Docs/
Remaining Risks — are derived from state signals, not byte-equal to prose). ADR
candidate noted for the docs-sync commit.
