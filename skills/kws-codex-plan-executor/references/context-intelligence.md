# Context Intelligence

Context intelligence keeps the active Codex session focused on the current unit
of work. State remains authoritative; raw prior task output is disposable after
compaction points.

## Artifacts

- `context.json`: run-level source snapshot and budget summary.
- `spec_manifest.json`: spec section ids, ranges, sizes, and hashes.
- `task_packets/task_<N>.json`: compact per-task execution context.
- `DECISIONS.md`: human-readable projection of `state.decisions_register`.

## Required Flow

1. Parse invocation args and echo resolved values.
2. Parse plan.
3. Build `spec_manifest` when `spec=` is present.
4. Compute `task_to_sections`.
5. Build one task packet before each task contract.
6. Execute only from the active task packet plus declared files.
7. Append decisions discovered during the task.
8. At compaction points, write state, render `DECISIONS.md`, and drop raw prior
   task context from active reasoning.

## Spec Mapping

Explicit `**Spec Refs:**` entries win. Unknown section ids are blockers.
When no explicit refs exist, map from task files to section titles using
case-insensitive path-component matching. If no section matches, set
`fallback_used=true` and include the full spec for that task packet.

## Compaction

After a compaction point, future work may use:

- `state.tasks`
- `state.task_summaries`
- `state.decisions_register`
- `DECISIONS.md`
- changed files on disk

Future work must not rely on raw subagent output or raw previous task prompts
remaining in the active conversation.
