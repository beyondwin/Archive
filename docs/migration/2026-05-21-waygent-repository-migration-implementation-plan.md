# Waygent Repository Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the repository into a coherent Waygent product root, migrate AgentRunway execution semantics into Waygent runtime packages, and remove `skills/agent-runway` after parity is proven.

**Architecture:** Keep Waygent as the top-level product root with `apps/`, `packages/`, `native/`, `components/`, `skills/`, `docs/`, and `tests/`. Move AgentLens into `components/agentlens`, rename the web console to `apps/console`, and port runner behavior into TypeScript packages plus the Rust kernel boundary before deleting the old Python AgentRunway skill.

**Tech Stack:** Bun, TypeScript project references, React/Vite, Rust workspace crates, Python AgentLens package, pytest, git worktrees, JSONL event storage.

---

## Source Spec

- Design: `docs/migration/2026-05-21-waygent-repository-migration-design.md`
- Current pending change before this plan starts: `.gitignore` is modified and must be committed separately in Task 0.

## Execution Rules

- Work on `main` unless the user asks for a feature branch.
- Preserve unrelated user changes.
- Do not run `git clean`, `rm -rf`, or delete generated runtime directories without explicit user approval.
- Exclude `.DS_Store` from broad staging.
- Commit at the end of every task.
- If using subagents, use disjoint write ownership per task. Workers are not alone in the codebase and must not revert edits made by others.

## File Ownership Map

Task 0 owns only `.gitignore`.

Task 1 owns path moves and path references:
- Move: `AgentLens/` -> `components/agentlens/`
- Move: `apps/lens-web/` -> `apps/console/`
- Modify: `package.json`
- Modify: `apps/console/package.json`
- Modify: `tests/e2e/lens-console-model.test.ts`
- Modify: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `skills/README.md`
- Modify docs under `docs/`

Task 2 owns plan parsing:
- Create: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/planParser.test.ts`

Task 3 owns task graph conversion:
- Create: `packages/orchestrator/src/taskGraph.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/taskGraph.test.ts`

Task 4 owns durable run commands and run index:
- Create: `packages/lens-store/src/runIndex.ts`
- Create: `packages/orchestrator/src/runEvents.ts`
- Create: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/lens-store/src/index.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/lens-store/tests/runIndex.test.ts`
- Test: `packages/orchestrator/tests/runCommands.test.ts`

Task 5 owns real Waygent run execution:
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`
- Test: `apps/cli/tests/cli.test.ts`
- Test: `tests/integration/platform-demo.test.ts`

Task 6 owns worktree and apply parity:
- Modify: `native/kernel/crates/git-worktree/src/lib.rs`
- Modify: `packages/kernel-client/src/worktreeClient.ts`
- Modify: `packages/runway-control/src/projection.ts`
- Test: `packages/kernel-client/tests/worktreeClient.test.ts`
- Test: `packages/runway-control/tests/mergeApply.test.ts`
- Rust test: native kernel workspace

Task 7 owns contract migration:
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/lens-projectors/src/trust.ts`
- Create: `tests/fixtures/contracts/valid-lens-runway-projection.json`
- Test: `packages/contracts/tests/contracts.test.ts`
- Test: `packages/contracts/tests/fixtures.test.ts`
- Test: `packages/lens-projectors/tests/trust.test.ts`

Task 8 owns AgentLens read compatibility:
- Modify files under `components/agentlens/src/agentlens/`
- Modify files under `components/agentlens/tests/`
- Preserve legacy `agentrunway.*` read fixtures as legacy compatibility fixtures.

Task 9 owns AgentRunway removal:
- Delete: `skills/agent-runway/`
- Modify: `AGENTS.md`, `CLAUDE.md`, `skills/README.md`, `docs/architecture/waygent.md`, `docs/operations/waygent.md`
- Verify active routing no longer points at `skills/agent-runway`.

Task 10 owns final generated-file policy review:
- Modify ignore docs only if verification exposes missing patterns.
- Do not delete local generated files without user approval.

---

### Task 0: Commit Ignore Policy

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Inspect pending ignore diff**

Run:

```bash
git diff -- .gitignore
```

Expected: the diff contains only generated-output ignore patterns such as Bun logs, coverage outputs, JS tooling caches, and Rust profiling files.

- [ ] **Step 2: Confirm no newly ignored tracked files exist**

Run:

```bash
git ls-files -ci --exclude-standard
```

Expected: no output.

- [ ] **Step 3: Run hygiene check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Commit only `.gitignore`**

Run:

```bash
git add .gitignore
git commit -m "chore: extend generated file ignores"
```

Expected: commit succeeds and does not stage the migration plan or generated files.

- [ ] **Step 5: Confirm remaining status**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: the tree is clean or contains only changes intentionally created by the current task runner.

---

### Task 1: Move Product Structure Without Behavior Changes

**Files:**
- Move: `AgentLens/` -> `components/agentlens/`
- Move: `apps/lens-web/` -> `apps/console/`
- Modify: `package.json`
- Modify: `apps/console/package.json`
- Modify: `tests/e2e/lens-console-model.test.ts`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `GEMINI.md`
- Modify: `skills/README.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`

- [ ] **Step 1: Move directories with git**

Run:

```bash
mkdir -p components
git mv AgentLens components/agentlens
git mv apps/lens-web apps/console
```

Expected: `git status --short` shows renames instead of delete/add churn for tracked files.

- [ ] **Step 2: Update root package scripts**

In `package.json`, replace the test script path segment:

```json
"test": "bun test ./packages/contracts/tests ./packages/runway-control/tests ./packages/lens-projectors/tests ./packages/lens-store/tests ./packages/provider-adapters/tests ./packages/policy/tests ./packages/kernel-client/tests ./packages/orchestrator/tests ./packages/context-packer/tests ./apps/cli/tests ./apps/api/tests ./apps/console/src ./tests/e2e ./tests/integration"
```

Keep the existing `workspaces` value:

```json
"workspaces": [
  "apps/*",
  "packages/*"
]
```

- [ ] **Step 3: Rename console package**

In `apps/console/package.json`, set the package name to:

```json
"name": "@waygent/console"
```

Keep scripts unchanged:

```json
"scripts": {
  "dev": "vite --host 127.0.0.1",
  "build": "vite build",
  "test": "bun test src",
  "test:e2e": "bun test ../../tests/e2e"
}
```

- [ ] **Step 4: Update e2e import**

In `tests/e2e/lens-console-model.test.ts`, replace the import path with:

```ts
} from "../../apps/console/src/uiModel";
```

- [ ] **Step 5: Update repository instructions**

In `AGENTS.md`, update the active component paths to:

```markdown
- AgentLens Python package: `components/agentlens/src/agentlens/`
- AgentLens Python tests: `components/agentlens/tests/`
- Waygent console app: `apps/console/`
- Current docs: `components/agentlens/docs/` and root `docs/`
```

Replace the AgentLens verification commands with:

```bash
cd components/agentlens
python -m pip install -e .[test]
python -m pytest -q

cd apps/console
bun test src
bun run build
```

In `CLAUDE.md`, replace:

```bash
cd AgentLens && python -m pytest -q
cd AgentLens/web && npx vitest run && npm run build
```

with:

```bash
cd components/agentlens && python -m pytest -q
cd apps/console && bun test src && bun run build
```

In `GEMINI.md` and `skills/README.md`, replace active references to `AgentLens/` with `components/agentlens/` and `apps/lens-web` with `apps/console`.

- [ ] **Step 6: Update docs**

In `docs/architecture/waygent.md`, set the product tree sentence to:

```markdown
The product tree is `apps/`, `packages/`, `native/`, `components/`, `tests/`,
`docs/`, and `skills/waygent/`. AgentLens lives under
`components/agentlens/` as the observability and evaluation component.
```

In `docs/operations/waygent.md`, add console verification:

```bash
bun run --cwd apps/console build
```

- [ ] **Step 7: Rewrite remaining path references**

Run:

```bash
rg -n "AgentLens/|apps/lens-web|cd AgentLens|AgentLens/web" AGENTS.md CLAUDE.md GEMINI.md package.json docs tests apps components skills --glob '!**/node_modules/**' --glob '!**/dist/**'
```

Expected: remaining matches are only historical design/spec references that intentionally describe old paths. Active commands must use `components/agentlens` and `apps/console`.

- [ ] **Step 8: Verify structure move**

Run:

```bash
bun run check
bun run --cwd apps/console build
cd components/agentlens && python -m pytest -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 9: Commit structure move**

Run:

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git commit -m "refactor: align repository structure with Waygent"
```

Expected: commit succeeds and the status is clean after the commit.

---

### Task 2: Add Waygent Plan Parser

**Files:**
- Create: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/planParser.test.ts`

- [ ] **Step 1: Write failing parser tests**

Create `packages/orchestrator/tests/planParser.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";

const plan = `
# Demo Plan

### Task 1: Prepare
\`\`\`yaml waygent-task
id: task_prepare
title: Prepare workspace
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - bun test ./packages/orchestrator/tests
\`\`\`

### Task 2: Verify
\`\`\`yaml waygent-task
id: task_verify
title: Verify output
dependencies: [task_prepare]
file_claims:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
risk: medium
verify:
  - bun run check
\`\`\`
`;

describe("Waygent plan parser", () => {
  test("parses waygent-task blocks into typed task specs", () => {
    const parsed = parseWaygentPlan(plan);

    expect(parsed.tasks).toHaveLength(2);
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_prepare",
      title: "Prepare workspace",
      dependencies: [],
      risk: "low"
    });
    expect(parsed.tasks[0]?.file_claims).toEqual([{ path: "README.md", mode: "owned" }]);
    expect(parsed.tasks[1]?.dependencies).toEqual(["task_prepare"]);
    expect(parsed.tasks[1]?.verification_commands).toEqual(["bun run check"]);
  });

  test("rejects missing task ids", () => {
    expect(() =>
      parseWaygentPlan(`
\`\`\`yaml waygent-task
title: Missing id
dependencies: []
file_claims: []
risk: low
verify: []
\`\`\`
`)
    ).toThrow("missing required waygent-task fields: id");
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
bun test ./packages/orchestrator/tests/planParser.test.ts
```

Expected: fail because `packages/orchestrator/src/planParser.ts` does not exist.

- [ ] **Step 3: Implement parser**

Create `packages/orchestrator/src/planParser.ts`:

```ts
import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";

export interface ParsedWaygentTask {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verification_commands: string[];
}

export interface ParsedWaygentPlan {
  tasks: ParsedWaygentTask[];
}

const TASK_BLOCK = /```yaml waygent-task\n([\s\S]*?)\n```/g;
const VALID_RISK = new Set<RiskLevel>(["low", "medium", "high"]);
const VALID_CLAIM_MODE = new Set<FileClaimMode>(["owned", "shared_append", "read_only"]);

export function parseWaygentPlan(markdown: string): ParsedWaygentPlan {
  const tasks = [...markdown.matchAll(TASK_BLOCK)].map((match) => parseTaskBlock(match[1] ?? ""));
  if (tasks.length === 0) {
    throw new Error("missing waygent-task block");
  }
  return { tasks };
}

function parseTaskBlock(block: string): ParsedWaygentTask {
  const lines = block.split("\n").map((line) => line.trimEnd());
  const scalar = new Map<string, string>();
  const fileClaims: FileClaim[] = [];
  const verification: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]?.trim();
    if (!line) continue;
    const scalarMatch = line.match(/^([a-z_]+):\s*(.*)$/);
    if (scalarMatch && scalarMatch[1] !== "file_claims" && scalarMatch[1] !== "verify") {
      scalar.set(scalarMatch[1], scalarMatch[2]);
      continue;
    }
    if (line === "file_claims:") {
      index = readFileClaims(lines, index + 1, fileClaims) - 1;
      continue;
    }
    if (line === "verify:") {
      index = readStringList(lines, index + 1, verification) - 1;
    }
  }

  const missing = ["id", "title", "dependencies", "risk"].filter((key) => !scalar.has(key));
  if (missing.length > 0) {
    throw new Error(`missing required waygent-task fields: ${missing.join(", ")}`);
  }

  const risk = scalar.get("risk") as RiskLevel;
  if (!VALID_RISK.has(risk)) {
    throw new Error(`invalid risk ${risk}`);
  }

  return {
    id: scalar.get("id")!,
    title: scalar.get("title")!,
    dependencies: parseInlineList(scalar.get("dependencies")!),
    file_claims: fileClaims,
    risk,
    verification_commands: verification
  };
}

function readFileClaims(lines: string[], start: number, out: FileClaim[]): number {
  let current: Partial<FileClaim> | null = null;
  let index = start;
  for (; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (!line.startsWith("  - ") && !line.startsWith("    ")) break;
    const trimmed = line.trim();
    if (trimmed.startsWith("- path:")) {
      if (current) pushClaim(current, out);
      current = { path: trimmed.slice("- path:".length).trim() };
    } else if (trimmed.startsWith("mode:")) {
      current = current ?? {};
      current.mode = trimmed.slice("mode:".length).trim() as FileClaimMode;
    }
  }
  if (current) pushClaim(current, out);
  return index;
}

function pushClaim(claim: Partial<FileClaim>, out: FileClaim[]): void {
  if (!claim.path || !claim.mode) throw new Error("file_claims entries require path and mode");
  if (!VALID_CLAIM_MODE.has(claim.mode)) throw new Error(`invalid file claim mode ${claim.mode}`);
  out.push({ path: claim.path, mode: claim.mode });
}

function readStringList(lines: string[], start: number, out: string[]): number {
  let index = start;
  for (; index < lines.length; index += 1) {
    const trimmed = lines[index]?.trim() ?? "";
    if (!trimmed.startsWith("- ")) break;
    out.push(trimmed.slice(2).trim());
  }
  return index;
}

function parseInlineList(value: string): string[] {
  const trimmed = value.trim();
  if (trimmed === "[]") return [];
  if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) {
    throw new Error(`expected inline list, got ${value}`);
  }
  return trimmed
    .slice(1, -1)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
```

- [ ] **Step 4: Export parser**

In `packages/orchestrator/src/index.ts`, add:

```ts
export * from "./planParser";
```

- [ ] **Step 5: Verify parser tests**

Run:

```bash
bun test ./packages/orchestrator/tests/planParser.test.ts
```

Expected: pass.

- [ ] **Step 6: Commit parser**

Run:

```bash
git add packages/orchestrator/src/planParser.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/planParser.test.ts
git commit -m "feat: parse Waygent task plans"
```

Expected: commit succeeds.

---

### Task 3: Convert Parsed Plans Into Runway Task Graphs

**Files:**
- Create: `packages/orchestrator/src/taskGraph.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/taskGraph.test.ts`

- [ ] **Step 1: Write failing task graph tests**

Create `packages/orchestrator/tests/taskGraph.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";
import { buildTaskGraphFromPlan } from "../src/taskGraph";

describe("Waygent task graph conversion", () => {
  test("marks root tasks ready and dependent tasks pending", () => {
    const parsed = parseWaygentPlan(`
\`\`\`yaml waygent-task
id: task_a
title: A
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - bun test
\`\`\`
\`\`\`yaml waygent-task
id: task_b
title: B
dependencies: [task_a]
file_claims:
  - path: packages/orchestrator/src/taskGraph.ts
    mode: owned
risk: high
verify:
  - bun run check
\`\`\`
`);

    const graph = buildTaskGraphFromPlan(parsed);

    expect(graph.tasks.get("task_a")?.status).toBe("READY");
    expect(graph.tasks.get("task_b")?.status).toBe("PENDING");
    expect(graph.tasks.get("task_b")?.resource_locks).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
bun test ./packages/orchestrator/tests/taskGraph.test.ts
```

Expected: fail because `buildTaskGraphFromPlan` is missing.

- [ ] **Step 3: Implement task graph conversion**

Create `packages/orchestrator/src/taskGraph.ts`:

```ts
import { createTaskGraph, type TaskGraph, type TaskNode } from "@waygent/runway-control";
import type { ParsedWaygentPlan } from "./planParser";

export function buildTaskGraphFromPlan(plan: ParsedWaygentPlan): TaskGraph {
  const nodes: TaskNode[] = plan.tasks.map((task) => ({
    id: task.id,
    dependencies: task.dependencies,
    file_claims: task.file_claims,
    resource_locks: [],
    risk: task.risk,
    status: task.dependencies.length === 0 ? "READY" : "PENDING"
  }));
  return createTaskGraph(nodes);
}
```

- [ ] **Step 4: Export task graph conversion**

In `packages/orchestrator/src/index.ts`, add:

```ts
export * from "./taskGraph";
```

- [ ] **Step 5: Verify task graph tests and scheduler tests**

Run:

```bash
bun test ./packages/orchestrator/tests/taskGraph.test.ts ./packages/runway-control/tests/scheduler.test.ts
```

Expected: pass.

- [ ] **Step 6: Commit task graph conversion**

Run:

```bash
git add packages/orchestrator/src/taskGraph.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/taskGraph.test.ts
git commit -m "feat: build Waygent task graphs from plans"
```

Expected: commit succeeds.

---

### Task 4: Add Durable Run Index And Command Projections

**Files:**
- Create: `packages/lens-store/src/runIndex.ts`
- Create: `packages/orchestrator/src/runEvents.ts`
- Create: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/lens-store/src/index.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/lens-store/tests/runIndex.test.ts`
- Test: `packages/orchestrator/tests/runCommands.test.ts`

- [ ] **Step 1: Write failing run index tests**

Create `packages/lens-store/tests/runIndex.test.ts`:

```ts
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId, writeLatestRunId } from "../src/runIndex";

describe("run index", () => {
  test("writes and reads the latest run id", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-index-"));

    writeLatestRunId(root, "run_demo");

    expect(readLatestRunId(root)).toBe("run_demo");
    expect(readFileSync(join(root, "latest"), "utf8")).toBe("run_demo\n");
  });

  test("returns null when no latest pointer exists", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-index-empty-"));

    expect(readLatestRunId(root)).toBeNull();
  });
});
```

- [ ] **Step 2: Implement run index**

Create `packages/lens-store/src/runIndex.ts`:

```ts
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function writeLatestRunId(root: string, runId: string): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, "latest"), `${runId}\n`);
}

export function readLatestRunId(root: string): string | null {
  try {
    const value = readFileSync(join(root, "latest"), "utf8").trim();
    return value.length > 0 ? value : null;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}
```

In `packages/lens-store/src/index.ts`, add:

```ts
export * from "./runIndex";
```

- [ ] **Step 3: Write failing command projection tests**

Create `packages/orchestrator/tests/runCommands.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendEvent, runPaths, writeLatestRunId } from "@waygent/lens-store";
import { buildRunEvent, explainRun, resumeRun, statusRun } from "../src/runCommands";

describe("Waygent run commands", () => {
  test("status reads the latest run projection", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-status-"));
    const paths = runPaths(root, "run_demo");
    writeLatestRunId(root, "run_demo");
    appendEvent(paths.events, buildRunEvent({ run_id: "run_demo", sequence: 1, event_type: "platform.run_started", phase: "platform", outcome: "running", summary: "Run opened.", payload: {} }));
    appendEvent(paths.events, buildRunEvent({ run_id: "run_demo", sequence: 2, event_type: "runway.verification_result", phase: "verify", outcome: "success", summary: "Verified.", payload: { task_id: "task_demo" } }));

    expect(statusRun({ root, last: true })).toMatchObject({
      run_id: "run_demo",
      status: "completed",
      total_events: 2,
      last_event_type: "runway.verification_result"
    });
  });

  test("explain and resume expose blocked decision state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-explain-"));
    const paths = runPaths(root, "run_blocked");
    writeLatestRunId(root, "run_blocked");
    appendEvent(paths.events, buildRunEvent({ run_id: "run_blocked", sequence: 1, event_type: "runway.decision_packet_created", phase: "runway", outcome: "blocked", summary: "Verification failed.", payload: { task_id: "task_verify", failure_class: "verification_failed" } }));

    expect(explainRun({ root, last: true }).blocked_by).toBe("verification_failed");
    expect(resumeRun({ root, last: true, dry_run: true }).allowed_actions).toContain("retry_with_evidence");
  });
});
```

- [ ] **Step 4: Implement run events and commands**

Create `packages/orchestrator/src/runEvents.ts`:

```ts
import type { AgentLensEvent, EventOutcome, TrustImpact } from "@waygent/contracts";
import { nextSequence, readEvents } from "@waygent/lens-store";

export interface RunEventInput {
  run_id: string;
  sequence?: number;
  event_type: string;
  phase: string;
  outcome: EventOutcome;
  summary: string;
  payload: Record<string, unknown>;
  trust_impact?: TrustImpact;
}

export function buildRunEvent(input: RunEventInput): AgentLensEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_${input.run_id}_${input.sequence ?? 1}`,
    agentlens_run_id: `lens_${input.run_id}`,
    orchestrator_run_id: input.run_id,
    producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
    event_type: input.event_type,
    occurred_at: "2026-05-21T00:00:00Z",
    sequence: input.sequence ?? 1,
    phase: input.phase,
    outcome: input.outcome,
    severity: input.outcome === "failed" || input.outcome === "blocked" ? "error" : "info",
    trust_impact: input.trust_impact ?? (input.outcome === "success" ? "supports_success" : "neutral"),
    summary: input.summary,
    payload: input.payload
  };
}

export function nextRunEvent(path: string, input: Omit<RunEventInput, "sequence">): AgentLensEvent {
  return buildRunEvent({ ...input, sequence: nextSequence(readEvents(path)) });
}
```

Create `packages/orchestrator/src/runCommands.ts`:

```ts
import type { FailureClass, RunStatus } from "@waygent/contracts";
import { readEvents, readLatestRunId, rebuildRunSummary, runPaths } from "@waygent/lens-store";
import { projectFailureSummary, projectTrustReport } from "@waygent/lens-projectors";
export { buildRunEvent, nextRunEvent } from "./runEvents";

export interface RunCommandOptions {
  root: string;
  run?: string;
  last?: boolean;
}

export interface RunStatusView {
  run_id: string;
  status: RunStatus;
  total_events: number;
  last_event_type: string | null;
  trust_status: string;
}

export function resolveRunId(options: RunCommandOptions): string {
  if (options.run) return options.run;
  if (options.last) {
    const latest = readLatestRunId(options.root);
    if (latest) return latest;
  }
  throw new Error("run id required; pass --run <id> or --last");
}

export function statusRun(options: RunCommandOptions): RunStatusView {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const summary = rebuildRunSummary(events);
  const trust = projectTrustReport(events);
  const blocked = events.some((event) => event.outcome === "blocked");
  const failed = events.some((event) => event.outcome === "failed");
  const status: RunStatus = blocked ? "blocked" : failed ? "failed" : trust.trust_status === "trusted" ? "completed" : "running";
  return {
    run_id: runId,
    status,
    total_events: summary.total_events,
    last_event_type: summary.last_event_type,
    trust_status: trust.trust_status
  };
}

export function explainRun(options: RunCommandOptions): { run_id: string; blocked_by: FailureClass | "unknown" | null; summary: string } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const failure = projectFailureSummary(events)[0] ?? null;
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    summary: failure ? `${failure.task_id} blocked by ${failure.failure_class}` : "no active failure barrier"
  };
}

export function resumeRun(options: RunCommandOptions & { dry_run?: boolean }): { run_id: string; allowed_actions: string[]; dry_run: boolean } {
  const explanation = explainRun(options);
  return {
    run_id: explanation.run_id,
    allowed_actions: explanation.blocked_by === "verification_failed" ? ["retry_with_evidence", "update_plan"] : ["inspect_run"],
    dry_run: options.dry_run ?? false
  };
}
```

In `packages/orchestrator/src/index.ts`, add:

```ts
export * from "./runCommands";
export * from "./runEvents";
```

- [ ] **Step 5: Verify command tests**

Run:

```bash
bun test ./packages/lens-store/tests/runIndex.test.ts ./packages/orchestrator/tests/runCommands.test.ts
```

Expected: pass.

- [ ] **Step 6: Commit durable commands**

Run:

```bash
git add packages/lens-store/src/runIndex.ts packages/lens-store/src/index.ts packages/lens-store/tests/runIndex.test.ts packages/orchestrator/src/runEvents.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/runCommands.test.ts
git commit -m "feat: add Waygent durable run commands"
```

Expected: commit succeeds.

---

### Task 5: Replace Demo-Only Run Flow With Real Waygent Run Entry

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`
- Test: `apps/cli/tests/cli.test.ts`
- Test: `tests/integration/platform-demo.test.ts`

- [ ] **Step 1: Write failing orchestrator run test**

Create `packages/orchestrator/tests/orchestratorRun.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";

const plan = `
\`\`\`yaml waygent-task
id: task_demo
title: Demo task
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

describe("runWaygent", () => {
  test("runs a parsed plan through fake provider and durable events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-"));
    const result = await runWaygent({ root, run_id: "run_demo", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

    expect(readLatestRunId(root)).toBe("run_demo");
    expect(result.events.map((event) => event.event_type)).toEqual([
      "platform.run_started",
      "runway.plan_loaded",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "runway.verification_result",
      "lens.trust_report_updated"
    ]);
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.projection.safe_wave).toEqual(["task_demo"]);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
bun test ./packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected: fail because `runWaygent` is not exported.

- [ ] **Step 3: Implement real run entry while keeping demo wrapper**

In `packages/orchestrator/src/orchestrator.ts`, add `runWaygent` and make `runWaygentDemo` call it with a built-in plan. The implementation must:

```ts
import { writeLatestRunId } from "@waygent/lens-store";
import { parseWaygentPlan } from "./planParser";
import { buildTaskGraphFromPlan } from "./taskGraph";
import { buildRunEvent } from "./runEvents";
```

Append these event types in order:

```ts
[
  "platform.run_started",
  "runway.plan_loaded",
  "runway.safe_wave_selected",
  "runway.worker_result",
  "runway.verification_result",
  "lens.trust_report_updated"
]
```

Use `writeLatestRunId(options.root, runId)` after events are written. Keep the returned shape compatible with `WaygentRunResult`.

Use this built-in demo plan for `runWaygentDemo`:

```ts
const DEMO_PLAN = `
\`\`\`yaml waygent-task
id: task_demo
title: Demo task
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;
```

- [ ] **Step 4: Update CLI to use durable commands**

In `apps/cli/src/index.ts`, import:

```ts
import { defaultRunRoot, explainRun, intentToCommand, parseNaturalLanguageIntent, resumeRun, runWaygent, runWaygentDemo, statusRun } from "@waygent/orchestrator";
```

Change the run branch to call `runWaygent` when `--plan` or `--spec` is present and keep `demo` as the explicit demo command:

```ts
if (parsed.command === "run") {
  return runWaygent(options);
}
if (parsed.command === "demo") {
  return runWaygentDemo(options);
}
```

Change command projections:

```ts
if (parsed.command === "status" || parsed.command === "inspect") {
  return statusRun({ root: String(parsed.flags.root ?? defaultRunRoot()), run: typeof parsed.flags.run === "string" ? parsed.flags.run : undefined, last: Boolean(parsed.flags.last) });
}
if (parsed.command === "explain") {
  return explainRun({ root: String(parsed.flags.root ?? defaultRunRoot()), run: typeof parsed.flags.run === "string" ? parsed.flags.run : undefined, last: Boolean(parsed.flags.last) });
}
if (parsed.command === "resume") {
  return resumeRun({ root: String(parsed.flags.root ?? defaultRunRoot()), run: typeof parsed.flags.run === "string" ? parsed.flags.run : undefined, last: Boolean(parsed.flags.last), dry_run: true });
}
```

Keep `apply` returning a guarded response until Task 6:

```ts
if (parsed.command === "apply") {
  return { command: "apply", status: "requires_clean_source_checkout" };
}
```

- [ ] **Step 5: Update CLI tests**

In `apps/cli/tests/cli.test.ts`, keep existing assertions and add:

```ts
test("status reads a run created by run", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-cli-"));
  await runCli(["run", "--root", root, "--run", "run_cli"]);
  expect(await runCli(["status", "--root", root, "--last"])).toMatchObject({
    run_id: "run_cli",
    status: "completed"
  });
});
```

Add the imports required by that test:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
```

- [ ] **Step 6: Verify run flow**

Run:

```bash
bun test ./packages/orchestrator/tests/orchestratorRun.test.ts ./apps/cli/tests/cli.test.ts ./tests/integration/platform-demo.test.ts
bun run platform:demo
```

Expected: tests pass and demo prints JSON with `trust_status` equal to `trusted`.

- [ ] **Step 7: Commit run flow**

Run:

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts tests/integration/platform-demo.test.ts
git commit -m "feat: run Waygent plans through durable runtime"
```

Expected: commit succeeds.

---

### Task 6: Port Worktree And Explicit Apply Guardrails

**Files:**
- Modify: `native/kernel/crates/git-worktree/src/lib.rs`
- Modify: `packages/kernel-client/src/worktreeClient.ts`
- Modify: `packages/runway-control/src/projection.ts`
- Test: `packages/kernel-client/tests/worktreeClient.test.ts`
- Test: `packages/runway-control/tests/mergeApply.test.ts`

- [ ] **Step 1: Add failing worktree client tests**

In `packages/kernel-client/tests/worktreeClient.test.ts`, add:

```ts
import { describe, expect, test } from "bun:test";
import { buildApplyGuard, buildWorktreeBranch } from "../src/worktreeClient";

describe("worktree apply guard", () => {
  test("builds owned Waygent worktree branches", () => {
    expect(buildWorktreeBranch("run_demo", "task_demo")).toBe("waygent/run_demo/task_demo");
  });

  test("blocks apply on dirty source checkout", () => {
    expect(buildApplyGuard({ sourceDirty: true, merged: true, candidate_id: "candidate_demo", task_id: "task_demo" })).toMatchObject({
      can_apply: false,
      reason: "dirty_source_checkout"
    });
  });
});
```

- [ ] **Step 2: Implement TypeScript apply guard**

In `packages/kernel-client/src/worktreeClient.ts`, export:

```ts
export function buildWorktreeBranch(runId: string, taskId: string): string {
  return `waygent/${runId}/${taskId}`;
}

export interface ApplyGuardInput {
  sourceDirty: boolean;
  merged: boolean;
  candidate_id: string;
  task_id: string;
}

export interface ApplyGuard {
  can_apply: boolean;
  reason: "ready" | "dirty_source_checkout" | "candidate_not_merged";
  candidate_id: string;
  task_id: string;
}

export function buildApplyGuard(input: ApplyGuardInput): ApplyGuard {
  if (input.sourceDirty) {
    return { can_apply: false, reason: "dirty_source_checkout", candidate_id: input.candidate_id, task_id: input.task_id };
  }
  if (!input.merged) {
    return { can_apply: false, reason: "candidate_not_merged", candidate_id: input.candidate_id, task_id: input.task_id };
  }
  return { can_apply: true, reason: "ready", candidate_id: input.candidate_id, task_id: input.task_id };
}
```

- [ ] **Step 3: Add Rust branch validation tests**

In `native/kernel/crates/git-worktree/src/lib.rs`, add a test:

```rust
#[test]
fn accepts_waygent_owned_branch_names() {
    assert!(validate_owned_branch("waygent/run_demo/task_demo").is_ok());
    assert!(validate_owned_branch("../outside").is_err());
    assert!(validate_owned_branch("-bad").is_err());
}
```

- [ ] **Step 4: Implement Rust branch validation**

In `native/kernel/crates/git-worktree/src/lib.rs`, add:

```rust
pub fn validate_owned_branch(branch: &str) -> io::Result<()> {
    if !branch.starts_with("waygent/")
        || branch.contains("..")
        || branch.contains('\\')
        || branch.starts_with('-')
        || branch.ends_with('/')
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "unsafe branch"));
    }
    Ok(())
}
```

Call it at the top of `create_run_main`:

```rust
validate_owned_branch(branch)?;
```

- [ ] **Step 5: Verify apply and worktree checks**

Run:

```bash
bun test ./packages/kernel-client/tests/worktreeClient.test.ts ./packages/runway-control/tests/mergeApply.test.ts
cd native/kernel && cargo fmt --all -- --check
cd native/kernel && cargo clippy --workspace --all-targets -- -D warnings
cd native/kernel && cargo test --workspace
```

Expected: all commands pass.

- [ ] **Step 6: Commit apply guardrails**

Run:

```bash
git add packages/kernel-client/src/worktreeClient.ts packages/kernel-client/tests/worktreeClient.test.ts native/kernel/crates/git-worktree/src/lib.rs packages/runway-control/src/projection.ts packages/runway-control/tests/mergeApply.test.ts
git commit -m "feat: add Waygent worktree apply guardrails"
```

Expected: commit succeeds.

---

### Task 7: Add Lens Runway Projection Contract

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/lens-projectors/src/trust.ts`
- Create: `tests/fixtures/contracts/valid-lens-runway-projection.json`
- Test: `packages/contracts/tests/contracts.test.ts`
- Test: `packages/contracts/tests/fixtures.test.ts`
- Test: `packages/lens-projectors/tests/trust.test.ts`

- [ ] **Step 1: Write failing contract tests**

In `packages/contracts/tests/contracts.test.ts`, add:

```ts
test("validates lens runway projection contract", () => {
  expect(validateContract("lens.runway_projection.v1", {
    schema: "lens.runway_projection.v1",
    run_id: "run_demo",
    status: "completed",
    safe_wave: ["task_demo"],
    trust_status: "trusted",
    event_count: 6,
    legacy_source: null
  })).toMatchObject({
    schema: "lens.runway_projection.v1",
    run_id: "run_demo"
  });
});
```

Create `tests/fixtures/contracts/valid-lens-runway-projection.json`:

```json
{
  "schema": "lens.runway_projection.v1",
  "run_id": "run_demo",
  "status": "completed",
  "safe_wave": ["task_demo"],
  "trust_status": "trusted",
  "event_count": 6,
  "legacy_source": null
}
```

In `packages/contracts/tests/fixtures.test.ts`, add validation for the fixture:

```ts
expect(validateContract("lens.runway_projection.v1", fixture("valid-lens-runway-projection.json"))).toBeTruthy();
```

- [ ] **Step 2: Implement projection type and schema**

In `packages/contracts/src/types.ts`, add:

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

In `packages/contracts/src/schemas.ts`, add:

```ts
export const lensRunwayProjectionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["schema", "run_id", "status", "safe_wave", "trust_status", "event_count", "legacy_source"],
  properties: {
    schema: { const: "lens.runway_projection.v1" },
    run_id: { type: "string", pattern: idPattern },
    status: { enum: ["pending", "running", "blocked", "failed", "completed", "applied"] },
    safe_wave: { type: "array", items: { type: "string", pattern: idPattern } },
    trust_status: { enum: ["trusted", "failed", "insufficient_evidence"] },
    event_count: { type: "integer", minimum: 0 },
    legacy_source: { enum: ["agentrunway"], nullable: true }
  }
} as const;
```

Add it to `schemas`:

```ts
"lens.runway_projection.v1": lensRunwayProjectionSchema
```

- [ ] **Step 3: Project active and legacy event inputs**

In `packages/lens-projectors/src/trust.ts`, add:

```ts
import type { LensRunwayProjection, RunStatus } from "@waygent/contracts";

export function projectRunwayProjection(events: AgentLensEvent[], safe_wave: string[] = []): LensRunwayProjection {
  const trust = projectTrustReport(events);
  const failed = events.some((event) => event.outcome === "failed");
  const blocked = events.some((event) => event.outcome === "blocked");
  const status: RunStatus = blocked ? "blocked" : failed ? "failed" : trust.trust_status === "trusted" ? "completed" : "running";
  const legacy = events.some((event) => event.event_type.startsWith("agentrunway."));
  return {
    schema: "lens.runway_projection.v1",
    run_id: events[0]?.orchestrator_run_id ?? "run_empty",
    status,
    safe_wave,
    trust_status: trust.trust_status,
    event_count: events.length,
    legacy_source: legacy ? "agentrunway" : null
  };
}
```

- [ ] **Step 4: Verify contracts and projectors**

Run:

```bash
bun test ./packages/contracts/tests ./packages/lens-projectors/tests
```

Expected: pass.

- [ ] **Step 5: Commit contract migration**

Run:

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts packages/contracts/tests/fixtures.test.ts packages/lens-projectors/src/trust.ts tests/fixtures/contracts/valid-lens-runway-projection.json
git commit -m "feat: add Lens runway projection contract"
```

Expected: commit succeeds.

---

### Task 8: Preserve AgentLens Legacy Read Compatibility

**Files:**
- Modify: `components/agentlens/src/agentlens/evaluator/agentrunway_events.py`
- Modify: `components/agentlens/src/agentlens/evaluator/agentrunway_v2.py`
- Modify: `components/agentlens/src/agentlens/commands/agentrunway.py`
- Modify tests under `components/agentlens/tests/`

- [ ] **Step 1: Rename test descriptions to legacy compatibility**

Run:

```bash
rg -n "AgentRunway|agentrunway" components/agentlens/tests components/agentlens/src/agentlens --glob '!**/__pycache__/**'
```

Expected: matches show existing compatibility surface.

In test names and comments, use wording such as:

```python
def test_legacy_agentrunway_events_project_for_read_compatibility() -> None:
    ...
```

Do not rename the public `agentlens agentrunway` command in this task; it remains a compatibility command until a separate CLI deprecation plan exists.

- [ ] **Step 2: Add active Waygent projection tests in Python only when AgentLens consumes Waygent events**

Create or update the narrowest test file under `components/agentlens/tests/unit/` so it checks that active `runway.*` events can be read without being converted to `agentrunway.*`.

Use this event shape in the test:

```python
{
    "schema": "agentlens.event.v3",
    "event_id": "event_run_demo_1",
    "agentlens_run_id": "lens_run_demo",
    "orchestrator_run_id": "run_demo",
    "producer": {"name": "waygent", "kind": "orchestrator", "version": "0.1.0"},
    "event_type": "runway.verification_result",
    "occurred_at": "2026-05-21T00:00:00Z",
    "sequence": 1,
    "phase": "verify",
    "outcome": "success",
    "severity": "info",
    "trust_impact": "supports_success",
    "summary": "Verification passed.",
    "payload": {"task_id": "task_demo"},
}
```

- [ ] **Step 3: Verify AgentLens compatibility**

Run:

```bash
cd components/agentlens && python -m pytest -q
```

Expected: pass.

- [ ] **Step 4: Commit AgentLens compatibility**

Run:

```bash
git add components/agentlens/src/agentlens components/agentlens/tests
git commit -m "test: preserve AgentLens legacy runway compatibility"
```

Expected: commit succeeds.

---

### Task 9: Remove Active AgentRunway Skill Routing

**Files:**
- Delete: `skills/agent-runway/`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `skills/README.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`

- [ ] **Step 1: Prove Waygent parity before deletion**

Run:

```bash
bun run check
bun run platform:demo
cd native/kernel && cargo test --workspace
cd components/agentlens && python -m pytest -q
```

Expected: all commands pass.

- [ ] **Step 2: Remove old skill**

Run:

```bash
git rm -r skills/agent-runway
```

Expected: tracked AgentRunway skill files are deleted. Runtime cache files under ignored `__pycache__` paths are not staged unless they are tracked.

- [ ] **Step 3: Update active instructions**

In `AGENTS.md`, remove the active `### AgentRunway` section and replace it with:

```markdown
### Waygent Runtime

- Skill entry point: `skills/waygent/SKILL.md`
- CLI app: `apps/cli/`
- Runtime orchestration: `packages/orchestrator/`
- Scheduling and recovery: `packages/runway-control/`
- Provider adapters: `packages/provider-adapters/`
- Kernel boundary: `native/kernel/`
- Lens storage and projections: `packages/lens-store/`, `packages/lens-projectors/`

Waygent owns scheduling, state, worktrees, runtime adapters, verification,
recovery, apply, and Lens emission. Do not manually orchestrate workers from
chat context when a Waygent run is requested.
```

Replace AgentRunway verification commands with:

```bash
bun run check
bun run platform:demo
cd native/kernel && cargo test --workspace
```

In `CLAUDE.md`, replace AgentRunway runner routing with Waygent CLI routing:

```markdown
- If a task asks for execution through Waygent, invoke `waygent` through
  `apps/cli/src/index.ts` or the installed `waygent` command rather than
  coordinating worker prompts manually.
```

In `skills/README.md`, remove the `agent-runway` installation row and add a `waygent` row:

```markdown
| [`waygent`](./waygent/) | 자연어 Waygent 실행, 상태, 설명, 재개, 적용 요청을 안정적인 Waygent CLI 명령으로 변환. |
```

- [ ] **Step 4: Verify no active AgentRunway routing remains**

Run:

```bash
rg -n "skills/agent-runway|agentrunway.py|agent-runway last|agent-runway plan" AGENTS.md CLAUDE.md GEMINI.md skills docs apps packages tests components --glob '!**/node_modules/**' --glob '!**/dist/**'
```

Expected: no active routing references. Historical migration docs and legacy compatibility tests may still contain `agentrunway.*`.

- [ ] **Step 5: Run full checks**

Run:

```bash
bun run check
bun run platform:demo
cd native/kernel && cargo test --workspace
cd components/agentlens && python -m pytest -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 6: Commit removal**

Run:

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git commit -m "refactor: remove legacy AgentRunway skill routing"
```

Expected: commit succeeds and `git status --short` is clean.

---

### Task 10: Final Verification And Cleanup Report

**Files:**
- Modify docs only if command output reveals stale instructions.
- Do not delete generated files unless the user explicitly approves that deletion.

- [ ] **Step 1: Run final verification**

Run:

```bash
git status --short --branch --untracked-files=all
bun run check
bun run platform:demo
bun run check:legacy
cd native/kernel && cargo fmt --all -- --check
cd native/kernel && cargo clippy --workspace --all-targets -- -D warnings
cd native/kernel && cargo test --workspace
cd components/agentlens && python -m pytest -q
git diff --check
```

Expected: all verification commands pass. `git status` may show ignored generated files only when run without `--ignored`.

- [ ] **Step 2: Inspect remaining AgentRunway references**

Run:

```bash
rg -n "AgentRunway|agentrunway|skills/agent-runway|agentrunway.py" AGENTS.md CLAUDE.md GEMINI.md docs apps packages components skills tests --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/__pycache__/**'
```

Expected: remaining matches are migration docs, historical compatibility fixtures, or AgentLens read-compatibility code. No active execution instruction points at `skills/agent-runway`.

- [ ] **Step 3: Commit final doc fixes if any were required**

If Step 1 or Step 2 required doc-only fixes, run:

```bash
git add AGENTS.md CLAUDE.md GEMINI.md docs skills/README.md
git commit -m "docs: finalize Waygent migration guidance"
```

Expected: commit succeeds when files changed. If no files changed, skip this step.

- [ ] **Step 4: Report cleanup candidates without deleting them**

Run:

```bash
find . -maxdepth 3 \( -name node_modules -o -name dist -o -name build -o -name .pytest_cache -o -name __pycache__ -o -name target -o -name tmp \) -print | sort
```

Expected: output lists local generated directories that may be removed only after explicit user approval.

---

## Parallel Execution Map

Task 0 and Task 1 are sequential.

After Task 1, Tasks 2 and 3 are sequential because Task 3 depends on the parser from Task 2.

After Task 3, Tasks 4, 6, and 7 can be implemented by separate workers because their write sets are mostly disjoint. Task 5 depends on Task 4 and should integrate Task 2, Task 3, and Task 4.

Task 8 depends on Task 1 and Task 7.

Task 9 depends on Tasks 5, 6, 7, and 8.

Task 10 is always last.

## Final Acceptance

The implementation is accepted when:

- `AgentLens/` no longer exists at the repository root.
- `components/agentlens/` contains the Python AgentLens component.
- `apps/console/` contains the Waygent console.
- `skills/agent-runway/` is deleted after parity checks pass.
- `waygent run/status/explain/resume/apply` routes through Waygent code, not through AgentRunway Python.
- New active events use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.
- `agentrunway.*` remains only for historical read compatibility.
- Bun, Rust, and AgentLens verification commands pass.
