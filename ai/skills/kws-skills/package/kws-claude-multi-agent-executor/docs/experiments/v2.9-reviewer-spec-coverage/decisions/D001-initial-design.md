# D001 — Spec-Coverage Walk: single-pass enumeration in reviewer-prompt.md

**Date**: 2026-05-13
**Status**: Decided (pre-implementation)

## Context

`oh-my-claudecode` (omc) analysis surfaced 7 importable orchestration patterns
(A–G). Pre-write advisor review forced an evidence test: which of the 7 maps
to a *measured* KCMAE failure?

| Candidate                                  | Evidence in KCMAE corpus? |
|--------------------------------------------|----------------------------|
| C — Reviewer "What's Missing" walk         | **YES — see "Evidence chain" below** |
| D, E, F, G, A, B                           | No measured failure       |

Only C survived the test. v2.9 ships C alone; the others remain candidate
ideas pending real-failure evidence from the v2.8 learning log.

### Evidence chain (one inferential hop, made explicit)

v2.7 F002 directly measures the **Implementer's** rubric pass-rate on
fixture 08: 3 of 4 reps shipped code that failed the `parse_duration("30m20m")`
ValueError check (75% miss rate). The Reviewer ran against each shipped
artifact under v2.6.0's Combined Reviewer prompt and did not produce a
`SPEC_STATUS: FAIL` blocking the merge — i.e., the shipped code is precisely
the artifact the Reviewer signed off on.

So the chain is: *"Implementer rubric miss rate = 75% ∧ Reviewer marked
SPEC_STATUS: PASS on each rep ⇒ Reviewer miss rate on `implementer_omitted`
= 75% for this fixture."* Solid inference, but one hop — v2.9's T5
measurement should also record raw Reviewer output (not just whether the
rep shipped buggy code) so we can confirm the inference holds under the
new prompt.

## Question 1 — Mechanism: single-pass enumeration vs multi-perspective dispatch

**Options considered**:

- **A. Single-pass enumeration in `reviewer-prompt.md`** — add a deterministic
  "Spec Coverage Walk" step BEFORE the existing Part 1 scoring. The Reviewer
  must list every spec-mandated behavior (happy-path examples + error cases
  + notes) and locate the code path satisfying each one. Items without a
  located path become `implementer_omitted` flags driving SPEC_SCORE down.
- **B. Multi-perspective dispatch** — orchestrator dispatches N parallel
  Reviewer sub-agents with distinct prompts (Security / Correctness / DX),
  combines findings. This is omc's "Team" pattern.
- **C. Best-of-N Reviewer + judge** — like quality_plus from v2.7 but applied
  to review side instead of implementation side.

**Decision**: **A (single-pass enumeration)**.

Rationale:
- F002 explicitly shows the miss is *not* probabilistic candidate diversity:
  3/3 reps produced the same single miss on `30m20m`. Best-of-N would
  produce three candidates with the same miss. Multi-perspective dispatch
  with one "Correctness" perspective collapses to the same single-pass
  problem we're trying to fix.
- The root cause is the prompt asking "verify it satisfies" (which scans for
  *presence*) rather than "for each mandated item, locate the path" (which
  forces *coverage*). Fixing the prompt is the minimum-viable intervention
  matching the diagnosed mechanism.
- Single-pass costs ~0 extra tokens (one section added to one prompt) vs
  multi-perspective which adds N× dispatch.
- If A underperforms in T5 measurement (miss rate still ≥50%), we have data
  to justify B as v2.10. Reverse order would skip the cheaper experiment.

## Question 2 — Where to write the new step

**Options**:

- **A.** Prepend to Part 1 in `references/reviewer-prompt.md` (before the
  existing 4 numbered steps).
- **B.** Replace step 1 in Part 1.
- **C.** New top-level "Part 0" section.

**Decision**: **A**. Existing structure is good; inserting one new step
between "Before reviewing" (Skill call) and Part 1 step 1 keeps the
"first walk coverage, then score" ordering explicit without restructuring
the prompt.

## Question 3 — How strict to make the walk, AND how to handle meta-rules

**Critical correction (post-advisor-pre-check 2026-05-13)**: The initial
template would have been useless on fixture 08. The fixture's spec section
lists 5 explicit ValueError examples (empty / bare number / unknown unit /
negative / decimal) plus a meta-rule:

> *"Beyond these examples, the function must strictly validate input format.
>  Anything that does not match the documented `<integer><unit>...` grammar
>  is invalid. ... The rule is 'strict validation of the grammar.'"*

`parse_duration("30m20m")` is covered ONLY by the meta-rule. A faithful
enumeration over explicit bullets would pass all 5, locate each rejection
path in the code, and never produce a row for `30m20m` — i.e., the same
miss as today. The walk would feel rigorous and change nothing.

The omc "What's Missing" pattern this experiment imports is **adversarial
generation from meta-rules**, not enumeration of stated bullets.

**Options reconsidered**:

- **A.** Free-form enumeration.
- **B.** Strict template — enumerate stated spec bullets only.
- **C.** Strict template — enumerate stated bullets AND generate ≥3
  adversarial inputs per meta-rule, locate rejection path for each.

**Decision**: **C (enumerate + adversarial generation)**.

The walk has two ordered sub-steps:

**3a. Enumerate stated bullets.** For each happy-path example and each
explicit error-case bullet in the injected spec excerpt, emit one walk row
using the strict template:

```
"<spec text fragment>" :: <file>:<line>      (satisfied)
"<spec text fragment>" :: NOT FOUND          (implementer_omitted)
"<spec text fragment>" :: PARTIAL @ <file>:<line> — <why>
```

**3b. Adversarial generation for meta-rules.** Identify each meta-rule in
the spec (sentences containing words like *"strict"*, *"reject"*,
*"anything else"*, *"must validate"*, *"rule is"*, *"beyond these
examples"*). For each meta-rule, generate **at least 3 adversarial inputs
not explicitly listed in the spec** — inputs the Implementer might overlook:
- repeated-unit variants (e.g., `30m20m`, `1h1h`)
- ordering / casing edge cases (e.g., `1H`, `1h 30m`, `1h30`)
- format combinations the spec implicitly excludes (e.g., empty unit `s`,
  trailing integer `1h30`)

Emit one walk row for each adversarial input, locating the rejection path
in the code or flagging NOT FOUND.

Output label: `SPEC_COVERAGE_WALK:` with both sub-sections inline (no
sub-headers — single flat list, where adversarial rows are visually
distinguishable by being newly synthesized strings, not direct spec quotes).

Rationale:
- Enumeration alone (option B) doesn't move the F002 miss rate. Verified
  by walking the spec for fixture 08 manually: `30m20m` is not a stated
  bullet.
- Adversarial generation forces Sonnet to surface candidate edges before
  scoring. Even if the Implementer's code lacks a path for one of the
  generated inputs, the walk row produces a `NOT FOUND` → SPEC_FAULT:
  implementer_omitted.
- Cost: ~5-10 additional walk rows per task. Fixture 08 may produce ~25
  total rows (15 stated + ~10 adversarial). Output cost negligible.
- Risk: Sonnet generates "weak" adversarial inputs (already-covered cases)
  and the walk feels rigorous without finding the miss. Mitigation: the
  prompt explicitly directs the generation toward classes of inputs
  ("repeated units", "ordering variants", "casing", "format combinations
  the spec implicitly excludes"). If T5 reveals the generation is too
  weak, v2.10 escalates to either a calibration step or multi-perspective
  dispatch.
- `NOT FOUND` token remains mechanically detectable for future analysis.

## Question 4 — Measurement plan

**Decision**:
- T5 runs `evals/fixtures/08-subtle-input-validation.yaml` 3-4 reps with
  the v2.9 prompt change applied.
- Pass criterion: `parse_duration("30m20m")` ValueError check rejected in
  ≥75% of reps (vs ~25% in F002 baseline = ~75% miss rate).
- Secondary check: SPEC_SCORE distribution stays within tolerance of the
  v2.7 baseline mean (no significant new false-positive `implementer_omitted`
  flags).
- Cost: ~$5-10 per rep × 4 reps = $20-40 budget ask.

## Question 5 — Hard prerequisite on v2.8 F001 smoke

**Decision**: T4 (prompt edit) **cannot start** until v2.8 F001 full-fixture
smoke closes PASS.

Reason:
- v2.9's primary observability is `reviewer_warn_or_fail` event emission
  from the v2.8 learning log. If F001 reveals the orchestrator skips the
  helper-invocation snippets in SKILL.md under real `claude -p`, the
  learning log produces no events and v2.9's measurement becomes
  rubric-only (older, less informative).
- Backup channel exists: rubric.py pass_rate, which worked in v2.7 F002
  without any learning log. If F001 shows an integration gap, v2.9 can
  proceed using the backup channel — but only with explicit acknowledgment
  in the T5 finding that event-level analysis was lost.
- The cleanest path is: smoke v2.8, confirm events fire, then start v2.9.
  Order matters because building v2.9 on an unvalidated foundation creates
  ambiguity if T5 underperforms (was it the prompt change, or did the
  log not fire?).

## Out-of-scope decisions (recorded but deferred)

### Multi-perspective Reviewer dispatch (v2.10 candidate)

omc dispatches multiple Reviewer perspectives in parallel. KCMAE has no
measured failure that requires N perspectives — F002 is a single-axis
correctness miss. **Decision**: defer to v2.10. Re-evaluate after v2.9
T5 results. If miss rate still ≥50% after the prompt change, multi-perspective
is the obvious next step.

### Conflict-mailbox event type (v2.10+ candidate)

omc uses a conflict-mailbox JSONL for cross-agent merge collisions. KCMAE
has no measured merge-conflict failure in the corpus. **Decision**: defer.
Re-evaluate when the v2.8 learning log surfaces a real `parallel_dispatch_failure`
or merge-related event.

### omc governance flags / heartbeat / sentinel READY (v2.10+ candidates)

All defensive instrumentation for failure modes KCMAE has not measured.
**Decision**: defer. Re-evaluate when the v2.8 learning log surfaces matching
failure modes.

### Inbox/Outbox messaging (v2.11+ candidate)

omc uses per-pane JSONL messaging because it runs N CLI processes in tmux.
KCMAE uses in-process Agent-tool dispatch (Phase 1) + `claude -p` subprocess
(Resume Chain) which already work. **Decision**: defer indefinitely. Revisit
only if KCMAE topology changes to multi-process.

### Auto-merge orchestrator (v2.11+ candidate)

omc auto-merges parallel branches per its multi-pane topology. KCMAE merges
in-process (no parallel branches at orchestrator level). **Decision**: defer
indefinitely.

## Consequences

- v2.9 surface area: one prompt file, ~30 lines added. Smaller than v2.8.
- T5 cost: $20-40 (separate from the v2.8 smoke budget).
- Cleanest possible attribution: any change in F002 miss rate is uniquely
  attributable to the prompt change.
- If T5 fails to move the miss rate, v2.10 has a clean rationale for
  escalating to multi-perspective dispatch.
- If T5 succeeds, future Reviewer changes have a working template for
  "deterministic walk before scoring" patterns.

## Links

- v2.7 F002 close-out (evidence base): `../v2.7-quality-mode/findings/F002-close-out.md`
- v2.7 F001 fixture 08 baseline: `../v2.7-quality-mode/findings/F001-fixture08-baseline.md`
- v2.8 F001 smoke (the hard prerequisite): `../v2.8-learning-log/findings/F001-smoke.md`
- Current Reviewer prompt: `references/reviewer-prompt.md`
- Fixture 08: `evals/fixtures/08-subtle-input-validation.yaml`
- AGENTS.md protocol for experiment record-keeping
