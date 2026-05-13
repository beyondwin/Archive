# v2.7 Quality Mode Experiment

**Status**: In progress (started 2026-05-13)
**Branch**: `feature/v2.7-quality-mode-experiment`
**Production baseline**: v2.6.0 (untouched on `main`)

## Goal

Determine whether adding a "quality mode" to `kws-claude-multi-agent-executor`
measurably improves output quality on fixtures where v2.6.0 ships incomplete
work. Quality mode candidates:

- **quality_alpha**: LOW → MID floor (no batch verifier, no TDD skip); HIGH tasks
  get best-of-3 candidates judged by Opus
- **quality_plus**: same as alpha, plus MID tasks also get best-of-3

## Hypothesis

Best-of-N + Opus judge reduces correctness misses on tasks where multiple
reasonable implementations are possible (subtle input validation, design
choices, error-handling policy). Cost: 2–6× tokens vs balanced.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work, problems, reviews
- [decisions/](./decisions/) — one short ADR per major decision
- [findings/](./findings/) — run artifacts and analysis (populated as runs complete)

## Current phase: **Pilot**

| Task | Status | Notes |
|------|--------|-------|
| Experiment branch | ✓ | commit d5aa5eb |
| Fixture 08 design | ✓ | 20 deterministic rubric checks |
| Judge calibration | ✓ | Pass via deterministic rubric runner (Δ=0.20) |
| Rubric runner integrated into harness | ⏳ | next |
| Fixture 08 ceiling check (balanced × 1) | ⏳ | |
| quality_plus mode implementation | ⏳ | |
| Pilot (6 runs: balanced × 3 + quality_plus × 3) | ⏳ | |
| Analysis + decision | ⏳ | |

## Decisions index

- [D001 — MID floor (not HIGH floor)](./decisions/D001-floor-level.md)
- [D002 — Use Opus judge, not Sonnet](./decisions/D002-judge-model.md)
- [D003 — Deterministic rubric runner replaces LLM correctness estimation](./decisions/D003-rubric-runner.md)
- [D004 — Pilot scope: balanced vs quality_plus only (skip alpha until HIGH fixture)](./decisions/D004-pilot-scope.md)
- [D005 — Experimental branch, no production SKILL.md edits until pilot validates](./decisions/D005-experimental-branch.md)
- [D006 — Pilot-first instead of full 15-run experiment](./decisions/D006-pilot-first.md)
- [D007 — Fixture 08 redesign: realistic underspec after ceiling check showed pass_rate 1.0](./decisions/D007-fixture-realistic-spec.md)
