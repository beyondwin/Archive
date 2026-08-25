# D006 — Pilot first, not full experiment

**Date**: 2026-05-13
**Status**: Decided (per advisor #1, #2, #3)

## Context

User originally approved the "full experiment" plan: 4 stressing fixtures
(08–11) × 3 modes × 1 rep = 15 runs, plus mode implementation work, plus
judge calibration. Estimated cost: $300–900, 1.5–2 days.

Advisor pushback:
- n=1 per cell can't detect <huge effects (statistical power broken)
- Designing 4 fixtures + rubrics without piloting one first risks throwing
  away a day's work if the first fixture isn't well-calibrated
- Judge calibration is a prerequisite, not an output

## Decision

Replace "full experiment" with **pilot-first**:

1. Build only fixture 08 first
2. Calibrate judge against fixture 08 (D002)
3. Verify fixture 08 is not at ceiling for balanced mode
4. Implement quality_plus mode (minimal — see D004 for scope)
5. Run pilot: balanced × 3 + quality_plus × 3 = 6 runs
6. Decide next phase based on pilot data

## Decision-tree after pilot

```
Δ (quality_plus − balanced) on rubric pass_rate
│
├─ ≥ +0.10:    Strong signal. Quality_plus has measurable value on MID work.
│              → Design HIGH-fixture, validate quality_alpha vs balanced
│              → Then expand to full experiment fixtures 09–11 if budget permits
│
├─ +0.05–0.10: Marginal positive. Consider whether the cost (~2× tokens)
│              is justified by the lift.
│              → User decision: ship balanced + opt-in plus, or kill plus
│
├─ −0.05–+0.05: Null result. Best-of-N on MID is noise.
│              → Ship quality_alpha only (LOW→MID floor; best-of-N reserved
│                for HIGH); kill quality_plus
│
└─ < −0.05:    Quality_plus regression. Best-of-N + judge selection harms
              MID quality (e.g., judge picks weird/over-engineered candidate).
              → Kill quality_plus. Reconsider whether quality_alpha alone is
                worth shipping; possibly archive entire v2.7 experiment.
```

## Pilot success != ship gate

A positive pilot signal triggers more investigation; it does not by itself
merge the branch. Merge gate is in [D005](./D005-experimental-branch.md).
