# Waygent Full Platform Implementation Program

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete Waygent architecture described in the Bun control plane + Rust kernel spec, not only the Phase 1 spine.

**Architecture:** Waygent is built as a Bun/TypeScript control plane with a Rust execution kernel and an event-sourced AgentLens substrate. The first executable spine proves contracts, the scheduler projection, the event journal, the fake provider, and bounded kernel process execution; later phases complete policy, worktrees, patch/apply, live adapters, API, dashboard, context packing, and legacy removal without reintroducing Python, Graphify, or old KWS CPE/CME namespaces.

**Tech Stack:** Bun 1.3+, TypeScript 5.9+, `bun:test`, JSON Schema, Ajv, Rust stable, Cargo resolver v2, `serde`, `serde_json`, `thiserror`, `wait-timeout`, SQLite projection cache, React/Vite operator console, filesystem JSONL artifacts.

---

## Source Spec

- Design spec: `AgentLens/docs/spec/2026-05-21-bun-control-plane-rust-kernel-agent-platform-design.md`
- Existing first-slice detailed plan: `AgentLens/docs/plan/2026-05-21-bun-control-plane-rust-kernel-platform-phase-1-spine.md`
- Read-only reference for useful strategy only: `AgentLens/docs/plan/2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md`

Do not edit the Full Rust spec or Full Rust Phase 1 plan while executing this
program. They are historical alternatives and source references, not the active
Waygent execution path.

## Scope Boundary

This document covers the complete implementation program for the spec. It does
not replace the Phase 1 spine plan. Instead, it defines every product phase
needed after the first spine and records the acceptance gates that prove the
whole architecture exists.

The implementation must end with:

- no Python runtime package in the Waygent product tree;
- no Graphify runtime or documentation dependency in the Waygent product tree;
- no `kws-cpe.*` or `kws-cme.*` event namespace;
- one deterministic offline demo path;
- opt-in live provider smoke paths for Codex and Claude;
- replayable AgentLens event/artifact evidence;
- explicit apply from accepted run-main checkpoints into the source checkout.

## Target Product Tree

```text
package.json
bun.lock
bunfig.toml
tsconfig.base.json
apps/
  cli/
  api/
  lens-web/
packages/
  contracts/
  runway-control/
  lens-store/
  lens-projectors/
  orchestrator/
  provider-adapters/
  policy/
  context-packer/
  eval/
  testkit/
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

## Program Phases

| Phase | Name | Result |
|---|---|---|
| 1 | Executable Spine | Bun workspace, contracts, minimal scheduler projection, Lens event journal, Rust process kernel, fake provider, deterministic demo. |
| 2 | Contract And Schema Hardening | Domain primitives, schema fixtures, cross-language validation, status machine, capability manifests. |
| 3 | Kernel Safety Boundary | Process groups, cancellation, output digests, sandbox policy, event journal append ordering, artifact sealing. |
| 4 | Runway Control Plane | Durable task graph, safe-wave release, file/resource locks, status machine, failure barriers, decision packets. |
| 5 | Store And Projectors | Append-only AgentLens store, artifact store, SQLite projection cache, trust/failure/timeline projectors. |
| 6 | Worktree And Patch Apply | Run-main worktree, candidate worktrees, diff validation, patch dry-run/apply, merge/checkpoint, explicit source apply. |
| 7 | Provider Adapters | Codex, Claude, local fake, and optional OpenCode/Gemini/Goose/ACP adapters behind capability-aware contracts. |
| 8 | Policy And Permissions | Mode hierarchy, filesystem/network/command rules, approval requests, kernel-enforced permission evidence. |
| 9 | Orchestrator, CLI, And API | Waygent run lifecycle, profile selection, CLI commands, local HTTP API, SSE event stream. |
| 10 | Context Packer | Graphify-free repo map, symbol scan, task-scoped context, evidence-aware context selection. |
| 11 | Lens Web Console | Operator UI for runs, safe waves, tasks, events, trust reports, failures, decision packets, and apply state. |
| 12 | Migration And Legacy Removal | Remove Python runtime references from the product tree, remove Graphify assumptions, preserve old code only as archived reference. |

## Phase 1: Executable Spine

Detailed execution lives in:

```text
AgentLens/docs/plan/2026-05-21-bun-control-plane-rust-kernel-platform-phase-1-spine.md
```

Acceptance gates:

```bash
bun install
bun run check
bun run platform:demo
cd native/kernel && cargo test
cd ../.. && git diff --check
```

Expected result:

- `bun run platform:demo` prints a trusted run with three canonical events.
- Bun typecheck and tests pass.
- Rust kernel tests pass.
- The source checkout stays dirty only with intentional in-scope changes.

## Phase 2: Contract And Schema Hardening

### Task 2.1: Expand Domain Primitives

```yaml agentrunway-task
task_id: phase2_task_001
title: Expand Domain Primitives
risk: medium
phase: implementation
dependencies: [phase1]
file_claims:
  - {path: packages/contracts, mode: owned}
  - {path: tests/fixtures/contracts, mode: owned}
acceptance_commands:
  - bun test packages/contracts/tests/contracts.test.ts
  - bun test packages/contracts/tests/fixtures.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `packages/contracts/src/ids.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`
- Create: `packages/contracts/tests/fixtures.test.ts`
- Create: `tests/fixtures/contracts/valid-event.json`
- Create: `tests/fixtures/contracts/invalid-legacy-namespace.json`
- Create: `tests/fixtures/contracts/valid-kernel-request.json`
- Create: `tests/fixtures/contracts/valid-worker-result.json`

- [ ] **Step 1: Add fixture tests**

Create `packages/contracts/tests/fixtures.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { ContractValidationError, validateContract } from "../src";

function fixture(name: string): unknown {
  return JSON.parse(
    readFileSync(join(import.meta.dir, "../../../tests/fixtures/contracts", name), "utf8")
  );
}

describe("contract fixtures", () => {
  test("accepts valid event fixture", () => {
    expect(validateContract("agentlens.event.v3", fixture("valid-event.json"))).toBeTruthy();
  });

  test("rejects legacy namespace fixture", () => {
    expect(() =>
      validateContract("agentlens.event.v3", fixture("invalid-legacy-namespace.json"))
    ).toThrow(ContractValidationError);
  });

  test("accepts kernel request fixture", () => {
    expect(
      validateContract("kernel.execution_request.v1", fixture("valid-kernel-request.json"))
    ).toBeTruthy();
  });

  test("accepts worker result fixture", () => {
    expect(
      validateContract("runway.worker_result.v1", fixture("valid-worker-result.json"))
    ).toBeTruthy();
  });
});
```

- [ ] **Step 2: Add valid event fixture**

Create `tests/fixtures/contracts/valid-event.json`:

```json
{
  "schema": "agentlens.event.v3",
  "event_id": "event_demo",
  "agentlens_run_id": "run_lens",
  "orchestrator_run_id": "run_orchestrator",
  "producer": {
    "name": "agentrunway",
    "kind": "orchestrator",
    "version": "0.1.0"
  },
  "event_type": "runway.worker_result",
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "worker",
  "outcome": "success",
  "severity": "info",
  "trust_impact": "supports_success",
  "summary": "Worker produced bounded evidence.",
  "payload": {
    "task_id": "task_demo"
  }
}
```

- [ ] **Step 3: Add invalid legacy namespace fixture**

Create `tests/fixtures/contracts/invalid-legacy-namespace.json`:

```json
{
  "schema": "agentlens.event.v3",
  "event_id": "event_demo",
  "agentlens_run_id": "run_lens",
  "orchestrator_run_id": "run_orchestrator",
  "producer": {
    "name": "agentrunway",
    "kind": "orchestrator",
    "version": "0.1.0"
  },
  "event_type": "kws-cpe.worker_result",
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "worker",
  "outcome": "success",
  "severity": "info",
  "trust_impact": "supports_success",
  "summary": "Legacy namespace should fail.",
  "payload": {}
}
```

- [ ] **Step 4: Add kernel request fixture**

Create `tests/fixtures/contracts/valid-kernel-request.json`:

```json
{
  "schema": "kernel.execution_request.v1",
  "request_id": "exec_demo",
  "run_id": "run_demo",
  "task_id": "task_demo",
  "cwd": ".",
  "argv": ["printf", "hello"],
  "env": {},
  "timeout_ms": 1000,
  "stdin": "closed",
  "tty": false,
  "capture": {
    "stdout_limit_bytes": 100,
    "stderr_limit_bytes": 100
  }
}
```

- [ ] **Step 5: Add worker result fixture**

Create `tests/fixtures/contracts/valid-worker-result.json`:

```json
{
  "schema": "runway.worker_result.v1",
  "task_id": "task_demo",
  "candidate_id": "candidate_demo",
  "status": "completed",
  "changed_files": ["README.md"],
  "summary": "Fake provider completed the task.",
  "evidence": {
    "provider": "fake-provider"
  }
}
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
bun test packages/contracts/tests/fixtures.test.ts
bun run typecheck
```

Expected: all commands pass.

Commit:

```bash
git add packages/contracts tests/fixtures/contracts
git commit -m "feat: harden Waygent contract fixtures"
```

### Task 2.2: Mirror Kernel Contract Validation In Rust

```yaml agentrunway-task
task_id: phase2_task_002
title: Mirror Kernel Contract Validation In Rust
risk: medium
phase: implementation
dependencies: [phase2_task_001]
file_claims:
  - {path: native/kernel, mode: owned}
  - {path: tests/fixtures/contracts, mode: read_only}
acceptance_commands:
  - cd native/kernel && cargo test
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `native/kernel/crates/kernel-protocol/src/lib.rs`
- Modify: `native/kernel/crates/kernel-protocol/Cargo.toml`
- Create: `native/kernel/crates/kernel-protocol/tests/fixture_roundtrip.rs`

- [ ] **Step 1: Add Rust fixture round-trip test**

Create `native/kernel/crates/kernel-protocol/tests/fixture_roundtrip.rs`:

```rust
use kernel_protocol::ExecutionRequest;

#[test]
fn reads_shared_kernel_request_fixture() {
    let text = include_str!("../../../../../tests/fixtures/contracts/valid-kernel-request.json");
    let request: ExecutionRequest = serde_json::from_str(text).expect("fixture should parse");

    assert_eq!(request.schema, "kernel.execution_request.v1");
    assert_eq!(request.request_id, "exec_demo");
    assert_eq!(request.argv, vec!["printf".to_string(), "hello".to_string()]);
}
```

- [ ] **Step 2: Add dev dependency**

Modify `native/kernel/crates/kernel-protocol/Cargo.toml`:

```toml
[dev-dependencies]
serde_json.workspace = true
```

- [ ] **Step 3: Verify and commit**

Run:

```bash
cd native/kernel && cargo test
```

Expected: all kernel tests pass.

Commit:

```bash
git add native/kernel
git commit -m "test: mirror kernel contract fixtures in Rust"
```

## Phase 3: Kernel Safety Boundary

### Task 3.1: Add Toolchain And Formatting Gates

```yaml agentrunway-task
task_id: phase3_task_001
title: Add Kernel Toolchain And Formatting Gates
risk: low
phase: implementation
dependencies: [phase2_task_002]
file_claims:
  - {path: native/kernel/rust-toolchain.toml, mode: owned}
  - {path: native/kernel/rustfmt.toml, mode: owned}
  - {path: native/kernel/Cargo.lock, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo fmt --all -- --check
  - cd native/kernel && cargo clippy --workspace --all-targets -- -D warnings
  - cd native/kernel && cargo test
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `native/kernel/rust-toolchain.toml`
- Create: `native/kernel/rustfmt.toml`
- Modify: `native/kernel/Cargo.lock`

- [ ] **Step 1: Pin Rust toolchain**

Create `native/kernel/rust-toolchain.toml`:

```toml
[toolchain]
channel = "stable"
components = ["rustfmt", "clippy"]
```

- [ ] **Step 2: Add Rust formatting policy**

Create `native/kernel/rustfmt.toml`:

```toml
edition = "2024"
max_width = 100
newline_style = "Unix"
```

- [ ] **Step 3: Verify and commit**

Run:

```bash
cd native/kernel
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test
```

Expected: all commands pass.

Commit:

```bash
git add native/kernel/rust-toolchain.toml native/kernel/rustfmt.toml native/kernel/Cargo.lock
git commit -m "chore: pin kernel Rust toolchain"
```

### Task 3.2: Add Process Safety Evidence

```yaml agentrunway-task
task_id: phase3_task_002
title: Add Process Safety Evidence
risk: high
phase: implementation
dependencies: [phase3_task_001]
file_claims:
  - {path: native/kernel/crates/process-supervisor, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo test -p process-supervisor
  - bun test packages/contracts/tests/contracts.test.ts
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `native/kernel/crates/process-supervisor/src/lib.rs`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`

Required behavior:

- process timeout returns `timed_out: true`;
- captured output is bounded and marks truncation;
- result includes stdout/stderr digest fields;
- result includes `changed_files` as an empty list until file snapshotting exists;
- process execution never reads stdin unless the request explicitly supports it.

Verification:

```bash
cd native/kernel && cargo test -p process-supervisor
cd ../.. && bun test packages/contracts/tests/contracts.test.ts
```

Commit:

```bash
git add native/kernel/crates/process-supervisor packages/contracts
git commit -m "feat: add kernel process safety evidence"
```

### Task 3.3: Add Event Journal And Artifact Seal Crates

```yaml agentrunway-task
task_id: phase3_task_003
title: Add Kernel Event Journal And Artifact Seal
risk: medium
phase: implementation
dependencies: [phase3_task_002]
file_claims:
  - {path: native/kernel/crates/event-journal, mode: owned}
  - {path: native/kernel/crates/artifact-seal, mode: owned}
  - {path: native/kernel/Cargo.toml, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo test --workspace
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- `event-journal` appends newline-delimited JSON atomically enough for local
  single-host runs;
- `event-journal` refuses empty event payloads;
- `artifact-seal` returns path, byte length, and SHA-256 digest;
- kernel process results can reference sealed output artifacts without storing
  unbounded text in the event payload.

Verification:

```bash
cd native/kernel
cargo test --workspace
```

Commit:

```bash
git add native/kernel
git commit -m "feat: add kernel event journal and artifact sealing"
```

## Phase 4: Runway Control Plane

### Task 4.1: Implement Durable Task Graph

```yaml agentrunway-task
task_id: phase4_task_001
title: Implement Durable Task Graph
risk: high
phase: implementation
dependencies: [phase2_task_001]
file_claims:
  - {path: packages/runway-control, mode: owned}
acceptance_commands:
  - bun test packages/runway-control/tests/taskGraph.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- task graph stores task id, dependencies, file claims, resource locks, risk,
  status, checkpoint reference, and latest failure class;
- dependencies must be acyclic;
- tasks with missing dependency checkpoints are withheld;
- task status values match the spec status machine.

Verification:

```bash
bun test packages/runway-control/tests/taskGraph.test.ts
bun run typecheck
```

Commit:

```bash
git add packages/runway-control
git commit -m "feat: add durable runway task graph"
```

### Task 4.2: Implement Safe-Wave Scheduler

```yaml agentrunway-task
task_id: phase4_task_002
title: Implement Safe-Wave Scheduler
risk: high
phase: implementation
dependencies: [phase4_task_001]
file_claims:
  - {path: packages/runway-control, mode: owned}
acceptance_commands:
  - bun test packages/runway-control/tests/scheduler.test.ts
  - bun test packages/runway-control/tests/barriers.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- independent low and medium risk tasks can enter one safe wave;
- high risk tasks serialize;
- overlapping owned file claims serialize;
- shared append claims can run together only when no owned claim conflicts;
- stale activities, missing checkpoints, missing resume handlers, and terminal
  failures block dispatch.

Verification:

```bash
bun test packages/runway-control/tests/scheduler.test.ts
bun test packages/runway-control/tests/barriers.test.ts
```

Commit:

```bash
git add packages/runway-control
git commit -m "feat: implement safe-wave scheduling barriers"
```

### Task 4.3: Implement Decision Packets And Recovery Policy

```yaml agentrunway-task
task_id: phase4_task_003
title: Implement Decision Packets And Recovery Policy
risk: high
phase: implementation
dependencies: [phase4_task_002]
file_claims:
  - {path: packages/runway-control, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - bun test packages/runway-control/tests/recovery.test.ts
  - bun test packages/contracts/tests/contracts.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- retryable failures produce bounded retry recommendations;
- non-retryable failures produce human-readable decision packets;
- decision packets include task id, failure class, evidence references, allowed
  actions, blocked actions, and resume input shape;
- no recovery action can create a mutable worktree unless the durable projection
  places the task back into `safe_wave`.

Verification:

```bash
bun test packages/runway-control/tests/recovery.test.ts
bun test packages/contracts/tests/contracts.test.ts
```

Commit:

```bash
git add packages/runway-control packages/contracts
git commit -m "feat: add runway recovery decision packets"
```

## Phase 5: Store And Projectors

### Task 5.1: Implement Artifact Store

```yaml agentrunway-task
task_id: phase5_task_001
title: Implement AgentLens Artifact Store
risk: medium
phase: implementation
dependencies: [phase3_task_003]
file_claims:
  - {path: packages/lens-store, mode: owned}
acceptance_commands:
  - bun test packages/lens-store/tests/artifactStore.test.ts
  - bun test packages/lens-store/tests/eventJournal.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- artifacts are written under a run directory;
- artifact writes create parent directories;
- artifact writes return relative path, byte length, SHA-256 digest, and media
  type;
- the event journal references artifact paths instead of embedding unbounded
  command output.

Verification:

```bash
bun test packages/lens-store/tests/artifactStore.test.ts
bun test packages/lens-store/tests/eventJournal.test.ts
```

Commit:

```bash
git add packages/lens-store
git commit -m "feat: add AgentLens artifact store"
```

### Task 5.2: Implement SQLite Projection Cache

```yaml agentrunway-task
task_id: phase5_task_002
title: Implement SQLite Projection Cache
risk: medium
phase: implementation
dependencies: [phase5_task_001]
file_claims:
  - {path: packages/lens-store, mode: owned}
acceptance_commands:
  - bun test packages/lens-store/tests/sqliteProjection.test.ts
  - bun test packages/lens-store/tests/rebuild.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- SQLite is a rebuildable cache, not the source of truth;
- rebuilding from event journal plus artifacts produces the same run summary;
- corrupt cache rows can be dropped and rebuilt;
- read APIs fall back to filesystem artifacts when the cache is missing.

Verification:

```bash
bun test packages/lens-store/tests/sqliteProjection.test.ts
bun test packages/lens-store/tests/rebuild.test.ts
```

Commit:

```bash
git add packages/lens-store
git commit -m "feat: add rebuildable AgentLens projection cache"
```

### Task 5.3: Implement Trust, Failure, And Timeline Projectors

```yaml agentrunway-task
task_id: phase5_task_003
title: Implement Trust Failure Timeline Projectors
risk: medium
phase: implementation
dependencies: [phase5_task_002, phase4_task_003]
file_claims:
  - {path: packages/lens-projectors, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - bun test packages/lens-projectors/tests/trust.test.ts
  - bun test packages/lens-projectors/tests/failure.test.ts
  - bun test packages/lens-projectors/tests/timeline.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- final agent claims are lower trust than verification artifacts and kernel
  evidence;
- failure projector groups failures by task, failure class, and recovery action;
- timeline projector orders platform, runway, kernel, provider, and lens events;
- insufficient evidence returns `insufficient_evidence`, not `trusted`.

Verification:

```bash
bun test packages/lens-projectors/tests/trust.test.ts
bun test packages/lens-projectors/tests/failure.test.ts
bun test packages/lens-projectors/tests/timeline.test.ts
```

Commit:

```bash
git add packages/lens-projectors packages/contracts
git commit -m "feat: add AgentLens trust and failure projectors"
```

## Phase 6: Worktree And Patch Apply

### Task 6.1: Add Kernel Git Worktree Crate

```yaml agentrunway-task
task_id: phase6_task_001
title: Add Kernel Git Worktree Crate
risk: high
phase: implementation
dependencies: [phase3_task_003]
file_claims:
  - {path: native/kernel/crates/git-worktree, mode: owned}
  - {path: native/kernel/Cargo.toml, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo test -p git-worktree
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- create run-main worktree from source checkout;
- create candidate worktree from run-main checkpoint;
- detect dirty source checkout before explicit apply;
- create checkpoint commit refs;
- cleanup only worktrees owned by the current run id.

Verification:

```bash
cd native/kernel && cargo test -p git-worktree
```

Commit:

```bash
git add native/kernel
git commit -m "feat: add kernel git worktree boundary"
```

### Task 6.2: Add Patch Dry-Run And Apply Diagnostics

```yaml agentrunway-task
task_id: phase6_task_002
title: Add Patch Dry-Run And Apply Diagnostics
risk: high
phase: implementation
dependencies: [phase6_task_001]
file_claims:
  - {path: native/kernel/crates/diff-apply, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo test -p diff-apply
  - bun test packages/contracts/tests/contracts.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- parse unified diff patches;
- reject paths outside the candidate worktree;
- dry-run patch application and report exact failing hunks;
- detect already-applied hunks;
- return changed file list and diagnostics as structured evidence.

Verification:

```bash
cd native/kernel && cargo test -p diff-apply
cd ../.. && bun test packages/contracts/tests/contracts.test.ts
```

Commit:

```bash
git add native/kernel packages/contracts
git commit -m "feat: add kernel patch apply diagnostics"
```

### Task 6.3: Wire Merge Checkpoint And Explicit Apply

```yaml agentrunway-task
task_id: phase6_task_003
title: Wire Merge Checkpoint And Explicit Apply
risk: high
phase: implementation
dependencies: [phase6_task_002, phase4_task_003, phase5_task_003]
file_claims:
  - {path: packages/runway-control, mode: owned}
  - {path: packages/kernel-client, mode: owned}
  - {path: packages/lens-store, mode: shared_append}
acceptance_commands:
  - bun test packages/runway-control/tests/mergeApply.test.ts
  - bun test packages/kernel-client/tests/worktreeClient.test.ts
  - bun run check
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- selected candidates merge into run-main only after review and verification;
- merge writes a checkpoint event and checkpoint artifact;
- explicit apply refuses dirty source checkout;
- apply writes `runway.apply_completed` only after source checkout mutation
  succeeds;
- merge conflicts create a failure barrier and decision packet.

Verification:

```bash
bun test packages/runway-control/tests/mergeApply.test.ts
bun test packages/kernel-client/tests/worktreeClient.test.ts
bun run check
```

Commit:

```bash
git add packages/runway-control packages/kernel-client packages/lens-store
git commit -m "feat: wire merge checkpoint and explicit apply"
```

## Phase 7: Provider Adapters

### Task 7.1: Add Capability Manifests

```yaml agentrunway-task
task_id: phase7_task_001
title: Add Provider Capability Manifests
risk: medium
phase: implementation
dependencies: [phase2_task_001]
file_claims:
  - {path: packages/provider-adapters, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - bun test packages/provider-adapters/tests/capabilities.test.ts
  - bun test packages/contracts/tests/contracts.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- every adapter declares provider name, supported modes, tool call support,
  file edit support, shell support, streaming support, approval support, and
  result artifact shape;
- scheduler and policy can reject a provider before execution when capability
  requirements are unmet.

Verification:

```bash
bun test packages/provider-adapters/tests/capabilities.test.ts
bun test packages/contracts/tests/contracts.test.ts
```

Commit:

```bash
git add packages/provider-adapters packages/contracts
git commit -m "feat: add provider capability manifests"
```

### Task 7.2: Add Codex And Claude Process Adapters

```yaml agentrunway-task
task_id: phase7_task_002
title: Add Codex And Claude Process Adapters
risk: high
phase: implementation
dependencies: [phase7_task_001, phase3_task_002]
file_claims:
  - {path: packages/provider-adapters, mode: owned}
  - {path: tests/fixtures/provider-adapters, mode: owned}
acceptance_commands:
  - bun test packages/provider-adapters/tests/codexAdapter.test.ts
  - bun test packages/provider-adapters/tests/claudeAdapter.test.ts
  - bun test packages/provider-adapters/tests/fakeProvider.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- default adapter tests use fake CLI fixtures and make no live model calls;
- Codex and Claude adapter outputs normalize into `runway.worker_result.v1`;
- malformed provider output produces `malformed_result`;
- process crash produces `adapter_crashed`;
- live smoke commands are opt-in through environment variables.

Verification:

```bash
bun test packages/provider-adapters/tests/codexAdapter.test.ts
bun test packages/provider-adapters/tests/claudeAdapter.test.ts
bun test packages/provider-adapters/tests/fakeProvider.test.ts
```

Commit:

```bash
git add packages/provider-adapters tests/fixtures/provider-adapters
git commit -m "feat: add Codex and Claude provider adapters"
```

### Task 7.3: Add Optional ACP-Compatible Adapter Boundary

```yaml agentrunway-task
task_id: phase7_task_003
title: Add ACP Compatible Adapter Boundary
risk: medium
phase: implementation
dependencies: [phase7_task_002]
file_claims:
  - {path: packages/provider-adapters, mode: owned}
acceptance_commands:
  - bun test packages/provider-adapters/tests/acpAdapter.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- ACP-style adapters normalize provider events without changing scheduler
  contracts;
- unsupported ACP capabilities fail before worker dispatch;
- provider-native transcripts are stored as artifacts, not scheduler truth.

Verification:

```bash
bun test packages/provider-adapters/tests/acpAdapter.test.ts
```

Commit:

```bash
git add packages/provider-adapters
git commit -m "feat: add ACP provider adapter boundary"
```

## Phase 8: Policy And Permissions

### Task 8.1: Implement Policy Rule Engine

```yaml agentrunway-task
task_id: phase8_task_001
title: Implement Policy Rule Engine
risk: high
phase: implementation
dependencies: [phase2_task_001]
file_claims:
  - {path: packages/policy, mode: owned}
  - {path: packages/contracts, mode: shared_append}
acceptance_commands:
  - bun test packages/policy/tests/policy.test.ts
  - bun test packages/policy/tests/permissionProfile.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- mode hierarchy supports `plan`, `read`, `execute`, `auto_edit`, `recovery`,
  and `yolo`;
- filesystem rules include read, write, deny, and path canonicalization request
  shape;
- network rules support disabled, localhost-only, and explicit allow lists;
- command prefix rules explain denials;
- every decision returns an operator-facing reason.

Verification:

```bash
bun test packages/policy/tests/policy.test.ts
bun test packages/policy/tests/permissionProfile.test.ts
```

Commit:

```bash
git add packages/policy packages/contracts
git commit -m "feat: add Waygent policy rule engine"
```

### Task 8.2: Enforce Policy Through Kernel Requests

```yaml agentrunway-task
task_id: phase8_task_002
title: Enforce Policy Through Kernel Requests
risk: high
phase: implementation
dependencies: [phase8_task_001, phase3_task_002]
file_claims:
  - {path: packages/kernel-client, mode: owned}
  - {path: native/kernel/crates/sandbox-policy, mode: owned}
  - {path: packages/policy, mode: shared_append}
acceptance_commands:
  - bun test packages/kernel-client/tests/permission.test.ts
  - cd native/kernel && cargo test -p sandbox-policy
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- Bun policy decision is included in every kernel request;
- Rust kernel revalidates path, command, and network policy before side effects;
- denial returns structured evidence and writes `kernel.exec_completed` with
  failed outcome;
- no Bun package can bypass kernel validation for irreversible effects.

Verification:

```bash
bun test packages/kernel-client/tests/permission.test.ts
cd native/kernel && cargo test -p sandbox-policy
```

Commit:

```bash
git add packages/kernel-client packages/policy native/kernel
git commit -m "feat: enforce permissions through kernel boundary"
```

## Phase 9: Orchestrator, CLI, And API

### Task 9.1: Implement Waygent Orchestrator

```yaml agentrunway-task
task_id: phase9_task_001
title: Implement Waygent Orchestrator
risk: high
phase: implementation
dependencies: [phase4_task_003, phase5_task_003, phase7_task_002, phase8_task_002]
file_claims:
  - {path: packages/orchestrator, mode: owned}
  - {path: apps/cli, mode: shared_append}
acceptance_commands:
  - bun test packages/orchestrator/tests/orchestrator.test.ts
  - bun run platform:demo
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- orchestrator opens a run, writes contract snapshot, selects provider profile,
  computes safe wave, launches adapter through kernel client, records evidence,
  runs gates, updates projectors, and stops before explicit apply;
- fake provider path remains deterministic and offline;
- failed provider path creates a decision packet.

Verification:

```bash
bun test packages/orchestrator/tests/orchestrator.test.ts
bun run platform:demo
```

Commit:

```bash
git add packages/orchestrator apps/cli
git commit -m "feat: add Waygent orchestrator run lifecycle"
```

### Task 9.2: Implement CLI Commands

```yaml agentrunway-task
task_id: phase9_task_002
title: Implement Waygent CLI Commands
risk: medium
phase: implementation
dependencies: [phase9_task_001]
file_claims:
  - {path: apps/cli, mode: owned}
acceptance_commands:
  - bun test apps/cli/tests/cli.test.ts
  - bun run platform:demo
required_skills: [test-driven-development]
serial: true
```

Required commands:

- `waygent run --plan <path> --spec <path> --adapter fake`;
- `waygent status --run <run_id>`;
- `waygent events --run <run_id> --json`;
- `waygent inspect --run <run_id> --json`;
- `waygent apply --run <run_id>`.

Verification:

```bash
bun test apps/cli/tests/cli.test.ts
bun run platform:demo
```

Commit:

```bash
git add apps/cli
git commit -m "feat: add Waygent CLI commands"
```

### Task 9.3: Implement Local API And Event Stream

```yaml agentrunway-task
task_id: phase9_task_003
title: Implement Local API And Event Stream
risk: medium
phase: implementation
dependencies: [phase9_task_002, phase5_task_003]
file_claims:
  - {path: apps/api, mode: owned}
  - {path: packages/lens-store, mode: shared_append}
acceptance_commands:
  - bun test apps/api/tests/api.test.ts
  - bun test apps/api/tests/events.test.ts
required_skills: [test-driven-development]
serial: true
```

Required routes:

- `GET /healthz`;
- `GET /runs`;
- `GET /runs/:runId`;
- `GET /runs/:runId/events`;
- `GET /runs/:runId/trust`;
- `GET /runs/:runId/failures`;
- `GET /events/stream`.

Verification:

```bash
bun test apps/api/tests/api.test.ts
bun test apps/api/tests/events.test.ts
```

Commit:

```bash
git add apps/api packages/lens-store
git commit -m "feat: add Waygent local API"
```

## Phase 10: Context Packer

### Task 10.1: Implement Graphify-Free Repo Map

```yaml agentrunway-task
task_id: phase10_task_001
title: Implement Graphify Free Repo Map
risk: medium
phase: implementation
dependencies: [phase2_task_001]
file_claims:
  - {path: packages/context-packer, mode: owned}
acceptance_commands:
  - bun test packages/context-packer/tests/repoMap.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- use `rg --files` compatible file discovery;
- respect ignored directories such as `node_modules`, `target`, `.git`, and
  generated output;
- produce a bounded repo map with file path, extension, byte size, and shallow
  symbol summary when available;
- do not read or write `graphify-out`.

Verification:

```bash
bun test packages/context-packer/tests/repoMap.test.ts
```

Commit:

```bash
git add packages/context-packer
git commit -m "feat: add Graphify-free context packer"
```

### Task 10.2: Implement Task-Scoped Context Selection

```yaml agentrunway-task
task_id: phase10_task_002
title: Implement Task Scoped Context Selection
risk: medium
phase: implementation
dependencies: [phase10_task_001, phase4_task_001]
file_claims:
  - {path: packages/context-packer, mode: owned}
  - {path: packages/runway-control, mode: shared_append}
acceptance_commands:
  - bun test packages/context-packer/tests/taskContext.test.ts
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- file claims seed context selection;
- recent failure evidence can add context paths;
- context packet reports included paths and excluded paths with reasons;
- context packet has deterministic ordering and byte limits.

Verification:

```bash
bun test packages/context-packer/tests/taskContext.test.ts
```

Commit:

```bash
git add packages/context-packer packages/runway-control
git commit -m "feat: add task-scoped context packets"
```

## Phase 11: Lens Web Console

### Task 11.1: Create Operator Console Shell

```yaml agentrunway-task
task_id: phase11_task_001
title: Create Lens Web Operator Console Shell
risk: medium
phase: implementation
dependencies: [phase9_task_003]
file_claims:
  - {path: apps/lens-web, mode: owned}
acceptance_commands:
  - bun test apps/lens-web/src
  - bun run --cwd apps/lens-web build
required_skills: [test-driven-development]
serial: true
```

Required views:

- run list;
- run detail;
- task timeline;
- event timeline;
- trust report;
- failure barriers;
- decision packets;
- apply status.

Verification:

```bash
bun test apps/lens-web/src
bun run --cwd apps/lens-web build
```

Commit:

```bash
git add apps/lens-web
git commit -m "feat: add AgentLens operator console shell"
```

### Task 11.2: Add Browser E2E Coverage

```yaml agentrunway-task
task_id: phase11_task_002
title: Add Lens Web Browser E2E Coverage
risk: medium
phase: verification
dependencies: [phase11_task_001]
file_claims:
  - {path: tests/e2e, mode: owned}
  - {path: apps/lens-web, mode: shared_append}
acceptance_commands:
  - bun run --cwd apps/lens-web test:e2e
required_skills: [test-driven-development]
serial: true
```

Required scenarios:

- run list loads demo run;
- run detail shows three canonical event families;
- trust report displays `trusted`, `failed`, and `insufficient_evidence`;
- decision packet is visible when a run is blocked;
- apply status is visible and cannot be triggered from a dirty source checkout.

Verification:

```bash
bun run --cwd apps/lens-web test:e2e
```

Commit:

```bash
git add apps/lens-web tests/e2e
git commit -m "test: add AgentLens console e2e coverage"
```

## Phase 12: Migration And Legacy Removal

### Task 12.1: Add Legacy Exclusion Checks

```yaml agentrunway-task
task_id: phase12_task_001
title: Add Legacy Exclusion Checks
risk: medium
phase: verification
dependencies: [phase11_task_002]
file_claims:
  - {path: packages/testkit, mode: owned}
  - {path: package.json, mode: shared_append}
acceptance_commands:
  - bun run check:legacy
required_skills: [test-driven-development]
serial: true
```

Required checks:

- `packages`, `apps`, `native`, and `tests` contain no Python runtime files;
- no product package imports or executes Graphify;
- no product event fixture uses `kws-cpe` or `kws-cme`;
- old `AgentLens/` and `skills/agent-runway/` remain outside the Waygent
  product tree until explicitly archived or removed by a separate cleanup task.

Verification:

```bash
bun run check:legacy
```

Commit:

```bash
git add packages/testkit package.json
git commit -m "test: add Waygent legacy exclusion checks"
```

### Task 12.2: Archive Or Remove Legacy Runtime References

```yaml agentrunway-task
task_id: phase12_task_002
title: Archive Or Remove Legacy Runtime References
risk: high
phase: migration
dependencies: [phase12_task_001]
file_claims:
  - {path: AgentLens, mode: owned}
  - {path: skills/agent-runway, mode: owned}
  - {path: docs, mode: shared_append}
acceptance_commands:
  - bun run check
  - bun run check:legacy
  - cd native/kernel && cargo test --workspace
required_skills: [test-driven-development]
serial: true
```

Required behavior:

- removal happens only after the Waygent CLI, API, kernel, store, adapters, and
  web console pass full verification;
- any retained old material is marked as archived reference, not runtime path;
- docs index points to Waygent specs and plans as the active path;
- no command in `package.json`, `apps`, `packages`, `native`, or `tests` calls
  old Python entrypoints.

Verification:

```bash
bun run check
bun run check:legacy
cd native/kernel && cargo test --workspace
```

Commit:

```bash
git add AgentLens skills/agent-runway docs package.json
git commit -m "chore: remove legacy runtime references from Waygent"
```

## Full Verification

Run from repository root:

```bash
bun install
bun run check
bun run platform:demo
bun run check:legacy
cd native/kernel
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cd ../..
git diff --check
```

Expected:

- Bun install succeeds.
- TypeScript typecheck succeeds.
- All Bun tests pass.
- Deterministic demo prints a trusted run.
- Legacy exclusion checks pass.
- Rust formatting, clippy, and tests pass.
- `git diff --check` prints no output.

## Spec Coverage Review

This program covers the source spec as follows:

- Decision and product roles: Phases 1, 9, and 12.
- Full Rust carry-forward strategy: Phases 2 and 3.
- Target repository structure: Phases 1 through 3, 9, and 11.
- `packages/contracts`: Phase 2.
- `packages/runway-control`: Phase 4.
- `packages/lens-store`: Phase 5.
- `packages/lens-projectors`: Phase 5.
- `packages/provider-adapters`: Phase 7.
- `packages/policy`: Phase 8.
- `packages/context-packer`: Phase 10.
- `native/kernel`: Phases 3, 6, and 8.
- Data flow: Phases 4 through 9.
- Durable state model: Phases 4 and 5.
- Status machine: Phase 4.
- Failure and recovery: Phase 4.
- Permission and kernel request model: Phase 8.
- AgentLens event model: Phases 2, 5, and 9.
- Testing strategy: all phases plus Full Verification.
- Migration position: Phase 12.
- Recommended first slice: Phase 1.

## Execution Order

Execute phases in numeric order. Within a phase, tasks can run in parallel only
when their file claims do not overlap and their dependencies are complete.
Shared-core tasks in `packages/runway-control`, `packages/contracts`,
`native/kernel`, and `packages/orchestrator` should run serially unless a later
task explicitly narrows its file claims.
