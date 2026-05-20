Source-of-truth: the design document wins when this reference and code disagree.

# Context Policy

The runner stores snapshot metadata and packet hashes outside conversation context.

Host compaction and rotation are safe because replay state lives in SQLite and artifacts, not hidden chat state.

## Summary Mode

Use `agentrunway summarize --run <run_id> --json` as the default host view.
It reads local SQLite and bounded event tails, then returns task counts,
selected candidates, blocked tasks, worker durations, recent events, artifact
paths, AgentLens status, and the next operator action. This keeps the host
session from loading full prompts, complete event streams, or raw worker logs
unless a summary points to a specific failure.

`status` and `inspect` share the same SQLite fallback path when `run.json` is
missing. If AgentLens is disabled, local SQLite and artifacts remain
authoritative.

## Deep Inspect

Use `agentrunway inspect --run <run_id> --json` for targeted diagnosis after
summary mode identifies a blocked task, merge conflict, missing result, or
quality gate failure. Deep inspect may include full worker rows, merge queue
state, artifact graph coverage, quality decisions, and recovery actions.
