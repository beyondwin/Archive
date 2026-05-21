# Waygent Runtime V1 Operational Maturity Design

## Goal

Waygent v1 must become a practical local agent execution runtime that can be
used where the KWS executor skills are used today, while remaining a Waygent
product runtime rather than a wrapper around those skills.

The target is stronger than the current runtime parity slice:

- real Codex and Claude execution through a common provider contract;
- isolated git worktrees with durable state outside the source checkout;
- task-packet dispatch instead of whole-plan context dumping;
- implement, review, fix, verify, resume, and apply loops owned by Waygent;
- full run replay through AgentLens projections, API, console, and eval
  harnesses;
- explicit maturity gates that prove Waygent can dogfood itself.

The design is intentionally broad. Implementation can be phased, but each phase
must be a piece of the final runtime rather than a throwaway MVP.

## Research Basis

This design is based on four sources of evidence:

1. Current Waygent code:
   - `packages/orchestrator/src/orchestrator.ts`
   - `packages/orchestrator/src/runState.ts`
   - `packages/provider-adapters/src/processAdapters.ts`
   - `packages/runway-control/src/scheduler.ts`
   - `packages/kernel-client/src/worktreeClient.ts`
   - `native/kernel/crates/*`
   - `apps/cli`, `apps/api`, `apps/console`
2. KWS executor skill contracts:
   - `skills/kws-codex-plan-executor/SKILL.md`
   - `skills/kws-codex-plan-executor/references/*`
   - `skills/kws-codex-plan-executor/scripts/*`
   - `skills/kws-codex-plan-executor/evals/*`
   - `skills/kws-claude-multi-agent-executor/SKILL.md`
   - `skills/kws-claude-multi-agent-executor/evals/*`
3. Local harness and eval patterns:
   - contract fixture validation across TypeScript and Rust;
   - AgentLens deterministic replay tests;
   - KWS Codex isolated fixture harness;
   - KWS Claude rubric, cost, time, and baseline gates.
4. External agent runtime patterns:
   - OpenAI Agents: manager-owned agents-as-tools vs ownership handoffs;
   - OpenAI Agents guardrails, approvals, resumable state, and trace evals;
   - Codex non-interactive `codex exec` and resume;
   - Claude Code headless execution, subagents, hooks, permissions, and
     sessions;
   - Harness-style CLI normalization into a unified event stream;
   - OpenHands-style separation of harness, runtime environment, and control
     plane.

## Product Boundary

Waygent is split into three layers.

### 1. Control Plane

The control plane owns durable truth:

- run identity;
- lifecycle state;
- task graph and safe-wave scheduling;
- provider attempts;
- review and verification decisions;
- recovery and resume decisions;
- apply authorization;
- completion audit;
- AgentLens-compatible events.

The control plane lives mainly in:

- `apps/cli`
- `packages/orchestrator`
- `packages/runway-control`
- `packages/lens-store`
- `packages/lens-projectors`
- `apps/api`
- `apps/console`

### 2. Harness Layer

The harness layer wraps native coding agents as bounded provider processes.
It must normalize different provider outputs into a common stream and result
surface.

Initial providers:

- Codex: `codex exec` plus `codex exec resume` where available;
- Claude: `claude -p --output-format json|stream-json`, with an optional
  future Claude Agent SDK adapter behind the same provider contract;
- fake: deterministic offline provider for local and CI verification.

Possible later providers, such as OpenCode, Cursor, or a unified external
harness CLI, can be added only if they emit the same Waygent provider event and
worker-result contracts.

### 3. Runtime Environment

The runtime environment is where code changes and verification happen:

- one Waygent-owned worktree per run or per task group;
- artifacts under the Waygent run root, not inside the source checkout;
- provider cwd fixed to the isolated worktree;
- process supervision through the Rust kernel boundary;
- checkpoint commits or sealed diffs for verified candidates;
- cleanup and orphan detection for abandoned worktrees.

## Non-Goals

- Do not call `skills/kws-codex-plan-executor` or
  `skills/kws-claude-multi-agent-executor` from Waygent.
- Do not preserve KWS internal state schemas as Waygent schemas.
- Do not reintroduce active `kws-cpe.*`, `kws-cme.*`, or old orchestrator
  namespaces.
- Do not build remote multi-user SaaS orchestration in v1.
- Do not add cloud queues or distributed workers in v1.
- Do not make AgentLens mutate Waygent execution state.
- Do not treat provider claims as verification.

## Design Principles

### Waygent Owns The Final Decision

Codex, Claude, and future agents are bounded workers. They can implement,
review, summarize, or propose fixes. They do not decide that a task is
verified, applied, or complete. Waygent does.

This follows the manager-owned "agent as tool" pattern rather than full
handoff. Handoffs are useful when a specialist should own a user-facing branch,
but Waygent is a coding runtime where the control plane must remain accountable
for safety, state, and final status.

### State Is Authoritative, Events Are Replay Evidence

`waygent.run_state.v2` is the source of truth for status, resume, and apply.
Events are append-only replay evidence used by AgentLens, API, console, and
debugging.

If state and events drift, the run is not finished until reconciliation passes
or a repair-safe path records what was repaired.

### Verification Is External To The Provider

A provider can say "I changed the files" or "tests pass", but that is evidence
only. Waygent must run the configured verification commands through the kernel
process boundary and record exit codes, output digests, timeouts, and changed
files.

### Parallelism Is A Scheduler Permission

Parallel execution is allowed only for scheduler-approved safe waves. File
claim conflicts, high-risk tasks, missing dependency checkpoints, stale
activity, terminal failures, and missing resume handlers are hard barriers.

### Apply Is An Explicit Product Action

No provider can apply directly to the source checkout. `waygent apply` may
apply only a verified checkpoint, only from a clean source checkout, and only
after post-apply verification passes or a blocked state is recorded.

## Current Gap Analysis

The current parity implementation has the right product surfaces but not enough
operational maturity:

- `runWaygent` creates events and state, but still acts like a slice runner. It
  removes the run directory at start, dispatches a safe wave once, creates
  kernel success evidence without executing the command, and marks tasks
  verified on the happy path.
- `WaygentRunState` is too small. It lacks context snapshots, task packets,
  provider attempt ledgers, review records, verification artifacts, retry
  history, dirty checkout classification, and state reconciliation.
- Provider adapters normalize JSON, JSONL, fenced JSON, crashes, missing
  executables, and malformed output, but prompts do not yet carry task-packet
  contracts, write scopes, acceptance criteria, or recovery context.
- The scheduler has file-claim, dependency, checkpoint, stale activity, and
  failure barrier primitives, but the runtime does not yet loop through waves
  until the graph reaches a terminal state.
- `applyRun` blocks dirty source checkouts, but does not yet materialize a
  verified checkpoint into the source checkout.
- API and console can inspect real run roots, but console rendering is still
  demo-snapshot centered and not yet a live control surface.
- `skills/waygent/evals` checks the skill contract only; there is no
  Waygent-native scenario harness comparable to KWS fixtures.

## Target Runtime Flow

`waygent run` follows this lifecycle:

1. Parse and echo invocation deterministically.
2. Resolve `--plan`, `--spec`, `--latest`, or `--topic`.
3. Detect active runs for the same plan and require explicit resume/new-run
   choice if ambiguous.
4. Classify source checkout dirtiness as clean, dirty-related, or
   dirty-unrelated against the plan file claims.
5. Create `run_id`, run root, artifact root, and Waygent-owned worktree.
6. Write initial `waygent.run_state.v2`.
7. Build context snapshot, spec manifest, decisions register, and task packets.
8. Parse tasks into a graph with file claims, dependencies, risk, and
   verification commands.
9. Compute the first safe wave.
10. For each safe-wave task, execute the task lifecycle:
    - build task execution contract;
    - dispatch implement pass;
    - collect diff and changed files;
    - run verification;
    - run review when required;
    - run fix pass when allowed;
    - seal checkpoint when verified;
    - block with decision packet when not recoverable.
11. Recompute safe waves until all tasks are verified, blocked, failed, or
    withheld by a terminal barrier.
12. Reconcile state and artifacts.
13. Write completion audit.
14. End as `completed`, `blocked`, or `failed`.
15. Wait for explicit `waygent apply` before source checkout mutation.

## State Model

`waygent.run_state.v2` should be introduced as an additive schema. Existing
v1 run readers can continue reading the old fields, but v2-capable commands
must prefer the v2 structure.

Core fields:

```json
{
  "schema": "waygent.run_state.v2",
  "run_id": "string",
  "workspace": "string",
  "source_branch": "string|null",
  "worktree_root": "string",
  "run_root": "string",
  "artifact_root": "string",
  "state_path": "string",
  "event_journal_path": "string",
  "plan_path": "string|null",
  "spec_path": "string|null",
  "provider_profile": {},
  "status": "initializing|running|blocked|failed|completed|applying|applied",
  "lifecycle_outcome": "finished|blocked|failed|aborted|null",
  "current_phase": "preflight|dispatch|review|verify|recover|apply|complete",
  "tasks": {},
  "safe_waves": [],
  "provider_attempts": [],
  "reviews": [],
  "verification": [],
  "recovery": [],
  "apply": {},
  "context": {},
  "drift": {},
  "completion_audit": null,
  "timestamps": {}
}
```

Task records:

```json
{
  "id": "task_a",
  "status": "pending|ready|running|needs_fix|verified|blocked|failed|applied",
  "risk": "low|medium|high",
  "dependencies": [],
  "file_claims": [],
  "attempts": [],
  "task_packet_path": "string",
  "task_packet_sha256": "string",
  "unit_manifest": {},
  "checkpoint_refs": [],
  "latest_failure_class": "string|null",
  "decision_packet_ref": "string|null",
  "timing": {}
}
```

Provider attempt records:

```json
{
  "attempt_id": "run_task_attempt_1",
  "task_id": "task_a",
  "role": "implement|review|fix|verify_assist",
  "provider": "codex|claude|fake",
  "command": ["codex", "exec", "--json", "-"],
  "cwd": "worktree path",
  "stdin_ref": "artifact path",
  "stdout_ref": "artifact path",
  "stderr_ref": "artifact path",
  "event_stream_ref": "artifact path|null",
  "exit_code": 0,
  "timed_out": false,
  "started_at": "iso8601",
  "completed_at": "iso8601",
  "worker_result_ref": "artifact path",
  "failure_class": "string|null"
}
```

Verification records:

```json
{
  "verification_id": "verify_task_a_1",
  "task_id": "task_a",
  "command": "bun test ...",
  "cwd": "worktree path",
  "kernel_result_ref": "artifact path",
  "exit_code": 0,
  "timed_out": false,
  "stdout_sha256": "string",
  "stderr_sha256": "string",
  "status": "passed|failed|skipped|blocked"
}
```

Completion audit:

```json
{
  "status": "passed|failed",
  "required_checks": [],
  "verification_evidence": [],
  "review_evidence": [],
  "state_reconciliation": {},
  "prompt_to_artifact_checklist": [],
  "residual_risk": []
}
```

## Task Packets

Every provider run receives a task packet. The provider prompt can summarize
the task, but the packet is the authoritative machine-readable contract.

Packet contents:

- task id and title;
- exact plan excerpt;
- spec section excerpts or full-spec fallback flag;
- file claims;
- allowed write globs;
- forbidden write globs;
- dependencies and checkpoint inputs;
- acceptance commands;
- verification commands;
- risk level;
- provider role;
- previous review findings;
- previous verification failures;
- relevant decisions register entries;
- context budget and truncation status.

Provider prompts must state:

- do not write AgentLens events;
- do not apply to the source checkout;
- edit only the isolated worktree;
- obey allowed and forbidden write scopes;
- return structured JSON or JSONL matching the role contract;
- include changed files and evidence;
- do not spawn nested agent CLIs unless the task packet explicitly permits it.

## Provider Roles

### Implement

The provider edits the isolated worktree. It returns `WorkerResult` plus
optional richer artifacts:

- summary;
- changed files;
- commands it ran;
- self-reported evidence;
- risk notes;
- whether it believes review is required.

Waygent then computes the real diff and changed files itself.

### Review

The reviewer receives:

- task packet;
- diff;
- changed files;
- verification evidence;
- relevant prior findings.

It returns:

- `pass|needs_fix|reject`;
- spec coverage findings;
- code quality findings;
- file and line references when possible;
- residual risk.

Review is mandatory for:

- high-risk tasks;
- tasks touching shared core;
- tasks with broad file claims;
- tasks where verification passed but changed files exceed claims;
- repeated fix attempts;
- operator-configured review policies.

Low-risk tasks can skip review only when verification passes, changed files are
within claims, and policy allows it.

### Fix

Fix pass is a bounded implement pass. It receives only the failed findings and
the original task packet. It cannot expand write scope without creating a
decision packet.

### Verify Assist

A provider may help diagnose failing verification, but the actual pass/fail
decision remains the kernel execution result plus Waygent policy.

## Provider Adapter Strategy

### Codex

Default command:

```bash
codex exec --json -
```

The adapter must support:

- non-interactive prompt over stdin;
- JSON or JSONL output;
- session id capture when available;
- `codex exec resume` for provider-native continuation when useful;
- timeout, crash, malformed output, and missing executable classification;
- raw output artifact preservation.

### Claude

Default command:

```bash
claude -p --output-format json
```

The adapter should also support stream-json mode because Claude Code exposes
useful event-level information for hooks, subagents, permissions, and tool
execution. A future Claude Agent SDK adapter is allowed only if it emits the
same provider event stream and result contracts.

### Unified Harness Adapter

Waygent should allow an optional harness adapter that wraps Codex, Claude,
OpenCode, Cursor, or similar CLIs behind a single NDJSON event stream. This is
not a replacement for Codex and Claude adapters; it is an adapter family for
environments where unified CLI execution is more stable than provider-specific
parsing.

## Scheduling And Parallelism

The scheduler is the only component allowed to release tasks.

Safe-wave rules:

- dependency checkpoint required for dependent tasks;
- overlapping owned file claims cannot run together;
- high-risk tasks serialize;
- stale activity blocks dispatch;
- terminal failure classes block dispatch;
- missing resume handlers block dispatch;
- dirty related source checkout blocks new run by default;
- dirty unrelated source checkout can continue only if outside all file claims.

After each task attempt, Waygent recomputes the projection. It does not assume
that the original safe wave remains safe after files change or failures occur.

## Verification

Verification uses `native/kernel/crates/process-supervisor` through a
TypeScript client.

Required behavior:

- run every configured verification command unless policy marks it as an
  honest substitute;
- record cwd, argv, env redaction, timeout, exit code, signal, stdout/stderr
  digests, truncation flags, and duration;
- preserve bounded stdout/stderr excerpts for operator display;
- classify failures into stable failure classes;
- support environment-blocker triage without burning infinite retries;
- never mark a task verified from provider output alone.

Verification classes:

- `passed`
- `verification_failed`
- `timeout`
- `permission_denied`
- `service_unreachable`
- `dependency_missing`
- `environment_blocker`
- `flaky_unconfirmed`
- `command_not_found`

## Recovery And Resume

Recovery is state-driven. It is not a new natural-language prompt over the
whole run.

Each blocked or failed task records:

- failure class;
- evidence refs;
- retry count;
- max retry policy;
- allowed actions;
- blocked actions;
- recommended next action;
- whether a provider-native session can be resumed;
- whether a Waygent task-level retry is safe.

Allowed actions:

- `retry_same_provider`
- `retry_switch_provider`
- `fix_from_review`
- `rerun_verification`
- `update_plan`
- `split_task`
- `mark_terminal`
- `human_decision`

`waygent resume --last` may execute only the unambiguous safe action. If more
than one action is plausible, it returns a decision packet and stops.

Resume must re-read state from disk, validate artifact existence, check the
worktree still exists, check source checkout dirtiness, and reconcile state
before dispatch.

## Apply

Apply is a separate command:

```bash
waygent apply --run <run_id>
```

Apply prerequisites:

- source checkout is clean;
- run has `completion_audit.status=passed`;
- target task or run has a verified checkpoint;
- checkpoint changed files are inside accepted file claims or explicitly
  approved expanded claims;
- no unresolved blocking drift;
- no pending human review decision;
- post-apply verification command is known or an honest substitute is recorded.

Apply flow:

1. Read v2 state.
2. Reconcile state and artifacts.
3. Check source checkout cleanliness.
4. Dry-run patch or merge.
5. Reject path escapes and unexpected files.
6. Apply the checkpoint.
7. Run post-apply verification.
8. Emit `runway.apply_completed` only after success.
9. If apply fails, emit `runway.apply_blocked` or `runway.apply_failed` and
   leave enough evidence for rollback or manual repair.

## AgentLens, API, And Console

AgentLens remains downstream.

Waygent emits canonical events:

- `platform.*` for run lifecycle;
- `runway.*` for plan, schedule, provider, review, verification, recovery, and
  apply;
- `kernel.*` for process and worktree evidence;
- `lens.*` for projection updates.

API and console must read v2 state and events together.

Required API additions:

- run state v2 detail;
- task packet metadata;
- provider attempt list;
- verification evidence;
- review findings;
- decision packets;
- drift/reconciliation status;
- apply readiness;
- event stream scoped by run and task.

Console must become a live operator surface:

- real run list, not only demo snapshots;
- task graph with safe-wave and withheld reasons;
- provider attempts and raw artifact refs;
- verification command evidence;
- review findings and residual risk;
- resume decision packets;
- apply readiness and blocker reasons;
- SSE updates for running jobs.

The console can expose actions later, but v1 completion requires accurate live
inspection before action buttons are trusted.

## Harness And Maturity Gates

Waygent needs a native fixture harness, not just unit tests.

### M0: Contract Offline

Default local gate:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
cd native/kernel && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
```

### M1: Provider Boundary

Offline process fixtures must cover:

- direct JSON;
- JSONL events;
- fenced JSON;
- malformed output;
- missing executable;
- non-zero exit;
- timeout;
- provider result with unexpected changed files;
- provider output that claims verification without kernel evidence.

### M2: Waygent Scenario Fixtures

Add 5-8 default offline scenarios:

- trivial successful edit;
- independent multi-task safe wave;
- overlapping file claims;
- malformed provider output;
- flaky or broken verification environment;
- dirty source checkout apply block;
- stale activity barrier;
- missing checkpoint resume block.

Each fixture creates a disposable git repo, runs Waygent, and verifies the run
root.

### M3: Golden Replay

Each scenario fixture should produce normalized golden outputs:

- `events.jsonl`;
- `run_state.json`;
- trust projection;
- failure projection;
- apply projection;
- summary;
- selected artifacts metadata.

Timestamps and machine-local paths are normalized. Rebuilds must be byte-equal
unless schema changes are intentional.

### M4: Real Worktree And Apply

Fixture gate for:

- real git worktree creation;
- branch naming;
- diff capture;
- checkpoint commit or sealed patch;
- dirty source block;
- clean source apply;
- post-apply verification;
- failed apply evidence.

### M5: Live Provider Smoke

Opt-in only:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Requirements:

- explicit auth/CLI detection;
- cost and wall-clock budget;
- skip by default when unavailable;
- run against disposable fixtures only;
- record provider version and command;
- preserve raw event stream artifacts.

### M6: Dogfood

Waygent must run a small Waygent implementation plan against this repository or
a disposable mirror:

- real provider;
- real verification;
- API visibility;
- console visibility;
- completion audit;
- apply blocked or apply-ready status with clear evidence.

Dogfood success is the first point where Waygent can be considered a KWS
replacement candidate.

### M7: Long-Running Recovery

Waygent must handle interruption:

- process killed after provider dispatch;
- missing worktree;
- orphan worktree;
- partially written state;
- event/state drift;
- stale activity;
- provider-native session resume unavailable.

Completion requires either safe resume or a concrete blocked decision packet.

## Failure Classes

Stable failure classes:

- `adapter_crashed`
- `timeout`
- `malformed_result`
- `permission_denied`
- `verification_failed`
- `review_rejected`
- `needs_plan_fix`
- `needs_split`
- `missing_checkpoint`
- `missing_resume_handler`
- `dependency_blocked`
- `file_claim_conflict`
- `dirty_source_checkout`
- `unsafe_apply`
- `stale_activity`
- `state_drift`
- `artifact_missing`
- `environment_blocker`

Every failure class must map to:

- retry policy;
- resume policy;
- apply policy;
- operator explanation;
- test fixture coverage.

## Security And Safety

Provider process execution must:

- pass through a permission profile;
- set cwd to the isolated worktree;
- redact configured env vars from artifacts;
- bound stdout/stderr captures;
- preserve full output digests;
- block path escapes in patches;
- reject write attempts outside file claims unless explicitly approved;
- avoid nested agent CLI spawning by default;
- classify destructive commands before execution where possible.

The source checkout is never mutated during `run`. Only `apply` may mutate it.

## Documentation And Operator Contract

Docs must explain:

- how to run fake/offline Waygent;
- how to run live provider smoke checks;
- how to inspect a run;
- how to interpret blocked states;
- how to resume safely;
- how to apply safely;
- how to clean orphaned worktrees;
- what evidence is required before trusting a run;
- how Waygent differs from KWS skills.

`skills/waygent` remains thin and maps operator language to CLI commands. It
does not implement runtime behavior.

## Implementation Map

Likely module ownership:

- `packages/contracts`: v2 state, provider event, review result, decision
  packet, and audit schemas.
- `packages/orchestrator`: runtime state machine, task lifecycle, resume,
  apply orchestration, completion audit.
- `packages/runway-control`: scheduler barriers, retry policy, recovery
  decision packets.
- `packages/context-packer`: task packet and spec manifest generation.
- `packages/provider-adapters`: role-aware Codex/Claude/fake/harness adapters.
- `packages/kernel-client`: process supervisor, worktree, checkpoint, apply
  clients.
- `native/kernel`: actual process execution, git worktree, diff dry-run, apply
  safety, artifact sealing.
- `packages/lens-store`: v2 run-root storage and golden replay helpers.
- `packages/lens-projectors`: v2 trust, failure, timeline, review, recovery,
  apply projections.
- `apps/cli`: command contract for run, status, events, inspect, explain,
  resume, apply, cleanup, and live-smoke.
- `apps/api`: v2 state and event read routes.
- `apps/console`: live run inspection UI.
- `skills/waygent`: operator skill contract and evals.
- `tests/integration` and `packages/testkit`: scenario fixtures and maturity
  gates.

## Rollout Strategy

The implementation should be planned as one complete v1 program, but landed in
phases that keep the repo verifiable:

1. Contract and state v2.
2. Worktree and artifact lifecycle.
3. Task packet and provider role contracts.
4. Real process verification.
5. Review and fix loop.
6. Runtime recovery and resume executor.
7. Checkpoint materialization and apply.
8. API/console live inspection.
9. Scenario harness and golden replay.
10. Live provider smoke and dogfood.
11. Docs and operational closure.

Each phase must add tests and must not weaken existing `bun run check`,
`platform:demo`, `check:legacy`, Rust tests, or AgentLens pytest.

## Design Risks

### Over-Copying KWS

Risk: Waygent becomes KWS skill internals in a new package.

Mitigation: copy operational invariants, not schemas or namespaces. Keep
Waygent contracts under `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.

### Under-Specified Provider Output

Risk: provider adapters accept vague summaries and mark tasks complete.

Mitigation: require role-specific schemas, raw artifacts, diff capture, and
kernel verification.

### Context Bloat

Risk: every provider receives the full plan/spec and diverges.

Mitigation: task packets with section slicing, context budgets, and explicit
fallback behavior.

### Unsafe Parallelism

Risk: agents modify shared files concurrently.

Mitigation: scheduler-controlled safe waves only, file-claim conflict tests,
high-risk serialization, and post-attempt safe-wave recompute.

### False Completion

Risk: run status says completed while artifacts are missing or checks were not
run.

Mitigation: completion audit plus state reconciliation; finished state is
blocked when required artifacts or unit manifests are missing.

### Live Provider Instability

Risk: live Codex/Claude behavior changes or auth is unavailable.

Mitigation: default tests remain offline, live smoke is opt-in, provider
version and command are recorded, and scenario fixtures isolate behavior.

### Console Trust Drift

Risk: console shows demo or stale projection as if it were live truth.

Mitigation: v2 API reads run state and event journal from the same root;
console labels missing state, stale projection, or drift explicitly.

## Completion Definition

Waygent v1 operational maturity is complete when:

- a disposable repo fixture can be implemented, reviewed, verified, resumed,
  and applied by Waygent;
- Codex and Claude live providers each pass an opt-in smoke run;
- default offline gates pass without live credentials;
- golden replay fixtures are stable;
- API and console can inspect the same real run;
- dirty apply, stale activity, missing checkpoint, malformed provider output,
  and verification failure all produce actionable decision packets;
- no active runtime path depends on KWS executor skills;
- docs explain how to operate, debug, resume, and apply Waygent runs.

## References

- OpenAI Agents orchestration:
  <https://developers.openai.com/api/docs/guides/agents/orchestration>
- OpenAI Agents guardrails and human review:
  <https://developers.openai.com/api/docs/guides/agents/guardrails-approvals>
- OpenAI Agents results and state:
  <https://developers.openai.com/api/docs/guides/agents/results>
- OpenAI Agents workflow evaluation:
  <https://developers.openai.com/api/docs/guides/agent-evals>
- Codex non-interactive mode:
  <https://developers.openai.com/codex/noninteractive>
- Claude Code Agent SDK overview:
  <https://code.claude.com/docs/en/agent-sdk>
- Claude Code subagents:
  <https://code.claude.com/docs/en/sub-agents>
- Claude Code hooks:
  <https://code.claude.com/docs/en/hooks>
- Harness unified CLI:
  <https://www.harness.lol/docs>
- OpenHands runtime overview:
  <https://docs.openhands.dev/openhands/usage/v0/runtimes/V0_overview>
- OpenHands agent control plane:
  <https://www.openhands.dev/blog/agent-control-plane>
