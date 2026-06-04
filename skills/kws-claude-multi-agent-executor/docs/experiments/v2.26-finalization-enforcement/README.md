# Finalization + schema enforcement (v2.26)

**Status**: In progress — 2026-06-04
**Branch**: `main` (in-repo skill change)
**Production baseline**: v2.21.0 (SKILL.md frontmatter at experiment start; experiment labels v2.22–v2.25 shipped without a frontmatter bump)

## Goal

Two real 2026-06-04 runs (`source-matching-refinement-20260604-210431`,
`readmates-member-reading-experience-20260604-210358`), both `interactive_attached`
mode, completed every task functionally but left `state.json` inconsistent: null
`completed_at` under a top-level `status: COMPLETE`, a task stuck at
`verifier: PENDING_BATCH`, `cost_ledger.totals.dispatches == 0`, and (readmates) a
fully non-canonical schema (empty `tasks{}`, data improvised into `task_summaries{}`,
`execution_order` instead of `execution_plan`, a `"verify"` risk value). The helper
tooling the missing fields depend on already exists; the gap is **enforcement** —
attached mode has no forcing function, so prose-mandated Phase 2 finalization gets
skipped under context pressure.

Success: the two observed bad states are caught mechanically; a run can no longer be
declared COMPLETE with an unfinalized or non-canonical `state.json`.

## Hypothesis

Attached-mode runs skip Phase 2 finalization and write non-canonical state because
nothing forces the in-session orchestrator to reach the finalization step. Two
standalone validators wired as Phase 2 gates — plus a Stop-hook forcing function that
fires even when Phase 2 is never entered — convert silent divergence into a hard,
self-correcting halt.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| validate_state_schema.py + tests | done | canonical-shape gate (check-only) |
| finalize_run.py + tests | done | finalization gate, safe `--fix` (completed_at only) |
| Phase 2 wiring + Guardrail | done | Step 1.5 schema gate, Step 2 finalize gate |
| check_skill_contract.py extension | done | v226 helper-exists + wiring checks |
| Docs + version bump | in progress | this record, ARCHITECTURE/HISTORY, 2.26.0 |
| Stop-hook forcing function | in progress | resolves the two documented remaining risks |

## Decisions index

- D001 — Stop-hook forcing function reinstated to resolve remaining risks — [link](./decisions/D001-stop-hook-forcing-function.md)

## Findings index

- F01 — Close-out: what shipped + remaining-risk resolution — [link](./findings/F01-close-out.md)
