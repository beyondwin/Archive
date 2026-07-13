# Risks, Limitations, And Deferrals

## Mapper Omission

A model can omit or distort source material. Document maps retain exact
excerpts and hashes, program coverage rejects unmapped normative requirements,
task briefs are lossless, document auditors reread original snapshots, and the
final integrator sees all verdicts. These controls reduce but do not eliminate
semantic model error.

## Conflicting Authorities

CLI order never grants precedence. Explicit supersession or one offered user
answer is required. This can pause affected tasks even when an implementer has
a technically reasonable preference.

## Autonomous Technical Choices

Standing autonomy can choose the wrong reversible implementation. Decisions
are constrained by approved requirements, repository conventions, reversibility,
risk, testability, and maintenance cost; every material choice is durable
evidence and remains reviewable. Legal, security, policy, and material scope
authority remain user-owned.

## Persistent Recovery

There is no arbitrary product-failure attempt limit. A repeated material
failure must change investigator or strategy and preserve evidence. A genuine
runner-integrity contradiction fails closed. Long difficult programs can
therefore consume substantial local time and disk before reaching a terminal
state.

## Unselected Mapping Attempt Retention

Program-map publications are content-addressed and indexed before the
map.generation_created selection event. A crash followed by different valid
mapper bytes can leave multiple unselected attempts.

CPE 4.0.0 keeps exactly one live unselected Program Mapper attempt per logical
map generation, whether the attempt reached accepted.json or stopped after
writing a strict physical artifact path. Document Mapper outboxes are not
content-addressed attempts and are outside this policy. Every
map.generation_created manifest, every physical artifact it reaches, and all
non-mapping evidence are permanently protected.

Pruning validates all selected reachability first, appends strict artifact
index tombstones under the writer lock, fsyncs them, and only then unlinks
matching private files. Open recovery finishes a tombstone-before-unlink crash.
Tombstoned reads fail and a selected digest, identity, or reachability
ambiguity fails closed.

A partial group has no publication commitment yet, so retention permits only
strict maps/GENERATION/attempts/SHA/artifacts/{maps,briefs}/... paths whose
indexed bytes still validate. Any other identity is ambiguous and fails
closed. Operators must not manually remove indexed paths; remove an abandoned
run only as a whole after deciding it is no longer evidence.

## Schema 3

CPE 4 reads only a bounded schema-3 summary. It does not migrate or resume old
runs. Historical execution requires an explicit checkout of the pre-4.0 code;
the old run and worktree must remain untouched.

## Python Size

Python remains because child and Git latency dominate interpreter cost. The
4.0.0 runtime is split into the public CLI and eight focused runtime files, but
strict lossless mapping, crash-safe storage, recovery, process-group control,
and final-evidence validation remain substantial. Active line counts are
measured at release. The Task 7 review-fix count is 15,989 lines against the
directional 5,000-line target: 9,686 runtime lines and 6,303 eval lines.

| Active file | Lines | Necessary retained responsibility |
| --- | ---: | --- |
| scripts/cpe.py | 571 | four-command parsing, public result, authority and resume adapter |
| contracts.py | 2,085 | lossless map, brief, event, audit, terminal, and child validation |
| store.py | 2,277 | private snapshots, crash-safe append, tombstone retention, publication, replay |
| queue.py | 3,725 | mapping, dependency execution, recovery, audits, final integration |
| launcher.py | 680 | strict child boundary, writer lease, timeout and process-group cleanup |
| worktree.py | 207 | source identity, branch, commit and clean-handoff checks |
| legacy.py | 63 | bounded read-only schema-3 inspection |
| prompt_export.py | 77 | side-effect-free prompt and handoff rendering |
| __init__.py | 1 | package marker |
| six checks plus fake_codex.py | 6,303 | 124 semantic cases and deterministic child behavior |

The excess is an explicit maintenance risk. Task 7 removed more than 65,000
superseded lines and consolidated the repeated six-check Git fixture, but did
not compress formatting or remove semantic assertions merely to improve wc.
Further safe reduction needs its own behavior-preserving plan:

1. replace repeated map field validators in contracts.py with one declarative
   strict-record vocabulary while retaining exact error and cross-reference
   tests;
2. factor store.py event, autonomy-ledger, and artifact-index locked I/O into
   one crash-safe append/read transaction primitive with fault injection;
3. separate queue.py generation, task recovery, and final-evidence walkers
   behind pure state helpers, then prove replay parity before deleting the old
   paths;
4. extend the shared eval fixture with typed map/result builders so the 124
   cases keep their assertions without repeating payload construction.

Any later Bun proposal must demonstrate measured packaging, maintenance, or
latency benefit and implement only the lean queue contract. It may not port
deleted surfaces.

## Scope Limits

CPE 4 does not:

- optimize small-task execution;
- merge, push, deploy, publish, or send external messages without authority;
- modify installed Superpowers skills or Waygent;
- migrate schema-3 state;
- clean external worktrees;
- synthesize product quality beyond the terminal artifact.
