# JOURNAL — v2.23 Implementer Adversarial Self-Check

## 2026-06-02 — T0: experiment opened

- Origin: user asked for quality-prioritized optimizations. Analysis surfaced a
  prevention/detection asymmetry — the Reviewer has an adversarial mechanism
  (v2.9 sub-step B) but the Implementer has none. The defect v2.7 F002 measured
  (`30m20m` first-pass miss) is caught in review, not prevented at creation.
- Selected this as the experiment because it is the only Implementer-prompt
  change mapping to a documented, quantified failure (v2.7 F002), and it mirrors
  a mechanism v2.9 already validated.
- Key framing decision (D001): on fixture 08 the v2.9 reviewer walk already
  ceilings *final* rubric pass-rate at 1.0, so this experiment can only show
  *prevention* (first-pass pass-rate ↑, retries ↓), never higher end-state
  quality. Measuring final quality would yield a null by construction. This also
  means a v2.7-style "marginal gain, SKIP" outcome is a real possibility.
- Measurement isolation decision (D002): measure the Implementer alone on
  fixture 08 Task 0, not via the full ~$5–15 orchestrator harness, to (a) isolate
  the intervention from the already-shipped reviewer walk and (b) keep cost low.

## 2026-06-02 — T1: intervention drafted

- Edited `references/implementer-prompt.md`: added an "Adversarial meta-rule
  self-check" instruction wired into the TDD RED step, plus an optional
  `ADVERSARIAL_SELFCHECK:` output line for adherence measurement. Meta-rule
  lexicon mirrors reviewer sub-step B verbatim for consistency.
- Change is in the working tree only, unvalidated. Status README marks it as
  such. Not committed (repo tree has unrelated pending changes; will recommend a
  branch when measurement passes).

## 2026-06-02 — T2: bench harness built + validated (no budget spent)

- `bench/run_ab.py`: dispatches one Implementer via `claude -p` per rep on fixture
  08 Task 0, scores first-pass `src/duration.py` with `evals/rubric.py`, records the
  4 meta-rule-only checks (`30m20m`/`1h 30m`/`1H`/`s`) + the `ADVERSARIAL_SELFCHECK:`
  line. Control arm = `git show HEAD:` of the prompt (pre-intervention); treatment =
  working-tree prompt.
- Validated plumbing offline (no `claude -p` calls): fixture loads, both arms fill
  with zero leftover placeholders, prompt body correctly extracted from the ````
  fence, control lacks the self-check / treatment has it. Fixed two fidelity bugs:
  path depth (`parents[3]`) and stripping the doc wrapper + inapplicable re-dispatch
  bullets.
- `evals/check_skill_contract.py --skill ./SKILL.md` → passed: true (intervention
  doesn't break the prompt contract).

## 2026-06-02 — T3: pilot dry-run (1 rep/arm) + fidelity fix

- First pilot (control + treatment, 1 rep each) returned BOTH arms at 4/4
  meta-rule + 20/20 total. Treatment's `ADVERSARIAL_SELFCHECK:` line fired
  correctly ("meta-rules found: 2 … inputs tested: 30m20m, 1h1h, 1H, \"1h 30m\",
  s, …") — the mechanism works.
- BUG found by the dry-run: `_run_implementer` dispatched `claude -p` with no
  `--model`, so it inherited the user default (`claude-opus-4-8`, per
  `~/.claude/settings.json`). Production Implementer + the v2.7 F002 ~25%
  baseline are both **Sonnet**. Opus 4.8 ceilings the metric and invalidates the
  control baseline — exactly the contamination D002 warned against.
- Fix: pinned `--model sonnet` in `_run_implementer`. Re-running the pilot on
  Sonnet to see whether the ~25% baseline reproduces at all on the current CLI
  (2.1.145). If even Sonnet now ceilings control, the v2.7 premise is stale and
  this is a SKIP (the model improved past the defect the intervention targets).

## 2026-06-02 — T4/T5: Sonnet control baseline → SKIP

- Clean n=4 Sonnet control baseline: ALL 4 reps 4/4 meta-rule + 20/20 total.
  Meta-rule first-pass pass-rate = 100% (16/16). v2.7 F002 measured ~25% on this
  exact fixture; the defect no longer reproduces on the current Sonnet.
- Did NOT run treatment n=4: control is at ceiling, so pass criterion #1
  (treatment ≥75% vs ~25% control) is structurally unsatisfiable — no information
  value in spending 4 more dispatches.
- Outcome: **SKIP**, recorded in `findings/F001-close-out-skip.md`. Mirrors v2.7
  D008 (best-of-N kept off main). The mechanism works (SELFCHECK line fired with
  genuine adversarial inputs) — this is a "problem already solved by the model"
  null, not a "mechanism broken" null. Intervention reverted to HEAD; experiment
  dir kept as the negative-result record + ready-to-revive lever.

## 2026-06-02 — T6: residual-risk close-out

- **Advisor review (AGENTS.md step 6)** — WAIVED, not pending. The protocol step
  exists to vet a *shipping* change; this experiment ships nothing (SKIP), so there
  is no production diff to review. If revived, run advisor review on the re-applied
  intervention before shipping.
- **Harness revival hazard** — RESOLVED. The treatment arm reads the working-tree
  prompt, which was reverted to HEAD at close; re-running treatment would have
  silently produced a control-identical (invalid) A/B. Added a guard in
  `bench/run_ab.py` that aborts before any dispatch unless the
  `ADVERSARIAL_SELFCHECK` marker is present (treatment) / absent (control). Verified
  it fires (exit 1, zero budget).
- **Results provenance** — RESOLVED. `bench/results/README.md` records that the
  stored JSONs are Sonnet (control n=4, treatment n=1 pilot) and that the invalid
  Opus pilots were discarded.
- **Intervention preservation** — RESOLVED. Exact patch blocks saved in
  `intervention.md` so the reverted change is revivable.

## Notes / open items

- None. Experiment CLOSED (SKIP). Re-test trigger documented in F001 §Recommendation.
