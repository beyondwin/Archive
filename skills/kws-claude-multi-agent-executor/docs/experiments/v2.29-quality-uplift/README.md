# v2.29 quality-uplift (I1–I12)

**Status**: In progress
**Branch**: `v2.29-quality-uplift`
**Production baseline**: v2.28.0 (untouched on main)

## Goal

Implement the 12-item quality-improvement catalog from
`docs/improvements/품질개선-플랜-ko.md` + `품질개선-구현-ko.md`, grouped on three
axes: **A — orchestrator context reduction**, **B — autonomous problem
handling**, **C — post-run observability**. Success = all P0/P1/P2 items shipped
additively (no schema_version bump), evals + paired unit tests green, no
regression of the closed-issue invariants listed in the plan §2.1.

## Hypothesis

The remaining gaps (full-spec re-read, in-context slice/report derivation, last
Phase-1 hard stop on retry exhaustion, missing machine-readable run report +
decision trace + local event timeline) can be closed with additive helpers +
reference-doc precision edits, without increasing fan-out (plan §3.1) and without
disturbing the v2.26–v2.28 finalization/instrumentation guardrails.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — chronological log of work
- [decisions/](./decisions/) — ADRs per major decision
- [findings/](./findings/) — data and analysis

## Phase status

| Bundle | Items | Status | Notes |
|--------|-------|--------|-------|
| v2.29.0 (P0) | I1 I2 I3 | in progress | retry→SKIP, events.jsonl tee, retry_trace |
| v2.29.1 (P1) | I4 I5 I6 I7 | pending | report builder, context slice, partial re-read, failure_summary |
| v2.29.2 (P2) | I8 I9 I10 I11 I12 | pending | auto_resolved surfacing, forced verify, resume digest, compaction discipline, SDK record |

## Decisions index

- D001 — Defer native Agent SDK context-editing + memory tool (I12) — [link](./decisions/D001-agent-sdk-context-editing-deferred.md)

## Findings index

- F01 — close-out — [link](./findings/F01-close-out.md)
