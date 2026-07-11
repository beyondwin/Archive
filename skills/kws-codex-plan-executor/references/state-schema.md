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
created once. The compiler's plan/spec/docs internal input snapshots are hashed
before allocation; the manifest also indexes every immutable task packet by
task ID, run-relative path, media type, and `packet_sha256`. A changed manifest
is integrity drift, not an update.

## Events

Each event has a monotonic `seq`, unique `event_id`, UTC timestamp, runtime
actor, type, payload, optional task/attempt IDs, `previous_hash`, and `hash`.
The hash is SHA-256 over canonical event JSON without the `hash` field.

The active projector consumes run and task status, typed attempt and verdict,
worktree revision, blocker lifecycle, retry, evidence, context, completion,
and repair events. Historical `attempt.recorded` remains readable but is not a
writable event. Unknown or invalid transitions are not accepted as successful
state changes.

## Projection

`state.json` includes:

- `schema_version`, `run_id`, and run lifecycle;
- current task and projected task statuses;
- `worktree_revision` and `worktree_patch_sha256` for the current real delta;
- projected attempt summaries, verdicts, and evidence index;
- `active_blockers`, `blocker_history`, and the explicit `retry_queue`;
- context health, repairs, and completion audit when emitted;
- the last applied event sequence and hash.

Typed evidence for acceptance, task review, verification, repository check,
and final review records the task and attempt identity, `packet_sha256`,
`worktree_revision`, and `worktree_patch_sha256`. These records become stale
after any later product write. `completion_audit` is a candidate payload only
while validating the exact prospective `completion.recorded` transition; it
cannot replace authoritative replay state.

Blockers are projected by stable ID. Open and update events change both the
active record and its history record. Resolution removes the blocker from
`active_blockers` while retaining the resolved record and evidence in
`blocker_history`. A retry phase moves a blocked task to that phase's entry
state; blocked tasks do not have a generic transition back to ready.

No agent writes this file. The transition kernel replays the manifest and event
stream and atomically replaces the projection. Validation compares stored bytes
with a fresh projection.

## Evidence

Evidence refs are run-relative and content-addressed. A ref records kind, path,
digest, and media type. Absolute paths, parent traversal, symlinked ancestors,
missing or contradictory objects, and digest mismatches are integrity failures.
Patch evidence is immutable and must describe the measured current delta, not
a worker-reported file list.

## Compatibility

Only schema `3` participates in execution. A v2 marker yields
`unsupported_schema`; validation, reconciliation, repair, resume, and inspection
must not reinterpret or mutate that run.
