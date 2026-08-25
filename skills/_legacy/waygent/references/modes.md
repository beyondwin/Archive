# Waygent Modes

## run

Creates a durable run from a plan, latest plan, or topic query. The runtime
creates state, events, artifacts, and worktree data.

When the user invokes the Waygent skill for implementation work from a
design/plan pair, this mode is still the entry point. Host-level subagents are
not a substitute for the runtime run.

## status

Returns the last known status from the event journal and trust projection.

## events

Reads persisted `agentlens.event.v3` events for the selected run.

## inspect

Returns run state, task graph, safe wave, trust, failure, and apply state.

## explain

Summarizes the active failure barrier or reports that no barrier is active.

## resume

Returns the next allowed operator action from durable state.

## apply

Applies a verified checkpoint only when the source checkout is clean.
