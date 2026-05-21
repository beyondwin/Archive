# Waygent Bun Control Plane Rust Kernel Phase 1 Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first executable spine of Waygent: a Python-free, Graphify-free agent platform with a Bun workspace, shared contracts, minimal durable projection, append-only Lens store, Rust kernel protocol/process execution, fake provider adapter, and one deterministic end-to-end run.

**Architecture:** This plan creates a new clean Waygent platform tree beside the existing Python references. Bun/TypeScript owns contracts, scheduler policy, store projection, fake adapter, and CLI orchestration. Rust owns the first native kernel boundary: typed protocol plus bounded process execution evidence.

**Tech Stack:** Bun 1.3+, TypeScript 5.9+, `bun:test`, JSON Schema, Ajv, Rust stable, Cargo resolver v2, `serde`, `serde_json`, `thiserror`, `wait-timeout`, filesystem JSONL artifacts.

---

## Source Spec

- Design spec: `AgentLens/docs/spec/2026-05-21-bun-control-plane-rust-kernel-agent-platform-design.md`
- Full implementation program: `AgentLens/docs/plan/2026-05-21-waygent-full-platform-implementation-program.md`
- Do not edit as part of this plan:
  - `AgentLens/docs/spec/2026-05-21-full-rust-agent-platform-rewrite-design.md`
  - `AgentLens/docs/plan/2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md`

## Scope Boundary

This plan is Phase 1 of the full Waygent implementation program. It creates the
first working platform spine only. It does not delete the
existing Python `AgentLens/` package or `skills/agent-runway/` runner. It does
not migrate the React dashboard. It does not add live Codex or Claude adapters.
It does not introduce Graphify.

The output of this plan is a deterministic command:

```bash
bun run platform:demo
```

Expected behavior: it runs a fake provider task, writes canonical AgentLens
events/artifacts under a temporary run directory, computes a durable projection,
executes one bounded kernel process command, and emits a trust projection.

## Target File Structure

Create:

```text
package.json
bunfig.toml
tsconfig.base.json
apps/
  cli/
    package.json
    tsconfig.json
    src/
      demo.ts
      index.ts
packages/
  contracts/
    package.json
    tsconfig.json
    src/
      index.ts
      ids.ts
      schemas.ts
      types.ts
      validate.ts
    tests/
      contracts.test.ts
  runway-control/
    package.json
    tsconfig.json
    src/
      index.ts
      projection.ts
      scheduler.ts
      types.ts
    tests/
      scheduler.test.ts
  lens-store/
    package.json
    tsconfig.json
    src/
      eventJournal.ts
      index.ts
      paths.ts
      projection.ts
    tests/
      eventJournal.test.ts
  lens-projectors/
    package.json
    tsconfig.json
    src/
      index.ts
      trust.ts
    tests/
      trust.test.ts
  provider-adapters/
    package.json
    tsconfig.json
    src/
      fakeProvider.ts
      index.ts
      types.ts
    tests/
      fakeProvider.test.ts
  kernel-client/
    package.json
    tsconfig.json
    src/
      index.ts
      kernelClient.ts
    tests/
      kernelClient.test.ts
tests/
  integration/
    platform-demo.test.ts
native/
  kernel/
    Cargo.toml
    crates/
      kernel-protocol/
        Cargo.toml
        src/
          lib.rs
      process-supervisor/
        Cargo.toml
        src/
          lib.rs
      kernel-cli/
        Cargo.toml
        src/
          main.rs
```

Modify:

```text
.gitignore
```

Do not modify:

```text
AgentLens/docs/spec/2026-05-21-full-rust-agent-platform-rewrite-design.md
AgentLens/docs/plan/2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md
AgentLens/src/
AgentLens/tests/
AgentLens/web/src/
skills/agent-runway/scripts/
skills/agent-runway/evals/
graphify-out/
```

## Task 1: Create The Bun Workspace Shell

```yaml agentrunway-task
task_id: task_001
title: Create The Bun Workspace Shell
risk: medium
phase: implementation
dependencies: []
file_claims:
  - {path: package.json, mode: owned}
  - {path: bunfig.toml, mode: owned}
  - {path: tsconfig.base.json, mode: owned}
  - {path: .gitignore, mode: shared_append}
acceptance_commands:
  - bun --version
  - bun install
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `package.json`
- Create: `bunfig.toml`
- Create: `tsconfig.base.json`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm Bun is available**

Run:

```bash
bun --version
```

Expected: prints `1.3.10` or newer.

- [ ] **Step 2: Create root package manifest**

Create `package.json`:

```json
{
  "name": "waygent",
  "private": true,
  "type": "module",
  "workspaces": [
    "apps/*",
    "packages/*"
  ],
  "scripts": {
    "typecheck": "tsc -b apps/* packages/*",
    "test": "bun test",
    "check": "bun run typecheck && bun test",
    "platform:demo": "bun run apps/cli/src/demo.ts"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.9.3"
  },
  "dependencies": {
    "ajv": "^8.17.1"
  }
}
```

- [ ] **Step 3: Create Bun config**

Create `bunfig.toml`:

```toml
[install]
exact = true
```

- [ ] **Step 4: Create root TypeScript build config**

Create `tsconfig.base.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "skipLibCheck": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "resolveJsonModule": true,
    "allowSyntheticDefaultImports": true,
    "types": ["bun-types"]
  }
}
```

- [ ] **Step 5: Add Rust build outputs to `.gitignore`**

Append this block to `.gitignore` only if it is not present:

```gitignore

# Rust tooling
/target/
native/kernel/target/
```

- [ ] **Step 6: Install dependencies and verify the empty workspace**

Run:

```bash
bun install
bun run typecheck
```

Expected: `bun install` creates `bun.lock`; `bun run typecheck` fails because
`apps/*` and `packages/*` do not exist yet. This confirms the root scripts are
being read.

- [ ] **Step 7: Commit**

```bash
git add package.json bun.lock bunfig.toml tsconfig.base.json .gitignore
git commit -m "chore: add Bun platform workspace"
```

## Task 2: Add Shared Platform Contracts

```yaml agentrunway-task
task_id: task_002
title: Add Shared Platform Contracts
risk: high
phase: implementation
dependencies: [task_001]
file_claims:
  - {path: packages/contracts, mode: owned}
  - {path: package.json, mode: shared_append}
acceptance_commands:
  - bun test packages/contracts/tests/contracts.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `packages/contracts/package.json`
- Create: `packages/contracts/tsconfig.json`
- Create: `packages/contracts/src/ids.ts`
- Create: `packages/contracts/src/types.ts`
- Create: `packages/contracts/src/schemas.ts`
- Create: `packages/contracts/src/validate.ts`
- Create: `packages/contracts/src/index.ts`
- Create: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Create contracts package manifest**

Create `packages/contracts/package.json`:

```json
{
  "name": "@waygent/contracts",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/contracts.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "ajv": "^8.17.1"
  }
}
```

Create `packages/contracts/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 2: Define id helpers**

Create `packages/contracts/src/ids.ts`:

```ts
export type IdPrefix =
  | "run"
  | "task"
  | "candidate"
  | "checkpoint"
  | "event"
  | "exec";

export type PlatformId = `${IdPrefix}_${string}`;

export function makeId(prefix: IdPrefix, seed: string): PlatformId {
  const normalized = seed
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${prefix}_${normalized || "unknown"}`;
}
```

- [ ] **Step 3: Define shared TypeScript types**

Create `packages/contracts/src/types.ts`:

```ts
import type { PlatformId } from "./ids";

export type Outcome = "pending" | "success" | "failed" | "blocked";
export type Severity = "debug" | "info" | "warning" | "error";
export type TrustImpact =
  | "neutral"
  | "supports_success"
  | "supports_failure"
  | "weakens_claim";

export interface Producer {
  name: "agentrunway" | "agentlens" | "kernel" | "fake-provider";
  kind: "orchestrator" | "kernel" | "provider" | "projector";
  version: string;
}

export interface PlatformEvent {
  schema: "agentlens.event.v3";
  event_id: PlatformId;
  agentlens_run_id: PlatformId;
  orchestrator_run_id: PlatformId;
  producer: Producer;
  event_type: string;
  occurred_at: string;
  sequence: number;
  phase: string;
  outcome: Outcome;
  severity: Severity;
  trust_impact: TrustImpact;
  summary: string;
  payload: Record<string, unknown>;
}

export interface KernelExecutionRequest {
  schema: "kernel.execution_request.v1";
  request_id: PlatformId;
  run_id: PlatformId;
  task_id: PlatformId;
  cwd: string;
  argv: string[];
  env: Record<string, string>;
  timeout_ms: number;
  stdin: "closed";
  tty: false;
  capture: {
    stdout_limit_bytes: number;
    stderr_limit_bytes: number;
  };
}

export interface KernelExecutionResult {
  schema: "kernel.execution_result.v1";
  request_id: PlatformId;
  exit_code: number | null;
  signal: string | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  duration_ms: number;
}

export interface WorkerResult {
  schema: "runway.worker_result.v1";
  task_id: PlatformId;
  candidate_id: PlatformId;
  status: "completed" | "failed";
  changed_files: string[];
  summary: string;
  evidence: Record<string, unknown>;
}
```

- [ ] **Step 4: Define JSON schemas**

Create `packages/contracts/src/schemas.ts`:

```ts
export const platformEventSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "agentlens.event.v3",
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "event_id",
    "agentlens_run_id",
    "orchestrator_run_id",
    "producer",
    "event_type",
    "occurred_at",
    "sequence",
    "phase",
    "outcome",
    "severity",
    "trust_impact",
    "summary",
    "payload"
  ],
  properties: {
    schema: { const: "agentlens.event.v3" },
    event_id: { type: "string", pattern: "^event_[a-z0-9-]+$" },
    agentlens_run_id: { type: "string", pattern: "^run_[a-z0-9-]+$" },
    orchestrator_run_id: { type: "string", pattern: "^run_[a-z0-9-]+$" },
    producer: {
      type: "object",
      additionalProperties: false,
      required: ["name", "kind", "version"],
      properties: {
        name: { enum: ["agentrunway", "agentlens", "kernel", "fake-provider"] },
        kind: { enum: ["orchestrator", "kernel", "provider", "projector"] },
        version: { type: "string", minLength: 1 }
      }
    },
    event_type: {
      type: "string",
      pattern: "^(platform|runway|kernel|lens)\\.[a-z0-9_.-]+$"
    },
    occurred_at: { type: "string", format: "date-time" },
    sequence: { type: "integer", minimum: 1 },
    phase: { type: "string", minLength: 1 },
    outcome: { enum: ["pending", "success", "failed", "blocked"] },
    severity: { enum: ["debug", "info", "warning", "error"] },
    trust_impact: {
      enum: ["neutral", "supports_success", "supports_failure", "weakens_claim"]
    },
    summary: { type: "string", minLength: 1, maxLength: 500 },
    payload: { type: "object" }
  }
} as const;

export const kernelExecutionRequestSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "kernel.execution_request.v1",
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "request_id",
    "run_id",
    "task_id",
    "cwd",
    "argv",
    "env",
    "timeout_ms",
    "stdin",
    "tty",
    "capture"
  ],
  properties: {
    schema: { const: "kernel.execution_request.v1" },
    request_id: { type: "string", pattern: "^exec_[a-z0-9-]+$" },
    run_id: { type: "string", pattern: "^run_[a-z0-9-]+$" },
    task_id: { type: "string", pattern: "^task_[a-z0-9-]+$" },
    cwd: { type: "string", minLength: 1 },
    argv: {
      type: "array",
      minItems: 1,
      items: { type: "string" }
    },
    env: {
      type: "object",
      additionalProperties: { type: "string" }
    },
    timeout_ms: { type: "integer", minimum: 1, maximum: 600000 },
    stdin: { const: "closed" },
    tty: { const: false },
    capture: {
      type: "object",
      additionalProperties: false,
      required: ["stdout_limit_bytes", "stderr_limit_bytes"],
      properties: {
        stdout_limit_bytes: { type: "integer", minimum: 0, maximum: 1000000 },
        stderr_limit_bytes: { type: "integer", minimum: 0, maximum: 1000000 }
      }
    }
  }
} as const;

export const workerResultSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "runway.worker_result.v1",
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "task_id",
    "candidate_id",
    "status",
    "changed_files",
    "summary",
    "evidence"
  ],
  properties: {
    schema: { const: "runway.worker_result.v1" },
    task_id: { type: "string", pattern: "^task_[a-z0-9-]+$" },
    candidate_id: { type: "string", pattern: "^candidate_[a-z0-9-]+$" },
    status: { enum: ["completed", "failed"] },
    changed_files: {
      type: "array",
      items: { type: "string", minLength: 1 }
    },
    summary: { type: "string", minLength: 1, maxLength: 500 },
    evidence: { type: "object" }
  }
} as const;

export const schemas = {
  "agentlens.event.v3": platformEventSchema,
  "kernel.execution_request.v1": kernelExecutionRequestSchema,
  "runway.worker_result.v1": workerResultSchema
} as const;
```

- [ ] **Step 5: Add validation helpers**

Create `packages/contracts/src/validate.ts`:

```ts
import Ajv from "ajv";
import addFormats from "ajv-formats";
import { schemas } from "./schemas";

export type SchemaName = keyof typeof schemas;

const ajv = new Ajv({ allErrors: true, strict: true });
addFormats(ajv);

const validators = new Map(
  Object.entries(schemas).map(([name, schema]) => [name, ajv.compile(schema)])
);

export class ContractValidationError extends Error {
  constructor(
    public readonly schemaName: SchemaName,
    public readonly issues: string[]
  ) {
    super(`${schemaName} validation failed: ${issues.join("; ")}`);
  }
}

export function validateContract<T>(schemaName: SchemaName, value: unknown): T {
  const validator = validators.get(schemaName);
  if (!validator) {
    throw new Error(`Unknown schema: ${schemaName}`);
  }
  if (!validator(value)) {
    const issues = (validator.errors ?? []).map((error) => {
      const path = error.instancePath || "/";
      return `${path} ${error.message ?? "is invalid"}`;
    });
    throw new ContractValidationError(schemaName, issues);
  }
  return value as T;
}
```

Create `packages/contracts/src/index.ts`:

```ts
export * from "./ids";
export * from "./schemas";
export * from "./types";
export * from "./validate";
```

- [ ] **Step 6: Install `ajv-formats`**

Run:

```bash
bun add ajv-formats
```

Expected: `package.json` and `bun.lock` include `ajv-formats`.

- [ ] **Step 7: Add contract tests**

Create `packages/contracts/tests/contracts.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  ContractValidationError,
  makeId,
  type PlatformEvent,
  validateContract
} from "../src";

describe("contracts", () => {
  test("makeId normalizes stable ids", () => {
    expect(makeId("run", "Demo Run 01")).toBe("run_demo-run-01");
  });

  test("validates platform events", () => {
    const event: PlatformEvent = {
      schema: "agentlens.event.v3",
      event_id: "event_demo",
      agentlens_run_id: "run_lens",
      orchestrator_run_id: "run_orchestrator",
      producer: {
        name: "agentrunway",
        kind: "orchestrator",
        version: "0.1.0"
      },
      event_type: "runway.worker_result",
      occurred_at: "2026-05-21T00:00:00Z",
      sequence: 1,
      phase: "worker",
      outcome: "success",
      severity: "info",
      trust_impact: "supports_success",
      summary: "Worker produced bounded evidence.",
      payload: { task_id: "task_demo" }
    };

    expect(validateContract<PlatformEvent>("agentlens.event.v3", event)).toBe(event);
  });

  test("rejects legacy KWS event namespaces", () => {
    const event = {
      schema: "agentlens.event.v3",
      event_id: "event_demo",
      agentlens_run_id: "run_lens",
      orchestrator_run_id: "run_orchestrator",
      producer: {
        name: "agentrunway",
        kind: "orchestrator",
        version: "0.1.0"
      },
      event_type: "kws-cpe.worker_result",
      occurred_at: "2026-05-21T00:00:00Z",
      sequence: 1,
      phase: "worker",
      outcome: "success",
      severity: "info",
      trust_impact: "supports_success",
      summary: "Legacy namespace should fail.",
      payload: {}
    };

    expect(() => validateContract("agentlens.event.v3", event)).toThrow(
      ContractValidationError
    );
  });
});
```

- [ ] **Step 8: Verify and commit**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
bun run typecheck
```

Expected: both commands pass after the workspace packages exist.

Commit:

```bash
git add package.json bun.lock packages/contracts
git commit -m "feat: add platform contracts package"
```

## Task 3: Add Minimal Durable Projection And Safe-Wave Scheduler

```yaml agentrunway-task
task_id: task_003
title: Add Minimal Durable Projection And Safe-Wave Scheduler
risk: high
phase: implementation
dependencies: [task_002]
file_claims:
  - {path: packages/runway-control, mode: owned}
acceptance_commands:
  - bun test packages/runway-control/tests/scheduler.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `packages/runway-control/package.json`
- Create: `packages/runway-control/tsconfig.json`
- Create: `packages/runway-control/src/types.ts`
- Create: `packages/runway-control/src/scheduler.ts`
- Create: `packages/runway-control/src/projection.ts`
- Create: `packages/runway-control/src/index.ts`
- Create: `packages/runway-control/tests/scheduler.test.ts`

- [ ] **Step 1: Create package files**

Create `packages/runway-control/package.json`:

```json
{
  "name": "@waygent/runway-control",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/scheduler.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*"
  }
}
```

Create `packages/runway-control/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [{ "path": "../contracts" }],
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 2: Define scheduler types**

Create `packages/runway-control/src/types.ts`:

```ts
import type { PlatformId } from "@waygent/contracts";

export type Risk = "low" | "medium" | "high";
export type FileClaimMode = "owned" | "shared_append" | "read_only";
export type TaskStatus =
  | "PENDING"
  | "READY"
  | "WITHHELD_DEPENDENCY"
  | "WITHHELD_FILE_CLAIM"
  | "WITHHELD_RISK"
  | "RUNNING"
  | "MERGED"
  | "FAILED_TERMINAL";

export interface FileClaim {
  path: string;
  mode: FileClaimMode;
}

export interface TaskSpec {
  task_id: PlatformId;
  title: string;
  risk: Risk;
  dependencies: PlatformId[];
  file_claims: FileClaim[];
  acceptance_commands: string[];
  serial: boolean;
}

export interface ProjectionInput {
  tasks: TaskSpec[];
  completed_tasks: PlatformId[];
  running_tasks: PlatformId[];
  failed_tasks: PlatformId[];
}

export interface WithheldTask {
  task_id: PlatformId;
  reason: "blocked_dependency" | "file_claim_conflict" | "high_risk_or_serial";
  details: Record<string, unknown>;
}

export interface DurableProjection {
  ready_tasks: TaskSpec[];
  safe_wave: TaskSpec[];
  withheld_tasks: WithheldTask[];
  projection_status: "running" | "blocked" | "finished";
}
```

- [ ] **Step 3: Implement safe-wave scheduling**

Create `packages/runway-control/src/scheduler.ts`:

```ts
import type { TaskSpec, WithheldTask } from "./types";

function writeClaims(task: TaskSpec): string[] {
  return task.file_claims
    .filter((claim) => claim.mode === "owned" || claim.mode === "shared_append")
    .map((claim) => claim.path);
}

function conflictsWithSelected(task: TaskSpec, selected: TaskSpec[]): string[] {
  const taskWrites = new Set(writeClaims(task));
  const conflicts: string[] = [];
  for (const selectedTask of selected) {
    for (const path of writeClaims(selectedTask)) {
      if (taskWrites.has(path)) {
        conflicts.push(path);
      }
    }
  }
  return conflicts;
}

export function scheduleSafeWave(readyTasks: TaskSpec[]): {
  safe_wave: TaskSpec[];
  withheld_tasks: WithheldTask[];
} {
  const safe_wave: TaskSpec[] = [];
  const withheld_tasks: WithheldTask[] = [];

  for (const task of readyTasks) {
    if (task.serial || task.risk === "high") {
      withheld_tasks.push({
        task_id: task.task_id,
        reason: "high_risk_or_serial",
        details: { risk: task.risk, serial: task.serial }
      });
      continue;
    }

    const conflicts = conflictsWithSelected(task, safe_wave);
    if (conflicts.length > 0) {
      withheld_tasks.push({
        task_id: task.task_id,
        reason: "file_claim_conflict",
        details: { conflicts }
      });
      continue;
    }

    safe_wave.push(task);
  }

  return { safe_wave, withheld_tasks };
}
```

- [ ] **Step 4: Implement durable projection**

Create `packages/runway-control/src/projection.ts`:

```ts
import { scheduleSafeWave } from "./scheduler";
import type { DurableProjection, ProjectionInput, TaskSpec, WithheldTask } from "./types";

function dependencyBlocked(task: TaskSpec, completed: Set<string>, failed: Set<string>): string[] {
  return task.dependencies.filter((dependency) => !completed.has(dependency) || failed.has(dependency));
}

export function computeDurableProjection(input: ProjectionInput): DurableProjection {
  const completed = new Set(input.completed_tasks);
  const failed = new Set(input.failed_tasks);
  const running = new Set(input.running_tasks);
  const ready_tasks: TaskSpec[] = [];
  const withheld_tasks: WithheldTask[] = [];

  for (const task of input.tasks) {
    if (completed.has(task.task_id) || running.has(task.task_id)) {
      continue;
    }
    const blocked = dependencyBlocked(task, completed, failed);
    if (blocked.length > 0) {
      withheld_tasks.push({
        task_id: task.task_id,
        reason: "blocked_dependency",
        details: { blocked_dependencies: blocked }
      });
      continue;
    }
    ready_tasks.push(task);
  }

  const scheduled = scheduleSafeWave(ready_tasks);
  const safe_wave = scheduled.safe_wave;
  const allWithheld = [...withheld_tasks, ...scheduled.withheld_tasks];

  const projection_status =
    completed.size === input.tasks.length
      ? "finished"
      : safe_wave.length > 0 || running.size > 0
        ? "running"
        : "blocked";

  return {
    ready_tasks,
    safe_wave,
    withheld_tasks: allWithheld,
    projection_status
  };
}
```

Create `packages/runway-control/src/index.ts`:

```ts
export * from "./projection";
export * from "./scheduler";
export * from "./types";
```

- [ ] **Step 5: Add scheduler tests**

Create `packages/runway-control/tests/scheduler.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { computeDurableProjection, type TaskSpec } from "../src";

const task = (id: string, paths: string[], dependencies: string[] = []): TaskSpec => ({
  task_id: `task_${id}`,
  title: id,
  risk: "medium",
  dependencies: dependencies.map((dependency) => `task_${dependency}`),
  file_claims: paths.map((path) => ({ path, mode: "owned" })),
  acceptance_commands: ["bun test"],
  serial: false
});

describe("computeDurableProjection", () => {
  test("selects independent ready tasks into safe wave", () => {
    const projection = computeDurableProjection({
      tasks: [task("a", ["packages/a.ts"]), task("b", ["packages/b.ts"])],
      completed_tasks: [],
      running_tasks: [],
      failed_tasks: []
    });

    expect(projection.safe_wave.map((item) => item.task_id)).toEqual(["task_a", "task_b"]);
    expect(projection.withheld_tasks).toEqual([]);
  });

  test("withholds tasks with blocked dependencies", () => {
    const projection = computeDurableProjection({
      tasks: [task("a", ["packages/a.ts"], ["b"])],
      completed_tasks: [],
      running_tasks: [],
      failed_tasks: []
    });

    expect(projection.safe_wave).toEqual([]);
    expect(projection.withheld_tasks[0]?.reason).toBe("blocked_dependency");
  });

  test("withholds overlapping file claims from the same wave", () => {
    const projection = computeDurableProjection({
      tasks: [task("a", ["packages/shared.ts"]), task("b", ["packages/shared.ts"])],
      completed_tasks: [],
      running_tasks: [],
      failed_tasks: []
    });

    expect(projection.safe_wave.map((item) => item.task_id)).toEqual(["task_a"]);
    expect(projection.withheld_tasks[0]?.reason).toBe("file_claim_conflict");
  });
});
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test packages/runway-control/tests/scheduler.test.ts
bun run typecheck
```

Expected: both commands pass.

Commit:

```bash
git add packages/runway-control package.json bun.lock
git commit -m "feat: add runway durable projection"
```

## Task 4: Add Append-Only AgentLens Event Store

```yaml agentrunway-task
task_id: task_004
title: Add Append-Only AgentLens Event Store
risk: high
phase: implementation
dependencies: [task_002]
file_claims:
  - {path: packages/lens-store, mode: owned}
acceptance_commands:
  - bun test packages/lens-store/tests/eventJournal.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `packages/lens-store/package.json`
- Create: `packages/lens-store/tsconfig.json`
- Create: `packages/lens-store/src/paths.ts`
- Create: `packages/lens-store/src/eventJournal.ts`
- Create: `packages/lens-store/src/projection.ts`
- Create: `packages/lens-store/src/index.ts`
- Create: `packages/lens-store/tests/eventJournal.test.ts`

- [ ] **Step 1: Create package files**

Create `packages/lens-store/package.json`:

```json
{
  "name": "@waygent/lens-store",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/eventJournal.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*"
  }
}
```

Create `packages/lens-store/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [{ "path": "../contracts" }],
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 2: Add store path helpers**

Create `packages/lens-store/src/paths.ts`:

```ts
import { join } from "node:path";

export interface RunPaths {
  runDir: string;
  eventsPath: string;
  artifactsDir: string;
}

export function runPaths(root: string, workspaceId: string, runId: string): RunPaths {
  const runDir = join(root, "runs", workspaceId, runId);
  return {
    runDir,
    eventsPath: join(runDir, "events.jsonl"),
    artifactsDir: join(runDir, "artifacts")
  };
}
```

- [ ] **Step 3: Add append/read journal**

Create `packages/lens-store/src/eventJournal.ts`:

```ts
import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { PlatformEvent } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";

export async function appendEvent(eventsPath: string, event: PlatformEvent): Promise<void> {
  validateContract<PlatformEvent>("agentlens.event.v3", event);
  await mkdir(dirname(eventsPath), { recursive: true });
  await appendFile(eventsPath, `${JSON.stringify(event)}\n`, "utf8");
}

export async function readEvents(eventsPath: string): Promise<PlatformEvent[]> {
  try {
    const text = await readFile(eventsPath, "utf8");
    return text
      .split("\n")
      .filter(Boolean)
      .map((line) => validateContract<PlatformEvent>("agentlens.event.v3", JSON.parse(line)));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw error;
  }
}
```

Create `packages/lens-store/src/projection.ts`:

```ts
import type { PlatformEvent } from "@waygent/contracts";

export interface RunEventSummary {
  total_events: number;
  failed_events: number;
  success_events: number;
  last_sequence: number;
}

export function summarizeEvents(events: PlatformEvent[]): RunEventSummary {
  return {
    total_events: events.length,
    failed_events: events.filter((event) => event.outcome === "failed").length,
    success_events: events.filter((event) => event.outcome === "success").length,
    last_sequence: Math.max(0, ...events.map((event) => event.sequence))
  };
}
```

Create `packages/lens-store/src/index.ts`:

```ts
export * from "./eventJournal";
export * from "./paths";
export * from "./projection";
```

- [ ] **Step 4: Add journal tests**

Create `packages/lens-store/tests/eventJournal.test.ts`:

```ts
import { mkdtemp } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import type { PlatformEvent } from "@waygent/contracts";
import { appendEvent, readEvents, summarizeEvents } from "../src";

function event(sequence: number, outcome: PlatformEvent["outcome"]): PlatformEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_${sequence}`,
    agentlens_run_id: "run_lens",
    orchestrator_run_id: "run_orchestrator",
    producer: { name: "agentrunway", kind: "orchestrator", version: "0.1.0" },
    event_type: "runway.worker_result",
    occurred_at: "2026-05-21T00:00:00Z",
    sequence,
    phase: "worker",
    outcome,
    severity: outcome === "failed" ? "error" : "info",
    trust_impact: outcome === "failed" ? "supports_failure" : "supports_success",
    summary: `Event ${sequence}`,
    payload: {}
  };
}

describe("event journal", () => {
  test("appends valid events and rebuilds summary", async () => {
    const dir = await mkdtemp(join(tmpdir(), "lens-store-"));
    const eventsPath = join(dir, "events.jsonl");

    await appendEvent(eventsPath, event(1, "success"));
    await appendEvent(eventsPath, event(2, "failed"));

    const events = await readEvents(eventsPath);
    expect(events.map((item) => item.sequence)).toEqual([1, 2]);
    expect(summarizeEvents(events)).toEqual({
      total_events: 2,
      failed_events: 1,
      success_events: 1,
      last_sequence: 2
    });
  });
});
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/lens-store/tests/eventJournal.test.ts
bun run typecheck
```

Expected: both commands pass.

Commit:

```bash
git add packages/lens-store package.json bun.lock
git commit -m "feat: add append-only lens event store"
```

## Task 5: Add Rust Kernel Protocol And Process Execution

```yaml agentrunway-task
task_id: task_005
title: Add Rust Kernel Protocol And Process Execution
risk: high
phase: implementation
dependencies: [task_002]
file_claims:
  - {path: native/kernel, mode: owned}
  - {path: .gitignore, mode: shared_append}
acceptance_commands:
  - cd native/kernel && cargo test
  - cd native/kernel && cargo run -p kernel-cli -- exec-json ../../tests/fixtures/kernel/echo-request.json
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `native/kernel/Cargo.toml`
- Create: `native/kernel/crates/kernel-protocol/Cargo.toml`
- Create: `native/kernel/crates/kernel-protocol/src/lib.rs`
- Create: `native/kernel/crates/process-supervisor/Cargo.toml`
- Create: `native/kernel/crates/process-supervisor/src/lib.rs`
- Create: `native/kernel/crates/kernel-cli/Cargo.toml`
- Create: `native/kernel/crates/kernel-cli/src/main.rs`
- Create: `tests/fixtures/kernel/echo-request.json`

- [ ] **Step 1: Confirm Rust toolchain availability**

Run:

```bash
cargo --version
rustc --version
```

Expected: both commands print versions. If unavailable, install Rust stable
with `rustup` before starting this task, then rerun the commands.

- [ ] **Step 2: Create Rust workspace**

Create `native/kernel/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
  "crates/kernel-protocol",
  "crates/process-supervisor",
  "crates/kernel-cli",
]

[workspace.package]
edition = "2024"
version = "0.1.0"
license = "Proprietary"

[workspace.dependencies]
kernel-protocol = { path = "crates/kernel-protocol" }
process-supervisor = { path = "crates/process-supervisor" }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
thiserror = "2"
wait-timeout = "0.2"
```

- [ ] **Step 3: Add protocol crate**

Create `native/kernel/crates/kernel-protocol/Cargo.toml`:

```toml
[package]
name = "kernel-protocol"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
serde.workspace = true
```

Create `native/kernel/crates/kernel-protocol/src/lib.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CaptureLimits {
    pub stdout_limit_bytes: usize,
    pub stderr_limit_bytes: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionRequest {
    pub schema: String,
    pub request_id: String,
    pub run_id: String,
    pub task_id: String,
    pub cwd: String,
    pub argv: Vec<String>,
    pub env: BTreeMap<String, String>,
    pub timeout_ms: u64,
    pub stdin: String,
    pub tty: bool,
    pub capture: CaptureLimits,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionResult {
    pub schema: String,
    pub request_id: String,
    pub exit_code: Option<i32>,
    pub signal: Option<String>,
    pub timed_out: bool,
    pub stdout: String,
    pub stderr: String,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub duration_ms: u128,
}

impl ExecutionResult {
    pub fn completed(request_id: String, exit_code: Option<i32>, stdout: String, stderr: String, duration_ms: u128) -> Self {
        Self {
            schema: "kernel.execution_result.v1".to_string(),
            request_id,
            exit_code,
            signal: None,
            timed_out: false,
            stdout,
            stderr,
            stdout_truncated: false,
            stderr_truncated: false,
            duration_ms,
        }
    }
}
```

- [ ] **Step 4: Add process supervisor crate**

Create `native/kernel/crates/process-supervisor/Cargo.toml`:

```toml
[package]
name = "process-supervisor"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
kernel-protocol.workspace = true
thiserror.workspace = true
wait-timeout.workspace = true
```

Create `native/kernel/crates/process-supervisor/src/lib.rs`:

```rust
use kernel_protocol::{ExecutionRequest, ExecutionResult};
use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use thiserror::Error;
use wait_timeout::ChildExt;

#[derive(Debug, Error)]
pub enum SupervisorError {
    #[error("argv must contain at least one item")]
    EmptyArgv,
    #[error("failed to spawn process: {0}")]
    Spawn(std::io::Error),
    #[error("failed to wait for process: {0}")]
    Wait(std::io::Error),
    #[error("failed to collect process output: {0}")]
    Output(std::io::Error),
}

fn truncate_utf8(bytes: &[u8], limit: usize) -> (String, bool) {
    if bytes.len() <= limit {
        return (String::from_utf8_lossy(bytes).to_string(), false);
    }
    let truncated = &bytes[..limit];
    (String::from_utf8_lossy(truncated).to_string(), true)
}

pub fn execute(request: &ExecutionRequest) -> Result<ExecutionResult, SupervisorError> {
    let (program, args) = request.argv.split_first().ok_or(SupervisorError::EmptyArgv)?;
    let started = Instant::now();
    let mut command = Command::new(program);
    command.args(args);
    command.current_dir(&request.cwd);
    command.envs(&request.env);
    command.stdin(Stdio::null());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    let mut child = command.spawn().map_err(SupervisorError::Spawn)?;
    let timeout = Duration::from_millis(request.timeout_ms);

    match child.wait_timeout(timeout).map_err(SupervisorError::Wait)? {
        Some(status) => {
            let mut stdout_bytes = Vec::new();
            let mut stderr_bytes = Vec::new();
            if let Some(mut stdout) = child.stdout.take() {
                stdout.read_to_end(&mut stdout_bytes).map_err(SupervisorError::Output)?;
            }
            if let Some(mut stderr) = child.stderr.take() {
                stderr.read_to_end(&mut stderr_bytes).map_err(SupervisorError::Output)?;
            }
            let (stdout, stdout_truncated) =
                truncate_utf8(&stdout_bytes, request.capture.stdout_limit_bytes);
            let (stderr, stderr_truncated) =
                truncate_utf8(&stderr_bytes, request.capture.stderr_limit_bytes);
            Ok(ExecutionResult {
                schema: "kernel.execution_result.v1".to_string(),
                request_id: request.request_id.clone(),
                exit_code: status.code(),
                signal: None,
                timed_out: false,
                stdout,
                stderr,
                stdout_truncated,
                stderr_truncated,
                duration_ms: started.elapsed().as_millis(),
            })
        }
        None => {
            let _ = child.kill();
            let _ = child.wait();
            Ok(ExecutionResult {
                schema: "kernel.execution_result.v1".to_string(),
                request_id: request.request_id.clone(),
                exit_code: None,
                signal: None,
                timed_out: true,
                stdout: String::new(),
                stderr: "process timed out".to_string(),
                stdout_truncated: false,
                stderr_truncated: false,
                duration_ms: started.elapsed().as_millis(),
            })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use kernel_protocol::CaptureLimits;
    use std::collections::BTreeMap;

    #[test]
    fn executes_simple_command() {
        let request = ExecutionRequest {
            schema: "kernel.execution_request.v1".to_string(),
            request_id: "exec_echo".to_string(),
            run_id: "run_demo".to_string(),
            task_id: "task_demo".to_string(),
            cwd: ".".to_string(),
            argv: vec!["printf".to_string(), "hello".to_string()],
            env: BTreeMap::new(),
            timeout_ms: 1000,
            stdin: "closed".to_string(),
            tty: false,
            capture: CaptureLimits {
                stdout_limit_bytes: 100,
                stderr_limit_bytes: 100,
            },
        };

        let result = execute(&request).expect("process should run");
        assert_eq!(result.exit_code, Some(0));
        assert_eq!(result.stdout, "hello");
        assert!(!result.timed_out);
    }
}
```

- [ ] **Step 5: Add CLI crate**

Create `native/kernel/crates/kernel-cli/Cargo.toml`:

```toml
[package]
name = "kernel-cli"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
kernel-protocol.workspace = true
process-supervisor.workspace = true
serde_json.workspace = true
```

Create `native/kernel/crates/kernel-cli/src/main.rs`:

```rust
use kernel_protocol::ExecutionRequest;
use process_supervisor::execute;
use std::env;
use std::fs;
use std::process;

fn main() {
    let mut args = env::args().skip(1);
    let command = args.next().unwrap_or_default();
    let path = args.next().unwrap_or_default();

    if command != "exec-json" || path.is_empty() {
        eprintln!("usage: kernel-cli exec-json <request.json>");
        process::exit(2);
    }

    let text = fs::read_to_string(&path).unwrap_or_else(|error| {
        eprintln!("failed to read {path}: {error}");
        process::exit(2);
    });
    let request: ExecutionRequest = serde_json::from_str(&text).unwrap_or_else(|error| {
        eprintln!("failed to parse request json: {error}");
        process::exit(2);
    });

    match execute(&request) {
        Ok(result) => {
            println!("{}", serde_json::to_string(&result).expect("result serializes"));
            process::exit(0);
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}
```

- [ ] **Step 6: Add fixture and verify**

Create `tests/fixtures/kernel/echo-request.json`:

```json
{
  "schema": "kernel.execution_request.v1",
  "request_id": "exec_echo",
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

Run:

```bash
cd native/kernel
cargo test
cargo run -p kernel-cli -- exec-json ../../tests/fixtures/kernel/echo-request.json
```

Expected: tests pass and the CLI prints JSON containing `"stdout":"hello"`.

- [ ] **Step 7: Commit**

```bash
git add native/kernel tests/fixtures/kernel .gitignore
git commit -m "feat: add native process kernel spine"
```

## Task 6: Add Bun Kernel Client

```yaml agentrunway-task
task_id: task_006
title: Add Bun Kernel Client
risk: medium
phase: implementation
dependencies: [task_002, task_005]
file_claims:
  - {path: packages/kernel-client, mode: owned}
acceptance_commands:
  - bun test packages/kernel-client/tests/kernelClient.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `packages/kernel-client/package.json`
- Create: `packages/kernel-client/tsconfig.json`
- Create: `packages/kernel-client/src/kernelClient.ts`
- Create: `packages/kernel-client/src/index.ts`
- Create: `packages/kernel-client/tests/kernelClient.test.ts`

- [ ] **Step 1: Create package files**

Create `packages/kernel-client/package.json`:

```json
{
  "name": "@waygent/kernel-client",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/kernelClient.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*"
  }
}
```

Create `packages/kernel-client/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [{ "path": "../contracts" }],
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 2: Implement kernel client**

Create `packages/kernel-client/src/kernelClient.ts`:

```ts
import { mkdtemp, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import type { KernelExecutionRequest, KernelExecutionResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";

export interface KernelClientOptions {
  kernelRoot?: string;
}

export async function executeWithKernel(
  request: KernelExecutionRequest,
  options: KernelClientOptions = {}
): Promise<KernelExecutionResult> {
  validateContract<KernelExecutionRequest>("kernel.execution_request.v1", request);
  const kernelRoot = options.kernelRoot ?? resolve("native/kernel");
  const dir = await mkdtemp(join(tmpdir(), "kernel-request-"));
  const requestPath = join(dir, "request.json");
  await writeFile(requestPath, JSON.stringify(request), "utf8");

  const proc = Bun.spawn({
    cmd: ["cargo", "run", "-q", "-p", "kernel-cli", "--", "exec-json", requestPath],
    cwd: kernelRoot,
    stdout: "pipe",
    stderr: "pipe"
  });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited
  ]);

  if (exitCode !== 0) {
    throw new Error(`kernel-cli failed with exit code ${exitCode}: ${stderr}`);
  }

  return validateContract<KernelExecutionResult>(
    "kernel.execution_result.v1",
    JSON.parse(stdout)
  );
}
```

Create `packages/kernel-client/src/index.ts`:

```ts
export * from "./kernelClient";
```

- [ ] **Step 3: Add result schema to contracts**

Modify `packages/contracts/src/schemas.ts` by adding `kernelExecutionResultSchema` and registering it:

```ts
export const kernelExecutionResultSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "kernel.execution_result.v1",
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "request_id",
    "exit_code",
    "signal",
    "timed_out",
    "stdout",
    "stderr",
    "stdout_truncated",
    "stderr_truncated",
    "duration_ms"
  ],
  properties: {
    schema: { const: "kernel.execution_result.v1" },
    request_id: { type: "string", pattern: "^exec_[a-z0-9-]+$" },
    exit_code: { anyOf: [{ type: "integer" }, { type: "null" }] },
    signal: { anyOf: [{ type: "string" }, { type: "null" }] },
    timed_out: { type: "boolean" },
    stdout: { type: "string" },
    stderr: { type: "string" },
    stdout_truncated: { type: "boolean" },
    stderr_truncated: { type: "boolean" },
    duration_ms: { type: "integer", minimum: 0 }
  }
} as const;
```

Update the `schemas` object in the same file:

```ts
export const schemas = {
  "agentlens.event.v3": platformEventSchema,
  "kernel.execution_request.v1": kernelExecutionRequestSchema,
  "kernel.execution_result.v1": kernelExecutionResultSchema,
  "runway.worker_result.v1": workerResultSchema
} as const;
```

- [ ] **Step 4: Add kernel client test**

Create `packages/kernel-client/tests/kernelClient.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { executeWithKernel } from "../src";

describe("executeWithKernel", () => {
  test("executes a bounded echo request", async () => {
    const result = await executeWithKernel({
      schema: "kernel.execution_request.v1",
      request_id: "exec_echo",
      run_id: "run_demo",
      task_id: "task_demo",
      cwd: ".",
      argv: ["printf", "hello"],
      env: {},
      timeout_ms: 1000,
      stdin: "closed",
      tty: false,
      capture: {
        stdout_limit_bytes: 100,
        stderr_limit_bytes: 100
      }
    });

    expect(result.exit_code).toBe(0);
    expect(result.stdout).toBe("hello");
    expect(result.timed_out).toBe(false);
  });
});
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/kernel-client/tests/kernelClient.test.ts
bun run typecheck
```

Expected: both commands pass.

Commit:

```bash
git add packages/kernel-client packages/contracts package.json bun.lock
git commit -m "feat: add Bun kernel client"
```

## Task 7: Add Fake Provider And Trust Projector

```yaml agentrunway-task
task_id: task_007
title: Add Fake Provider And Trust Projector
risk: medium
phase: implementation
dependencies: [task_002, task_004]
file_claims:
  - {path: packages/provider-adapters, mode: owned}
  - {path: packages/lens-projectors, mode: owned}
acceptance_commands:
  - bun test packages/provider-adapters/tests/fakeProvider.test.ts packages/lens-projectors/tests/trust.test.ts
  - bun run typecheck
required_skills: [test-driven-development]
serial: false
```

**Files:**
- Create: `packages/provider-adapters/package.json`
- Create: `packages/provider-adapters/tsconfig.json`
- Create: `packages/provider-adapters/src/types.ts`
- Create: `packages/provider-adapters/src/fakeProvider.ts`
- Create: `packages/provider-adapters/src/index.ts`
- Create: `packages/provider-adapters/tests/fakeProvider.test.ts`
- Create: `packages/lens-projectors/package.json`
- Create: `packages/lens-projectors/tsconfig.json`
- Create: `packages/lens-projectors/src/trust.ts`
- Create: `packages/lens-projectors/src/index.ts`
- Create: `packages/lens-projectors/tests/trust.test.ts`

- [ ] **Step 1: Create provider package**

Create `packages/provider-adapters/package.json`:

```json
{
  "name": "@waygent/provider-adapters",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/fakeProvider.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*",
    "@waygent/runway-control": "workspace:*"
  }
}
```

Create `packages/provider-adapters/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [
    { "path": "../contracts" },
    { "path": "../runway-control" }
  ],
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 2: Implement fake provider**

Create `packages/provider-adapters/src/types.ts`:

```ts
import type { TaskSpec } from "@waygent/runway-control";
import type { WorkerResult } from "@waygent/contracts";

export interface ProviderAdapter {
  readonly name: string;
  runTask(task: TaskSpec): Promise<WorkerResult>;
}
```

Create `packages/provider-adapters/src/fakeProvider.ts`:

```ts
import type { WorkerResult } from "@waygent/contracts";
import type { TaskSpec } from "@waygent/runway-control";
import type { ProviderAdapter } from "./types";

export class FakeProviderAdapter implements ProviderAdapter {
  readonly name = "fake-provider";

  async runTask(task: TaskSpec): Promise<WorkerResult> {
    return {
      schema: "runway.worker_result.v1",
      task_id: task.task_id,
      candidate_id: `candidate_${task.task_id.replace(/^task_/, "")}`,
      status: "completed",
      changed_files: task.file_claims
        .filter((claim) => claim.mode !== "read_only")
        .map((claim) => claim.path),
      summary: `Fake provider completed ${task.title}.`,
      evidence: {
        acceptance_commands: task.acceptance_commands,
        provider: this.name
      }
    };
  }
}
```

Create `packages/provider-adapters/src/index.ts`:

```ts
export * from "./fakeProvider";
export * from "./types";
```

- [ ] **Step 3: Add fake provider test**

Create `packages/provider-adapters/tests/fakeProvider.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { FakeProviderAdapter } from "../src";

describe("FakeProviderAdapter", () => {
  test("returns a typed worker result", async () => {
    const provider = new FakeProviderAdapter();
    const result = await provider.runTask({
      task_id: "task_demo",
      title: "Demo",
      risk: "medium",
      dependencies: [],
      file_claims: [{ path: "packages/demo.ts", mode: "owned" }],
      acceptance_commands: ["bun test"],
      serial: false
    });

    expect(result.status).toBe("completed");
    expect(result.changed_files).toEqual(["packages/demo.ts"]);
  });
});
```

- [ ] **Step 4: Create trust projector package**

Create `packages/lens-projectors/package.json`:

```json
{
  "name": "@waygent/lens-projectors",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "test": "bun test tests/trust.test.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*"
  }
}
```

Create `packages/lens-projectors/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [{ "path": "../contracts" }],
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 5: Implement trust projector**

Create `packages/lens-projectors/src/trust.ts`:

```ts
import type { PlatformEvent } from "@waygent/contracts";

export interface TrustProjection {
  status: "trusted" | "failed" | "insufficient_evidence";
  supporting_events: number;
  failing_events: number;
  warnings: string[];
}

export function projectTrust(events: PlatformEvent[]): TrustProjection {
  const supporting_events = events.filter(
    (event) => event.trust_impact === "supports_success"
  ).length;
  const failing_events = events.filter(
    (event) => event.trust_impact === "supports_failure" || event.outcome === "failed"
  ).length;

  if (failing_events > 0) {
    return { status: "failed", supporting_events, failing_events, warnings: [] };
  }
  if (supporting_events === 0) {
    return {
      status: "insufficient_evidence",
      supporting_events,
      failing_events,
      warnings: ["no supporting evidence events were recorded"]
    };
  }
  return { status: "trusted", supporting_events, failing_events, warnings: [] };
}
```

Create `packages/lens-projectors/src/index.ts`:

```ts
export * from "./trust";
```

- [ ] **Step 6: Add trust test**

Create `packages/lens-projectors/tests/trust.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { PlatformEvent } from "@waygent/contracts";
import { projectTrust } from "../src";

function event(trust_impact: PlatformEvent["trust_impact"], outcome: PlatformEvent["outcome"]): PlatformEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_${trust_impact}_${outcome}`,
    agentlens_run_id: "run_lens",
    orchestrator_run_id: "run_orchestrator",
    producer: { name: "agentlens", kind: "projector", version: "0.1.0" },
    event_type: "lens.trust_report_updated",
    occurred_at: "2026-05-21T00:00:00Z",
    sequence: 1,
    phase: "trust",
    outcome,
    severity: outcome === "failed" ? "error" : "info",
    trust_impact,
    summary: "Trust event",
    payload: {}
  };
}

describe("projectTrust", () => {
  test("trusts runs with supporting evidence and no failures", () => {
    expect(projectTrust([event("supports_success", "success")]).status).toBe("trusted");
  });

  test("fails runs with failure evidence", () => {
    expect(projectTrust([event("supports_failure", "failed")]).status).toBe("failed");
  });
});
```

- [ ] **Step 7: Verify and commit**

Run:

```bash
bun test packages/provider-adapters/tests/fakeProvider.test.ts packages/lens-projectors/tests/trust.test.ts
bun run typecheck
```

Expected: both commands pass.

Commit:

```bash
git add packages/provider-adapters packages/lens-projectors package.json bun.lock
git commit -m "feat: add fake provider and trust projector"
```

## Task 8: Add Deterministic CLI Demo End-To-End

```yaml agentrunway-task
task_id: task_008
title: Add Deterministic CLI Demo End-To-End
risk: high
phase: implementation
dependencies: [task_003, task_004, task_006, task_007]
file_claims:
  - {path: apps/cli, mode: owned}
  - {path: tests/integration/platform-demo.test.ts, mode: owned}
acceptance_commands:
  - bun run platform:demo
  - bun test tests/integration/platform-demo.test.ts
  - bun run check
  - cd native/kernel && cargo test
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `apps/cli/package.json`
- Create: `apps/cli/tsconfig.json`
- Create: `apps/cli/src/index.ts`
- Create: `apps/cli/src/demo.ts`
- Create: `tests/integration/platform-demo.test.ts`

- [ ] **Step 1: Create CLI package**

Create `apps/cli/package.json`:

```json
{
  "name": "@waygent/cli",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "types": "src/index.ts",
  "scripts": {
    "demo": "bun run src/demo.ts",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*",
    "@waygent/kernel-client": "workspace:*",
    "@waygent/lens-projectors": "workspace:*",
    "@waygent/lens-store": "workspace:*",
    "@waygent/provider-adapters": "workspace:*",
    "@waygent/runway-control": "workspace:*"
  }
}
```

Create `apps/cli/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "rootDir": ".",
    "outDir": "dist"
  },
  "references": [
    { "path": "../../packages/contracts" },
    { "path": "../../packages/kernel-client" },
    { "path": "../../packages/lens-projectors" },
    { "path": "../../packages/lens-store" },
    { "path": "../../packages/provider-adapters" },
    { "path": "../../packages/runway-control" }
  ],
  "include": ["src/**/*.ts"]
}
```

- [ ] **Step 2: Implement demo runner**

Create `apps/cli/src/index.ts`:

```ts
export { runDemo } from "./demo";
```

Create `apps/cli/src/demo.ts`:

```ts
import { mkdtemp } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { PlatformEvent } from "@waygent/contracts";
import { executeWithKernel } from "@waygent/kernel-client";
import { appendEvent, readEvents, runPaths, summarizeEvents } from "@waygent/lens-store";
import { projectTrust } from "@waygent/lens-projectors";
import { FakeProviderAdapter } from "@waygent/provider-adapters";
import { computeDurableProjection, type TaskSpec } from "@waygent/runway-control";

function event(sequence: number, event_type: string, summary: string, payload: Record<string, unknown>): PlatformEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_demo-${sequence}`,
    agentlens_run_id: "run_lens-demo",
    orchestrator_run_id: "run_orchestrator-demo",
    producer: { name: "agentrunway", kind: "orchestrator", version: "0.1.0" },
    event_type,
    occurred_at: "2026-05-21T00:00:00Z",
    sequence,
    phase: "demo",
    outcome: "success",
    severity: "info",
    trust_impact: "supports_success",
    summary,
    payload
  };
}

export async function runDemo(rootOverride?: string): Promise<{
  root: string;
  projection_status: string;
  trust_status: string;
  total_events: number;
}> {
  const root = rootOverride ?? (await mkdtemp(join(tmpdir(), "waygent-demo-")));
  const paths = runPaths(root, "workspace-demo", "run_lens-demo");
  const task: TaskSpec = {
    task_id: "task_demo",
    title: "Demo task",
    risk: "medium",
    dependencies: [],
    file_claims: [{ path: "packages/demo.ts", mode: "owned" }],
    acceptance_commands: ["printf kernel-ok"],
    serial: false
  };

  const projection = computeDurableProjection({
    tasks: [task],
    completed_tasks: [],
    running_tasks: [],
    failed_tasks: []
  });
  await appendEvent(paths.eventsPath, event(1, "runway.safe_wave_selected", "Safe wave selected.", {
    safe_wave: projection.safe_wave.map((item) => item.task_id)
  }));

  const provider = new FakeProviderAdapter();
  const workerResult = await provider.runTask(task);
  await appendEvent(paths.eventsPath, event(2, "runway.worker_result", workerResult.summary, workerResult));

  const kernelResult = await executeWithKernel({
    schema: "kernel.execution_request.v1",
    request_id: "exec_demo",
    run_id: "run_orchestrator-demo",
    task_id: "task_demo",
    cwd: ".",
    argv: ["printf", "kernel-ok"],
    env: {},
    timeout_ms: 1000,
    stdin: "closed",
    tty: false,
    capture: {
      stdout_limit_bytes: 100,
      stderr_limit_bytes: 100
    }
  });
  await appendEvent(paths.eventsPath, event(3, "kernel.exec_completed", "Kernel command completed.", kernelResult));

  const events = await readEvents(paths.eventsPath);
  const summary = summarizeEvents(events);
  const trust = projectTrust(events);

  return {
    root,
    projection_status: projection.projection_status,
    trust_status: trust.status,
    total_events: summary.total_events
  };
}

if (import.meta.main) {
  const result = await runDemo();
  console.log(JSON.stringify(result, null, 2));
}
```

- [ ] **Step 3: Add integration test**

Create `tests/integration/platform-demo.test.ts`:

```ts
import { mkdtemp } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { readEvents, runPaths } from "../../packages/lens-store/src";
import { runDemo } from "../../apps/cli/src";

describe("platform demo", () => {
  test("runs fake provider, kernel command, event store, and trust projection", async () => {
    const root = await mkdtemp(join(tmpdir(), "platform-demo-test-"));
    const result = await runDemo(root);
    const paths = runPaths(root, "workspace-demo", "run_lens-demo");
    const events = await readEvents(paths.eventsPath);

    expect(result.projection_status).toBe("running");
    expect(result.trust_status).toBe("trusted");
    expect(result.total_events).toBe(3);
    expect(events.map((event) => event.event_type)).toEqual([
      "runway.safe_wave_selected",
      "runway.worker_result",
      "kernel.exec_completed"
    ]);
  });
});
```

- [ ] **Step 4: Verify the full slice**

Run:

```bash
bun run platform:demo
bun test tests/integration/platform-demo.test.ts
bun run check
cd native/kernel && cargo test
```

Expected:

- `bun run platform:demo` prints JSON with `"trust_status": "trusted"` and `"total_events": 3`.
- integration test passes.
- typecheck and all Bun tests pass.
- Rust kernel tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/cli tests/integration package.json bun.lock
git commit -m "feat: add deterministic platform spine demo"
```

## Final Verification

Run from repository root:

```bash
bun install
bun run check
bun run platform:demo
cd native/kernel && cargo test
cd ../.. && git diff --check
```

Expected:

- Bun install succeeds.
- TypeScript typecheck succeeds.
- All Bun tests pass.
- Demo prints a trusted run with three events.
- Rust kernel tests pass.
- `git diff --check` prints no output.

## Spec Coverage Review

This Phase 1 plan covers the source spec's first executable slice:

- Bun workspace and package boundaries: Task 1.
- Shared contract fixtures and validators: Task 2.
- Durable projection and safe-wave scheduler: Task 3.
- Append-only AgentLens event journal: Task 4.
- Rust kernel protocol and bounded process execution: Task 5.
- Bun-to-Rust kernel client: Task 6.
- Fake provider adapter and trust projection: Task 7.
- Deterministic end-to-end run: Task 8.

Covered by the full implementation program after Phase 1:

- Python/legacy deletion.
- Codex and Claude live provider adapters.
- React dashboard migration.
- SQLite projection cache.
- patch/diff/apply kernel crate.
- sandbox policy enforcement beyond bounded local process execution.
- graphify removal cleanup if generated files reappear.
