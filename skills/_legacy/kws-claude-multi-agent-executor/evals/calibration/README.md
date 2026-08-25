# Judge Calibration

Purpose: validate that the LLM judge can discriminate good code from buggy code
**when both have all tests passing**. This is the discrimination the judge will
need during best-of-N selection in quality mode — a Combined Reviewer that says
PASS does not guarantee correctness; the judge must see the bugs in the diff.

## Acceptance criteria (advisor #3)

Judge score(`good_impl`) − score(`broken_impl`) ≥ 0.2, consistent across 3 reps.
Otherwise the judge cannot serve as the measurement instrument for the pilot.

## Protocol

1. `good_impl.py` — handles all 15 spec behaviors from fixture 08.
2. `broken_impl.py` — handles 11/15. Returns wrong VALUE (not error) for: internal
   whitespace, uppercase units, repeated unit, bare unit. (Decimal also raises but
   for wrong reason; we count this as not-a-discriminating-case.) Tests pass for
   both because `tests.py` does not cover the 4 silent-failure cases.
3. `run.py` builds a judge-input prompt for each impl using
   `../judge.md` as template, then optionally invokes `claude -p` 3× per impl.
4. Compares mean scores across the 3 reps; pass iff Δ ≥ 0.2.

## Why "tests pass for both" matters

In quality mode the best-of-N judge runs *after* Combined Reviewer has already
passed each candidate. So tests-pass is the precondition. The discriminating
signal must come from the diff itself, not from pytest output.

## Regression check after judge bias-guard changes (v2.30 J4)

`judge.md` gained a **Bias guards** section (v2.30 J4) that constrains only the
subjective `code_quality` axis (verbosity ≠ quality, no position bias, no
self-preference). The deterministic axes are unchanged.

Whenever `judge.md`'s scoring text changes, re-run this calibration and confirm
the discrimination acceptance criterion still holds:

- **`score(good_impl) − score(broken_impl) ≥ 0.2`, consistent across 3 reps.**

The specific risk this guards against: the new "verbosity ≠ quality / minimal
sufficiency is near-perfect" wording must NOT cause the judge to *under*-value
`good_impl`'s concise-but-complete implementation (which would shrink the delta).
If the delta drops below 0.2 after a judge edit, the bias guards over-corrected —
revert or soften the wording, do not ship. This is a paid re-run (`run.py`);
run it once per judge change, not per commit.
