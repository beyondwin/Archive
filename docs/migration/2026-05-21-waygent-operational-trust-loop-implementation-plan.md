# Waygent Operational Trust Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent apply readiness a single runtime truth across run preflight, provider execution, reconciliation, API, console, scenarios, and opt-in live provider smoke tests.

**Architecture:** Waygent remains the state-owning runtime. AgentLens, API, and console read durable state and events but do not mutate execution state. The implementation proceeds from shared contracts and runtime barriers outward to operator surfaces, with apply readiness derived from `waygent.run_state.v2`, completion audit evidence, combined apply evidence, and reconciliation records.

**Tech Stack:** Bun, TypeScript project references, filesystem JSON/JSONL artifacts, git worktrees, `@waygent/lens-projectors`, `@waygent/orchestrator`, `@waygent/provider-adapters`, React/Vite console, opt-in Codex and Claude process adapters.

---

## Source Design

- Design: `docs/architecture/2026-05-21-waygent-operational-trust-loop-design.md`
- Architecture index: `docs/architecture/waygent.md`
- Operational reference: `docs/operations/waygent.md`
- Prior maturity plan: `docs/migration/2026-05-21-waygent-runtime-v1-operational-maturity-implementation-plan.md`
- Current planning commit: `1d08ffd`
- Source audit basis in the design: `5887d84`

## Non-Negotiable Boundaries

- Do not route Waygent through `skills/kws-codex-plan-executor` or `skills/kws-claude-multi-agent-executor`.
- Do not add active `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` event namespaces.
- AgentLens remains downstream observability and must not mutate Waygent state.
- Provider success claims never make a task verified without Waygent verification and checkpoint sealing.
- `waygent run` must not mutate the source checkout.
- `waygent apply` remains the only source-checkout mutation path.
- Live Codex and Claude smoke tests stay opt-in through `WAYGENT_LIVE_PROVIDER`.
- Keep runtime state, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `node_modules/`, `.venv/`, build outputs, caches, and `.DS_Store` out of git.

## File Structure And Ownership

### Contracts And Readiness Projection

```yaml
files:
  - path: packages/contracts/src/types.ts
    mode: edit
    responsibility: Add source preflight, worktree manifest, process evidence, and apply readiness projection types.
  - path: packages/contracts/src/schemas.ts
    mode: edit
    responsibility: Keep JSON schemas aligned with the additive v2 state fields and provider evidence shape.
  - path: packages/contracts/tests/contracts.test.ts
    mode: edit
    responsibility: Assert contract validation accepts the new additive state shape.
  - path: packages/lens-projectors/src/apply.ts
    mode: edit
    responsibility: Keep event-only projection and add v2-state apply readiness derivation.
  - path: packages/lens-projectors/src/index.ts
    mode: edit
    responsibility: Export the new readiness projection helper.
  - path: packages/lens-projectors/tests/apply.test.ts
    mode: edit
    responsibility: Prove real v2 readiness requires completion audit, combined patch evidence, and no drift blockers.
```

### Runtime Preflight And Evidence Preservation

```yaml
files:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: edit
    responsibility: Connect source preflight, block duplicate run roots, record preflight/worktree state, and dispatch only allowed runs.
  - path: packages/orchestrator/src/sourceCheckout.ts
    mode: edit
    responsibility: Return a preflight record with checked_at, warning/blocker reason, and related/unrelated dirty paths.
  - path: packages/orchestrator/src/runState.ts
    mode: edit
    responsibility: Keep v2 read/write helpers compatible with the additive fields.
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: edit
    responsibility: Cover dirty-related preflight block, dirty-unrelated warning, duplicate run id block, and clean-run state.
  - path: packages/orchestrator/tests/sourceCheckout.test.ts
    mode: edit
    responsibility: Cover clean, related dirty, unrelated dirty, nested path, and git-status failure behavior.
```

### Provider Adapter Boundary

```yaml
files:
  - path: packages/provider-adapters/src/types.ts
    mode: edit
    responsibility: Change provider run output to include worker result plus raw process evidence.
  - path: packages/provider-adapters/src/processAdapters.ts
    mode: edit
    responsibility: Preserve valid failure_class, reject unknown statuses, and surface stdout/stderr/exit/timing evidence.
  - path: packages/provider-adapters/src/fakeProvider.ts
    mode: edit
    responsibility: Return deterministic provider evidence through the same adapter output shape.
  - path: packages/provider-adapters/src/codexAdapter.ts
    mode: edit
    responsibility: Adapt Codex process adapter to the new output shape.
  - path: packages/provider-adapters/src/claudeAdapter.ts
    mode: edit
    responsibility: Adapt Claude process adapter to the new output shape.
  - path: packages/provider-adapters/tests/codexAdapter.test.ts
    mode: edit
    responsibility: Cover preserved provider failure_class, unknown status rejection, cwd, missing executable, and raw output evidence.
  - path: packages/provider-adapters/tests/claudeAdapter.test.ts
    mode: edit
    responsibility: Cover malformed output, fenced JSON envelope, preserved failure_class, and raw output evidence.
  - path: packages/provider-adapters/tests/providerRoles.test.ts
    mode: edit
    responsibility: Keep task packet and write-boundary prompt contract visible.
```

### Worktree And Diff Scope

```yaml
files:
  - path: packages/orchestrator/src/diffScope.ts
    mode: owned
    responsibility: Compare provider changed_files with actual git diff and enforce allowed/forbidden write globs.
  - path: packages/orchestrator/tests/diffScope.test.ts
    mode: owned
    responsibility: Unit test actual diff discovery, missing claim detection, forbidden path detection, and read-only task behavior.
  - path: packages/orchestrator/src/orchestrator.ts
    mode: edit
    responsibility: Call diff scope validation before checkpoint creation and map failures to diff_scope_failed.
  - path: packages/context-packer/src/taskPacket.ts
    mode: edit
    responsibility: Populate checkpoint_inputs from dependency checkpoints during retry or dependent task dispatch.
  - path: packages/context-packer/tests/taskPacket.test.ts
    mode: edit
    responsibility: Assert checkpoint_inputs and forbidden_write_globs remain stable.
  - path: packages/kernel-client/src/worktreeClient.ts
    mode: edit
    responsibility: Add a serializable worktree manifest helper while preserving planWorktree compatibility.
  - path: packages/kernel-client/tests/worktreeClient.test.ts
    mode: edit
    responsibility: Assert manifest branch/path/source shape.
```

### Reconciliation And Resume/Apply Gates

```yaml
files:
  - path: packages/orchestrator/src/stateReconciliation.ts
    mode: edit
    responsibility: Check task packets, provider artifacts, worker results, verification artifacts, checkpoint manifests, patch digests, dry-run evidence, combined patch evidence, event journal, and v2 state consistency.
  - path: packages/orchestrator/tests/stateReconciliation.test.ts
    mode: edit
    responsibility: Cover each blocker class and verify drift records are written back.
  - path: packages/orchestrator/src/completionAudit.ts
    mode: edit
    responsibility: Keep hasApplyReadyCheckpoint aligned with the expanded readiness contract.
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
    responsibility: Use one readiness contract in resume and apply, and surface drift/artifact blockers consistently.
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: edit
    responsibility: Prove resume/apply reject completion-audit, combined patch, digest, drift, and dirty-source blockers.
  - path: packages/orchestrator/tests/orchestratorApplyE2E.test.ts
    mode: edit
    responsibility: Prove completed fake-provider runs stay apply-ready only with sealed evidence.
```

### API, Console, Scenarios, And Operations

```yaml
files:
  - path: apps/api/src/server.ts
    mode: edit
    responsibility: Use v2 readiness projection for real run list/detail.
  - path: apps/api/tests/api.test.ts
    mode: edit
    responsibility: Assert list and detail agree on apply readiness and include combined patch/drift evidence.
  - path: apps/console/src/uiModel.ts
    mode: edit
    responsibility: Render readiness status, reason, checkpoint_refs, combined_patch_ref, source, and drift blockers from API data.
  - path: apps/console/src/App.tsx
    mode: edit
    responsibility: Show readiness evidence and disabled apply command state without executing apply.
  - path: apps/console/src/uiModel.test.ts
    mode: edit
    responsibility: Assert ready/blocked/not_ready/applied mapping and drift warning model.
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: edit
    responsibility: Normalize replay from state plus events, not event payloads alone.
  - path: packages/testkit/tests/waygentScenarioHarness.test.ts
    mode: edit
    responsibility: Assert completion audit, manifest-backed checkpoint refs, combined patch evidence, and blockers.
  - path: tests/waygent-scenarios/*.json
    mode: edit
    responsibility: Update expected replay for v2 evidence and manifest-backed checkpoints.
  - path: tests/integration/waygent-live-provider-smoke.test.ts
    mode: edit
    responsibility: Assert opt-in live provider output uses the same state contract.
  - path: docs/operations/waygent.md
    mode: edit
    responsibility: Document preflight, duplicate run id behavior, readiness, recovery, scenarios, and live smoke gates.
```

## Execution Order

Sequential shared-core tasks:

1. Task 1 contracts and v2 readiness projection.
2. Task 2 run preflight and duplicate-run protection.
3. Task 3 provider process evidence and normalization.
4. Task 4 worktree manifest and diff-scope enforcement.
5. Task 5 reconciliation expansion.
6. Task 6 resume/apply readiness unification.

Parallel-safe after Task 6:

- Task 7 API and console can run after the readiness projection shape is stable.
- Task 8 scenario harness and live smoke can run after provider evidence and reconciliation records are stable.

Final closure:

- Task 9 operations docs and full verification gate.

Human approval gates:

- Review after Task 1 if the contract names change.
- Review after Task 6 before starting console presentation work.
- Review after Task 9 before broad commit, push, or PR.

---

### Task 1: Add Contracts And One V2 Readiness Projection

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`
- Modify: `packages/lens-projectors/src/apply.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Modify: `packages/lens-projectors/tests/apply.test.ts`

- [ ] **Step 1: Write failing readiness projection tests**

Add tests in `packages/lens-projectors/tests/apply.test.ts`:

```ts
test("derives ready apply readiness from v2 state, completion audit, and combined patch evidence", () => {
  const state = makeState({
    apply: { status: "not_applied" },
    drift: { last_checked_at: "2026-05-21T00:00:00Z", records: [], unrepaired_blockers: [] },
    completion_audit: {
      status: "passed",
      combined_apply_evidence: {
        status: "passed",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        patch_ref: "artifacts/checkpoints/apply/run_ready.patch",
        patch_sha256: "a".repeat(64),
        patch_byte_length: 12,
        evidence_ref: "artifacts/checkpoints/apply-dry-run.json"
      }
    }
  });

  expect(projectApplyReadinessFromState(state)).toEqual({
    status: "ready",
    reason: null,
    checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
    combined_patch_ref: "artifacts/checkpoints/apply/run_ready.patch",
    source: "run_state_v2"
  });
});

test("blocks v2 apply readiness when reconciliation has unrepaired blockers", () => {
  const state = makeState({
    drift: {
      last_checked_at: "2026-05-21T00:00:00Z",
      records: [{ type: "artifact_missing", severity: "blocking" }],
      unrepaired_blockers: [{ type: "artifact_missing", severity: "blocking" }]
    },
    completion_audit: { status: "passed" }
  });

  expect(projectApplyReadinessFromState(state)).toMatchObject({
    status: "blocked",
    reason: "state_drift",
    source: "run_state_v2"
  });
});
```

Run: `bun test packages/lens-projectors/tests/apply.test.ts`

Expected: FAIL because `projectApplyReadinessFromState` is not exported.

- [ ] **Step 2: Add additive contract types**

In `packages/contracts/src/types.ts`, add:

```ts
export interface WaygentSourcePreflight {
  status: "clean" | "dirty_unrelated" | "dirty_related";
  dirty_files: string[];
  related: string[];
  unrelated: string[];
  checked_at: string;
  reason: string | null;
  decision_packet_ref: string | null;
}

export interface WaygentWorktreeManifest {
  task_id: string;
  branch: string;
  path: string;
  source: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "unknown";
}

export interface ProviderProcessEvidence {
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string;
  completed_at: string | null;
  event_stream?: string | null;
}

export interface ApplyReadinessProjection {
  status: "ready" | "not_ready" | "blocked" | "applied";
  reason: string | null;
  checkpoint_refs: string[];
  combined_patch_ref: string | null;
  source: "run_state_v2" | "events";
}
```

Then extend `WaygentRunStateV2` with:

```ts
preflight?: WaygentSourcePreflight;
worktrees?: WaygentWorktreeManifest[];
```

Extend `ProviderAttempt` with:

```ts
process?: ProviderProcessEvidence;
```

- [ ] **Step 3: Align schemas with the additive fields**

In `packages/contracts/src/schemas.ts`:

- add schemas for `preflight`, `worktrees`, and optional `ProviderAttempt.process`;
- keep `waygent.run_state.v2` compatible with older v2 states by not adding `preflight` or `worktrees` to `required`;
- keep `ProviderAttempt.process` optional;
- keep `additionalProperties: false` on the new nested shapes.

Run: `bun test packages/contracts/tests`

Expected: PASS after schema updates.

- [ ] **Step 4: Implement readiness projection**

In `packages/lens-projectors/src/apply.ts`, keep `projectApplyState(events)` unchanged for event-only replay and add:

```ts
export function projectApplyReadinessFromState(state: WaygentRunStateV2): ApplyReadinessProjection {
  if (state.apply.status === "applied") {
    return {
      status: "applied",
      reason: null,
      checkpoint_refs: checkpointRefsFromState(state),
      combined_patch_ref: combinedPatchRef(state),
      source: "run_state_v2"
    };
  }
  if (state.drift.unrepaired_blockers.length > 0) {
    return {
      status: "blocked",
      reason: "state_drift",
      checkpoint_refs: checkpointRefsFromState(state),
      combined_patch_ref: combinedPatchRef(state),
      source: "run_state_v2"
    };
  }
  const audit = state.completion_audit as { status?: string; combined_apply_evidence?: Record<string, unknown> } | null;
  const combined = audit?.combined_apply_evidence;
  const refs = Array.isArray(combined?.checkpoint_refs)
    ? combined.checkpoint_refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0)
    : checkpointRefsFromState(state);
  const patchRef = typeof combined?.patch_ref === "string" ? combined.patch_ref : null;
  if (audit?.status === "passed" && combined?.status === "passed" && patchRef && refs.length > 0) {
    return { status: "ready", reason: null, checkpoint_refs: refs, combined_patch_ref: patchRef, source: "run_state_v2" };
  }
  return {
    status: state.apply.status === "blocked" ? "blocked" : "not_ready",
    reason: state.apply.reason || "missing_apply_ready_evidence",
    checkpoint_refs: refs,
    combined_patch_ref: patchRef,
    source: "run_state_v2"
  };
}
```

Add local helpers `checkpointRefsFromState` and `combinedPatchRef`, then export from `packages/lens-projectors/src/index.ts`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/contracts/tests packages/lens-projectors/tests/apply.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts packages/lens-projectors/src/apply.ts packages/lens-projectors/src/index.ts packages/lens-projectors/tests/apply.test.ts
git commit -m "feat: add Waygent apply readiness projection"
```

### Task 2: Add Run Preflight And Preserve Existing Run Evidence

**Files:**
- Modify: `packages/orchestrator/src/sourceCheckout.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/sourceCheckout.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorRunV2.test.ts`

- [ ] **Step 1: Add failing source checkout and orchestrator tests**

Add cases to `packages/orchestrator/tests/orchestratorRunV2.test.ts`:

```ts
test("blocks dispatch when source checkout has dirty related files", async () => {
  const workspace = initGitWorkspace({ "README.md": "base\n" });
  writeFileSync(join(workspace, "README.md"), "user edit\n");
  const root = mkdtempSync(join(tmpdir(), "waygent-preflight-related-"));

  await runWaygent({ root, workspace, run_id: "run_dirty_related", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

  const state = readRunStateV2(root, "run_dirty_related");
  expect(state.status).toBe("blocked");
  expect(state.current_phase).toBe("preflight");
  expect(state.preflight).toMatchObject({ status: "dirty_related", related: ["README.md"], reason: "dirty_source_checkout" });
  expect(state.provider_attempts).toEqual([]);
});

test("records a warning and proceeds when source checkout has only unrelated dirty files", async () => {
  const workspace = initGitWorkspace({ "README.md": "base\n" });
  mkdirSync(join(workspace, "notes"), { recursive: true });
  writeFileSync(join(workspace, "notes", "scratch.md"), "scratch\n");
  const root = mkdtempSync(join(tmpdir(), "waygent-preflight-unrelated-"));

  await runWaygent({ root, workspace, run_id: "run_dirty_unrelated", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

  const state = readRunStateV2(root, "run_dirty_unrelated");
  expect(state.preflight).toMatchObject({ status: "dirty_unrelated", unrelated: ["notes/scratch.md"] });
  expect(state.status).toBe("completed");
});

test("does not erase an existing run root for the same run id", async () => {
  const workspace = initGitWorkspace({ "README.md": "base\n" });
  const root = mkdtempSync(join(tmpdir(), "waygent-duplicate-run-"));
  await runWaygent({ root, workspace, run_id: "run_existing", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

  await expect(runWaygent({ root, workspace, run_id: "run_existing", plan, profile: { provider: "fake", execution_mode: "multi-agent" } }))
    .rejects.toThrow("run_id_already_exists");
});
```

Run: `bun test packages/orchestrator/tests/sourceCheckout.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts`

Expected: FAIL because preflight is not connected and duplicate runs are deleted.

- [ ] **Step 2: Return a durable preflight record**

In `packages/orchestrator/src/sourceCheckout.ts`, add `checked_at`, `reason`, and `decision_packet_ref` to the returned classification. Use `dirty_source_checkout` for `dirty_related`, `null` for `clean`, and `dirty_unrelated_source_checkout` for warnings.

- [ ] **Step 3: Block duplicate run roots before deletion**

In `packages/orchestrator/src/orchestrator.ts`:

- import `existsSync`;
- remove the unconditional `rmSync(paths.root, { recursive: true, force: true })`;
- before writing state, if `paths.root`, `state.json`, or `events.jsonl` exists, throw `new Error("run_id_already_exists")`;
- keep any explicit replacement behavior out of the CLI in this slice.

- [ ] **Step 4: Run source preflight before provider dispatch**

In `runWaygent()`:

- parse the plan and task graph;
- collect all task file claims;
- call `classifySourceCheckout(workspace, allClaims)`;
- include `preflight` in `initialState`;
- append `runway.preflight_result`;
- if `preflight.status === "dirty_related"`, write blocked state with `current_phase: "preflight"`, `lifecycle_outcome: "blocked"`, `apply: { status: "blocked", reason: "dirty_source_checkout" }`, write latest run id, and return without dispatching providers.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/sourceCheckout.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/sourceCheckout.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/sourceCheckout.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
git commit -m "feat: add Waygent run preflight"
```

### Task 3: Preserve Provider Process Evidence And Normalize Failures Strictly

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/fakeProvider.ts`
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/claudeAdapter.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`
- Modify: `packages/provider-adapters/tests/providerRoles.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorRunV2.test.ts`

- [ ] **Step 1: Add failing provider adapter tests**

Add to `packages/provider-adapters/tests/codexAdapter.test.ts`:

```ts
test("preserves provider supplied failure_class", () => {
  const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
    exitCode: 0,
    stdout: JSON.stringify({
      status: "failed",
      failure_class: "verification_failed",
      summary: "provider saw verification fail",
      changed_files: ["README.md"],
      evidence: { command: "codex" }
    }),
    stderr: "stderr evidence"
  });

  expect(result.worker.status).toBe("failed");
  expect(result.worker.failure_class).toBe("verification_failed");
  expect(result.process.stderr).toBe("stderr evidence");
});

test("rejects unknown worker status as malformed_result", () => {
  const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
    exitCode: 0,
    stdout: JSON.stringify({ status: "done", summary: "ambiguous", changed_files: [], evidence: {} }),
    stderr: ""
  });

  expect(result.worker.status).toBe("failed");
  expect(result.worker.failure_class).toBe("malformed_result");
});
```

Run: `bun test packages/provider-adapters/tests`

Expected: FAIL because adapter output currently returns `WorkerResult` directly and unknown status defaults to success.

- [ ] **Step 2: Change adapter output type**

In `packages/provider-adapters/src/types.ts`, add:

```ts
export interface ProviderAdapterRunResult {
  worker: WorkerResult;
  process: {
    stdout: string;
    stderr: string;
    exit_code: number | null;
    timed_out: boolean;
    started_at: string;
    completed_at: string | null;
    event_stream: string | null;
  };
}
```

Change `ProviderAdapter.run()` to return `Promise<ProviderAdapterRunResult>`.

- [ ] **Step 3: Normalize process output into worker plus process evidence**

In `packages/provider-adapters/src/processAdapters.ts`:

- make `normalizeProcessOutput()` return `ProviderAdapterRunResult`;
- preserve `failure_class` when it is one of `FailureClass`;
- return `failed(..., "malformed_result", ...)` for unknown statuses;
- include raw `stdout`, `stderr`, `exitCode`, and timing fields in `process`;
- keep missing executable and timeout mapped to `adapter_crashed` and `timeout`.

- [ ] **Step 4: Update fake, Codex, Claude, and orchestrator call sites**

Update provider adapters to return `{ worker, process }`. In `packages/orchestrator/src/orchestrator.ts`, rename the provider call result:

```ts
const providerResult = await provider.run(...);
const worker = providerResult.worker;
const stdoutArtifact = writeArtifact(paths.root, `provider/${attemptId}.stdout.txt`, providerResult.process.stdout, "text/plain");
const stderrArtifact = writeArtifact(paths.root, `provider/${attemptId}.stderr.txt`, providerResult.process.stderr, "text/plain");
```

Set `ProviderAttempt.exit_code`, `timed_out`, `started_at`, `completed_at`, and optional `process` from provider process evidence.

Append a `runway.provider_attempt` event before `runway.worker_result` with payload:

```ts
{
  attempt_id: attempt.attempt_id,
  task_id: attempt.task_id,
  provider: attempt.provider,
  cwd: attempt.cwd,
  stdin_ref: attempt.stdin_ref,
  stdout_ref: attempt.stdout_ref,
  stderr_ref: attempt.stderr_ref,
  event_stream_ref: attempt.event_stream_ref,
  worker_result_ref: attempt.worker_result_ref,
  failure_class: attempt.failure_class
}
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/provider-adapters/tests packages/orchestrator/tests/orchestratorRunV2.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/src/fakeProvider.ts packages/provider-adapters/src/codexAdapter.ts packages/provider-adapters/src/claudeAdapter.ts packages/orchestrator/src/orchestrator.ts packages/provider-adapters/tests/codexAdapter.test.ts packages/provider-adapters/tests/claudeAdapter.test.ts packages/provider-adapters/tests/providerRoles.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
git commit -m "feat: preserve provider process evidence"
```

### Task 4: Enforce Worktree Manifests And Diff Scope Before Checkpoint Sealing

**Files:**
- Create: `packages/orchestrator/src/diffScope.ts`
- Create: `packages/orchestrator/tests/diffScope.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/context-packer/tests/taskPacket.test.ts`
- Modify: `packages/kernel-client/src/worktreeClient.ts`
- Modify: `packages/kernel-client/tests/worktreeClient.test.ts`

- [ ] **Step 1: Add failing diff scope tests**

Create `packages/orchestrator/tests/diffScope.test.ts` with cases for:

```ts
expect(validateDiffScope({
  actual_changed_files: ["README.md"],
  claimed_changed_files: ["README.md"],
  allowed_write_globs: ["README.md"],
  forbidden_write_globs: [".git/**", "node_modules/**"]
})).toEqual({ ok: true, changed_files: ["README.md"] });

expect(validateDiffScope({
  actual_changed_files: ["secrets.txt"],
  claimed_changed_files: ["README.md"],
  allowed_write_globs: ["README.md"],
  forbidden_write_globs: [".git/**", "node_modules/**"]
})).toMatchObject({ ok: false, failure_class: "diff_scope_failed", reason: "changed_file_outside_allowed_globs" });

expect(validateDiffScope({
  actual_changed_files: [".git/config"],
  claimed_changed_files: [".git/config"],
  allowed_write_globs: [".git/config"],
  forbidden_write_globs: [".git/**"]
})).toMatchObject({ ok: false, failure_class: "diff_scope_failed", reason: "changed_file_matches_forbidden_globs" });
```

Run: `bun test packages/orchestrator/tests/diffScope.test.ts`

Expected: FAIL because `diffScope.ts` does not exist.

- [ ] **Step 2: Implement diff-scope helpers**

Create `packages/orchestrator/src/diffScope.ts` with:

- `listActualChangedFiles(worktree: string): string[]` using `git status --porcelain`;
- `validateDiffScope(input)` returning either `{ ok: true, changed_files }` or `{ ok: false, failure_class: "diff_scope_failed", reason, changed_files }`;
- glob matching for exact file paths, directory prefixes, and `/**` suffixes;
- no dependency on shell glob expansion.

- [ ] **Step 3: Add worktree manifest helper**

In `packages/kernel-client/src/worktreeClient.ts`, add:

```ts
export interface WorktreeManifest extends PlannedWorktree {
  task_id: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "unknown";
}

export function buildWorktreeManifest(input: PlannedWorktree & { task_id: string; source_commit: string | null }): WorktreeManifest {
  return { ...input, cleanup_status: "active" };
}
```

Cover this in `packages/kernel-client/tests/worktreeClient.test.ts`.

- [ ] **Step 4: Enforce scope before checkpoint creation**

In `packages/orchestrator/src/orchestrator.ts`:

- record each task worktree manifest in `state.worktrees`;
- compute actual changed files after verification;
- validate actual changes against `stateTask.unit_manifest.allowed_write_globs` and `forbidden_write_globs`;
- if validation fails, set task `status: "blocked"`, `latest_failure_class: "diff_scope_failed"`, skip checkpoint creation, and append a blocked event with reason and changed files;
- pass validated actual changed files, not provider claims alone, to `createCheckpointArtifact()`.

- [ ] **Step 5: Thread dependency checkpoint inputs into packets**

When building a task packet for a task with dependencies, include verified dependency checkpoint refs in `checkpoint_inputs`. Add a `taskPacket.test.ts` case that a dependent task packet includes `checkpoint_inputs: ["artifacts/checkpoints/task_base/candidate_task_base.json"]`.

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/diffScope.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts packages/context-packer/tests/taskPacket.test.ts packages/kernel-client/tests/worktreeClient.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/diffScope.ts packages/orchestrator/tests/diffScope.test.ts packages/orchestrator/src/orchestrator.ts packages/context-packer/src/taskPacket.ts packages/context-packer/tests/taskPacket.test.ts packages/kernel-client/src/worktreeClient.ts packages/kernel-client/tests/worktreeClient.test.ts
git commit -m "feat: enforce Waygent diff scope"
```

### Task 5: Expand Reconciliation Into The Final Consistency Barrier

**Files:**
- Modify: `packages/orchestrator/src/stateReconciliation.ts`
- Modify: `packages/orchestrator/tests/stateReconciliation.test.ts`
- Modify: `packages/orchestrator/src/completionAudit.ts`
- Modify: `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`

- [ ] **Step 1: Add failing reconciliation tests**

Add table-driven tests in `packages/orchestrator/tests/stateReconciliation.test.ts` for:

```ts
[
  ["missing_provider_stdout", "artifact_missing"],
  ["missing_worker_result", "artifact_missing"],
  ["missing_kernel_result", "artifact_missing"],
  ["missing_checkpoint_manifest", "artifact_missing"],
  ["missing_checkpoint_patch", "artifact_missing"],
  ["checkpoint_digest_mismatch", "state_drift"],
  ["missing_checkpoint_dry_run_evidence", "artifact_missing"],
  ["missing_combined_patch", "artifact_missing"],
  ["combined_patch_digest_mismatch", "state_drift"],
  ["missing_event_journal", "artifact_missing"],
  ["completed_without_terminal_trust_event", "state_drift"]
]
```

Each case should write a minimal `waygent.run_state.v2`, create the needed artifacts, remove or corrupt the target artifact, call `reconcileRunState(root, runId)`, and assert:

```ts
expect(report.passed).toBe(false);
expect(report.unrepaired_blockers[0]).toMatchObject({ severity: "blocking" });
expect(readRunStateV2(root, runId).drift.unrepaired_blockers.length).toBeGreaterThan(0);
```

Run: `bun test packages/orchestrator/tests/stateReconciliation.test.ts`

Expected: FAIL for newly asserted blockers.

- [ ] **Step 2: Implement artifact and digest checks**

In `packages/orchestrator/src/stateReconciliation.ts`, add checks for:

- task packet path exists;
- task packet sha256 matches the file bytes when `task_packet_sha256` is set;
- provider attempt `stdin_ref`, `stdout_ref`, `stderr_ref`, `event_stream_ref`, and `worker_result_ref` exist when non-null;
- each verification `kernel_result_ref` exists;
- each verified task has at least one checkpoint manifest;
- each checkpoint manifest and patch pass `validateCheckpointManifest()`;
- each checkpoint dry-run evidence ref exists;
- completion audit `combined_apply_evidence.evidence_ref` exists;
- combined patch exists and matches `patch_sha256` and `patch_byte_length`;
- event journal exists;
- completed v2 state has `completion_audit.status === "passed"` and a terminal `lens.trust_report_updated` event.

- [ ] **Step 3: Keep drift records stable and readable**

Use record types that operator surfaces can display:

```ts
{
  type: "artifact_missing" | "state_drift",
  severity: "blocking",
  failure_class: "artifact_missing" | "state_drift",
  message: string,
  artifact_ref?: string,
  task_id?: string
}
```

Write the full records to `state.drift.records` and blocking records to `state.drift.unrepaired_blockers`.

- [ ] **Step 4: Align completion audit with reconciliation**

In `packages/orchestrator/src/completionAudit.ts`, ensure `hasApplyReadyCheckpoint()` returns false when `state.drift.unrepaired_blockers.length > 0`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/stateReconciliation.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/stateReconciliation.ts packages/orchestrator/tests/stateReconciliation.test.ts packages/orchestrator/src/completionAudit.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git commit -m "feat: expand Waygent state reconciliation"
```

### Task 6: Use The Same Readiness Contract In Resume And Apply

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`
- Modify: `packages/lens-projectors/tests/apply.test.ts`

- [ ] **Step 1: Add failing resume/apply readiness tests**

Add tests in `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
test("resume does not allow apply when reconciliation drift blocks readiness", () => {
  writeReadyLookingState({ drift_blocker: { failure_class: "state_drift" } });
  expect(resumeRun({ root, run: "run_drifted", dry_run: true }).allowed_actions).not.toContain("apply_verified_checkpoint");
});

test("apply blocks when readiness projection is not ready", async () => {
  writeReadyLookingState({ missing_combined_patch: true });
  await expect(applyRun({ root, run: "run_missing_combined", workspace })).resolves.toMatchObject({
    status: "blocked",
    reason: "checkpoint_patch_missing"
  });
});
```

Run: `bun test packages/orchestrator/tests/runCommandsV2.test.ts`

Expected: FAIL until `resumeRun()` and `applyRun()` share the readiness contract.

- [ ] **Step 2: Derive readiness before resume action selection**

In `resumeRun()`:

- call `projectApplyReadinessFromState(v2State)`;
- allow `apply_verified_checkpoint` only when readiness status is `ready`;
- for `blocked` readiness caused by drift or artifacts, return `["inspect_run", "retry_checkpoint_generation", "human_decision"]`;
- keep dirty source checkout as `["clean_source_checkout"]` when the state records that blocker.

- [ ] **Step 3: Derive readiness before apply mutation**

In `applyRun()`:

- keep the existing live dirty checkout guard first;
- compute readiness from v2 state;
- if readiness is not `ready`, append `runway.apply_blocked`, write `state.apply = { status: "blocked", reason }`, and return before reading or applying a patch;
- only after readiness is `ready`, resolve and validate the combined patch and run `applyVerifiedCheckpoint()`.

- [ ] **Step 4: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/lens-projectors/tests/apply.test.ts
git diff --check
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/lens-projectors/tests/apply.test.ts
git commit -m "feat: unify Waygent apply readiness gates"
```

### Task 7: Align API And Console With V2 Readiness

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add failing API tests**

In `apps/api/tests/api.test.ts`, add a real v2 run where events contain successful verification but `completion_audit` lacks combined apply evidence. Assert:

```ts
expect(body.runs[0]).toMatchObject({
  run_id: "run_not_ready",
  apply_status: "not_ready"
});

expect(detail.apply_readiness).toEqual({
  status: "not_ready",
  reason: "missing_apply_ready_evidence",
  checkpoint_refs: [],
  combined_patch_ref: null,
  source: "run_state_v2"
});
```

Run: `bun test apps/api/tests/api.test.ts`

Expected: FAIL because list summary still uses event-only `projectApplyState(events)`.

- [ ] **Step 2: Use v2 readiness in API list and detail**

In `apps/api/src/server.ts`:

- import `projectApplyReadinessFromState`;
- in `summarizeRealRun()`, read v2 state when available and set `apply_status` from readiness;
- in `readRealRunDetail()`, return the full `apply_readiness` projection for v2 states;
- preserve event-only `projectApplyState(events)` under `apply` for replay/debug views.

- [ ] **Step 3: Add console model tests**

In `apps/console/src/uiModel.test.ts`, assert:

```ts
expect(realRunDetailToConsoleRun({
  run_id: "run_blocked",
  status: "blocked",
  trust_status: "insufficient_evidence",
  apply_status: "blocked",
  total_events: 1,
  last_event_type: "runway.apply_blocked",
  safe_wave: [],
  failures: [],
  timeline: [],
  apply_readiness: {
    status: "blocked",
    reason: "state_drift",
    checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
    combined_patch_ref: null,
    source: "run_state_v2"
  },
  drift: { last_checked_at: "2026-05-21T00:00:00Z", records: [], unrepaired_blockers: [{ failure_class: "state_drift" }] }
}).applyStatus).toMatchObject({
  state: "blocked",
  canApply: false,
  reason: "state_drift",
  checkpointRef: "artifacts/checkpoints/task_a/candidate_task_a.json"
});
```

Run: `bun test apps/console/src/uiModel.test.ts`

Expected: FAIL until the type and mapping support `checkpoint_refs` and `combined_patch_ref`.

- [ ] **Step 4: Update console mapping and display**

In `apps/console/src/uiModel.ts`:

- change `RealRunDetailResponse.apply_readiness` to the full projection shape;
- prefer `apply_readiness.status`, `reason`, and `checkpoint_refs.join(", ")`;
- include `combined_patch_ref` in the model when present;
- keep `canApply` true only for `status === "ready"`;
- keep dirty source detection from recovery and drift blockers.

In `apps/console/src/App.tsx`, render:

- readiness status;
- reason;
- checkpoint refs;
- combined patch ref;
- disabled apply command text for non-ready states.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test apps/api/tests apps/console/src
git diff --check
```

Expected: PASS.

Commit:

```bash
git add apps/api/src/server.ts apps/api/tests/api.test.ts apps/console/src/uiModel.ts apps/console/src/App.tsx apps/console/src/uiModel.test.ts
git commit -m "feat: align console apply readiness"
```

### Task 8: Upgrade Scenario Harness And Live Provider Smoke Contract

**Files:**
- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Modify: `packages/testkit/tests/waygentScenarioHarness.test.ts`
- Modify: `tests/waygent-scenarios/*.json`
- Modify: `tests/integration/waygent-scenarios.test.ts`
- Modify: `tests/integration/waygent-live-provider-smoke.test.ts`

- [ ] **Step 1: Add failing harness tests**

In `packages/testkit/tests/waygentScenarioHarness.test.ts`, add a replay fixture with events that look successful but v2 state missing combined apply evidence. Assert normalized replay is failed or not ready:

```ts
const normalized = normalizeWaygentReplay({
  events: [{ event_type: "runway.verification_result", payload: {}, outcome: "success" }],
  trust_report: { trust_status: "trusted" },
  summary: { total_events: 1 },
  projection: { safe_wave: ["task_a"] },
  run_state_v2: {
    status: "completed",
    completion_audit: { status: "failed" },
    drift: { unrepaired_blockers: [] }
  } as any
});

expect(normalized.run_status).toBe("failed");
expect(normalized.apply_status).toBe("not_applied");
```

Run: `bun test packages/testkit/tests/waygentScenarioHarness.test.ts`

Expected: FAIL because the harness does not read v2 state.

- [ ] **Step 2: Normalize from state plus events**

In `packages/testkit/src/waygentScenarioHarness.ts`:

- extend `ReplayLike` with `run_state_v2?: WaygentRunStateV2 | null`;
- derive `run_status` from `run_state_v2.completion_audit.status === "passed"`, no worker failures, and no drift blockers;
- derive checkpoints from state task `checkpoint_refs` and completion audit `combined_apply_evidence.checkpoint_refs`;
- derive apply status from `projectApplyReadinessFromState(run_state_v2)` when state exists;
- keep event-only behavior for demo or legacy replay.

- [ ] **Step 3: Update scenario expectations**

Update `tests/waygent-scenarios/*.json` so successful fake runs assert:

- checkpoint refs are manifest-backed paths ending in `.json`;
- combined patch evidence exists through normalized state;
- blocked scenarios include blockers from state readiness, not only scenario flags.

For `tests/integration/waygent-live-provider-smoke.test.ts`, replace the old logical checkpoint expectation with a manifest-backed path expectation:

```ts
expect(run.normalized.checkpoints.some((ref) => ref.endsWith(".json"))).toBe(true);
expect(run.normalized.event_types).toContain("runway.provider_attempt");
```

- [ ] **Step 4: Verify and commit**

Run:

```bash
bun test packages/testkit/tests/waygentScenarioHarness.test.ts tests/integration/waygent-scenarios.test.ts
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
```

Expected:

- first two commands PASS;
- live smoke may SKIP or PASS depending on local authenticated Codex CLI. If it is skipped, record the skip reason in the final implementation report.

Commit:

```bash
git add packages/testkit/src/waygentScenarioHarness.ts packages/testkit/tests/waygentScenarioHarness.test.ts tests/waygent-scenarios tests/integration/waygent-scenarios.test.ts tests/integration/waygent-live-provider-smoke.test.ts
git commit -m "test: assert Waygent v2 scenario readiness"
```

### Task 9: Update Operations Docs And Run The Full Gate

**Files:**
- Modify: `docs/operations/waygent.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md`

- [ ] **Step 1: Update operations documentation**

In `docs/operations/waygent.md`, document:

- `waygent run` preflight statuses: `clean`, `dirty_unrelated`, `dirty_related`;
- duplicate run id behavior: `run_id_already_exists`;
- apply readiness definition: completion audit, valid checkpoint manifests, dry-run evidence, combined patch evidence, digest checks, no unrepaired drift;
- resume actions for drift, artifact missing, provider failure, verification failure, and dirty source;
- live smoke commands and their opt-in nature.

- [ ] **Step 2: Link implementation plan from architecture index**

In `docs/architecture/waygent.md`, add one sentence near the trust-loop design link:

```markdown
Its implementation plan is tracked in
[`../migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md`](../migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md).
```

- [ ] **Step 3: Run targeted gate**

Run:

```bash
bun test packages/orchestrator/tests/sourceCheckout.test.ts \
  packages/orchestrator/tests/stateReconciliation.test.ts \
  packages/orchestrator/tests/runCommandsV2.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts \
  packages/orchestrator/tests/orchestratorRunV2.test.ts \
  packages/provider-adapters/tests \
  packages/lens-projectors/tests \
  apps/api/tests \
  apps/console/src \
  packages/testkit/tests/waygentScenarioHarness.test.ts \
  tests/integration/waygent-scenarios.test.ts
```

Expected: PASS.

- [ ] **Step 4: Run repository gate**

Run:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd /Users/kws/source/private/Archive/components/agentlens && .venv/bin/python -m pytest -q
cd /Users/kws/source/private/Archive && git diff --check
```

Expected: PASS, except live provider checks remain opt-in and are not part of the default repository gate.

- [ ] **Step 5: Commit docs and final status**

Run:

```bash
git add docs/operations/waygent.md docs/architecture/waygent.md docs/migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md
git commit -m "docs: document Waygent trust loop operations"
git status --short --branch --untracked-files=all
```

Expected: worktree clean except intentional untracked local runtime state ignored by git.

## Review Checklist

Use `code_review.md` before reporting implementation complete.

Spec coverage:

- Run preflight and duplicate run id protection: Task 2.
- Provider failure normalization and raw evidence: Task 3.
- Worktree manifest and diff-scope enforcement: Task 4.
- Verification, checkpoint, combined patch, and reconciliation barrier: Task 5.
- Resume/apply shared readiness contract: Task 6.
- API and console readiness alignment: Task 7.
- Scenario and live provider gates: Task 8.
- Operations docs and full gate: Task 9.

Residual risks to check during execution:

- Existing tests that reuse a run id inside the same root may need fresh temp roots.
- API imports should avoid introducing circular package dependencies; prefer readiness projection in `@waygent/lens-projectors`.
- Provider adapter return-shape changes must update every adapter call site in one commit.
- Console must not execute apply in this slice.
- Scenario harness must keep event-only compatibility for demo replay while preferring v2 state for real runs.

## Execution Choice

Plan complete when this file is reviewed and committed. Recommended execution mode is Subagent-Driven for Tasks 7 and 8 after Tasks 1-6 stabilize; Tasks 1-6 should be sequential because they share core runtime contracts and state transitions.
