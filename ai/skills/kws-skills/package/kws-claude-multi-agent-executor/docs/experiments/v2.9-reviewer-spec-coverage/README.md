# v2.9 — Reviewer Spec-Coverage Walk

**Status**: DESIGN (implementation BLOCKED on v2.8 F001 full-fixture smoke PASS)
**Branch**: TBD (cut from `main` once v2.8 lands and F001 closes PASS)
**Production baseline**: v2.6.0 (untouched on `main`)
**Predecessor**: v2.8 learning log (shipped on branch, behavior-smoke deferred — see `../v2.8-learning-log/findings/F001-smoke.md`)

## Goal

Reduce the Reviewer sub-agent's *prospective* miss rate on `implementer_omitted`
faults by adding a single deterministic step to `references/reviewer-prompt.md`:
a **Spec Coverage Walk** that enumerates spec-mandated behaviors and forces the
Reviewer to locate the code path satisfying each one, before scoring.

Single change. Single prompt file. Single fixture as evidence. No new event
types. No new sub-agent dispatch. No new infrastructure.

## Why this and only this

This experiment was selected from a 7-item shortlist (sourced from the
`oh-my-claudecode` orchestration patterns) on a strict evidence-first basis:

| Candidate                                     | Has measured KCMAE failure case? |
|-----------------------------------------------|----------------------------------|
| **C — Reviewer "What's Missing" walk**        | **YES — v2.7 F002, 75% miss on fixture 08 `30m20m`** |
| D — Governance flags                          | No |
| E — Heartbeat freshness                       | No |
| F — Conflict-mailbox event type               | No |
| G — Sentinel READY gate                       | No |
| A — Inbox/Outbox messaging                    | No |
| B — Auto-merge orchestrator                   | No |

Only C maps to a documented failure with quantified miss rate. The other six
are interesting omc imports without local evidence; they remain on the
candidate shelf, to be reconsidered only when the learning log surfaces a
matching real failure pattern.

This matches the discipline from v2.7 D008 ("designed but not shipped" was
the right call) and v2.6.0 D006 ("pilot-first scoping saves days"). Build
*one* thing, measure, then decide.

## Hypothesis

If the Reviewer prompt requires a deterministic Spec Coverage Walk before
scoring — combining (A) enumeration of stated spec bullets with
(B) adversarial input generation from spec meta-rules ("strict validation",
"reject anything else", etc.) — the miss rate on `implementer_omitted` faults
will drop from the ~75% baseline (inferred from v2.7 F002 fixture 08, 4 reps)
to under 25% on the same fixture.

The mechanism: today's Reviewer prompt asks "for each spec requirement,
verify the implementation satisfies it" but Sonnet treats this as a *summary
check*, scanning the diff for what is present rather than for what is
mandated-but-absent. Pure enumeration of stated bullets does not close
F002 — `30m20m` is not an explicit bullet in fixture 08; it is covered
only by the meta-rule "strict validation of the grammar". Adversarial
generation from meta-rules is what closes the gap.

Reviewer-miss inference is one hop from the F002 data: F002 directly
measures the Implementer's rubric pass-rate (3/4 reps shipped buggy code),
and each rep passed `SPEC_STATUS: PASS` review — so the Reviewer signed
off on the buggy artifact in 3/4 reps. T5 measurement records raw Reviewer
output (not just whether the rep shipped buggy code) so the inference can
be re-confirmed under the new prompt.

## Evidence base

- `v2.7-quality-mode/findings/F002-close-out.md` — 4 reps of fixture 08,
  3 of 4 missed `parse_duration("30m20m")` ValueError. Single most reproducible
  miss in the eval corpus.
- `v2.7-quality-mode/findings/F001-fixture08-baseline.md` — Reviewer score
  variance analysis on the same fixture.
- Existing `references/reviewer-prompt.md` lines 34-41 — Part 1 Spec Compliance
  step is *abductive* (SPEC_FAULT diagnosis after the fact), not *prospective*.

## Non-goals (explicit deferrals)

- **Multi-perspective Reviewer dispatch** (separate Reviewer-Security /
  Reviewer-Correctness / Reviewer-DX sub-agents per omc pattern). Single-pass
  enumeration first; if it underperforms in F002 follow-up, escalate to
  multi-perspective dispatch in v2.10.
- **New event types** in the learning log. The existing
  `reviewer_warn_or_fail` event type captures everything this experiment
  needs to observe.
- **SKILL.md changes**. The change lives entirely in `references/reviewer-prompt.md`.
- **Plan Reviewer / Verifier** prompt changes. v2.8 already added their
  Skill calls; no further work in v2.9.

## Hard prerequisite

**v2.8 F001 full-fixture smoke must close PASS before T4 (prompt edit)
starts.** Reason: v2.9 measurement uses fixture 08 with the v2.8 learning
log capturing `reviewer_warn_or_fail` events as the primary observability
channel. If the learning log doesn't actually fire under real `claude -p`
conditions, we cannot measure whether the prompt change worked.

If F001 finds the orchestrator skips the helper-invocation snippets, v2.9
either (a) waits for a v2.8.1 fix, or (b) measures the change purely via
rubric.py pass_rate (the older mechanism) — but the latter loses cross-run
event-level signal.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T0 — Experiment scaffold + D001 ADR | ✓ done | this directory + D001 |
| T1 — Spec doc (Archive-level)        | ✓ done | `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage-design.md` |
| T2 — Plan doc (Archive-level)        | ✓ done | `docs/superpowers/plans/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage.md` |
| T3 — Advisor review on design        | pending | run before T4 |
| **GATE — v2.8 F001 full-fixture smoke PASS** | **blocked** | budget approval + execute |
| T4 — `reviewer-prompt.md` edit       | ✓ done   | Spec Coverage Walk added (sub-steps A + B) |
| T4.5 — Cheap dry-run pilot (1 rep)   | ✓ done   | Guardrail PASS; failure mode shifted (miss → spec ambiguity). See [F001-T4.5](./findings/F001-T4.5-dry-run.md) |
| T5 — Re-run fixture 08 (3-4 reps)    | user-controlled | $20-40; recommendation = Path γ then α |
| T6 — Findings doc + recommendation   | blocked | gated by T5 |
| T7 — Release metadata / HISTORY      | blocked | only if T6 recommends ship |

### v2.8 F001 gate result

v2.8 F001 full-fixture smoke ran 2026-05-13 evening:
- **Smoke A** (fixture 01): PASS — clean lifecycle (init-run + close-run, meta.outcome=success).
- **Smoke B** (fixture 08): PARTIAL — implementation+rubric PASS, but the orchestrator skipped the helper invocation entirely (0 of 47 Bash calls referenced the helper). Adherence gap recorded; v2.9 falls back to inspecting `.harness/run.jsonl` directly for Reviewer output.

See [v2.8 F001-smoke.md](../v2.8-learning-log/findings/F001-smoke.md) for full details.

## Decisions index

- D001 — Why single-pass enumeration (not multi-perspective dispatch); evidence
  selection; v2.8 smoke as hard prerequisite — [link](./decisions/D001-initial-design.md)

## Findings index

- F001 — T4.5 dry-run pilot (1 rep). Walk mechanism PASSED; failure mode shifted from silent miss (F002) to spec-text ambiguity surfaced and reasoned through. [link](./findings/F001-T4.5-dry-run.md)
