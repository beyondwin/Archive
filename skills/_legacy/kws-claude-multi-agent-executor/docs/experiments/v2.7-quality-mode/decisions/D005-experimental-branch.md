# D005 — Experimental branch; no production SKILL.md edits

**Date**: 2026-05-13
**Status**: Decided (per advisor #6)

## Context

v2.6.0 baseline was just stabilized (commits 80c0c39, c9ab406 — eval harness
fixes + v2.6.0 baseline JSON). Modifying SKILL.md to add quality modes risks
breaking that baseline before we have evidence the modes are worth shipping.

## Decision

All quality-mode work happens on `feature/v2.7-quality-mode-experiment`.
`main`'s SKILL.md stays at v2.6.0 unchanged until pilot data justifies merging.

## Branch model

```
main:                  ...80c0c39 ← v2.6.0 (production, stable)
                                  \
feature/v2.7-...:                   d5aa5eb ← calibration + fixture 08 + rubric.py
                                            \
                                              <future: rubric integration>
                                                \
                                                  <future: quality_plus mode>
                                                    \
                                                      <future: pilot results>
```

## Merge gate

Pilot results must show **either**:
- `quality_plus` rubric pass_rate > `balanced` by ≥0.05 with n=3 reps each, OR
- Clear directional signal (no rep where balanced > quality_plus) and stable
  variance

Otherwise: the branch is recorded as a failed hypothesis (kept for posterity
in `findings/`) and not merged.

## What lives where

- **`main` SKILL.md** — v2.6.0 behavior, no `mode` parameter
- **`feature/v2.7-...` SKILL.md** — adds `mode=balanced|quality_plus` parameter
- **`evals/rubric.py`** — additive, harmless on main if backported (but won't be
  backported until quality_plus is merged or rubric proves useful standalone)
- **`evals/calibration/`** — experiment-only, can stay on branch
- **`docs/experiments/v2.7-quality-mode/`** — kept on branch; on merge,
  becomes historical record alongside the new SKILL.md
