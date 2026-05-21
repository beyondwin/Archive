# Waygent No-Legacy Runtime Implementation Plan

> Status: historical. This plan predates deletion of the legacy Python
> `components/agentlens` tree. Do not execute its Python AgentLens tasks as
> active work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove active legacy runtime compatibility from Waygent, then clean up the remaining AgentLens Python AgentRunway compatibility surface without regressing runtime quality.

**Architecture:** Phase 1 makes the TypeScript Waygent product path v2-only and Waygent-only. Phase 2 then converts the AgentLens Python trust-console surface from AgentRunway-specific names to Waygent-native names, using the Phase 1 acceptance gate as the handoff point.

**Tech Stack:** Bun, TypeScript project references, AJV JSON schema contracts, Python AgentLens package, pytest, Vite console build.

---

## Source Design

Spec: `docs/superpowers/specs/2026-05-22-waygent-no-legacy-runtime-design.md`

Phase 1 is complete before Phase 2 starts. Do not interleave Phase 2 Python changes into Phase 1 commits.

## File Structure

Phase 1 TypeScript runtime cleanup:

- `packages/orchestrator/src/runState.ts`: keep v2 state read/write helpers and add a non-throwing v2 read classifier; remove v1 state API.
- `packages/orchestrator/src/runCommands.ts`: use v2 state classifier for `inspect`, `resume`, and `apply`; remove event-only apply success and v1 fallback branches.
- `packages/orchestrator/src/planParser.ts`: accept only `waygent-task`.
- `packages/orchestrator/src/planDiscovery.ts`: discover only `waygent-task` plans.
- `packages/contracts/src/types.ts`: remove `legacy_source` from `LensRunwayProjection`.
- `packages/contracts/src/schemas.ts`: remove `legacy_source` from `lensRunwayProjectionSchema`.
- `packages/lens-projectors/src/trust.ts`: remove `agentrunway.*` special-case projection.
- `packages/testkit/src/legacyCheck.ts`: keep the legacy guard and strengthen it for active product paths.
- `code_review.md`: rename AgentRunway review guidance to Waygent runtime guidance.
- TypeScript tests under `packages/**/tests` and fixtures under `tests/fixtures/contracts`: update to the new no-legacy product contract.

Phase 2 AgentLens Python cleanup:

- `components/agentlens/src/agentlens/cli.py`: replace the `agentrunway` command registration with a Waygent command.
- `components/agentlens/src/agentlens/commands/waygent.py`: add Waygent trust report command.
- `components/agentlens/src/agentlens/commands/agentrunway.py`: remove after command tests are migrated.
- `components/agentlens/src/agentlens/evaluator/waygent_events.py`: add Waygent event projection and evidence coverage.
- `components/agentlens/src/agentlens/evaluator/waygent_projection.py`: add Waygent projection wrapper.
- `components/agentlens/src/agentlens/evaluator/engine.py`: write Waygent trust artifacts without AgentRunway context detection.
- `components/agentlens/src/agentlens/evaluator/trust.py`: rename fields and wording to Waygent.
- `components/agentlens/src/agentlens/store/trust_artifacts.py`: write `waygent_projection.json`.
- `components/agentlens/src/agentlens/constants.py`: replace AgentRunway projection schema constant.
- `components/agentlens/src/agentlens/schema/validate.py`: register Waygent projection schema.
- `components/agentlens/src/agentlens/schema/jsonschema/waygent_projection.v1.schema.json`: create Waygent projection schema.
- `components/agentlens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json`: remove after fixture migration.
- Python tests and fixtures under `components/agentlens/tests`: rename or delete AgentRunway-only compatibility tests.

## Execution Order

Parallel-safe Phase 1 tasks:

- Task 2 plan marker cleanup can run after Task 1 tests are known but does not edit the same files as Task 1.
- Task 3 projection contract cleanup can run in parallel with Task 2.
- Task 4 legacy guard and docs can run after Task 2 and Task 3 choose final banned tokens.

Sequential/shared-core tasks:

- Task 1 must complete before Task 5 because the full runtime gate depends on v2-only command behavior.
- Phase 2 starts only after Task 5 passes and is committed.
- Phase 2 schema/fixture updates should follow the Python command/evaluator rename tasks to avoid regenerating fixtures against names that still move.

Human approval gates:

- Start Phase 2 only after Phase 1 acceptance gate passes.
- If Phase 2 deletion mode is preferred over rename-and-reshape, stop before Task 6 and update this plan. The default plan below uses rename-and-reshape.

---

## Phase 1: Waygent Product Runtime Cleanup

### Task 1: Make Run Commands V2-Only

**Files:**
- Modify: `packages/orchestrator/src/runState.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runStateV2.test.ts`
- Delete: `packages/orchestrator/tests/runState.test.ts`
- Modify: `packages/orchestrator/tests/runCommands.test.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`

- [ ] **Step 1: Add failing tests for v2 state classification**

Add these tests to `packages/orchestrator/tests/runStateV2.test.ts`:

```ts
test("classifies missing v2 state without throwing", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
  expect(readRunStateV2Result(root, "missing_run")).toEqual({
    status: "missing",
    reason: "missing_run_state_v2"
  });
});

test("classifies unsupported state schemas", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
  const runId = "run_unsupported_state";
  mkdirSync(join(root, runId), { recursive: true });
  writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: "waygent.run_state.v1", run_id: runId }));

  expect(readRunStateV2Result(root, runId)).toMatchObject({
    status: "unsupported",
    reason: "unsupported_run_state",
    schema: "waygent.run_state.v1"
  });
});

test("classifies invalid v2 state", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
  const runId = "run_invalid_state";
  mkdirSync(join(root, runId), { recursive: true });
  writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: "waygent.run_state.v2", run_id: runId }));

  expect(readRunStateV2Result(root, runId)).toMatchObject({
    status: "invalid",
    reason: "invalid_run_state_v2"
  });
});
```

Ensure the imports include:

```ts
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readRunStateV2Result } from "../src/runState";
```

- [ ] **Step 2: Run the focused state test and confirm it fails**

Run:

```bash
bun test packages/orchestrator/tests/runStateV2.test.ts
```

Expected: FAIL because `readRunStateV2Result` is not exported.

- [ ] **Step 3: Implement v2 state classification and remove v1 state API**

In `packages/orchestrator/src/runState.ts`, remove these exports:

```ts
export type WaygentTaskRunStatus = "pending" | "running" | "completed" | "verified" | "failed" | "blocked";
export type WaygentRunLifecycleStatus = "created" | "running" | "blocked" | "failed" | "completed";
export type WaygentApplyStatus = "not_applied" | "blocked" | "applied";
export interface WaygentRunState { ... }
export function writeRunState(root: string, state: WaygentRunState): void { ... }
export function readRunState(root: string, runId: string): WaygentRunState { ... }
```

Keep `runStatePath`, `hasRunState`, `writeRunStateV2`, and `readRunStateV2`.
Add this result type and helper:

```ts
export type RunStateV2ReadResult =
  | { status: "ok"; state: WaygentRunStateV2 }
  | { status: "missing"; reason: "missing_run_state_v2" }
  | { status: "unsupported"; reason: "unsupported_run_state"; schema: unknown }
  | { status: "invalid"; reason: "invalid_run_state_v2"; error: string };

export function readRunStateV2Result(root: string, runId: string): RunStateV2ReadResult {
  const path = runStatePath(root, runId);
  if (!existsSync(path)) return { status: "missing", reason: "missing_run_state_v2" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
  } catch (error) {
    return { status: "invalid", reason: "invalid_run_state_v2", error: error instanceof Error ? error.message : String(error) };
  }
  const schema = parsed && typeof parsed === "object" ? (parsed as { schema?: unknown }).schema : undefined;
  if (schema !== "waygent.run_state.v2") return { status: "unsupported", reason: "unsupported_run_state", schema };
  try {
    return { status: "ok", state: validateContract<WaygentRunStateV2>("waygent.run_state.v2", parsed) };
  } catch (error) {
    return { status: "invalid", reason: "invalid_run_state_v2", error: error instanceof Error ? error.message : String(error) };
  }
}
```

- [ ] **Step 4: Run the focused state test and confirm it passes**

Run:

```bash
bun test packages/orchestrator/tests/runStateV2.test.ts
```

Expected: PASS.

- [ ] **Step 5: Write failing command tests for missing and unsupported v2 state**

Add tests to `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
test("resume blocks runs without v2 state", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-run-commands-v2-"));
  const runId = "run_missing_state";
  const paths = runPaths(root, runId);
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: {}
  }));

  expect(resumeRun({ root, run: runId, dry_run: true })).toEqual({
    run_id: runId,
    allowed_actions: ["inspect_run", "human_decision"],
    dry_run: true,
    blocked_by: "missing_run_state_v2"
  });
});

test("apply blocks unsupported state schema", async () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-workspace-"));
  spawnSync("git", ["init"], { cwd: workspace });
  spawnSync("git", ["config", "user.email", "test@example.com"], { cwd: workspace });
  spawnSync("git", ["config", "user.name", "Test User"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "hello\n");
  spawnSync("git", ["add", "README.md"], { cwd: workspace });
  spawnSync("git", ["commit", "-m", "init"], { cwd: workspace });

  const root = mkdtempSync(join(tmpdir(), "waygent-run-commands-v2-"));
  const runId = "run_unsupported_state";
  mkdirSync(join(root, runId), { recursive: true });
  writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: "waygent.run_state.v1", run_id: runId }));

  await expect(applyRun({ root, run: runId, workspace })).resolves.toEqual({
    command: "apply",
    run_id: runId,
    status: "blocked",
    reason: "unsupported_run_state"
  });
});
```

Ensure the file imports `appendEvent`, `runPaths`, `buildRunEvent`,
`resumeRun`, `applyRun`, and Node helpers it uses.

- [ ] **Step 6: Run command tests and confirm they fail**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: FAIL because command return shapes still use v1 fallback.

- [ ] **Step 7: Rewrite `runCommands.ts` around v2 classifier**

In `packages/orchestrator/src/runCommands.ts`, replace the v1 imports:

```ts
import { hasRunState, readRunState, writeRunState, type WaygentRunState } from "./runState";
```

with:

```ts
import { readRunStateV2Result, writeRunStateV2, type RunStateV2ReadResult, type WaygentRunStateV2 } from "./runState";
```

Change `inspectRun` return type to include v2 state metadata:

```ts
state?: WaygentRunStateV2;
state_error?: Exclude<RunStateV2ReadResult, { status: "ok" }>;
```

Implement this helper:

```ts
function stateBlocker(result: Exclude<RunStateV2ReadResult, { status: "ok" }>): "missing_run_state_v2" | "unsupported_run_state" | "invalid_run_state_v2" {
  return result.reason;
}
```

Update `inspectRun` so it calls `readRunStateV2Result` and attaches `state`
only for `status === "ok"`. For missing, unsupported, and invalid states,
attach `state_error`.

Update `resumeRun` so a non-ok state result returns:

```ts
{
  run_id: explanation.run_id,
  allowed_actions: ["inspect_run", "human_decision"],
  dry_run: options.dry_run ?? false,
  blocked_by: stateBlocker(result)
}
```

Update the exported return type of `resumeRun` to include:

```ts
blocked_by?: "missing_run_state_v2" | "unsupported_run_state" | "invalid_run_state_v2";
```

Update `applyRun` so after dirty-check it blocks on non-ok state:

```ts
const stateResult = readRunStateV2Result(options.root, runId);
if (stateResult.status !== "ok") {
  const reason = stateBlocker(stateResult);
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: "runway.apply_blocked",
    phase: "apply",
    outcome: "blocked",
    summary: "Apply blocked because Waygent v2 run state is unavailable.",
    payload: { reason },
    trust_impact: "requires_review"
  }));
  return { command: "apply", run_id: runId, status: "blocked", reason };
}
const v2State = stateResult.state;
```

Remove the final event-only success fallback at the bottom of `applyRun`.

- [ ] **Step 8: Delete the v1 state test file**

Delete:

```bash
git rm packages/orchestrator/tests/runState.test.ts
```

- [ ] **Step 9: Run focused command and state tests**

Run:

```bash
bun test packages/orchestrator/tests/runStateV2.test.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/runCommands.test.ts
```

Expected: PASS.

- [ ] **Step 10: Commit Phase 1 state cleanup**

Run:

```bash
git add packages/orchestrator/src/runState.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runStateV2.test.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runState.test.ts
git commit -m "refactor: require Waygent v2 run state"
```

### Task 2: Remove AgentRunway Plan Fence Compatibility

**Files:**
- Modify: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/planDiscovery.ts`
- Modify: `packages/orchestrator/tests/planParser.test.ts`
- Modify: `packages/orchestrator/tests/planDiscovery.test.ts`

- [ ] **Step 1: Change parser test from import compatibility to rejection**

In `packages/orchestrator/tests/planParser.test.ts`, replace the old
`agentrunway-task` import test with:

```ts
test("rejects legacy agentrunway-task fences", () => {
  const plan = `
\`\`\`yaml agentrunway-task
id: task_old
title: Old task
dependencies: []
risk: low
\`\`\`
`;

  expect(() => parseWaygentPlan(plan)).toThrow("missing waygent-task block");
});
```

- [ ] **Step 2: Add plan discovery test for ignoring legacy-only markdown**

In `packages/orchestrator/tests/planDiscovery.test.ts`, add:

```ts
test("latest discovery ignores markdown with only legacy agentrunway-task fences", () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-discovery-"));
  mkdirSync(join(workspace, "docs", "migration"), { recursive: true });
  writeFileSync(join(workspace, "docs", "migration", "2026-05-22-old.md"), `
\`\`\`yaml agentrunway-task
id: task_old
title: Old task
dependencies: []
risk: low
\`\`\`
`);

  expect(() => resolvePlanInput({ workspace, latest: true })).toThrow("no Waygent plan found");
});
```

- [ ] **Step 3: Run parser and discovery tests and confirm they fail**

Run:

```bash
bun test packages/orchestrator/tests/planParser.test.ts packages/orchestrator/tests/planDiscovery.test.ts
```

Expected: FAIL because legacy fences are still accepted.

- [ ] **Step 4: Remove legacy fence support**

In `packages/orchestrator/src/planParser.ts`, change:

```ts
const TASK_BLOCK = /```yaml (?:waygent-task|agentrunway-task)\n([\s\S]*?)\n```/g;
```

to:

```ts
const TASK_BLOCK = /```yaml waygent-task\n([\s\S]*?)\n```/g;
```

In `packages/orchestrator/src/planDiscovery.ts`, change:

```ts
const PLAN_MARKER = /```yaml (?:waygent-task|agentrunway-task)\n/;
```

to:

```ts
const PLAN_MARKER = /```yaml waygent-task\n/;
```

- [ ] **Step 5: Run parser and discovery tests**

Run:

```bash
bun test packages/orchestrator/tests/planParser.test.ts packages/orchestrator/tests/planDiscovery.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit Phase 1 plan marker cleanup**

Run:

```bash
git add packages/orchestrator/src/planParser.ts packages/orchestrator/src/planDiscovery.ts packages/orchestrator/tests/planParser.test.ts packages/orchestrator/tests/planDiscovery.test.ts
git commit -m "refactor: require Waygent task fences"
```

### Task 3: Remove Legacy Source From TypeScript Projections

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`
- Modify: `tests/fixtures/contracts/valid-lens-runway-projection.json`
- Modify: `packages/lens-projectors/src/trust.ts`
- Modify: `packages/lens-projectors/tests/trust.test.ts`

- [ ] **Step 1: Write failing contract expectations**

In `packages/contracts/tests/contracts.test.ts`, update the canonical
`lens.runway_projection.v1` object by deleting `legacy_source`.

Add this assertion near the projection contract test:

```ts
expect(() => validateContract("lens.runway_projection.v1", {
  schema: "lens.runway_projection.v1",
  run_id: "run_projection_extra",
  status: "completed",
  safe_wave: [],
  trust_status: "trusted",
  event_count: 1,
  legacy_source: "agentrunway"
})).toThrow();
```

Update `tests/fixtures/contracts/valid-lens-runway-projection.json` by
removing the `legacy_source` property.

- [ ] **Step 2: Update projector test expectations**

In `packages/lens-projectors/tests/trust.test.ts`, remove the local
`legacy_source` type field and replace the legacy projection test with:

```ts
test("runway projection does not expose legacy source metadata", () => {
  const projection = projectRunwayProjection([
    demoEvent({ event_type: "agentrunway.worker_started", outcome: "running", sequence: 1 })
  ]);

  expect(projection).toEqual({
    schema: "lens.runway_projection.v1",
    run_id: "run_demo",
    status: "running",
    safe_wave: [],
    trust_status: "insufficient_evidence",
    event_count: 1
  });
});
```

- [ ] **Step 3: Run contracts and projector tests and confirm they fail**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts packages/contracts/tests/fixtures.test.ts packages/lens-projectors/tests/trust.test.ts
```

Expected: FAIL because `legacy_source` is still required by the schema and
projector.

- [ ] **Step 4: Remove `legacy_source` from TypeScript contracts**

In `packages/contracts/src/types.ts`, change:

```ts
export interface LensRunwayProjection {
  schema: "lens.runway_projection.v1";
  run_id: string;
  status: RunStatus;
  safe_wave: string[];
  trust_status: "trusted" | "failed" | "insufficient_evidence";
  event_count: number;
  legacy_source: "agentrunway" | null;
}
```

to:

```ts
export interface LensRunwayProjection {
  schema: "lens.runway_projection.v1";
  run_id: string;
  status: RunStatus;
  safe_wave: string[];
  trust_status: "trusted" | "failed" | "insufficient_evidence";
  event_count: number;
}
```

In `packages/contracts/src/schemas.ts`, remove `legacy_source` from the
`required` array and remove the `legacy_source` property definition.

- [ ] **Step 5: Remove special-case legacy projection logic**

In `packages/lens-projectors/src/trust.ts`, delete:

```ts
const legacy = events.some((event) => event.event_type.startsWith("agentrunway."));
```

and delete this property from the returned object:

```ts
legacy_source: legacy ? "agentrunway" : null
```

- [ ] **Step 6: Run contracts and projector tests**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts packages/contracts/tests/fixtures.test.ts packages/lens-projectors/tests/trust.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit Phase 1 projection cleanup**

Run:

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts tests/fixtures/contracts/valid-lens-runway-projection.json packages/lens-projectors/src/trust.ts packages/lens-projectors/tests/trust.test.ts
git commit -m "refactor: remove legacy runway projection source"
```

### Task 4: Strengthen Legacy Guard And Active Docs

**Files:**
- Modify: `packages/testkit/src/legacyCheck.ts`
- Modify: `packages/testkit/tests/legacyCheck.test.ts`
- Modify: `code_review.md`
- Modify: `AGENTS.md` if active wording still frames AgentRunway as a route

- [ ] **Step 1: Add failing legacy guard tests**

In `packages/testkit/tests/legacyCheck.test.ts`, add:

```ts
test("rejects active legacy Waygent compatibility tokens", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-legacy-check-"));
  mkdirSync(join(root, "packages", "orchestrator", "src"), { recursive: true });
  writeFileSync(join(root, "packages", "orchestrator", "src", "bad.ts"), [
    "const schema = 'waygent.run_state.v1';",
    "const marker = '```yaml agentrunway-task';",
    "const projection = { legacy_source: 'agentrunway' };"
  ].join("\n"));

  const result = runLegacyCheck(root);

  expect(result.violations).toContain("packages/orchestrator/src/bad.ts: legacy Waygent v1 state schema in product tree");
  expect(result.violations).toContain("packages/orchestrator/src/bad.ts: legacy AgentRunway task fence in product tree");
  expect(result.violations).toContain("packages/orchestrator/src/bad.ts: legacy projection source in product tree");
});

test("allows legacy guard implementation to contain banned tokens", () => {
  const result = runLegacyCheck(process.cwd());
  expect(result.violations.filter((item) => item.startsWith("packages/testkit/"))).toEqual([]);
});
```

- [ ] **Step 2: Run legacy guard tests and confirm they fail**

Run:

```bash
bun test packages/testkit/tests/legacyCheck.test.ts
```

Expected: FAIL because the new tokens are not checked and `packages/testkit`
is not excluded from the broad product scan.

- [ ] **Step 3: Strengthen `legacyCheck.ts`**

In `packages/testkit/src/legacyCheck.ts`, add this helper:

```ts
function isTestkitPath(rel: string): boolean {
  return rel === "packages/testkit" || rel.startsWith("packages/testkit/");
}
```

At the top of `walk`, after `const rel = relative(root, path);`, skip the
testkit package:

```ts
if (isTestkitPath(rel)) return;
```

After reading `text`, add:

```ts
if (/waygent\.run_state\.v1/.test(text)) {
  violations.push(`${rel}: legacy Waygent v1 state schema in product tree`);
}
if (/agentrunway-task/.test(text)) {
  violations.push(`${rel}: legacy AgentRunway task fence in product tree`);
}
if (/legacy_source/.test(text)) {
  violations.push(`${rel}: legacy projection source in product tree`);
}
```

In `walkActiveRouting`, replace the inline testkit skip with `isTestkitPath(rel)`.

- [ ] **Step 4: Update review docs to current runtime names**

In `code_review.md`, replace:

```md
- Observability: For AgentLens/AgentRunway changes, are durable artifacts,
```

with:

```md
- Observability: For AgentLens/Waygent changes, are durable artifacts,
```

Replace:

```md
## AgentRunway Checks
```

with:

```md
## Waygent Runtime Checks
```

Replace the bullets in that section with:

```md
- Providers do not write SQLite or AgentLens directly.
- Scheduler changes respect safe waves, dependency checkpoints, and failure
  barriers.
- Recovery paths stop on missing handlers or human-decision classes instead of
  recording fake progress.
- Runtime behavior changes include targeted tests or scenario harness coverage.
```

- [ ] **Step 5: Run legacy guard and docs hygiene**

Run:

```bash
bun test packages/testkit/tests/legacyCheck.test.ts
bun run check:legacy
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 6: Commit Phase 1 guard and docs cleanup**

Run:

```bash
git add packages/testkit/src/legacyCheck.ts packages/testkit/tests/legacyCheck.test.ts code_review.md AGENTS.md
git commit -m "test: guard Waygent no-legacy runtime"
```

### Task 5: Run Phase 1 Acceptance Gate

**Files:**
- No source edits unless a verification failure identifies a Phase 1 regression.

- [ ] **Step 1: Search for disallowed active TypeScript legacy tokens**

Run:

```bash
rg -n "waygent\\.run_state\\.v1|agentrunway-task|legacy_source" apps packages native tests code_review.md AGENTS.md --glob '!packages/testkit/**' --glob '!**/node_modules/**' --glob '!**/dist/**'
```

Expected: no output.

- [ ] **Step 2: Run full Phase 1 verification**

Run:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Expected:

- `bun run check`: PASS, with the live provider smoke still skipped unless explicitly enabled.
- `bun run waygent:scenarios`: PASS.
- `bun run platform:demo`: prints a trusted demo run.
- `bun run check:legacy`: prints `legacy checks passed`.
- console build: PASS.
- `git diff --check`: no output.

- [ ] **Step 3: Commit any verification-only fixes**

If Step 2 exposed a regression and files were changed to fix it, commit those
files with:

```bash
git add <changed-files>
git commit -m "fix: complete Waygent no-legacy runtime gate"
```

If no files changed, do not create an empty commit.

- [ ] **Step 4: Record Phase 1 handoff status**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: clean worktree, branch ahead count only.

Phase 2 starts only after this task is complete.

---

## Phase 2: AgentLens Python Cleanup

Default mode: rename-and-reshape AgentRunway trust-console artifacts into
Waygent-native artifacts. Use full deletion only if the user explicitly
changes direction before Task 6 starts.

### Task 6: Add Waygent-Native AgentLens Projection Modules

**Files:**
- Create: `components/agentlens/src/agentlens/evaluator/waygent_events.py`
- Create: `components/agentlens/src/agentlens/evaluator/waygent_projection.py`
- Modify: `components/agentlens/tests/unit/test_waygent_events.py`

- [ ] **Step 1: Write tests for Waygent event projection**

Replace imports in `components/agentlens/tests/unit/test_waygent_events.py` so
the file imports the new modules:

```py
from agentlens.evaluator.waygent_projection import project_events
from agentlens.evaluator.waygent_events import build_evidence_coverage
```

Add this test:

```py
def test_waygent_events_project_to_waygent_projection() -> None:
    projection = project_events(
        [
            {
                "event_type": "platform.run_started",
                "payload": {"run_id": "run_waygent"},
                "producer": {"name": "waygent"},
            },
            {
                "event_type": "runway.verification_result",
                "payload": {"task_id": "task_verify", "status": "passed"},
                "producer": {"name": "waygent"},
            },
            {
                "event_type": "lens.trust_report_updated",
                "payload": {"trust_status": "trusted"},
                "producer": {"name": "waygent"},
            },
        ]
    )

    assert projection["schema"] == "agentlens.waygent_projection.v1"
    assert projection["waygent_run_id"] == "run_waygent"
    assert projection["producer"] == "waygent"
    assert projection["event_count"] == 3
```

Add this coverage test:

```py
def test_waygent_evidence_coverage_counts_active_event_families() -> None:
    coverage = build_evidence_coverage(
        [
            {"event_type": "platform.run_started", "payload": {}},
            {"event_type": "runway.verification_result", "payload": {}},
            {"event_type": "kernel.execution_result", "payload": {}},
            {"event_type": "lens.trust_report_updated", "payload": {}},
        ],
        run={"agent": {"name": "waygent"}},
    )

    assert coverage["producer"] == "waygent"
    assert coverage["event_count"] == 4
    assert coverage["coverage"]["platform"] == 1
    assert coverage["coverage"]["runway"] == 1
    assert coverage["coverage"]["kernel"] == 1
    assert coverage["coverage"]["lens"] == 1
```

- [ ] **Step 2: Run the Waygent event tests and confirm they fail**

Run:

```bash
cd components/agentlens
python -m pytest tests/unit/test_waygent_events.py -q
```

Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Create `waygent_events.py`**

Create `components/agentlens/src/agentlens/evaluator/waygent_events.py`:

```py
"""Projection helpers for active Waygent events."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

WAYGENT_PREFIXES = ("platform.", "runway.", "kernel.", "lens.")


def is_waygent_event(event: Mapping[str, Any]) -> bool:
    event_type = event.get("event_type") or event.get("type")
    return isinstance(event_type, str) and event_type.startswith(WAYGENT_PREFIXES)


def build_evidence_coverage(
    events: Iterable[Mapping[str, Any]],
    run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event_list = [event for event in events if isinstance(event, Mapping) and is_waygent_event(event)]
    coverage = {"platform": 0, "runway": 0, "kernel": 0, "lens": 0}
    for event in event_list:
        event_type = str(event.get("event_type") or event.get("type") or "")
        family = event_type.split(".", 1)[0]
        if family in coverage:
            coverage[family] += 1
    run_agent = {}
    if isinstance(run, Mapping):
        candidate = run.get("agent")
        if isinstance(candidate, Mapping):
            run_agent = dict(candidate)
    return {
        "producer": "waygent",
        "event_count": len(event_list),
        "coverage": coverage,
        "run_agent": run_agent,
    }
```

- [ ] **Step 4: Create `waygent_projection.py`**

Create `components/agentlens/src/agentlens/evaluator/waygent_projection.py`:

```py
"""Waygent projection artifacts."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .waygent_events import is_waygent_event


def project_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    event_list = [event for event in events if isinstance(event, Mapping) and is_waygent_event(event)]
    run_id = None
    timeline: list[dict[str, Any]] = []
    tasks: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(event_list, start=1):
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        if run_id is None:
            candidate = payload.get("run_id") or event.get("run_id") or event.get("orchestrator_run_id")
            if isinstance(candidate, str):
                run_id = candidate
        event_type = str(event.get("event_type") or event.get("type") or "")
        timeline.append({
            "sequence": event.get("sequence", index),
            "type": event_type,
            "summary": event.get("summary", ""),
        })
        task_id = payload.get("task_id")
        if isinstance(task_id, str):
            tasks.setdefault(task_id, {"task_id": task_id, "events": []})["events"].append(event_type)
    return {
        "schema": "agentlens.waygent_projection.v1",
        "run_id": run_id,
        "waygent_run_id": run_id,
        "producer": "waygent",
        "status": "observed" if event_list else "empty",
        "event_count": len(event_list),
        "timeline": timeline,
        "tasks": list(tasks.values()),
    }
```

- [ ] **Step 5: Run Waygent event tests**

Run:

```bash
cd components/agentlens
python -m pytest tests/unit/test_waygent_events.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Waygent projection modules**

Run:

```bash
git add components/agentlens/src/agentlens/evaluator/waygent_events.py components/agentlens/src/agentlens/evaluator/waygent_projection.py components/agentlens/tests/unit/test_waygent_events.py
git commit -m "feat: add Waygent AgentLens projection"
```

### Task 7: Rename AgentLens Trust Artifacts And CLI Command

**Files:**
- Create: `components/agentlens/src/agentlens/commands/waygent.py`
- Delete: `components/agentlens/src/agentlens/commands/agentrunway.py`
- Modify: `components/agentlens/src/agentlens/cli.py`
- Modify: `components/agentlens/src/agentlens/store/trust_artifacts.py`
- Modify: `components/agentlens/src/agentlens/evaluator/engine.py`
- Modify: `components/agentlens/src/agentlens/evaluator/trust.py`
- Modify: `components/agentlens/tests/integration/test_trust_console_cli.py`
- Modify: `components/agentlens/tests/unit/test_trust_artifacts.py`

- [ ] **Step 1: Update CLI tests to expect `agentlens waygent`**

In `components/agentlens/tests/integration/test_trust_console_cli.py`,
rename the command test to:

```py
def test_waygent_cli_reports_trust_report_json(runner, monkeypatch, tmp_path):
```

Replace invocation:

```py
result = runner.invoke(app, ["agentrunway", run_id, "--format", "json"])
```

with:

```py
result = runner.invoke(app, ["waygent", run_id, "--format", "json"])
```

Replace expected field `agentrunway_run_id` in test fixtures with
`waygent_run_id`.

- [ ] **Step 2: Update trust artifact tests to expect Waygent projection path**

In `components/agentlens/tests/unit/test_trust_artifacts.py`, replace:

```py
assert projection_path == tmp_path / "artifacts" / "agentrunway_projection.json"
```

with:

```py
assert projection_path == tmp_path / "artifacts" / "waygent_projection.json"
```

Replace projection schema values with `agentlens.waygent_projection.v1`.
Replace `agentrunway_run_id` with `waygent_run_id`.

- [ ] **Step 3: Run command/artifact tests and confirm they fail**

Run:

```bash
cd components/agentlens
python -m pytest tests/integration/test_trust_console_cli.py tests/unit/test_trust_artifacts.py -q
```

Expected: FAIL because the CLI and artifact writer still use AgentRunway names.

- [ ] **Step 4: Add Waygent command and remove AgentRunway command**

Create `components/agentlens/src/agentlens/commands/waygent.py` by copying the
old command behavior and replacing public names:

```py
"""Waygent trust report command."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agentlens.schema.validate import SchemaError, validate_doc
from agentlens.store.paths import agentlens_home


def _find_run_dir(run_id: str) -> Optional[Path]:
    root = agentlens_home() / "runs"
    if not root.is_dir():
        return None
    for ws_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        candidate = ws_dir / run_id
        if candidate.is_dir():
            return candidate
    return None


def _load_trust_report(run_id: str) -> dict | None:
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        return None
    path = run_dir / "artifacts" / "trust_report.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_doc(payload, schema_name="trust_report")
    return payload


def waygent(
    run_id: str = typer.Argument(..., help="run_id to inspect"),
    format: str = typer.Option("text", "--format", help="output format: 'text' or 'json'"),
) -> None:
    """Print the Waygent trust report for a run."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(f"unknown --format {format!r}; expected 'text' or 'json'")
    try:
        report = _load_trust_report(run_id)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        if format == "json":
            typer.echo(json.dumps({"run_id": run_id, "trust_report_error": str(exc)}, sort_keys=True))
            return
        typer.echo(f"trust_report_error: {exc}")
        return
    if report is None:
        if format == "json":
            typer.echo("null")
            return
        typer.echo("(no trust report)")
        return
    if format == "json":
        typer.echo(json.dumps(report, sort_keys=True))
        return
    for key in ("run_id", "waygent_run_id", "claimed_outcome", "trust_verdict", "evidence_strength"):
        typer.echo(f"{key}: {report.get(key)}")


__all__ = ["waygent"]
```

Delete `components/agentlens/src/agentlens/commands/agentrunway.py`.

In `components/agentlens/src/agentlens/cli.py`, replace:

```py
from .commands import agentrunway as agentrunway_cmd
app.command(name="agentrunway")(agentrunway_cmd.agentrunway)
```

with:

```py
from .commands import waygent as waygent_cmd
app.command(name="waygent")(waygent_cmd.waygent)
```

- [ ] **Step 5: Rename trust artifact output path**

In `components/agentlens/src/agentlens/store/trust_artifacts.py`, change the
projection path from:

```py
path = _artifacts_dir(run_dir) / "agentrunway_projection.json"
```

to:

```py
path = _artifacts_dir(run_dir) / "waygent_projection.json"
```

- [ ] **Step 6: Update evaluator engine imports and artifact refs**

In `components/agentlens/src/agentlens/evaluator/engine.py`, replace:

```py
from .agentrunway_v2 import project_events
from .agentrunway_events import build_evidence_coverage
```

with:

```py
from .waygent_projection import project_events
from .waygent_events import build_evidence_coverage
```

Replace:

```py
doc["projection_ref"] = "artifacts/agentrunway_projection.json"
```

with:

```py
doc["projection_ref"] = "artifacts/waygent_projection.json"
```

Rename `_is_agentrunway_context` to `_is_waygent_context` and make it return
true for nonzero Waygent event coverage or run agent names containing
`waygent`.

- [ ] **Step 7: Update trust report field names**

In `components/agentlens/src/agentlens/evaluator/trust.py`, replace
`agentrunway_run_id` with `waygent_run_id`. Replace user-facing strings that
say `AgentRunway` with `Waygent`.

- [ ] **Step 8: Run command/artifact tests**

Run:

```bash
cd components/agentlens
python -m pytest tests/integration/test_trust_console_cli.py tests/unit/test_trust_artifacts.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit command and artifact rename**

Run:

```bash
git add components/agentlens/src/agentlens/commands/waygent.py components/agentlens/src/agentlens/commands/agentrunway.py components/agentlens/src/agentlens/cli.py components/agentlens/src/agentlens/store/trust_artifacts.py components/agentlens/src/agentlens/evaluator/engine.py components/agentlens/src/agentlens/evaluator/trust.py components/agentlens/tests/integration/test_trust_console_cli.py components/agentlens/tests/unit/test_trust_artifacts.py
git commit -m "refactor: rename AgentLens trust command to Waygent"
```

### Task 8: Rename AgentLens Schemas And Fixtures

**Files:**
- Modify: `components/agentlens/src/agentlens/constants.py`
- Modify: `components/agentlens/src/agentlens/schema/validate.py`
- Create: `components/agentlens/src/agentlens/schema/jsonschema/waygent_projection.v1.schema.json`
- Delete: `components/agentlens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json`
- Modify: `components/agentlens/src/agentlens/schema/jsonschema/run.v2.schema.json`
- Modify: `components/agentlens/src/agentlens/schema/jsonschema/event.v2.schema.json`
- Modify: `components/agentlens/src/agentlens/schema/jsonschema/trust_report.v1.schema.json`
- Modify: `components/agentlens/tests/fixtures/schemas/v2/valid/*`
- Modify: `components/agentlens/tests/unit/test_schema_v2_validation.py`

- [ ] **Step 1: Update schema validation tests to Waygent names**

In `components/agentlens/tests/unit/test_schema_v2_validation.py`, replace
schema fixture references:

```py
"agentrunway_projection"
```

with:

```py
"waygent_projection"
```

Replace fixture filename expectations:

```py
("agentrunway_projection.json", "agentrunway_projection")
```

with:

```py
("waygent_projection.json", "waygent_projection")
```

- [ ] **Step 2: Run schema tests and confirm they fail**

Run:

```bash
cd components/agentlens
python -m pytest tests/unit/test_schema_v2_validation.py -q
```

Expected: FAIL because the Waygent schema is not registered yet.

- [ ] **Step 3: Update constants and schema registry**

In `components/agentlens/src/agentlens/constants.py`, replace:

```py
SCHEMA_AGENTRUNWAY_PROJECTION_V1 = "agentlens.agentrunway_projection.v1"
```

with:

```py
SCHEMA_WAYGENT_PROJECTION_V1 = "agentlens.waygent_projection.v1"
```

In `components/agentlens/src/agentlens/schema/validate.py`, replace registry
entries for `agentrunway_projection` with `waygent_projection`:

```py
"waygent_projection": "waygent_projection.v1.schema.json",
"agentlens.waygent_projection.v1": "waygent_projection",
```

- [ ] **Step 4: Create Waygent projection schema**

Create `components/agentlens/src/agentlens/schema/jsonschema/waygent_projection.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agentlens.dev/schemas/agentlens.waygent_projection.v1.json",
  "title": "agentlens.waygent_projection.v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "run_id", "waygent_run_id", "producer", "status", "event_count", "timeline", "tasks"],
  "properties": {
    "schema": { "type": "string", "const": "agentlens.waygent_projection.v1" },
    "run_id": { "type": ["string", "null"] },
    "waygent_run_id": { "type": ["string", "null"] },
    "producer": { "type": "string", "const": "waygent" },
    "status": { "type": "string" },
    "event_count": { "type": "integer", "minimum": 0 },
    "timeline": { "type": "array", "items": { "type": "object" } },
    "tasks": { "type": "array", "items": { "type": "object" } }
  }
}
```

Delete `components/agentlens/src/agentlens/schema/jsonschema/agentrunway_projection.v1.schema.json`.

- [ ] **Step 5: Update hard-coded producer schemas**

In `run.v2.schema.json`, replace hard-coded `agentrunway` producer/adapter
constants with `waygent` where the schema represents current product runs.

In `event.v2.schema.json`, change the event type pattern from
`^agentrunway\\.` to a pattern that accepts active Waygent families:

```json
"^(platform|runway|kernel|lens)\\.[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)?$"
```

In `trust_report.v1.schema.json`, replace `agentrunway_run_id` with
`waygent_run_id`.

- [ ] **Step 6: Rename schema fixtures**

Rename:

```bash
git mv components/agentlens/tests/fixtures/schemas/v2/valid/agentrunway_projection.json components/agentlens/tests/fixtures/schemas/v2/valid/waygent_projection.json
```

Edit the renamed fixture so it uses:

```json
{
  "schema": "agentlens.waygent_projection.v1",
  "waygent_run_id": "run_waygent",
  "producer": "waygent"
}
```

Update other v2 valid fixtures by replacing:

- `agentrunway_run_id` with `waygent_run_id`
- `producer.name = agentrunway` with `producer.name = waygent`
- `adapter = agentrunway` with `adapter = waygent`
- AgentRunway summaries with Waygent summaries

- [ ] **Step 7: Run schema tests**

Run:

```bash
cd components/agentlens
python -m pytest tests/unit/test_schema_v2_validation.py tests/unit/test_schema_validation.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit schema rename**

Run:

```bash
git add components/agentlens/src/agentlens/constants.py components/agentlens/src/agentlens/schema/validate.py components/agentlens/src/agentlens/schema/jsonschema components/agentlens/tests/fixtures/schemas components/agentlens/tests/unit/test_schema_v2_validation.py components/agentlens/tests/unit/test_schema_validation.py
git commit -m "refactor: rename AgentLens schemas to Waygent"
```

### Task 9: Remove Old AgentRunway Python Projection Modules And Tests

**Files:**
- Delete: `components/agentlens/src/agentlens/evaluator/agentrunway_events.py`
- Delete: `components/agentlens/src/agentlens/evaluator/agentrunway_v2.py`
- Modify or delete: `components/agentlens/tests/unit/test_agentrunway_events.py`
- Modify: AgentLens integration tests that use `agentrunway.*` as current examples
- Modify: AgentLens expected eval fixtures under `components/agentlens/tests/fixtures`

- [ ] **Step 1: Search Python AgentLens active AgentRunway references**

Run:

```bash
rg -n "agentrunway|AgentRunway|agentrunway_projection|agentrunway_run_id" components/agentlens/src/agentlens components/agentlens/tests --glob '!**/__pycache__/**'
```

Expected: output listing the old modules, command tests, schema fixtures, and
expected eval fixtures that still need migration.

- [ ] **Step 2: Remove old projection modules**

Run:

```bash
git rm components/agentlens/src/agentlens/evaluator/agentrunway_events.py
git rm components/agentlens/src/agentlens/evaluator/agentrunway_v2.py
```

- [ ] **Step 3: Replace AgentRunway-only unit tests with Waygent tests**

If `components/agentlens/tests/unit/test_agentrunway_events.py` only tests old
read compatibility, delete it:

```bash
git rm components/agentlens/tests/unit/test_agentrunway_events.py
```

If it contains reusable active-event projection assertions, move those
assertions into `components/agentlens/tests/unit/test_waygent_events.py` and
rewrite event families to `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.

- [ ] **Step 4: Update generic event query tests without preserving product legacy**

For generic event-query tests such as `test_event_query.py`,
replace example event types from `agentrunway.task_started` to
`runway.task_started`. Keep the glob semantics tests; only the example
namespace changes.

- [ ] **Step 5: Regenerate expected eval fixtures by running failing tests once**

Run:

```bash
cd components/agentlens
python -m pytest tests/unit tests/integration -q
```

Expected: FAIL in expected fixture comparisons that still reference old
AgentRunway artifact names or fields.

For each failed expected JSON fixture, update:

- `producer: "agentrunway"` to `producer: "waygent"`;
- `agentrunway_run_id` to `waygent_run_id`;
- `artifacts/agentrunway_projection.json` to `artifacts/waygent_projection.json`;
- `agentlens.agentrunway_projection.v1` to `agentlens.waygent_projection.v1`.

- [ ] **Step 6: Run AgentLens tests**

Run:

```bash
cd components/agentlens
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit old projection removal**

Run:

```bash
git add components/agentlens/src/agentlens/evaluator components/agentlens/tests
git commit -m "refactor: remove AgentLens AgentRunway projection"
```

### Task 10: Run Phase 2 Acceptance Gate

**Files:**
- Modify: `packages/testkit/src/legacyCheck.ts` only if the guard needs an AgentLens Python scan extension.
- Modify: `packages/testkit/tests/legacyCheck.test.ts` only if adding an AgentLens Python guard case.

- [ ] **Step 1: Search for remaining active AgentRunway references**

Run:

```bash
rg -n "agentlens agentrunway|agentrunway_projection|agentrunway_run_id|AgentRunway Trust Console|producer.*agentrunway|adapter.*agentrunway" components/agentlens/src/agentlens components/agentlens/tests --glob '!**/__pycache__/**'
```

Expected: no output. If output remains in archived or explicitly historical
fixtures, move those fixtures under an archived compatibility directory or
delete the compatibility fixture.

- [ ] **Step 2: Run AgentLens Python verification**

Run:

```bash
cd components/agentlens
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run TypeScript and legacy verification**

Run:

```bash
bun run check
bun run check:legacy
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 4: Commit Phase 2 verification fixes**

If Step 1 through Step 3 required changes, run:

```bash
git add <changed-files>
git commit -m "fix: complete AgentLens Waygent cleanup gate"
```

If no files changed, do not create an empty commit.

- [ ] **Step 5: Record final status**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: clean worktree.

## Final Verification

Run this from the repository root after Task 10:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
cd components/agentlens && python -m pytest -q
git diff --check
git status --short --branch --untracked-files=all
```

Expected:

- Waygent TypeScript checks pass.
- Waygent scenario replay passes.
- Platform demo reports a trusted run.
- Legacy guard passes.
- Console production build passes.
- AgentLens Python tests pass.
- Patch hygiene passes.
- Worktree is clean except branch ahead count.

## Review Checklist

Before reporting completion, review the final diff with `code_review.md` and
confirm:

- `apply` never mutates source checkout without valid v2 readiness.
- `resume` never infers readiness from events or v1 state.
- no active product path accepts `agentrunway-task`;
- no active TypeScript contract exposes `legacy_source`;
- AgentLens Python public command is Waygent-named;
- any remaining AgentRunway text is historical documentation or archived
  compatibility material.
