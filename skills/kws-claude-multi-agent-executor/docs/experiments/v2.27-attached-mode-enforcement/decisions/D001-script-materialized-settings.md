# D001 — Script-materialized + deep-merged worktree settings.json

**Date**: 2026-06-06
**Status**: Decided

## Context

`readmates-host-prep-pace-20260606-003707` finished `interactive_attached` with
**no hooks** wired into `<worktree>/.claude/settings.json` — only ReadMates'
pre-existing `permissions.allow` allowlist + `$schema`. Phase 0 Step 2.5
(`phase-0-setup.md:141`) instructs the orchestrator to **hand-write** a settings.json
that contains *only* a `hooks` key. There is no merge step. When the source repo
ships its own settings.json, the hand-write either clobbers it or (as observed)
keeps the repo's keys and never adds hooks. Either way the four safety hooks —
including the v2.26 Stop finalization gate — never wired, so the degraded finish
went unblocked. This is the same prose-is-skippable shape v2.26 set out to fix, one
layer earlier: the gate that catches a bad finish was itself never installed.

## Options considered

- **A**: keep the prose hand-write, add a sentence "merge into any existing
  settings.json and assert the Stop hook." Rejected — the failure *is* prose
  drift; adding more prose to the same skippable step does not remove the failure
  mode, it just reduces its probability.
- **B**: deterministic script `materialize_worktree_hooks.py` that reads any
  existing settings.json, deep-merges the four hook events while preserving every
  other top-level key, atomic-writes, and self-asserts the Stop hook is wired
  (non-zero exit otherwise). A `--check` mode re-runs the assertion without writing,
  reusable as the Phase 1 Task-1 preflight (improvement #3). Tested with fixtures
  including the exact ReadMates shape.

## Decision

**B.** Matches the repo philosophy ("discipline lives in the runtime, not in the
loop") already applied to the hooks themselves. Phase 0 Step 2.5 prose collapses to
"run this script; non-zero = hard halt." One tested artifact covers improvement #1
(merge + assert) and #3 (preflight via `--check`).

Merge policy: `merged = {**existing}`; `merged["hooks"] = {**existing.get("hooks",
{}), **our_four_events}`. All non-hooks top-level keys (`permissions`, `$schema`,
anything) are preserved; the four events we own win over any repo-defined entry
under those keys (our safety hooks must run); any *other* hook event type the repo
defined is preserved.

## Consequences

- The run-2 failure class (repo-owned settings.json silently dropping our hooks) is
  eliminated and covered by a regression fixture.
- The settings.json shape stays documented in `safety-hooks.md` as the reference;
  the script emits exactly that, so there is one source of truth for the shape.
- Sub-worktree byte-identical copy (Parallel Sub-Flow P.1) is unchanged — it copies
  the already-materialized file.
- Advisory-blocking, consistent with the rest of the hook suite: a determined
  operator can still disable hooks. It is enforcement, not a hard lock.
