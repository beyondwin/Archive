# v2.7 Quality Mode Experiment

**Status**: **CLOSED** (negative result on quality_plus; positive on infrastructure) — 2026-05-13
**Branch**: `feature/v2.7-quality-mode-experiment`
**Production baseline**: v2.6.0 (untouched on `main`)

## Outcome

3 reps of balanced v2.6.0 on fixture 08 produced identical 0.95 rubric
pass_rate (0% variance, same single miss every time). quality_plus's
maximum gain on this fixture is +0.05 and best-of-N is unlikely to
discriminate when 3/3 reps reproduce the exact same code.

See [F002-close-out.md](./findings/F002-close-out.md) for the full
recommendation and what infrastructure to ship.

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

## Final phase status

| Task | Status | Notes |
|------|--------|-------|
| Experiment branch | ✓ | commit d5aa5eb |
| Fixture 08 design + redesign | ✓ | D007: realistic underspec, 20 rubric checks |
| Judge calibration | ✓ | Failed LLM-alone; replaced with deterministic rubric runner |
| Rubric runner integrated into harness | ✓ | commit cc2cf6e — ship to main |
| Fixture 08 ceiling check (balanced × 3) | ✓ | All 3 reps: 0.95, same single miss |
| quality_plus mode implementation | **SKIPPED** | Ceiling makes lift marginal (+0.05 max) |
| Pilot (6 runs) | **SKIPPED** | Lift undetectable at zero baseline variance |
| Close-out + findings | ✓ | F001 (data), F002 (decision) |

## Decisions index

- [D001 — MID floor (not HIGH floor)](./decisions/D001-floor-level.md)
- [D002 — Use Opus judge, not Sonnet](./decisions/D002-judge-model.md)
- [D003 — Deterministic rubric runner replaces LLM correctness estimation](./decisions/D003-rubric-runner.md)
- [D004 — Pilot scope: balanced vs quality_plus only (skip alpha until HIGH fixture)](./decisions/D004-pilot-scope.md)
- [D005 — Experimental branch, no production SKILL.md edits until pilot validates](./decisions/D005-experimental-branch.md)
- [D006 — Pilot-first instead of full 15-run experiment](./decisions/D006-pilot-first.md)
- [D007 — Fixture 08 redesign: realistic underspec after ceiling check showed pass_rate 1.0](./decisions/D007-fixture-realistic-spec.md)
- [D008 — quality_plus mode SKILL.md change design (best-of-N sub-flow spec)](./decisions/D008-quality-plus-skill-changes.md)
