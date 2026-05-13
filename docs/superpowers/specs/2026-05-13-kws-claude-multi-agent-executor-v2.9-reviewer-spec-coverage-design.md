# Design Spec: kws-claude-multi-agent-executor v2.9 — Reviewer Spec-Coverage Walk

**Date**: 2026-05-13
**Owner**: kws
**Status**: DESIGN (implementation gated on v2.8 F001 full-fixture smoke PASS)
**Target skill**: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor`
**Predecessor**: v2.8 (learning log) — shipped on branch, behavior-smoke deferred
**Production baseline**: v2.6.0 (untouched on `main`)
**Sibling experiment record**: `package/.../docs/experiments/v2.9-reviewer-spec-coverage/`

## Problem statement

v2.7 F002 directly measured a ~75% Implementer rubric miss rate on
`parse_duration("30m20m")` failing to raise ValueError on fixture 08 (3 of 4
reps shipped buggy code). Each of those reps passed through the v2.6.0
Combined Reviewer prompt with `SPEC_STATUS: PASS` — so the Reviewer
signed off on the buggy artifact in 3 of 4 reps. Reviewer miss rate on
this `implementer_omitted` fault is therefore inferred at 75% (one
inferential hop from F002's directly-measured Implementer miss rate).

This is the most reproducible measured failure in the KCMAE eval corpus
and the only orchestration-side failure with quantified data.

Mechanism diagnosed in F002 close-out + this design's pre-write check:
Sonnet's regex/grammar instinct reads the spec excerpt as "natural language
about non-repeated units" and never explicitly tests *"is the case
`30m20m` rejected somewhere in this code?"* The fixture 08 spec lists 5
explicit ValueError examples (empty / bare number / unknown unit / negative /
decimal) — `30m20m` is **not** one of them. It is covered only by the
meta-rule *"strict validation of the grammar."* The current Reviewer
prompt (Part 1 step 1: *"For each requirement in the spec excerpt: verify
the implementation satisfies it exactly"*) treats this as a summary check
over stated bullets — Sonnet scans for what is present, not for what is
mandated-by-meta-rule-but-absent.

## Goal

Reduce the `implementer_omitted` miss rate on fixture 08 from ~75% to under
25% by changing the Reviewer prompt to require a deterministic enumeration
pass before scoring.

Single-prompt change. No new sub-agent dispatch, no helper changes, no
SKILL.md changes, no new event types.

## Non-goals

- Multi-perspective Reviewer dispatch (Reviewer-Security, Reviewer-Correctness,
  Reviewer-DX as separate sub-agents). Deferred to v2.10 conditionally.
- Best-of-N Reviewer + judge.
- Verifier / Plan Reviewer prompt changes.
- Generalizing the walk to non-spec axes (security, performance). Only the
  spec-coverage axis has measured failure data.

## Design

### Contract: one new section in `references/reviewer-prompt.md`

Inserted between the existing "**Before reviewing:**" Skill-invocation
paragraph and "**Part 1 — Spec Compliance:**". Heading: **"Spec Coverage
Walk (REQUIRED — output BEFORE scoring)"**.

The walk has two ordered sub-steps. Both produce rows in a single flat
`SPEC_COVERAGE_WALK:` list, each row using the same strict template:

```
"<spec text fragment OR adversarial input>" :: <file>:<line>     # satisfied
"<spec text fragment OR adversarial input>" :: NOT FOUND         # implementer_omitted
"<spec text fragment OR adversarial input>" :: PARTIAL @ <file>:<line> — <why>
```

**Sub-step A — Enumerate stated bullets.** For each happy-path example,
each explicit error-case bullet, and each "Notes" bullet that imposes a
constraint in the injected spec excerpt, emit one walk row.

**Sub-step B — Adversarial generation for meta-rules.** Identify each
meta-rule in the spec (sentences with words like *"strict"*, *"reject"*,
*"anything else"*, *"must validate"*, *"rule is"*, *"beyond these
examples"*). For each meta-rule, generate **≥3 adversarial inputs not
explicitly listed in the spec** drawn from at least these classes:
- repeated-unit / repeated-segment variants
- ordering / casing edge cases (uppercase units, internal whitespace,
  trailing unit-less integer)
- format combinations the spec implicitly excludes

Emit one walk row for each generated input, locating its rejection path in
the code or flagging NOT FOUND.

This sub-step is the critical mechanism for closing F002's measured miss.
Enumeration alone (sub-step A only) would not surface `30m20m` on fixture 08
because the spec lists 5 explicit ValueError examples that do NOT include
repeated-unit cases — those are covered only by the meta-rule "strict
validation of the grammar."

#### Scoring impact

If any `NOT FOUND` row exists (in either sub-step) → `SPEC_FAULT: implementer_omitted`
and the top `SPEC_ISSUES` row references the offending walk row as evidence.

If any `PARTIAL` row exists → SPEC_SCORE capped at 0.7 (existing anchor).

If all rows are satisfied → walk passes; SPEC_SCORE proceeds to existing
0.85+ logic.

The walk output **precedes** the existing output block (SPEC_SCORE, etc.)
under the new top-level label `SPEC_COVERAGE_WALK:`.

### Reviewer output format (extended)

```
SPEC_COVERAGE_WALK:
  # sub-step A (stated bullets):
  - "30s == 30" :: src/duration.py:14
  - "empty string raises ValueError" :: src/duration.py:7
  - "negative -30s raises ValueError" :: src/duration.py:22
  # sub-step B (adversarial from meta-rule "strict validation"):
  - "repeated unit 30m20m raises ValueError" :: NOT FOUND
  - "uppercase unit 1H raises ValueError" :: src/duration.py:18
  - "internal whitespace 1h 30m raises ValueError" :: NOT FOUND
  ...
SPEC_SCORE: <0.0–1.0>
QUALITY_SCORE: <0.0–1.0>
SPEC_STATUS: PASS | FAIL
QUALITY_STATUS: PASS | FAIL
SPEC_FAULT: spec_contradicts | unclear | implementer_omitted | none
SUMMARY: <≤3 sentences>
SPEC_ISSUES:
  - ISSUE_KEY: <file>:<line>:<category> | <description> or "none"
QUALITY_ISSUES:
  - ISSUE_KEY: <file>:<line>:<category> | <description> or "none"
FILES_REVIEWED:
  - <file>
```

Nothing existing changes. The walk is purely additive at the front of the
output.

### Orchestrator parsing impact

SKILL.md's Reviewer output parser (Phase 1 Step 3) currently reads
`SPEC_SCORE`, `QUALITY_SCORE`, `SPEC_STATUS`, `QUALITY_STATUS`, `SPEC_FAULT`,
`SUMMARY`, `SPEC_ISSUES`, `QUALITY_ISSUES`, `FILES_REVIEWED`. The new
`SPEC_COVERAGE_WALK` field is **ignored by the parser** in v2.9. The walk's
job is to force the Reviewer into a coverage pass that influences the
existing fields it already parses. Logging the walk to the learning log is
a v2.10+ enhancement.

### Learning log payload (no schema change)

The existing `reviewer_warn_or_fail` event captures `summary` and `evidence`.
The walk's top `NOT FOUND` row will surface in those fields naturally
through `SPEC_ISSUES`. **No event_type addition. No schema change.**

## Hard prerequisite: v2.8 F001 full-fixture smoke must PASS

Before T4 (prompt edit) starts, `docs/experiments/v2.8-learning-log/findings/F001-smoke.md`
must transition from "DEFERRED" to "PASS" on the full-fixture criteria:
- Smoke A (`01-trivial-typo.yaml`) produces `meta.outcome=success`, `event_count=0`.
- Smoke B (`08-subtle-input-validation.yaml`) produces at least one event
  with `event_type=reviewer_warn_or_fail`.

If Smoke B fails to emit the event, v2.9 measurement loses event-level
attribution and must fall back to rubric.py-only signal (v2.7's mechanism).
The fallback is acceptable but inferior; the v2.9 finding must explicitly
note the fallback in its residual-risks section.

## Testing plan

### Measurement: fixture 08, n=3–4 reps

Run `evals/fixtures/08-subtle-input-validation.yaml` with the v2.9 prompt
applied. For each rep, capture:

1. `rubric.json` pass_rate (existing mechanism).
2. Whether `parse_duration("30m20m")` rejection check passes (specific item).
3. `events.jsonl` contents (from v2.8 learning log) — count of
   `reviewer_warn_or_fail` events; SPEC_COVERAGE_WALK content if the
   Reviewer is asked to include it in the evidence payload.

### Pass criteria for v2.9 ship

**Primary**: `parse_duration("30m20m")` rejection check rate moves from
~25% (F002 baseline) to ≥75% across 3-4 reps. (Equivalent: miss rate drops
from ~75% to ≤25%.)

**Secondary**: SPEC_SCORE distribution mean stays within 0.05 of F002 baseline.
No significant new false-positive `implementer_omitted` flags from the walk.

**Tertiary**: When `reviewer_warn_or_fail` fires, the event payload should
include the `NOT FOUND` walk row as evidence (v2.10 schema enhancement;
captured in T5 finding only if naturally surfaced).

### Stop condition (negative result)

If pass_rate on `30m20m` rejection check stays ≤50% across 3+ reps, ship is
blocked. Findings doc captures the outcome and recommends v2.10 multi-
perspective dispatch as next attempt. The prompt change reverts.

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Sonnet generates "weak" adversarial inputs (already-covered cases) in sub-step B | Medium | Prompt names input classes explicitly (repeated-unit, ordering/casing, format combinations the spec implicitly excludes). T5 inspects walk output. If weak, v2.10 escalates. |
| Walk produces false-positive `NOT FOUND` flags (Reviewer can't find code that exists) | Medium | Secondary pass criterion catches this; if it spikes, walk template needs anchor examples |
| Reviewer ignores the walk template and reverts to summary check | Low | Template is structurally strict; sub-step B explicitly requires ≥3 adversarial rows per meta-rule |
| v2.8 F001 reveals helper invocation gap → no event signal | Medium | Fallback to rubric-only measurement; documented in T5 finding |
| Reviewer output exceeds context budget (longer prompt + walk output) | Low | Fixture 08 ~15 stated + ~10 adversarial = ~25 walk lines × ~80 chars = ~2KB additional output |
| Walk doesn't fire on tasks with short specs / no meta-rules | Medium | Acceptable — sub-step A still runs; sub-step B no-ops when no meta-rule keywords match |

## Out-of-scope (deferred to v2.10+ candidate shelf)

- omc multi-perspective Reviewer dispatch
- omc governance flags
- omc heartbeat freshness
- omc conflict-mailbox event type
- omc sentinel READY gate
- omc inbox/outbox messaging
- omc auto-merge orchestrator

Each remains a candidate. None has measured KCMAE failure data. Re-rank
after v2.8 learning log produces 4+ weeks of real-run event data and
v2.9 T5 produces its result.

## Acceptance criteria (for the ship decision)

1. v2.8 F001 full-fixture smoke PASS (gate).
2. Prompt change applied to `references/reviewer-prompt.md` only.
3. Fixture 08 re-run 3-4 reps shows `30m20m` rejection rate ≥75% (primary).
4. SPEC_SCORE mean within 0.05 of F002 baseline (secondary).
5. v2.9 finding doc records reps, scores, rubric results, residual risks.
6. HISTORY.md v2.9.0 entry + manifest bump (only if 1-5 satisfied).

## Open questions (for advisor review before T4)

- **Q1**: Should the walk be made *visible to the Implementer* on review_retries > 0
  (so retry attempts target NOT FOUND rows)? Current answer: defer — Implementer
  retry already receives `previous_issues`; adding walk would duplicate.
- **Q2**: Should the walk's strict template be encoded as a small validator
  in `evals/check_skill_contract.py` (counting walk lines vs spec bullets)?
  Current answer: defer to v2.10 — adds eval surface for marginal benefit
  given the walk is a prompt-level discipline, not a code-level contract.
- **Q3**: If T5 succeeds, should the walk pattern be extended to Verifier
  (acceptance-criteria coverage walk)? Current answer: defer — Verifier
  failure rate is not measured at this granularity yet; speculation.

## Links

- v2.7 F002 (evidence base): `package/.../docs/experiments/v2.7-quality-mode/findings/F002-close-out.md`
- v2.8 F001 (hard prerequisite): `package/.../docs/experiments/v2.8-learning-log/findings/F001-smoke.md`
- Current Reviewer prompt: `package/.../references/reviewer-prompt.md`
- Fixture 08: `package/.../evals/fixtures/08-subtle-input-validation.yaml`
- v2.9 experiment record: `package/.../docs/experiments/v2.9-reviewer-spec-coverage/`
- D001: `package/.../docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md`
