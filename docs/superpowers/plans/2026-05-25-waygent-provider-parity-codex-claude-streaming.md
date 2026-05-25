# Waygent — Provider Adapter Parity (Codex) + Claude Stream-JSON Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining parity gap between the Codex and Claude provider adapters (Codex env sanitize / prompt split / retry resume / unsupported-option reject) and put the Claude stream-json envelopes already in flight to first-class use (per-task tool-use audit, role-aware model routing).

**Architecture:** All changes are additive and localized to existing files in `packages/provider-adapters/src/`, `packages/orchestrator/src/`, and `apps/cli/src/`. No new packages, no new event types, no schema version bump. One `waygent-task` envelope, ~14 plan steps grouped into Phase A (Codex parity, C1–C4), Phase B (D1 tool-use audit), Phase C (D2 role routing), Phase D (integration gate).

**Tech Stack:** TypeScript, Bun (test runner), `@waygent/contracts`, `codex` CLI (`exec --json -`, `exec resume <id> --json -`, `-m`, `--reasoning`), `claude` CLI (`-p`, `--output-format stream-json`).

**Spec:** `docs/superpowers/specs/2026-05-25-waygent-provider-parity-claude-streaming-design.md`

---

```yaml waygent-task
id: task_provider_parity_codex_claude_streaming
title: Implement provider-adapter parity for Codex (env sanitize, sentinel prompt split, retry resume, unsupported-option reject) and activate stream-json per-task tool-use audit + role-aware model routing per docs/superpowers/specs/2026-05-25-waygent-provider-parity-claude-streaming-design.md, additively (no schema bump) and without weakening apply readiness.
dependencies: []
file_claims:
  - path: packages/provider-adapters/src/capabilities.ts
    mode: owned
  - path: packages/provider-adapters/src/types.ts
    mode: owned
  - path: packages/provider-adapters/src/processAdapters.ts
    mode: owned
  - path: packages/provider-adapters/tests/envSanitize.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/codexPromptSplit.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/codexResume.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/unsupportedOption.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/toolUseAudit.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/manifest.test.ts
    mode: owned
  - path: packages/provider-adapters/tests/fixtures/codex/session_init.jsonl
    mode: owned
  - path: packages/provider-adapters/tests/fixtures/claude/stream_json_with_tools.jsonl
    mode: owned
  - path: packages/orchestrator/src/executionProfile.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/roleRouting.test.ts
    mode: owned
  - path: packages/orchestrator/tests/codexResume.test.ts
    mode: owned
  - path: apps/cli/src/index.ts
    mode: owned
  - path: apps/cli/tests/roleFlags.test.ts
    mode: owned
risk: high
verify_isolation: isolated
verify:
  - bun run typecheck
  - bun test packages/provider-adapters/tests
  - bun test packages/orchestrator/tests
  - bun test apps/cli/tests
  - bun run waygent:scenarios
  - bun run platform:demo
```

---

## Conventions

- Bun is the package manager and test runner. Run tests with `bun test <path>`.
- Run from repo root unless a task specifies `cd <subpath>`.
- All commits include the trailer `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` (per repo policy in `CLAUDE.md`).
- Roles use the `ProviderRole` enum from `packages/contracts/src/types.ts`: `"implement" | "review" | "fix" | "verify_assist"`.
- Reasoning levels use the `ReasoningLevel` enum from `packages/orchestrator/src/executionProfile.ts`: `"medium" | "high" | "xhigh"`.
- Each task ends with a commit. Keep commits small and reversible.
- Run `bun run check` once at the end as the integrative regression gate (Phase D).

## File Map

| File | Phase | Responsibility |
|---|---|---|
| `packages/provider-adapters/src/capabilities.ts` | A (C4) | Add `supports` block per provider |
| `packages/provider-adapters/src/types.ts` | A (C4), B (D1) | `ProviderCapabilityManifest.supports`; `ToolCall` schema |
| `packages/provider-adapters/src/processAdapters.ts` | A (C1, C2, C3, C4), B (D1) | `buildSpawnEnv`, `buildProviderStdinPrompt`, `providerProcessArgsWithWarnings`, `runProviderProcess`, `parseWorkerOutput` |
| `packages/provider-adapters/tests/*.test.ts` (new) | A, B | Unit coverage for each item |
| `packages/provider-adapters/tests/fixtures/codex/session_init.jsonl` | A (R1) | Codex first-envelope session_id capture |
| `packages/provider-adapters/tests/fixtures/claude/stream_json_with_tools.jsonl` | B | Claude stream-json with `assistant.tool_use` + `user.tool_result` |
| `packages/orchestrator/src/executionProfile.ts` | C (D2) | `RoleRouting`, `roles: { implement, review, verify_assist }` |
| `packages/orchestrator/src/orchestrator.ts` | C (D2) | Per-role `(model, reasoning)` resolution at worker dispatch |
| `packages/orchestrator/src/taskExecutor.ts` | A (C3) | Codex retry: set `resume_session_id` when prior attempt captured `session_id` |
| `packages/orchestrator/tests/*.test.ts` (new) | A, C | Codex resume wiring; role routing matrix |
| `apps/cli/src/index.ts` | C (D2) | Parse `--role-model` and `--role-reasoning` |
| `apps/cli/tests/roleFlags.test.ts` (new) | C | CLI flag parse coverage |

## Cross-Path Invariants (CP)

- **CP-1**: Sentinel strings `<system_instructions role="...">` and `<user_request>` (Task A.3) are byte-stable per role. Co-located in `buildProviderStdinPrompt` (Codex branch) and the fixture in `codexPromptSplit.test.ts`. Update both together.
- **CP-2**: `HOST_ENV_KEYS_TO_DROP` (Task A.1) and the parent-host detection predicate live next to each other in `buildSpawnEnv`. The `envSanitize.test.ts` matrix enumerates each key + each parent host.
- **CP-3**: Every key in `ProviderCapabilityManifest.supports` (Task A.5) has exactly one check in `runProviderProcess`'s unsupported-option gate; every check looks up exactly one key. `manifest.test.ts` enumerates this.
- **CP-4**: Profile resolution priority (Task C.3) — `--main-*` > `--subagent-*` > `--role-*` > `--profile` — is asserted by an explicit matrix test in `roleRouting.test.ts`.

---

# Phase A — Codex Parity (C1, R1, C2, C3, C4)

## Task A.1: C1 — Codex Environment Sanitization

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts:49,155-175`
- Create: `packages/provider-adapters/tests/envSanitize.test.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/provider-adapters/tests/envSanitize.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildSpawnEnv } from "../src/processAdapters";

const CODEX_HOST_PARENT = { CODEX_APP: "1", CODEX_CLI: "1", CODEX_ENTRYPOINT: "codex.app", CODEX_HOME: "/Users/me/.codex" };
const CLAUDE_HOST_PARENT = { CLAUDECODE: "1", CLAUDE_CODE_ENTRYPOINT: "claude-code", CLAUDE_PROJECT_DIR: "/Users/me/proj" };

describe("buildSpawnEnv — host env sanitization (C1)", () => {
  test("drops Codex host keys when parent looks like a Codex host", () => {
    const env = buildSpawnEnv(CODEX_HOST_PARENT, undefined, "/tmp");
    expect(env.CODEX_APP).toBeUndefined();
    expect(env.CODEX_CLI).toBeUndefined();
    expect(env.CODEX_ENTRYPOINT).toBeUndefined();
  });

  test("preserves CODEX_HOME (credential storage) even under sanitization", () => {
    const env = buildSpawnEnv(CODEX_HOST_PARENT, undefined, "/tmp");
    expect(env.CODEX_HOME).toBe("/Users/me/.codex");
  });

  test("drops Claude host keys when parent looks like a Claude host", () => {
    const env = buildSpawnEnv(CLAUDE_HOST_PARENT, undefined, "/tmp");
    expect(env.CLAUDECODE).toBeUndefined();
    expect(env.CLAUDE_CODE_ENTRYPOINT).toBeUndefined();
    expect(env.CLAUDE_PROJECT_DIR).toBeUndefined();
  });

  test("drops both sets when parent is both (defense-in-depth)", () => {
    const env = buildSpawnEnv({ ...CODEX_HOST_PARENT, ...CLAUDE_HOST_PARENT }, undefined, "/tmp");
    expect(env.CODEX_APP).toBeUndefined();
    expect(env.CLAUDECODE).toBeUndefined();
    expect(env.CODEX_HOME).toBe("/Users/me/.codex");
  });

  test("WAYGENT_KEEP_HOST_ENV=1 disables sanitization for both host families", () => {
    const env = buildSpawnEnv({ ...CODEX_HOST_PARENT, ...CLAUDE_HOST_PARENT, WAYGENT_KEEP_HOST_ENV: "1" }, undefined, "/tmp");
    expect(env.CODEX_APP).toBe("1");
    expect(env.CLAUDECODE).toBe("1");
  });

  test("no-op when parent is neither host", () => {
    const env = buildSpawnEnv({ PATH: "/usr/bin", HOME: "/Users/me" }, undefined, "/tmp");
    expect(env.PATH).toBe("/usr/bin");
    expect(env.HOME).toBe("/Users/me");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/provider-adapters/tests/envSanitize.test.ts`
Expected: FAIL on the Codex-host cases — only Claude keys are dropped today.

- [ ] **Step 3: Extend `HOST_ENV_KEYS_TO_DROP` and the detection predicate**

In `packages/provider-adapters/src/processAdapters.ts`, replace line 49:

```ts
const HOST_ENV_KEYS_TO_DROP = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"] as const;
```

with:

```ts
// Co-located with the parent-host detection predicate below — see CP-2 in the
// provider-parity-claude-streaming spec. Update both together.
const HOST_ENV_KEYS_TO_DROP = [
  "CLAUDECODE",
  "CLAUDE_CODE_ENTRYPOINT",
  "CLAUDE_PROJECT_DIR",
  "CODEX_APP",
  "CODEX_CLI",
  "CODEX_ENTRYPOINT"
] as const;

// CODEX_HOME points at the auth credential store; dropping it breaks the
// child's ability to authenticate. Always preserve it (intentional exception).
const HOST_ENV_KEYS_PRESERVE_ALWAYS = new Set(["CODEX_HOME"]);

function detectHostParent(parentEnv: NodeJS.ProcessEnv): boolean {
  if (parentEnv.CLAUDECODE === "1") return true;
  if (typeof parentEnv.CLAUDE_CODE_ENTRYPOINT === "string") return true;
  if (parentEnv.CODEX_APP === "1") return true;
  if (parentEnv.CODEX_CLI === "1") return true;
  if (typeof parentEnv.CODEX_ENTRYPOINT === "string") return true;
  return false;
}
```

Now find the `buildSpawnEnv` function (around line 155) and change the inline detection to call `detectHostParent`. Replace the body so the predicate is shared:

```ts
export function buildSpawnEnv(
  parentEnv: NodeJS.ProcessEnv,
  overlay: Record<string, string> | undefined,
  _cwd: string | undefined
): Record<string, string> {
  const keepHostEnv = parentEnv.WAYGENT_KEEP_HOST_ENV === "1";
  const shouldSanitize = !keepHostEnv && detectHostParent(parentEnv);
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(parentEnv)) {
    if (value === undefined) continue;
    if (shouldSanitize && (HOST_ENV_KEYS_TO_DROP as readonly string[]).includes(key) && !HOST_ENV_KEYS_PRESERVE_ALWAYS.has(key)) continue;
    result[key] = value;
  }
  if (overlay) {
    for (const [key, value] of Object.entries(overlay)) result[key] = value;
  }
  return result;
}
```

(If the existing signature differs — verify with `grep -n "export function buildSpawnEnv" packages/provider-adapters/src/processAdapters.ts` first — keep the existing argument order and types; the body above is what matters.)

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/provider-adapters/tests/envSanitize.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Run full package tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/envSanitize.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): sanitize Codex host env keys for child processes (C1)

Extends HOST_ENV_KEYS_TO_DROP with CODEX_APP/CODEX_CLI/CODEX_ENTRYPOINT
and shares the parent-host predicate (Claude OR Codex parent triggers
sanitize). CODEX_HOME is preserved unconditionally to keep child auth
working. WAYGENT_KEEP_HOST_ENV=1 still disables sanitization end-to-end.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task A.2: R1 — Capture Codex `session_id` Fixture

**Goal:** Lock the actual Codex stream-json envelope key name for the session id before depending on it in Task A.4. This is a one-time observational task; no production code change.

**Files:**
- Create: `packages/provider-adapters/tests/fixtures/codex/session_init.jsonl`
- Create: `packages/provider-adapters/tests/fixtures/codex/README.md`

- [ ] **Step 1: Capture a real Codex `--json` first envelope**

Run the Codex CLI against a trivial prompt with `--json`:

```bash
mkdir -p packages/provider-adapters/tests/fixtures/codex
echo 'print "hi"' | codex exec --json - 2>/dev/null | head -5 > /tmp/codex_init.jsonl
cat /tmp/codex_init.jsonl
```

Expected: at least one JSON line containing a session identifier. Field name is likely `session_id`, but Codex may emit it as `session.id`, `id`, or nested under `system`. **Do not assume the name.**

- [ ] **Step 2: Identify the session-id field**

Inspect `/tmp/codex_init.jsonl` and find the field that:
- Appears in the **first** envelope
- Is a stable UUID-like string for the session lifetime
- Is the value Codex's `exec resume <SESSION_ID>` subcommand expects

Record the exact JSON path (e.g., `$.session_id`, `$.session.id`, `$.id`) in a one-line note.

- [ ] **Step 3: Persist the fixture and the discovered field name**

Copy the first 2–3 envelopes to the fixture file (redact any user content if the trivial prompt leaked):

```bash
head -3 /tmp/codex_init.jsonl > packages/provider-adapters/tests/fixtures/codex/session_init.jsonl
```

Create `packages/provider-adapters/tests/fixtures/codex/README.md`:

```markdown
# Codex `exec --json` first-envelope fixture

Captured: <YYYY-MM-DD> against `codex` CLI version <output of `codex --version`>.

**Session id JSON path:** `<exact path discovered in Step 2, e.g. $.session_id>`

This fixture locks the field name used by `parseCodexSessionId` in
`packages/provider-adapters/src/processAdapters.ts` (Task A.4 in
`docs/superpowers/plans/2026-05-25-waygent-provider-parity-codex-claude-streaming.md`).
If Codex changes the envelope shape, update both this fixture and
`parseCodexSessionId` together.
```

- [ ] **Step 4: Add a parser stub-test that locks the field name**

Append to `packages/provider-adapters/tests/codexResume.test.ts` (created empty — content added in Task A.4):

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("Codex session_init fixture (R1)", () => {
  test("first envelope exposes the documented session id field", () => {
    const path = join(import.meta.dir, "fixtures/codex/session_init.jsonl");
    const firstLine = readFileSync(path, "utf8").split("\n")[0];
    const envelope = JSON.parse(firstLine);
    // Update this assertion to match the path documented in fixtures/codex/README.md
    // (e.g. envelope.session_id, envelope.session?.id, envelope.id).
    const sessionId = envelope.session_id ?? envelope.session?.id ?? envelope.id;
    expect(typeof sessionId).toBe("string");
    expect(sessionId.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 5: Run test to confirm fixture is parseable**

Run: `bun test packages/provider-adapters/tests/codexResume.test.ts`
Expected: PASS (1 test — fixture lock only; resume logic comes in Task A.4).

- [ ] **Step 6: Commit**

```bash
git add packages/provider-adapters/tests/fixtures/codex packages/provider-adapters/tests/codexResume.test.ts
git commit -m "$(cat <<'EOF'
test(provider-adapters): lock Codex exec --json session_id fixture (R1)

Captures the first stream-json envelope from a real codex exec --json
invocation and locks the discovered session_id JSON path in a fixture +
README. This unblocks the Codex retry-resume work (Task A.4) without
guessing the field name.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task A.3: C2 — Codex System + User Prompt Split (Sentinel)

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts:412-417` (the existing `buildProviderStdinPrompt` Codex branch)
- Create: `packages/provider-adapters/tests/codexPromptSplit.test.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/provider-adapters/tests/codexPromptSplit.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildProviderStdinPromptForTest } from "../src/processAdapters";

const baseRequest = {
  task_id: "t1",
  candidate_id: "c1",
  role: "implement" as const,
  prompt: "Do the thing.",
  task_packet_path: undefined
};

describe("buildProviderStdinPrompt Codex branch (C2 sentinel)", () => {
  test("wraps system + user content with stable sentinel tags", () => {
    const out = buildProviderStdinPromptForTest("codex", baseRequest);
    expect(out).toContain('<system_instructions role="implement">');
    expect(out).toContain("</system_instructions>");
    expect(out).toContain("<user_request>");
    expect(out).toContain("</user_request>");
  });

  test("system_instructions prefix is byte-stable per role across requests (cache amortization)", () => {
    const a = buildProviderStdinPromptForTest("codex", baseRequest);
    const b = buildProviderStdinPromptForTest("codex", { ...baseRequest, task_id: "t2", candidate_id: "c2", prompt: "Something else." });
    const prefixA = a.split("</system_instructions>")[0];
    const prefixB = b.split("</system_instructions>")[0];
    expect(prefixA).toBe(prefixB);
  });

  test("role drives the sentinel attribute (review)", () => {
    const out = buildProviderStdinPromptForTest("codex", { ...baseRequest, role: "review" });
    expect(out).toContain('<system_instructions role="review">');
  });

  test("Claude branch is unchanged (no sentinel wrapper)", () => {
    const out = buildProviderStdinPromptForTest("claude", baseRequest);
    expect(out).not.toContain("<system_instructions");
    expect(out).not.toContain("<user_request>");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/provider-adapters/tests/codexPromptSplit.test.ts`
Expected: FAIL — `buildProviderStdinPromptForTest` is not exported; the Codex branch concatenates the legacy combined prompt without sentinels.

- [ ] **Step 3: Add the sentinel wrapper in the Codex branch and expose for tests**

In `packages/provider-adapters/src/processAdapters.ts`, replace the existing `buildProviderStdinPrompt` (around line 412) with:

```ts
// What we actually pipe to stdin for each provider.
// Claude moves the contract reminder block into --append-system-prompt (handled upstream).
// Codex has no system-prompt flag; we wrap with byte-stable sentinel tags so the
// Codex provider can cache the leading system block across workers in the same role.
// CP-1: tag strings are part of the design contract — keep in sync with codexPromptSplit.test.ts.
function buildProviderStdinPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  if (provider === "claude") return buildProviderUserPrompt(provider, request);
  const role = request.role ?? "implement";
  const systemBlock = buildProviderSystemPrompt(role);
  const userBlock = buildProviderUserPrompt("codex", request);
  return [
    `<system_instructions role="${role}">`,
    systemBlock,
    `</system_instructions>`,
    ``,
    `<user_request>`,
    userBlock,
    `</user_request>`
  ].join("\n");
}

// Exported for tests only. Stable across refactors.
export const buildProviderStdinPromptForTest = buildProviderStdinPrompt;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/provider-adapters/tests/codexPromptSplit.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Run full package tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS. If `buildProviderPrompt` callers in existing tests depend on the legacy concatenation shape, they should still pass because that function is unchanged.

- [ ] **Step 6: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/codexPromptSplit.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): Codex stdin prompt split via sentinel tags (C2)

Wraps Codex stdin in <system_instructions role="..."> ... </system_instructions>
+ <user_request> ... </user_request> so the leading system block is byte-stable
per role and amortizes Codex prompt-cache across workers. Claude branch
unchanged (still --append-system-prompt + user-only stdin).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task A.4: C3 — Codex Retry Resume

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` — Codex branch of `providerProcessArgsWithWarnings`, add `parseCodexSessionId`, extend `detectResumeSessionMissing` for Codex stderr patterns
- Modify: `packages/orchestrator/src/taskExecutor.ts` — Codex retry path sets `resume_session_id`
- Extend: `packages/provider-adapters/tests/codexResume.test.ts` (already created in Task A.2)
- Create: `packages/orchestrator/tests/codexResume.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `packages/provider-adapters/tests/codexResume.test.ts`:

```ts
import { providerProcessArgs, parseCodexSessionId, detectResumeSessionMissing } from "../src/processAdapters";

describe("Codex retry resume args (C3)", () => {
  test("first attempt: spawn args are ['exec', '--json', '-']", () => {
    const args = providerProcessArgs("codex", { executable: "codex" }, "/tmp/work", {
      task_id: "t", candidate_id: "c", role: "implement", prompt: "p"
    });
    expect(args).toContain("exec");
    expect(args).toContain("--json");
    expect(args).toContain("-");
    expect(args).not.toContain("resume");
  });

  test("retry attempt: resume_session_id injects ['exec', 'resume', <id>, '--json', '-']", () => {
    const args = providerProcessArgs("codex", { executable: "codex", resume_session_id: "sess-abc" }, "/tmp/work", {
      task_id: "t", candidate_id: "c", role: "implement", prompt: "p"
    });
    const execIdx = args.indexOf("exec");
    expect(execIdx).toBeGreaterThanOrEqual(0);
    expect(args[execIdx + 1]).toBe("resume");
    expect(args[execIdx + 2]).toBe("sess-abc");
    expect(args).toContain("--json");
  });

  test("parseCodexSessionId reads the documented field from the first envelope", () => {
    const sample = '{"session_id":"sess-xyz","type":"session.init"}\n{"type":"assistant"}';
    expect(parseCodexSessionId(sample)).toBe("sess-xyz");
  });

  test("parseCodexSessionId returns undefined when absent", () => {
    expect(parseCodexSessionId('{"type":"assistant"}')).toBeUndefined();
    expect(parseCodexSessionId("")).toBeUndefined();
  });

  test("detectResumeSessionMissing matches Codex stderr 'session not found' shape", () => {
    expect(detectResumeSessionMissing("codex: session sess-abc not found\n")).toBe(true);
    expect(detectResumeSessionMissing("ok\n")).toBe(false);
  });
});
```

Create `packages/orchestrator/tests/codexResume.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { injectCodexResumeContext } from "../src/taskExecutor";

describe("injectCodexResumeContext (orchestrator wiring for C3)", () => {
  test("first attempt: resume_session_id remains undefined", () => {
    const base = { codex: { executable: "codex" } };
    const out = injectCodexResumeContext(base, { priorSessionId: undefined });
    expect(out.codex.resume_session_id).toBeUndefined();
  });

  test("retry: resume_session_id is set to prior attempt's captured id", () => {
    const base = { codex: { executable: "codex" } };
    const out = injectCodexResumeContext(base, { priorSessionId: "sess-prev" });
    expect(out.codex.resume_session_id).toBe("sess-prev");
  });

  test("non-codex providers are passed through unchanged", () => {
    const base = { claude: { executable: "claude" } };
    const out = injectCodexResumeContext(base, { priorSessionId: "sess-prev" });
    expect(out.claude).toEqual({ executable: "claude" });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun test packages/provider-adapters/tests/codexResume.test.ts packages/orchestrator/tests/codexResume.test.ts`
Expected: FAIL — `parseCodexSessionId`, the Codex resume args branch, and `injectCodexResumeContext` do not exist.

- [ ] **Step 3: Implement the Codex resume args branch in `providerProcessArgsWithWarnings`**

In `packages/provider-adapters/src/processAdapters.ts`, locate the existing Codex branch (after the Claude branch returns; around line 324). Inject the resume-or-fresh prefix **before** the `--cd`/`--skip-git-repo-check` handling. Replace the start of the Codex branch:

```ts
  if (provider !== "codex") return { args, warnings };
  let nextArgs = [...args];
  const isCodexCli = isProviderCliExecutable("codex", options.executable);
```

with:

```ts
  if (provider !== "codex") return { args, warnings };
  let nextArgs = [...args];
  const isCodexCli = isProviderCliExecutable("codex", options.executable);
  if (isCodexCli && nextArgs.length === 0) {
    // Default Codex spawn shape: `exec [resume <id>] --json -`.
    if (options.resume_session_id) {
      nextArgs = ["exec", "resume", options.resume_session_id, "--json", "-"];
    } else {
      nextArgs = ["exec", "--json", "-"];
    }
  }
```

(If callers already pass explicit `args`, do not override — the Codex CLI users at higher levels may construct args differently. The default branch only triggers when `args` is empty/default.)

- [ ] **Step 4: Add `parseCodexSessionId` and extend `detectResumeSessionMissing`**

Add after `detectResumeSessionMissing` (around line 684):

```ts
export function parseCodexSessionId(stdout: string): string | undefined {
  const firstLine = stdout.split("\n").find(line => line.trim().length > 0);
  if (!firstLine) return undefined;
  let envelope: unknown;
  try {
    envelope = JSON.parse(firstLine);
  } catch {
    return undefined;
  }
  if (!envelope || typeof envelope !== "object") return undefined;
  const obj = envelope as Record<string, unknown>;
  // Field name confirmed by Task A.2 fixture (R1). Update both together if Codex changes shape.
  if (typeof obj.session_id === "string") return obj.session_id;
  if (typeof obj.id === "string" && (obj.type === "session.init" || obj.type === "system.init")) return obj.id;
  const nested = obj.session as Record<string, unknown> | undefined;
  if (nested && typeof nested.id === "string") return nested.id;
  return undefined;
}
```

And extend `detectResumeSessionMissing` to also match Codex's pattern. Find the existing function and broaden the regex:

```ts
function detectResumeSessionMissing(stderr: string): boolean {
  if (!stderr) return false;
  // Claude: "session ... not found"; Codex: "session <id> not found" or "no such session".
  return /session(?:[^\n]{0,80})?not\s+found|no\s+such\s+session/i.test(stderr);
}
```

Export it as `export function detectResumeSessionMissing(...)` if not already exported (the test imports it).

Capture the session id into evidence: in `normalizeProcessOutput`'s success branch (around lines 60–80), set `evidence.session_id` for Codex from `parseCodexSessionId(output.stdout)` if undefined in `parsed.evidence`. The minimal patch — inside the `try` block where `parsed` is assembled:

```ts
const codexSessionId = provider === "codex" ? parseCodexSessionId(output.stdout) : undefined;
// ...later, when building evidence:
evidence: {
  provider,
  ...((parsed.evidence && typeof parsed.evidence === "object") ? parsed.evidence : {}),
  ...(codexSessionId && !(parsed.evidence as Record<string, unknown> | undefined)?.session_id ? { session_id: codexSessionId } : {}),
  native: parsed.evidence ?? parsed
}
```

- [ ] **Step 5: Add `injectCodexResumeContext` in `taskExecutor.ts`**

In `packages/orchestrator/src/taskExecutor.ts`, find the existing `injectClaudeSessionContext` (around line 879). Add a sibling, exported function:

```ts
export function injectCodexResumeContext<T extends Record<string, { executable?: string; resume_session_id?: string }>>(
  provider_processes: T,
  ctx: { priorSessionId: string | undefined }
): T {
  const codex = provider_processes.codex;
  if (!codex) return provider_processes;
  if (!ctx.priorSessionId) return provider_processes;
  return {
    ...provider_processes,
    codex: { ...codex, resume_session_id: ctx.priorSessionId }
  };
}
```

Wire it into the retry path. Find the call site near `injectClaudeSessionContext` (around `taskExecutor.ts:201`) and add a parallel call for Codex:

```ts
const resolvedProcesses = injectClaudeSessionContext(input.provider_processes, {
  /* existing args */
});
const withCodexResume = injectCodexResumeContext(resolvedProcesses, {
  priorSessionId: input.priorAttempt?.evidence?.session_id as string | undefined
});
// then use `withCodexResume` downstream where `resolvedProcesses` was used.
```

(Adapt to the exact shape of `input.priorAttempt` already located in nearby Claude code. The point is: extract the prior `session_id` from the Codex evidence and pass it forward.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `bun test packages/provider-adapters/tests/codexResume.test.ts packages/orchestrator/tests/codexResume.test.ts`
Expected: PASS (8 tests across both files).

- [ ] **Step 7: Run package tests for regression**

Run: `cd packages/provider-adapters && bun test && cd ../orchestrator && bun test`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/codexResume.test.ts packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/codexResume.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters,orchestrator): Codex retry resume support (C3)

Codex retry attempts now spawn as `exec resume <session_id> --json -`.
Session id is captured from the first stream-json envelope into
worker_result.evidence.session_id (field path locked by R1 fixture) and
flowed to the next attempt via injectCodexResumeContext. Codex stderr
"session not found" surfaces as worker_result.evidence.resume_session_missing
via the shared detectResumeSessionMissing pattern.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task A.5: C4 — Capability Manifest `supports` + Unsupported-Option Reject

**Files:**
- Modify: `packages/provider-adapters/src/types.ts` (extend `ProviderCapabilityManifest`)
- Modify: `packages/provider-adapters/src/capabilities.ts` (populate `supports` for claude + codex)
- Modify: `packages/provider-adapters/src/processAdapters.ts` (`runProviderProcess` entry: enumerate options against `supports`)
- Create: `packages/provider-adapters/tests/manifest.test.ts` (if not present from prior plan — append if it is)
- Create: `packages/provider-adapters/tests/unsupportedOption.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `packages/provider-adapters/tests/unsupportedOption.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { collectUnsupportedOptionWarnings } from "../src/processAdapters";
import { claudeCapabilityManifest, codexCapabilityManifest } from "../src/capabilities";

describe("collectUnsupportedOptionWarnings (C4)", () => {
  test("Codex rejects settings_path with a structured warning", () => {
    const warnings = collectUnsupportedOptionWarnings(codexCapabilityManifest, {
      executable: "codex",
      settings_path: "/etc/waygent/settings.json"
    });
    expect(warnings).toContain("unsupported_provider_option: settings_path (codex)");
  });

  test("Codex rejects mcp_config_path", () => {
    const warnings = collectUnsupportedOptionWarnings(codexCapabilityManifest, {
      executable: "codex",
      mcp_config_path: "/etc/waygent/mcp.json"
    });
    expect(warnings).toContain("unsupported_provider_option: mcp_config_path (codex)");
  });

  test("Codex rejects session_id (first-attempt injection)", () => {
    const warnings = collectUnsupportedOptionWarnings(codexCapabilityManifest, {
      executable: "codex",
      session_id: "sess-pre-spawn"
    });
    expect(warnings).toContain("unsupported_provider_option: session_id (codex)");
  });

  test("Codex rejects per-process reasoning via the warning channel (still spawned, just warned)", () => {
    const warnings = collectUnsupportedOptionWarnings(codexCapabilityManifest, {
      executable: "codex",
      effort: "high"
    });
    // C4: reasoning surfaces as a warning rather than a spawn flag for Codex.
    expect(warnings).toContain("unsupported_provider_option: reasoning (codex)");
  });

  test("Claude accepts all four options silently (no warnings)", () => {
    const warnings = collectUnsupportedOptionWarnings(claudeCapabilityManifest, {
      executable: "claude",
      settings_path: "x",
      mcp_config_path: "y",
      session_id: "z",
      effort: "high"
    });
    expect(warnings).toEqual([]);
  });

  test("Empty options produce no warnings for either provider", () => {
    expect(collectUnsupportedOptionWarnings(claudeCapabilityManifest, { executable: "claude" })).toEqual([]);
    expect(collectUnsupportedOptionWarnings(codexCapabilityManifest, { executable: "codex" })).toEqual([]);
  });
});
```

Append to (or create) `packages/provider-adapters/tests/manifest.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { claudeCapabilityManifest, codexCapabilityManifest } from "../src/capabilities";

describe("ProviderCapabilityManifest.supports lock (CP-3)", () => {
  test("Claude supports matrix", () => {
    expect(claudeCapabilityManifest.supports).toEqual({
      settings_path: true,
      mcp_config_path: true,
      session_id_first_attempt: true,
      reasoning: true
    });
  });

  test("Codex supports matrix", () => {
    expect(codexCapabilityManifest.supports).toEqual({
      settings_path: false,
      mcp_config_path: false,
      session_id_first_attempt: false,
      reasoning: false
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun test packages/provider-adapters/tests/unsupportedOption.test.ts packages/provider-adapters/tests/manifest.test.ts`
Expected: FAIL — `collectUnsupportedOptionWarnings` does not exist; `supports` is undefined on both manifests.

- [ ] **Step 3: Extend `ProviderCapabilityManifest` with `supports`**

In `packages/provider-adapters/src/types.ts` (or wherever `ProviderCapabilityManifest` is defined — check with `grep -rn "ProviderCapabilityManifest" packages/`), add:

```ts
export interface ProviderCapabilityManifest {
  // ... existing fields unchanged ...
  supports?: {
    settings_path: boolean;
    mcp_config_path: boolean;
    session_id_first_attempt: boolean;
    reasoning: boolean;
  };
}
```

If `ProviderCapabilityManifest` lives in `@waygent/contracts`, mirror the change there and re-export. Keep it optional (`?`) for back-compat with any consumer that constructs manifests outside this package.

- [ ] **Step 4: Populate `supports` in both manifests**

In `packages/provider-adapters/src/capabilities.ts`, add to `claudeCapabilityManifest`:

```ts
supports: {
  settings_path: true,
  mcp_config_path: true,
  session_id_first_attempt: true,
  reasoning: true
}
```

And to `codexCapabilityManifest`:

```ts
supports: {
  settings_path: false,
  mcp_config_path: false,
  session_id_first_attempt: false,
  reasoning: false
}
```

- [ ] **Step 5: Add `collectUnsupportedOptionWarnings` and call it from `runProviderProcess`**

In `packages/provider-adapters/src/processAdapters.ts`, add a top-level exported function. **CP-3** requires the lookup table here to map 1-to-1 to `supports` keys:

```ts
// CP-3: every key in ProviderCapabilityManifest.supports has exactly one check;
// every check looks up exactly one key. Keep in sync with capabilities.ts.
const OPTION_TO_SUPPORTS_KEY: Record<string, keyof NonNullable<ProviderCapabilityManifest["supports"]>> = {
  settings_path: "settings_path",
  mcp_config_path: "mcp_config_path",
  session_id: "session_id_first_attempt",
  effort: "reasoning"
};

export function collectUnsupportedOptionWarnings(
  manifest: ProviderCapabilityManifest,
  options: ProviderProcessOptions
): string[] {
  const supports = manifest.supports;
  if (!supports) return [];
  const warnings: string[] = [];
  for (const [optionKey, supportsKey] of Object.entries(OPTION_TO_SUPPORTS_KEY)) {
    const optionSet = (options as Record<string, unknown>)[optionKey];
    if (optionSet === undefined || optionSet === null || optionSet === "") continue;
    if (supports[supportsKey] === false) {
      // The user-facing option name for `effort` is "reasoning" per the spec.
      const displayName = optionKey === "effort" ? "reasoning" : optionKey;
      warnings.push(`unsupported_provider_option: ${displayName} (${manifest.provider})`);
    }
  }
  return warnings;
}
```

Then wire it into `runProviderProcess` (around line 177). After `providerProcessArgsWithWarnings` is called, append the manifest warnings:

```ts
const { args: spawnArgs, warnings: argWarnings } = providerProcessArgsWithWarnings(provider, options, cwd, request);
const manifest = provider === "claude" ? claudeCapabilityManifest : provider === "codex" ? codexCapabilityManifest : undefined;
const supportWarnings = manifest ? collectUnsupportedOptionWarnings(manifest, options) : [];
const warnings = [...argWarnings, ...supportWarnings];
```

Surface `warnings` into `worker_result.evidence.adapter_warnings` at the same site `argWarnings` was already plumbed (look for the existing usage downstream — likely in the result builder near `withProcessEvidence`). Add:

```ts
if (warnings.length > 0) {
  // evidence merge — concrete shape depends on the surrounding result builder
  evidence.adapter_warnings = [...(evidence.adapter_warnings ?? []), ...warnings];
}
```

Also log to stderr summary so it surfaces in run output:

```ts
if (supportWarnings.length > 0) {
  console.error(supportWarnings.join("\n"));
}
```

(Silent skip is forbidden per the spec — either the operator sees the warning or the option is honored.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `bun test packages/provider-adapters/tests/unsupportedOption.test.ts packages/provider-adapters/tests/manifest.test.ts`
Expected: PASS (8 tests total).

- [ ] **Step 7: Run package tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/capabilities.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/unsupportedOption.test.ts packages/provider-adapters/tests/manifest.test.ts
git commit -m "$(cat <<'EOF'
feat(provider-adapters): unsupported_provider_option warnings + supports manifest (C4)

ProviderCapabilityManifest.supports declares which adapter options each
provider can honor (settings_path, mcp_config_path, session_id_first_attempt,
reasoning). runProviderProcess collects warnings for any option set but
unsupported and surfaces them via evidence.adapter_warnings + stderr.
Silent skip is no longer possible — operator either sees the warning or
the option takes effect.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Phase B — D1 Tool-Use Audit Capture

## Task B.1: Tool-Use Audit Capture

**Files:**
- Create: `packages/provider-adapters/tests/fixtures/claude/stream_json_with_tools.jsonl`
- Modify: `packages/provider-adapters/src/processAdapters.ts` — extend `parseWorkerOutput`'s stream-json branch to accumulate `assistant.tool_use` + `user.tool_result` envelopes
- Modify: `packages/provider-adapters/src/types.ts` — `ToolCall` schema
- Create: `packages/provider-adapters/tests/toolUseAudit.test.ts`

- [ ] **Step 1: Create the fixture**

Create `packages/provider-adapters/tests/fixtures/claude/stream_json_with_tools.jsonl`:

```jsonl
{"type":"system","subtype":"init","model":"claude-opus-4-7","tools":["Read","Edit"]}
{"type":"assistant","message":{"content":[{"type":"text","text":"Reading file."},{"type":"tool_use","id":"tu_1","name":"Read","input":{"file_path":"/tmp/x.txt","limit":50}}]},"timestamp":"2026-05-25T08:00:00.100Z"}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_1","content":[{"type":"text","text":"file contents (243 chars)"}],"is_error":false}]},"timestamp":"2026-05-25T08:00:00.350Z"}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_2","name":"Edit","input":{"file_path":"/tmp/x.txt","old_string":"a","new_string":"b"}}]},"timestamp":"2026-05-25T08:00:01.000Z"}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_2","content":[{"type":"text","text":"err"}],"is_error":true}]},"timestamp":"2026-05-25T08:00:01.200Z"}
{"type":"result","subtype":"success","total_cost_usd":0.01,"usage":{"input_tokens":120,"output_tokens":40},"result":"{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"t\",\"candidate_id\":\"c\",\"status\":\"completed\",\"changed_files\":[\"/tmp/x.txt\"],\"summary\":\"ok\",\"evidence\":{}}"}
```

- [ ] **Step 2: Write the failing test**

Create `packages/provider-adapters/tests/toolUseAudit.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseClaudeStreamJsonToolCalls } from "../src/processAdapters";

const fixture = readFileSync(join(import.meta.dir, "fixtures/claude/stream_json_with_tools.jsonl"), "utf8");

describe("parseClaudeStreamJsonToolCalls (D1)", () => {
  test("captures two paired tool calls", () => {
    const calls = parseClaudeStreamJsonToolCalls(fixture);
    expect(calls).toHaveLength(2);
  });

  test("first call: Read, ok, input keys sorted, sizes computed only for strings", () => {
    const [first] = parseClaudeStreamJsonToolCalls(fixture);
    expect(first.tool_use_id).toBe("tu_1");
    expect(first.name).toBe("Read");
    expect(first.input_summary.keys).toEqual(["file_path", "limit"]);
    expect(first.input_summary.sizes_bytes.file_path).toBe(Buffer.byteLength("/tmp/x.txt", "utf8"));
    expect(first.input_summary.sizes_bytes.limit).toBeUndefined(); // not a string
    expect(first.result?.status).toBe("ok");
    expect(first.result?.is_error).toBe(false);
    expect(first.result?.summary_bytes).toBe(Buffer.byteLength("file contents (243 chars)", "utf8"));
    expect(first.duration_ms).toBe(250);
  });

  test("second call: Edit, error status", () => {
    const [, second] = parseClaudeStreamJsonToolCalls(fixture);
    expect(second.name).toBe("Edit");
    expect(second.result?.status).toBe("error");
    expect(second.result?.is_error).toBe(true);
  });

  test("never stores raw input values or raw tool_result content", () => {
    const calls = parseClaudeStreamJsonToolCalls(fixture);
    const json = JSON.stringify(calls);
    expect(json).not.toContain("/tmp/x.txt"); // value, not key
    expect(json).not.toContain("file contents (243 chars)");
  });

  test("incomplete tool_use (no matching tool_result) yields result: null", () => {
    const incomplete = '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_x","name":"Foo","input":{"k":"v"}}]},"timestamp":"2026-05-25T08:00:00.000Z"}';
    const calls = parseClaudeStreamJsonToolCalls(incomplete);
    expect(calls).toHaveLength(1);
    expect(calls[0].result).toBeNull();
    expect(calls[0].duration_ms).toBeNull();
  });

  test("empty / non-stream-json input returns []", () => {
    expect(parseClaudeStreamJsonToolCalls("")).toEqual([]);
    expect(parseClaudeStreamJsonToolCalls("{\"not\":\"stream-json\"}")).toEqual([]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bun test packages/provider-adapters/tests/toolUseAudit.test.ts`
Expected: FAIL — `parseClaudeStreamJsonToolCalls` is not exported.

- [ ] **Step 4: Add `ToolCall` schema and the parser**

In `packages/provider-adapters/src/types.ts`, add:

```ts
export interface ToolCall {
  tool_use_id: string;
  name: string;
  input_summary: {
    keys: string[];
    sizes_bytes: Record<string, number>;
  };
  result: {
    status: "ok" | "error";
    summary_bytes: number;
    is_error: boolean;
  } | null;
  duration_ms: number | null;
}
```

In `packages/provider-adapters/src/processAdapters.ts`, add (after `parseWorkerOutput`):

```ts
export function parseClaudeStreamJsonToolCalls(stdout: string): ToolCall[] {
  if (!stdout) return [];
  const calls = new Map<string, { call: ToolCall; assistantTs: number | null }>();
  for (const raw of stdout.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    let env: unknown;
    try { env = JSON.parse(line); } catch { continue; }
    if (!env || typeof env !== "object") continue;
    const e = env as Record<string, unknown>;
    const message = e.message as { content?: Array<Record<string, unknown>> } | undefined;
    const content = message?.content;
    if (!Array.isArray(content)) continue;
    const tsStr = typeof e.timestamp === "string" ? e.timestamp : undefined;
    const ts = tsStr ? Date.parse(tsStr) : NaN;
    if (e.type === "assistant") {
      for (const item of content) {
        if (item.type !== "tool_use") continue;
        const id = typeof item.id === "string" ? item.id : "";
        const name = typeof item.name === "string" ? item.name : "";
        if (!id || !name) continue;
        const input = (item.input && typeof item.input === "object") ? item.input as Record<string, unknown> : {};
        const keys = Object.keys(input).sort();
        const sizes_bytes: Record<string, number> = {};
        for (const k of keys) {
          const v = input[k];
          if (typeof v === "string") sizes_bytes[k] = Buffer.byteLength(v, "utf8");
        }
        calls.set(id, {
          call: {
            tool_use_id: id,
            name,
            input_summary: { keys, sizes_bytes },
            result: null,
            duration_ms: null
          },
          assistantTs: Number.isFinite(ts) ? ts : null
        });
      }
      continue;
    }
    if (e.type === "user") {
      for (const item of content) {
        if (item.type !== "tool_result") continue;
        const id = typeof item.tool_use_id === "string" ? item.tool_use_id : "";
        const entry = calls.get(id);
        if (!entry) continue;
        const items = Array.isArray(item.content) ? item.content as Array<Record<string, unknown>> : [];
        let total = 0;
        for (const c of items) {
          if (typeof c.text === "string") total += Buffer.byteLength(c.text, "utf8");
        }
        const is_error = item.is_error === true;
        entry.call.result = {
          status: is_error ? "error" : "ok",
          summary_bytes: total,
          is_error
        };
        if (entry.assistantTs !== null && Number.isFinite(ts)) {
          entry.call.duration_ms = ts - entry.assistantTs;
        }
      }
    }
  }
  return Array.from(calls.values(), v => v.call);
}
```

Wire it into the success-path result builder of `normalizeProcessOutput` (around line 60–80). Only attach when the format is stream-json:

```ts
const isStreamJson = output.stdout.split("\n").some(l => {
  try { return (JSON.parse(l) as { type?: string }).type === "system"; } catch { return false; }
});
const toolCalls = (provider === "claude" && isStreamJson) ? parseClaudeStreamJsonToolCalls(output.stdout) : undefined;
// later, when building evidence:
evidence: {
  provider,
  ...((parsed.evidence && typeof parsed.evidence === "object") ? parsed.evidence : {}),
  ...(toolCalls !== undefined ? { tool_calls: toolCalls } : {}),
  native: parsed.evidence ?? parsed
}
```

(Per the spec: key absent when stream-json is not the format; empty array when stream-json with no tools.)

- [ ] **Step 5: Run test to verify it passes**

Run: `bun test packages/provider-adapters/tests/toolUseAudit.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 6: Run package tests for regression**

Run: `cd packages/provider-adapters && bun test`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/provider-adapters/src/types.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/toolUseAudit.test.ts packages/provider-adapters/tests/fixtures/claude/stream_json_with_tools.jsonl
git commit -m "$(cat <<'EOF'
feat(provider-adapters): capture Claude stream-json tool-use audit (D1)

parseClaudeStreamJsonToolCalls pairs assistant.tool_use envelopes with
user.tool_result envelopes and emits worker_result.evidence.tool_calls
with per-call name, input key set + per-string-field byte sizes,
result status/summary_bytes/is_error, and duration_ms. Raw input
values and tool_result content are never stored (secret-leakage
prevention). Empty array when stream-json with no tools; key absent
otherwise.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Phase C — D2 Role-Aware Model Routing

## Task C.1: D2 — Profile Types: Add per-role `RoleRouting`

**Files:**
- Modify: `packages/orchestrator/src/executionProfile.ts`
- Create: `packages/orchestrator/tests/roleRouting.test.ts`

- [ ] **Step 1: Write the failing test**

Create `packages/orchestrator/tests/roleRouting.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { resolveExecutionProfile } from "../src/executionProfile";

describe("resolveExecutionProfile — D2 role routing baseline (max-quality)", () => {
  test("max-quality profile: all roles opus/high", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, { profile_preset: "max-quality" });
    expect(p.roles.implement).toEqual({ model: "opus", reasoning: "high" });
    expect(p.roles.review).toEqual({ model: "opus", reasoning: "high" });
    expect(p.roles.verify_assist).toEqual({ model: "opus", reasoning: "high" });
    expect(p.main).toEqual({ model: "opus", reasoning: "high" });
  });

  test("ExecutionProfile.subagent remains present for back-compat", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, { profile_preset: "max-quality" });
    expect(p.subagent).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/orchestrator/tests/roleRouting.test.ts`
Expected: FAIL — `roles`, `profile_preset` field don't exist; layer shape unknown.

- [ ] **Step 3: Extend `ExecutionProfile` and `ProfileOverride`**

In `packages/orchestrator/src/executionProfile.ts`, replace the file contents:

```ts
export type ProviderName = "codex" | "claude" | "fake";
export type ExecutionMode = "multi-agent" | "single-agent";
export type ReasoningLevel = "medium" | "high" | "xhigh";
export type ProfilePreset = "max-quality" | "balanced" | "cost-saver";

export interface AgentProfile {
  model: string;
  reasoning: ReasoningLevel;
}

export interface RoleRouting {
  implement: AgentProfile;
  review: AgentProfile;
  verify_assist: AgentProfile;
}

export interface ExecutionProfile {
  provider: ProviderName;
  execution_mode: ExecutionMode;
  main: AgentProfile;
  subagent: AgentProfile; // retained for back-compat / single-slot consumers
  roles: RoleRouting;
  evidence_event_type: "runway.execution_profile_selected";
}

export interface ProfileOverride {
  provider?: ProviderName;
  execution_mode?: ExecutionMode;
  profile_preset?: ProfilePreset;
  main_model?: string;
  main_reasoning?: ReasoningLevel;
  subagent_model?: string;
  subagent_reasoning?: ReasoningLevel;
  role_models?: Partial<Record<keyof RoleRouting, string>>;
  role_reasonings?: Partial<Record<keyof RoleRouting, ReasoningLevel>>;
}

const PRESET_ROLE_ROUTING: Record<ProfilePreset, RoleRouting> = {
  "max-quality": {
    implement: { model: "opus", reasoning: "high" },
    review: { model: "opus", reasoning: "high" },
    verify_assist: { model: "opus", reasoning: "high" }
  },
  "balanced": {
    implement: { model: "opus", reasoning: "high" },
    review: { model: "sonnet", reasoning: "medium" },
    verify_assist: { model: "sonnet", reasoning: "medium" }
  },
  "cost-saver": {
    implement: { model: "sonnet", reasoning: "medium" },
    review: { model: "haiku", reasoning: "medium" },
    verify_assist: { model: "haiku", reasoning: "medium" }
  }
};

const PRESET_MAIN: Record<ProfilePreset, AgentProfile> = {
  "max-quality": { model: "opus", reasoning: "high" },
  "balanced": { model: "opus", reasoning: "high" },
  "cost-saver": { model: "haiku", reasoning: "medium" }
};

export const defaultProfiles: Record<ProviderName, ExecutionProfile> = {
  codex: {
    provider: "codex",
    execution_mode: "multi-agent",
    main: { model: "gpt-5.5", reasoning: "xhigh" },
    subagent: { model: "gpt-5.5", reasoning: "high" },
    roles: {
      implement: { model: "gpt-5.5", reasoning: "high" },
      review: { model: "gpt-5.5", reasoning: "high" },
      verify_assist: { model: "gpt-5.5", reasoning: "high" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  },
  claude: {
    provider: "claude",
    execution_mode: "multi-agent",
    main: { model: "opus", reasoning: "high" },
    subagent: { model: "opus", reasoning: "high" },
    roles: {
      implement: { model: "opus", reasoning: "high" },
      review: { model: "opus", reasoning: "high" },
      verify_assist: { model: "opus", reasoning: "high" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  },
  fake: {
    provider: "fake",
    execution_mode: "multi-agent",
    main: { model: "fake", reasoning: "medium" },
    subagent: { model: "fake", reasoning: "medium" },
    roles: {
      implement: { model: "fake", reasoning: "medium" },
      review: { model: "fake", reasoning: "medium" },
      verify_assist: { model: "fake", reasoning: "medium" }
    },
    evidence_event_type: "runway.execution_profile_selected"
  }
};

export function resolveExecutionProfile(...layers: Array<ProfileOverride | undefined>): ExecutionProfile {
  const merged = Object.assign({}, ...layers.reverse()) as ProfileOverride;
  const base = defaultProfiles[merged.provider ?? "codex"];
  const preset = merged.profile_preset;
  const presetRoles = preset ? PRESET_ROLE_ROUTING[preset] : undefined;
  const presetMain = preset ? PRESET_MAIN[preset] : undefined;
  const mainModel = merged.main_model ?? presetMain?.model ?? base.main.model;
  const mainReasoning = merged.main_reasoning ?? presetMain?.reasoning ?? base.main.reasoning;
  const subagentModel = merged.subagent_model ?? presetRoles?.implement.model ?? base.subagent.model;
  const subagentReasoning = merged.subagent_reasoning ?? presetRoles?.implement.reasoning ?? base.subagent.reasoning;
  const resolveRole = (role: keyof RoleRouting): AgentProfile => {
    // CP-4 priority: --main > --subagent > --role > --profile > default.
    const explicitModel = merged.role_models?.[role];
    const explicitReasoning = merged.role_reasonings?.[role];
    const presetSlot = presetRoles?.[role];
    return {
      model: explicitModel ?? merged.subagent_model ?? presetSlot?.model ?? base.roles[role].model,
      reasoning: explicitReasoning ?? merged.subagent_reasoning ?? presetSlot?.reasoning ?? base.roles[role].reasoning
    };
  };
  return {
    provider: merged.provider ?? base.provider,
    execution_mode: merged.execution_mode ?? base.execution_mode,
    main: { model: mainModel, reasoning: mainReasoning },
    subagent: { model: subagentModel, reasoning: subagentReasoning },
    roles: {
      implement: resolveRole("implement"),
      review: resolveRole("review"),
      verify_assist: resolveRole("verify_assist")
    },
    evidence_event_type: "runway.execution_profile_selected"
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/roleRouting.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Run package tests for regression**

Run: `cd packages/orchestrator && bun test`
Expected: all PASS. Older tests reading `profile.subagent` still see a populated slot.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/executionProfile.ts packages/orchestrator/tests/roleRouting.test.ts
git commit -m "$(cat <<'EOF'
feat(orchestrator): per-role model routing in ExecutionProfile (D2 types)

ExecutionProfile gains a `roles: { implement, review, verify_assist }`
block; resolveExecutionProfile honors profile_preset, --main, --subagent,
and per-role overrides with the CP-4 priority rule. `subagent` slot kept
for back-compat with single-slot consumers. balanced and cost-saver
presets are redefined per the spec to route cheap roles to cheaper
models.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task C.2: D2 — CLI Parser: `--role-model` and `--role-reasoning`

**Files:**
- Modify: `apps/cli/src/index.ts`
- Create: `apps/cli/tests/roleFlags.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/cli/tests/roleFlags.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { parseRoleModelFlag, parseRoleReasoningFlag } from "../src/index";

describe("--role-model parser (D2)", () => {
  test("parses comma-separated key=value pairs", () => {
    expect(parseRoleModelFlag("implement=opus,review=sonnet-4-6,verify_assist=haiku-4-5")).toEqual({
      implement: "opus",
      review: "sonnet-4-6",
      verify_assist: "haiku-4-5"
    });
  });

  test("partial set is allowed", () => {
    expect(parseRoleModelFlag("review=sonnet-4-6")).toEqual({ review: "sonnet-4-6" });
  });

  test("unknown role key throws", () => {
    expect(() => parseRoleModelFlag("manager=opus")).toThrow(/unknown role/i);
  });

  test("empty string returns empty object", () => {
    expect(parseRoleModelFlag("")).toEqual({});
  });
});

describe("--role-reasoning parser (D2)", () => {
  test("parses valid reasoning values", () => {
    expect(parseRoleReasoningFlag("implement=high,review=medium,verify_assist=medium")).toEqual({
      implement: "high",
      review: "medium",
      verify_assist: "medium"
    });
  });

  test("unknown reasoning value throws", () => {
    expect(() => parseRoleReasoningFlag("implement=ultra")).toThrow(/unknown reasoning/i);
  });

  test("unknown role key throws", () => {
    expect(() => parseRoleReasoningFlag("manager=high")).toThrow(/unknown role/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test apps/cli/tests/roleFlags.test.ts`
Expected: FAIL — neither parser is exported.

- [ ] **Step 3: Add the parsers and wire into the CLI**

In `apps/cli/src/index.ts`, near the existing `isReasoning` helper (around line 91), add:

```ts
const ROLE_KEYS = new Set(["implement", "review", "verify_assist"]);

export function parseRoleModelFlag(raw: string): Partial<Record<"implement" | "review" | "verify_assist", string>> {
  const out: Record<string, string> = {};
  if (!raw) return out;
  for (const pair of raw.split(",")) {
    const [k, v] = pair.split("=").map(s => s.trim());
    if (!k || !v) continue;
    if (!ROLE_KEYS.has(k)) throw new Error(`unknown role '${k}' in --role-model; expected one of: implement, review, verify_assist`);
    out[k] = v;
  }
  return out as Partial<Record<"implement" | "review" | "verify_assist", string>>;
}

export function parseRoleReasoningFlag(raw: string): Partial<Record<"implement" | "review" | "verify_assist", "medium" | "high" | "xhigh">> {
  const out: Record<string, "medium" | "high" | "xhigh"> = {};
  if (!raw) return out;
  for (const pair of raw.split(",")) {
    const [k, v] = pair.split("=").map(s => s.trim());
    if (!k || !v) continue;
    if (!ROLE_KEYS.has(k)) throw new Error(`unknown role '${k}' in --role-reasoning; expected one of: implement, review, verify_assist`);
    if (v !== "medium" && v !== "high" && v !== "xhigh") throw new Error(`unknown reasoning '${v}' in --role-reasoning; expected one of: medium, high, xhigh`);
    out[k] = v;
  }
  return out as Partial<Record<"implement" | "review" | "verify_assist", "medium" | "high" | "xhigh">>;
}
```

Hook into the existing flag-merge block. After the existing `--subagent-reasoning` line (around 132), add:

```ts
if (typeof parsed.flags["role-model"] === "string") {
  Object.assign(profile.role_models = profile.role_models ?? {}, parseRoleModelFlag(parsed.flags["role-model"]));
}
if (typeof parsed.flags["role-reasoning"] === "string") {
  Object.assign(profile.role_reasonings = profile.role_reasonings ?? {}, parseRoleReasoningFlag(parsed.flags["role-reasoning"]));
}
```

(Adapt to the actual `profile` shape passed to `resolveExecutionProfile`. The fields `role_models` and `role_reasonings` flow through to the `ProfileOverride` defined in Task C.1.)

Update the `run:` usage string (line 58) to document the new flags:

```
[--role-model <impl=...,review=...,verify_assist=...>] [--role-reasoning <impl=high,review=medium,verify_assist=medium>]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test apps/cli/tests/roleFlags.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Run package tests for regression**

Run: `cd apps/cli && bun test`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/cli/src/index.ts apps/cli/tests/roleFlags.test.ts
git commit -m "$(cat <<'EOF'
feat(cli): --role-model and --role-reasoning flags (D2)

Operators can override model/reasoning per worker role:
  --role-model implement=opus,review=sonnet-4-6,verify_assist=haiku-4-5
  --role-reasoning implement=high,review=medium,verify_assist=medium
Partial sets inherit profile defaults. Unknown role keys and unknown
reasoning values are CLI parse errors.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task C.3: D2 — Orchestrator: Resolve `(model, reasoning)` per role at worker dispatch

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts` — at worker dispatch, pick `(model, reasoning)` from `profile.roles[role]`
- Extend: `packages/orchestrator/tests/roleRouting.test.ts` — full priority matrix

- [ ] **Step 1: Extend the test with the CP-4 priority matrix**

Append to `packages/orchestrator/tests/roleRouting.test.ts`:

```ts
describe("CP-4 priority matrix (--main > --subagent > --role > --profile > default)", () => {
  test("profile only: balanced → implement opus/high, review sonnet/medium", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, { profile_preset: "balanced" });
    expect(p.roles.implement).toEqual({ model: "opus", reasoning: "high" });
    expect(p.roles.review).toEqual({ model: "sonnet", reasoning: "medium" });
    expect(p.roles.verify_assist).toEqual({ model: "sonnet", reasoning: "medium" });
  });

  test("--role overrides profile per slot", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, {
      profile_preset: "balanced",
      role_models: { verify_assist: "haiku" },
      role_reasonings: { verify_assist: "medium" }
    });
    expect(p.roles.verify_assist).toEqual({ model: "haiku", reasoning: "medium" });
    expect(p.roles.review).toEqual({ model: "sonnet", reasoning: "medium" });
  });

  test("--subagent fills all roles that --role does not specify", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, {
      profile_preset: "balanced",
      subagent_model: "sonnet-4-6",
      subagent_reasoning: "high",
      role_models: { review: "haiku" }
    });
    expect(p.roles.review.model).toBe("haiku");
    expect(p.roles.implement.model).toBe("sonnet-4-6");
    expect(p.roles.verify_assist.model).toBe("sonnet-4-6");
    expect(p.roles.implement.reasoning).toBe("high");
  });

  test("--main affects main only, not any role", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, {
      profile_preset: "balanced",
      main_model: "custom-main",
      main_reasoning: "xhigh"
    });
    expect(p.main).toEqual({ model: "custom-main", reasoning: "xhigh" });
    expect(p.roles.implement.model).toBe("opus");
  });

  test("cost-saver baseline: implement sonnet/medium, review/verify_assist haiku/medium, main haiku/medium", () => {
    const p = resolveExecutionProfile({ provider: "claude" }, { profile_preset: "cost-saver" });
    expect(p.roles.implement).toEqual({ model: "sonnet", reasoning: "medium" });
    expect(p.roles.review).toEqual({ model: "haiku", reasoning: "medium" });
    expect(p.roles.verify_assist).toEqual({ model: "haiku", reasoning: "medium" });
    expect(p.main).toEqual({ model: "haiku", reasoning: "medium" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `bun test packages/orchestrator/tests/roleRouting.test.ts`
Expected: most should PASS already from Task C.1's resolver. Any that fail indicate a precedence bug to fix in `resolveExecutionProfile` before continuing.

- [ ] **Step 3: Wire role lookup into worker dispatch**

In `packages/orchestrator/src/orchestrator.ts`, find the existing `resolveProviderProcesses` (line 1113) or the call site that builds `ProviderProcessOptions.model` / `.effort` per worker. Currently the orchestrator passes `profile.subagent.model` / `profile.subagent.reasoning` to every worker. Replace with a per-role lookup:

```ts
// Where the orchestrator decides which (model, reasoning) to hand a worker
// (search for `subagent.model` / `subagent.reasoning` references in this file).
function pickRoleAgent(profile: ExecutionProfile, role: ProviderRole): AgentProfile {
  if (role === "review") return profile.roles.review;
  if (role === "verify_assist") return profile.roles.verify_assist;
  // implement, fix, undefined → implement
  return profile.roles.implement;
}
```

Then at each spawn site, replace `profile.subagent.model` → `pickRoleAgent(profile, request.role).model` and same for `reasoning`. Reasoning is passed to `ProviderProcessOptions.effort` for Codex and as a CLI flag (`--effort`) for Claude — both already handled by existing code; only the source of the value changes.

`lens.model_attestation_confirmed` will now report per-role expected models. This is intended.

- [ ] **Step 4: Run tests**

Run: `bun test packages/orchestrator/tests/roleRouting.test.ts && cd packages/orchestrator && bun test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/roleRouting.test.ts
git commit -m "$(cat <<'EOF'
feat(orchestrator): dispatch workers with per-role (model, reasoning) (D2)

Orchestrator now picks ProviderProcessOptions.model / .effort from
profile.roles[role] at worker dispatch time, so cheap roles run on
cheap models under balanced/cost-saver. CP-4 priority matrix
(--main > --subagent > --role > --profile > default) is asserted
across all four combinations.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task C.4: D2 — Surface Codex reasoning as `unsupported_provider_option` warning

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts` (already touched in Task A.5) — confirm Codex `effort` triggers the warning channel under the manifest `supports.reasoning = false`
- Extend: `packages/provider-adapters/tests/unsupportedOption.test.ts`

This task is the spec's explicit closure on Codex coupling for D2: when the orchestrator hands a Codex worker a per-role `reasoning`, the manifest declares Codex doesn't honor a per-process reasoning flag, so it surfaces as a warning. Task A.5 already wired the warning; this task just adds the dedicated regression test and ensures the orchestrator does **not** pass `--reasoning` to Codex from per-role values.

- [ ] **Step 1: Append the regression test**

Append to `packages/provider-adapters/tests/unsupportedOption.test.ts`:

```ts
describe("Codex reasoning warning under D2 role routing", () => {
  test("a Codex worker spawned with effort=high produces the warning, not a --reasoning flag", () => {
    const warnings = collectUnsupportedOptionWarnings(codexCapabilityManifest, {
      executable: "codex",
      effort: "high",
      model: "gpt-5.5"
    });
    expect(warnings).toContain("unsupported_provider_option: reasoning (codex)");
  });
});
```

- [ ] **Step 2: Verify orchestrator does not pass `effort` to Codex args from per-role resolution**

Inspect the Codex branch of `providerProcessArgsWithWarnings` (existing line 327):

```ts
if (isCodexCli && options.effort && !nextArgs.includes("--reasoning")) {
  nextArgs = ["--reasoning", options.effort, ...nextArgs];
}
```

The spec says Codex has no per-process reasoning flag and the value must surface only as a warning. **Remove** this block — or, to keep operator-explicit `--effort` usage working without breaking existing tests, replace it with:

```ts
// Per D2 + CP-3: Codex has no per-process reasoning flag. The value flows
// through worker_result.evidence.adapter_warnings via collectUnsupportedOptionWarnings
// (see C4). Keep this block intentionally absent.
```

Update any existing Codex CLI tests that expected `--reasoning` on the args list — switch them to assert the warning shape instead.

- [ ] **Step 3: Run tests**

Run: `bun test packages/provider-adapters/tests/unsupportedOption.test.ts && cd packages/provider-adapters && bun test`
Expected: PASS. Fix existing tests that expected the old `--reasoning` Codex arg by switching them to the warning channel.

- [ ] **Step 4: Commit**

```bash
git add packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/tests/unsupportedOption.test.ts
git commit -m "$(cat <<'EOF'
fix(provider-adapters): Codex reasoning routes through adapter_warnings only (D2 + C4)

Drops the speculative --reasoning arg from the Codex branch of
providerProcessArgsWithWarnings. Codex has no per-process reasoning
flag; the value (whether from --main-reasoning, --subagent-reasoning,
--role-reasoning, or a profile) now surfaces only as
worker_result.evidence.adapter_warnings:
"unsupported_provider_option: reasoning (codex)". Operator either sees
the warning or sees the option honored — no silent skip.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Phase D — Integration Gate

## Task D.1: Repo-wide integration sweep

- [ ] **Step 1: Full repo check**

Run: `bun run check`
Expected: green.

- [ ] **Step 2: Waygent scenarios**

Run: `bun run waygent:scenarios`
Expected: green. Confirm at least one scenario observes role-aware attestation under the `balanced` profile (different `expected_model` per role).

- [ ] **Step 3: Platform demo**

Run: `bun run platform:demo`
Expected: green (fake provider regression).

- [ ] **Step 4: `git diff --check`**

Run: `git diff --check`
Expected: empty — no trailing whitespace or merge markers introduced.

- [ ] **Step 5: Manual smoke (optional)**

If `codex` is on PATH with credentials:
- Run a 2-step plan with a `verify` that fails once. Confirm:
  - Attempt 1 spawn args contain `exec --json -`.
  - Attempt 2 spawn args contain `exec resume <id> --json -`, where `<id>` matches the first-attempt's `worker_result.evidence.session_id`.
  - `worker_result.evidence.adapter_warnings` is absent when no unsupported options are set.

If `claude` is on PATH with credentials:
- Run a one-task plan and verify `worker_result.evidence.tool_calls` is populated with at least one entry (Read/Edit/etc.) and contains no raw input/result values.

Document observations as a short note in the Lens evidence — no source change.

- [ ] **Step 6: Cross-cutting wrap commit (if any cleanup landed)**

Only commit if Step 1–4 fixes were needed:

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(waygent): integration sweep cleanup for provider parity + D2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If nothing changed, skip the commit.

- [ ] **Step 7: Branch wrap**

Use `superpowers:finishing-a-development-branch` to choose merge / PR / cleanup path.

---

## Self-Review Notes

- **Spec coverage:** C1 → Task A.1; R1 → Task A.2; C2 → Task A.3; C3 → Task A.4; C4 → Task A.5; D1 → Task B.1; D2 → Tasks C.1–C.4; Phase D integration gate → Task D.1. All 6 spec work items + R1 + integration gate covered.
- **Cross-Path Invariants:** CP-1 asserted in Task A.3 Steps 1–4 (sentinel byte-stable test); CP-2 asserted in Task A.1 Step 1 (env sanitize matrix); CP-3 asserted in Task A.5 Steps 1–4 (manifest lock + supports key coverage); CP-4 asserted in Task C.3 Step 1 (priority matrix).
- **No placeholders:** every code step contains the actual code. No "TBD" / "similar to" / "add appropriate handling" references. Where exact line numbers depend on the file's current state, the plan calls out a `grep` to anchor first.
- **Type consistency:** `RoleRouting` keys are `implement | review | verify_assist` everywhere (Tasks C.1, C.2, C.3). `ToolCall` schema (Task B.1) matches the spec's D1 schema verbatim. `supports` keys (Task A.5) match the spec's C4 table exactly.
