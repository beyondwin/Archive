# v2.8 — Learning Log

**Status**: SHIPPED on branch (full-fixture smoke deferred) — see [F001](./findings/F001-smoke.md)
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
| T0 — Experiment scaffold + design ADR | ✓ done | this directory + D001 |
| T1 — Spec doc (Archive-level) | ✓ done | `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-learning-log-design.md` |
| T2 — Plan doc (Archive-level) | ✓ done | `docs/superpowers/plans/2026-05-13-kws-claude-multi-agent-executor-learning-log.md` |
| T3 — Advisor review on design | ✓ done | 4 gaps patched into D001 / spec / plan |
| T4 — Helper script + failing eval (TDD) | ✓ done | 16/16 checks pass; commits `d9f4f8a`, `6cfa8a2` |
| T5 — Runtime contract docs | ✓ done | learning-log.md + contract eval; commits `01d734c`, `de0f573` |
| T6 — SKILL.md + sub-agent prompts + escalation-playbook | ✓ done | Review-side Skill calls added; commit `e54a97a` |
| T7 — Release metadata + ARCHITECTURE/HISTORY sync | ✓ done | §14 added; v2.8.0; commit `08c7d19` |
| T8 — Smoke run + close-out finding | ✓ done (shell-level); full-fixture DEFERRED | [F001](./findings/F001-smoke.md) |

## Decisions index

- D001 — Initial design decisions (per-run shard layout, run_id format, helper subcommands, scope) — [link](./decisions/D001-initial-design.md)

## Findings index

- F001 — Shell-level integration smoke (PASS; full-fixture DEFERRED) — [link](./findings/F001-smoke.md)
