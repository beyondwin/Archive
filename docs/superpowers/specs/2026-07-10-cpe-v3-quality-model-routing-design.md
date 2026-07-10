# CPE v3 Quality And Model Routing Design

**Date:** 2026-07-10

**Status:** Approved design

**Scope:** `skills/kws-codex-plan-executor`

**Target release:** `3.0.0`

## Objective

Redesign KWS Codex Plan Executor (CPE) as a higher-quality, simpler, and more
observable independent Codex plan executor. Preserve its core execution,
validation, reconciliation, repair, resume, and inspection capabilities while
replacing the accumulated v2 state contract with a clean v3 contract.

The default model policy is quality-first:

- `gpt-5.6-sol` with reasoning effort `high` for coordination,
  implementation, review, verification judgment, repair, analysis, and
  completion decisions.
- `gpt-5.6-terra` with reasoning effort `high` only for explicitly bounded,
  read-only scout work that does not make implementation or quality verdicts.

This design follows the current OpenAI guidance that `gpt-5.6-sol` is the
flagship GPT-5.6 model, that reasoning effort should be measured rather than
increased blindly, and that GPT-5.6 prompt stacks should remove redundant
scaffolding while preserving outcomes, constraints, evidence, and completion
criteria:

- [Using GPT-5.6](https://developers.openai.com/api/docs/guides/latest-model)
- [Prompting guidance for GPT-5.6 Sol](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)

## Approved Decisions

1. CPE remains an independent plan executor. It does not become a Waygent
   wrapper and does not delegate its runtime ownership to Waygent.
2. CPE keeps worktree isolation, task packets, subagent execution, state
   validation, reconciliation, repair, resume, recent-run inspection, prompt,
   and handoff capabilities.
3. CPE v3 does not interpret, resume, repair, or migrate v2 run state beyond
   reading its schema marker. Existing v2 files are left untouched and reported
   only as `unsupported_schema`.
4. Core work uses Sol/high regardless of task difficulty. Terra/high is allowed
   only for bounded read-only scouting.
5. The Python implementation base is retained. This is a contract and module
   redesign, not a TypeScript runtime rewrite.
6. Write-capable tasks execute sequentially for quality and conflict control.
   Independent read-only Terra scouts may run in parallel.
7. A prompt claim is not model enforcement. CPE must request and attest the
   actual model and reasoning effort for every core attempt.
8. Static contract tests remain required, but the GPT-5.6 migration also needs
   representative live model comparisons before the 3.0.0 release is closed.

## Current Evidence

The current package is version 2.27.0 with additional unreleased changes. The
package contains roughly 17,000 lines across its skill contract, references,
Python runtime helpers, and deterministic evals. The current design has strong
safety coverage, but the audit found several concrete quality and maintenance
problems:

- `gpt-5.5 high` is primarily declared in the fresh-session prompt and prompt
  fixtures; a prompt declaration does not prove the executing agent actually
  used that model.
- The full deterministic eval command currently fails in this environment
  because `PyYAML` is imported without a declared or preflighted runtime
  dependency. The failure is initially silent because the harness exits before
  printing the failed check output.
- The live Superpowers compatibility audit fails against the installed
  Superpowers package even though the relevant capabilities are present. It
  checks exact English prose tokens instead of semantic or structural
  capabilities.
- The repository Graphify report was stale at audit time.
- The recent-run analyzer found 13 recent CPE states: 8 completion-passed runs,
  5 red report-class runs, 3 validation failures, and substantially more local
  fallback tasks than delegated tasks. This shows that deterministic fixture
  coverage alone does not guarantee consistent operational evidence.
- Completion, run-quality, follow-up, and inspection fields repeat related
  facts across multiple mutable surfaces, creating drift and interpretation
  risk.

These findings motivate a clean v3 state contract rather than another layer of
compatible optional v2 fields.

## Goals

- Improve final implementation and review quality with an enforceable
  Sol/high default.
- Keep Terra savings restricted to clearly non-judgmental read-only scouting.
- Make every run replayable, auditable, resumable, and repairable from durable
  filesystem artifacts.
- Reduce state-schema duplication and eliminate manually maintained derived
  quality fields.
- Make validation, reconciliation, repair, and inspection agree on one source
  of truth.
- Reduce unnecessary prompt and accumulated context without weakening safety
  or completion evidence.
- Make eval failures explain themselves and make dependencies reproducible.
- Measure task success, retries, tokens, caching, latency, and cost per
  successful task.

## Non-Goals

- Preserving or migrating CPE v2 state.
- Deleting existing v2 run directories.
- Replacing CPE with Waygent or making either runtime depend on the other.
- Rewriting CPE in TypeScript or Rust.
- Using Luna as a default route.
- Silently falling back to GPT-5.5, Terra, or another model when Sol is
  unavailable.
- Automatically installing dependencies or mutating operator environments
  during execution preflight.
- Treating lower token use, fewer tool calls, or lower latency as an
  improvement when final quality declines.

## Architecture

CPE v3 is organized into six layers:

```text
User request
  -> Invocation
  -> Deterministic Preflight
  -> Run Kernel
  -> Task Execution
  -> Verification / Recovery
  -> Inspection / Completion
```

### Invocation

Parse `plan`, `spec`, `docs`, mode, subagent policy, context policy, and model
policy into one structured invocation. Natural-language hints are resolved
after explicit arguments, conflicts are rejected, and this phase performs no
worktree or run-state mutation.

### Deterministic Preflight

Compile the plan, validate file claims and acceptance commands, inspect dirty
scope, verify environment and model capabilities, and probe the installed
Superpowers contract. Successful preflight produces immutable manifest inputs.
The Run Kernel then allocates the run ID and worktree and freezes the final
manifest before task execution.

When a spec is supplied, every executable task must map to explicit spec
sections. CPE v3 removes `full_spec_on_blocker`; missing task-to-spec mapping is
a fixable preflight blocker rather than a reason to inject the full spec.

### Run Kernel

The kernel exclusively owns worktree creation and durable state transitions.
Models and helper scripts cannot edit `state.json` directly. Every state change
passes through one transition API that appends an event and projects a new
snapshot.

### Task Execution

Compile plan tasks into bounded execution units with dependencies, file
claims, acceptance commands, model route, attempt history, and evidence
requirements. One write-capable task runs at a time. Independent read-only
scouts may run concurrently.

### Verification And Recovery

Product verification and executor-integrity verification are separate gates.
Reconciliation and repair are deterministic runtime operations, not free-form
model edits to state.

### Inspection And Completion

Inspection is a read-only projection. Completion is a state transition allowed
only after product evidence, model attestation, event integrity, snapshot
parity, diff scope, review, and required repository verification all pass.

## Runtime Layout And Sources Of Truth

```text
~/.codex/worktrees/<run_id>/
  # isolated repository worktree

~/.codex/orchestrator/<run_id>/
  run_manifest.json
  events.jsonl
  state.json
  artifacts/
    task-packets/
    evidence/
    prompts/
    reports/
```

The authority order is:

```text
plan/spec content and hashes
  -> immutable run manifest
  -> append-only event stream
  -> immutable evidence artifacts
  -> rebuildable state snapshot
  -> disposable inspection reports
```

`events.jsonl` is the authoritative run history. `state.json` is a snapshot for
fast resume and inspection. Each successful transition appends and syncs its
event before atomically replacing the projected snapshot. If the process stops
between those operations, replay rebuilds the snapshot.

Events use monotonically increasing sequence numbers and a hash chain. The
runtime rejects gaps, reordering, invalid predecessor hashes, and conflicting
event IDs.

## Component Boundaries

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Invocation Parser | Resolve paths, modes, and explicit options | Create run state |
| Plan Compiler | Produce task DAG and execution contracts | Execute tasks |
| Preflight Auditor | Inspect safety, environment, model, and method capability | Edit the repo |
| Event Store | Append ordered, hash-chained events | Interpret product success |
| State Projector | Replay events into current state | Invent missing evidence |
| Task Scheduler | Select dependency-ready work and enforce write locks | Bypass task contracts |
| Model Router | Enforce Sol core and Terra scout routes | Infer a cheaper route from task difficulty |
| Worker Controller | Launch, monitor, and capture structured attempts | Write state directly |
| Evidence Store | Persist immutable, hashed evidence | Store secrets or raw transcripts |
| Reconciler | Detect manifest, event, state, artifact, and git drift | Modify product files |
| Repair Planner | Plan and apply safe compensating events | Fabricate success |
| Inspector | Project current and recent run health | Mutate state |
| Completion Gate | Decide whether completion invariants pass | Downgrade blockers to advisories |

`SKILL.md` becomes a concise routing and invariant document. Detailed schemas,
mode contracts, and maintenance guidance live in focused references. Python
runtime code moves toward a real internal package with modules matching the
boundaries above instead of continuing to grow large top-level scripts.

## Data Model

### Immutable Run Manifest

The manifest contains data that must not change during a run:

```json
{
  "schema_version": "3",
  "run_id": "...",
  "mode": "interactive",
  "workspace_ref": "...",
  "execution_worktree_ref": "...",
  "plan": {"ref": "...", "sha256": "..."},
  "spec": {"ref": "...", "sha256": "..."},
  "model_policy": {
    "core": {"model": "gpt-5.6-sol", "reasoning": "high"},
    "scout": {"model": "gpt-5.6-terra", "reasoning": "high"},
    "silent_fallback": false
  },
  "plan_graph_hash": "...",
  "policy_hash": "...",
  "model_catalog_hash": "..."
}
```

A versioned `model-catalog.json` records supported model IDs, reasoning levels,
activation status, and pricing. The manifest pins its hash so cost calculations
remain reproducible after future catalog updates.

### Event Envelope

```json
{
  "seq": 42,
  "event_id": "...",
  "type": "task.verification_completed",
  "at": "...",
  "actor": "cpe-runtime",
  "task_id": "task_3",
  "attempt_id": "task_3.verify.1",
  "payload": {},
  "previous_hash": "...",
  "hash": "..."
}
```

Events reference evidence by relative path and digest. They do not contain raw
transcripts, secrets, absolute home paths, or long command output.

### Task And Attempt

A task owns:

- dependencies;
- allowed and forbidden file claims;
- acceptance commands;
- risk and operator-review markers;
- lifecycle state;
- model route;
- attempt IDs;
- changed files and evidence references;
- unresolved blockers.

Risk controls approval, isolation, and verification strength. It does not
select a lower model.

Each attempt records:

- kind: `scout`, `implement`, `review`, `verify`, `repair`, or `analysis`;
- requested model and reasoning;
- actual model and reasoning attestation;
- start and completion timestamps;
- outcome and failure category;
- input, output, reasoning, cache-read, and cache-write tokens;
- latency and reproducible cost;
- evidence references.

### State Snapshot

`state.json` contains projected current state:

- run and current-task lifecycle;
- task and attempt summaries;
- blockers and recovery state;
- last applied event sequence and hash;
- context health;
- completion audit;
- usage, cost, and latency aggregates;
- artifact-index summary.

Run-quality grades, recent-run classes, and recommendations are computed by the
Inspector. They are not independently authored mutable state fields.

## Run And Task State Machines

Run lifecycle:

```text
created -> ready -> running -> completed
                    |-> blocked
                    |-> failed
```

- `blocked` is resumable after an external condition or operator decision.
- `failed` means retry policy is exhausted or an invariant prevents safe
  continuation.
- `completed` requires both product and executor-integrity completion gates.

Task lifecycle:

```text
pending -> ready -> [scouting] -> implementing -> reviewing -> verifying -> completed
                                      |              |             |
                                      +---------- repairing <-------+
                                      |-> blocked
                                      |-> failed
```

Only the transition layer may move these states. Invalid jumps are rejected
before an event is appended.

## Superpowers Boundary

CPE owns scheduling, persistence, model execution, and evidence. Superpowers
owns development-method contracts such as approved design, current plan shape,
TDD, task review, and completion verification.

Compatibility is tested through:

- active registry path and package-version discovery;
- required skill presence;
- supported plan-header and task-brief structure;
- semantic fixtures for brainstorming approval, TDD, review, and verification
  gates;
- explicit capability results stored in preflight evidence.

CPE does not search for exact English prose such as a particular sentence from
an installed `SKILL.md`. An unknown or incompatible contract blocks execution;
CPE does not silently enter a legacy self-invented workflow.

## Execution Flow

```text
resolve invocation
  -> compile plan/spec
  -> read-only preflight
  -> verify model and environment capability
  -> allocate run ID and isolated worktree
  -> freeze manifest
  -> build task packets
  -> execute task loop
  -> run whole-diff final review
  -> reconcile durable state and git evidence
  -> validate completion
```

The task loop is:

```text
optional Terra scout
  -> Sol implementation
  -> independent Sol task review
  -> deterministic acceptance command
  -> Sol verification judgment
  -> Sol repair when needed
  -> fresh re-review and re-verification
```

Write-capable tasks run sequentially. Review findings may return to the same
implementer for a bounded correction, but a fresh Sol reviewer checks the
result. Verification failures use a fresh Sol repair agent with a bounded
evidence packet. After the initial implementation, at most two repair attempts
are allowed for the same root-cause key; a third required attempt blocks the
run.

All completed tasks are followed by a separate Sol whole-diff review to catch
cross-task regressions and missing requirements.

## Model Policy And Enforcement

### Sol Core

The following always request `gpt-5.6-sol` with `high` reasoning:

- main coordination;
- implementation;
- task and final review;
- verification interpretation;
- recovery and repair;
- root-cause analysis;
- completion decisions;
- final prompt and handoff validation.

### Terra Scout

Terra/high is allowed only when all of the following are true:

- attempt kind is `scout`;
- the tool and filesystem policy are read-only;
- there are no write claims;
- output is limited to `findings`, `evidence_refs`, and `missing_evidence`;
- the output schema has no implementation, review, verification, or completion
  verdict;
- uncertainty causes a handoff to Sol;
- Sol reopens critical sources before acting.

The old Spark scout route is removed from the v3 default and is not a
compatibility surface.

### Actual Model Control

Prompts do not control the executing model. CPE must use a host model-control
capability or an explicit provider command equivalent to:

```text
codex exec --model gpt-5.6-sol -c model_reasoning_effort="high"
```

Terra scouts use the corresponding explicit Terra/high configuration.

If an interactive session cannot prove that its coordinator is Sol/high, CPE
blocks before edits and returns a Sol/high relaunch command. Each core attempt
must record requested and actual model attestation. An unavailable model,
missing attestation, or mismatch blocks completion. There is no silent fallback
to GPT-5.5 or Terra.

## Context And Prompt Optimization

- Keep stable prefixes limited to durable safety, permission, model, evidence,
  and output contracts.
- Give workers the current task packet, not the full plan and spec.
- Require explicit task-to-spec mapping; remove automatic full-spec fallback.
- Carry previous decisions, changed files, and evidence references instead of
  raw conversation history.
- Compact at task boundaries, not after every turn.
- Bound scout output and make Sol reopen critical evidence.
- Remove redundant procedure, generic brevity, generic thoroughness, and
  repeated permission language.
- Preserve explicit outcomes, safety boundaries, acceptance commands, review
  requirements, and stopping rules.
- Deduplicate evidence artifacts by digest and load large evidence lazily in
  inspection.

The migration target is at least a 25% reduction in starting and accumulated
context tokens on identical representative tasks, measured only after required
quality and evidence gates pass.

## Error Handling

| Category | Example | Default action |
| --- | --- | --- |
| `preflight` | Invalid plan, file claim, or spec mapping | Block before edits |
| `model` | Sol unavailable or attestation mismatch | Block without downgrade |
| `environment` | Missing declared runtime dependency | Block with exact preparation guidance |
| `transient` | Temporary provider or process failure | Retry at most twice |
| `implementation` | Task contract not met | Sol correction and re-review |
| `verification` | Acceptance, build, or test failure | Sol repair and re-verification |
| `state_integrity` | Event, snapshot, or artifact mismatch | Stop and reconcile |
| `operator_review` | Security, migration, or unsafe command | Block for explicit decision |
| `policy_violation` | Source checkout edit or forbidden path change | Fail or block immediately |

Command observations use stable root-cause keys. CPE does not repeat the same
failing command while presenting each attempt as a new diagnosis.

## Reconciliation

Reconciliation performs these checks in order:

1. manifest and plan/spec hashes;
2. event sequence and hash chain;
3. replayed expected snapshot;
4. expected versus stored snapshot;
5. worktree identity, branch, HEAD, and dirty diff;
6. task file claims versus actual changes;
7. evidence existence and digest;
8. attempt terminal state and model attestation;
9. verification and completion evidence links.

Outcomes are `clean`, `repairable`, or `blocking_drift`.

## Repair

Repair always produces a dry-run plan first. Mutation requires explicit
`--apply` and a run ID. Safe repair is implemented as compensating events and
snapshot replay.

Allowed automatic repairs:

- rebuild a snapshot from valid events;
- regenerate derived indexes and reports;
- mark a provably dead stale attempt as interrupted;
- reconnect a hash-valid evidence artifact to its attempt;
- recommend cleanup for temporary artifacts.

Forbidden repairs:

- changing product files;
- fabricating test or review success;
- changing plan/spec hashes;
- inventing model attestation;
- changing a failed run to completed;
- overwriting a damaged event chain;
- deleting existing operator files or v2 run directories.

## Validation And Completion

The completion gate requires:

- valid manifest and event chain;
- snapshot replay parity;
- all required tasks completed;
- actual diff within file claims;
- Sol/high attestation for every core attempt;
- acceptance-command evidence;
- task review and whole-diff final review;
- no unresolved blocker or repair attempt;
- completion evidence referencing real artifact digests;
- required Graphify, build, test, render, or smoke evidence;
- no unexpected CPE mutation in the source checkout.

There is no yellow lifecycle. Non-blocking observability limitations may appear
as completion advisories. Missing model attestation, missing verification,
stale required Graphify evidence, or state drift are blockers.

## Inspection

Inspection is read-only and prioritizes:

- run and task progress;
- last successful phase and next action;
- requested and actual models;
- first-pass acceptance and repair count;
- token, cache, cost, and latency summaries;
- verification commands and evidence;
- blocker owner and resume condition;
- manifest, event, snapshot, artifact, and git integrity.

Recent-run reports show completion and block rates, first-pass success, average
repair attempts, attestation success, cost and latency per successful task,
environment-failure frequency, drift and repair frequency, and missing-evidence
frequency. V2 directories are counted only as `unsupported_schema`.

## Eval Strategy

### Deterministic Unit Evals

Cover invocation parsing, plan compilation, event hashes, state transitions,
snapshot replay, model routing, cost accounting, retry policy, reconciliation,
repair planning, and completion rules.

### Contract And Golden Evals

Cover current Superpowers plan shape, missing spec mapping, dirty scope, path
escape, export-only modes, Sol attempt output, Terra scout output, and parity
between validator, reconciler, and inspector.

### Process Integration Evals

Use temporary git repositories and a fake provider to exercise worktree
creation, task execution, review, verification, repair, event projection,
resume, inspect, and source-checkout isolation.

### Fault Injection

Test process interruption after event append, snapshot-write interruption,
snapshot corruption, event-chain corruption, missing evidence, model mismatch,
worker timeout, verification interruption, stale attempts, and missing
worktrees.

### Live Model Migration Matrix

Run representative plans through:

```text
GPT-5.5/high + current prompt
GPT-5.6-sol/high + current prompt
GPT-5.6-sol/high + v3 prompt
GPT-5.6-terra/high + scout-only prompt
```

Model-only and prompt changes are evaluated separately. Cases cover single-file
implementation, cross-package work, root-cause repair, defect review, failed
test interpretation, security or migration blocking, resume and state repair,
and large read-only exploration.

Measure task completion, first-pass success, review accuracy, evidence
completeness, repair attempts, post-completion regressions, tokens, cache use,
latency, cost per successful task, attestation, worktree isolation, and state
drift.

Quality gates precede efficiency comparisons:

- zero critical regressions;
- zero silent model fallback;
- zero completion without required evidence;
- zero out-of-scope product changes;
- 100% core model attestation;
- no task-success regression from the GPT-5.5 baseline.

Live model evals are opt-in during ordinary development because they need
credentials and budget. They are required evidence for closing the GPT-5.6
3.0.0 migration release.

## Dependency And Harness Reproducibility

- Add an explicit Python dependency manifest for the CPE package.
- Declare a compatible PyYAML version rather than relying on a machine-global
  import.
- Run dependency preflight before the eval suite.
- On failure, print the missing import, required version, and exact preparation
  command.
- Report each eval name, duration, status, and failure output.
- Emit a structured eval report for release evidence.
- Never hide the first failing command behind `set -e` and redirected output.
- Keep baseline updates explicit and reviewable.
- Do not update a baseline to hide an unexplained failure.

## Security And Privacy

- Use repo-relative or home-relative artifact references.
- Never persist secrets, raw transcripts, full prompts, or unbounded command
  logs in events.
- Redact provider output before writing diagnostic summaries.
- Validate all plan and artifact paths against their allowed roots.
- Treat external plan content, dependency documentation, and provider output as
  untrusted input.
- Require explicit operator review for destructive, security-sensitive,
  migration, release, or external-write commands.

## Release And Documentation Impact

This is a `3.0.0` major release because it replaces the run-state schema and
drops v2 read and resume compatibility.

Implementation must update the CPE package's:

- `SKILL.md` metadata and contract;
- `README.md` and `ARCHITECTURE.md`;
- model, mode, state, execution, reconciliation, repair, inspection, context,
  and eval references;
- prompt and handoff templates;
- operator and maintainer documentation;
- history, release notes, eval baseline, and verification log;
- Graphify output after structural changes.

The implementation plan must explicitly identify which v2 scripts and docs are
replaced, retained, or removed. Removal is based on superseded internal
implementation, not removal of validator, reconciliation, repair, resume, or
inspection capabilities.

## Acceptance Criteria

1. CPE remains an independent executor with all approved core capabilities.
2. CPE v3 reads only the v2 schema marker, rejects the state as
   `unsupported_schema`, and never rewrites it.
3. Manifest, hash-chained events, immutable evidence, and replayable snapshot
   form the documented and tested authority model.
4. Models cannot directly edit durable state.
5. Core roles use attested `gpt-5.6-sol/high`; Terra/high is confined to the
   read-only scout contract.
6. No core task completes with missing or mismatched model attestation.
7. Write-capable tasks are sequential; only independent read-only scouts may
   run concurrently.
8. Full-spec fallback is removed and missing task-to-spec mapping blocks before
   edits.
9. Validator, reconciler, repair planner, inspector, and completion gate agree
   on replayed state and evidence.
10. The eval harness reports missing dependencies and the first failing check
    clearly.
11. Deterministic, integration, fault-injection, and required live migration
    evidence pass before release closeout.
12. Sol v3 meets the GPT-5.5 task-success baseline with zero critical
    regressions and at least 25% context-token reduction on the accepted
    representative suite.
13. Prompt and handoff modes remain export-only and create no run artifacts.
14. Source checkout isolation and file-claim enforcement have zero accepted
    violations in the release suite.
15. Documentation, release metadata, verification evidence, and Graphify output
    match the shipped 3.0.0 contract.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Event sourcing adds implementation complexity | Keep a small event vocabulary, pure projector, replay tests, and atomic snapshot replacement |
| Sol is unavailable in an operator account | Block before edits and provide an explicit relaunch or capability action; never silently downgrade |
| Mandatory attestation is unavailable from a host | Treat the host as unsupported for core execution until a verifiable provider route is available |
| Sequential writes increase wall-clock time | Parallelize bounded Terra scouting and optimize context, caching, and evidence loading without parallel write risk |
| Prompt trimming removes useful behavior | Compare model-only and prompt-change treatments separately and restore only instructions tied to measured failures |
| Live eval cost grows | Use a bounded representative release suite with an explicit budget cap and keep routine CI deterministic |
| V2 users expect resume | Fail clearly as `unsupported_schema`, preserve files, and document that a new v3 run is required |
| Reconciliation repairs too much | Limit mutation to explicit safe compensating events and make dry-run the default |

## Implementation Planning Boundary

This document defines the approved design. It does not authorize implementation
before the user reviews the committed spec. After approval, the next workflow
is `superpowers:writing-plans`, which must produce a task-by-task implementation
plan with explicit files, RED/GREEN evidence, and acceptance commands.
