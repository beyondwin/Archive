# D001 — Defer native Agent SDK context-editing + memory tool (I12)

**Date**: 2026-06-07
**Status**: Decided (record-only — no code change this version)

## Context

Plan item I12 asks whether to adopt Anthropic's native **context-editing**
(auto-clears stale tool-results; reported ~84% token reduction over a 100-turn
eval) and the **file-based memory tool** (create/read/update/delete) to push axis-A
(orchestrator context reduction) further than the in-session edits in this release.

Both features are gated behind the API beta header
`context-management-2025-06-27`. This executor runs as a **Claude Code session**
(attached) or a detached `claude -p` subprocess — neither path lets the skill set
arbitrary API beta headers. So the native features are **not reachable in the
current execution form**.

## Options considered

- **A — Adopt now.** Not possible: the beta header cannot be enabled from the
  Claude Code / `claude -p` execution form. Would require porting the executor to
  a Claude Agent SDK app first.
- **B — Port to Agent SDK to unlock it.** Large, out-of-scope effort for a
  quality-uplift release; would also change the whole dispatch/worktree/state
  substrate. No demand pull yet.
- **C — Record the decision; ship the in-session equivalent (I11) now.** The I11
  compaction discipline (explicit keep_first pin of plan + `state_resume_digest`
  output, explicit drop of the prior task's tool-result blocks) is the in-session
  analogue of context-editing and needs no beta header.

## Decision

**Option C.** Do not adopt native context-editing / memory tool in v2.29. Capture
the trigger condition and the future adoption plan here; ship I11 as the near-term
equivalent. state.json already maps naturally onto the memory tool's external
memory model, so the future port is low-friction when it happens.

## Consequences

- No runtime change from I12 itself (record-only, per the plan).
- Near-term axis-A reduction is delivered by I4/I5/I6/I10/I11, not by the native
  API features.
- **Trigger to revisit:** a decision to port this executor to a Claude Agent SDK
  app. At that point adopt context-editing (stale tool-result auto-clear) and the
  file-based memory tool, mapping state.json onto external memory.

## Open questions

- Whether an Agent SDK port is desirable at all (separate, larger evaluation).
- Whether the in-session I11 discipline captures "enough" of the 84% figure to
  make the native port low-priority indefinitely.
