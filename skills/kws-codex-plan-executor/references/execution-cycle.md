# Execution Cycle

## 1. Snapshot

Run validates a clean Git workspace, creates a private run root and isolated
worktree, copies every declared document, and records stable IDs, roles, byte
lengths, and SHA-256 digests before a child starts.

## 2. Document Mapping

One fresh read-only mapper receives one snapshot and applicable repository
instructions. It emits exact excerpts and references, requirements, task
candidates, constraints, decisions, and conflicts. Its outbox is validated and
ingested before the next state transition.

## 3. Program Mapping

One fresh mapper composes document maps into:

- a global task and dependency graph;
- exact lossless task briefs;
- requirement dispositions and coverage;
- shared-file and interface hotspots;
- an authority queue.

The validated artifact set is published as one content-addressed batch. A
single map.generation_created event selects it.

## 4. Task And Review

The queue selects the first dependency-ready, authority-free task. One task
agent follows Superpowers TDD, runs focused checks, creates one clean commit,
and writes a report. One fresh read-only reviewer checks the exact brief,
report, upstream evidence, and diff.

A clean review closes the task. Findings go to one consolidated fix agent and a
fresh reviewer. Repeated material failure records a fresh investigation and
changed recovery strategy. Only one writer may run at a time.

## 5. Authority And Resume

A genuine authority item blocks only affected tasks. Independent ready work may
continue. Resume can append one offered answer, explicitly refresh inputs into
a new generation, or continue from existing durable state.

Before launch, resume validates the manifest, events, artifacts, selected
publication, worktree, commits, and any active handoff. Completed queue items
are not redispatched.

## 6. Document Audits

At the final revision, one fresh auditor per source document receives that
snapshot plus only relevant maps, briefs, reports, reviews, and diff slices.
Auditors check coverage and exact constraints, not general code quality.

## 7. Final Integration

The Program Final Integrator receives the program and coverage maps, auditor
verdicts, autonomy ledger, authority state, whole diff, and final verification
command. It reviews integration and executes the full verification once.

A clean current-revision result produces the launcher-owned handoff and
result.json. An integration finding launches one consolidated writer; the new
revision invalidates audits and verification before closure repeats.
