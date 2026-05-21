# Waygent Runtime And AgentLens Product Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Waygent into the product runtime that independently provides KWS-grade plan execution while exposing every real run through AgentLens, the local API, and the console.

**Architecture:** Waygent stays independent from `skills/kws-*`; those skills are not product dependencies. The implementation proceeds as vertical slices: skill/CLI command, durable runtime state, provider and scheduler execution, AgentLens-compatible events, API reads, console inspection, and explicit apply/recovery gates.

**Tech Stack:** Bun, TypeScript project references, React/Vite, Rust kernel crates, Python AgentLens, pytest, filesystem JSONL events, git worktrees.

---

## Source Design

- Design: `docs/architecture/2026-05-21-waygent-runtime-agentlens-product-parity-design.md`
- Product architecture index: `docs/architecture/waygent.md`
- Existing repository migration plan: `docs/migration/2026-05-21-waygent-repository-migration-implementation-plan.md`

## Non-Negotiable Boundaries

- Do not call `skills/kws-codex-plan-executor` or `skills/kws-claude-multi-agent-executor` from Waygent.
- Do not emit active `kws-cpe.*`, `kws-cme.*`, or KWS orchestrator namespaces from Waygent.
- Keep `skills/waygent` thin: natural-language intent plus CLI invocation only.
- Waygent workers and provider adapters must not write AgentLens directly.
- AgentLens must read/project Waygent events; it must not mutate Waygent execution state.
- A slice is incomplete if the CLI works but the API/console cannot inspect the same run.

## File Structure And Ownership

### Skill Contract

- `skills/waygent/SKILL.md`: operator-facing skill contract.
- `skills/waygent/README.md`: concise human guide.
- `skills/waygent/references/commands.md`: CLI command reference.
- `skills/waygent/references/modes.md`: run/status/resume/apply behavior.
- `skills/waygent/evals/run.sh`: skill contract eval entrypoint.
- `skills/waygent/evals/check_skill_contract.py`: static contract checks.

### CLI And Orchestrator

- `apps/cli/src/index.ts`: command parsing and command dispatch only.
- `apps/cli/tests/cli.test.ts`: command behavior tests.
- `packages/orchestrator/src/planDiscovery.ts`: `--plan`, `--latest`, and `--topic` resolution.
- `packages/orchestrator/src/planParser.ts`: task fence parser.
- `packages/orchestrator/src/runState.ts`: durable run state schema and read/write helpers.
- `packages/orchestrator/src/orchestrator.ts`: lifecycle orchestration.
- `packages/orchestrator/src/runCommands.ts`: status/events/inspect/explain/resume/apply read commands.
- `packages/orchestrator/tests/*.test.ts`: runtime behavior tests.

### Execution, Worktree, And Providers

- `packages/kernel-client/src/worktreeClient.ts`: TypeScript worktree guard wrapper.
- `native/kernel/crates/git-worktree/src/lib.rs`: native worktree ownership/cleanup.
- `packages/provider-adapters/src/types.ts`: worker adapter contract.
- `packages/provider-adapters/src/fakeProvider.ts`: deterministic offline adapter.
- `packages/provider-adapters/src/codexAdapter.ts`: Codex process adapter boundary.
- `packages/provider-adapters/src/claudeAdapter.ts`: Claude process adapter boundary.
- `packages/context-packer/src/taskContext.ts`: task-scoped context packet.
- `packages/runway-control/src/*`: safe-wave, barrier, recovery, and apply state.

### AgentLens, API, And Console

- `packages/contracts/src/types.ts`: event, run, apply, recovery, and evidence types.
- `packages/lens-store/src/*`: filesystem event/run/artifact store.
- `packages/lens-projectors/src/*`: trust, failure, timeline, apply, and resume projections.
- `apps/api/src/server.ts`: real run API routes and SSE.
- `apps/api/tests/*.test.ts`: API tests against real run roots.
- `apps/console/src/uiModel.ts`: API response to UI model mapping.
- `apps/console/src/App.tsx`: visible run inspection surface.
- `components/agentlens/src/agentlens/*`: Python read compatibility and trust/eval tests when event semantics change.

## Execution Order

Sequential core:

1. Task 1 skill contract.
2. Task 2 plan discovery/parser.
3. Task 3 CLI real command surface.
4. Task 4 durable state and filesystem lifecycle.
5. Task 5 worktree isolation.
6. Task 6 provider adapters.
7. Task 7 safe-wave multi-agent runtime.
8. Task 8 AgentLens projections.
9. Task 9 API real run reads.
10. Task 10 console real run inspection.
11. Task 11 apply and recovery.
12. Task 12 full verification and docs closure.

Parallel-safe after Task 4:

- Task 6 provider adapter tests and Task 8 projector tests can proceed in parallel if write scopes stay disjoint.
- Task 9 API and Task 10 console can proceed in parallel only after the API response shape is locked.

---

### Task 1: Promote `skills/waygent` To A Tested Product Skill

**Files:**
- Modify: `skills/waygent/SKILL.md`
- Create: `skills/waygent/README.md`
- Modify: `skills/waygent/references/commands.md`
- Create: `skills/waygent/references/modes.md`
- Create: `skills/waygent/evals/run.sh`
- Create: `skills/waygent/evals/check_skill_contract.py`
- Modify: `skills/README.md`

- [ ] **Step 1: Write the failing skill contract eval**

Create `skills/waygent/evals/check_skill_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

required_skill_phrases = [
    "Waygent",
    "waygent run --latest",
    "waygent status --last",
    "waygent events --run",
    "waygent inspect --run",
    "waygent explain --last",
    "waygent resume --last",
    "waygent apply --run",
    "must not call `skills/kws-codex-plan-executor`",
    "must not call `skills/kws-claude-multi-agent-executor`",
]

required_files = [
    "SKILL.md",
    "README.md",
    "references/commands.md",
    "references/modes.md",
]


def main() -> int:
    missing_files = [name for name in required_files if not (ROOT / name).is_file()]
    if missing_files:
        raise SystemExit(f"missing files: {', '.join(missing_files)}")

    combined = "\n".join((ROOT / name).read_text() for name in required_files)
    missing_phrases = [phrase for phrase in required_skill_phrases if phrase not in combined]
    if missing_phrases:
        raise SystemExit(f"missing contract phrases: {', '.join(missing_phrases)}")

    print("waygent skill contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the eval runner**

Create `skills/waygent/evals/run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 evals/check_skill_contract.py
```

Then run:

```bash
chmod +x skills/waygent/evals/run.sh
skills/waygent/evals/run.sh
```

Expected: FAIL because `README.md` and `references/modes.md` do not exist.

- [ ] **Step 3: Expand `SKILL.md`**

Replace the body of `skills/waygent/SKILL.md` with a contract that states:

```markdown
# Waygent

Use this skill when the user asks to run, inspect, resume, explain, or apply a
Waygent execution from natural language.

Waygent is the product runtime. This skill translates operator intent into the
`waygent` CLI and then reports the command outcome. It must not implement
scheduling, provider execution, worktree mutation, trust scoring, or direct
AgentLens writes.

Hard boundaries:

- Waygent must not call `skills/kws-codex-plan-executor`.
- Waygent must not call `skills/kws-claude-multi-agent-executor`.
- KWS executor skills are not Waygent product dependencies.
- New Waygent runs use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`
  event families.

Default mappings:

- "최근 승인된 플랜 실행해줘" -> `waygent run --latest`
- "상태 보여줘" -> `waygent status --last`
- "이벤트 보여줘" -> `waygent events --run <run_id> --json`
- "자세히 검사해줘" -> `waygent inspect --run <run_id> --json`
- "왜 막혔어?" -> `waygent explain --last`
- "재개해줘" -> `waygent resume --last`
- "검증 통과한 것만 적용해줘" -> `waygent apply --run <run_id>`

Stop rules:

- If the plan is missing or `--latest` is ambiguous, ask for the plan path.
- If apply reports `dirty_source_checkout`, report the blocker and do not retry.
- If verification fails, use `waygent explain --last` before resume.
```

- [ ] **Step 4: Add README and mode reference**

Create `skills/waygent/README.md` with:

```markdown
# Waygent Skill

Waygent is the active product skill for running local agent executions. The
skill is intentionally thin: it maps natural language to `waygent` CLI commands
and lets the runtime own state, scheduling, providers, verification, AgentLens
events, resume, and apply.

KWS executor skills may remain in this repository, but they are outside the
Waygent product boundary.

## Common Commands

```bash
waygent run --latest
waygent run --plan docs/migration/example.md --provider fake
waygent status --last
waygent events --run run_example --json
waygent inspect --run run_example --json
waygent explain --last
waygent resume --last
waygent apply --run run_example
```
```

Create `skills/waygent/references/modes.md`:

```markdown
# Waygent Modes

## run

Creates a durable run from a plan, latest plan, or topic query. The runtime
creates state, events, artifacts, and worktree data.

## status

Returns the last known status from the event journal and trust projection.

## events

Reads persisted `agentlens.event.v3` events for the selected run.

## inspect

Returns run state, task graph, safe wave, trust, failure, and apply state.

## explain

Summarizes the active failure barrier or reports that no barrier is active.

## resume

Returns the next allowed operator action from durable state.

## apply

Applies a verified checkpoint only when the source checkout is clean.
```

- [ ] **Step 5: Update command reference and skill index**

Ensure `skills/waygent/references/commands.md` includes exactly these commands:

```bash
waygent run --plan <path> --spec <path> --provider fake
waygent run --latest --provider codex --execution-mode multi-agent
waygent run --topic <topic> --provider claude --main-model opus --main-reasoning high
waygent status --last
waygent status --run <run_id>
waygent events --run <run_id> --json
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
```

Update `skills/README.md` so the `waygent` row says it is the active product
runtime skill and KWS skills are separate non-product executor skills.

- [ ] **Step 6: Verify and commit**

Run:

```bash
skills/waygent/evals/run.sh
git diff --check
```

Expected: eval prints `waygent skill contract ok`; `git diff --check` exits 0.

Commit:

```bash
git add skills/waygent skills/README.md
git commit -m "docs: promote Waygent skill contract"
```

---

### Task 2: Resolve Real Plans From `--plan`, `--latest`, And `--topic`

**Files:**
- Create: `packages/orchestrator/src/planDiscovery.ts`
- Modify: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/planDiscovery.test.ts`
- Test: `packages/orchestrator/tests/planParser.test.ts`

- [ ] **Step 1: Write failing parser compatibility test**

Append to `packages/orchestrator/tests/planParser.test.ts`:

```typescript
test("imports existing agentrunway-task fences without depending on KWS runtime", () => {
  const parsed = parseWaygentPlan(`
\`\`\`yaml agentrunway-task
task_id: phase9_task_004
title: Implement Waygent CLI Commands
risk: medium
dependencies: [phase9_task_002, phase9_task_003]
file_claims:
  - {path: apps/cli, mode: owned}
acceptance_commands:
  - bun test apps/cli/tests/cli.test.ts
\`\`\`
`);

  expect(parsed.tasks[0]).toEqual({
    id: "phase9_task_004",
    title: "Implement Waygent CLI Commands",
    dependencies: ["phase9_task_002", "phase9_task_003"],
    file_claims: [{ path: "apps/cli", mode: "owned" }],
    risk: "medium",
    verification_commands: ["bun test apps/cli/tests/cli.test.ts"]
  });
});
```

- [ ] **Step 2: Run parser test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/planParser.test.ts
```

Expected: FAIL with `missing waygent-task block`.

- [ ] **Step 3: Add plan discovery tests**

Create `packages/orchestrator/tests/planDiscovery.test.ts`:

```typescript
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { discoverPlan, resolvePlanInput } from "../src/planDiscovery";

const plan = (id: string) => `
\`\`\`yaml waygent-task
id: ${id}
title: ${id}
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

describe("Waygent plan discovery", () => {
  test("discovers the newest Waygent plan by filename date", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-plan-"));
    mkdirSync(join(root, "docs", "migration"), { recursive: true });
    writeFileSync(join(root, "docs", "migration", "2026-05-20-old.md"), plan("old_task"));
    writeFileSync(join(root, "docs", "migration", "2026-05-21-new.md"), plan("new_task"));

    const found = discoverPlan({ workspace: root, latest: true });

    expect(found.path?.endsWith("2026-05-21-new.md")).toBe(true);
    expect(found.markdown).toContain("id: new_task");
  });

  test("filters topic matches against filename and heading text", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-topic-"));
    mkdirSync(join(root, "docs", "plan"), { recursive: true });
    writeFileSync(join(root, "docs", "plan", "2026-05-21-console-runtime.md"), plan("console_task"));

    const found = resolvePlanInput({ workspace: root, topic: "console runtime" });

    expect(found.path?.endsWith("2026-05-21-console-runtime.md")).toBe(true);
  });
});
```

- [ ] **Step 4: Run discovery test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/planDiscovery.test.ts
```

Expected: FAIL because `planDiscovery.ts` does not exist.

- [ ] **Step 5: Implement parser support**

In `packages/orchestrator/src/planParser.ts`:

```typescript
const TASK_BLOCK = /```yaml (?:waygent-task|agentrunway-task)\n([\s\S]*?)\n```/g;
```

Before required-field validation:

```typescript
if (!scalar.has("id") && scalar.has("task_id")) {
  scalar.set("id", scalar.get("task_id")!);
}
```

Treat `acceptance_commands:` like `verify:` and add inline file claim parsing:

```typescript
if (line === "acceptance_commands:") {
  index = readStringList(lines, index + 1, verification) - 1;
  continue;
}
```

```typescript
function parseInlineClaim(line: string): Partial<FileClaim> {
  const body = line.replace(/^- \{/, "").replace(/\}$/, "");
  const claim: Partial<FileClaim> = {};
  for (const part of body.split(",")) {
    const [rawKey, ...rawValue] = part.split(":");
    const key = rawKey?.trim();
    const value = rawValue.join(":").trim();
    if (key === "path") claim.path = value;
    if (key === "mode") claim.mode = value as FileClaimMode;
  }
  return claim;
}
```

- [ ] **Step 6: Implement plan discovery**

Create `packages/orchestrator/src/planDiscovery.ts` with:

```typescript
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";

export interface PlanDiscoveryOptions {
  workspace: string;
  plan_path?: string;
  latest?: boolean;
  topic?: string;
  inline_plan?: string;
}

export interface ResolvedPlanInput {
  markdown: string;
  path: string | null;
}

const PLAN_MARKER = /```yaml (?:waygent-task|agentrunway-task)\n/;
const SKIP_DIRS = new Set([".git", ".venv", "node_modules", "target", "tmp", "dist", "build"]);

export function resolvePlanInput(options: PlanDiscoveryOptions): ResolvedPlanInput {
  if (options.inline_plan?.trim()) {
    if (PLAN_MARKER.test(options.inline_plan)) return { markdown: options.inline_plan, path: null };
    const candidate = resolve(options.workspace, options.inline_plan);
    if (existsSync(candidate)) return readPlanFile(candidate);
    return { markdown: options.inline_plan, path: null };
  }
  if (options.plan_path) return readPlanFile(resolve(options.workspace, options.plan_path));
  if (options.latest || options.topic) return discoverPlan(options);
  throw new Error("plan input required; pass --plan, --latest, or --topic");
}

export function discoverPlan(options: PlanDiscoveryOptions): ResolvedPlanInput {
  const workspace = resolve(options.workspace);
  const candidates = collectMarkdownPlans(workspace)
    .map((path) => ({ path, markdown: readFileSync(path, "utf8") }))
    .filter((candidate) => PLAN_MARKER.test(candidate.markdown))
    .filter((candidate) => matchesTopic(candidate.path, candidate.markdown, options.topic));

  if (candidates.length === 0) {
    throw new Error(options.topic ? `no Waygent plan found for topic ${options.topic}` : "no Waygent plan found");
  }

  candidates.sort((left, right) => planRank(right.path) - planRank(left.path) || right.path.localeCompare(left.path));
  return { markdown: candidates[0]!.markdown, path: candidates[0]!.path };
}

function readPlanFile(path: string): ResolvedPlanInput {
  if (!existsSync(path)) throw new Error(`plan not found: ${path}`);
  return { markdown: readFileSync(path, "utf8"), path };
}

function collectMarkdownPlans(workspace: string): string[] {
  const roots = [
    workspace,
    join(workspace, "docs"),
    join(workspace, "docs", "plan"),
    join(workspace, "docs", "migration"),
    join(workspace, "components", "agentlens", "docs", "plan")
  ];
  const out = new Set<string>();
  for (const root of roots) {
    if (existsSync(root)) walk(root, out, 0);
  }
  return [...out];
}

function walk(dir: string, out: Set<string>, depth: number): void {
  if (depth > 6) return;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(join(dir, entry.name), out, depth + 1);
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".md")) out.add(join(dir, entry.name));
  }
}

function matchesTopic(path: string, markdown: string, topic?: string): boolean {
  if (!topic) return true;
  const terms = topic.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = `${basename(path)}\n${markdown.slice(0, 4000)}`.toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function planRank(path: string): number {
  const stat = statSync(path);
  const nameDate = basename(path).match(/(20\d{2})-(\d{2})-(\d{2})/);
  if (nameDate) return Number(`${nameDate[1]}${nameDate[2]}${nameDate[3]}`);
  return Math.floor(stat.mtimeMs);
}
```

Export it from `packages/orchestrator/src/index.ts`.

- [ ] **Step 7: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/planParser.test.ts packages/orchestrator/tests/planDiscovery.test.ts
bun run typecheck
```

Expected: tests pass and TypeScript project references compile.

Commit:

```bash
git add packages/orchestrator/src packages/orchestrator/tests
git commit -m "feat: resolve Waygent implementation plans"
```

---

### Task 3: Make CLI Commands Read And Mutate Real Run Data

**Files:**
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Test: `packages/orchestrator/tests/runCommands.test.ts`

- [ ] **Step 1: Add failing CLI tests**

Append to `apps/cli/tests/cli.test.ts`:

```typescript
test("run --latest discovers and executes the newest local implementation plan", async () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-workspace-"));
  const root = mkdtempSync(join(tmpdir(), "waygent-runs-"));
  mkdirSync(join(workspace, "docs", "plan"), { recursive: true });
  writeFileSync(join(workspace, "docs", "plan", "2026-05-21-real-plan.md"), plan("task_real"));

  const result = await runCli(["run", "--workspace", workspace, "--root", root, "--latest", "--run", "run_latest"]);

  expect(result).toMatchObject({ run_id: "run_latest", projection: { safe_wave: ["task_real"] } });
});

test("events reads persisted run events", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-cli-events-"));
  await runCli(["run", "--root", root, "--run", "run_events"]);

  const result = await runCli(["events", "--root", root, "--run", "run_events"]);

  expect(result).toMatchObject({ run_id: "run_events", total_events: 6 });
  expect((result as { events: Array<{ event_type: string }> }).events[0]?.event_type).toBe("platform.run_started");
});
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
bun test apps/cli/tests/cli.test.ts
```

Expected: FAIL because `--latest` still falls back to demo input and `events`
returns a stub.

- [ ] **Step 3: Add run command helpers**

In `packages/orchestrator/src/runCommands.ts`, add:

```typescript
export function eventsRun(options: RunCommandOptions): { run_id: string; total_events: number; events: AgentLensEvent[] } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  return { run_id: runId, total_events: events.length, events };
}

export function inspectRun(options: RunCommandOptions): {
  run_id: string;
  status: RunStatus;
  total_events: number;
  trust_status: string;
  failures: ReturnType<typeof projectFailureSummary>;
} {
  const status = statusRun(options);
  return {
    ...status,
    failures: projectFailureSummary(readEvents(runPaths(options.root, status.run_id).events))
  };
}
```

Import `AgentLensEvent` from `@waygent/contracts`.

- [ ] **Step 4: Wire CLI flags**

In `apps/cli/src/index.ts`, extend `ParsedCli` handling:

```typescript
const workspace = String(parsed.flags.workspace ?? process.cwd());
```

For run options:

```typescript
if (parsed.flags.latest) options.latest = true;
if (typeof parsed.flags.topic === "string") options.topic = parsed.flags.topic;
if (typeof parsed.flags.workspace === "string") options.workspace = parsed.flags.workspace;
```

Route commands:

```typescript
if (parsed.command === "events") return eventsRun(runCommandOptions(parsed));
if (parsed.command === "inspect") return inspectRun(runCommandOptions(parsed));
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test apps/cli/tests/cli.test.ts packages/orchestrator/tests/runCommands.test.ts
bun run platform:demo
```

Expected: tests pass; demo still prints trusted run.

Commit:

```bash
git add apps/cli/src apps/cli/tests packages/orchestrator/src packages/orchestrator/tests
git commit -m "feat: read real Waygent run data from CLI"
```

---

### Task 4: Add Durable Run State And Completion Audit

**Files:**
- Create: `packages/orchestrator/src/runState.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Test: `packages/orchestrator/tests/runState.test.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`

- [ ] **Step 1: Write failing run state tests**

Create `packages/orchestrator/tests/runState.test.ts`:

```typescript
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunState, writeRunState } from "../src/runState";

describe("Waygent run state", () => {
  test("persists lifecycle, worktree, task, and audit metadata", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-"));
    writeRunState(root, {
      schema: "waygent.run_state.v1",
      run_id: "run_state",
      workspace: "/workspace",
      worktree: "/worktree",
      status: "completed",
      provider: "fake",
      execution_mode: "multi-agent",
      tasks: [{ id: "task_a", status: "verified", checkpoint_ref: "checkpoint_task_a" }],
      completion_audit: {
        status: "passed",
        commands: ["printf hello"],
        evidence_events: ["event_run_state_5"]
      },
      apply: { status: "not_applied" }
    });

    expect(readRunState(root, "run_state")).toMatchObject({
      run_id: "run_state",
      status: "completed",
      tasks: [{ id: "task_a", status: "verified" }],
      completion_audit: { status: "passed" }
    });
  });
});
```

- [ ] **Step 2: Run state test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/runState.test.ts
```

Expected: FAIL because `runState.ts` does not exist.

- [ ] **Step 3: Implement run state helpers**

Create `packages/orchestrator/src/runState.ts`:

```typescript
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExecutionMode, ProviderName } from "./executionProfile";

export type WaygentTaskRunStatus = "pending" | "running" | "completed" | "verified" | "failed" | "blocked";
export type WaygentRunLifecycleStatus = "created" | "running" | "blocked" | "failed" | "completed";
export type WaygentApplyStatus = "not_applied" | "blocked" | "applied";

export interface WaygentRunState {
  schema: "waygent.run_state.v1";
  run_id: string;
  workspace: string;
  worktree: string;
  status: WaygentRunLifecycleStatus;
  provider: ProviderName;
  execution_mode: ExecutionMode;
  tasks: Array<{ id: string; status: WaygentTaskRunStatus; checkpoint_ref?: string; failure_class?: string }>;
  completion_audit: null | { status: "passed" | "failed"; commands: string[]; evidence_events: string[] };
  apply: { status: WaygentApplyStatus; reason?: string };
}

export function runStatePath(root: string, runId: string): string {
  return join(root, runId, "state.json");
}

export function writeRunState(root: string, state: WaygentRunState): void {
  mkdirSync(join(root, state.run_id), { recursive: true });
  writeFileSync(runStatePath(root, state.run_id), `${JSON.stringify(state, null, 2)}\n`);
}

export function readRunState(root: string, runId: string): WaygentRunState {
  return JSON.parse(readFileSync(runStatePath(root, runId), "utf8")) as WaygentRunState;
}
```

Export it from `packages/orchestrator/src/index.ts`.

- [ ] **Step 4: Write state during orchestration**

In `packages/orchestrator/src/orchestrator.ts`, after profile and graph
creation, write created/running state, then update it after verification:

```typescript
writeRunState(options.root, {
  schema: "waygent.run_state.v1",
  run_id: runId,
  workspace: options.workspace ?? process.cwd(),
  worktree: paths.root,
  status: "running",
  provider: profile.provider,
  execution_mode: profile.execution_mode,
  tasks: parsed.tasks.map((task) => ({ id: task.id, status: task.id === taskId ? "running" : "pending" })),
  completion_audit: null,
  apply: { status: "not_applied" }
});
```

After verification event:

```typescript
writeRunState(options.root, {
  schema: "waygent.run_state.v1",
  run_id: runId,
  workspace: options.workspace ?? process.cwd(),
  worktree: paths.root,
  status: "completed",
  provider: profile.provider,
  execution_mode: profile.execution_mode,
  tasks: parsed.tasks.map((task) => ({
    id: task.id,
    status: task.id === taskId ? "verified" : "pending",
    checkpoint_ref: task.id === taskId ? task.checkpoint_ref : undefined
  })),
  completion_audit: {
    status: "passed",
    commands: parsedTask?.verification_commands ?? ["printf hello"],
    evidence_events: [`event_${runId}_5`]
  },
  apply: { status: "not_applied" }
});
```

- [ ] **Step 5: Include state in inspect/resume**

Update `inspectRun` to include `state: readRunState(options.root, runId)` when
`state.json` exists. Update `resumeRun` so completed runs return:

```typescript
allowed_actions: ["inspect_run", "apply_verified_checkpoint"]
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/runState.test.ts packages/orchestrator/tests/orchestratorRun.test.ts packages/orchestrator/tests/runCommands.test.ts
bun run platform:demo
```

Expected: tests pass; `tmp/waygent-runs/run_demo/state.json` exists after demo.

Commit:

```bash
git add packages/orchestrator/src packages/orchestrator/tests
git commit -m "feat: persist Waygent run state"
```

---

### Task 5: Create Isolated Worktrees For Real Runs

**Files:**
- Modify: `packages/kernel-client/src/worktreeClient.ts`
- Modify: `packages/kernel-client/tests/worktreeClient.test.ts`
- Modify: `native/kernel/crates/git-worktree/src/lib.rs`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`

- [ ] **Step 1: Add failing worktree creation test**

Append to `packages/kernel-client/tests/worktreeClient.test.ts`:

```typescript
test("plans isolated worktree paths under a Waygent-owned branch", () => {
  expect(planWorktree({
    run_id: "run_demo",
    task_id: "task_demo",
    workspace: "/repo",
    worktree_root: "/tmp/waygent-worktrees"
  })).toEqual({
    branch: "waygent/run_demo/task_demo",
    path: "/tmp/waygent-worktrees/run_demo/task_demo",
    source: "/repo"
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/kernel-client/tests/worktreeClient.test.ts
```

Expected: FAIL because `planWorktree` is not exported.

- [ ] **Step 3: Implement TypeScript worktree planning**

In `packages/kernel-client/src/worktreeClient.ts`, add:

```typescript
import { join } from "node:path";

export interface PlannedWorktree {
  branch: string;
  path: string;
  source: string;
}

export function planWorktree(options: {
  run_id: string;
  task_id: string;
  workspace: string;
  worktree_root: string;
}): PlannedWorktree {
  return {
    branch: buildWorktreeBranch(options.run_id, options.task_id),
    path: join(options.worktree_root, options.run_id, options.task_id),
    source: options.workspace
  };
}
```

- [ ] **Step 4: Guard native ownership**

Extend `native/kernel/crates/git-worktree/src/lib.rs` tests so `waygent/` is the
only owned branch prefix accepted for cleanup. The expected test shape:

```rust
#[test]
fn refuses_non_waygent_owned_branch_names() {
    assert!(validate_owned_branch("codex/run/task").is_err());
    assert!(validate_owned_branch("kws-cpe/run/task").is_err());
}
```

- [ ] **Step 5: Use planned worktree in run state**

In `packages/orchestrator/src/orchestrator.ts`, set state `worktree` from
`planWorktree({ run_id: runId, task_id: task.id, workspace, worktree_root })`.
For this slice, keep actual file mutation fake-provider-only; the state must
still record the intended isolated worktree path and branch.

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test packages/kernel-client/tests/worktreeClient.test.ts packages/orchestrator/tests/orchestratorRun.test.ts
cd native/kernel && cargo fmt --all -- --check && cargo test -p git-worktree
```

Expected: all tests pass.

Commit:

```bash
git add packages/kernel-client native/kernel/crates/git-worktree packages/orchestrator
git commit -m "feat: plan Waygent isolated worktrees"
```

---

### Task 6: Normalize Fake, Codex, And Claude Provider Boundaries

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/fakeProvider.ts`
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/claudeAdapter.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Test: `packages/provider-adapters/tests/fakeProvider.test.ts`
- Test: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Test: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [ ] **Step 1: Add provider contract test**

Append to `packages/provider-adapters/tests/codexAdapter.test.ts`:

```typescript
test("Codex adapter builds a non-executed command request by default", () => {
  const adapter = new CodexProviderAdapter({ executable: "codex" });
  expect(adapter.describe()).toEqual({
    provider: "codex",
    execution: "process",
    direct_agentlens_writes: false
  });
});
```

Append to `packages/provider-adapters/tests/claudeAdapter.test.ts`:

```typescript
test("Claude adapter builds a non-executed command request by default", () => {
  const adapter = new ClaudeProviderAdapter({ executable: "claude" });
  expect(adapter.describe()).toEqual({
    provider: "claude",
    execution: "process",
    direct_agentlens_writes: false
  });
});
```

- [ ] **Step 2: Run provider tests and verify RED**

Run:

```bash
bun test packages/provider-adapters/tests/codexAdapter.test.ts packages/provider-adapters/tests/claudeAdapter.test.ts
```

Expected: FAIL because adapter classes or `describe()` are missing.

- [ ] **Step 3: Define adapter interface**

In `packages/provider-adapters/src/types.ts`:

```typescript
export interface ProviderAdapterDescription {
  provider: "fake" | "codex" | "claude";
  execution: "deterministic" | "process";
  direct_agentlens_writes: false;
}

export interface ProviderAdapter {
  describe(): ProviderAdapterDescription;
  run(task: {
    task_id: string;
    candidate_id: string;
    prompt: string;
    changed_files: string[];
  }): Promise<WorkerResult>;
}
```

- [ ] **Step 4: Implement Codex and Claude process boundaries**

In `packages/provider-adapters/src/codexAdapter.ts`:

```typescript
import type { WorkerResult } from "@waygent/contracts";
import type { ProviderAdapter, ProviderAdapterDescription } from "./types";

export class CodexProviderAdapter implements ProviderAdapter {
  constructor(private readonly options: { executable: string }) {}

  describe(): ProviderAdapterDescription {
    return { provider: "codex", execution: "process", direct_agentlens_writes: false };
  }

  async run(task: { task_id: string; candidate_id: string; prompt: string; changed_files: string[] }): Promise<WorkerResult> {
    return {
      schema: "runway.worker_result.v1",
      task_id: task.task_id,
      candidate_id: task.candidate_id,
      status: "blocked",
      summary: `Codex provider requires process execution wiring: ${this.options.executable}`,
      changed_files: task.changed_files,
      evidence: { provider: "codex", process_boundary: true }
    };
  }
}
```

Mirror the same structure in `claudeAdapter.ts` with `provider: "claude"`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/provider-adapters/tests
bun run typecheck
```

Expected: provider adapter tests pass and typecheck passes.

Commit:

```bash
git add packages/provider-adapters
git commit -m "feat: define Waygent provider adapter boundaries"
```

---

### Task 7: Execute Safe-Wave Multi-Agent Runtime Through Provider Adapters

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/runState.ts`
- Modify: `packages/context-packer/src/taskContext.ts`
- Modify: `packages/runway-control/src/projection.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`
- Test: `packages/context-packer/tests/taskContext.test.ts`
- Test: `packages/runway-control/tests/scheduler.test.ts`

- [ ] **Step 1: Add failing multi-task run test**

Append to `packages/orchestrator/tests/orchestratorRun.test.ts`:

```typescript
test("dispatches every task in the scheduler-approved safe wave", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-safe-wave-"));
  const result = await runWaygent({
    root,
    run_id: "run_wave",
    profile: { provider: "fake", execution_mode: "multi-agent" },
    plan: `
\`\`\`yaml waygent-task
id: task_a
title: Task A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - printf a
\`\`\`
\`\`\`yaml waygent-task
id: task_b
title: Task B
dependencies: []
file_claims:
  - path: b.txt
    mode: owned
risk: low
verify:
  - printf b
\`\`\`
`
  });

  expect(result.projection.safe_wave).toEqual(["task_a", "task_b"]);
  expect(result.events.filter((event) => event.event_type === "runway.worker_result")).toHaveLength(2);
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected: FAIL because the orchestrator dispatches only the first safe-wave
task.

- [ ] **Step 3: Dispatch all safe-wave tasks**

In `packages/orchestrator/src/orchestrator.ts`, replace the single `taskId`
flow with:

```typescript
const safeWave = projection.safe_wave.length > 0 ? projection.safe_wave : [parsed.tasks[0]!.id];
for (const taskId of safeWave) {
  const task = graph.tasks.get(taskId);
  if (!task) throw new Error(`task ${taskId} missing from graph`);
  const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);
  const worker = await provider.run({
    task_id: task.id,
    candidate_id: `candidate_${task.id}`,
    prompt: buildTaskPrompt(parsedTask),
    changed_files: []
  });
  // append worker and verification events with incrementing sequence numbers
}
```

Add:

```typescript
function buildTaskPrompt(task: ParsedWaygentTask | undefined): string {
  if (!task) return "Waygent task";
  return `${task.title}\n\nVerify:\n${task.verification_commands.join("\n")}`;
}
```

- [ ] **Step 4: Update task context packet**

In `packages/context-packer/src/taskContext.ts`, ensure task context includes
`file_claims`, `verification_commands`, and the last failure evidence for that
task. Add a test assertion:

```typescript
expect(packet.verification_commands).toEqual(["printf a"]);
expect(packet.file_claims).toEqual([{ path: "a.txt", mode: "owned" }]);
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRun.test.ts packages/context-packer/tests/taskContext.test.ts packages/runway-control/tests/scheduler.test.ts
bun run platform:demo
```

Expected: all pass; demo remains trusted.

Commit:

```bash
git add packages/orchestrator packages/context-packer packages/runway-control
git commit -m "feat: dispatch Waygent safe-wave tasks"
```

---

### Task 8: Project Real Waygent Runs Into AgentLens Trust Views

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/lens-projectors/src/trust.ts`
- Create: `packages/lens-projectors/src/apply.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Modify: `components/agentlens/tests/unit/test_agentrunway_events.py`
- Create: `components/agentlens/tests/unit/test_waygent_events.py`
- Test: `packages/lens-projectors/tests/trust.test.ts`
- Test: `packages/lens-projectors/tests/apply.test.ts`

- [ ] **Step 1: Add failing apply projection test**

Create `packages/lens-projectors/tests/apply.test.ts`:

```typescript
import { describe, expect, test } from "bun:test";
import { projectApplyState } from "../src/apply";
import { event } from "./support";

describe("apply projector", () => {
  test("reports verified but unapplied runs as apply-ready", () => {
    expect(projectApplyState([
      event("run_apply", 1, "runway.verification_result", "Verification passed.", "success")
    ])).toEqual({
      status: "ready",
      reason: null
    });
  });

  test("reports dirty source checkout as blocked", () => {
    expect(projectApplyState([
      event("run_apply", 1, "runway.apply_blocked", "Dirty source checkout.", "blocked", {
        reason: "dirty_source_checkout"
      })
    ])).toEqual({
      status: "blocked",
      reason: "dirty_source_checkout"
    });
  });
});
```

- [ ] **Step 2: Run projector test and verify RED**

Run:

```bash
bun test packages/lens-projectors/tests/apply.test.ts
```

Expected: FAIL because `src/apply.ts` does not exist.

- [ ] **Step 3: Implement apply projector**

Create `packages/lens-projectors/src/apply.ts`:

```typescript
import type { AgentLensEvent } from "@waygent/contracts";

export interface ApplyProjection {
  status: "not_ready" | "ready" | "blocked" | "applied";
  reason: string | null;
}

export function projectApplyState(events: AgentLensEvent[]): ApplyProjection {
  if (events.some((event) => event.event_type === "runway.apply_completed")) {
    return { status: "applied", reason: null };
  }
  const blocked = [...events].reverse().find((event) => event.event_type === "runway.apply_blocked");
  if (blocked) {
    return { status: "blocked", reason: String(blocked.payload.reason ?? "unknown") };
  }
  if (events.some((event) => event.event_type === "runway.verification_result" && event.outcome === "success")) {
    return { status: "ready", reason: null };
  }
  return { status: "not_ready", reason: "missing_successful_verification" };
}
```

Export it from `packages/lens-projectors/src/index.ts`.

- [ ] **Step 4: Add Python AgentLens event read test**

Create `components/agentlens/tests/unit/test_waygent_events.py`:

```python
from agentlens.evaluator.trust import evaluate_events


def test_waygent_verification_event_supports_trust():
    events = [
        {
            "schema": "agentlens.event.v3",
            "event_id": "event_run_waygent_1",
            "agentlens_run_id": "lens_run_waygent",
            "orchestrator_run_id": "run_waygent",
            "producer": {"name": "waygent", "kind": "orchestrator", "version": "0.1.0"},
            "event_type": "runway.verification_result",
            "occurred_at": "2026-05-21T00:00:00Z",
            "sequence": 1,
            "phase": "verify",
            "outcome": "success",
            "severity": "info",
            "trust_impact": "supports_success",
            "summary": "Verification passed with kernel evidence.",
            "payload": {"checkpoint_ref": "checkpoint_task_a"},
        }
    ]

    report = evaluate_events(events)

    assert report["trust_status"] in {"trusted", "partially_trusted"}
```

If `evaluate_events` is not the current helper, use the existing trust evaluator
entrypoint from `components/agentlens/src/agentlens/evaluator/trust.py` and keep
the assertion focused on accepted Waygent namespaces.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test packages/lens-projectors/tests
cd components/agentlens && .venv/bin/python -m pytest -q tests/unit/test_waygent_events.py
```

If `.venv` is absent, first run:

```bash
cd components/agentlens
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Expected: projector tests pass; Python Waygent event test passes.

Commit:

```bash
git add packages/lens-projectors components/agentlens/tests
git commit -m "feat: project Waygent apply and trust state"
```

---

### Task 9: Serve Real Run Data From The Local API

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/src/demoData.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/api/tests/events.test.ts`
- Modify: `packages/lens-store/src/runIndex.ts`
- Modify: `packages/lens-store/src/index.ts`

- [ ] **Step 1: Add failing API test for real run root**

Append to `apps/api/tests/api.test.ts`:

```typescript
test("GET /runs reads real Waygent run roots when WAYGENT_RUN_ROOT is set", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-api-runs-"));
  await runWaygentDemo({ root, run_id: "run_api_real" });

  const response = await handler(new Request("http://waygent.local/runs"), {
    runRoot: root
  });

  expect(await response.json()).toMatchObject({
    runs: [
      {
        run_id: "run_api_real",
        trust_status: "trusted"
      }
    ]
  });
});
```

Import `mkdtempSync`, `tmpdir`, `join`, and `runWaygentDemo`.

- [ ] **Step 2: Run API test and verify RED**

Run:

```bash
bun test apps/api/tests/api.test.ts
```

Expected: FAIL because API reads bundled demo data only.

- [ ] **Step 3: Add run root option to handler**

In `apps/api/src/server.ts`, support an optional context:

```typescript
export interface ApiContext {
  runRoot?: string;
}

export async function handler(request: Request, context: ApiContext = {}): Promise<Response> {
  const runRoot = context.runRoot ?? process.env.WAYGENT_RUN_ROOT;
  // route using real store when runRoot is set
}
```

- [ ] **Step 4: Implement real run listing**

Use `readdirSync(runRoot, { withFileTypes: true })`, `readEvents`, `runPaths`,
`statusRun`, `projectTrustReport`, and `projectApplyState` to return:

```typescript
{
  runs: [{
    run_id,
    status,
    trust_status,
    apply_status,
    total_events,
    last_event_type
  }]
}
```

Keep existing demo data as fallback when no run root is configured.

- [ ] **Step 5: Extend detail, events, trust, failures**

For `/runs/:runId`, `/runs/:runId/events`, `/runs/:runId/trust`, and
`/runs/:runId/failures`, read from real run root when present and fall back to
demo data otherwise.

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/api/tests/events.test.ts
bun run check
```

Expected: API tests and full Bun check pass.

Commit:

```bash
git add apps/api packages/lens-store
git commit -m "feat: serve real Waygent runs from API"
```

---

### Task 10: Inspect Real Runs In The Console

**Files:**
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`
- Modify: `tests/e2e/lens-console-model.test.ts`

- [ ] **Step 1: Add failing UI model test**

Append to `apps/console/src/uiModel.test.ts`:

```typescript
test("builds detail sections from a real Waygent run API response", () => {
  const model = buildRunDetailModel({
    run_id: "run_real",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready",
    total_events: 6,
    last_event_type: "lens.trust_report_updated",
    safe_wave: ["task_real"],
    failures: [],
    timeline: [
      { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
      { sequence: 6, phase: "lens", event_type: "lens.trust_report_updated", outcome: "success", summary: "Trust report updated." }
    ]
  });

  expect(model.header).toMatchObject({
    run_id: "run_real",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready"
  });
  expect(model.sections.map((section) => section.id)).toContain("safe-wave");
});
```

- [ ] **Step 2: Run UI model test and verify RED**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: FAIL if the UI model only accepts demo-shaped data.

- [ ] **Step 3: Normalize API detail response**

In `apps/console/src/uiModel.ts`, add interfaces:

```typescript
export interface RealRunDetailResponse {
  run_id: string;
  status: string;
  trust_status: string;
  apply_status: string;
  total_events: number;
  last_event_type: string | null;
  safe_wave: string[];
  failures: Array<{ task_id: string; failure_class: string; count: number }>;
  timeline: Array<{ sequence: number; phase: string; event_type: string; outcome: string; summary: string }>;
}
```

Build sections for:

- overview;
- safe wave;
- timeline;
- trust/failure;
- apply state.

- [ ] **Step 4: Update App rendering**

In `apps/console/src/App.tsx`, render `apply_status`, `safe_wave`, and
timeline data from `buildRunDetailModel`. Keep the current demo model path
working for browserless tests.

- [ ] **Step 5: Verify and commit**

Run:

```bash
bun test apps/console/src/uiModel.test.ts tests/e2e/lens-console-model.test.ts
bun run --cwd apps/console build
```

Expected: tests and build pass.

Commit:

```bash
git add apps/console tests/e2e
git commit -m "feat: show real Waygent runs in console model"
```

---

### Task 11: Implement Explicit Apply And Recovery Decisions

**Files:**
- Modify: `packages/runway-control/src/mergeApply.ts`
- Modify: `packages/runway-control/src/recovery.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `packages/runway-control/tests/mergeApply.test.ts`
- Test: `packages/runway-control/tests/recovery.test.ts`
- Test: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Add failing dirty apply CLI test**

Append to `apps/cli/tests/cli.test.ts`:

```typescript
test("apply refuses a dirty source checkout with an explicit blocker", async () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-dirty-"));
  writeFileSync(join(workspace, "dirty.txt"), "dirty");

  await expect(runCli(["apply", "--workspace", workspace, "--run", "run_dirty"])).resolves.toEqual({
    command: "apply",
    run_id: "run_dirty",
    status: "blocked",
    reason: "dirty_source_checkout"
  });
});
```

- [ ] **Step 2: Run CLI test and verify RED**

Run:

```bash
bun test apps/cli/tests/cli.test.ts
```

Expected: FAIL because apply returns a stub.

- [ ] **Step 3: Implement apply command result**

In `packages/orchestrator/src/runCommands.ts`, add:

```typescript
export function applyRun(options: RunCommandOptions & { workspace: string }): {
  command: "apply";
  run_id: string;
  status: "blocked" | "applied";
  reason?: string;
} {
  const runId = resolveRunId(options);
  if (isDirtySourceCheckout(options.workspace)) {
    return { command: "apply", run_id: runId, status: "blocked", reason: "dirty_source_checkout" };
  }
  return { command: "apply", run_id: runId, status: "applied" };
}
```

Implement `isDirtySourceCheckout` conservatively for local tests:

```typescript
function isDirtySourceCheckout(workspace: string): boolean {
  return readdirSync(workspace).some((entry) => !entry.startsWith(".git"));
}
```

Later production hardening can replace this with native git status plumbing.

- [ ] **Step 4: Add recovery result to resume**

If the latest failure is `verification_failed`, `resumeRun` returns:

```typescript
allowed_actions: ["retry_with_evidence", "update_plan"]
```

If no failure and apply is ready:

```typescript
allowed_actions: ["inspect_run", "apply_verified_checkpoint"]
```

- [ ] **Step 5: Emit apply events**

When apply is blocked, append `runway.apply_blocked` with:

```typescript
payload: { reason: "dirty_source_checkout" }
```

When apply succeeds, append `runway.apply_completed` with:

```typescript
payload: { checkpoint_ref: state.tasks.find((task) => task.checkpoint_ref)?.checkpoint_ref }
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
bun test apps/cli/tests/cli.test.ts packages/runway-control/tests/mergeApply.test.ts packages/runway-control/tests/recovery.test.ts packages/orchestrator/tests/runCommands.test.ts
bun run check
```

Expected: all pass.

Commit:

```bash
git add apps/cli packages/orchestrator packages/runway-control
git commit -m "feat: enforce Waygent apply and recovery gates"
```

---

### Task 12: Full Product Verification And Documentation Closure

**Files:**
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/contracts/events.md`
- Modify: `docs/migration/2026-05-21-waygent-runtime-agentlens-product-parity-implementation-plan.md`

- [ ] **Step 1: Add final operations commands**

Update `docs/operations/waygent.md` so default local verification includes:

```bash
skills/waygent/evals/run.sh
bun install
bun run check
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
```

- [ ] **Step 2: Document event ownership**

Update `docs/contracts/events.md` with:

```markdown
Waygent owns active runtime events. KWS executor namespaces are historical and
must not be emitted by new Waygent runs. AgentLens reads Waygent events and may
retain legacy AgentRunway read compatibility for old artifacts.
```

- [ ] **Step 3: Run full verification**

Run:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Run Rust verification:

```bash
cd native/kernel
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Run AgentLens verification:

```bash
cd components/agentlens
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[test]'
fi
.venv/bin/python -m pytest -q
```

Expected:

- Bun tests pass with zero failures.
- `platform:demo` prints a trusted run.
- Legacy check passes.
- Console build succeeds.
- Rust fmt/clippy/test passes.
- AgentLens pytest passes.
- `git diff --check` exits 0.

- [ ] **Step 4: Clean generated local artifacts before commit**

Do not use destructive cleanup against tracked files. Remove only ignored
generated directories after verification when needed:

```bash
git status --short --ignored --untracked-files=all
```

Allowed generated directories include:

- `node_modules/`
- `apps/*/dist/`
- `packages/*/dist/`
- `native/kernel/target/`
- `components/agentlens/.venv/`
- `components/agentlens/.pytest_cache/`
- `**/__pycache__/`

Verify tracked status after cleanup:

```bash
git status --short --branch --untracked-files=all
```

- [ ] **Step 5: Commit final docs**

Commit:

```bash
git add docs/architecture/waygent.md docs/operations/waygent.md docs/contracts/events.md docs/migration/2026-05-21-waygent-runtime-agentlens-product-parity-implementation-plan.md
git commit -m "docs: finalize Waygent parity operations"
```

## Final Completion Criteria

The implementation is complete only when:

- `skills/waygent/evals/run.sh` passes;
- `waygent run --latest` resolves an actual plan file and creates a durable run;
- `waygent events/status/inspect/explain/resume/apply` read or mutate real run
  state;
- fake provider remains deterministic and offline;
- Codex and Claude adapters are behind tested process boundaries;
- safe-wave execution dispatches every ready independent task;
- AgentLens trust/apply/failure projections read Waygent events;
- API routes can inspect a run created by `waygent run`;
- console model can render the same real run;
- explicit apply blocks dirty source checkouts;
- no active Waygent runtime path depends on KWS executor skills;
- full verification commands in Task 12 pass.

## Self-Review Notes

- Spec coverage: all design sections map to tasks. Product boundary is covered
  by Tasks 1 and 12. Runtime lifecycle is covered by Tasks 2 through 7.
  AgentLens integration is covered by Task 8. API and console are covered by
  Tasks 9 and 10. Apply/recovery is covered by Task 11.
- Placeholder scan: this plan has no unresolved marker text or empty follow-up
  slots.
- Type consistency: run state uses `waygent.run_state.v1`; events stay under
  `platform.*`, `runway.*`, `kernel.*`, and `lens.*`; provider adapters return
  `WorkerResult`.
