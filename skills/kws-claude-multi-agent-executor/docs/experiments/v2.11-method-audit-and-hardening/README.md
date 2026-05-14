# v2.11 — Method Audit + Codex-Inspired Hardening

**Status**: In progress
**Branch**: `v2.11-method-audit-and-hardening-20260514-115803`
**Production baseline**: v2.10.2

## Goal

Close MAE's gap between *required* sub-agent disciplines (TDD, review, verification) and actual *validation* of those disciplines, plus four smaller hardening items from `kws-codex-plan-executor` commit `1d10f13`.

## Hypothesis

Adding structured `METHOD_AUDIT:` evidence to sub-agent output + an orchestrator-side validator will catch the case where a task ships `COMPLETE` without TDD evidence, without adding per-task overhead beyond ~50 tokens of structured output and ~5 grep operations.

## Status / quick links

- [PLAN.md](./PLAN.md) — detailed implementation plan
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) — concrete code/edit guidance per task
- [JOURNAL.md](./JOURNAL.md) — chronological log

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| Task 1 (Fixtures) | COMPLETE | |
| Task 2 (Outcome resolver) | COMPLETE | |
| Task 3 (Sub-agent prompts) | COMPLETE | |
| Task 4 (Hook) | COMPLETE | |
| Task 5 (Validator + gate) | COMPLETE | |
| Task 6 (Populator) | COMPLETE | |
| Task 7 (ENV_BLOCKER categories) | COMPLETE | |
| Task 8 (Preflight) | COMPLETE | |
| Task 9 (Resource key) | COMPLETE | |
| Task 10 (Docs + verify) | In progress | |

## Decisions index

(One line per ADR. Add as you make decisions.)

## Findings index

(One line per finding doc.)
