# v2.8 — Learning Log

**Status**: In progress
**Branch**: `codex/executor-learning-log` (shared with Codex sibling work; Claude files isolated by path)
**Production baseline**: v2.6.0 (untouched on `main`)
**Sibling work**: `kws-codex-plan-executor` learning log (Codex side, parallel design)

## Goal

Add a user-local JSONL learning log to `kws-claude-multi-agent-executor` so the
orchestrator and sub-agents can record notable-boundary events (blockers,
verification failures, reviewer WARN/FAIL, escalations, user corrections,
successful workarounds, completion learnings) across repositories. The log is
the long-term institutional memory for *improving the skill itself* — distinct
from `state.json`, which is the per-run resume source of truth.

Same 4-axis contract as the Codex sibling — `execution-only`, `notable-boundaries`,
`redacted-context`, `schema + helper script` — adapted for Claude Code (native
hooks, sub-agent dispatch, worktree isolation, `docs/experiments/` integration).

## Hypothesis

Per-run sharded layout (`runs/<date>/<run_id>/{meta.json, events.jsonl}`)
combined with a deterministic helper script gives us:
- zero concurrent-write contention even when multiple executors run in the same
  repo at once
- a 1:1 link between learning events and `~/.claude/projects/<...>/<session_id>.jsonl`
  transcripts (via `session_id` in `meta.json`)
- forward-compat globbing for any future aggregator

Plus, threading `Skill("superpowers:requesting-code-review" | "verification-before-completion" | "writing-plans")`
into Reviewer / Verifier / Plan Reviewer prompts closes the asymmetry where
only Implementer currently invokes superpowers.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T0 — Experiment scaffold + design ADR | in progress | this directory + D001 |
| T1 — Spec doc (Archive-level) | pending | `docs/superpowers/specs/...` |
| T2 — Plan doc (Archive-level) | pending | `docs/superpowers/plans/...` |
| T3 — Advisor review on design | pending | before substantive code |
| T4 — Helper script + failing eval (TDD) | pending | after plan approved |
| T5 — Runtime contract docs | pending | references + SKILL.md |
| T6 — Reviewer/Verifier/Plan Reviewer Skill invocations | pending | A from §5 of design chat |
| T7 — Release metadata + ARCHITECTURE/HISTORY sync | pending | per AGENTS.md |
| T8 — Smoke run + close-out finding | pending | verify event lands |

## Decisions index

- D001 — Initial design decisions (per-run shard layout, run_id format, helper subcommands, scope) — [link](./decisions/D001-initial-design.md)

## Findings index

(none yet)
