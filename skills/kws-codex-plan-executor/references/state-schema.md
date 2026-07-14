# Schema 4 State And Replay

## Run Root

A run owns private files beneath CODEX_HOME/orchestrator/RUN_ID:

| Path | Contract |
| --- | --- |
| run.json | immutable schema, run ID, workspace, status seed, document-set digest |
| inputs/ | immutable source snapshots and generation document sets |
| events.jsonl | authoritative canonical hash-chained transition stream |
| artifacts.jsonl | append-only logical path, SHA-256, and byte-length index |
| autonomy-decisions.jsonl | append-only structured technical choices |
| writer.lease | cross-process exclusive writer ownership |
| maps/ | document maps and content-addressed program publications |
| briefs/, reports/, reviews/ | role-scoped immutable evidence |
| verification/ | audit, whole-diff, integration, and terminal evidence |
| outbox/ | untrusted per-attempt staging, never authoritative |
| result.json | terminal artifact, absent before completion |

All managed files and directories use private permissions and reject symlinks.

## Events

The allowlisted events are run.created, documents.snapshotted,
map.generation_created, task.started, task.reported, review.reported,
autonomy.recorded, authority.opened, authority.resolved, run.interrupted,
audit.reported, integration.reported, run.completed, and run.failed.

Each event has a contiguous ID, strict payload, previous-event hash, and its own
SHA-256. Appending fsyncs events.jsonl. A partial tail, altered payload, unknown
event, or broken previous hash fails closed.

## Artifacts And Publications

An artifact index record binds one normalized logical path to immutable regular
file bytes. Existing bytes may be reused only when their digest and length are
identical.

A program-map generation installs its validated logical artifacts once, plus a
content-addressed bundle manifest that commits every path, digest, and length.
Exactly one map.generation_created event selects that bundle. Invalid or
interrupted mapper output remains disposable outbox data and is never replayed.

## Replay

Replay validates the manifest, current generation document set, event chain,
autonomy ledger, indexed artifacts, accepted mapping bundle, and terminal
artifact. It derives mapping, task, review, authority, audit, integration, and
run status without trusting a mutable projection.

Resume additionally verifies the isolated worktree identity and that every
recorded commit is an ancestor of its current head. Active writer handoffs are
reconciled from exact outbox/result/event evidence. Ambiguity fails closed; a
durably completed item is never redispatched.

## Input Refresh

Source paths are inert after snapshot. Explicit --refresh-inputs creates the
next generation with new snapshot hashes. Prior generations remain immutable.
Task identity, brief digest, governing document, and dependency closure
determine invalidation.

## Schema 3

A schema-3 root has run_manifest.json rather than run.json. CPE 4 inspect reads
only a bounded summary and does not modify timestamps, permissions, or bytes.
Resume is rejected. No schema conversion exists.
