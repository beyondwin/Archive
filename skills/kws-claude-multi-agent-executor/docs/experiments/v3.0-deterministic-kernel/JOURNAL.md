# JOURNAL — v3.0-deterministic-kernel

Chronological log. Update **as you go**, not at the end.

---

## 2026-07-06

### 14:30 — Task 1 kickoff: Kernel scaffold + atomic state I/O

Opening experiment record and beginning TDD implementation of kernel package skeleton and statefile.py atomic state layer. Plan: (1) create experiment dir structure with spec link, (2) write failing tests (test_roundtrip, test_atomic_no_partial, test_active_resolution), (3) implement statefile.py with fcntl-based exclusive locking and post-write verification, (4) scaffold kernel.py CLI with argparse subcommand routing, (5) verify all tests pass, (6) commit.

Expected outcome: kernel/statefile.py provides reliable JSON state persistence with atomicity guarantees. kernel.py provides CLI scaffold for later task implementation.

---

## On close-out

Add a final entry: outcome, what shipped, what didn't, what was learned.

---

### 18:20 — Task 6 review decisions (controller-recorded)

T6 (transitions.py) reviewed and Approved. Three design decisions surfaced by review,
recorded here (advisor: controller owns JOURNAL for these):

1. **`run_command.purpose` gains `"reset"`.** The brief listed purpose as `baseline|acceptance`,
   but the brief ALSO mandates a `pre_task_sha` reset directive on verifier FAIL. The kernel models
   that reset as `run_command{purpose:"reset", task_id, command}` — the natural synthesis of the two
   requirements. **T9 must handle purpose="reset"**, and T15's SKILL.md action table + the eventual
   ADR/interface doc must list it. Not a bug; a spec evolution.

2. **`transitions.apply_result` is the SOLE writer of `quality_trend` in v3.** CYCLE prose names
   `phase_boundary.py task-complete` as sole writer with "do NOT append by hand." In v3 the kernel
   REPLACES phase_boundary.py (deleted in T15). No double-append risk because the kernel path is not
   wired into SKILL.md until T15. **T15 must delete phase_boundary.py** so the two writers never coexist.

3. **Run-level escalation counter is T9's responsibility.** T6 increments only `task.escalations`.
   `phase-1-escalation.md` also mandates a run-level `current_escalation_count`. If T9's resume/cap
   logic needs it, T9 wires it. Recorded so it is not dropped.

Also: tightened test_spec_fault_budget_non_burning (Test 8) from an either-or assertion to assert
both `pending_escalation` and SKIPPED status — the either-or form could have masked a regression,
which is exactly the silent-green class this experiment targets.

### 19:10 — Cross-task fix during T9: reviewer score scale (0–10 → 0.0–1.0)

T9's implementer flagged a score-scale discrepancy. Traced it: the reviewer PROMPT
(references/reviewer-prompt.md) and the kernel tier thresholds (transitions.py: 0.85/0.75/0.70/0.60)
both use a 0.0–1.0 scale, but reviewer_result.schema.json's spec_score/quality_score DESCRIPTIONS
said "0–10". Since that schema is the --json-schema contract handed to the live reviewer subagent,
"0–10" could induce an 8.5-style emission that silently defeats the gate (8.5 ≥ 0.85 always PASS).
The stdlib validator does not enforce min/max, so the description is the only scale signal.
Fix (controller, mechanical): corrected both descriptions to "0.0–1.0 ... (PASS threshold 0.85/0.75)".
This is the writing-plans "types consistent across tasks" class — a T5 artifact bug surfaced only
when T9 wired the real cycle. Committed with T9.
