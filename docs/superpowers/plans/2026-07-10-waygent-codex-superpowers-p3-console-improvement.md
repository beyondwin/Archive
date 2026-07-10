# Waygent Codex Superpowers P3 Console And Improvement Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the local operator a secure, live, evidence-backed view and control surface for runs, failures, Superpowers compliance, merge readiness, and Waygent improvement candidates.

**Architecture:** Shared pure Lens projectors derive every user-visible fact from P0-P2 sealed evidence. The API tails the journal with cursor/gap recovery and exposes a small authenticated command surface. The React Console renders those shared projections and never computes readiness or mutates runtime files directly.

**Tech Stack:** Bun, TypeScript, `bun:test`, Fetch/SSE, React, Vite, CSS, Lens projectors/store.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- `P2_ACCEPTED` must pass before P3.
- Bind API to `127.0.0.1`; remove wildcard CORS.
- Mutations require a local session and CSRF token.
- Public run commands are pause, resume, cancel, and validated cleanup only; improvement preparation uses a separate typed endpoint with the same session, CSRF, CAS, idempotency and journal boundary.
- No push or merge route, button, command, RPC name, or generic shell endpoint.
- SSE uses monotonic sealed event sequence and `Last-Event-ID`; gaps recover through a snapshot.
- CLI, API, and Console consume the same projectors.
- Console shows structured rationale and evidence refs, not private reasoning or default raw logs.
- Improvement candidates never auto-edit the active runtime; implementation stays on a local feature branch and waits for user merge.
- Every helper, fixture, and local constant shown in a test snippet is defined in that named test file and returns the exact contract fields asserted by the task; do not rely on undeclared global test state.

## File Structure

- `packages/lens-projectors/src/runBoard.ts`: run/DAG/worker plus stale/orphan board projection.
- `packages/lens-projectors/src/productionRun.ts`: composes one run from focused projectors.
- `packages/lens-projectors/src/methodEvidence.ts`: Superpowers requirement/evidence projection.
- `packages/lens-projectors/src/productionMetrics.ts`: cross-run quality, latency, token and parallelism metrics.
- `packages/lens-projectors/src/mergeReady.ts`: merge-readiness projection.
- `packages/lens-projectors/src/failureClusters.ts`: cross-run normalized fingerprint clusters.
- `packages/lens-projectors/src/improvementCandidates.ts`: promotion policy and candidate projection.
- `packages/lens-store/src/eventTail.ts`: cursor-based journal tail and gap status.
- `apps/api/src/localSession.ts`, `commandApi.ts`: localhost auth/CSRF and explicit commands.
- `apps/console/src/apiClient.ts`, `useWaygentEvents.ts`: typed snapshot/SSE/command client.
- `apps/console/src/uiModel.ts`: view model only.

## Task Ownership And Risk

| Task | Owner boundary | Risk | Dependency |
| --- | --- | --- | --- |
| 1 | focused Lens run/method/metrics/failure/merge projectors | high | P2 acceptance |
| 2 | cursor journal tail and gap recovery | high | Task 1 |
| 3 | loopback session, CSRF, CORS and SSE API | high | Task 2 |
| 4 | idempotent CAS run-control command boundary | high | Task 3 |
| 5 | typed Console client and views | medium | Task 4 |
| 6 | redacted improvement candidate and secured preparation | high | Task 5 |
| 7 | parity, security and automated browser acceptance | high | Task 6 |

Tasks are sequential across the shared projection/API contracts. Each commit
stages only exact task paths; broad directory staging is forbidden.

---

### Task 1: Add Shared Production Console Projections

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/lens-projectors/src/runBoard.ts`
- Create: `packages/lens-projectors/src/productionRun.ts`
- Create: `packages/lens-projectors/src/methodEvidence.ts`
- Create: `packages/lens-projectors/src/productionMetrics.ts`
- Create: `packages/lens-projectors/src/mergeReady.ts`
- Create: `packages/lens-projectors/src/failureClusters.ts`
- Create: `packages/lens-projectors/src/improvementCandidates.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Create: `packages/lens-projectors/tests/runBoard.test.ts`
- Create: `packages/lens-projectors/tests/productionRun.test.ts`
- Create: `packages/lens-projectors/tests/methodEvidence.test.ts`
- Create: `packages/lens-projectors/tests/productionMetrics.test.ts`
- Create: `packages/lens-projectors/tests/mergeReady.test.ts`
- Create: `packages/lens-projectors/tests/failureClusters.test.ts`
- Create: `packages/lens-projectors/tests/improvementCandidates.test.ts`

**Interfaces:**

- Produces: `ProductionRunProjection`, `RunBoardProjection`, `MethodEvidenceProjection`, `ProductionMetricsProjection`, `FailureClusterProjection`, `ImprovementCandidateProjection`, `MergeReadyProjection`.
- Consumes: sealed events, RunManifest, method reports, observations, reviews, model routes, worktrees and integration evidence.

- [ ] **Step 1: Write projection RED tests**

```ts
test("failure clusters group by fingerprint across runs", () => {
  const clusters = projectFailureClusters([runA, runB, unrelatedRun]);
  expect(clusters[0]).toMatchObject({
    fingerprint: "sha256:same",
    occurrences: 2,
    distinct_runs: 2,
    owner: "harness_bug"
  });
});

test("merge ready requires every production gate", () => {
  const projection = projectProductionRun(runMissingMethodEvidence);
  expect(projection.merge_ready.status).toBe("blocked");
  expect(projection.merge_ready.blockers).toContain("method_evidence_missing");
});

test("home board preserves stale and orphan runs", () => {
  expect(projectRunBoard([healthyRun, staleRun, orphanRun]).counts)
    .toMatchObject({ stale: 1, orphan: 1 });
});

test("cross-run metrics expose every approved metric family", () => {
  expect(Object.keys(projectProductionMetrics(metricFixtures))).toEqual([
    "first_attempt_success", "merge_ready_success", "time_to_merge_ready",
    "repair_and_same_fingerprint_waste", "harness_misclassification",
    "review_findings", "regression_escape", "method_compliance",
    "lead_token_ratio", "parallel_wall_clock_savings", "model_by_task_class"
  ]);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/lens-projectors/tests/runBoard.test.ts \
  packages/lens-projectors/tests/productionRun.test.ts \
  packages/lens-projectors/tests/methodEvidence.test.ts \
  packages/lens-projectors/tests/productionMetrics.test.ts \
  packages/lens-projectors/tests/mergeReady.test.ts \
  packages/lens-projectors/tests/failureClusters.test.ts \
  packages/lens-projectors/tests/improvementCandidates.test.ts
```

Expected: contracts/projectors are absent; current failure projector groups only within one run/class.

- [ ] **Step 3: Implement pure projections**

```ts
export interface ProductionRunProjection {
  schema: "lens.production_run.v1";
  run_id: string;
  manifest: { id: string; hash: string; spec_path: string; plan_path: string };
  dag: { waves: ProductionWave[]; tasks: ProductionTaskProjection[] };
  workers: WorkerAttemptProjection[];
  methods: MethodEvidenceProjection[];
  failures: FailureFingerprintProjection[];
  metrics: RunMetricProjection;
  merge_ready: MergeReadyProjection;
}

export interface RunBoardProjection {
  schema: "lens.run_board.v1";
  runs: ProductionRunSummary[];
  counts: {
    running: number;
    blocked: number;
    merge_ready: number;
    stale: number;
    orphan: number;
  };
}

export function projectProductionRun(input: SealedRunEvidence): ProductionRunProjection;
export function projectRunBoard(input: SealedRunEvidence[]): RunBoardProjection;
```

Keep focused projection functions deterministic and side-effect free, then
compose them at the API boundary. The metrics projector implements all approved
cross-run metric families, and the Home projector explicitly retains stale and
orphan runs. Improvement
promotion requires either repeated cross-run fingerprint, severe integrity/
startup/artifact circuit, missed quality gate, or explicit operator request.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/lens-projectors/tests
git add -- packages/contracts/src/types.ts packages/contracts/src/schemas.ts \
  packages/lens-projectors/src/runBoard.ts packages/lens-projectors/src/methodEvidence.ts \
  packages/lens-projectors/src/productionRun.ts \
  packages/lens-projectors/src/productionMetrics.ts packages/lens-projectors/src/mergeReady.ts \
  packages/lens-projectors/src/failureClusters.ts packages/lens-projectors/src/improvementCandidates.ts \
  packages/lens-projectors/src/index.ts packages/lens-projectors/tests/runBoard.test.ts \
  packages/lens-projectors/tests/productionRun.test.ts \
  packages/lens-projectors/tests/methodEvidence.test.ts \
  packages/lens-projectors/tests/productionMetrics.test.ts \
  packages/lens-projectors/tests/mergeReady.test.ts \
  packages/lens-projectors/tests/failureClusters.test.ts \
  packages/lens-projectors/tests/improvementCandidates.test.ts
git commit -m "feat(lens): project production run and failure clusters"
```

### Task 2: Implement Cursor-Based Journal Tail And Gap Recovery

**Files:**

- Create: `packages/lens-store/src/eventTail.ts`
- Modify: `packages/lens-store/src/eventJournal.ts`
- Modify: `packages/lens-store/src/index.ts`
- Create: `packages/lens-store/tests/eventTail.test.ts`
- Modify: `apps/api/tests/events.test.ts`

**Interfaces:**

- Produces: `readEventTail`, `watchEventTail`, `EventTailBatch`.
- Detects: cursor behind retention floor, sequence gap, corrupt head, and live append.

- [ ] **Step 1: Write tail RED tests**

```ts
test("tail resumes strictly after Last-Event-ID", () => {
  const batch = readEventTail({ journal_path, after_sequence: 7, limit: 100 });
  expect(batch.events.map((event) => event.sequence)).toEqual([8, 9]);
  expect(batch.next_sequence).toBe(9);
});

test("gap requests snapshot recovery", () => {
  const batch = readEventTail({ journal_path: gapFixture, after_sequence: 4, limit: 100 });
  expect(batch.status).toBe("snapshot_required");
  expect(batch.reason).toBe("sequence_gap");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/lens-store/tests/eventTail.test.ts apps/api/tests/events.test.ts
```

Expected: no tail API; current SSE concatenates a snapshot/current events and closes.

- [ ] **Step 3: Implement bounded polling tail**

```ts
export interface EventTailBatch {
  status: "ok" | "snapshot_required" | "corrupt";
  events: SealedAgentLensEvent[];
  next_sequence: number | null;
  reason: string | null;
}
```

Use sealed sequence/integrity verification. `watchEventTail` accepts an AbortSignal,
emits keepalive comments, and stops cleanly without retaining full event history.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/lens-store/tests/eventTail.test.ts apps/api/tests/events.test.ts
git add -- packages/lens-store/src/eventTail.ts packages/lens-store/src/eventJournal.ts \
  packages/lens-store/src/index.ts packages/lens-store/tests/eventTail.test.ts \
  apps/api/tests/events.test.ts
git commit -m "feat(lens): tail sealed events with cursor recovery"
```

### Task 3: Secure The Local API And Persistent SSE

**Files:**

- Create: `apps/api/src/localSession.ts`
- Create: `apps/api/src/sse.ts`
- Modify: `apps/api/src/server.ts`
- Create: `apps/api/tests/security.test.ts`
- Modify: `apps/api/tests/events.test.ts`
- Modify: `apps/api/tests/api.test.ts`

**Interfaces:**

- Produces: `createLocalSession`, `verifyLocalSession`, `verifyCsrf`, `streamRunEvents`.
- Enforces: loopback host, exact configured Console origin, no wildcard CORS.

- [ ] **Step 1: Write API security/SSE RED tests**

```ts
test("CORS is exact and never wildcard", async () => {
  const response = await handler(requestFrom("http://127.0.0.1:5173"));
  expect(response.headers.get("access-control-allow-origin"))
    .toBe("http://127.0.0.1:5173");
  expect(response.headers.get("access-control-allow-origin")).not.toBe("*");
});

test("SSE honors Last-Event-ID and stays open", async () => {
  const response = await handler(streamRequest({ "Last-Event-ID": "7" }));
  expect(response.headers.get("content-type")).toContain("text/event-stream");
  expect(await readFirstSseEvent(response)).toMatchObject({ id: "8" });
});
```

- [ ] **Step 2: Run RED**

```bash
bun test apps/api/tests/security.test.ts apps/api/tests/events.test.ts apps/api/tests/api.test.ts
```

Expected: wildcard CORS, no session/CSRF, completed response rather than live tail.

- [ ] **Step 3: Implement local session and SSE**

Bind Bun.serve with `hostname: "127.0.0.1"`. Generate a random private local
session file at API start, set HttpOnly/SameSite=Strict cookie, return CSRF in a
bootstrap response, validate exact origin for mutations, and stream event IDs
as sequences. A gap emits `lens.snapshot_required` then closes for client resync.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test apps/api/tests/security.test.ts apps/api/tests/events.test.ts apps/api/tests/api.test.ts
git add -- apps/api/src/localSession.ts apps/api/src/sse.ts apps/api/src/server.ts \
  apps/api/tests/security.test.ts apps/api/tests/events.test.ts apps/api/tests/api.test.ts
git commit -m "feat(api): secure local sessions and live event stream"
```

### Task 4: Add Explicit Run Commands Without Merge Or Shell Escape

**Files:**

- Create: `packages/orchestrator/src/runControl.ts`
- Create: `packages/orchestrator/src/runCommandProjection.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/tests/runControl.test.ts`
- Create: `packages/orchestrator/tests/runCommandProjection.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Create: `apps/api/src/commandApi.ts`
- Create: `apps/api/tests/commands.test.ts`
- Modify: `apps/api/src/server.ts`

**Interfaces:**

- Produces: `pauseRun`, `resumeRunExecution`, `cancelRun`, `planCleanup`, `applyCleanup`.
- Produces: `rebuildRunCommandProjection(sealedEvents)` as the only dedupe/result source.
- API routes: `/runs/:id/commands/pause|resume|cancel|cleanup` only.
- Consumes: a `RunCommandEnvelope` with command ID, idempotency key, expected event sequence and expected state hash.

- [ ] **Step 1: Write command allowlist RED tests**

```ts
test("command API requires session and CSRF", async () => {
  expect((await handler(postCommand("resume"))).status).toBe(403);
});

test("merge, push and arbitrary shell routes do not exist", async () => {
  for (const command of ["merge", "push", "shell"]) {
    expect((await handler(postCommand(command, validAuth))).status).toBe(404);
  }
});

test("resume executes the next sealed transition", async () => {
  const result = await resumeRunExecution(resumableFixture());
  expect(result.action).toBe("resumed");
  expect(result.event.event_type).toBe("runway.run_resumed");
});

test("duplicate command returns the original sealed result", async () => {
  const envelope = commandEnvelope({ kind: "resume" });
  const first = await submitRunCommand(envelope);
  const duplicate = await submitRunCommand(envelope);
  expect(duplicate.result_event_id).toBe(first.result_event_id);
  expect(currentSequence()).toBe(first.result_sequence);
});

test("stale expected state is rejected without mutation", async () => {
  const before = sealedHead();
  const response = await handler(postCommandEnvelope({
    ...commandEnvelope({ kind: "pause" }),
    expected_sequence: before.sequence - 1
  }, validAuth));
  expect(response.status).toBe(409);
  expect(sealedHead()).toEqual(before);
});

test("duplicate command survives API process restart", async () => {
  const envelope = commandEnvelope({ kind: "resume" });
  const first = await startApi(runRoot).submit(envelope);
  await stopApi();
  const duplicate = await startApi(runRoot).submit(envelope);
  expect(duplicate.result_event_id).toBe(first.result_event_id);
  expect(projectCommandEffects(readSealedEvents(runRoot), envelope.command_id))
    .toHaveLength(1);
});

test("crash after requested resumes one command effect", async () => {
  const envelope = commandEnvelope({ kind: "cleanup" });
  await expect(submitWithCrash(envelope, "after_requested")).rejects.toThrow();
  const recovered = await startApi(runRoot).submit(envelope);
  expect(recovered.status).toBe("completed");
  expect(projectCommandEffects(readSealedEvents(runRoot), envelope.command_id))
    .toHaveLength(1);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/runControl.test.ts \
  packages/orchestrator/tests/runCommandProjection.test.ts \
  apps/api/tests/commands.test.ts apps/cli/tests/cli.test.ts
```

Expected: current CLI resume always dry-runs; API is GET-only; no structured command layer.

- [ ] **Step 3: Implement typed commands**

Define `RunCommandEnvelope` with `command_id`, `idempotency_key`,
`expected_sequence`, `expected_state_sha256`, `issued_at`, a closed `kind` union
and kind-specific payload. Atomically compare state/head, append sealed
`command_requested` and `command_completed|rejected` transitions. Rebuild the
persistent command projection from the sealed journal on every process start;
there is no authoritative in-memory cache. An incomplete requested command is
resumed through its kind-specific idempotent effect check, never blindly
re-executed. Exact duplicate retries return the original sealed result; ID reuse
with different bytes is rejected. Cleanup is always
dry-run first and requires exact orphan/worktree IDs. Do not accept command
strings, paths outside owned roots, or a generic argv.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/runControl.test.ts \
  packages/orchestrator/tests/runCommandProjection.test.ts \
  apps/api/tests/commands.test.ts apps/cli/tests/cli.test.ts
git add -- packages/orchestrator/src/runControl.ts packages/orchestrator/src/runCommandProjection.ts \
  packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runControl.test.ts \
  packages/orchestrator/tests/runCommandProjection.test.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts \
  apps/api/src/commandApi.ts apps/api/tests/commands.test.ts apps/api/src/server.ts
git commit -m "feat(waygent): expose safe local run controls"
```

### Task 5: Build The Typed Console Client And Production Views

**Files:**

- Create: `apps/console/src/apiClient.ts`
- Create: `apps/console/src/useWaygentEvents.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`
- Modify: `tests/e2e/lens-console-model.test.ts`

**Interfaces:**

- Produces: typed snapshot/SSE client and models for Home, Run, Failure Analysis, Superpowers Evidence, Improvement Lab, Merge Ready.
- Sends: explicit command IDs with CSRF; reconnects from last sequence.

- [ ] **Step 1: Write view-model and reconnect RED tests**

```ts
test("Superpowers view exposes required versus proven methods", () => {
  const model = buildRunDetailModel(productionRunFixture);
  expect(model.superpowers.tasks[0]).toMatchObject({
    required: ["using-superpowers", "test-driven-development"],
    status: "passed"
  });
});

test("event client recovers from a sequence gap", async () => {
  const client = createFixtureClient([event8, gapSignal, snapshotAt12]);
  expect((await client.collect()).last_sequence).toBe(12);
  expect(client.snapshot_fetches).toBe(1);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test apps/console/src/uiModel.test.ts tests/e2e/lens-console-model.test.ts
```

Expected: current App fetches on selection only and has no SSE/command connection or new views.

- [ ] **Step 3: Implement views and command feedback**

Render DAG waves, worker/model/reasoning/worktree, method chain, sealed diff,
tests/reviews, failure owner/fingerprint/circuit, cost/context metrics,
improvement status and local feature-branch merge instructions. Raw logs are
collapsed behind explicit evidence links. Remove any apply control that implies
source/protected mutation.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test apps/console/src tests/e2e/lens-console-model.test.ts
(cd apps/console && bun run build)
git add -- apps/console/src/apiClient.ts apps/console/src/useWaygentEvents.ts \
  apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts apps/console/src/App.tsx \
  apps/console/src/styles.css tests/e2e/lens-console-model.test.ts
git commit -m "feat(console): show live Waygent production evidence"
```

### Task 6: Materialize Improvement Candidates Without Self-Merging

**Files:**

- Create: `packages/orchestrator/src/improvementCandidates.ts`
- Create: `packages/orchestrator/src/improvementWorkspace.ts`
- Create: `packages/orchestrator/tests/improvementCandidates.test.ts`
- Create: `packages/orchestrator/tests/improvementWorkspace.test.ts`
- Modify: `packages/orchestrator/src/runControl.ts`
- Modify: `packages/orchestrator/tests/runControl.test.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/api/src/commandApi.ts`
- Modify: `apps/api/tests/commands.test.ts`

**Interfaces:**

- Produces: `analyzeImprovementCandidates`, `prepareImprovementWorkspace`.
- CLI/API expose read plus secured prepare only in P3; actual replay/canary acceptance is P4.

- [ ] **Step 1: Write promotion and branch-boundary RED tests**

```ts
test("one ordinary failure does not self-improve", () => {
  expect(analyzeImprovementCandidates([singleProductFailure])).toEqual([]);
});

test("severe artifact integrity circuit creates a local candidate", () => {
  const candidate = analyzeImprovementCandidates([artifactIntegrityCircuit])[0]!;
  expect(candidate.trigger).toBe("severe_integrity_circuit");
  expect(candidate.remote_push_forbidden).toBe(true);
});

test("improvement prepare uses the authenticated idempotent command boundary", async () => {
  const response = await handler(postImprovementPrepare(prepareEnvelope, validAuth));
  expect(response.status).toBe(202);
  expect(readSealedCommand(prepareEnvelope.command_id).kind)
    .toBe("prepare_improvement");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/improvementCandidates.test.ts \
  packages/orchestrator/tests/improvementWorkspace.test.ts \
  packages/orchestrator/tests/runControl.test.ts \
  apps/cli/tests/cli.test.ts apps/api/tests/commands.test.ts
```

Expected: no cluster-to-candidate/workspace pipeline exists.

- [ ] **Step 3: Implement redacted candidate packets**

Create a local candidate ID, redacted fixture refs, exact trigger, affected
versions/runs, standing-autonomy basis, required Superpowers chain and local
feature-branch name. Never embed raw external logs as instructions. Preparation
does not edit current runtime code or start implementation in P3. The API
prepare endpoint accepts only a candidate ID and the unified command envelope,
requires local session/CSRF, performs state CAS/deduplication, and journals its
result; GET candidate projections remain read-only.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/improvementCandidates.test.ts \
  packages/orchestrator/tests/improvementWorkspace.test.ts
git add -- packages/orchestrator/src/improvementCandidates.ts \
  packages/orchestrator/src/improvementWorkspace.ts \
  packages/orchestrator/tests/improvementCandidates.test.ts \
  packages/orchestrator/tests/improvementWorkspace.test.ts \
  packages/orchestrator/src/runControl.ts packages/orchestrator/tests/runControl.test.ts \
  apps/cli/src/index.ts \
  apps/cli/tests/cli.test.ts apps/api/src/server.ts apps/api/tests/api.test.ts \
  apps/api/src/commandApi.ts apps/api/tests/commands.test.ts
git commit -m "feat(waygent): prepare evidence-backed improvement candidates"
```

### Task 7: Close P3 With Security, Parity And Browser Evidence

**Files:**

- Create: `packages/testkit/src/p3Acceptance.ts`
- Create: `packages/testkit/tests/p3Acceptance.test.ts`
- Modify: `apps/console/package.json`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/operations/verification.md`
- Modify: `package.json`
- Modify: `bun.lock`
- Create: `tests/e2e/waygent-console.browser.test.ts`

**Interfaces:**

- Produces: `P3_ACCEPTED` only when CLI/API/Console facts match and no forbidden route exists.

- [ ] **Step 1: Add parity/security acceptance tests**

Assert one sealed fixture has identical blocker, next action, method status,
failure fingerprint and merge-ready status through CLI inspect, API detail and
Console view model. Inspect the registered routes and command IDs to assert no
merge/push/shell entry exists.

- [ ] **Step 2: Implement the browser/evaluator code and create the candidate commit**

Add pinned `@playwright/test` tooling and a `waygent:console-e2e` script that
starts fixture API/Console servers on loopback. The test verifies Home (including
stale/orphan), Run, Failure, Superpowers, Improvement and Merge Ready views at
desktop and narrow width; exercises pause/resume idempotency and stale-CAS
rejection; reconnects SSE; and asserts Console has no merge/push/shell control.
It emits a redacted JSON evidence report with command observations and screenshot
digests into the ignored run-evidence root.

```bash
bun test packages/testkit/tests/p3Acceptance.test.ts
bun run waygent:console-check
bun run waygent:console-e2e
git diff --check
git add -- packages/testkit/src/p3Acceptance.ts packages/testkit/tests/p3Acceptance.test.ts \
  apps/console/package.json docs/operations/waygent.md docs/operations/verification.md \
  package.json bun.lock tests/e2e/waygent-console.browser.test.ts
git commit -m "test(waygent): close console and improvement phase"
```

This pre-commit run proves implementation behavior but is not final P3 evidence.

- [ ] **Step 3: Review and run final acceptance on clean HEAD**

Confirm `git status --porcelain` is empty, then use `requesting-code-review` with
Sol xhigh over the P3 diff. If review requires a change, make it, stage only the
Task 7 files, commit, and restart this step from a new clean HEAD. With an
approved clean HEAD, run:

```bash
bun run check
bun test packages/testkit/tests/p3Acceptance.test.ts
bun run waygent:console-check
bun run waygent:console-e2e
bun run typecheck
git diff --exit-code
git diff --cached --exit-code
```

Expected: `P3_ACCEPTED` is bound to this clean HEAD. The redacted browser report
and screenshot digests remain in the ignored evidence root; do not commit after
this final evidence run. An unrun/skipped suite cannot pass P3.

## Execution Order

- Sequential: Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Kill Switches

```text
WAYGENT_API_COMMANDS=off|safe
WAYGENT_SSE_MODE=snapshot|tail
WAYGENT_IMPROVEMENT_LAB=off|read-only|prepare
WAYGENT_RETENTION_APPLY=0|1
```

- Snapshot fallback remains read-only.
- Disabling commands does not disable inspection.
- Improvement Lab never has an apply/merge/push mode.

## Review

Use `code_review.md`. Block P3 for wildcard CORS, non-loopback bind, missing
CSRF, arbitrary command input, readiness recomputation in UI, SSE gap loss,
private reasoning/raw secret display, or any merge/push control.
