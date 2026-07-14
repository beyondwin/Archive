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

## Mapping Publication Boundary

Program Mapper output remains in a private attempt outbox until the complete
program map, coverage, authority queue, and every brief validate together.
Only then are their logical paths installed immutably and committed by one
content-addressed bundle plus map.generation_created event. This intentionally
has no attempt-retention, tombstone, or garbage-collection subsystem. A run
root may be removed only as one operator-owned unit after it is no longer
needed as evidence.

## Schema 3

CPE 4 reads only a bounded schema-3 summary. It does not migrate or resume old
runs. Historical execution requires an explicit checkout of the pre-4.0 code;
the old run and worktree must remain untouched.

## Python Size

Python remains because child and Git latency dominate interpreter cost. The
4.0.0 runtime is the public CLI plus eight focused runtime files. The final
lean pass measures 6,290 runtime lines and 2,035 eval/runner lines.

| Active file | Lines | Necessary retained responsibility |
| --- | ---: | --- |
| scripts/cpe.py | 571 | four-command parsing, public result, authority and resume adapter |
| contracts.py | 2,071 | lossless map, brief, event, audit, terminal, and child validation |
| store.py | 925 | private snapshots, immutable artifacts, hash-chain, replay |
| queue.py | 1,695 | mapping, dependency execution, recovery, audits, final integration |
| launcher.py | 680 | strict child boundary, writer lease, timeout and process-group cleanup |
| worktree.py | 207 | source identity, branch, commit and clean-handoff checks |
| legacy.py | 63 | bounded read-only schema-3 inspection |
| prompt_export.py | 77 | side-effect-free prompt and handoff rendering |
| __init__.py | 1 | package marker |
| six checks plus fake_codex.py and run.sh | 2,035 | 19 high-signal scenarios and deterministic child behavior |

The runtime is below the approved 6,500-line ceiling but remains above the
directional 5,000-line aspiration because strict map and terminal validation,
bounded process cleanup, refresh, and schema-3 inspection remain explicit.
Do not reintroduce concurrency or speculative filesystem policy to reduce
wall time.

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
