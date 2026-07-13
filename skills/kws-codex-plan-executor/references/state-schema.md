# Schema 4 State And Replay

## Run Root

A run owns private files beneath CODEX_HOME/orchestrator/RUN_ID:

| Path | Contract |
| --- | --- |
| run.json | immutable schema, run ID, workspace, status seed, document-set digest |
| inputs/ | immutable source snapshots and generation document sets |
| events.jsonl | authoritative canonical hash-chained transition stream |
| events.head.json | synced event count and terminal event hash |
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
SHA-256. Appending fsyncs events.jsonl before atomically replacing the head.
Replay validates both. A partial tail, head mismatch, altered payload, unknown
event, or broken previous hash fails closed.

## Artifacts And Publications

An artifact index record binds one normalized logical path to immutable regular
file bytes. Existing bytes may be reused only when their digest and length are
identical.

A program-map generation is published beneath:

    maps/GENERATION/attempts/PUBLICATION_SHA256/

Its accepted.json commits every logical artifact path, physical path, digest,
and length. Exactly one map.generation_created event selects an accepted
manifest and its program-map digest. Logical shadow files and unselected
attempts cannot replace event-selected state.

Event-selected publications and every physical artifact they reach are
permanent run evidence. For each generation, CPE retains one live unselected
Program Mapper attempt. Older complete or strict partial groups receive
append-only index tombstones, the index is fsynced, and only then are matching
files unlinked. On open, live tombstones reconcile stale bytes from an
interruption. A tombstoned path is unreadable. A partial group is eligible only
when every live path has the exact mapping-attempt namespace and valid indexed
bytes; any other identity fails closed.

## Replay

Replay validates the manifest, current generation document set, event chain,
autonomy ledger, indexed artifact parity, accepted publication, and terminal
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
