# Full Rust Agent Platform Rewrite Design

| | |
|---|---|
| Date | 2026-05-21 |
| Author | kws |
| Status | Draft -> User review |
| Scope | Full rewrite of AgentRunway runtime, AgentLens backend, CLI, store, evaluator, API server, and repository structure |
| Decision | Full Rust product, with TypeScript/React retained only for the web dashboard |

> **Implementation note (2026-05-21):** This target architecture remains the
> selected direction, but implementation must start with the contract-first
> reconciliation in
> `2026-05-21-contract-first-unified-agent-platform-design.md`. Do not execute
> the Phase 1 skeleton plan as written if it introduces competing `agent.*`
> runtime schema names or bypasses AgentLens/AgentRunway compatibility.

## 0. Summary

This design replaces the current Python-based AgentRunway and AgentLens backend with a single Rust product. The new system treats AgentRunway and AgentLens as product roles inside one evidence-driven agent platform:

- AgentRunway is the execution engine: scheduling, worktrees, adapters, gates, merge, recovery, and apply.
- AgentLens is the evidence, evaluation, and operator visibility surface: durable artifacts, trust reports, failure projections, API, CLI status, and web dashboard.
- Python is not retained in the final runtime, test harness, packaging, or backend implementation.
- TypeScript remains only for the React dashboard.
- Graphify and similar code-map tools remain optional development aids under `tools/`; they are not product runtime dependencies.

The rewrite optimizes for execution reliability, durable recovery, typed contracts, deployable binaries, and a clean repository structure that can scale without recreating the current Python module sprawl.

## 1. Context

The current Archive checkout has two active surfaces:

- `AgentLens/`: a Python + React local-first evidence system.
- `skills/agent-runway/`: a Python deterministic runner skill that owns scheduling, worktrees, runtime adapters, review and verification gates, merge queue, durable projection, and AgentLens emission.

This has worked as a fast iteration model, but a full no-Python rewrite changes the design center. The goal is no longer to optimize the existing Python runner. The goal is to define a new product boundary where execution, evidence, evaluation, and UI read models are derived from the same durable Rust core.

The existing root `docs/` and `graphify-out/` generated layers were pruned from the current checkout. This spec therefore lives under the current documentation tree: `AgentLens/docs/spec/`.

## 2. Goals

- Replace Python runtime and backend code with Rust.
- Build one coherent product structure instead of two loosely attached tools.
- Preserve the strongest current AgentRunway properties: safe waves, shared-core serialization, durable checkpoints, failure barriers, bounded retries, human decision packets, and explicit apply.
- Preserve the strongest current AgentLens properties: local-first artifacts, filesystem source of truth, schema validation, deterministic evaluator, trust reports, and a UI that does not believe agent claims without evidence.
- Make CLI, HTTP API, evaluator, and web UI read from the same store projection.
- Make state recovery and failure policy typed and testable.
- Keep Graphify/code-map tooling outside the product runtime.

## 3. Non-Goals

- Keeping Python compatibility shims.
- Migrating current Python modules one-for-one into Rust names.
- Making Graphify a required runtime dependency.
- Supporting remote multi-user cloud deployment in the first rewrite slice.
- Rebuilding the web dashboard in Rust.
- Preserving old `kws-cpe.*` or `kws-cme.*` namespaces as the new integration model.

## 4. Architecture

The selected architecture is a Full Rust product: CLI, runtime, store, evaluator, adapters, and API server are Rust crates. The web dashboard remains TypeScript/React.

```text
agent-platform/
  Cargo.toml
  crates/
    agent-core/
    agent-contracts/
    agent-store/
    agent-runway/
    agent-eval/
    agent-adapters/
    agent-server/
    agent-cli/
  apps/
    lens-web/
  tests/
    fixtures/
    e2e/
  docs/
    architecture/
    contracts/
    operations/
  tools/
    dev/
```

### 4.1 Repository Boundary

The rewrite should move toward a root Rust workspace rather than keeping `AgentLens/` as a Python package and `skills/agent-runway/` as an embedded Python skill. The final product name can be chosen later, but the architecture assumes one source tree and one product-level binary family.

### 4.2 Runtime Boundary

Runtime decisions belong in Rust library crates, not in CLI or server glue. The CLI and HTTP API must call the same service functions so `status`, `inspect`, `resume`, `apply`, and dashboard views cannot drift.

### 4.3 Product Roles

- Runway: execution and recovery.
- Lens: evidence, evaluation, and operator-facing read models.
- Store: source of truth and rebuildable indexes.
- Contracts: schemas and event/artifact validation.

These roles are product concepts, not isolated runtimes.

## 5. Component Boundaries

```text
crates/
  agent-core/
    domain/
    config/
    time/
    error/

  agent-contracts/
    schemas/
    events/
    artifacts/
    validation/

  agent-store/
    fs_store/
    sqlite_index/
    locks/
    retention/
    query/

  agent-runway/
    plan/
    scheduler/
    worktree/
    gates/
    merge/
    recovery/

  agent-eval/
    checks/
    trust/
    import/
    projection/

  agent-adapters/
    process/
    codex/
    claude/
    local/
    sandbox/

  agent-server/
    api/
    dto/
    assets/
    auth/

  agent-cli/
    commands/
    output/
```

### 5.1 `agent-core`

Owns product-wide primitives:

- `RunId`, `TaskId`, `WorkspaceId`, `CandidateId`, `CheckpointId`.
- `Outcome`, `RiskLevel`, `TaskStatus`, `RunStatus`.
- deterministic and system clocks.
- resolved config and environment parsing.
- shared error taxonomy.

This crate must not depend on Runway, Lens, HTTP, SQLite, Git, or process adapters.

### 5.2 `agent-contracts`

Owns schemas and validation:

- event envelope schemas.
- final/eval/manifest/trust report artifacts.
- AgentRunway projection artifacts.
- schema version handling.
- schema drift checks.

No crate should define a competing event or artifact shape.

### 5.3 `agent-store`

Owns durable persistence:

- filesystem artifact source of truth.
- append-only event journal.
- lock files.
- artifact sealing.
- SQLite read index.
- index rebuild.
- query read models.
- retention and garbage collection.

SQLite is a cache and query accelerator. Filesystem artifacts remain authoritative.

### 5.4 `agent-runway`

Owns execution:

- spec/plan loading and lint.
- task packets.
- safe-wave scheduling.
- shared-core/high-risk serialization.
- worktree lifecycle.
- file claims.
- reviewer and verifier gates.
- candidate ranking.
- merge queue.
- checkpoint writing.
- durable resume.
- failure barriers.
- human decision packets.

Workers, reviewers, verifiers, CLI commands, and UI views must not write store internals directly.

### 5.5 `agent-eval`

Owns judgment:

- deterministic evidence checks.
- final claim versus evidence comparison.
- trust report generation.
- failure projection.
- degraded evidence classification.
- evaluator read models consumed by CLI and web.

The evaluator must treat agent output as a claim, not as truth.

### 5.6 `agent-adapters`

Owns process integration:

- supervised child process execution.
- Codex adapter.
- Claude adapter.
- local deterministic fake adapter.
- sandbox and permission abstractions.
- stdout/stderr/event capture.
- timeout and cancellation behavior.

Adapters produce typed worker/gate results and evidence. They do not schedule tasks or mutate run projections directly.

### 5.7 `agent-server`

Owns local HTTP API:

- read endpoints for runs, events, failures, trust reports, workspaces, and doctor state.
- command endpoints for explicit operator actions if later approved.
- local-only host policy.
- dashboard asset serving.

It must not contain scheduling, recovery, trust-scoring, or store mutation logic.

### 5.8 `agent-cli`

Owns human terminal entrypoints:

- `run`
- `lint-plan`
- `status`
- `summarize`
- `inspect`
- `events`
- `resume`
- `apply`
- `serve`
- `doctor`

Formatting belongs here. Decisions do not.

### 5.9 `apps/lens-web`

Owns UI only:

- run list.
- run detail.
- trust report panel.
- failure panel.
- workspace view.
- degraded/offline states.

The web app reads API projections and requests explicit commands through the server. It does not own runtime logic or schemas.

## 6. Data Flow

```text
CLI / Server request
  -> agent-cli / agent-server
  -> agent-runway::plan loads spec + plan
  -> agent-contracts validates task/evidence contract
  -> agent-store opens run and writes immutable run manifest
  -> agent-runway::scheduler computes safe_wave
  -> agent-runway::worktree creates isolated candidate worktrees
  -> agent-adapters runs codex/claude/local workers
  -> agent-runway::gates runs review + verification
  -> agent-runway::merge applies accepted candidate to run-main
  -> agent-store writes checkpoint + event + artifact evidence
  -> agent-eval recomputes trust/eval projection
  -> agent-cli / agent-server returns same read model
  -> apps/lens-web renders API projection
```

### 6.1 Durable State Layout

```text
~/.agent-platform/
  runs/
    <workspace-id>/
      <run-id>/
        manifest.json
        events.jsonl
        artifacts/
          contract.json
          checkpoints/
          candidates/
          decisions/
          final.json
          eval.json
          trust_report.json
        index.sqlite
  worktrees/
    <workspace-id>/
      <run-id>/
        main/
        candidates/
```

### 6.2 Storage Rules

- Filesystem artifacts are the source of truth.
- SQLite is rebuildable and never the only copy of critical evidence.
- All events and artifacts pass through `agent-contracts`.
- Runner, evaluator, server, and web do not each define their own schemas.
- Human decisions, blocked states, failure barriers, and checkpoints must be reconstructable from durable evidence.
- UI mutations, if added later, must call command APIs and emit durable events.

## 7. Error Handling

Failure policy is typed. The initial failure taxonomy is:

```rust
enum FailureClass {
    NeedsRebase,
    NeedsFullContext,
    NeedsPlanFix,
    NeedsInfraFix,
    MissingCheckpoint,
    MissingResumeHandler,
    FileClaimViolation,
    VerificationFailed,
    ReviewChangesRequested,
    HumanDecisionRequired,
    AgentLensUnavailable,
    Unknown,
}
```

### 7.1 Recovery Policy

| Failure | Policy |
|---|---|
| `NeedsRebase` | Try one automatic redispatch or rebase. Repeated failure blocks. |
| `NeedsFullContext` | Retry once with expanded reviewer/verifier context. |
| `NeedsPlanFix` | Stop. Require plan/spec correction. |
| `NeedsInfraFix` | Stop. Mark environment/tooling problem. |
| `MissingCheckpoint` | Reconstruct only when durable evidence proves the checkpoint. Otherwise block. |
| `MissingResumeHandler` | Block. Never record fake progress. |
| `FileClaimViolation` | Reject candidate and either redispatch or block according to task risk. |
| `VerificationFailed` | Retry once only when failure is actionable. Repeated failure blocks. |
| `ReviewChangesRequested` | Retry once with review evidence threaded into the worker prompt. |
| `HumanDecisionRequired` | Write decision packet and stop. |
| `AgentLensUnavailable` | Mark observability/evaluation as degraded when relevant. Execution evidence remains local and authoritative. |
| `Unknown` | Block safely. |

### 7.2 Flow

```text
worker/gate/store error
  -> FailureClassifier
  -> RecoveryPolicy
  -> AutomaticAction | ManualAction | Blocked
  -> event + decision packet
  -> status/read model
```

The important property is that Rust does not merely port Python behavior. It makes failure barriers and recovery decisions explicit, typed, and testable.

## 8. Testing And Verification

The test suite proves that the new Rust structure preserves or improves the current reliability contract.

```text
crates/*/tests/
tests/fixtures/
tests/e2e/
apps/lens-web/src/*test
```

### 8.1 Required Test Coverage

- `agent-contracts`: schema validation, backward compatibility, version handling, drift detection.
- `agent-store`: artifact writes, readback, locks, index rebuild, corrupted SQLite recovery.
- `agent-runway::scheduler`: safe waves, dependency checkpoint release, shared-core serialization, high-risk barriers.
- `agent-runway::worktree`: dirty checkout refusal, file claims, candidate retention.
- `agent-runway::gates`: review and verification pass/fail/block outcomes, candidate ranking.
- `agent-runway::recovery`: missing checkpoint, missing handler, retry caps, human decision packets.
- `agent-eval`: final claim versus evidence, trust reports, failure projection.
- `agent-cli`: run, lint-plan, status, summarize, inspect, events, resume, apply, serve, doctor.
- `agent-server`: API and CLI read-model parity.
- `apps/lens-web`: run list, run detail, trust panel, failure panel, degraded states.
- `tests/e2e`: deterministic full runs using a local fake adapter.

### 8.2 Verification Commands

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cd apps/lens-web && bun test && bun run build
```

### 8.3 Python Removal Acceptance

Runtime and source trees in the new platform must not contain Python implementation files or Python packaging.

```bash
rg -n "python|pytest|pyproject|\\.py\\b" crates apps packages tests
```

Historical docs and migration notes may mention Python. Runtime source, tests, scripts, and package metadata may not depend on it.

## 9. Migration Strategy

The rewrite should avoid a prolonged mixed-runtime state. The implementation plan should still be phased, but the end-state must be a clean Rust product.

### Phase 1: Skeleton And Contracts

- Create root Rust workspace.
- Add `agent-core` domain types.
- Add `agent-contracts` schemas and validation.
- Add fixture-based schema tests.
- Add web app relocation plan under `apps/lens-web`.

### Phase 2: Store And Read Models

- Implement filesystem store.
- Implement SQLite index as rebuildable cache.
- Implement query read models.
- Implement manifest, event journal, and artifact sealing.
- Add CLI read commands for fixture-backed runs.

### Phase 3: Runway Runtime

- Implement plan parsing and lint.
- Implement scheduler and safe-wave computation.
- Implement worktree lifecycle.
- Implement local fake adapter.
- Implement review/verification gate model.
- Implement merge queue and checkpoints.

### Phase 4: Recovery And Evaluation

- Implement failure classifier.
- Implement recovery policy.
- Implement durable resume.
- Implement decision packets.
- Implement trust evaluator and failure projections.

### Phase 5: CLI, Server, And Web

- Implement production CLI commands.
- Implement local HTTP API.
- Move or recreate dashboard under `apps/lens-web`.
- Ensure CLI and web use the same read models.
- Package dashboard assets with the Rust server.

### Phase 6: Legacy Removal

- Remove Python runtime sources from the active product tree.
- Remove Python package metadata and eval harnesses.
- Replace old skill entrypoints with thin documentation or migration wrappers only if explicitly approved.
- Run no-Python acceptance checks.

## 10. Open Decisions For The Implementation Plan

The implementation plan should resolve these without changing the architecture:

- Final product and binary names.
- Whether the old `AgentLens/` directory is moved in one commit or replaced by a new root layout first.
- Whether old Python fixtures are converted mechanically or rewritten as Rust-native JSON fixtures.
- Whether the first server API is read-only or includes explicit operator command endpoints.
- Whether the initial dashboard is a direct UI port or a redesigned trust console.

## 11. Success Criteria

- A Rust workspace builds with no Python runtime dependency.
- A deterministic fake-adapter run can execute end to end.
- Run evidence can be inspected by CLI and web from the same store projection.
- Failure barriers block unsafe automatic progress.
- SQLite can be deleted and rebuilt from filesystem artifacts.
- Trust reports are generated from evidence, not final claims.
- Existing AgentRunway/AgentLens concepts are preserved as typed Rust boundaries, not as Python-shaped modules.
- Graphify/code-map tooling is optional and isolated under `tools/` if added.
