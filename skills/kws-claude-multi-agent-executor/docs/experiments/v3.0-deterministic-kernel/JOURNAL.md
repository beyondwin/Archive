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
