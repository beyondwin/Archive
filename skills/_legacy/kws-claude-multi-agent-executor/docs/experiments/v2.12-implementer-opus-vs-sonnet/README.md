# v2.12 — Implementer Opus vs Sonnet quality comparison

**Status**: In progress
**Branch**: `experiment/v2.12-implementer-opus-vs-sonnet`
**Production baseline**: v2.10.2

## Goal

Compare end-to-end task quality (spec adherence, code quality, retries, escalations) when the Implementer sub-agent runs on **Opus 4.7** vs **Sonnet 4.6**, holding everything else constant (Orchestrator=Opus, Reviewer/Verifier=Sonnet, same plan/spec/baseline).

The motivating question: is the ~5× cost of Opus per Implementer dispatch justified by measurable quality improvement, and if so, on which task complexities?

## Hypothesis

- **SMALL/LOW tasks**: no meaningful quality gap; Opus is wasted spend.
- **MEDIUM tasks**: small reduction in `review_retries`, marginal `quality_score` improvement.
- **LARGE/HIGH tasks**: noticeable drop in `review_retries`/`escalation_count`; `quality_score` rises by ≥ 0.05.

Cost-per-quality-point is expected to favor Sonnet on SMALL and either favor Opus or be equivocal on LARGE.

## Design

| Axis | Value |
|------|-------|
| Orchestrator | Opus 4.7 (fixed) |
| Implementer | **variable** — `sonnet` (default) vs `opus` |
| Reviewer | Sonnet 4.6 (fixed — judge consistency) |
| Verifier | Sonnet 4.6 (fixed) |
| Plan | `bench/plan.md` (6 tasks: 2 SMALL, 2 MEDIUM, 2 LARGE) |
| Spec | `bench/spec.md` |
| Runs per arm | 3 (total 6 runs) |
| Metrics | `spec_score`, `quality_score`, `review_tier`, `review_retries`, `verifier_retries`, `escalations`, `timing.completed - timing.started` |

## Skill changes shipped on this branch

- `SKILL.md`: new optional arg `implementer_model=opus|sonnet` (default `sonnet`)
- `SKILL.md`: state.json now records `implementer_model: {used, default}` at Phase 0 Step 7
- `SKILL.md` Phase 1 Step 1: dispatch passes `model` parameter when override set
- `references/implementer-prompt.md`: `subagent.model` learning-log field becomes a placeholder

These changes are **additive and backward-compatible** — runs without the arg behave exactly as v2.10.2.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis
- [bench/plan.md](./bench/plan.md) — benchmark plan
- [bench/spec.md](./bench/spec.md) — benchmark spec
- [bench/aggregate.py](./bench/aggregate.py) — multi-run aggregation script
- [RUN.md](./RUN.md) — step-by-step procedure to reproduce the comparison

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| Skill patch — `implementer_model` arg + state recording | done | additive; backward compatible |
| Benchmark plan + spec | done | 2×SMALL / 2×MEDIUM / 2×LARGE |
| Aggregation script | done | groups runs by `implementer_model.used`, breaks down by `task_complexity` |
| Run procedure doc | done | see [RUN.md](./RUN.md) |
| Execute 6 runs (3×Sonnet, 3×Opus) | pending — user-driven | needs interactive supervision or budget for headless `claude -p` |
| Findings F001 | pending | written after the 6 runs land |

## Decisions index

- D001 — Hold Reviewer/Verifier on Sonnet (judge consistency) — [link](./decisions/D001-hold-reviewer-on-sonnet.md)
- D002 — Record both used and default model — [link](./decisions/D002-record-used-and-default.md)

## Findings index

(Populated after data collection.)

- F001 — Quality vs cost by complexity bucket — pending
