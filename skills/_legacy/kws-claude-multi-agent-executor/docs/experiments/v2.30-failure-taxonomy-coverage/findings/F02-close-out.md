# F02 — Close-out: ship P0 eval-layer, re-scope the paid eval

**Date**: 2026-06-08
**Status**: FINAL — close-out decision
**Decision**: **SHIP P0 (J1–J4)**. No SKILL.md version bump. P1/P2 (J5–J9) stay
design-records. Paid pipeline eval + full LLM calibration re-run are re-scoped to
the J7/J8 behavioral round, not a P0 gate.

## What shipped (P0, axis D — orthogonal to SKILL.md runtime)

- **J1** — `docs/eval-coverage-mast.md` (authoritative MAST 14-mode coverage map),
  `mast_coverage:` annotations on fixtures 01–08, `evals/README.md` fixture list
  corrected (01–10). See D001.
- **J2** — fixture `09-spec-intent-uncovered.yaml` (FM-3.3 rubber-stamp probe).
- **J3** — fixture `10-error-propagation.yaml` (FM-2.3 / FM-3.2 propagation probe).
- **J4** — `evals/judge.md` bias guards scoped to the subjective `code_quality`
  axis only; `evals/calibration/README.md` regression note. See D003.

All four are eval-layer + docs. None touches `SKILL.md`, the orchestrator phase
references, or any sub-agent prompt. Per AGENTS.md ("eval improvements ship
orthogonally") the runtime regression risk is structurally zero.

## Why no version bump (user decision 2026-06-08)

`SKILL.md metadata.version` tracks the **runtime contract**. P0 changes no runtime
behavior, so bumping it to 2.30.0 would falsely signal a contract change. The work
is recorded under HISTORY §3 (experiment index) + this close-out instead. The
`metadata.version` stays `2.29.0` and `schema_version` is untouched. The "v2.30.0
SHIP gate" (a paid eval) is retained as the gate for the *behavioral* round below,
where it actually applies.

## Risk register — final state

| Plan §5 risk | Resolution |
|--------------|------------|
| **Probe fixture is inert** (top risk) | **CLOSED** deterministically by F01: 09 good 1.0 vs broken 0.6 (Δ0.4); 10 good 1.0 vs broken 0.4 (Δ0.6). Raw `rubric.py` output committed. |
| Spec YAML diverges from harness contract | **CLOSED**: read `rubric.py`/`run.sh` first, adapted to the real `{check,desc}` contract (D002); fixtures enumerate + parse under `run.sh`. |
| Judge bias inflates the subjective axis | **MITIGATED**: bias-guard section added, scoped to `code_quality` only; deterministic axes left mechanical (D003). Full re-calibration is paid (below). |
| MAST coverage drifts as fixtures change | **MITIGATED**: `eval-coverage-mast.md` carries an update protocol + revisit triggers; `mast_coverage:` annotations are inert to the runtime (run.sh `_meta.json` whitelist excludes them; rubric.py never reads them). |

## Explicitly NOT done this session (and why it is not a P0 blocker)

- **Paid pipeline eval (1-rep pilot → n=4).** Measures whether the *pipeline*
  (Combined Reviewer Spec Walk / AC-shell Verifier) surfaces-and-fixes the planted
  defect before SHIP. P0 changes no pipeline behavior, so there is nothing new in
  the pipeline to certify — the new fixtures are *measurement instruments*, proven
  to discriminate by F01. A paid run would establish a **baseline** of how the
  current pipeline scores 09/10; that baseline is the gate for the **J7/J8**
  behavioral build (D006/D007), which *does* edit prompts. It is therefore carried
  forward to that round, not blocking this commit.
- **Full LLM judge calibration re-run** (`score(good) − score(broken) ≥ 0.2` across
  all axes). The deterministic component (`spec_compliance` from `error_cases`) is
  already in F01 at Δ0.4 / Δ0.6. The subjective-axis component needs model calls.
- Both are paid, multi-call operations. Per the single-session decision and the
  user's manual-dispatch preference (no auto fan-out), they are a deliberate manual
  step for the J7/J8 round — not auto-run here.

## P1/P2 carried forward (design-records only — no code)

J5 (D004, start condition recorded), J6 (D005, conditional on J5=MET), J7 (D006,
fixture-eval gated), J8 (D007, fixture-eval gated — measured by fixture 09), J9
(D008, record-only). Build trigger and gate are written in each ADR.

## Recommendation

**SHIP** the P0 eval-layer + docs + this experiment record. Land on main by
fast-forward (the branch also carries the v2.29.0 release). Keep this experiment
**CLOSED — P0 SHIPPED**; reopen for the behavioral round (J7/J8) when its paid
fixture-eval gate is run manually.

## Cost actuals

$0 — deterministic harness + docs only; no model calls this session.
