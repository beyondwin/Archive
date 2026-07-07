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

### T14 review — CORE FLOW GAP found: LOW batch verification never drained

T14's reviewer (release-gate focus) caught that lingering PENDING_BATCH finalizes green+passed.
Tracing it (advisor-guided) revealed a deeper gap spanning T6/T11/T14: the kernel NEVER drains
LOW-risk PENDING_BATCH tasks. Confirmed by trace:
- `compaction_points` is READ by transitions._compaction_due but WRITTEN by nothing (gate/init/transitions
  all lack a producer) → decide()'s compact path never fires.
- apply_result has no batch-verifier drain: reviewer sets LOW → PENDING_BATCH (transitions.py:369) but no
  path drives PENDING_BATCH → COMPLETE.
Net: LOW tasks route to PENDING_BATCH and decide() finalizes them UNVERIFIED. Phase-2-finalization.md
Step 0 mandates a LOW Batch Verifier Sweep before finalize; lingering PENDING_BATCH is an explicit HALT.
Decision (controller, advisor-endorsed): batch-drain-before-finalize MUST be a kernel-returned action
(deferring to prose SKILL.md would reintroduce the prose-decision the kernel exists to kill). Fix spans
transitions.decide (return batch-verify when only PENDING_BATCH remain, before finalize) + apply_result
(batch drain path) + quality.completion_audit (lingering PENDING_BATCH = blocks_release, symmetric with
SKIPPED) + the e2e (drive the drain — the hand-authored 2-task fixture skipped it, a keystone coverage hole).
Routed through implementer→reviewer (load-bearing). PENDING_BATCH stays terminal for the per-task cycle
(no global _all_tasks_terminal redefinition) — targeted guard only.

### T15 — CUTOVER: SKILL.md v3.0.0, Stop-hook switch, v2 script deletion

Two-commit structure (A wiring, B cleanup). Orientation surfaced findings that
made the brief's action inventory require correction (verified against decide()
`return` statements + kernel.py handlers, NOT the prose brief):

1. **decide() never returns `done`.** The docstring lists `{"action":"done"}` but
   no `return` produces it, and decide() does NOT check `status==FINALIZED` — so
   after finalize it re-emits `finalize`. SKILL.md loop-exit MUST be "finalize
   returned status=finalized" (or check-stop already_finalized), NOT "decide
   returned done". A "wait for done" prose loop would spin finalize forever.

2. **init→next assembly gap.** `kernel.py init` writes empty tasks/execution_plan/
   risk_levels/compaction_points/spec_manifest. decide() on that state halts
   (no_dispatchable_task). planparse/gate/packets are LIBRARY-ONLY (no CLI, called
   only by their own tests). There is NO kernel subcommand that runs plan→state
   assembly. Therefore a SETUP step (parse plan → assign_risk → partition_waves →
   build packets → write execution_plan/risk_levels/tasks/compaction_points into
   state.json) MUST run between init and the first `next`. phase-0-setup.md is KEPT
   (reduced) as the assembly guide — it is the producer decide() depends on.

3. **run_command purposes:** decide() emits only purpose="reset" (verifier-FAIL git
   reset). "baseline" and "acceptance" are NOT decide() outputs — baseline is a
   setup-time command; acceptance runs INSIDE the verifier dispatch (AC-shell
   guardrail). §3 table states this honestly rather than listing them as kernel
   actions.

4. **compaction_points has no kernel producer** (T14 JOURNAL confirms): decide()'s
   `compact` action only fires if the orchestrator wrote compaction_points during
   setup. Documented as a setup responsibility.

5. **Stop-hook stderr contract.** Claude Code surfaces stderr (not stdout) to the
   model on exit 2. kernel.py check-stop prints its reason JSON to stdout. Switching
   the Stop hook to call check-stop directly would block silently (no corrective
   guidance). Fix: kernel.py main() echoes the halt reason/next_action to STDERR on
   the exit-2 path (additive; no test asserts stderr empty). Preserves the wedge
   invariant WITH visible guidance.

6. **check_problems() lockstep.** materialize_worktree_hooks.check_problems() asserts
   the Stop command references "finalization-stop-gate.sh"; do_write() calls it and
   init() halts on failure. Switching build_hooks() to emit kernel.py check-stop
   REQUIRES updating check_problems()'s expected substring + the 3 test assertions
   in lockstep, else init self-assert fails.

Seams forward-wired per D001/brief: delegate_parallel (orchestrator launches
parallel -p waves at setup — NOT a decide() action), operator-review via
escalate_to_user, serialization_reason NOT wired (default delegate_serial — stated
honestly). phase_boundary.py MUST be deleted (kernel = sole quality_trend writer).
