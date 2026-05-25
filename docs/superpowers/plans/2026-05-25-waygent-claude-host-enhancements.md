# Waygent — Claude Host Execution Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between the Codex and Claude provider adapters in Waygent: honest capability manifest, role-aware CLI args, stream-json output with first-class parsing, prompt-caching-friendly prompt split, and resumable retries.

**Architecture:** Four sequential phases that each ship independently. All changes live in `packages/provider-adapters/src/` and a few orchestrator wiring points. No new files outside fixtures and tests. Existing test patterns (`bun:test`, `normalizeProcessOutput`, fenced-JSON fixtures) extended; no new test framework or runner.

**Tech Stack:** TypeScript, Bun, `@waygent/contracts` runtime, `claude` CLI (`-p`, `--output-format stream-json`, `--append-system-prompt`, `--session-id`, `--resume`, `--settings`, `--mcp-config`, `--allowedTools`, `--disallowedTools`, `--permission-mode`).

**Spec:** `docs/superpowers/specs/2026-05-25-waygent-claude-host-enhancements-design.md`

---

```yaml waygent-task
id: task_claude_host_enhancements
title: Implement Claude host execution enhancements across four phases (honest capability manifest and role-aware Claude CLI args, stream-json output with first-class result parsing, prompt split with --append-system-prompt + --settings/--mcp-config pass-through + nested host env sanitize, session resume + retry context wiring) per docs/superpowers/specs/2026-05-25-waygent-claude-host-enhancements-design.md without weakening apply readiness.
dependencies: []
file_claims:
  - path: packages/provider-adapters/src/capabilities.ts
    mode: owned
  - path: packages/provider-adapters/src/types.ts
    mode: owned
  - path: packages/provider-adapters/src/processAdapters.ts
    mode: owned
  - path: packages/provider-adapters/src/claudeAdapter.ts
    mode: owned
  - path: packages/provider-adapters/tests/manifest.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/claudeAdapter.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/streamJson.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/usageExtraction.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/envSanitize.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/fixtures/claude/stream_json_success.jsonl
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/claudeResume.test.ts
    mode: owned
risk: high
verify_isolation: isolated
verify:
  - bun run typecheck
  - bun test packages/provider-adapters/tests
  - bun test packages/orchestrator/tests
```

---

## Conventions

- Bun is the package manager and test runner. Run tests with `bun test <path>`.
- Run from repo root unless a task specifies `cd <subpath>`.
- All commits must include the trailer
  `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` (per repo policy in `CLAUDE.md`).
- Roles use the `ProviderRole` enum from `packages/contracts/src/types.ts:63`:
  `"implement" | "review" | "fix" | "verify_assist"`.
- Each task ends with a commit. Keep commits small and reversible.
- Run `bun run check` once at the end of each phase as the integrative regression gate.

---

## File Map

Each phase touches a small set of files:

| File | Phase | Responsibility |
|---|---|---|
| `packages/provider-adapters/src/capabilities.ts` | 1, 2 | Per-provider capability manifest (claude split from codex; flip `streaming` in P2) |
| `packages/provider-adapters/src/types.ts` | 1, 3, 4 | `ProviderProcessOptions` extensions: `timeout_ms_by_role`, `settings_path`, `mcp_config_path`, `session_id`, `resume_session_id`; `AdapterRequest` retry context |
| `packages/provider-adapters/src/processAdapters.ts` | 1, 2, 3, 4 | `providerProcessArgs`, `runProviderProcess`, `normalizeProcessOutput`, `parseWorkerOutput`, `buildProviderPrompt` (split), env sanitize |
| `packages/provider-adapters/src/claudeAdapter.ts` | 2 | Default args switch to stream-json |
| `packages/provider-adapters/tests/claudeAdapter.test.ts` | 1, 3, 4 | Args / role / system-prompt / session tests |
| `packages/provider-adapters/tests/usageExtraction.test.ts` | 2 | model attestation precedence test |
| `packages/provider-adapters/tests/streamJson.test.ts` (new) | 2 | JSONL parsing + event_stream capture |
| `packages/provider-adapters/tests/fixtures/claude/` (new) | 2 | JSONL fixture for stream-json |
| `packages/provider-adapters/tests/manifest.test.ts` (new) | 1, 2 | Capability manifest lock tests |
| `packages/provider-adapters/tests/envSanitize.test.ts` (new) | 3 | Child env strip |
| `packages/orchestrator/src/orchestrator.ts` | 2 | `resolveProviderProcesses` Claude default args updated |
| `packages/orchestrator/src/taskExecutor.ts` | 4 | Retry path sets `resume_session_id` |

---

# Phase 1 — Truth & Role-aware Foundation

Phase 1 split-out goal: Honest capability manifest + role-aware Claude CLI args + per-role timeout, with no behavior change for the `implement` role that the orchestrator actually uses today.

### Step 1.1: Split `claudeCapabilityManifest` from `codexCapabilityManifest`

**Files:**
- Modify: `packages/provider-adapters/src/capabilities.ts`
- Create: `packages/provider-adapters/tests/manifest.test.ts`

- [x] **Step 1: Write the failing test**

Create `packages/provider-adapters/tests/manifest.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { claudeCapabilityManifest, codexCapabilityManifest } from "../src/capabilities";

describe("claudeCapabilityManifest (Phase 1: honest manifest)", () => {
  test("is not object-equal to codexCapabilityManifest", () => {
    expect(claudeCapabilityManifest).not.toEqual(codexCapabilityManifest);
  });

  test("reports provider claude with non-streaming, no approvals", () => {
    expect(claudeCapabilityManifest.provider).toBe("claude");
    expect(claudeCapabilityManifest.streaming).toBe(false);
    expect(claudeCapabilityManifest.approvals).toBe(false);
  });

  test("retains tool_calls, file_edits, shell, all supported_modes, result_schema", () => {
    expect(claudeCapabilityManifest.tool_calls).toBe(true);
    expect(claudeCapabilityManifest.file_edits).toBe(true);
    expect(claudeCapabilityManifest.shell).toBe(true);
    expect(claudeCapabilityManifest.supported_modes).toEqual([
      "single-agent",
      "multi-agent",
      "review",
      "verify"
    ]);
    expect(claudeCapabilityManifest.result_schema).toBe("runway.worker_result.v1");
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `bun test packages/provider-adapters/tests/manifest.test.ts`
Expected: FAIL — `streaming` is `true` and `approvals` is `true` (currently copied from codex).

- [x] **Step 3: Edit `capabilities.ts` to split the manifest**

In `packages/provider-adapters/src/capabilities.ts`, replace:

```ts
export const claudeCapabilityManifest: ProviderCapabilityManifest = {
  ...codexCapabilityManifest,
  provider: "claude"
};
```

with:

```ts
export const claudeCapabilityManifest: ProviderCapabilityManifest = {
  schema: "provider.capability_manifest.v1",
  provider: "claude",
  supported_modes: ["single-agent", "multi-agent", "review", "verify"],
  tool_calls: true,
  file_edits: true,
  shell: true,
  streaming: false,
  approvals: false,
  result_schema: "runway.worker_result.v1"
};
```

- [x] **Step 4: Run test to verify it passes**

Run: `bun test packages/provider-adapters/tests/manifest.test.ts`
Expected: PASS (3 tests).

- [x] **Step 5: Run package tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: All tests PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/capabilities.ts packages/provider-adapters/tests/manifest.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): split claudeCapabilityManifest from codex copy

Honest reporting: streaming=false, approvals=false. Other fields
preserved verbatim from the prior shared shape.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 1.2: Add `timeout_ms_by_role` to `ProviderProcessOptions`

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts:144` (timeout resolution site)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts` (append timeout test)

- [x] **Step 1: Write the failing test**

Append to `packages/provider-adapters/tests/claudeAdapter.test.ts` inside the existing `describe("Claude adapter normalization", ...)` block:

```ts
test("per-role timeout override applies before scalar timeout_ms (Phase 1)", async () => {
  // A bun -e script that sleeps for 500ms; with a 50ms timeout it must be killed.
  const script = `await new Promise(r => setTimeout(r, 500)); console.log('{}');`;
  const result = await new ClaudeProviderAdapter({
    executable: process.execPath,
    args: ["-e", script],
    timeout_ms: 5_000,
    timeout_ms_by_role: { implement: 50 }
  }).run({
    task_id: "t",
    candidate_id: "c",
    role: "implement",
    prompt: "p"
  });
  expect(result.worker.failure_class).toBe("timeout");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL — `timeout_ms_by_role` is not a known option; the 5_000 ms timeout wins and the test sleeps to completion.

- [x] **Step 3: Extend the type**

In `packages/provider-adapters/src/types.ts`, change:

```ts
export interface ProviderProcessOptions {
  executable: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeout_ms?: number;
  model?: string;
  effort?: string;
}
```

to:

```ts
import type { ModelAttestation, ProviderCapabilityManifest, ProviderRole, TokenUsage, UsageSource, WorkerResult } from "@waygent/contracts";

export interface ProviderProcessOptions {
  executable: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeout_ms?: number;
  timeout_ms_by_role?: Partial<Record<ProviderRole, number>>;
  model?: string;
  effort?: string;
}
```

(The `ProviderRole` import already exists at the top of the file — verify it; if not, add `ProviderRole` to the import list.)

- [x] **Step 4: Resolve role-aware timeout in `runProviderProcess`**

In `packages/provider-adapters/src/processAdapters.ts`, find the line:

```ts
const timeout = setTimeout(() => {
  timedOut = true;
  child.kill("SIGTERM");
}, options.timeout_ms ?? defaultTimeoutMs);
```

Replace with:

```ts
const resolvedTimeoutMs = resolveRoleTimeout(options, request.role) ?? options.timeout_ms ?? defaultTimeoutMs;
const timeout = setTimeout(() => {
  timedOut = true;
  child.kill("SIGTERM");
}, resolvedTimeoutMs);
```

Also update the timeout failure summary string below (`${options.timeout_ms ?? defaultTimeoutMs}ms`) to use `${resolvedTimeoutMs}ms`.

Add this helper near the top of the file (after `defaultTimeoutMs`):

```ts
function resolveRoleTimeout(options: ProviderProcessOptions, role: ProviderRole | undefined): number | undefined {
  if (!role || !options.timeout_ms_by_role) return undefined;
  return options.timeout_ms_by_role[role];
}
```

Import `ProviderRole` from `@waygent/contracts` at the top of the file.

- [x] **Step 5: Run test to verify it passes**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: PASS, including the new timeout test.

- [x] **Step 6: Run full package tests**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): per-role timeout override (timeout_ms_by_role)

Resolution order: role override → timeout_ms → 30 min default.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 1.3: Role-aware Claude args in `providerProcessArgs`

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`providerProcessArgs`)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [x] **Step 1: Write the failing tests**

Append to `packages/provider-adapters/tests/claudeAdapter.test.ts`:

```ts
describe("Phase 1 — role-aware Claude args", () => {
  function claudeArgs(role: "implement" | "review" | "fix" | "verify_assist" | undefined) {
    return providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p", "--output-format", "json"] },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", role, prompt: "p" }
    );
  }

  test("implement uses acceptEdits (existing default)", () => {
    const args = claudeArgs("implement");
    expect(args).toContain("--permission-mode");
    expect(args).toContain("acceptEdits");
    expect(args).not.toContain("plan");
    expect(args).not.toContain("--disallowedTools");
    expect(args).not.toContain("--allowedTools");
  });

  test("undefined role behaves like implement (no warning surface)", () => {
    const args = claudeArgs(undefined);
    expect(args).toContain("acceptEdits");
  });

  test("fix mirrors implement", () => {
    const args = claudeArgs("fix");
    expect(args).toContain("acceptEdits");
    expect(args).not.toContain("--disallowedTools");
  });

  test("review uses plan mode and blocks edit tools but keeps Bash", () => {
    const args = claudeArgs("review");
    expect(args).toContain("--permission-mode");
    expect(args).toContain("plan");
    expect(args).not.toContain("acceptEdits");
    const idx = args.indexOf("--disallowedTools");
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(args[idx + 1]).toBe("Edit,Write,MultiEdit");
  });

  test("verify_assist uses acceptEdits with allowedTools restricted to inspection+shell", () => {
    const args = claudeArgs("verify_assist");
    expect(args).toContain("--permission-mode");
    expect(args).toContain("acceptEdits");
    const idx = args.indexOf("--allowedTools");
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(args[idx + 1]).toBe("Bash,Read,Glob,Grep");
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: 4 FAIL (the `implement`/`undefined` tests pass).

- [x] **Step 3: Branch on role inside `providerProcessArgs`**

In `packages/provider-adapters/src/processAdapters.ts`, locate the existing Claude branch (currently injecting `--add-dir` and `--permission-mode acceptEdits`). Replace the `if (provider === "claude") { ... }` block with the version below. Keep model/effort handling intact at the end.

```ts
if (provider === "claude") {
  const nextArgs = [...args];
  const isClaudeCli = isProviderCliExecutable("claude", options.executable);
  if (isClaudeCli) {
    if (cwd && !nextArgs.includes("--add-dir")) {
      const allowedDirs = [cwd];
      if (request.task_packet_path) allowedDirs.push(dirname(request.task_packet_path));
      nextArgs.unshift("--add-dir", ...allowedDirs);
    }
    const rolePolicy = claudeRolePolicy(request.role);
    if (!nextArgs.includes("--permission-mode")) {
      nextArgs.unshift("--permission-mode", rolePolicy.permission_mode);
    }
    if (rolePolicy.disallowed_tools && !nextArgs.includes("--disallowedTools")) {
      nextArgs.unshift("--disallowedTools", rolePolicy.disallowed_tools);
    }
    if (rolePolicy.allowed_tools && !nextArgs.includes("--allowedTools")) {
      nextArgs.unshift("--allowedTools", rolePolicy.allowed_tools);
    }
  }
  if (isClaudeCli && options.effort && !nextArgs.includes("--effort")) {
    nextArgs.unshift("--effort", options.effort);
  }
  if (isClaudeCli && options.model && !nextArgs.includes("--model")) {
    nextArgs.unshift("--model", options.model);
  }
  return nextArgs;
}
```

Add the helper above (near `isProviderCliExecutable`):

```ts
interface ClaudeRolePolicy {
  permission_mode: "acceptEdits" | "plan";
  allowed_tools?: string;
  disallowed_tools?: string;
}

function claudeRolePolicy(role: ProviderRole | undefined): ClaudeRolePolicy {
  switch (role) {
    case "review":
      return { permission_mode: "plan", disallowed_tools: "Edit,Write,MultiEdit" };
    case "verify_assist":
      return { permission_mode: "acceptEdits", allowed_tools: "Bash,Read,Glob,Grep" };
    case "implement":
    case "fix":
    case undefined:
      return { permission_mode: "acceptEdits" };
    default:
      return { permission_mode: "acceptEdits" };
  }
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: all PASS, including the four new role tests AND the existing `implement` regression tests.

- [x] **Step 5: Full package test**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): role-aware Claude permission/tool args

review → plan mode + disallowedTools edit set; verify_assist →
acceptEdits + allowedTools inspection+Bash; implement/fix preserved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 1.4: Phase 1 integration gate

- [x] **Step 1: Run full repo check**

Run: `bun run check`
Expected: all packages green.

- [x] **Step 2: Run waygent scenarios**

Run: `bun run waygent:scenarios`
Expected: green (no regression on implement-role behavior).

- [x] **Step 3: Run platform demo**

Run: `bun run platform:demo`
Expected: green.

- [x] **Step 4: Patch hygiene**

Run: `git diff --check`
Expected: empty (no trailing whitespace).

---

# Phase 2 — Streaming & 견고한 파싱

Phase 2 goal: Switch the Claude default to stream-json, persist the JSONL into `event_stream`, parse the `result` event as a first-class path, and promote `system.init.model` to the primary attestation source. Flip `claudeCapabilityManifest.streaming` to `true` once the change actually streams.

### Step 2.1: Fixture for Claude stream-json output

**Files:**
- Create: `packages/provider-adapters/tests/fixtures/claude/stream_json_success.jsonl`

- [x] **Step 1: Create the fixture**

Write `packages/provider-adapters/tests/fixtures/claude/stream_json_success.jsonl` with one JSON object per line (no trailing newline issues):

```jsonl
{"type":"system","subtype":"init","session_id":"test-session-abc","model":"claude-opus-4-7","tools":["Read","Edit","Bash"]}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Inspecting the worktree…"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Applying patch…"}]}}
{"type":"result","subtype":"success","session_id":"test-session-abc","model":"claude-opus-4-7","result":"```json\n{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"task_stream\",\"candidate_id\":\"candidate_stream\",\"status\":\"completed\",\"changed_files\":[\"a.ts\"],\"summary\":\"stream-json success\",\"evidence\":{}}\n```","usage":{"input_tokens":1000,"output_tokens":200,"cache_read_input_tokens":600,"cache_creation_input_tokens":50},"modelUsage":{"claude-opus-4-7":{"duration_ms":1200}}}
```

- [x] **Step 2: Sanity-load the fixture**

Run: `bun -e 'console.log(require("fs").readFileSync("packages/provider-adapters/tests/fixtures/claude/stream_json_success.jsonl","utf8").split("\n").filter(Boolean).map(l => JSON.parse(l).type))'`
Expected output: `[ "system", "assistant", "assistant", "result" ]`

- [x] **Step 3: Commit the fixture**

```bash
git add packages/provider-adapters/tests/fixtures/claude/stream_json_success.jsonl
git commit -m "$(cat <<'EOF'
test(provider-adapters): add Claude stream-json success fixture

Four-line JSONL: system.init (session_id + model), two assistant
messages, terminal result with usage + modelUsage.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 2.2: `event_stream` capture for stream-json args

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`runProviderProcess`)
- Create: `packages/provider-adapters/tests/streamJson.test.ts`

- [x] **Step 1: Write the failing test**

Create `packages/provider-adapters/tests/streamJson.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ClaudeProviderAdapter } from "../src";

const fixturePath = join(import.meta.dir, "fixtures/claude/stream_json_success.jsonl");

describe("Phase 2 — Claude stream-json capture", () => {
  test("preserves JSONL into process.event_stream when --output-format stream-json is used", async () => {
    // Print the fixture to stdout to simulate the Claude CLI in stream-json mode.
    const script = `process.stdout.write(require("fs").readFileSync(${JSON.stringify(fixturePath)}, "utf8"));`;
    const result = await new ClaudeProviderAdapter({
      executable: process.execPath,
      args: ["-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose", "-e", script]
    }).run({
      task_id: "task_stream",
      candidate_id: "candidate_stream",
      prompt: "demo"
    });
    expect(result.process.event_stream).not.toBeNull();
    expect(result.process.event_stream).toContain('"type":"system"');
    expect(result.process.event_stream).toContain('"type":"result"');
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("stream-json success");
  });
});
```

Note: the script uses `-e` so bun runs the inline code; the prepended args (`-p`, `--output-format stream-json`, etc.) get ignored by bun but they must be on `options.args` so the adapter's stream-json detection kicks in.

- [x] **Step 2: Run the test to verify it fails**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: FAIL — `event_stream` is currently always `null`.

- [x] **Step 3: Implement stream-json detection + persistence**

In `packages/provider-adapters/src/processAdapters.ts`, inside `runProviderProcess`, after computing the resolved args (and before the `child.on("close", ...)` block), detect stream-json mode:

```ts
const adapterArgs = providerProcessArgs(provider, options, cwd, request);
const streamJson = adapterArgs.includes("stream-json");
```

(If the function does not currently capture the resolved args in a local variable, hoist them — the `spawn` call already calls `providerProcessArgs` inline; pull it out so we can also inspect it.)

Modify the `child.on("close", ...)` handler so that when `streamJson` is true and exit code is 0 (or with output present), we pass the raw stdout through `eventStream`:

```ts
finish(
  normalizeProcessOutput(provider, request.task_id, request.candidate_id, {
    exitCode: code ?? 1,
    stdout,
    stderr,
    timedOut: false,
    startedAt,
    completedAt,
    eventStream: streamJson ? stdout : null
  })
);
```

Do the same for the timed-out branch:

```ts
finish(
  withProcessEvidence(failed(request.task_id, request.candidate_id, "timeout", `${provider} timed out after ${resolvedTimeoutMs}ms`), {
    exitCode: code,
    stdout,
    stderr,
    timedOut: true,
    startedAt,
    completedAt,
    eventStream: streamJson ? stdout : null
  })
);
```

- [x] **Step 4: Run the test to verify it passes**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: PASS.

- [x] **Step 5: Full package test**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/streamJson.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): persist JSONL into event_stream for stream-json

Detect Claude --output-format stream-json from the resolved args and
hand the raw stdout through as the event_stream payload, replacing the
prior unconditional null.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 2.3: First-class `result`-event parsing path

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`parseWorkerOutput`)
- Modify: `packages/provider-adapters/tests/streamJson.test.ts` (extend)

- [x] **Step 1: Add the failing test**

Append to `packages/provider-adapters/tests/streamJson.test.ts`:

```ts
import { normalizeProcessOutput } from "../src/processAdapters";

describe("Phase 2 — Claude stream-json parsing", () => {
  test("prefers the last result event over earlier fenced JSON in assistant messages", () => {
    // assistant message contains a fenced JSON that says failed; result event says completed.
    const earlierAssistant = {
      type: "assistant",
      message: { role: "assistant", content: [{ type: "text", text: "```json\n{\"status\":\"failed\",\"changed_files\":[],\"summary\":\"old\",\"evidence\":{}}\n```" }] }
    };
    const finalResult = {
      type: "result",
      subtype: "success",
      session_id: "s-1",
      model: "claude-opus-4-7",
      result: "```json\n{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"task_p\",\"candidate_id\":\"candidate_p\",\"status\":\"completed\",\"changed_files\":[\"x.ts\"],\"summary\":\"new\",\"evidence\":{}}\n```"
    };
    const stdout = [JSON.stringify(earlierAssistant), JSON.stringify(finalResult)].join("\n") + "\n";
    const r = normalizeProcessOutput("claude", "task_p", "candidate_p", { exitCode: 0, stdout, stderr: "" });
    expect(r.worker.status).toBe("completed");
    expect(r.worker.summary).toBe("new");
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: FAIL — current parser walks lines in reverse first and may take the earlier assistant fence depending on order, or the assertion may otherwise mismatch. Confirm the failure mode before fixing.

- [x] **Step 3: Implement the priority path**

In `packages/provider-adapters/src/processAdapters.ts`, modify `parseWorkerOutput` to prefer the last JSON line whose `type === "result"`:

```ts
function parseWorkerOutput(stdout: string): { unwrapped: unknown; envelope: unknown | null } {
  const trimmed = stdout.trim();
  const lines = trimmed.split(/\r?\n/).map(l => l.trim()).filter(Boolean);

  // 1. Stream-json priority: scan from the end for type:"result" lines.
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const parsed = parseJsonText(lines[i]);
    if (!parsed || typeof parsed !== "object") continue;
    if ((parsed as Record<string, unknown>).type !== "result") continue;
    const unwrapped = unwrapProviderEnvelope(parsed);
    if (isWorkerResultCandidate(unwrapped)) {
      return { unwrapped, envelope: parsed };
    }
  }

  // 2. Existing reverse-line fallback (covers single-blob json + assistant fences).
  const candidates = [trimmed, ...lines.slice().reverse()];
  for (const candidate of candidates) {
    const parsed = parseJsonText(candidate);
    if (!parsed) continue;
    const unwrapped = unwrapProviderEnvelope(parsed);
    if (isWorkerResultCandidate(unwrapped)) {
      const envelope = unwrapped !== parsed && parsed && typeof parsed === "object" ? parsed : null;
      return { unwrapped, envelope };
    }
  }

  throw new Error("missing worker result JSON");
}
```

- [x] **Step 4: Run the test to verify it passes**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: PASS.

- [x] **Step 5: Run all parsing-related tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS, including `usageExtraction.test.ts` and `claudeAdapter.test.ts`.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/streamJson.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): first-class type:result parser path

Walk lines in reverse and prefer the last result event before falling
back to the existing fence/brace heuristics.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 2.4: `system.init.model` as primary attestation source

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`modelFromEnvelope` and `metadataFromParsed`)
- Modify: `packages/provider-adapters/tests/usageExtraction.test.ts` (append test)

- [x] **Step 1: Write the failing test**

Append to `packages/provider-adapters/tests/usageExtraction.test.ts`:

```ts
test("system.init.model wins over modelUsage keys[0] when stream-json is present", () => {
  const initLine = { type: "system", subtype: "init", session_id: "s", model: "claude-opus-4-7" };
  const resultLine = {
    type: "result",
    subtype: "success",
    session_id: "s",
    result: "```json\n{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"t\",\"candidate_id\":\"c\",\"status\":\"completed\",\"changed_files\":[],\"summary\":\"ok\",\"evidence\":{}}\n```",
    modelUsage: { "claude-different-model": { duration_ms: 1 } }
  };
  const stdout = [JSON.stringify(initLine), JSON.stringify(resultLine)].join("\n") + "\n";
  const result = normalizeProcessOutput("claude", "t", "c", { exitCode: 0, stdout, stderr: "", eventStream: stdout });
  expect(result.metadata?.actual_model.model).toBe("claude-opus-4-7");
  expect(result.metadata?.actual_model.source).toBe("provider_json");
});
```

- [x] **Step 2: Run to verify it fails**

Run: `bun test packages/provider-adapters/tests/usageExtraction.test.ts`
Expected: FAIL — `modelUsage` keys[0] wins and returns `claude-different-model`.

- [x] **Step 3: Plumb event-stream-aware attestation**

The current code path doesn't have access to the JSONL when computing `metadataFromParsed`. Pass it in.

In `processAdapters.ts`:

- Change `normalizeProcessOutput` to thread `output.eventStream ?? null` into `metadataFromParsed`:

```ts
const metadata = metadataFromParsed(provider, parsed, envelope, output.eventStream ?? null);
```

- Change the signature:

```ts
function metadataFromParsed(
  provider: "codex" | "claude" | "acp",
  parsed: Partial<WorkerResult>,
  envelope: unknown | null,
  eventStreamText: string | null
): ProviderRunMetadata {
  const evidence = parsed.evidence && typeof parsed.evidence === "object" ? parsed.evidence as Record<string, unknown> : {};
  const envelopeUsage = usageFromEnvelope(envelope);
  const evidenceUsage = usageFromEvidence(evidence);
  const usage = envelopeUsage ?? evidenceUsage ?? null;
  const usage_source: UsageSource = envelopeUsage
    ? "provider_json"
    : usageSourceFromEvidence(evidence, provider);
  const streamInitModel = modelFromStreamInit(eventStreamText);
  const envelopeModel = modelFromEnvelope(envelope, provider);
  const evidenceModel = actualModelFromEvidence(evidence);
  const actual_model = evidenceModel.model
    ? evidenceModel
    : (streamInitModel ?? envelopeModel ?? evidenceModel);
  return { actual_model, usage, usage_source };
}
```

- Add a helper:

```ts
function modelFromStreamInit(eventStreamText: string | null): ModelAttestation | null {
  if (!eventStreamText) return null;
  const lines = eventStreamText.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parsed = parseJsonText(trimmed);
    if (!parsed || typeof parsed !== "object") continue;
    const record = parsed as Record<string, unknown>;
    if (record.type === "system" && record.subtype === "init" && typeof record.model === "string" && record.model.length > 0) {
      return { model: record.model, reasoning: null, source: "provider_json" };
    }
  }
  return null;
}
```

The precedence is: evidence-self-report (worker_result) → stream init → envelope `modelUsage`/`model` → unknown.

- [x] **Step 4: Run the test to verify it passes**

Run: `bun test packages/provider-adapters/tests/usageExtraction.test.ts`
Expected: all PASS, including the new precedence test and the existing tests (which do not set a stream init and so still resolve to `modelUsage` or evidence as before).

- [x] **Step 5: Full package test**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/usageExtraction.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): prefer system.init.model for attestation

Precedence: worker_result evidence > stream-json system.init >
envelope modelUsage > unknown.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 2.5: Switch Claude default args to stream-json + flip `streaming` to true

**Files:**
- Modify: `packages/provider-adapters/src/claudeAdapter.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts:1135` (`resolveProviderProcesses` Claude defaults)
- Modify: `packages/provider-adapters/src/capabilities.ts` (`claudeCapabilityManifest.streaming`)
- Modify: `packages/provider-adapters/tests/manifest.test.ts`
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts` (existing args test that hard-codes `["-p", "--output-format", "json"]`)

- [x] **Step 1: Update the manifest lock test**

In `packages/provider-adapters/tests/manifest.test.ts`, change `expect(claudeCapabilityManifest.streaming).toBe(false);` to `expect(claudeCapabilityManifest.streaming).toBe(true);`.

- [x] **Step 2: Run to verify it fails**

Run: `bun test packages/provider-adapters/tests/manifest.test.ts`
Expected: FAIL on the streaming assertion.

- [x] **Step 3: Flip the manifest**

In `packages/provider-adapters/src/capabilities.ts`, change `streaming: false` to `streaming: true` in `claudeCapabilityManifest`.

- [x] **Step 4: Run to verify the manifest test passes**

Run: `bun test packages/provider-adapters/tests/manifest.test.ts`
Expected: PASS.

- [x] **Step 5: Update Claude adapter defaults**

In `packages/provider-adapters/src/claudeAdapter.ts`, change:

```ts
constructor(private readonly options: ProviderProcessOptions = { executable: "claude", args: ["-p", "--output-format", "json"] }) {}
```

to:

```ts
constructor(
  private readonly options: ProviderProcessOptions = {
    executable: "claude",
    args: ["-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose"]
  }
) {}
```

- [x] **Step 6: Update orchestrator default**

In `packages/orchestrator/src/orchestrator.ts`, find the Claude branch:

```ts
args: userClaude?.args ?? ["-p", "--output-format", "json"],
```

Change to:

```ts
args: userClaude?.args ?? ["-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose"],
```

- [x] **Step 7: Fix the now-stale claudeAdapter test arg expectation**

In `packages/provider-adapters/tests/claudeAdapter.test.ts`, the test "prepends --model and --effort to claude args when set" passes args `["-p", "--output-format", "json"]` explicitly. That call still works because the test passes its own args; do not change it. But the test "preserves provider supplied failure_class from fenced Claude JSON" and other parsing tests use direct JSON output paths — leave them alone too. The only change needed here is verifying nothing test-side broke. Re-run all adapter tests below.

- [x] **Step 8: Run package tests**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 9: Run orchestrator tests**

Run: `cd packages/orchestrator && bun test`
Expected: all PASS.

- [x] **Step 10: Commit**

```bash
git add packages/provider-adapters/src/claudeAdapter.ts packages/provider-adapters/src/capabilities.ts packages/provider-adapters/tests/manifest.test.ts packages/orchestrator/src/orchestrator.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters,orchestrator): default Claude args to stream-json

claude -p --output-format stream-json --include-partial-messages
--verbose. claudeCapabilityManifest.streaming flipped to true now that
the path actually streams.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 2.6: Phase 2 integration gate

- [x] **Step 1: Run `bun run check`**

Run: `bun run check`
Expected: green.

- [x] **Step 2: Run scenarios + platform demo**

Run: `bun run waygent:scenarios && bun run platform:demo`
Expected: green.

- [x] **Step 3: `git diff --check`**

Run: `git diff --check`
Expected: empty.

---

# Phase 3 — Caching & Prompt 구조화

Phase 3 goal: Split the prompt into a stable per-role system prompt (delivered via `--append-system-prompt`) plus a per-task user prompt (stdin). Add `--settings` and `--mcp-config` pass-through. Sanitize nested Claude Code host env.

### Step 3.1: Split `buildProviderPrompt` into system + user halves

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`buildProviderPrompt`)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [x] **Step 1: Write the failing test**

Append to `packages/provider-adapters/tests/claudeAdapter.test.ts`:

```ts
import { buildProviderSystemPrompt, buildProviderUserPrompt } from "../src/processAdapters";

describe("Phase 3 — prompt split", () => {
  const SYSTEM_PROMPT_IMPLEMENT = [
    "You are the claude worker for a Waygent task.",
    "role: implement",
    "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
    "Do not write AgentLens events directly.",
    "Do not apply changes to the source checkout.",
    "Edit only the isolated Waygent worktree.",
    "Obey the task packet write policy.",
    "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence."
  ].join("\n");

  test("buildProviderSystemPrompt is byte-stable per role (implement)", () => {
    expect(buildProviderSystemPrompt("claude", "implement")).toBe(SYSTEM_PROMPT_IMPLEMENT);
  });

  test("buildProviderUserPrompt contains only task-variable content (no role/contract reminders)", () => {
    const user = buildProviderUserPrompt({
      task_id: "task_abc",
      candidate_id: "cand_xyz",
      task_packet_path: "/p/packet.json",
      role: "implement",
      prompt: "do the thing"
    });
    expect(user).toContain("task_id: task_abc");
    expect(user).toContain("candidate_id: cand_xyz");
    expect(user).toContain("task_packet_path: /p/packet.json");
    expect(user).toContain("Task prompt:");
    expect(user).toContain("do the thing");
    expect(user).not.toContain("Required JSON fields");
    expect(user).not.toContain("Do not write AgentLens");
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL — `buildProviderSystemPrompt`/`buildProviderUserPrompt` are not exported.

- [x] **Step 3: Implement the split**

In `packages/provider-adapters/src/processAdapters.ts`, replace the existing `buildProviderPrompt` export with three exports — preserve the original as a thin combinator so any external caller still works:

```ts
export function buildProviderSystemPrompt(provider: "codex" | "claude", role: ProviderRole | undefined): string {
  const effectiveRole = role ?? "implement";
  return [
    `You are the ${provider} worker for a Waygent task.`,
    `role: ${effectiveRole}`,
    "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
    "Do not write AgentLens events directly.",
    "Do not apply changes to the source checkout.",
    "Edit only the isolated Waygent worktree.",
    "Obey the task packet write policy.",
    "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence."
  ].join("\n");
}

export function buildProviderUserPrompt(request: AdapterRequest): string {
  return [
    `task_id: ${request.task_id}`,
    `candidate_id: ${request.candidate_id}`,
    request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
    "Task prompt:",
    request.prompt
  ].join("\n");
}

export function buildProviderPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  // Preserved for codex (no append-system-prompt path) and any external caller.
  return [buildProviderSystemPrompt(provider, request.role), buildProviderUserPrompt(request)].join("\n");
}
```

- [x] **Step 4: Run to verify the split tests pass**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: PASS.

- [x] **Step 5: Full package test (regression for codex / fake)**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS — `buildProviderPrompt` still composes the same combined string for codex.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
refactor(provider-adapters): split provider prompt into system + user

System prompt is byte-stable per role; user prompt holds only
task-variable content. buildProviderPrompt preserved as combinator.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 3.2: Wire `--append-system-prompt` and switch Claude stdin to the user prompt

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`providerProcessArgs` Claude branch; `runProviderProcess` stdin write)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [x] **Step 1: Write the failing test**

Append to `packages/provider-adapters/tests/claudeAdapter.test.ts`:

```ts
test("Phase 3 — claude args inject --append-system-prompt with the role's stable text", () => {
  const args = providerProcessArgs(
    "claude",
    { executable: "claude", args: ["-p", "--output-format", "stream-json"] },
    "/tmp/work",
    { task_id: "t", candidate_id: "c", role: "implement", prompt: "p" }
  );
  const idx = args.indexOf("--append-system-prompt");
  expect(idx).toBeGreaterThanOrEqual(0);
  expect(args[idx + 1]).toContain("role: implement");
  expect(args[idx + 1]).toContain("Required JSON fields");
});

test("Phase 3 — non-CLI Claude executable does not get --append-system-prompt", () => {
  const args = providerProcessArgs(
    "claude",
    { executable: process.execPath, args: ["worker.mjs"] },
    "/tmp/work",
    { task_id: "t", candidate_id: "c", role: "implement", prompt: "p" }
  );
  expect(args).not.toContain("--append-system-prompt");
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL.

- [x] **Step 3: Inject `--append-system-prompt` and switch stdin**

In `processAdapters.ts`, inside the Claude branch of `providerProcessArgs` (only when `isClaudeCli`), after the role policy block, add:

```ts
if (!nextArgs.includes("--append-system-prompt")) {
  nextArgs.unshift("--append-system-prompt", buildProviderSystemPrompt("claude", request.role));
}
```

Change the stdin write in `runProviderProcess` to:

```ts
const stdinPayload = provider === "claude" && isProviderCliExecutable("claude", options.executable)
  ? buildProviderUserPrompt(request)
  : buildProviderPrompt(provider, request);
child.stdin.end(stdinPayload);
```

You will need `isProviderCliExecutable` and the prompt builders in scope at that site — they already live in this file.

- [x] **Step 4: Run to verify tests pass**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: PASS, including existing tests (no behavior change for codex; Claude regression tests pass because the stable system prompt + user prompt still contain the same task content).

- [x] **Step 5: Full package test**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): inject --append-system-prompt for claude CLI

Stable role prompt goes to --append-system-prompt; only task-variable
content remains on stdin. Enables prompt caching on the Claude side.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 3.3: `--settings` / `--mcp-config` pass-through

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`providerProcessArgs` Claude branch)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [x] **Step 1: Write the failing test**

```ts
test("Phase 3 — settings_path and mcp_config_path pass through to claude args", () => {
  const args = providerProcessArgs(
    "claude",
    {
      executable: "claude",
      args: ["-p", "--output-format", "stream-json"],
      settings_path: "/cfg/settings.json",
      mcp_config_path: "/cfg/.mcp.json"
    },
    "/tmp/work",
    { task_id: "t", candidate_id: "c", role: "implement", prompt: "p" }
  );
  const sIdx = args.indexOf("--settings");
  expect(sIdx).toBeGreaterThanOrEqual(0);
  expect(args[sIdx + 1]).toBe("/cfg/settings.json");
  const mIdx = args.indexOf("--mcp-config");
  expect(mIdx).toBeGreaterThanOrEqual(0);
  expect(args[mIdx + 1]).toBe("/cfg/.mcp.json");
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL — options not on type, args not injected.

- [x] **Step 3: Extend the type and the args branch**

In `types.ts`, add:

```ts
settings_path?: string;
mcp_config_path?: string;
```

to `ProviderProcessOptions`.

In `processAdapters.ts`, inside the Claude branch (when `isClaudeCli`), after the `--append-system-prompt` injection, add:

```ts
if (options.settings_path && !nextArgs.includes("--settings")) {
  nextArgs.unshift("--settings", options.settings_path);
}
if (options.mcp_config_path && !nextArgs.includes("--mcp-config")) {
  nextArgs.unshift("--mcp-config", options.mcp_config_path);
}
```

- [x] **Step 4: Run to verify the test passes**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): pass through claude --settings and --mcp-config

Lets a Waygent run scope settings and MCP servers per worktree without
mutating the user's global config.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 3.4: Nested Claude Code host env sanitize

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`runProviderProcess` env composition)
- Create: `packages/provider-adapters/tests/envSanitize.test.ts`

- [x] **Step 1: Write the failing test**

Create `packages/provider-adapters/tests/envSanitize.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { ClaudeProviderAdapter } from "../src";

const dumpEnvScript = `
const keys = ["CLAUDECODE","CLAUDE_CODE_ENTRYPOINT","CLAUDE_PROJECT_DIR","WAYGENT_TEST_MARK"];
const out = {};
for (const k of keys) out[k] = process.env[k] ?? null;
console.log(JSON.stringify({ status: "completed", changed_files: [], summary: "env", evidence: { env: out } }));
`;

describe("Phase 3 — nested Claude Code env sanitize", () => {
  test("strips CLAUDECODE/CLAUDE_CODE_ENTRYPOINT/CLAUDE_PROJECT_DIR when parent has CLAUDECODE=1", async () => {
    const prevCC = process.env.CLAUDECODE;
    const prevEP = process.env.CLAUDE_CODE_ENTRYPOINT;
    const prevPD = process.env.CLAUDE_PROJECT_DIR;
    const prevKeep = process.env.WAYGENT_KEEP_HOST_ENV;
    process.env.CLAUDECODE = "1";
    process.env.CLAUDE_CODE_ENTRYPOINT = "cli";
    process.env.CLAUDE_PROJECT_DIR = "/parent";
    process.env.WAYGENT_TEST_MARK = "kept";
    delete process.env.WAYGENT_KEEP_HOST_ENV;
    try {
      const result = await new ClaudeProviderAdapter({ executable: process.execPath, args: ["-e", dumpEnvScript] }).run({
        task_id: "t", candidate_id: "c", role: "implement", prompt: "p"
      });
      const env = (result.worker.evidence as any).env;
      expect(env.CLAUDECODE).toBeNull();
      expect(env.CLAUDE_CODE_ENTRYPOINT).toBeNull();
      expect(env.CLAUDE_PROJECT_DIR).toBeNull();
      expect(env.WAYGENT_TEST_MARK).toBe("kept");
    } finally {
      if (prevCC === undefined) delete process.env.CLAUDECODE; else process.env.CLAUDECODE = prevCC;
      if (prevEP === undefined) delete process.env.CLAUDE_CODE_ENTRYPOINT; else process.env.CLAUDE_CODE_ENTRYPOINT = prevEP;
      if (prevPD === undefined) delete process.env.CLAUDE_PROJECT_DIR; else process.env.CLAUDE_PROJECT_DIR = prevPD;
      if (prevKeep === undefined) delete process.env.WAYGENT_KEEP_HOST_ENV; else process.env.WAYGENT_KEEP_HOST_ENV = prevKeep;
      delete process.env.WAYGENT_TEST_MARK;
    }
  });

  test("WAYGENT_KEEP_HOST_ENV=1 preserves host env vars in the child", async () => {
    const prevKeep = process.env.WAYGENT_KEEP_HOST_ENV;
    process.env.CLAUDECODE = "1";
    process.env.WAYGENT_KEEP_HOST_ENV = "1";
    try {
      const result = await new ClaudeProviderAdapter({ executable: process.execPath, args: ["-e", dumpEnvScript] }).run({
        task_id: "t", candidate_id: "c", role: "implement", prompt: "p"
      });
      const env = (result.worker.evidence as any).env;
      expect(env.CLAUDECODE).toBe("1");
    } finally {
      delete process.env.CLAUDECODE;
      if (prevKeep === undefined) delete process.env.WAYGENT_KEEP_HOST_ENV; else process.env.WAYGENT_KEEP_HOST_ENV = prevKeep;
    }
  });
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/envSanitize.test.ts`
Expected: FAIL — env vars leak from parent.

- [x] **Step 3: Implement env sanitize in `runProviderProcess`**

In `processAdapters.ts`, replace the env composition currently passed to `spawn`:

```ts
env: { ...process.env, ...options.env, ...(cwd ? { PWD: cwd } : {}) },
```

with:

```ts
env: composeChildEnv(provider, process.env, options.env, cwd),
```

Add the helper:

```ts
const NESTED_CLAUDE_ENV_KEYS = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"] as const;

function composeChildEnv(
  provider: "codex" | "claude",
  parent: NodeJS.ProcessEnv,
  overrides: Record<string, string> | undefined,
  cwd: string | undefined
): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = { ...parent };
  if (provider === "claude" && parent.CLAUDECODE === "1" && parent.WAYGENT_KEEP_HOST_ENV !== "1") {
    for (const key of NESTED_CLAUDE_ENV_KEYS) {
      delete out[key];
    }
  }
  if (overrides) Object.assign(out, overrides);
  if (cwd) out.PWD = cwd;
  return out;
}
```

(Type note: `spawn` accepts `undefined` values; the `delete` operator is preferred over assignment to `undefined`, which the helper uses.)

- [x] **Step 4: Run to verify the tests pass**

Run: `bun test packages/provider-adapters/tests/envSanitize.test.ts`
Expected: PASS.

- [x] **Step 5: Full package test for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/envSanitize.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): sanitize nested Claude Code host env

When parent has CLAUDECODE=1, strip CLAUDECODE / CLAUDE_CODE_ENTRYPOINT
/ CLAUDE_PROJECT_DIR from the child env to avoid nested-session
confusion. Opt out with WAYGENT_KEEP_HOST_ENV=1.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 3.5: Phase 3 integration gate

- [x] **Step 1: Run `bun run check`**

Run: `bun run check`
Expected: green.

- [x] **Step 2: Run scenarios + platform demo**

Run: `bun run waygent:scenarios && bun run platform:demo`
Expected: green.

- [x] **Step 3: `git diff --check`**

Run: `git diff --check`
Expected: empty.

---

# Phase 4 — Resume & 재시도

Phase 4 goal: Add deterministic Claude `--session-id` on first attempt, capture the session id into worker evidence, and resume failed retries with `--resume`. Downgrade to a fresh attempt once if the session is missing.

### Step 4.1: Add `session_id` and `resume_session_id` to `ProviderProcessOptions`; wire CLI args

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`providerProcessArgs` Claude branch)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [x] **Step 1: Write the failing tests**

Append to `claudeAdapter.test.ts`:

```ts
describe("Phase 4 — session id / resume", () => {
  test("first attempt: --session-id is set, --resume is absent", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p", "--output-format", "stream-json"], session_id: "run1-task1-cand1" },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", role: "implement", prompt: "p" }
    );
    const sidIdx = args.indexOf("--session-id");
    expect(sidIdx).toBeGreaterThanOrEqual(0);
    expect(args[sidIdx + 1]).toBe("run1-task1-cand1");
    expect(args).not.toContain("--resume");
  });

  test("retry attempt: --resume wins and --session-id is omitted", () => {
    const args = providerProcessArgs(
      "claude",
      {
        executable: "claude",
        args: ["-p", "--output-format", "stream-json"],
        session_id: "run1-task1-cand1",
        resume_session_id: "run1-task1-cand1"
      },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", role: "implement", prompt: "p" }
    );
    const rIdx = args.indexOf("--resume");
    expect(rIdx).toBeGreaterThanOrEqual(0);
    expect(args[rIdx + 1]).toBe("run1-task1-cand1");
    expect(args).not.toContain("--session-id");
  });
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL — options not on type, args not injected.

- [x] **Step 3: Extend the type and the args branch**

In `types.ts`, add to `ProviderProcessOptions`:

```ts
session_id?: string;
resume_session_id?: string;
```

In `processAdapters.ts`, inside the Claude branch (when `isClaudeCli`), after the existing role/append-system-prompt/settings args, add:

```ts
if (options.resume_session_id && !nextArgs.includes("--resume")) {
  nextArgs.unshift("--resume", options.resume_session_id);
} else if (options.session_id && !nextArgs.includes("--session-id")) {
  nextArgs.unshift("--session-id", options.session_id);
}
```

- [x] **Step 4: Run to verify tests pass**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): wire --session-id / --resume for claude

Mutual exclusion: resume_session_id takes precedence; otherwise
session_id is injected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 4.2: Capture `session_id` and detect `session_missing` in worker evidence

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`normalizeProcessOutput`, `withProcessEvidence`, attestation)
- Modify: `packages/provider-adapters/tests/streamJson.test.ts`

- [x] **Step 1: Write the failing test**

Append to `streamJson.test.ts`:

```ts
describe("Phase 4 — session id capture and missing-session detection", () => {
  test("captures session_id from system.init into worker evidence", () => {
    const init = JSON.stringify({ type: "system", subtype: "init", session_id: "sess-XYZ", model: "claude-opus-4-7" });
    const final = JSON.stringify({
      type: "result",
      subtype: "success",
      result: "```json\n{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"t\",\"candidate_id\":\"c\",\"status\":\"completed\",\"changed_files\":[],\"summary\":\"ok\",\"evidence\":{}}\n```"
    });
    const stdout = [init, final].join("\n") + "\n";
    const r = normalizeProcessOutput("claude", "t", "c", { exitCode: 0, stdout, stderr: "", eventStream: stdout });
    expect((r.worker.evidence as any).session_id).toBe("sess-XYZ");
  });

  test("flags resume_session_missing when stderr matches 'session not found'", () => {
    const r = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 1,
      stdout: "",
      stderr: "Error: session not found: sess-missing"
    });
    expect(r.worker.status).toBe("failed");
    expect((r.worker.evidence as any).resume_session_missing).toBe(true);
  });
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: FAIL.

- [x] **Step 3: Implement evidence enrichment**

In `processAdapters.ts`, modify `normalizeProcessOutput` (or `withProcessEvidence` — pick the simpler site) to enrich the worker's evidence with `session_id` and `resume_session_missing` after construction.

Easiest path: after `worker` is constructed inside `normalizeProcessOutput`, mutate its evidence:

```ts
const sessionId = sessionIdFromStreamInit(output.eventStream ?? null);
if (sessionId) {
  (worker.evidence as Record<string, unknown>).session_id = sessionId;
}
```

Add the helper:

```ts
function sessionIdFromStreamInit(eventStreamText: string | null): string | null {
  if (!eventStreamText) return null;
  for (const line of eventStreamText.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parsed = parseJsonText(trimmed);
    if (!parsed || typeof parsed !== "object") continue;
    const r = parsed as Record<string, unknown>;
    if (r.type === "system" && r.subtype === "init" && typeof r.session_id === "string" && r.session_id.length > 0) {
      return r.session_id;
    }
  }
  return null;
}
```

For the missing-session signal: in `normalizeProcessOutput`'s `exitCode !== 0` branch (already returns `failed(..., "adapter_crashed", ...)`), enrich evidence before returning:

```ts
if (output.exitCode !== 0) {
  const worker = failed(task_id, candidate_id, "adapter_crashed", `${provider} exited ${output.exitCode}`);
  if (/session\s*not\s*found/i.test(output.stderr ?? "")) {
    (worker.evidence as Record<string, unknown>).resume_session_missing = true;
  }
  return withProcessEvidence(worker, output);
}
```

(Note: `failed()` validates via the contract, so mutating evidence after construction is safe as long as `evidence` is a plain object — which it is.)

- [x] **Step 4: Run tests to verify they pass**

Run: `bun test packages/provider-adapters/tests/streamJson.test.ts`
Expected: PASS.

- [x] **Step 5: Full package test**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/streamJson.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): capture session_id and detect resume misses

system.init.session_id is mirrored into worker evidence; stderr
matching /session not found/i flips resume_session_missing on adapter
crash output.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 4.3: Orchestrator retry: deterministic session id and resume wiring

**Files:**
- Modify: `packages/orchestrator/src/taskExecutor.ts` (find the Claude adapter construction or option-build site; thread `session_id` and `resume_session_id` from prior attempt evidence)

Before this task, **orient first**: run the search commands in Step 1 to locate the exact lines in `taskExecutor.ts` where the Claude adapter is constructed and where retries are issued. The orchestrator code is large enough that the right insertion point must be verified by reading, not assumed.

- [x] **Step 1: Orient — locate Claude adapter construction and retry site**

Run:

```bash
grep -n "ClaudeProviderAdapter\|provider === \"claude\"\|processes.claude\|claude.session\|--resume" packages/orchestrator/src/taskExecutor.ts
grep -n "retry\|attempt\|previous_attempt\|prior_attempt" packages/orchestrator/src/taskExecutor.ts | head -40
```

Read the surrounding ~60 lines for each match and identify:

- (a) where `ClaudeProviderAdapter` (or `new claudeAdapter`) is built with `ProviderProcessOptions`.
- (b) where retries are dispatched (look for repeated dispatch with an attempt counter or a `retry`/`revive` function name).
- (c) where the prior attempt's worker result (evidence) is in scope.

- [x] **Step 2: Write the failing test**

Add a new test file `packages/orchestrator/tests/claudeResume.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildClaudeProviderOptionsForAttempt } from "../src/taskExecutor";

describe("Phase 4 — Claude provider options per attempt", () => {
  test("first attempt assigns a deterministic session_id", () => {
    const opts = buildClaudeProviderOptionsForAttempt({
      run_id: "run-A",
      task_id: "task-1",
      candidate_id: "cand-1",
      prior_attempt_evidence: null
    });
    expect(opts.session_id).toBe("run-A-task-1-cand-1");
    expect(opts.resume_session_id).toBeUndefined();
  });

  test("retry attempt with prior session_id uses --resume", () => {
    const opts = buildClaudeProviderOptionsForAttempt({
      run_id: "run-A",
      task_id: "task-1",
      candidate_id: "cand-1",
      prior_attempt_evidence: { session_id: "captured-XYZ" }
    });
    expect(opts.resume_session_id).toBe("captured-XYZ");
    expect(opts.session_id).toBeUndefined();
  });

  test("retry after resume_session_missing downgrades back to fresh session_id", () => {
    const opts = buildClaudeProviderOptionsForAttempt({
      run_id: "run-A",
      task_id: "task-1",
      candidate_id: "cand-1",
      prior_attempt_evidence: { session_id: "captured-XYZ", resume_session_missing: true }
    });
    expect(opts.session_id).toBe("run-A-task-1-cand-1");
    expect(opts.resume_session_id).toBeUndefined();
  });
});
```

- [x] **Step 3: Run to verify failure**

Run: `bun test packages/orchestrator/tests/claudeResume.test.ts`
Expected: FAIL — `buildClaudeProviderOptionsForAttempt` is not exported.

- [x] **Step 4: Implement and export the option builder**

In `packages/orchestrator/src/taskExecutor.ts`, add (near the existing Claude adapter wiring):

```ts
export interface ClaudeAttemptInputs {
  run_id: string;
  task_id: string;
  candidate_id: string;
  prior_attempt_evidence: Record<string, unknown> | null;
}

export function buildClaudeProviderOptionsForAttempt(inputs: ClaudeAttemptInputs): {
  session_id?: string;
  resume_session_id?: string;
} {
  const prior = inputs.prior_attempt_evidence;
  const priorSessionId = prior && typeof prior.session_id === "string" ? prior.session_id : null;
  const priorMissing = prior?.resume_session_missing === true;
  if (priorSessionId && !priorMissing) {
    return { resume_session_id: priorSessionId };
  }
  return { session_id: `${inputs.run_id}-${inputs.task_id}-${inputs.candidate_id}` };
}
```

At the existing Claude adapter construction site (located in Step 1), merge the builder output into `ProviderProcessOptions`:

```ts
const claudeOpts: ProviderProcessOptions = {
  ...baseClaudeOpts,
  ...buildClaudeProviderOptionsForAttempt({
    run_id: state.run_id,           // adjust to actual field name in scope
    task_id: task.task_id,
    candidate_id: candidate.candidate_id,
    prior_attempt_evidence: priorAttempt?.evidence ?? null
  })
};
```

If the prior-attempt evidence isn't already threaded into the dispatch site, follow the existing retry plumbing (whatever Step 1 surfaced) and pass it in. Do NOT invent a new orchestrator concept of "prior attempt" — use whatever the existing retry/revive code already has.

- [x] **Step 5: Run the unit test to verify it passes**

Run: `bun test packages/orchestrator/tests/claudeResume.test.ts`
Expected: PASS.

- [x] **Step 6: Run orchestrator + adapter package tests**

Run: `cd packages/orchestrator && bun test && cd ../provider-adapters && bun test`
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/claudeResume.test.ts
git commit -m "$(cat <<'EOF'
feat(orchestrator): assign claude session_id / resume per attempt

First attempt gets {run_id}-{task_id}-{candidate_id}; retries reuse
the captured session via --resume; resume_session_missing downgrades
to a fresh session.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 4.4: Retry user-prompt prefix

**Files:**
- Modify: `packages/provider-adapters/src/types.ts` (`AdapterRequest` retry context)
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`buildProviderUserPrompt`)
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts` (populate retry context)

- [x] **Step 1: Write the failing test**

Append to `claudeAdapter.test.ts`:

```ts
test("Phase 4 — retry context prepends failure summary into the user prompt", () => {
  const user = buildProviderUserPrompt({
    task_id: "t",
    candidate_id: "c",
    role: "implement",
    prompt: "do the thing",
    retry_context: {
      prior_failure_class: "verification_failed",
      prior_stderr_summary: "FAIL tests/foo.test.ts > expected 1 got 2"
    }
  });
  expect(user.startsWith("Prior attempt failed: verification_failed.")).toBe(true);
  expect(user).toContain("FAIL tests/foo.test.ts");
  expect(user).toContain("runway.worker_result.v1 contract");
  expect(user).toContain("Task prompt:");
  expect(user).toContain("do the thing");
});
```

- [x] **Step 2: Run to verify failure**

Run: `bun test packages/provider-adapters/tests/claudeAdapter.test.ts`
Expected: FAIL — `retry_context` is not on the type.

- [x] **Step 3: Extend `AdapterRequest`**

In `types.ts`:

```ts
export interface AdapterRequest {
  task_id: string;
  candidate_id: string;
  role?: ProviderRole;
  prompt: string;
  task_packet_path?: string;
  cwd?: string;
  changed_files?: string[];
  retry_context?: {
    prior_failure_class: string;
    prior_stderr_summary: string;
  };
}
```

- [x] **Step 4: Update `buildProviderUserPrompt`**

In `processAdapters.ts`, change `buildProviderUserPrompt` to:

```ts
export function buildProviderUserPrompt(request: AdapterRequest): string {
  const retryPrefix = request.retry_context
    ? [
        `Prior attempt failed: ${request.retry_context.prior_failure_class}.`,
        `stderr summary: ${request.retry_context.prior_stderr_summary.slice(0, 300)}.`,
        "Fix and respond with the same runway.worker_result.v1 contract."
      ]
    : [];
  return [
    ...retryPrefix,
    `task_id: ${request.task_id}`,
    `candidate_id: ${request.candidate_id}`,
    request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
    "Task prompt:",
    request.prompt
  ].join("\n");
}
```

- [x] **Step 5: Populate retry_context from the orchestrator**

In `packages/orchestrator/src/taskExecutor.ts`, at the dispatch site where `AdapterRequest` is built, if a prior attempt exists, include:

```ts
const retry_context = priorAttempt
  ? {
      prior_failure_class: priorAttempt.worker.failure_class ?? "unknown",
      prior_stderr_summary: priorAttempt.process?.stderr_summary?.summary ?? priorAttempt.process?.stderr ?? ""
    }
  : undefined;
const request: AdapterRequest = {
  ...,
  ...(retry_context ? { retry_context } : {})
};
```

Adapt field names to whatever the in-scope `priorAttempt` actually exposes; Step 1 of Task 4.3 already located these.

- [x] **Step 6: Run tests to verify**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS, including the new retry-prefix test.

- [x] **Step 7: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/claudeAdapter.test.ts packages/orchestrator/src/taskExecutor.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters,orchestrator): retry prompt prefix from prior failure

User prompt gains a 3-line prefix with prior failure_class, trimmed
stderr summary, and a contract reminder when retry_context is set.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Step 4.5: Phase 4 integration gate

- [x] **Step 1: Run full repo check**

Run: `bun run check`
Expected: green.

- [x] **Step 2: Run scenarios + platform demo**

Run: `bun run waygent:scenarios && bun run platform:demo`
Expected: green.

- [x] **Step 3: `git diff --check`**

Run: `git diff --check`
Expected: empty.

- [x] **Step 4: Manual smoke (optional, requires `claude` CLI on PATH and credentials)**

Run a tiny one-task plan through Waygent twice in quick succession against a worktree where the first attempt is expected to fail (e.g., a plan whose `verify` will fail once). Confirm:

- First attempt has `--session-id` in the spawned args (capture via `ps` or by running with `set -x` wrapper).
- Second attempt has `--resume` with the same id.
- worker evidence contains `session_id`.

Document the observation in a short note attached to the PR / Lens evidence — no source change.

---

# Cross-cutting wrap-up

- [x] **Repo-wide regression sweep**

Run: `bun run check && bun run waygent:scenarios && bun run platform:demo && cd packages/provider-adapters && bun test && cd ../orchestrator && bun test && cd ../.. && git diff --check`
Expected: all green.

- [x] **Doc sync**

If `docs/operations/verification.md` or any user-facing doc references "Claude provider behavior", add a short note about stream-json, resume, and per-role permissions. If no such reference exists, skip — the spec covers contributors.

- [x] **Branch wrap**

Use `superpowers:finishing-a-development-branch` to choose merge / PR / cleanup path.
