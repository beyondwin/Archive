# v2.13 — Natural-language args + multi-plan auto-chain

**Status**: In progress
**Branch**: `experiment/v2.13-natural-multi-plan`
**Production baseline**: v2.12 (just merged to main)

## Goal

Two invocation-UX improvements that combine to make multi-plan, model-overridden runs much easier to kick off:

1. **Multi-plan auto-chain** — when the user passes `plan=A spec=A.spec plan2=B spec2=B.spec plan3=C spec3=C.spec` (or further N), the skill auto-chains them in numeric order. No `manifest=` arg required, no separate manifest file. v2.12's `plan2_state` (which only handled 2 plans) generalizes to a `plan_chain[]` array for N≥2 plans; the single-plan path stays exactly as v2.12.

2. **Natural-language argument keywords** — the user can write "오푸스로 순차적으로 진행해줘" (or "use Opus, sequential") in the args text, and the skill detects the keywords and applies them as if they were `implementer_model=opus parallel=off`. Explicit `key=value` always wins; NL only fills unset keys; conflicts halt with a batched question.

## Hypothesis

These are pure UX patches with no behavioral change to task execution. The 6-task v2.12 benchmark (`docs/experiments/v2.12-implementer-opus-vs-sonnet/bench/`) continues to work bit-for-bit when invoked the v2.12 way. Multi-plan chains add a re-baseline + risk/dep/complexity recompute per plan boundary (same as v2.12 plan2 swap — just generalized).

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log
- [decisions/](./decisions/) — ADRs
- [examples/](./examples/) — sample invocations + parsed echo outputs

## Decisions index

- D001 — NL lexicon scope (start small, additive only) — [link](./decisions/D001-nl-lexicon-scope.md)
- D002 — Single-plan keeps v2.12 schema; multi-plan introduces `plan_chain[]` — [link](./decisions/D002-plan-chain-schema.md)

## Findings index

(Populated after the design lands and a real multi-plan run is executed.)
