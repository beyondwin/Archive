# JOURNAL — v2.9 Reviewer Spec-Coverage Walk

Chronological log. Update **as you go**.

---

## 2026-05-13

### Origin

After v2.8 shipped (learning log + review-side Skill calls), user asked for
an analysis of `oh-my-claudecode` (omc) for patterns to import. Initial
ranking produced a 7-item shortlist (A–G). User said "전부 다 적용하고 싶은데
상세 스팩문서 상세 구현문서 작성해줘" (apply all 7, write detailed spec +
implementation docs).

Pre-write advisor review flagged the ranking as reasoning-from-code rather
than evidence-measured. Only item C ("What's Missing" Reviewer walk) maps to
a documented KCMAE failure pattern (v2.7 F002, 75% Reviewer miss on
fixture 08 `30m20m`). The other six are speculative imports.

User chose **Path A**: discipline-first. Smoke v2.8 first, only C as v2.9,
re-rank the rest after the learning log produces real failure data.

### Scope locked

In scope for v2.9:
1. Single change to `references/reviewer-prompt.md` — Spec Coverage Walk
   enumeration step inserted before scoring.
2. Re-measurement on fixture 08 (3-4 reps) to confirm miss rate drops from
   ~75% to under 25%.

Out of scope:
- omc-style multi-perspective dispatch (Reviewer-Security / Reviewer-Correctness
  / Reviewer-DX) — deferred to v2.10 only if v2.9 underperforms.
- New event types (omc conflict-mailbox style) — deferred until learning log
  surfaces a matching failure mode.
- SKILL.md / sub-agent dispatch / helper script changes.

### Hard prerequisite recorded

v2.8 F001 full-fixture smoke must PASS before T4 (prompt edit) starts.
Reason: v2.9 measurement relies on v2.8 `reviewer_warn_or_fail` events as
the primary observability channel. If the helper invocations don't actually
fire under real `claude -p`, we lose cross-run event-level signal.

Backup measurement channel: rubric.py pass_rate, which already worked in
v2.7 F002 without any learning log. Acceptable fallback if F001 reveals
an integration gap; less informative but not blocking.

### Scaffold + D001 + spec + plan drafted

This directory created. D001 captures the single design decision (single-pass
enumeration vs multi-perspective dispatch) + evidence selection rationale.
Spec written to
`docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage-design.md`,
plan written to the sibling `plans/` path.

### Pre-advisor self-check caught a critical design flaw

Before calling advisor, walked fixture 08's spec excerpt manually against
the initial walk template. The fixture lists 5 explicit ValueError bullets
(empty / bare number / unknown unit / negative / decimal). `parse_duration("30m20m")`
is **not** an explicit bullet — it is covered only by the meta-rule
*"strict validation of the grammar."*

A faithful enumeration over stated bullets passes all 5 and never emits
a `30m20m` walk row. **Same miss as today.** Primary pass criterion
(rejection rate ≥75% on `30m20m`) would have been unreachable as drafted.

Patched:
- D001 §Question 3: rewrote from "strict template enumeration only" to
  "enumeration + adversarial generation from meta-rules" with two ordered
  sub-steps and an explicit class taxonomy (repeated-unit / ordering /
  casing / format-excluded).
- Spec §Design: added sub-step B with the same taxonomy; updated example
  output to show stated bullets + adversarial rows distinguished.
- Spec §Problem statement: precision pass — F002 directly measures the
  Implementer rubric miss; Reviewer-miss inference is one hop ("Implementer
  shipped bug ∧ Reviewer marked PASS ⇒ Reviewer missed it"). Recorded
  the hop explicitly in D001 §Evidence chain.
- Spec §Risks: replaced "walk produces false NOT FOUND" risk family with
  "Sonnet generates weak adversarial inputs"; added mitigation language.
- Plan T4 Step 2: rewrote to describe sub-steps A and B and reference D001.
- Plan §Branch: cut as child of `codex/executor-learning-log` (v2.8 not
  yet on main; cross-refs resolve on that branch).

Next: advisor review on the patched design + plan.
