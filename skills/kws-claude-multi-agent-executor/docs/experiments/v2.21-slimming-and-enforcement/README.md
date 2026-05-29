# v2.21 — SKILL.md slimming + runtime enforcement hardening

**Status**: In progress (opened 2026-05-29)
**Branch**: in-place on `main` (Archive monorepo; sibling skill has unrelated WIP — no branch switch)
**Production baseline**: v2.20.0

## Goal

Attack two coupled problems at once:

1. **SKILL.md is too large.** At v2.20 it is 1872 lines / ~72k tokens, of which
   F001 (v2.19) measured only ~30–35% as actively referenced per task cycle. The
   rest sits resident in the orchestrator prefix for the whole run — pure cost,
   and (more importantly) a readability load that *causes* problem 2.

2. **Prose-only mandatory steps get silently skipped at runtime.** The SKILL.md
   itself documents a recurring regression: `phase_0_started` ("most reproducible
   adherence regression"), `accumulate_cost` ("silently skipped in every observed
   run, dispatches=0"), `timing.started/completed` ("null across all v2.11–v2.15
   runs"). Every past fix was *louder prose + a helper script*. Louder prose
   inside a 72k-token file is a losing strategy. The proven fix is moving
   enforcement into the runtime (P1/v2.5 debug-artifact hook: "discipline lives in
   the runtime, not in the loop").

This experiment slims SKILL.md to an ~8–10k entrypoint (per v2.19 D001 split) AND,
during the same extraction, replaces the scattered mandatory-but-skipped steps with
single enforced helper calls / hooks.

## Hypothesis

- H1 (cost): entrypoint + on-demand phase references cut resident SKILL.md tokens
  ~65–75% per the F001 cost model, with one extra Read per phase entry that
  amortizes via cache_read.
- H2 (adherence): consolidating emit/timing/cost into one `phase-boundary` helper
  call per boundary (and a `state_set.py` for all active-tree writes) drives the
  observed regressions to zero, because there is one call to skip instead of six
  prose paragraphs — and that call can be eval-checked deterministically.
- H3 (maintenance): retiring the v2.12 `plan2_state` dual-path via a resume
  migration shim removes a whole duplicated code surface with no behavior change
  for live runs.

Failure looks like: split introduces a behavioral regression the evals catch, or
the helper consolidation loses a guard the prose had.

## Scope (the 6 approved items)

| # | Item | Theme | Risk |
|---|------|-------|------|
| 1 | Finish SKILL.md split (v2.19 D001) | slimming | high (eval regression) |
| 2 | Phase-boundary enforcement helper | adherence | medium |
| 3 | `state_set.py` (active-tree + atomic R-M-W) | adherence | low |
| 4 | Retire v2.12 `plan2_state` dual-path | cleanup | medium |
| 5 | AgentLens reachability health probe | observability | low |
| 6 | headless-default vs cache-warmth decision | workflow | low (decision) |

## Execution order (safety-first)

Additive + testable first, risky split last:

1. Scaffold + ADRs (this record)
2. `state_set.py` (#3) — additive, unit-tested, no SKILL.md change
3. phase-boundary helper (#2) — additive, unit-tested
4. AgentLens health probe (#5) — additive
5. D003 headless decision (#6) — ADR + user confirm
6. SKILL.md split (#1) — wire helpers in during extraction; legacy retirement (#4)
   lands inside the multi-plan-chain cross-cutting file
7. Doc sync + paid eval regression (checkpoint with user) + close-out

## Status / quick links

- [JOURNAL.md](./JOURNAL.md)
- [plan.md](./plan.md) — detailed split boundary + helper contracts
- [decisions/](./decisions/)
- [findings/](./findings/)

## Decisions index

- D001 — `state_set.py` contract — [link](./decisions/D001-state-set-helper.md)
- D002 — phase-boundary helper: script vs hook — [link](./decisions/D002-phase-boundary-helper.md)
- D003 — headless-default vs cache-warmth — [link](./decisions/D003-headless-default-vs-cache.md)
- D004 — legacy plan2_state retirement via resume shim — [link](./decisions/D004-legacy-plan2state-retirement.md)
- D005 — split boundary (reaffirm/extend v2.19 D001) — [link](./decisions/D005-split-boundary.md)

## Findings index

- (pending — F001 will hold token + adherence measurements post-split)
