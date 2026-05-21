# Waygent Bun Control Plane + Rust Kernel Design

| | |
|---|---|
| Date | 2026-05-21 |
| Status | Approved direction |
| Scope | Clean rewrite architecture for AgentLens, AgentRunway, and Waygent |
| Decision | Python-free, Graphify-free platform with Bun/TypeScript control plane and Rust execution kernel |
| Relationship To Existing Docs | This is a new alternative design. It does not edit or replace the Full Rust spec/plan files in-place. |

## 0. Decision

Build Waygent as the next AgentLens/AgentRunway platform:

```text
Bun/TypeScript control plane
  + Rust execution kernel
  + event-sourced AgentLens store
  + agent-agnostic provider adapters
```

This supersedes direct execution of the current Full Rust Phase 1 plan as the
next architectural direction, but it intentionally leaves the Full Rust design
documents untouched. The new target assumes rewrite cost is not a constraint:
current Python runtime, Python tests, Graphify-generated navigation, and legacy
KWS CPE/CME split are not retained in the final product.

The core product roles are:

- **Waygent**: user-facing orchestration entrypoint and profile
  layer.
- **AgentRunway**: deterministic multi-agent execution control plane.
- **AgentLens**: evidence, evaluation, trust projection, and operator
  observability substrate.
- **Rust Execution Kernel**: the only boundary allowed to perform dangerous
  filesystem, process, worktree, sandbox, and patch/apply side effects.

## 1. Why This Architecture

The public harness review points to one consistent split:

- Product policy, orchestration, permission explanation, API composition, and
  UI iteration move fastest in TypeScript.
- Process execution, sandboxing, path canonicalization, patch application,
  worktree mutation, cancellation, output capture, and atomic event append need
  a smaller native boundary.
- Durable events and projections are more important than raw transcripts or
  chat history.
- Multi-agent systems are reliable only when scheduler state, file claims,
  checkpoints, review gates, and apply decisions are explicit contracts.

Therefore the best architecture is not Pure Bun and not Pure Rust. Bun owns the
control plane. Rust owns irreversible side effects.

## 2. Research Inputs

The design is based on direct structure and code-level review of these public
projects:

| Area | Projects Reviewed | Takeaway |
|---|---|---|
| Native execution and sandbox | OpenAI Codex `0b4f860`, Goose `ca26f01` | Use a typed execution request, central tool/execution orchestrator, sandbox manager, process cancellation, and event journal ordering. |
| TypeScript/IDE/CLI agents | Continue `cb27309`, Gemini CLI `906f8a3`, Cline `2a351ff`, OpenCode `6602341`, Crush `3250fef` | Use Bun/TS for tool registry, permission policy, session projection, provider adapters, and API/UI surfaces. Move process/diff/apply down to native. |
| Python coding agents | OpenHands `9a7e3ed`, SWE-agent `0f4f3bb`, SWE-ReX `5c995c3`, Aider `6435cb8` | Keep sandbox service, runtime protocol, trajectory, retry taxonomy, and edit diagnostics as patterns. Do not keep Python as final runtime. |
| Orchestration frameworks | LangGraph `aa322c1`, CrewAI `418afd2`, smolagents `3cd5c84`, AutoGPT `aa1d12b`, AutoGen `027ecf0`, OpenAI Agents Python `45effb4` | Adopt checkpoint snapshot, task write log, durable interrupt, explicit status machine, and schema-bound tool execution. Avoid full graph framework/platform complexity. |
| Multi-harness/ADE systems | OpenADE `522ffb4`, Codemux `ac2716d`, Coleo `92c540e`, harness-cli `d361f85`, OpenHarness `f727de1`, Open-Harness `4645c5d` | Treat AgentRunway as an execution control plane, not a single-agent runner. Use capability-aware adapters and canonical provider events. |
| Desktop/local orchestrators | RunMaestro/Maestro `1006e3b`, Reina Maestro `e32b857`, Overstory `00f6673`, Agent of Empires `df50ed9`, Orca `e9a79b8`, Claude Squad `4a02a30` | Borrow provider adapters, process supervision, output parsers, evidence/verdict contracts, worker replay, and worktree UX. Do not borrow UI-store or markdown-checkbox state as scheduler truth. |

## 2.1 Full Rust Phase 1 Carry-Forward

The blocked Full Rust Phase 1 plan should not be executed as the next path, but
it has several strong strategies that should carry into Waygent:

- **Contract skeleton before runtime behavior**: first prove ids, outcomes,
  timestamps, event envelopes, artifacts, schema validation, and package/crate
  boundaries before adding scheduler or adapter complexity.
- **Locked schemas as product contracts**: keep JSON Schema fixtures in the
  repository and validate real examples against them, instead of treating
  TypeScript interfaces or Rust structs as enough.
- **Typed domain primitives**: normalize run ids, task ids, candidate ids,
  checkpoint ids, timestamps, outcomes, risk levels, run statuses, and task
  statuses once in `packages/contracts` and mirror only the kernel subset in
  Rust.
- **Toolchain and lockfile discipline**: pin Rust formatting/toolchain settings,
  commit lockfiles for binary/demo workspaces, and make formatting, linting, and
  tests part of the first handoff criteria.
- **Boundary markers that compile early**: create small package/crate boundaries
  with explicit responsibility notes before wiring higher-level behavior through
  them.
- **Legacy exclusion checks**: verify the new product tree does not grow Python
  runtime files, Graphify assumptions, or old `kws-cpe` / `kws-cme` namespaces.

## 3. Non-Goals

- Keeping Python compatibility shims in the final runtime.
- Keeping Graphify as a runtime or documentation dependency.
- Editing the existing Full Rust spec or Full Rust Phase 1 plan.
- Rebuilding a desktop-first ADE shell.
- Using NATS, RabbitMQ, distributed queueing, or cloud execution in the first
  product shape.
- Letting an LLM brain continuously reinterpret scheduler state.
- Letting workers mutate AgentLens, SQLite, or the source checkout directly.
- Reintroducing `kws-cpe.*` or `kws-cme.*` as product roles or event
  namespaces.

## 4. Target Repository Structure

```text
waygent/
  package.json
  bun.lock
  tsconfig.base.json

  apps/
    cli/
      src/
    api/
      src/
    lens-web/
      src/

  packages/
    contracts/
      src/
      schemas/
    runway-control/
      src/
    lens-store/
      src/
    lens-projectors/
      src/
    orchestrator/
      src/
    provider-adapters/
      src/
    policy/
      src/
    context-packer/
      src/
    eval/
      src/
    testkit/
      src/

  native/
    kernel/
      Cargo.toml
      Cargo.lock
      rust-toolchain.toml
      rustfmt.toml
      crates/
        kernel-protocol/
        process-supervisor/
        sandbox-policy/
        git-worktree/
        diff-apply/
        event-journal/
        artifact-seal/

  tests/
    fixtures/
    integration/
    e2e/

  docs/
    architecture/
    contracts/
    operations/
```

The final product root should be a clean platform tree. Existing `AgentLens/`
and `skills/agent-runway/` are source references during the rewrite, not final
runtime package locations.

## 5. Component Boundaries

### 5.1 `packages/contracts`

Owns the cross-language contracts:

- run ids, task ids, candidate ids, checkpoint ids, event ids;
- typed domain primitives for ids, timestamps, outcomes, run status, task
  status, risk level, and trust impact;
- event envelope schemas;
- worker, reviewer, verifier, and apply result schemas;
- trust report and failure projection schemas;
- kernel request/response schemas;
- provider adapter capability manifests;
- checked-in JSON Schema fixtures and valid/invalid golden examples;
- schema versioning and compatibility checks.

This package emits JSON Schema for both Bun and Rust tests. No other package or
crate may invent competing event or artifact shapes.

### 5.2 `packages/runway-control`

Owns deterministic execution control:

- plan/spec parsing;
- task graph and dependency state;
- file claims and shared resource locks;
- `safe_wave` calculation;
- checkpoint-gated task release;
- stale activity detection;
- failure barrier classification;
- retry budget and recovery policy;
- durable interrupt and decision packet creation;
- operator-facing durable projection.

This package decides what may run. It does not spawn processes, mutate
worktrees, apply patches, or write unvalidated artifacts directly.

### 5.3 `packages/lens-store`

Owns logical store APIs:

- append event;
- write artifact;
- read run timeline;
- rebuild projection;
- query run summaries;
- retention planning.

The canonical source of truth remains filesystem events and artifacts. SQLite
is a rebuildable projection cache, not the only copy of evidence.

### 5.4 `packages/lens-projectors`

Owns read models:

- trust report;
- failure summary;
- task/candidate timeline;
- tool/permission timeline;
- worktree and checkpoint graph;
- stale or blocked activity views;
- run health and observability quality.

Projectors treat agent claims as claims. Verification artifacts, kernel
evidence, and gate outputs have higher trust weight than final text.

### 5.5 `packages/provider-adapters`

Owns agent integration:

- Codex adapter;
- Claude adapter;
- OpenCode/Gemini/Goose/ACP adapters when useful;
- local fake adapter for deterministic tests;
- capability matrix;
- provider event normalization.

Adapters produce typed events and result artifacts. They do not own scheduling,
merge, apply, projection, or trust scoring.

### 5.6 `packages/policy`

Owns policy language:

- mode hierarchy: `plan`, `read`, `execute`, `auto_edit`, `recovery`, `yolo`;
- permission rules;
- command prefix policy;
- filesystem grants and denies;
- network policy;
- risk classification;
- escalation reasons;
- human approval request shape.

The policy package explains decisions. The Rust kernel enforces path, process,
sandbox, and patch constraints.

### 5.7 `packages/context-packer`

Replaces Graphify with on-demand context:

- ripgrep file discovery;
- tree-sitter symbol extraction where useful;
- lightweight repo map generation;
- task-scoped file relevance;
- no persistent generated graph as product state.

Context packing is an input aid. It is not a scheduler truth source and not a
runtime dependency.

### 5.8 `native/kernel`

Owns dangerous hands:

- process spawn, PTY, stdin policy, stdout/stderr capture;
- timeout, cancellation, process group kill;
- sandbox selection and argv transformation;
- path canonicalization;
- git worktree creation, checkpoint, cherry-pick, cleanup;
- patch parse, dry-run, fuzzy diagnostics, apply validation;
- atomic event append ordering;
- artifact sealing and content hashes;
- file locks and concurrent workspace locks.

The kernel exposes a small typed protocol over JSON-RPC, UDS, or stdio. Bun can
request actions; Bun cannot bypass kernel validation for irreversible effects.

## 6. Data Flow

```text
User / CLI / API
  -> Waygent
  -> runway-control parses plan/spec and builds durable task graph
  -> lens-store records run_started and contract snapshot
  -> runway-control computes safe_wave
  -> kernel creates run-main and candidate worktree
  -> provider-adapter launches worker through kernel execution request
  -> worker emits normalized events and typed result
  -> kernel captures process evidence and seals artifacts
  -> eval/review/verification gates run
  -> runway-control ranks candidate and updates durable projection
  -> kernel merges selected candidate into run-main checkpoint
  -> lens-projectors rebuild trust/failure/status views
  -> explicit apply copies accepted run-main commits into source checkout
```

## 7. Durable State Model

The platform stores separate but linked records:

- **event journal**: append-only ordered facts;
- **task write log**: intermediate task outputs and decisions;
- **checkpoint snapshot**: run-main and scheduler state at safe boundaries;
- **artifact store**: worker results, review results, verification results,
  patches, diffs, command logs, decision packets, trust reports;
- **projection cache**: SQLite read models rebuilt from events/artifacts.

`durable_projection` remains the dispatch authority. It derives:

- ready tasks;
- safe wave;
- withheld tasks;
- task classes;
- stale activities;
- blocked node;
- failure class;
- next automatic action;
- required human decision;
- decision packet;
- projection status.

## 8. Status Machine

Every task moves through explicit states:

```text
PENDING
READY
WITHHELD_DEPENDENCY
WITHHELD_CHECKPOINT
WITHHELD_FILE_CLAIM
WITHHELD_RESOURCE_LOCK
WITHHELD_RISK
RUNNING
REVIEW
VERIFYING
FAILED_RETRYABLE
FAILED_TERMINAL
AWAITING_HUMAN_DECISION
MERGE_READY
MERGED
APPLIED
```

The scheduler may dispatch only `READY` tasks included in the current
`safe_wave`.

## 9. Failure And Recovery

Failure handling is a first-class contract, not a logging detail.

Failure classes include:

- `adapter_crashed`;
- `timeout`;
- `cancelled`;
- `malformed_result`;
- `diff_scope_failed`;
- `review_changes_requested`;
- `review_rejected`;
- `verification_failed`;
- `merge_conflict`;
- `needs_rebase`;
- `needs_plan_fix`;
- `needs_split`;
- `needs_infra_fix`;
- `missing_checkpoint`;
- `missing_resume_handler`;
- `stale_activity`;
- `terminal_rejected`.

Recovery actions include:

- retry implementer with gate evidence;
- redispatch from latest checkpoint;
- rebuild projection from event journal;
- repair missing checkpoint;
- request human decision;
- split task;
- block terminally with decision packet.

No recovery path can create mutable worker worktrees unless the durable
projection releases the task back into `safe_wave`.

## 10. Permission And Kernel Request Model

All side effects pass through a single execution request shape:

```json
{
  "request_id": "exec_...",
  "run_id": "run_...",
  "task_id": "task_...",
  "kind": "process.exec",
  "cwd": "/workspace/run-main",
  "argv": ["bun", "test"],
  "env": {},
  "timeout_ms": 120000,
  "stdin": "closed",
  "tty": false,
  "permission_profile": {
    "filesystem": {
      "read": ["."],
      "write": ["native/kernel/**", "packages/contracts/**"],
      "deny": [".git/config"]
    },
    "network": "disabled",
    "command_prefixes": ["bun", "cargo", "git"],
    "escalation_reason": "verification command"
  },
  "capture": {
    "stdout_limit_bytes": 200000,
    "stderr_limit_bytes": 200000
  }
}
```

The kernel returns structured evidence:

- exit code;
- signal;
- timeout/cancellation reason;
- stdout/stderr digests and bounded excerpts;
- changed files;
- sandbox decision;
- permission decision;
- artifact hashes.

## 11. AgentLens Event Model

AgentLens should prioritize canonical control events over raw transcript replay.

Core event families:

- `platform.run_started`;
- `platform.contract_snapshot`;
- `runway.task_ready`;
- `runway.task_withheld`;
- `runway.safe_wave_selected`;
- `runway.worker_started`;
- `runway.worker_result`;
- `kernel.exec_started`;
- `kernel.exec_completed`;
- `kernel.patch_validated`;
- `kernel.worktree_checkpointed`;
- `runway.review_result`;
- `runway.verification_result`;
- `runway.candidate_ranked`;
- `runway.merge_completed`;
- `runway.apply_completed`;
- `runway.failure_barrier`;
- `runway.decision_packet_created`;
- `lens.trust_report_updated`.

Provider-native transcripts may be imported as artifacts, but they are not the
primary read model and do not drive scheduling.

## 12. Testing Strategy

The first implementation plan should be contract-first and deterministic:

- pinned Bun and Rust workspace settings;
- domain primitive tests for ids, timestamps, statuses, outcomes, and risk
  levels;
- schema round-trip tests for Bun and Rust;
- checked-in valid and invalid JSON fixtures for every cross-language schema;
- kernel protocol golden fixtures;
- fake provider adapter e2e runs;
- safe-wave scheduler tests;
- file claim conflict tests;
- failure barrier tests;
- event journal replay tests;
- SQLite projection rebuild tests;
- patch dry-run/apply tests;
- process timeout/cancel/output-cap tests;
- AgentLens trust projection tests;
- Rust `cargo fmt`, `cargo clippy`, and `cargo test` gates for `native/kernel`;
- new-tree scans proving no Python runtime files, Graphify dependencies, or
  legacy KWS namespaces were introduced;
- one opt-in live Codex/Claude smoke suite kept outside the default run.

Default validation should not require real model calls.

## 13. Migration Position

This design is a clean target, not an incremental compatibility layer.

Final state removes:

- `AgentLens/pyproject.toml`;
- Python backend, CLI, store, evaluator, and FastAPI server;
- `skills/agent-runway/scripts/agentrunway/`;
- Python AgentRunway eval harness;
- Graphify-generated navigation and runtime assumptions;
- old KWS CPE/CME runtime split.

During rewrite, the old Python code can be used as behavioral reference only.
It should not be preserved as a runtime compatibility dependency.

## 14. Recommended First Slice

The first implementation plan should not start with the web UI. It should
create the platform spine:

1. Bun workspace and package boundaries.
2. Shared domain primitives, event envelopes, and JSON Schema fixtures.
3. Rust kernel workspace with pinned toolchain, protocol crate, and lockfile.
4. Append-only event journal and projection rebuild.
5. Fake provider adapter.
6. Minimal safe-wave scheduler.
7. Kernel process execution with timeout/cancel/output caps.
8. One deterministic end-to-end run that emits AgentLens trust projection.
9. Handoff checks for formatting, linting, test coverage, no Python runtime
   additions, no Graphify dependency, and no legacy KWS namespaces.

This proves the architecture before Codex/Claude adapters and before dashboard
polish.

## 15. Final Recommendation

Adopt this as the new architecture direction:

```text
Waygent
  -> AgentRunway Execution Control Plane (Bun/TS)
  -> Rust Execution Kernel
  -> AgentLens Event Store + Trust Projectors
  -> React Operator Console
```

This gives the project the product velocity of Bun/TypeScript, the reliability
of a native execution kernel, and the evidence-first operating model that
already differentiates AgentLens and AgentRunway.
