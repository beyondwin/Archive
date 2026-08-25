# Phase Transition — v3.0 (kernel-owned)

> **v3.0 cutover.** The compaction/transition decision is no longer prose. The
> kernel emits `{"action":"compact","steps":["batch_verifier","docs_updater","anchor"]}`
> from `transitions.decide` when `last_completed_task` is a `compaction_points` entry
> not yet compacted. When the orchestrator receives that action it performs the three
> steps in order (batch-verify accumulated LOW tasks → update phase docs → anchor on
> state.json and drop raw task context), then loops back to `kernel.py next`.

**How to perform a `compact` action** (per `SKILL.md §④`):

1. **batch_verifier** — dispatch the Verifier over the LOW tasks accumulated since the
   last compaction (the kernel also drains PENDING_BATCH via its own batch-verify
   dispatch before finalize; this in-transition sweep keeps the LOW backlog bounded).
2. **docs_updater** — dispatch the Docs Updater over the phase's changed files.
3. **anchor** — treat state.json as authoritative and drop raw sub-agent output from
   context.

**Honest note on the producer:** `compaction_points` currently has **no kernel
producer** — `transitions.decide` reads it, but nothing in the kernel writes it. The
`compact` action therefore fires only if the SETUP step
([`phase-0-setup.md`](phase-0-setup.md)) wrote `compaction_points` into state. If your
plan needs mid-run compaction, SETUP must assign the boundary task ids.

The token-health / Resume Chain long-run handoff mechanics live in
[`phase-minus-1-args-and-spawn.md`](phase-minus-1-args-and-spawn.md).
