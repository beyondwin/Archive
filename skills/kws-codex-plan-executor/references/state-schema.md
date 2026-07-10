# V3 State Schema

The run directory contains four classes of artifact:

```text
run_manifest.json  immutable run inputs and hashes
events.jsonl       authoritative ordered history
state.json         rebuildable current-state projection
artifacts/         immutable evidence and derived reports
```

## Manifest

`schema_version` is exactly `"3"`. The manifest pins the run ID, mode,
workspace and execution-worktree refs, plan and optional spec hashes, task graph
and hash, fixed model policy and hash, and pricing snapshot and hash. It is
created once. A changed manifest is integrity drift, not an update.

## Events

Each event has a monotonic `seq`, unique `event_id`, UTC timestamp, runtime
actor, type, payload, optional task/attempt IDs, `previous_hash`, and `hash`.
The hash is SHA-256 over canonical event JSON without the `hash` field.

The active projector consumes run status, task status, attempt, evidence,
context, completion, and repair events. Unknown or invalid transitions are not
accepted as successful state changes.

## Projection

`state.json` includes:

- `schema_version`, `run_id`, and run lifecycle;
- current task and projected task statuses;
- projected attempt summaries and evidence index;
- blockers, context health, repairs, and completion audit when emitted;
- the last applied event sequence and hash.

No agent writes this file. The transition kernel replays the manifest and event
stream and atomically replaces the projection. Validation compares stored bytes
with a fresh projection.

## Evidence

Evidence refs are run-relative and content-addressed. A ref records kind, path,
digest, and media type. Absolute paths, parent traversal, missing objects, and
digest mismatches are integrity failures.

## Compatibility

Only schema `3` participates in execution. A v2 marker yields
`unsupported_schema`; validation, reconciliation, repair, resume, and inspection
must not reinterpret or mutate that run.
