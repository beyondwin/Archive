# Waygent Codex Superpowers P0 Trust Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent execution evidence durable and safe before adding richer Superpowers or Codex orchestration.

**Architecture:** Add immutable execution identities and artifacts, fail-closed Codex startup, normalized command observations, failure circuits, and sealed additive `agentlens.event.v3` journals. Roll out state migration as `legacy → dual → sealed`; TypeScript Lens remains the canonical writer and Rust implements conformance primitives.

**Tech Stack:** Bun, TypeScript, `bun:test`, Node filesystem primitives, JSON/JSONL, Rust, Cargo.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- Preserve historical `agentlens.event.v3` reads; require sealed additive fields only for new production writes.
- Emit only `platform.*`, `runway.*`, `kernel.*`, and `lens.*` namespaces.
- Historical state-only/unsealed runs remain readable and immutable.
- No implicit `danger-full-access`; no insecure fallback when sandbox preflight fails.
- New attempts, verifications, observations, events, and artifacts are immutable and unique.
- Raw provider I/O is off by default and never embedded in state/events.
- `WAYGENT_DISPATCH_DISABLED=1` must stop all worker dispatch.
- `WAYGENT_JOURNAL_WRITE_MODE=legacy|dual|sealed` is the migration switch; rollback freezes mutation instead of downgrading a sealed run.
- P0 introduces `waygent.integrity_manifest.v1`; P1 supersedes it with the full RunManifest through explicit lineage.
- `P0_ACCEPTED` is deterministic and offline; optional live evidence is reported separately as `P0_LIVE_OBSERVED` and cannot block or satisfy P0.
- Every helper, fixture, and local constant shown in a test snippet is defined in that named test file and returns the exact contract fields asserted by the task; do not rely on undeclared global test state.

## File Structure

- `packages/contracts/src/ids.ts`: branded IDs and monotonic allocation helpers.
- `packages/contracts/src/types.ts`, `schemas.ts`: additive integrity, observation, failure and lease contracts.
- `packages/lens-store/src/{canonicalJson,writerLease,journalIntegrity,atomicProjection,permissions,redaction,retention}.ts`: focused durability/security primitives.
- `packages/orchestrator/src/{executionIdentity,commandObservation,failureFingerprint,failureCircuit,journalMigration,runStateProjector}.ts`: orchestration policy over P0 primitives.
- `packages/provider-adapters/src/providerPreflight.ts`: Codex executable/schema/startup gate.
- `native/kernel/crates/*`: protocol and enforcement parity; not a second canonical store.

## Task Ownership And Risk

| Task | Owner boundary | Risk | Dependency |
| --- | --- | --- | --- |
| 1 | contracts plus the minimal integrity-manifest compiler/writer only | high | none |
| 2 | provider preflight and secure Codex process configuration | high | Task 1 |
| 3 | execution identity, artifact naming and immutable artifact storage | high | Task 2 |
| 4 | command observation, classification and retry circuit | high | Task 3 |
| 5 | journal, lease and projection transaction | high | Task 4 |
| 6 | historical read and dual/sealed migration | high | Task 5 |
| 7 | filesystem privacy, redaction and retention | high | Task 6 |
| 8 | Rust conformance and deterministic P0 evaluator | high | Task 7 |

Tasks are sequential because Tasks 2 and 3 both change orchestrator dispatch.
Each commit stages only the exact paths in its task `Files` block; directory-wide
or repository-wide staging is forbidden.

---

### Task 1: Add Integrity Contracts And Unique IDs

**Files:**

- Modify: `packages/contracts/src/ids.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/src/validate.ts`
- Modify: `packages/contracts/src/index.ts`
- Create: `packages/contracts/tests/integrityContracts.test.ts`
- Create: `packages/contracts/tests/mixedEventCompatibility.test.ts`
- Create: `packages/orchestrator/src/integrityManifest.ts`
- Create: `packages/orchestrator/tests/integrityManifest.test.ts`

**Interfaces:**

- Produces: `newAttemptId`, `newVerificationId`, `newObservationId`.
- Produces: `CommandObservation`, `FailureFingerprint`, `WriterLease`, `SealedAgentLensEvent`.
- Produces: `compileIntegrityManifest`, `writeImmutableIntegrityManifest`, `waygent.integrity_manifest.v1` before any production event append.
- Produces: `validateAgentLensEventForWrite(value)` while existing read validation remains compatible.

- [ ] **Step 1: Write failing contract tests**

```ts
import { expect, test } from "bun:test";
import {
  newAttemptId,
  newVerificationId,
  validateAgentLensEventForWrite,
  validateContract
} from "../src";

test("execution identities never repeat", () => {
  expect(newAttemptId()).not.toBe(newAttemptId());
  expect(newVerificationId()).not.toBe(newVerificationId());
});

test("historical v3 reads but production write requires sealing", () => {
  const historical = fixtureHistoricalEvent();
  expect(validateContract("agentlens.event.v3", historical)).toBeTruthy();
  expect(() => validateAgentLensEventForWrite(historical)).toThrow("event_not_sealed");
});

test("integrity manifest is sealed before its hash can enter an event", () => {
  const manifest = compileIntegrityManifest(integrityManifestInput());
  const ref = writeImmutableIntegrityManifest(runRoot, manifest);
  expect(ref.sha256).toBe(manifest.manifest_hash);
  expect(() => writeImmutableIntegrityManifest(runRoot, changedManifest()))
    .toThrow("integrity_manifest_collision");
});
```

Define a valid historical-event helper in this test file for `fixtureHistoricalEvent()` and
add a sealed fixture whose `event_type` is `runway.task_started`. Assert a
`context.packet_budget_evaluated` sealed write is rejected as
`inactive_event_namespace`.

- [ ] **Step 2: Run RED**

```bash
bun test packages/contracts/tests/integrityContracts.test.ts \
  packages/contracts/tests/mixedEventCompatibility.test.ts \
  packages/orchestrator/tests/integrityManifest.test.ts
```

Expected: FAIL because the new exports and sealed writer validator do not exist.

- [ ] **Step 3: Add exact additive contracts**

```ts
export interface SealedAgentLensEvent extends AgentLensEvent {
  task_id: string | null;
  attempt_id: string | null;
  verification_id: string | null;
  parent_event_id: string | null;
  causation_id: string;
  correlation_id: string;
  idempotency_key: string;
  manifest_hash: string;
  persisted_at: string;
  previous_event_hash: string | null;
  event_hash: string;
}

export interface CommandObservation {
  schema: "waygent.command_observation.v1";
  observation_id: string;
  run_id: string;
  task_id: string;
  attempt_id: string | null;
  verification_id: string | null;
  executable: string;
  argv: string[];
  shell_mode: "direct" | "bash-lc";
  cwd: string;
  cwd_shape: string;
  allowed_environment_fingerprint: string;
  started_at: string;
  completed_at: string;
  timeout_ms: number;
  exit_code: number | null;
  signal: string | null;
  timed_out: boolean;
  executable_present: boolean;
  stdout_ref: string;
  stderr_ref: string;
  stdout_sha256: string;
  stderr_sha256: string;
  normalized_error_signature: string | null;
  before_diff_hash: string | null;
  after_diff_hash: string | null;
}

export interface IntegrityManifestV1 {
  schema: "waygent.integrity_manifest.v1";
  manifest_hash: string;
  plan_sha256: string;
  spec_sha256: string;
  base_commit: string;
  provider_profile_sha256: string;
  retention_policy_sha256: string;
}

export interface WriterLease {
  schema: "waygent.writer_lease.v1";
  lease_id: string;
  run_id: string;
  owner_id: string;
  generation: number;
  acquired_at: string;
  heartbeat_at: string;
  expires_at: string;
  previous_lease_sha256: string | null;
}

export interface WriterLeaseAcquireInput {
  run_id: string;
  owner_id: string;
  expected_generation: number;
  previous_lease_sha256: string | null;
  ttl_ms: number;
}
```

Use `crypto.randomUUID()` for identity allocation. Keep additive fields optional
in the general v3 read schema and required in `validateAgentLensEventForWrite`.
Compile and exclusively persist the integrity manifest after provider preflight
and before the first production event; the writer accepts only a verified
persisted manifest reference, never an arbitrary hash string.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/contracts/tests/integrityContracts.test.ts \
  packages/contracts/tests/mixedEventCompatibility.test.ts \
  packages/orchestrator/tests/integrityManifest.test.ts
git add -- packages/contracts/src/ids.ts packages/contracts/src/types.ts \
  packages/contracts/src/schemas.ts packages/contracts/src/validate.ts \
  packages/contracts/src/index.ts packages/contracts/tests/integrityContracts.test.ts \
  packages/contracts/tests/mixedEventCompatibility.test.ts \
  packages/orchestrator/src/integrityManifest.ts \
  packages/orchestrator/tests/integrityManifest.test.ts
git commit -m "feat(contracts): add Waygent integrity identities"
```

### Task 2: Fail Fast Before Codex Dispatch And Remove Insecure Defaults

**Files:**

- Create: `packages/provider-adapters/src/providerPreflight.ts`
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/capabilityProbe.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/provider-adapters/tests/providerPreflight.test.ts`
- Create: `packages/orchestrator/tests/providerStartupRegression.test.ts`
- Modify: `packages/provider-adapters/tests/envSanitize.test.ts`

**Interfaces:**

- Produces: `preflightProvider("codex", options): Promise<ProviderPreflightResult>`.
- Produces: explicit `CodexWorkerSandboxPolicy` input to `prepareCodexWorkerHomeEnv`.
- Guarantees: blocked preflight creates zero provider attempts and zero verifications.

- [ ] **Step 1: Write the startup and sandbox RED tests**

```ts
test("missing Codex blocks before dispatch", async () => {
  const result = await preflightProvider("codex", {
    executable: "/missing/codex",
    args: ["exec", "--json", "-"]
  });
  expect(result.status).toBe("blocked");
  expect(result.failure_class).toBe("provider_startup");
});

test("worker home never enables danger full access", () => {
  const prepared = prepareCodexWorkerHomeEnv(envWithFixtureAuth(), worktree, {
    mode: "workspace-write",
    writable_root: worktree,
    network: "disabled",
    approval_policy: "never"
  });
  expect(Bun.file(`${prepared.env.CODEX_HOME}/config.toml`).text())
    .resolves.not.toContain("danger-full-access");
});
```

The orchestrator regression fixture must assert `provider_attempts.length === 0`
and `verification.length === 0` after a blocked startup.

- [ ] **Step 2: Run RED**

```bash
bun test packages/provider-adapters/tests/providerPreflight.test.ts \
  packages/provider-adapters/tests/envSanitize.test.ts \
  packages/orchestrator/tests/providerStartupRegression.test.ts
```

Expected: missing preflight exports; current config contains
`danger-full-access`; dispatch continues after capability probe failure.

- [ ] **Step 3: Implement fail-closed preflight**

```ts
export interface ProviderPreflightResult {
  status: "ready" | "blocked";
  failure_class: "provider_startup" | null;
  executable: string;
  executable_present: boolean;
  version: string | null;
  schema_compatible: boolean;
  observation: CommandObservation;
}
```

Resolve executable candidates without basename shortcuts, execute a bounded
`--version` probe, and stop the run before worktree/provider/verification
dispatch when status is blocked. Generate `read-only` or `workspace-write`
Codex config with the task worktree as the sole writable root and network off.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/provider-adapters/tests/providerPreflight.test.ts \
  packages/provider-adapters/tests/envSanitize.test.ts \
  packages/orchestrator/tests/providerStartupRegression.test.ts
git add -- packages/provider-adapters/src/providerPreflight.ts \
  packages/provider-adapters/src/types.ts packages/provider-adapters/src/capabilityProbe.ts \
  packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/src/codexAdapter.ts \
  packages/provider-adapters/src/index.ts packages/provider-adapters/tests/providerPreflight.test.ts \
  packages/provider-adapters/tests/envSanitize.test.ts packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/providerStartupRegression.test.ts
git commit -m "fix(waygent): fail closed before Codex dispatch"
```

### Task 3: Make Attempts, Verifications And Artifacts Immutable

**Files:**

- Create: `packages/orchestrator/src/executionIdentity.ts`
- Create: `packages/orchestrator/src/artifactNaming.ts`
- Modify: `packages/lens-store/src/artifactStore.ts`
- Modify: `packages/lens-store/src/paths.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/verification.ts`
- Modify: `packages/orchestrator/src/checkpointArtifacts.ts`
- Modify: `packages/orchestrator/src/artifactIndex.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/orchestrator/tests/executionIdentity.test.ts`
- Modify: `packages/lens-store/tests/artifactStore.test.ts`
- Modify: `packages/orchestrator/tests/checkpointArtifacts.test.ts`

**Interfaces:**

- Produces: `allocateExecutionIdentity(priorAttemptIds)`.
- Produces: `writeImmutableArtifact(input)` with collision detection and `0600` mode.
- Changes: verification request IDs include immutable verification ID and attempt lineage.

- [ ] **Step 1: Write RED tests for overwrite and repeated IDs**

```ts
test("different bytes cannot overwrite one artifact ref", () => {
  writeImmutableArtifact(fixtureArtifact("attempt-a", "one"));
  expect(() => writeImmutableArtifact(fixtureArtifact("attempt-a", "two")))
    .toThrow("artifact_collision");
});

test("retry allocates new attempt and verification ids", async () => {
  const first = allocateExecutionIdentity([]);
  const second = allocateExecutionIdentity([first.attempt_id]);
  expect(second.attempt_id).not.toBe(first.attempt_id);
  expect(second.attempt_number).toBe(2);
});
```

Add a checkpoint test asserting dry-run evidence creates a new artifact and does
not mutate the checkpoint manifest bytes.

- [ ] **Step 2: Run RED**

```bash
bun test packages/lens-store/tests/artifactStore.test.ts \
  packages/orchestrator/tests/executionIdentity.test.ts \
  packages/orchestrator/tests/checkpointArtifacts.test.ts
```

Expected: second writes overwrite; attempt IDs stay `attempt_<task>_1`;
verification IDs repeat; dry-run changes the manifest.

- [ ] **Step 3: Implement immutable owner-based naming**

```ts
export function writeImmutableArtifact(input: {
  run_root: string;
  owner: { kind: "attempt" | "verification" | "run"; id: string };
  name: string;
  data: string | Uint8Array;
  media_type: string;
  retention_class: "canonical" | "redacted_evidence" | "raw_ephemeral";
}): ArtifactReference;
```

Use exclusive create (`flag: "wx"`, mode `0o600`). Permit exact-byte idempotent
reuse only after digest equality. Store packet, stdin summary, worker result,
verification, checkpoint and dry-run artifacts below their immutable owner ID.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/lens-store/tests/artifactStore.test.ts \
  packages/orchestrator/tests/executionIdentity.test.ts \
  packages/orchestrator/tests/checkpointArtifacts.test.ts
git add -- packages/orchestrator/src/executionIdentity.ts \
  packages/orchestrator/src/artifactNaming.ts packages/lens-store/src/artifactStore.ts \
  packages/lens-store/src/paths.ts packages/orchestrator/src/taskExecutor.ts \
  packages/orchestrator/src/verification.ts packages/orchestrator/src/checkpointArtifacts.ts \
  packages/orchestrator/src/artifactIndex.ts packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/executionIdentity.test.ts packages/lens-store/tests/artifactStore.test.ts \
  packages/orchestrator/tests/checkpointArtifacts.test.ts
git commit -m "feat(waygent): preserve immutable attempt evidence"
```

### Task 4: Normalize Commands And Stop Unchanged Failure Loops

**Files:**

- Create: `packages/orchestrator/src/commandObservation.ts`
- Create: `packages/orchestrator/src/failureFingerprint.ts`
- Create: `packages/orchestrator/src/failureCircuit.ts`
- Modify: `packages/kernel-client/src/kernelClient.ts`
- Modify: `packages/orchestrator/src/verification.ts`
- Modify: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/src/failureEvidence.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Create: `packages/orchestrator/tests/commandObservation.test.ts`
- Create: `packages/orchestrator/tests/failureCircuit.test.ts`
- Create: `packages/orchestrator/tests/spacePathVerification.test.ts`

**Interfaces:**

- Produces: `buildCommandObservation`, `fingerprintFailure`, `evaluateFailureCircuit`.
- Guarantees: unchanged fingerprint blocks; flaky result gets at most two isolated reruns; harness/environment/provider failures never dispatch product repair.

- [ ] **Step 1: Write RED tests from observed failures**

```ts
test("unchanged fingerprint opens the circuit", () => {
  const fingerprint = fingerprintFailure(fixtureFailure());
  expect(evaluateFailureCircuit({
    fingerprint,
    previous_fingerprints: [fingerprint],
    flaky_reruns_used: 0
  })).toEqual({ state: "open", action: "block", reason: "unchanged_failure" });
});

test("space containing cwd remains one argv value", async () => {
  const result = await runVerificationCommands(spacePathFixture());
  expect(result.results[0]?.exit_code).toBe(0);
  expect(result.observations[0]?.cwd).toContain("Application Support");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/commandObservation.test.ts \
  packages/orchestrator/tests/failureCircuit.test.ts \
  packages/orchestrator/tests/spacePathVerification.test.ts
```

Expected: modules are absent; current recovery retries by count only.

- [ ] **Step 3: Implement stable observations and fingerprint policy**

Hash normalized executable/argv/cwd-shape/allowed-env/exit/signal/stderr
signature/input-diff. Extend recovery actions with `repair`,
`isolated_rerun`, and `block`; preserve old failure names for historical reads
and map new writes to `provider_startup`, `environment`, `harness_bug`,
`product_bug`, `verification_flaky`, `integration_conflict`, `policy_denied`,
or `spec_conflict`.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/commandObservation.test.ts \
  packages/orchestrator/tests/failureCircuit.test.ts \
  packages/orchestrator/tests/spacePathVerification.test.ts
git add -- packages/orchestrator/src/commandObservation.ts \
  packages/orchestrator/src/failureFingerprint.ts packages/orchestrator/src/failureCircuit.ts \
  packages/kernel-client/src/kernelClient.ts packages/orchestrator/src/verification.ts \
  packages/orchestrator/src/recoveryExecutor.ts packages/orchestrator/src/failureEvidence.ts \
  packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/commandObservation.test.ts \
  packages/orchestrator/tests/failureCircuit.test.ts \
  packages/orchestrator/tests/spacePathVerification.test.ts
git commit -m "feat(waygent): classify failures before recovery"
```

### Task 5: Add Sealed Journal, Writer Fencing And Atomic Projections

**Files:**

- Create: `packages/lens-store/src/canonicalJson.ts`
- Create: `packages/lens-store/src/writerLease.ts`
- Create: `packages/lens-store/src/journalIntegrity.ts`
- Create: `packages/lens-store/src/atomicProjection.ts`
- Modify: `packages/lens-store/src/eventJournal.ts`
- Modify: `packages/lens-store/src/paths.ts`
- Modify: `packages/lens-store/src/projection.ts`
- Modify: `packages/lens-store/src/sqliteProjection.ts`
- Modify: `packages/lens-store/tests/eventJournal.test.ts`
- Modify: `packages/orchestrator/src/runEvents.ts`
- Modify: `packages/orchestrator/src/runExecutionContext.ts`
- Modify: `packages/orchestrator/src/runState.ts`
- Create: `packages/lens-store/tests/writerLease.test.ts`
- Create: `packages/lens-store/tests/journalFaults.test.ts`
- Create: `packages/lens-store/tests/mixedJournal.test.ts`
- Create: `packages/orchestrator/tests/firstEventManifest.test.ts`

**Interfaces:**

- Produces: `acquireWriterLease`, `renewWriterLease`, `takeOverExpiredWriterLease`, `appendSealedEvent`, `verifyJournalIntegrity`, `writeProjectionAtomic`.
- Replaces split append/mutate/flush with `commitTransition`.

- [ ] **Step 1: Write corruption and fencing RED tests**

```ts
test("stale generation cannot append", () => {
  const first = acquireWriterLease(leaseInput("owner-a", { expected_generation: 0 }));
  expect(() => acquireWriterLease(leaseInput("owner-b", { expected_generation: 1 })))
    .toThrow("writer_lease_active");
  advanceClockPast(first.expires_at);
  const second = takeOverExpiredWriterLease({
    ...leaseInput("owner-b", { expected_generation: 1 }),
    previous_lease_sha256: sha256(first)
  });
  expect(() => appendSealedEvent(eventInput(first))).toThrow("stale_lease");
  expect(appendSealedEvent(eventInput(second)).sequence).toBe(1);
});

test("first production event references the persisted integrity manifest", () => {
  const { manifest, manifest_ref, event } = startSealedRun(sealedRunFixture());
  expect(event.sequence).toBe(1);
  expect(event.manifest_hash).toBe(manifest.manifest_hash);
  expect(manifest_ref.sha256).toBe(manifest.manifest_hash);
});

test("only one process wins an expired-generation takeover", async () => {
  const expired = writeExpiredLease({ generation: 7 });
  const results = await raceInSeparateProcesses([
    takeoverInput("owner-b", expired),
    takeoverInput("owner-c", expired)
  ]);
  expect(results.filter((item) => item.status === "acquired")).toHaveLength(1);
  expect(results.filter((item) => item.failure === "lease_cas_conflict")).toHaveLength(1);
});

test("tampering is detected at the changed line", () => {
  const journal = writeThreeSealedEvents();
  replaceJournalSummary(journal, 2, "tampered");
  expect(verifyJournalIntegrity(journal)).toMatchObject({
    status: "corrupt",
    first_invalid_sequence: 2
  });
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/lens-store/tests/eventJournal.test.ts \
  packages/lens-store/tests/writerLease.test.ts \
  packages/lens-store/tests/journalFaults.test.ts \
  packages/lens-store/tests/mixedJournal.test.ts \
  packages/orchestrator/tests/firstEventManifest.test.ts
```

Expected: stale writers append; tampered lines read; no sync/atomic projection API.

- [ ] **Step 3: Implement one guarded transition**

```ts
export interface RunExecutionContext {
  commitTransition(input: {
    event: (head: JournalHead) => UnsealedRunEvent;
    reduce: (state: WaygentRunStateV2) => WaygentRunStateV2;
  }): SealedAgentLensEvent;
}
```

Under one lease/takeover guard: validate generation and journal head,
canonicalize/hash, append, fsync, reduce state, write temp projection, fsync,
rename, fsync parent directory. Lease acquisition is atomic create-or-CAS;
takeover requires expiry, the expected generation, and the previous lease hash.
Heartbeat renewal preserves generation and rejects a stale owner. SQLite rebuild
remains a cache operation.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/lens-store/tests
git add -- packages/lens-store/src/canonicalJson.ts packages/lens-store/src/writerLease.ts \
  packages/lens-store/src/journalIntegrity.ts packages/lens-store/src/atomicProjection.ts \
  packages/lens-store/src/eventJournal.ts packages/lens-store/src/paths.ts \
  packages/lens-store/src/projection.ts packages/lens-store/src/sqliteProjection.ts \
  packages/lens-store/tests/eventJournal.test.ts packages/lens-store/tests/writerLease.test.ts \
  packages/lens-store/tests/journalFaults.test.ts packages/lens-store/tests/mixedJournal.test.ts \
  packages/orchestrator/src/runEvents.ts packages/orchestrator/src/runExecutionContext.ts \
  packages/orchestrator/src/runState.ts packages/orchestrator/tests/firstEventManifest.test.ts
git commit -m "feat(lens): seal journal transitions and projections"
```

### Task 6: Migrate Legacy State Through Dual Write

**Files:**

- Create: `packages/orchestrator/src/journalMigration.ts`
- Create: `packages/orchestrator/src/runStateProjector.ts`
- Create: `packages/orchestrator/tests/journalProjectionMigration.test.ts`
- Create: `packages/orchestrator/tests/replayEquivalence.test.ts`
- Create: `packages/orchestrator/tests/p0Acceptance.test.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/lens-projectors/src/runReadModel.ts`

**Interfaces:**

- Produces: `JournalWriteMode = "legacy" | "dual" | "sealed"`.
- Produces: `readCompatibleRun`, `compareReplayProjection`, `projectRunState`.
- Produces: `P0_ACCEPTED` only when dual/sealed equivalence and integrity pass.

- [ ] **Step 1: Write RED compatibility tests**

```ts
test("historical state-only run is readable but immutable", () => {
  expect(readCompatibleRun(historicalFixture())).toMatchObject({
    mode: "historical_state_only",
    mutable: false
  });
});

test("dual run projection equals replay", () => {
  expect(compareReplayProjection(dualFixture())).toMatchObject({ equivalent: true });
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/journalProjectionMigration.test.ts \
  packages/orchestrator/tests/replayEquivalence.test.ts \
  packages/orchestrator/tests/p0Acceptance.test.ts
```

Expected: compatibility modes and replay comparison do not exist.

- [ ] **Step 3: Implement guarded migration**

Consume the immutable integrity manifest already introduced in Task 1. In dual
mode, compare replay and live projection after every transition. A mismatch
freezes mutation. Sealed mode never falls back to legacy writes.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/journalProjectionMigration.test.ts \
  packages/orchestrator/tests/replayEquivalence.test.ts \
  packages/orchestrator/tests/p0Acceptance.test.ts
git add -- packages/orchestrator/src/journalMigration.ts \
  packages/orchestrator/src/runStateProjector.ts packages/orchestrator/src/runCommands.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/journalProjectionMigration.test.ts \
  packages/orchestrator/tests/replayEquivalence.test.ts \
  packages/orchestrator/tests/p0Acceptance.test.ts packages/lens-projectors/src/runReadModel.ts
git commit -m "feat(waygent): migrate runtime state through sealed replay"
```

### Task 7: Enforce Private Storage, Redaction And Retention

**Files:**

- Create: `packages/lens-store/src/permissions.ts`
- Create: `packages/lens-store/src/redaction.ts`
- Create: `packages/lens-store/src/retention.ts`
- Modify: `packages/lens-store/src/artifactStore.ts`
- Modify: `packages/lens-store/src/eventJournal.ts`
- Modify: `packages/lens-store/src/runIndex.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Create: `packages/lens-store/tests/securityLifecycle.test.ts`
- Create: `packages/orchestrator/tests/persistedSecretScan.test.ts`

**Interfaces:**

- Produces: private directory/file writers, `redactPersistedText`, `applyRetentionPolicy`.
- Guarantees: canonical redacted evidence never expires; only `raw_ephemeral` is removable and leaves a tombstone.

- [ ] **Step 1: Write RED tests using marker credentials**

```ts
test("run storage is private and marker secret is absent", async () => {
  const run = await createRunWithProviderOutput("sk-waygent-test-marker");
  expect(mode(run.root)).toBe(0o700);
  expect(scanTree(run.root)).not.toContain("sk-waygent-test-marker");
});

test("retention dry run never deletes canonical evidence", () => {
  const decisions = applyRetentionPolicy(retentionFixture(), true);
  expect(decisions.find((item) => item.retention_class === "canonical")?.action)
    .toBe("keep");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/lens-store/tests/securityLifecycle.test.ts \
  packages/orchestrator/tests/persistedSecretScan.test.ts
```

Expected: default modes are permissive, raw output/marker appears, retention API missing.

- [ ] **Step 3: Implement safe persistence defaults**

Use `0700` for run directories and `0600` for files. Persist bounded redacted
provider summaries and artifact refs, not raw stdout/stderr in state. Keep raw
capture disabled unless `WAYGENT_RAW_PROVIDER_IO=ephemeral`, and require
`WAYGENT_RETENTION_APPLY=1` for deletion.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/lens-store/tests/securityLifecycle.test.ts \
  packages/orchestrator/tests/persistedSecretScan.test.ts
git add -- packages/lens-store/src/permissions.ts packages/lens-store/src/redaction.ts \
  packages/lens-store/src/retention.ts packages/lens-store/src/artifactStore.ts \
  packages/lens-store/src/eventJournal.ts packages/lens-store/src/runIndex.ts \
  packages/provider-adapters/src/processAdapters.ts packages/orchestrator/src/taskExecutor.ts \
  packages/lens-store/tests/securityLifecycle.test.ts \
  packages/orchestrator/tests/persistedSecretScan.test.ts
git commit -m "feat(waygent): protect local runtime evidence"
```

### Task 8: Add Native Conformance And Close P0

**Files:**

- Modify: `native/kernel/crates/kernel-protocol/src/lib.rs`
- Modify: `native/kernel/crates/process-supervisor/src/lib.rs`
- Modify: `native/kernel/crates/sandbox-policy/src/lib.rs`
- Modify: `native/kernel/crates/event-journal/src/lib.rs`
- Modify: `native/kernel/crates/artifact-seal/src/lib.rs`
- Modify: `native/kernel/crates/kernel-cli/src/main.rs`
- Create: `packages/testkit/src/p0Acceptance.ts`
- Create: `packages/testkit/tests/p0Acceptance.test.ts`
- Modify: `docs/operations/verification.md`

**Interfaces:**

- Produces: Rust `CommandObservation` parity and shared canonical hash fixtures.
- Enforces: supervisor consults sandbox policy and fails closed without a profile.
- Produces: one `P0_ACCEPTED` projection; TypeScript remains the active writer.

- [ ] **Step 1: Write failing Rust and cross-runtime fixtures**

Add one canonical sealed event fixture consumed by both TS and Rust. Assert both
produce the same SHA-256. Add supervisor tests for missing permission profile,
lease takeover, process kill during append, and artifact collision.

- [ ] **Step 2: Run RED**

```bash
cargo test --manifest-path native/kernel/Cargo.toml \
  -p event-journal -p artifact-seal -p sandbox-policy \
  -p process-supervisor -p kernel-protocol
bun test packages/testkit/tests/p0Acceptance.test.ts
```

Expected: new Rust fields/APIs do not compile and supervisor allows a missing profile.

- [ ] **Step 3: Implement native parity and P0 evaluator**

Make sandbox denial occur before spawn. Implement canonical hash, generation
fencing, sync and exclusive artifact create in Rust using the shared fixture.
The P0 evaluator requires all deterministic focused invariants and emits
`P0_ACCEPTED` without requiring network or a live provider. If an optional live
probe is run, record its separate `P0_LIVE_OBSERVED` status without changing the
deterministic P0 verdict; P4 owns mandatory live readiness.

- [ ] **Step 4: Run the full P0 gate**

```bash
bun run check
bun run typecheck
bun run waygent:scenarios
cargo test --manifest-path native/kernel/Cargo.toml --workspace
git diff --check
```

Expected: all exit 0 and `p0Acceptance` returns `status=P0_ACCEPTED`.

- [ ] **Step 5: Commit**

```bash
git add -- native/kernel/crates/kernel-protocol/src/lib.rs \
  native/kernel/crates/process-supervisor/src/lib.rs \
  native/kernel/crates/sandbox-policy/src/lib.rs native/kernel/crates/event-journal/src/lib.rs \
  native/kernel/crates/artifact-seal/src/lib.rs native/kernel/crates/kernel-cli/src/main.rs \
  packages/testkit/src/p0Acceptance.ts packages/testkit/tests/p0Acceptance.test.ts \
  docs/operations/verification.md
git commit -m "test(waygent): close production trust foundation"
```

## Execution Order

- Sequential shared core: Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.
- Human approval gates: none before the final program merge.

## Rollback And Kill Switches

```text
WAYGENT_DISPATCH_DISABLED=1
WAYGENT_JOURNAL_WRITE_MODE=legacy|dual|sealed
WAYGENT_RAW_PROVIDER_IO=off|ephemeral
WAYGENT_RETENTION_APPLY=0|1
```

- A sealed run never downgrades to legacy mutation.
- Journal corruption or projection mismatch freezes the run and preserves evidence.
- Retention defaults to dry-run and cannot remove canonical evidence.
- Provider preflight failure cannot be overridden by prompt or model output.

## Review

Use `code_review.md`. Block P0 acceptance for journal/state ordering, TOCTOU lease
gaps, artifact overwrite, raw secret persistence, namespace regression, sandbox
bypass, or any test that proves only an LLM claim instead of a deterministic outcome.
