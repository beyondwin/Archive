# v2.23 — Implementer Adversarial Self-Check

**Status**: **CLOSED — SKIP** (measured negative; baseline defect no longer reproduces on current Sonnet) — 2026-06-02
**Branch**: none (intervention was working-tree-only; reverted to HEAD on close)
**Production baseline**: v2.22 (untouched on `main` — unchanged by this experiment)
**Outcome**: see [findings/F001-close-out-skip.md](./findings/F001-close-out-skip.md). Control ceilings at 100% (n=4 Sonnet) where v2.7 F002 measured ~25% — no headroom for the intervention. Same disposition as v2.7 best-of-N.
**Predecessor**: v2.9 Reviewer Spec Coverage Walk (shipped 2026-05-14) — this is the *Implementer-side mirror* of v2.9's reviewer sub-step B.

## Goal

Reduce the Implementer sub-agent's **first-pass** miss rate on `implementer_omitted`
adversarial-input faults by adding one step to `references/implementer-prompt.md`:
an **Adversarial Meta-Rule Self-Check** that — before reporting GREEN — enumerates
spec meta-rules ("strict validation", "reject anything else", "not exhaustive", …),
generates ≥3 adversarial inputs per meta-rule, and writes a failing test for each
as part of the TDD RED step.

Single change. Single prompt file. Existing fixture 08 as evidence. No new sub-agent
dispatch. One optional output line (`ADVERSARIAL_SELFCHECK:`) for adherence measurement.

## Why this and only this

Asymmetry in the current skill: the **Reviewer** has an adversarial mechanism
(v2.9 Spec Coverage Walk **sub-step B**, `references/reviewer-prompt.md`) that the
prompt itself calls "the critical mechanism." The **Implementer** has no symmetric
step — it is told "implement exactly what the task says" + run TDD, with nothing
directing adversarial enumeration of spec meta-rules before submitting.

Consequence: the defect v2.7 F002 measured (Sonnet's consistent
`parse_duration("30m20m")` miss — covered only by the meta-rule "strict validation
of the grammar") is **caught in review** (a reset + re-dispatch cycle) rather than
**prevented at creation**.

This is the only Implementer-prompt change that maps to a documented, quantified
KCMAE failure (v2.7 F002, ~75% first-pass miss on fixture 08 `30m20m`). It mirrors
the exact mechanism v2.9 already proved on the reviewer side.

## Hypothesis

If the Implementer prompt requires adversarial meta-rule enumeration *before GREEN*
(write a failing test for ≥3 adversarial inputs per spec meta-rule), then the
Implementer's **first-pass** rejection rate on `30m20m`-class inputs on fixture 08
rises from the ~25% baseline (v2.7 F002: 1/4 reps rejected it first-pass) to ≥75%,
and the **review-retry count** attributable to `implementer_omitted` adversarial
misses drops correspondingly.

## What this experiment can and cannot show (load-bearing)

**Cannot improve final quality on fixture 08.** v2.9's reviewer walk already drives
fixture 08's *final* rubric pass-rate to 1.0 (v2.9 F002: 4/4 reps at 1.0). The
Implementer self-check therefore cannot raise the *end-state* number — it is at
ceiling. Measuring final rubric pass-rate would show a null effect by construction.

**Can only show prevention.** The honest, measurable benefit is upstream:
1. First-pass (pre-review) rubric pass-rate ↑ on adversarial checks.
2. `review_retries` attributable to adversarial omission ↓.
3. Therefore wall-time / tokens ↓ (fewer reset + re-dispatch cycles).

**Real risk of a v2.7-style negative result.** If the reviewer walk already catches
the miss in a single cheap retry, the saved cost (~one Implementer dispatch per
affected task) may not justify the prompt surface. That outcome is a legitimate
SKIP and must be reported as such — same discipline as v2.7 D008.

## Measurement design (isolated, low-cost)

To isolate the intervention from the already-shipped reviewer walk and avoid full
~$5–15 orchestrator runs, measure the **Implementer in isolation** on fixture 08
Task 0 (`parse_duration`):

- Control arm: current `implementer-prompt.md`, N reps → score first-pass output
  against the 20-check fixture-08 rubric (focus: the 4 meta-rule-only checks
  `30m20m`, `1h 30m`, `1H`, `s`).
- Treatment arm: patched prompt, N reps → same scoring.
- Primary metric: first-pass pass-rate on the 4 meta-rule-only checks.
- Secondary: total rubric pass-rate; presence/quality of `ADVERSARIAL_SELFCHECK:` line.

Pass criteria (all required to SHIP):
1. Treatment first-pass meta-rule pass-rate ≥ 75% (vs ~25% control).
2. No regression on the 16 non-adversarial rubric checks (stays ≥ control).
3. `ADVERSARIAL_SELFCHECK:` line present and non-fabricated in ≥ N-1 of N treatment reps.
4. No measurable code-quality regression (over-engineering from defensive input handling).

## Non-goals (explicit deferrals)

- **Verifier acceptance-criteria coverage walk** — separate deferred candidate.
- **SKILL.md changes** — the change lives entirely in `references/implementer-prompt.md`.
- **Hook enforcement of the new output line** — kept as a reported line only, to
  hold the surface small (matches v2.9 keeping the walk prose-level).
- **Reviewer / Verifier / Plan-Reviewer prompt changes.**

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis
- [intervention.md](./intervention.md) — the reverted prompt change, preserved for revival
- [bench/run_ab.py](./bench/run_ab.py) — isolated A/B harness (Sonnet-pinned); re-test trigger lives in F001

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T0 — Experiment scaffold + ADRs | ✓ done | this directory + D001 + D002 |
| T1 — `implementer-prompt.md` intervention edit | ✓ done (working tree, unvalidated) | adversarial self-check step + `ADVERSARIAL_SELFCHECK:` output line; `evals/check_skill_contract.py` passes |
| T2 — Isolated measurement harness | ✓ done | `bench/run_ab.py`; plumbing validated (both arms fill cleanly, no placeholders left, control/treatment contrast confirmed); no budget spent |
| **GATE — budget confirmation for N-rep dispatch** | ✓ cleared | user: "추천으로 진행" → pilot-first |
| T3 — Cheap dry-run pilot (1 rep/arm) + fidelity fix | ✓ done | mechanism + SELFCHECK line confirmed; found+fixed `--model sonnet` pin bug (was inheriting Opus default) |
| T4 — Sonnet control baseline (n=4) | ✓ done | **control = 100% meta-rule first-pass (16/16)** — premise falsified; treatment n=4 skipped (no headroom) |
| T5 — Findings + ship/skip recommendation | ✓ done | [F001](./findings/F001-close-out-skip.md) → **SKIP** |
| T6 — Residual-risk close-out | ✓ done | harness revival guard + results provenance + intervention preserved + advisor-review waived (nothing ships); release metadata/HISTORY n/a |

## Decisions index

- D001 — Metric is prevention (first-pass + retries), not final quality — [link](./decisions/D001-metric-is-prevention.md)
- D002 — Measure the Implementer in isolation, not via full orchestrator runs — [link](./decisions/D002-isolated-implementer-measurement.md)

## Findings index

- F001 — Close-out: **SKIP** (baseline defect no longer reproduces on current Sonnet) — [link](./findings/F001-close-out-skip.md)
