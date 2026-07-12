# Waygent Codex Superpowers P2 Worker Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute P1 contracts through pinned Codex App Server workers with the approved quality-first model policy, role isolation, safe waves, and serial feature-branch integration.

**Architecture:** A transport selector probes compatible Codex binaries and prefers a pinned App Server JSON-RPC client. Each attempt is a fresh root thread with explicit skill input, output schema, model, reasoning, and role sandbox. Waygent—not Codex—owns fan-out and integration. `codex exec` remains a bounded diagnostic fallback and cannot produce production merge-ready when explicit skill evidence is required.

**Tech Stack:** Bun, TypeScript, `bun:test`, JSON-RPC over stdio, Codex App Server generated schemas, Git worktrees/branches, Waygent scheduler.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- `P1_ACCEPTED` must pass before P2 dispatch.
- Pin Codex binary version and generated protocol compatibility per run.
- Unknown protocol events are retained as bounded diagnostics and never interpreted optimistically.
- Terra high is mechanical read-only only; any writable claim with Terra is a hard error.
- Sol high handles semantic exploration and all ordinary writes.
- Sol xhigh handles shared API/state/concurrency/security/migration, repeat repair, independent review, and completion audit.
- Sol max is allowed once only after xhigh produced new evidence; no default route uses max.
- Reject Luna as a default and reject `ultra` everywhere.
- Four total threads, two writers, one integrator are ceilings.
- Separate root threads are used for implementer, reviewers, verifier, repairer, Lead, and integrator decisions.
- No remote push, source-checkout patch apply, or protected-branch merge.
- Every helper, fixture, and local constant shown in a test snippet is defined in that named test file and returns the exact contract fields asserted by the task; do not rely on undeclared global test state.

## File Structure

- `packages/provider-adapters/src/codexAppServerClient.ts`: framed JSON-RPC transport and lifecycle.
- `packages/provider-adapters/src/codexAppServerAdapter.ts`: Waygent request/event normalization.
- `packages/provider-adapters/src/codexExecAdapter.ts`: renamed compatibility fallback.
- `packages/provider-adapters/src/codexAdapter.ts`: transport selection only.
- `packages/orchestrator/src/modelRouter.ts`: approved exact model policy.
- `packages/provider-adapters/src/roleSandbox.ts`: role permissions.
- `packages/orchestrator/src/{featureBranchManager,integrator,wholeDiffVerifier}.ts`: local feature branch closeout.

## Task Ownership And Risk

| Task | Owner boundary | Risk | Dependency |
| --- | --- | --- | --- |
| 1 | Codex executable probe and protocol compatibility | high | P1 acceptance |
| 2 | framed App Server transport and normalized events | high | Task 1 |
| 3 | model policy, fallback eval and pre-seal manifest routes | high | Task 2 |
| 4 | role sandbox, tool allowlist and fresh root attempts | high | Task 3 |
| 5 | scheduler resource locks and safe waves | high | Task 4 |
| 6 | Git command policy, local feature branch and integrator | high | Task 5 |
| 7 | transport selection, deterministic acceptance and live canary | high | Task 6 |

Tasks are sequential across the runtime/manifest boundary. Each commit stages
only the exact paths in its task `Files` block; broad directory staging is
forbidden.

---

### Task 1: Pin Codex Runtime And Protocol Compatibility

**Files:**

- Create: `packages/provider-adapters/src/codexRuntimeProbe.ts`
- Create: `packages/provider-adapters/src/codexProtocolCompatibility.ts`
- Create: `packages/provider-adapters/protocol/codex-app-server/v2/compatibility.json`
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/capabilities.ts`
- Modify: `packages/provider-adapters/src/capabilityProbe.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Create: `packages/provider-adapters/tests/codexRuntimeProbe.test.ts`
- Create: `packages/provider-adapters/tests/codexTransportCompatibility.test.ts`

**Interfaces:**

- Produces: `probeCodexRuntime`, `assertCodexProtocolCompatible`, `CodexRuntimePreflight`, `attestCodexRuntime(preflight): CodexRuntimeAttestation`.
- Consumes: executable candidates from explicit config, PATH, and supported app bundle path.

- [ ] **Step 1: Optionally refresh protocol evidence from a resolved live candidate**

This optional implementation probe is not an acceptance command. When
`WAYGENT_CODEX_BIN` names an executable candidate, invoke it directly with argv
`["--version"]`, then with
`["app-server","generate-json-schema","--out",<temporary-json-dir>]` and
`["app-server","generate-ts","--out",<temporary-ts-dir>]`. If no explicit
candidate is available, skip only this refresh and continue with committed
offline compatibility fixtures.

On macOS, explicit candidate discovery may include
`/Applications/ChatGPT.app/Contents/Resources/codex`; it is never the only or a
mandatory path. When a live candidate is supplied, capture its version, inspect
the generated method index and record
`skills/list`, `skills/extraRoots/set`, `thread/start`, `turn/start`,
`turn/interrupt`, `turn/steer`, and `model/list` as exact keys in
`compatibility.json`. Copy only reviewed compatibility facts and fixture
messages; do not commit the generated temp tree.

- [ ] **Step 2: Write RED probe/compatibility tests**

```ts
test("broken PATH shim falls through to compatible candidate", async () => {
  const result = await probeCodexRuntime({
    executable_candidates: [brokenShim, fixtureCompatibleCodex],
    compatibility: compatibilityV2
  });
  expect(result.status).toBe("ready");
  expect(result.executable).toBe(fixtureCompatibleCodex);
});

test("missing required App Server method fails closed", () => {
  expect(() => assertCodexProtocolCompatible(schemaWithoutSkillsList))
    .toThrow("codex_protocol_incompatible");
});

test("compatible preflight becomes the shared immutable attestation", async () => {
  const preflight = await probeCodexRuntime(compatibleFixtureInput);
  const attestation = attestCodexRuntime(preflight);
  expect(validateContract("waygent.codex_runtime_attestation.v1", attestation))
    .toMatchObject({ transport: "app_server", version: fixtureCodexVersion });
  expect(attestation.protocol_schema_sha256).toHaveLength(64);
});
```

- [ ] **Step 3: Run RED**

```bash
bun test packages/provider-adapters/tests/codexRuntimeProbe.test.ts \
  packages/provider-adapters/tests/codexTransportCompatibility.test.ts
```

Expected: new probe/compatibility exports absent.

- [ ] **Step 4: Implement candidate probing and commit**

```ts
export async function probeCodexRuntime(input: {
  executable_candidates: string[];
  compatibility: CodexCompatibilityMatrix;
}): Promise<CodexRuntimePreflight>;

export function attestCodexRuntime(
  preflight: CodexRuntimePreflight
): CodexRuntimeAttestation;
```

Require version, schema method set, skill input shape, model/list, read-only and
workspace-write sandbox shape. Record every rejected candidate reason without
persisting credentials.

```bash
bun test packages/provider-adapters/tests/codexRuntimeProbe.test.ts \
  packages/provider-adapters/tests/codexTransportCompatibility.test.ts
git add -- packages/provider-adapters/src/codexRuntimeProbe.ts \
  packages/provider-adapters/src/codexProtocolCompatibility.ts \
  packages/provider-adapters/protocol/codex-app-server/v2/compatibility.json \
  packages/provider-adapters/src/types.ts packages/provider-adapters/src/capabilities.ts \
  packages/provider-adapters/src/capabilityProbe.ts packages/provider-adapters/src/index.ts \
  packages/provider-adapters/tests/codexRuntimeProbe.test.ts \
  packages/provider-adapters/tests/codexTransportCompatibility.test.ts
git commit -m "feat(codex): pin App Server compatibility"
```

### Task 2: Implement The App Server Client And Adapter

**Files:**

- Create: `packages/provider-adapters/src/codexAppServerClient.ts`
- Create: `packages/provider-adapters/src/codexAppServerAdapter.ts`
- Create: `packages/provider-adapters/src/codexExecAdapter.ts`
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Create: `packages/provider-adapters/tests/codexAppServerClient.test.ts`
- Create: `packages/provider-adapters/tests/codexAppServerAdapter.test.ts`
- Create: `packages/provider-adapters/tests/fixtures/app-server-happy.jsonl`
- Create: `packages/provider-adapters/tests/fixtures/app-server-unknown-event.jsonl`
- Create: `packages/provider-adapters/tests/fixtures/app-server-approval.jsonl`

**Interfaces:**

- Produces: `CodexAppServerClient`, `CodexAppServerAdapter`, `CodexExecAdapter`, `normalizeCodexEvent`.
- Supports: initialize, skills list/reload, model list, thread start, turn start, interrupt/steer, owned process shutdown.

- [ ] **Step 1: Write JSON-RPC lifecycle RED tests**

```ts
test("adapter sends explicit skill items and output schema", async () => {
  const result = await fixtureAdapter.run(requestWithPinnedSkills());
  expect(fixtureServer.requestsFor("turn/start")[0]?.params.input)
    .toContainEqual({ type: "skill", name: "test-driven-development", path: pinnedPath });
  expect(fixtureServer.requestsFor("turn/start")[0]?.params.outputSchema)
    .toEqual(workerResultSchema);
  expect(result.metadata?.skill_injections).toHaveLength(2);
});

test("unknown event is diagnostic, not a state transition", async () => {
  const result = await unknownEventAdapter.run(request);
  expect(result.metadata?.adapter_warnings).toContain("unknown_app_server_event");
  expect(result.worker.status).toBe("blocked");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/provider-adapters/tests/codexAppServerClient.test.ts \
  packages/provider-adapters/tests/codexAppServerAdapter.test.ts
```

Expected: no App Server client exists; current adapter only shells out to `codex exec`.

- [ ] **Step 3: Implement framed client and normalized adapter**

```ts
export interface CodexAppServerClient {
  request<T>(method: string, params: unknown): Promise<T>;
  notifications(): AsyncIterable<CodexServerNotification>;
  interrupt(turnId: string): Promise<void>;
  steer(turnId: string, input: CodexInputItem[]): Promise<void>;
  close(): Promise<void>;
}
```

Correlate request IDs, bound line/message size, reject invalid JSON, capture
thread/turn/item/diff/token/compaction/skill/model events, and terminate through
`turn/interrupt` plus owned child-process shutdown; do not invent
`thread/terminate`.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/provider-adapters/tests/codexAppServerClient.test.ts \
  packages/provider-adapters/tests/codexAppServerAdapter.test.ts \
  packages/provider-adapters/tests/providerReplay.test.ts
git add -- packages/provider-adapters/src/codexAppServerClient.ts \
  packages/provider-adapters/src/codexAppServerAdapter.ts packages/provider-adapters/src/codexExecAdapter.ts \
  packages/provider-adapters/src/codexAdapter.ts packages/provider-adapters/src/types.ts \
  packages/provider-adapters/src/index.ts packages/provider-adapters/tests/codexAppServerClient.test.ts \
  packages/provider-adapters/tests/codexAppServerAdapter.test.ts \
  packages/provider-adapters/tests/fixtures/app-server-happy.jsonl \
  packages/provider-adapters/tests/fixtures/app-server-unknown-event.jsonl \
  packages/provider-adapters/tests/fixtures/app-server-approval.jsonl
git commit -m "feat(codex): add App Server worker adapter"
```

### Task 3: Implement The Approved Model Router

**Files:**

- Create: `packages/orchestrator/src/modelRouter.ts`
- Create: `packages/orchestrator/tests/modelRouter.test.ts`
- Create: `packages/orchestrator/tests/fixtures/model-routing-v1.json`
- Modify: `packages/orchestrator/src/executionProfile.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/manifestCompiler.ts`
- Modify: `packages/orchestrator/tests/runManifest.test.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/profilePreset.test.ts`
- Modify: `apps/cli/tests/roleFlags.test.ts`

**Interfaces:**

- Produces: `routeModel(input): ModelRoute` and `evaluateMaxEscalation`.
- Consumes: App Server `model/list`, task class, role, write status, risk, repair history and evidence delta.
- Supplies: resolved routes and runtime attestation to P1 manifest compilation before the immutable hash is written.

- [ ] **Step 1: Write the golden routing table as executable fixture data**

```json
[
  {"task_class":"mechanical_extraction","role":"scout","writes":false,"expected":{"model":"gpt-5.6-terra","reasoning":"high"}},
  {"task_class":"semantic_exploration","role":"scout","writes":false,"expected":{"model":"gpt-5.6-sol","reasoning":"high"}},
  {"task_class":"docs_config","role":"implementer","writes":true,"expected":{"model":"gpt-5.6-sol","reasoning":"high"}},
  {"task_class":"feature","role":"implementer","writes":true,"expected":{"model":"gpt-5.6-sol","reasoning":"high"}},
  {"task_class":"state_concurrency","role":"implementer","writes":true,"expected":{"model":"gpt-5.6-sol","reasoning":"xhigh"}},
  {"task_class":"review","role":"quality_reviewer","writes":false,"expected":{"model":"gpt-5.6-sol","reasoning":"xhigh"}},
  {"task_class":"completion_audit","role":"lead","writes":false,"expected":{"model":"gpt-5.6-sol","reasoning":"xhigh"}}
]
```

Add negative cases: Terra with writes, Luna default, ultra, unvalidated fallback,
and max without prior xhigh evidence delta.
Also assert the compiled manifest contains every resolved task/role route and
that changing any route requires a new manifest revision and run identity.

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/modelRouter.test.ts \
  packages/orchestrator/tests/runManifest.test.ts \
  apps/cli/tests/profilePreset.test.ts apps/cli/tests/roleFlags.test.ts
```

Expected: no router; current defaults are GPT-5.5 and review high.

- [ ] **Step 3: Implement exact policy and fallback**

```ts
export function routeModel(input: {
  task_class: TaskClass;
  role: ProductionWorkerRole;
  has_writes: boolean;
  risk: RiskLevel;
  repair_attempt: number;
  available_models: RuntimeModel[];
}): ModelRoute;
```

Sol fallback is GPT-5.5 at the same high/xhigh level; Terra fallback is GPT-5.4
high. Fail closed if the fallback lacks a passing golden threshold. `max` is an
internal one-shot Sol route only; CLI role flags do not expose `ultra`.
Resolve all routes and runtime pins before calling `compileRunManifest`; never
mutate or append them after manifest sealing.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/modelRouter.test.ts \
  packages/orchestrator/tests/runManifest.test.ts \
  apps/cli/tests/profilePreset.test.ts apps/cli/tests/roleFlags.test.ts
git add -- packages/orchestrator/src/modelRouter.ts packages/orchestrator/src/executionProfile.ts \
  packages/orchestrator/src/orchestrator.ts packages/orchestrator/src/manifestCompiler.ts \
  packages/orchestrator/tests/modelRouter.test.ts packages/orchestrator/tests/runManifest.test.ts \
  packages/orchestrator/tests/fixtures/model-routing-v1.json apps/cli/src/index.ts \
  apps/cli/tests/profilePreset.test.ts apps/cli/tests/roleFlags.test.ts
git commit -m "feat(waygent): route Codex models by quality risk"
```

### Task 4: Enforce Role Sandboxes And Fresh Root Threads

**Files:**

- Create: `packages/provider-adapters/src/roleSandbox.ts`
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/codexAppServerAdapter.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/reviewRunner.ts`
- Modify: `packages/orchestrator/src/repairDispatch.ts`
- Create: `packages/provider-adapters/tests/roleSandbox.test.ts`
- Create: `packages/orchestrator/tests/workerThreadIsolation.test.ts`

**Interfaces:**

- Produces: `sandboxForRole(role, task)`, `createFreshWorkerAttempt`.
- Guarantees: network off, exact roots, no recursive collaboration tools, separate attempts for each role.

- [ ] **Step 1: Write RED isolation tests**

```ts
test("reviewer is read-only and has no write roots", () => {
  expect(sandboxForRole("quality_reviewer", manifestTask)).toEqual({
    mode: "read-only",
    writable_roots: [],
    network: "disabled"
  });
});

test("implementer and reviewers use distinct root threads", async () => {
  const run = await executeFixtureTask();
  expect(new Set(run.attempts.map((item) => item.thread_id)).size)
    .toBe(run.attempts.length);
});

test("worker tool allowlist forbids recursive delegation", () => {
  const request = buildWorkerRequest(manifestTask);
  expect(request.allowed_tools).not.toContain("spawn_agent");
  expect(request.allowed_tools).not.toContain("collaboration");
  expect(request.allowed_tools).not.toContain("create_thread");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/provider-adapters/tests/roleSandbox.test.ts \
  packages/orchestrator/tests/workerThreadIsolation.test.ts
```

Expected: no role sandbox contract; process adapter roles share broad permissions.

- [ ] **Step 3: Implement role mapping and commit**

Implementer/repairer write only their task/repair worktree. Scout, reviewers,
verifier and Lead are read-only. Integrator writes only the run feature branch.
Disable native subagent/collaboration tools for every worker request.

```bash
bun test packages/provider-adapters/tests/roleSandbox.test.ts \
  packages/orchestrator/tests/workerThreadIsolation.test.ts
git add -- packages/provider-adapters/src/roleSandbox.ts packages/provider-adapters/src/types.ts \
  packages/provider-adapters/src/codexAppServerAdapter.ts packages/orchestrator/src/taskExecutor.ts \
  packages/orchestrator/src/reviewRunner.ts packages/orchestrator/src/repairDispatch.ts \
  packages/provider-adapters/tests/roleSandbox.test.ts \
  packages/orchestrator/tests/workerThreadIsolation.test.ts
git commit -m "feat(waygent): isolate Codex worker roles"
```

### Task 5: Add Production Resource Locks And Safe Waves

**Files:**

- Modify: `packages/runway-control/src/types.ts`
- Modify: `packages/runway-control/src/scheduler.ts`
- Modify: `packages/orchestrator/src/taskGraph.ts`
- Modify: `packages/orchestrator/src/safeWaveExecutor.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Create: `packages/runway-control/tests/scheduler.production.test.ts`
- Create: `packages/orchestrator/tests/safeWaveExecutor.production.test.ts`

**Interfaces:**

- Produces: `deriveResourceLocks`, `computeProductionSafeWave`.
- Enforces: total 4, writers 2, integrator 1; shared API/schema/lockfile and overlapping files serialize.

- [ ] **Step 1: Write RED scheduler cases**

```ts
test("shared schema tasks serialize despite disjoint files", () => {
  const wave = computeProductionSafeWave(graphWithSharedSchema(), limits);
  expect(wave.ready).toHaveLength(1);
  expect(wave.withheld[0]?.reason).toBe("resource_lock");
});

test("two disjoint writers and read-only scouts share one bounded wave", () => {
  const wave = computeProductionSafeWave(disjointGraph(), limits);
  expect(wave.ready.filter(isWriter)).toHaveLength(2);
  expect(wave.concurrency).toBeLessThanOrEqual(4);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/runway-control/tests/scheduler.production.test.ts \
  packages/orchestrator/tests/safeWaveExecutor.production.test.ts
```

Expected: scheduler knows file overlap/risk but not semantic resource locks or writer ceilings.

- [ ] **Step 3: Implement locks and emergency serialization**

Derive stable keys for file, package API, schema, lockfile, integration and
verification resources. `WAYGENT_DISABLE_PARALLEL_WRITES=1` sets writer ceiling
to one; `WAYGENT_WAVE_CONCURRENCY=1` serializes all without changing manifest.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/runway-control/tests/scheduler.production.test.ts \
  packages/orchestrator/tests/safeWaveExecutor.production.test.ts
git add -- packages/runway-control/src/types.ts packages/runway-control/src/scheduler.ts \
  packages/orchestrator/src/taskGraph.ts packages/orchestrator/src/safeWaveExecutor.ts \
  packages/orchestrator/src/taskExecutor.ts packages/runway-control/tests/scheduler.production.test.ts \
  packages/orchestrator/tests/safeWaveExecutor.production.test.ts
git commit -m "feat(waygent): schedule production-safe worker waves"
```

### Task 6: Integrate Verified Task Commits Into A Local Feature Branch

**Files:**

- Create: `packages/orchestrator/src/featureBranchManager.ts`
- Create: `packages/orchestrator/src/integrator.ts`
- Create: `packages/orchestrator/src/wholeDiffVerifier.ts`
- Create: `packages/orchestrator/src/gitCommandPolicy.ts`
- Modify: `packages/orchestrator/src/worktreeManager.ts`
- Modify: `packages/orchestrator/src/checkpointArtifacts.ts`
- Modify: `packages/orchestrator/src/applyEngine.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/orchestrator/tests/featureBranchManager.test.ts`
- Create: `packages/orchestrator/tests/integrator.test.ts`
- Create: `packages/orchestrator/tests/wholeDiffVerifier.test.ts`
- Create: `packages/orchestrator/tests/gitCommandPolicy.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`

**Interfaces:**

- Produces: `prepareRunFeatureBranch`, `commitAcceptedTask`, `integrateAcceptedCommit`, `verifyWholeFeatureBranch`.
- Deprecates: production use of source-checkout patch apply.

- [ ] **Step 1: Write RED integration boundary tests**

```ts
test("accepted task commits to run branch without touching source", async () => {
  const before = snapshotRepositoryRefsAndStatus(sourceCheckout, fakeRemote);
  const result = await integrateAcceptedCommit(fixtureAcceptedTask());
  expect(result.status).toBe("integrated");
  expect(snapshotSourceStatusAndProtectedRefs(sourceCheckout, fakeRemote))
    .toEqual(before.source_and_protected);
  expect(result.command_observations.every((item) =>
    !item.argv.includes("push") && !isProtectedMerge(item.argv)
  )).toBe(true);
});

test("push and protected merge are denied before process spawn", async () => {
  expect(await observeDeniedGit(["push", "origin", "HEAD"])).toMatchObject({
    spawned: false,
    failure_class: "policy_denied"
  });
  expect(await observeDeniedGit(["merge", "main"])).toMatchObject({ spawned: false });
});

test("conflict creates Lead packet and never force applies", async () => {
  const result = await integrateAcceptedCommit(conflictingTask());
  expect(result.status).toBe("blocked");
  expect(result.failure_class).toBe("integration_conflict");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/featureBranchManager.test.ts \
  packages/orchestrator/tests/integrator.test.ts \
  packages/orchestrator/tests/wholeDiffVerifier.test.ts \
  packages/orchestrator/tests/gitCommandPolicy.test.ts
```

Expected: current worktrees are detached and apply engine mutates the source checkout.

- [ ] **Step 3: Implement serial local integration**

Create `codex/waygent-run/<run-id>` from pinned base. Commit verified task diffs
in their worktrees, then integrate one at a time. Run declared integration
checks at dependency boundaries and whole-diff checks at closeout. Make legacy
apply explicitly non-production and fail closed when feature integrator is
disabled. All Git mutations pass an argv-array allowlist; `push`, protected-ref
updates and protected-branch merge are rejected before spawn. Tests use a temp
source repo and fake bare remote and compare source status, protected refs and
remote refs before/after; no worker result boolean is trusted as proof.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/featureBranchManager.test.ts \
  packages/orchestrator/tests/integrator.test.ts \
  packages/orchestrator/tests/wholeDiffVerifier.test.ts \
  packages/orchestrator/tests/gitCommandPolicy.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git add -- packages/orchestrator/src/featureBranchManager.ts packages/orchestrator/src/integrator.ts \
  packages/orchestrator/src/wholeDiffVerifier.ts packages/orchestrator/src/gitCommandPolicy.ts \
  packages/orchestrator/src/worktreeManager.ts packages/orchestrator/src/checkpointArtifacts.ts \
  packages/orchestrator/src/applyEngine.ts packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/featureBranchManager.test.ts packages/orchestrator/tests/integrator.test.ts \
  packages/orchestrator/tests/wholeDiffVerifier.test.ts packages/orchestrator/tests/gitCommandPolicy.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git commit -m "feat(waygent): integrate into local run branches"
```

### Task 7: Wire Transport Selection, Acceptance And Live Canary

**Files:**

- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/orchestrator/tests/p2Acceptance.test.ts`
- Modify: `tests/integration/waygent-live-provider-smoke.test.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `package.json`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/README.md`
- Modify: `skills/waygent/references/commands.md`
- Modify: `docs/operations/codex-best-loop.md`
- Modify: `docs/operations/waygent.md`

**Interfaces:**

- Produces: `P2_ACCEPTED` and `merge_ready` only for compatible App Server runs with complete P0/P1/P2 evidence.
- Keeps: exec fallback diagnostic/non-production when explicit skill evidence is required.

- [ ] **Step 1: Add transport and production acceptance RED tests**

Assert:

```ts
expect(execFallbackRun.merge_ready).toBe(false);
expect(execFallbackRun.blocker).toBe("explicit_skill_evidence_unavailable");
expect(appServerCompleteRun.status).toBe("P2_ACCEPTED");
expect(appServerCompleteRun.remote_push_attempted).toBe(false);
```

Also assert an App Server crash after writes seals evidence, discards the
worktree from integration, and starts a new attempt only when recovery evidence changes.

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/p2Acceptance.test.ts \
  tests/integration/waygent-live-provider-smoke.test.ts \
  apps/cli/tests/cli.test.ts
```

Expected: P2 acceptance/transport evidence absent.

- [ ] **Step 3: Wire kill switches and docs**

```text
WAYGENT_CODEX_TRANSPORT=auto|app-server|exec
WAYGENT_DISABLE_CODEX_APP_SERVER=1
WAYGENT_DISABLE_CODEX_EXEC_FALLBACK=1
WAYGENT_MODEL_POLICY=legacy-profile|codex-superpowers-v1
WAYGENT_DISABLE_PARALLEL_WRITES=1
WAYGENT_WAVE_CONCURRENCY=1
WAYGENT_DISABLE_FEATURE_INTEGRATOR=1
```

Fallback reasons, exact binary/protocol/model list, skills, sandbox and thread
lineage are sealed evidence. No fallback weakens a policy silently.

If P1 did not already add it, add this idempotent root script entry:

```json
"waygent:skill-evals": "bash skills/waygent/evals/run.sh",
"waygent:native-tests": "cargo test --manifest-path native/kernel/Cargo.toml --workspace",
"waygent:console-check": "cd apps/console && bun test src && bun run build"
```

- [ ] **Step 4: Run offline P2 gate**

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:skill-evals
git diff --check
```

Expected: all exit 0.

- [ ] **Step 5: Run opt-in canary and commit**

```bash
WAYGENT_LIVE_PROVIDER=codex \
WAYGENT_CODEX_TRANSPORT=app-server \
bun run waygent:live-smoke
git add -- packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/p2Acceptance.test.ts \
  tests/integration/waygent-live-provider-smoke.test.ts apps/cli/src/index.ts \
  apps/cli/tests/cli.test.ts package.json skills/waygent/SKILL.md \
  skills/waygent/README.md skills/waygent/references/commands.md \
  docs/operations/codex-best-loop.md docs/operations/waygent.md
git commit -m "test(waygent): close Codex worker plane phase"
```

Expected live evidence: compatible App Server, model list, explicit skills,
fresh role roots, sealed task commit, independent review, whole-diff verification,
local feature branch, no push, no protected-branch mutation.

## Execution Order

- Sequential: Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Review

Use `code_review.md`. Block P2 for schema drift, implicit skill injection,
shared root threads, Terra writes, Luna/ultra routes, unvalidated fallback,
parallel shared-resource writes, source-checkout apply, remote push, protected
merge, or App Server live success used to waive deterministic tests.
