# CPE 4 Architecture

CPE 4 is a non-semantic, non-LLM queue around fresh bounded Codex roles. Its
purpose is durability across large Superpowers programs, not a second
implementation methodology.

## Ownership Boundary

| Owner | Responsibility |
| --- | --- |
| Public CLI | repeated inputs, run/resume/inspect/export, one JSON result |
| RunStore | private snapshots, immutable artifacts, hash-chained events, replay |
| Worktree | source identity, isolated branch, clean writer handoffs |
| ChildLauncher | fixed role request, sanitized environment, timeout, process group, outbox |
| QueueEngine | map generations, dependencies, writer serialization, recovery, final closure |
| contracts | strict structural validation without prose interpretation |
| Fresh Codex roles | mapping, product reasoning, TDD, review, investigation, fixes, audits, integration |

CPE validates IDs, schemas, digests, commits, paths, state transitions, and
process results. It does not infer natural-language requirements, judge product
quality, or retain a model conversation between queue items.

## Data Flow

    source specs/plans
      -> immutable snapshots
      -> one document mapper per snapshot
      -> one program mapper
      -> content-addressed accepted map publication
      -> durable dependency queue
      -> task agent -> reviewer -> optional investigator/fixer
      -> document auditors
      -> Program Final Integrator
      -> result.json

Each arrow crosses a file-backed contract. A child receives exact input paths,
one role, one item ID, one outbox, one result schema, and an owned worktree
view. The child exits after writing its compact result and detailed artifacts.

## Mapping

Document mappers are read-only and bounded to one immutable document plus
applicable repository instructions. Their output retains exact source excerpts,
headings, ranges, IDs, and hashes.

The program mapper consumes those small maps and emits a task graph, coverage
map, authority queue, and exact task briefs. Requirement dispositions are
planned, preexisting_verify, explicit_non_goal, approved_deferred, conflict, or
unmapped. Conflict and unmapped dispositions block affected execution.

A generation publishes all program artifacts as one content-addressed batch.
The publication manifest commits each logical path, digest, and byte length.
Only the publication named by exactly one map.generation_created event is
authoritative. Direct logical shadows cannot override it.

## Queue And Writers

QueueEngine replays events and the accepted publication to identify the first
ready nonterminal task. Dependencies and open authority items determine
readiness. A writer lifecycle combines an in-process lock with a private file
lock, so task, fix, and integration-fix roles cannot overlap.

A task agent starts at the current clean revision, follows applicable
Superpowers skills, runs focused checks, commits, writes a report, and returns
a compact result. CPE verifies the commit, parent, tracked cleanliness, and
artifact digests before appending task.reported.

The reviewer is read-only and receives the brief, report, exact diff, and
upstream evidence. Changes-requested findings go to one consolidated fixer,
then a fresh reviewer. Repeated material failure requires a new investigation
record and changed strategy; ordinary defects never become authority items.

## Authority

Standing autonomy covers safe reversible work within the approved documents
and workspace. A durable authority item is permitted only for:

- credential_required
- external_side_effect
- destructive_outside_worktree
- authoritative_document_conflict
- material_scope_expansion
- legal_security_policy_authority

The packet records affected tasks, exact options, recommendation, excerpts, and
evidence. Resolving it appends authority.resolved; neither the packet nor prior
events are rewritten.

## Final Closure

Each document auditor reads one original snapshot plus only its relevant maps,
briefs, reports, reviews, and diff slices. It checks lossless coverage rather
than repeating general code review.

The Program Final Integrator receives the program map, all auditor verdicts,
autonomy evidence, authority state, the whole diff, and the repository's final
verification command. It performs one full verification and returns the
terminal artifact at the exact revision. CPE independently checks that
artifact and publishes the launcher-owned integration handoff.

Any integration fix changes the revision and invalidates all affected audits,
verification evidence, and terminal records before the closure cycle repeats.

## Recovery And Integrity

RunStore appends canonical JSON events under a lock, fsyncs the stream, then
atomically replaces the event head. Replay derives lifecycle and task state
from the manifest, input set, and events; there is no mutable state projection
to trust.

Resume checks:

1. private regular-file and directory ownership;
2. manifest and document-set digests;
3. event IDs, previous hashes, payload contracts, and event head;
4. artifact index parity and immutable bytes;
5. event-selected map publication identity;
6. worktree source, branch, head ancestry, and cleanliness where required;
7. active child handoff evidence before deciding whether redispatch is safe.

A file-before-index interruption can be reconciled only when bytes and the
content-addressed publication commitment fully validate. An accepted child
result without its matching durable event is reconciled; completed durable work
is not launched again. Ambiguous or contradictory evidence fails closed.

Mapping retention protects every event-selected publication and its physical
artifacts forever. It keeps one unselected Program Mapper attempt per
generation, including strict partial pre-manifest groups. Older groups are
removed only after append-only tombstones are fsynced; open recovery completes
a tombstone-before-unlink interruption.

## Modules

- scripts/cpe.py: public command adapter
- contracts.py: schema and value validation
- store.py: snapshots, artifacts, events, replay
- worktree.py: Git ownership and handoff validation
- launcher.py: child boundary and writer lease
- queue.py: mapping, task/review/recovery/final lifecycle
- legacy.py: bounded read-only schema-3 inspection
- prompt_export.py: side-effect-free prompt and handoff rendering

Schema-3 execution remains in Git history. CPE 4 never rewrites or resumes
those run directories.
