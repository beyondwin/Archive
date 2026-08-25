# v2.30 — Failure-taxonomy coverage & evidence-gating hardening

**Status**: CLOSED — P0 SHIPPED (2026-06-08); behavioral round (J7/J8) reopen-on-demand
**Branch**: `v2.29-quality-uplift` (P0 committed here; main fast-forwarded to include it)
**Production baseline**: v2.29.0 — `SKILL.md metadata.version` unchanged (P0 is eval-layer + docs, orthogonal to runtime; see F02)

## Goal

Widen the eval "measurement net" by mapping the fixture suite onto the MAST
multi-agent failure taxonomy, then add fixtures for the highest-value *uncovered*
classes (reviewer rubber-stamping, error propagation) and harden judge bias.
P0 (J1–J4) ships orthogonally to SKILL.md (AGENTS.md: "eval improvements ship
orthogonally") so the regression risk is near zero. P1/P2 (J5–J9) are recorded at
design level this round; only their start conditions are committed.

## Hypothesis

The skill already implements most industry/official multi-agent best practices
(plan §2.1). The remaining value is **measurement**: we have never measured
whether the pipeline catches a green-build-but-spec-violating change (FM-3.3) or a
latent defect propagating across a task chain (FM-2.3). Deterministic-rubric-first
probe fixtures can measure both with near-zero judge variance, and they gate the
P2 behavior changes (J7/J8) before those touch orchestrator prompts.

## Scope this round (user decision 2026-06-08)

- **P0 (J1–J4): full implementation.** MAST coverage doc, fixtures 09 + 10,
  judge bias guards.
- **P1/P2 (J5–J9): design records only.** ADRs + start conditions; no J5/J7/J8
  code, no J6/J9 build.
- **Execution**: single-session, in-session (no multi-agent fan-out — plan §3.1
  "팬아웃 확대 금지" + the user's manual-dispatch preference).

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log
- [decisions/](./decisions/) — ADRs
- [findings/](./findings/) — data and analysis
- Authoritative coverage map: [../../eval-coverage-mast.md](../../eval-coverage-mast.md)
- Source design docs: [plan](../../improvements/품질개선-v2.30-플랜-ko.md) ·
  [spec](../../improvements/품질개선-v2.30-구현-ko.md)

## Phase status

| Item | Axis | Status | Notes |
|------|------|--------|-------|
| J1 MAST matrix doc + fixture annotations | D | **implemented** | `docs/eval-coverage-mast.md`; 8 fixtures annotated; README updated |
| J2 fixture 09 rubber-stamp probe | D | **implemented** | adapted to real rubric.py contract; probe validity proven (F01) |
| J3 fixture 10 error-propagation probe | D | **implemented** | adapted; probe validity proven (F01) |
| J4 judge.md bias guards | D | **implemented** | subjective axis only; calibration regression note added |
| J5 analyze_shelf_triggers.py | E | **design-only** | D004 — start condition recorded |
| J6 Haiku LOW-tier A/B | E | **deferred** | D005 — conditional on J5=MET |
| J7 Reflexion retry reflection | F | **design-only** | D006 — fixture-eval gated |
| J8 AC anti-rubber-stamp cross-check | F | **design-only** | D007 — fixture-eval gated, measured by fixture 09 |
| J9 plan-DAG re-plan | F | **deferred** | D008 — record-only |
| Paid eval (1-rep pilot → n=4) + full calibration | — | **re-scoped** | NOT a P0 gate (P0 = no runtime change). Gate for the J7/J8 behavioral round; manual dispatch. F02 |
| SKILL.md version bump | — | **not done (by decision)** | eval-layer orthogonal → `metadata.version` stays 2.29.0. F02 |

## Decisions index

- D001 — MAST coverage matrix as authoritative eval doc (J1) — [link](./decisions/D001-mast-coverage-matrix.md)
- D002 — Probe-fixture design: harness-contract adaptation + detect-then-fix (J2/J3) — [link](./decisions/D002-probe-fixture-design.md)
- D003 — judge bias guards scoped to subjective axis (J4) — [link](./decisions/D003-judge-bias-guards.md)
- D004 — J5 shelf-trigger evaluator design + start condition (P1) — [link](./decisions/D004-shelf-trigger-evaluator.md)
- D005 — J6 Haiku LOW-tier deferred, conditional on J5 (P1) — [link](./decisions/D005-haiku-low-tier-deferred.md)
- D006 — J7 Reflexion retry reflection design, fixture-eval gated (P2) — [link](./decisions/D006-reflexion-retry-reflection.md)
- D007 — J8 AC anti-rubber-stamp cross-check design, fixture-eval gated (P2) — [link](./decisions/D007-ac-cross-check.md)
- D008 — J9 plan-DAG re-plan deferred, record-only (P2) — [link](./decisions/D008-replan-deferred.md)

## Findings index

- F01 — Probe validity (deterministic, no LLM): fixtures 09/10 discriminate good vs broken — [link](./findings/F01-probe-validity.md)
- F02 — Close-out: ship P0 eval-layer, no version bump, paid eval re-scoped to the J7/J8 round — [link](./findings/F02-close-out.md)
