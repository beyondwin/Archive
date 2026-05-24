# Waygent Android Intake Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent safely normalize and execute Android/Kotlin Superpowers plans with Gradle verification while adding evidence for intake repair, provider capability, wave barriers, and adjacent contract risk.

**Architecture:** Introduce shared plan extraction and verification policy modules, then refactor normalization, deterministic recovery, and preflight to use them. Add additive evidence artifacts/events around intake, provider capability, execution barriers, and contract-audit candidates without changing the native `waygent-task` format.

**Tech Stack:** TypeScript, Bun test, Waygent orchestrator packages, provider adapters, Lens artifacts/events, Graphify.

---

## File Structure

- Create `packages/orchestrator/src/planAdapters/commandLines.ts`
  - Owns shell-line normalization for fenced command blocks.
- Create `packages/orchestrator/src/planAdapters/verificationPolicy.ts`
  - Owns shared safe/unsafe verification classification.
- Create `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`
  - Owns Superpowers task section, explicit file claim, prose path, and fenced command extraction.
- Create `packages/orchestrator/src/intakeRepairPlanner.ts`
  - Merges strict normalization and deterministic recovery evidence into task-level intake status.
- Create `packages/orchestrator/src/adjacentContractAudit.ts`
  - Emits advisory contract candidates for trust-sensitive plans.
- Create `packages/orchestrator/src/executionDependencyBarrier.ts`
  - Adds conservative task dependencies and barrier events for Gradle/module verification overlap.
- Create `packages/provider-adapters/src/capabilityProbe.ts`
  - Probes local provider CLI help and sanitizes unsupported optional process flags.
- Create tests:
  - `packages/orchestrator/tests/verificationPolicy.test.ts`
  - `packages/orchestrator/tests/planClaimExtraction.test.ts`
  - `packages/orchestrator/tests/intakeRepairPlanner.test.ts`
  - `packages/orchestrator/tests/adjacentContractAudit.test.ts`
  - `packages/orchestrator/tests/executionDependencyBarrier.test.ts`
  - `packages/provider-adapters/tests/capabilityProbe.test.ts`
  - `tests/integration/waygent-android-intake-trust.test.ts`
- Modify `packages/orchestrator/src/planNormalizer.ts`
  - Replace local Superpowers extraction and safe command checks with shared modules.
- Modify `packages/orchestrator/src/intakeRecovery.ts`
  - Replace narrow fallback regex/allowlist with shared modules and merge planner.
- Modify `packages/orchestrator/src/planPreflight.ts`
  - Replace local safe command checks with shared verification policy.
- Modify `packages/orchestrator/src/orchestrator.ts`
  - Write intake extract artifacts, provider capability artifact, barrier events, and contract-audit findings.
- Modify `packages/orchestrator/src/index.ts`
  - Export new orchestrator helpers needed by tests and CLI users.
- Modify `packages/provider-adapters/src/processAdapters.ts`
  - Use sanitized provider options when building process args.
- Modify `packages/provider-adapters/src/index.ts`
  - Export capability probe helpers.
- Modify `packages/contracts/src/types.ts`
  - Add optional additive fields to `WaygentIntakeRecovery`.

---

### Task 1: Add Shared Command And Verification Policy

**Files:**
- Create: `packages/orchestrator/src/planAdapters/commandLines.ts`
- Create: `packages/orchestrator/src/planAdapters/verificationPolicy.ts`
- Create: `packages/orchestrator/tests/verificationPolicy.test.ts`

- [ ] **Step 1: Write failing verification policy tests**

Create `packages/orchestrator/tests/verificationPolicy.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { classifyVerificationCommand } from "../src/planAdapters/verificationPolicy";
import type { ProjectScriptCatalog } from "../src/planAdapters/projectScriptCatalog";

const catalog: ProjectScriptCatalog = {
  workspace_root: "/repo",
  commands: new Set([
    "npm run source-matching:fixtures:test",
    "pnpm run check",
    "bun run waygent:fixture-lab"
  ]),
  sources: new Map([
    ["npm run source-matching:fixtures:test", "npm"],
    ["pnpm run check", "pnpm"],
    ["bun run waygent:fixture-lab", "bun"]
  ])
};

function classify(command: string) {
  return classifyVerificationCommand({
    command,
    workspace: "/repo",
    catalog
  });
}

describe("verification policy", () => {
  test("accepts Android Gradle verification commands", () => {
    expect(classify('./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon')).toMatchObject({
      status: "safe",
      reason: "gradle_wrapper"
    });
    expect(classify("gradle test")).toMatchObject({
      status: "safe",
      reason: "gradle"
    });
  });

  test("accepts node test and declared package scripts", () => {
    expect(classify("node --test scripts/source-matching-fixtures-test.mjs")).toMatchObject({
      status: "safe",
      reason: "node_test"
    });
    expect(classify("npm run source-matching:fixtures:test")).toMatchObject({
      status: "safe",
      reason: "package_script"
    });
  });

  test("rejects undeclared scripts and destructive command chains", () => {
    expect(classify("npm run unknown-script")).toMatchObject({
      status: "unsafe",
      reason: "unknown"
    });
    expect(classify("npm test && rm -rf build")).toMatchObject({
      status: "unsafe",
      reason: "destructive"
    });
  });

  test("allows workspace cd only as the first safe segment", () => {
    expect(classify("cd packages/orchestrator && bun test tests/planNormalizer.test.ts")).toMatchObject({
      status: "safe",
      reason: "known_runner"
    });
    expect(classify("cd ../outside && bun test")).toMatchObject({
      status: "unsafe",
      reason: "workspace_escape"
    });
  });

  test("keeps every command segment in the evidence", () => {
    const result = classify("cd packages/orchestrator && bun test tests/planNormalizer.test.ts");
    expect(result.segments.map((segment) => segment.command)).toEqual([
      "cd packages/orchestrator",
      "bun test tests/planNormalizer.test.ts"
    ]);
    expect(result.segments.every((segment) => segment.status === "safe")).toBe(true);
  });
});
```

- [ ] **Step 2: Run the policy tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts
```

Expected: FAIL because `packages/orchestrator/src/planAdapters/verificationPolicy.ts` does not exist.

- [ ] **Step 3: Add shared logical command parsing**

Create `packages/orchestrator/src/planAdapters/commandLines.ts`:

```ts
export function logicalCommandLines(raw: string): string[] {
  const commands: string[] = [];
  let current = "";
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (trimmed.endsWith("\\")) {
      current += `${trimmed.slice(0, -1).trim()} `;
      continue;
    }
    commands.push(`${current}${trimmed}`.trim());
    current = "";
  }
  if (current.trim()) commands.push(current.trim());
  return commands;
}

export function commandSegments(command: string): string[] {
  return command
    .replace(/\s+/g, " ")
    .trim()
    .split(/\s+&&\s+/)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

export function commandTokens(command: string): string[] {
  return command
    .split(/\s+/)
    .map((token) => token.replace(/^['"]|['"]$/g, ""))
    .filter(Boolean);
}
```

- [ ] **Step 4: Add shared verification policy**

Create `packages/orchestrator/src/planAdapters/verificationPolicy.ts`:

```ts
import { isAbsolute, resolve } from "node:path";
import { commandSegments, commandTokens } from "./commandLines";
import { isCommandInCatalog, type ProjectScriptCatalog } from "./projectScriptCatalog";

export type VerificationClassificationStatus = "safe" | "unsafe" | "ignored";

export type VerificationClassificationReason =
  | "gradle_wrapper"
  | "gradle"
  | "node_test"
  | "package_script"
  | "known_runner"
  | "git_diff_check"
  | "destructive"
  | "workspace_escape"
  | "unknown";

export interface VerificationCommandSegment {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
}

export interface VerificationPolicyInput {
  command: string;
  workspace: string;
  catalog: ProjectScriptCatalog | null;
}

export interface VerificationClassification {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
  segments: VerificationCommandSegment[];
}

const destructivePattern = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;
const knownPrefixes = [
  "bun test",
  "bun run test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run platform:demo",
  "bun run waygent:scenarios",
  "bun run waygent:dogfood",
  "bun run waygent:fixture-lab",
  "cargo test",
  "npm test",
  "npm run test",
  "pnpm test",
  "pnpm run test",
  "yarn test",
  "test ",
  "printf "
];

export function classifyVerificationCommand(input: VerificationPolicyInput): VerificationClassification {
  const segments = commandSegments(input.command).map((segment, index) =>
    classifySegment(segment, index, input.workspace, input.catalog)
  );
  const unsafe = segments.find((segment) => segment.status === "unsafe");
  if (unsafe) {
    return { command: input.command, status: "unsafe", reason: unsafe.reason, segments };
  }
  const safe = [...segments].reverse().find((segment) => segment.status === "safe");
  return {
    command: input.command,
    status: safe ? "safe" : "ignored",
    reason: safe?.reason ?? "unknown",
    segments
  };
}

export function isSafeVerificationCommand(input: VerificationPolicyInput): boolean {
  return classifyVerificationCommand(input).status === "safe";
}

function classifySegment(
  segment: string,
  index: number,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): VerificationCommandSegment {
  if (!segment) return { command: segment, status: "ignored", reason: "unknown" };
  if (destructivePattern.test(segment)) return { command: segment, status: "unsafe", reason: "destructive" };
  if (/[|;`]/.test(segment) || /\s[12]?>/.test(segment)) {
    return { command: segment, status: "unsafe", reason: "unknown" };
  }
  if (segment.startsWith("cd ")) {
    if (index !== 0 || !cdStaysInsideWorkspace(segment, workspace)) {
      return { command: segment, status: "unsafe", reason: "workspace_escape" };
    }
    return { command: segment, status: "safe", reason: "known_runner" };
  }
  if (segment.startsWith("./gradlew ")) return { command: segment, status: "safe", reason: "gradle_wrapper" };
  if (segment === "./gradlew") return { command: segment, status: "safe", reason: "gradle_wrapper" };
  if (segment.startsWith("gradle ")) return { command: segment, status: "safe", reason: "gradle" };
  if (segment.startsWith("node --test")) return { command: segment, status: "safe", reason: "node_test" };
  if (segment.startsWith("git diff --check")) return { command: segment, status: "safe", reason: "git_diff_check" };
  if (catalog && isCommandInCatalog(segment, catalog)) {
    return { command: segment, status: "safe", reason: "package_script" };
  }
  if (knownPrefixes.some((prefix) => segment === prefix.trim() || segment.startsWith(prefix))) {
    return { command: segment, status: "safe", reason: "known_runner" };
  }
  return { command: segment, status: "unsafe", reason: "unknown" };
}

function cdStaysInsideWorkspace(segment: string, workspace: string): boolean {
  const target = commandTokens(segment)[1];
  if (!target) return false;
  const resolved = isAbsolute(target) ? resolve(target) : resolve(workspace, target);
  const root = resolve(workspace);
  return resolved === root || resolved.startsWith(`${root}/`);
}
```

- [ ] **Step 5: Run the policy tests and verify success**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add packages/orchestrator/src/planAdapters/commandLines.ts \
  packages/orchestrator/src/planAdapters/verificationPolicy.ts \
  packages/orchestrator/tests/verificationPolicy.test.ts
git commit -m "feat: add shared verification policy"
```

---

### Task 2: Add Shared Superpowers Claim Extraction

**Files:**
- Create: `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`
- Create: `packages/orchestrator/tests/planClaimExtraction.test.ts`

- [ ] **Step 1: Write failing extraction tests**

Create `packages/orchestrator/tests/planClaimExtraction.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { extractSuperpowersPlan } from "../src/planAdapters/planClaimExtraction";

const androidPlan = `
# Android Intake Plan

### Task 1: Android Claims

**Files:**
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`
- Modify: \`fixthis-compose-core/src/main/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceMatcher.kt\`
- Modify: \`fixthis-gradle-plugin/src/main/kotlin/io/github/beyondwin/fixthis/gradle/source/KotlinSourceScanner.kt\`
- Modify: \`fixthis-gradle-plugin/build.gradle.kts\`
- Modify: \`scripts/source-matching-fixtures-test.mjs\`
- Read: \`docs/reference/output-schema.md\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
node --test scripts/source-matching-fixtures-test.mjs
\`\`\`

\`\`\`kotlin
val sample = """
## Task 99: Not A Real Task
"""
\`\`\`

### Task 2: Prose Claim Recovery

Inspect \`fixthis-compose-core/src/main/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceIndex.kt\`
and update \`docs/reference/source-matching.md\`.

Run:

\`\`\`bash
git diff --check
\`\`\`
`;

describe("Superpowers plan claim extraction", () => {
  test("extracts Android and Kotlin explicit file claims", () => {
    const extracted = extractSuperpowersPlan(androidPlan);
    expect(extracted.tasks).toHaveLength(2);
    expect(extracted.tasks[0]?.explicit_file_claims).toEqual([
      { path: "fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt", mode: "owned" },
      { path: "fixthis-compose-core/src/main/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceMatcher.kt", mode: "owned" },
      { path: "fixthis-gradle-plugin/src/main/kotlin/io/github/beyondwin/fixthis/gradle/source/KotlinSourceScanner.kt", mode: "owned" },
      { path: "fixthis-gradle-plugin/build.gradle.kts", mode: "owned" },
      { path: "scripts/source-matching-fixtures-test.mjs", mode: "owned" },
      { path: "docs/reference/output-schema.md", mode: "read_only" }
    ]);
  });

  test("extracts fenced commands and masks headings inside code fences", () => {
    const extracted = extractSuperpowersPlan(androidPlan);
    expect(extracted.tasks.map((task) => task.number)).toEqual([1, 2]);
    expect(extracted.tasks[0]?.fenced_commands).toEqual([
      './gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon',
      "node --test scripts/source-matching-fixtures-test.mjs"
    ]);
  });

  test("recovers prose paths with Kotlin and Markdown extensions", () => {
    const extracted = extractSuperpowersPlan(androidPlan);
    expect(extracted.tasks[1]?.prose_file_claims).toEqual([
      { path: "fixthis-compose-core/src/main/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceIndex.kt", mode: "read_only" },
      { path: "docs/reference/source-matching.md", mode: "owned" }
    ]);
  });
});
```

- [ ] **Step 2: Run extraction tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts
```

Expected: FAIL because `planClaimExtraction.ts` does not exist.

- [ ] **Step 3: Create the shared extractor**

Create `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`:

```ts
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import { logicalCommandLines } from "./commandLines";

export interface ExtractedPlanTask {
  number: number;
  title: string;
  body: string;
  explicit_file_claims: FileClaim[];
  prose_file_claims: FileClaim[];
  fenced_commands: string[];
}

export interface ExtractedSuperpowersPlan {
  tasks: ExtractedPlanTask[];
}

const taskHeading = /^#{2,4}\s+(?:Task|작업|Phase)\s+(\d+)\s*[:.)-]?\s*(.*)$/gim;
const explicitClaim = /^\s*-\s+(Create|Modify|Read|Append):\s+`([^`]+)`/gim;
const fencedCommand = /```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;
const inlinePath = /`([^`]+\.(?:ts|tsx|js|jsx|mjs|json|md|mdx|toml|yaml|yml|rs|py|sh|css|html|kt|kts|gradle|gradle\.kts|java|xml))`/g;

export function extractSuperpowersPlan(markdown: string): ExtractedSuperpowersPlan {
  const masked = maskFencedCodeBlocks(markdown);
  const headings = [...masked.matchAll(taskHeading)];
  const tasks = headings.map((match, index): ExtractedPlanTask => {
    const start = match.index ?? 0;
    const nextIndex = index + 1 < headings.length ? headings[index + 1]!.index : undefined;
    const end = typeof nextIndex === "number" ? nextIndex : markdown.length;
    const number = Number(match[1]);
    const title = (match[2] ?? "").trim() || `Task ${number}`;
    const body = markdown.slice(start, end);
    const explicit = extractExplicitFileClaims(body);
    const prose = extractProseFileClaims(body, explicit);
    return {
      number,
      title,
      body,
      explicit_file_claims: explicit,
      prose_file_claims: prose,
      fenced_commands: extractFencedCommands(body)
    };
  });
  return { tasks };
}

export function maskFencedCodeBlocks(markdown: string): string {
  return markdown.replace(/(^|\n)(```[^\n]*\n)([\s\S]*?)(\n```)/g, (_match, lead: string, opener: string, body: string, closer: string) => {
    const sanitized = body.replace(/[^\n]/g, " ");
    return `${lead}${opener}${sanitized}${closer}`;
  });
}

export function extractExplicitFileClaims(section: string): FileClaim[] {
  const claims: FileClaim[] = [];
  for (const match of section.matchAll(explicitClaim)) {
    const verb = (match[1] ?? "").toLowerCase();
    const path = (match[2] ?? "").trim();
    if (!path || path.includes("..")) continue;
    claims.push({ path, mode: claimModeForVerb(verb) });
  }
  return dedupeClaims(claims);
}

export function extractProseFileClaims(section: string, explicitClaims: FileClaim[] = []): FileClaim[] {
  const explicitPaths = new Set(explicitClaims.map((claim) => claim.path));
  const claims: FileClaim[] = [];
  for (const match of section.matchAll(inlinePath)) {
    const path = (match[1] ?? "").trim();
    if (!path || path.includes("..") || explicitPaths.has(path)) continue;
    claims.push({ path, mode: inferClaimMode(section, path) });
  }
  return dedupeClaims(claims);
}

export function extractFencedCommands(section: string): string[] {
  const commands = [...section.matchAll(fencedCommand)]
    .flatMap((match) => logicalCommandLines(match[1] ?? ""));
  return [...new Set(commands)];
}

function claimModeForVerb(verb: string): FileClaimMode {
  if (verb === "read") return "read_only";
  if (verb === "append") return "shared_append";
  return "owned";
}

function inferClaimMode(body: string, path: string): FileClaimMode {
  const index = body.indexOf(path);
  const before = body.slice(Math.max(0, index - 80), index).toLowerCase();
  if (/\b(read|inspect|review)\b/.test(before)) return "read_only";
  if (/\b(append|add to)\b/.test(before)) return "shared_append";
  return "owned";
}

function dedupeClaims(claims: FileClaim[]): FileClaim[] {
  const byPath = new Map<string, FileClaim>();
  for (const claim of claims) {
    const existing = byPath.get(claim.path);
    if (!existing || existing.mode === "read_only") byPath.set(claim.path, claim);
  }
  return [...byPath.values()];
}
```

- [ ] **Step 4: Run extraction tests and verify success**

Run:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add packages/orchestrator/src/planAdapters/planClaimExtraction.ts \
  packages/orchestrator/tests/planClaimExtraction.test.ts
git commit -m "feat: extract Superpowers plan claims"
```

---

### Task 3: Refactor Normalizer And Preflight Onto Shared Policy

**Files:**
- Modify: `packages/orchestrator/src/planNormalizer.ts`
- Modify: `packages/orchestrator/src/planPreflight.ts`
- Modify: `packages/orchestrator/tests/planNormalizer.test.ts`
- Modify: `packages/orchestrator/tests/planPreflight.test.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Add failing normalizer regression for FixThis-style Gradle tasks**

Append this test to `packages/orchestrator/tests/planNormalizer.test.ts`:

```ts
test("normalizes Android Kotlin tasks with Gradle verification", () => {
  const normalized = normalizeWaygentPlanInput({
    path: "/tmp/source-matching-trust-program.md",
    workspace: "/tmp/repo",
    markdown: `
# Source Matching Trust Program

### Task 3: Improve Precise And Compact Handoff Trust Wording

**Files:**
- Modify: \`fixthis-mcp/src/test/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatterTest.kt\`
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --tests "*CopyPromptEditSurfaceRendererTest" --no-daemon
\`\`\`

### Task 4: Strengthen Core Confidence Cap Tests

**Files:**
- Modify: \`fixthis-compose-core/src/test/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceMatcherTest.kt\`
- Modify: \`fixthis-compose-core/src/main/kotlin/io/github/beyondwin/fixthis/compose/core/source/SourceMatcher.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --tests "*TargetReliabilityCalculatorTest" --no-daemon
\`\`\`
`
  });

  const parsed = parseWaygentPlan(normalized.markdown);
  expect(normalized.mode).toBe("superpowers");
  expect(normalized.task_count).toBe(2);
  expect(parsed.tasks[0]?.verification_commands).toEqual([
    './gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --tests "*CopyPromptEditSurfaceRendererTest" --no-daemon'
  ]);
  expect(parsed.tasks[0]?.file_claims.map((claim) => claim.path)).toContain(
    "fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt"
  );
});
```

- [ ] **Step 2: Add failing preflight regression for the same Gradle command**

Append this test to `packages/orchestrator/tests/planPreflight.test.ts`:

```ts
test("accepts normalized Gradle verification commands that the normalizer accepted", () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-preflight-gradle-"));
  const normalized = {
    path: join(workspace, "plan.md"),
    markdown: `
\`\`\`yaml waygent-task
id: task_gradle
title: Gradle
dependencies: []
file_claims:
  - path: fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt
    mode: owned
risk: high
verify:
  - ./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
\`\`\`
`,
    mode: "superpowers" as const,
    task_count: 1,
    diagnostics: []
  };

  const result = runPlanPreflight({
    workspace,
    plan_path: normalized.path,
    normalized_plan: normalized,
    spec_path: null
  });

  expect(result.status).toBe("passed");
  expect(result.errors).toEqual([]);
});
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/planPreflight.test.ts
```

Expected: FAIL because Gradle verification is still rejected by local allowlists.

- [ ] **Step 4: Refactor `planNormalizer.ts` imports**

In `packages/orchestrator/src/planNormalizer.ts`, replace the existing imports from `projectScriptCatalog` and remove local regex constants for task headings, file claims, run blocks, and safe command starts. Add these imports:

```ts
import {
  buildProjectScriptCatalog,
  type ProjectScriptCatalog
} from "./planAdapters/projectScriptCatalog";
import { extractSuperpowersPlan, type ExtractedPlanTask } from "./planAdapters/planClaimExtraction";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
import { commandTokens } from "./planAdapters/commandLines";
```

- [ ] **Step 5: Replace normalizer section extraction and command extraction**

In `packages/orchestrator/src/planNormalizer.ts`, replace `extractSuperpowersTaskSections`, `maskFencedCodeBlocks`, `extractFileClaims`, `claimModeForVerb`, `dedupeClaims`, `extractVerificationCommands`, `logicalCommandLines`, and `isSafeVerificationCommand` with:

```ts
function extractSuperpowersTaskSections(markdown: string): ExtractedPlanTask[] {
  return extractSuperpowersPlan(markdown).tasks;
}

function extractFileClaims(section: ExtractedPlanTask): FileClaim[] {
  return section.explicit_file_claims;
}

function extractVerificationCommands(
  section: ExtractedPlanTask,
  workspace: string | undefined,
  catalog: ProjectScriptCatalog | null
): string[] {
  const safe = section.fenced_commands.filter((command) =>
    classifyVerificationCommand({
      command,
      workspace: workspace ?? process.cwd(),
      catalog
    }).status === "safe"
  );
  return [...new Set(safe)];
}
```

Then update the loop to call:

```ts
const fileClaims = extractFileClaims(section);
const verify = extractVerificationCommands(section, input.workspace, catalog);
```

- [ ] **Step 6: Keep explicit verification path coverage working with shared token parsing**

In `packages/orchestrator/src/planNormalizer.ts`, replace `commandTokens` with the imported helper and extend `explicitVerificationPaths` so `node --test` is covered:

```ts
function explicitVerificationPaths(command: string): string[] {
  const paths = new Set<string>();
  for (const part of command.replace(/\s+/g, " ").trim().split(/\s+&&\s+/)) {
    const normalized = part.trim();
    if (normalized.startsWith("cd ")) continue;
    if (normalized.startsWith("bun test ")) {
      for (const token of commandTokens(normalized).slice(2)) {
        if (isExplicitPathToken(token)) paths.add(token);
      }
      continue;
    }
    if (normalized.startsWith("node --test ")) {
      for (const token of commandTokens(normalized).slice(2)) {
        if (isExplicitPathToken(token)) paths.add(token);
      }
      continue;
    }
    if (normalized.startsWith("git diff --check")) {
      const tokens = commandTokens(normalized);
      const separatorIndex = tokens.indexOf("--");
      if (separatorIndex >= 0) {
        for (const token of tokens.slice(separatorIndex + 1)) {
          if (isExplicitPathToken(token)) paths.add(token);
        }
      }
    }
  }
  return [...paths];
}
```

- [ ] **Step 7: Refactor preflight onto shared policy**

In `packages/orchestrator/src/planPreflight.ts`, add:

```ts
import { buildProjectScriptCatalog } from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
```

Remove the local `SAFE_COMMAND_STARTS` array and replace `isSafeVerificationCommand` with:

```ts
function isSafeVerificationCommand(command: string, workspace: string): boolean {
  return classifyVerificationCommand({
    command,
    workspace,
    catalog: buildProjectScriptCatalog(workspace)
  }).status === "safe";
}
```

Then update the call site in `validateTasks`:

```ts
if (!isSafeVerificationCommand(command, workspace)) errors.push(`${task.id} has unsafe verification command: ${command}`);
```

- [ ] **Step 8: Export shared helper modules**

Append these exports to `packages/orchestrator/src/index.ts`:

```ts
export * from "./planAdapters/commandLines";
export * from "./planAdapters/verificationPolicy";
export * from "./planAdapters/planClaimExtraction";
```

- [ ] **Step 9: Run normalizer and preflight tests**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts
```

Expected: PASS.

- [ ] **Step 10: Commit Task 3**

Run:

```bash
git add packages/orchestrator/src/planNormalizer.ts \
  packages/orchestrator/src/planPreflight.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts
git commit -m "fix: share intake verification policy"
```

---

### Task 4: Merge Intake Recovery Without Losing Strict Evidence

**Files:**
- Create: `packages/orchestrator/src/intakeRepairPlanner.ts`
- Create: `packages/orchestrator/tests/intakeRepairPlanner.test.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/orchestrator/src/intakeRecovery.ts`
- Modify: `packages/orchestrator/tests/intakeRecovery.test.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Add additive intake recovery types**

In `packages/contracts/src/types.ts`, add these interfaces above `WaygentIntakeRecovery`:

```ts
export type IntakeTaskStatus = "normalized" | "recovered" | "blocked" | "warning";

export interface IntakeTaskRecoveryStatus {
  task_id: string;
  status: IntakeTaskStatus;
  title: string;
  file_claim_count: number;
  verification_command_count: number;
  blockers: string[];
}
```

Then add optional fields to `WaygentIntakeRecovery`:

```ts
  strict_task_status?: IntakeTaskRecoveryStatus[];
  fallback_task_status?: IntakeTaskRecoveryStatus[];
  merged_task_status?: IntakeTaskRecoveryStatus[];
  blocked_tasks?: IntakeTaskRecoveryStatus[];
  extract_report_ref?: string | null;
```

- [ ] **Step 2: Write failing merge planner tests**

Create `packages/orchestrator/tests/intakeRepairPlanner.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mergeIntakeRepair } from "../src/intakeRepairPlanner";
import { extractSuperpowersPlan } from "../src/planAdapters/planClaimExtraction";

const plan = `
# Demo

### Task 1: Kotlin Task

**Files:**
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
\`\`\`

### Task 2: Unsafe Task

**Files:**
- Modify: \`README.md\`

Run:

\`\`\`bash
git reset --hard
\`\`\`
`;

describe("intake repair planner", () => {
  test("preserves explicit claims and reports unsafe verification by task", () => {
    const extracted = extractSuperpowersPlan(plan);
    const merged = mergeIntakeRepair({
      extracted,
      strict_error: "Task 2 has unsafe verification command",
      normalized_task_ids: new Set(["task_1_kotlin_task"]),
      plan_path: "/tmp/plan.md"
    });

    expect(merged.merged_task_status).toEqual([
      {
        task_id: "task_1_kotlin_task",
        title: "Kotlin Task",
        status: "normalized",
        file_claim_count: 1,
        verification_command_count: 1,
        blockers: []
      },
      {
        task_id: "task_2_unsafe_task",
        title: "Unsafe Task",
        status: "blocked",
        file_claim_count: 1,
        verification_command_count: 1,
        blockers: ["unsafe_verification_command"]
      }
    ]);
    expect(merged.findings).toContainEqual(expect.objectContaining({
      code: "unsafe_verification_command",
      task_id: "task_2_unsafe_task",
      severity: "blocking"
    }));
  });

  test("reports extractor policy gaps instead of false missing file claims", () => {
    const extracted = extractSuperpowersPlan(plan);
    const merged = mergeIntakeRepair({
      extracted,
      strict_error: "fallback failed to read Kotlin paths",
      normalized_task_ids: new Set(),
      plan_path: "/tmp/plan.md"
    });

    expect(merged.findings.some((finding) => finding.code === "extractor_policy_gap")).toBe(false);
    expect(merged.merged_task_status[0]?.file_claim_count).toBe(1);
  });
});
```

- [ ] **Step 3: Run merge planner tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/intakeRepairPlanner.test.ts
```

Expected: FAIL because `intakeRepairPlanner.ts` does not exist.

- [ ] **Step 4: Add intake repair planner**

Create `packages/orchestrator/src/intakeRepairPlanner.ts`:

```ts
import type { IntakeFinding, IntakeTaskRecoveryStatus } from "@waygent/contracts";
import type { ExtractedSuperpowersPlan, ExtractedPlanTask } from "./planAdapters/planClaimExtraction";

export interface IntakeRepairMergeInput {
  extracted: ExtractedSuperpowersPlan;
  strict_error: string | null;
  normalized_task_ids: Set<string>;
  plan_path: string | null;
}

export interface IntakeRepairMergeResult {
  strict_task_status: IntakeTaskRecoveryStatus[];
  fallback_task_status: IntakeTaskRecoveryStatus[];
  merged_task_status: IntakeTaskRecoveryStatus[];
  blocked_tasks: IntakeTaskRecoveryStatus[];
  findings: IntakeFinding[];
}

export function mergeIntakeRepair(input: IntakeRepairMergeInput): IntakeRepairMergeResult {
  const merged = input.extracted.tasks.map((task) => statusForTask(task, input));
  const blocked = merged.filter((task) => task.status === "blocked");
  const findings = blocked.flatMap((task): IntakeFinding[] =>
    task.blockers.map((blocker) => ({
      code: blocker,
      severity: "blocking",
      message: `${task.task_id} blocked by ${blocker}.`,
      task_id: task.task_id,
      evidence_refs: evidenceRefs(input.plan_path, task.task_id)
    }))
  );
  return {
    strict_task_status: merged.map((task) => ({
      ...task,
      status: input.normalized_task_ids.has(task.task_id) ? "normalized" : task.status
    })),
    fallback_task_status: merged,
    merged_task_status: merged,
    blocked_tasks: blocked,
    findings
  };
}

function statusForTask(task: ExtractedPlanTask, input: IntakeRepairMergeInput): IntakeTaskRecoveryStatus {
  const taskId = taskIdFor(task);
  const blockers: string[] = [];
  const fileClaimCount = task.explicit_file_claims.length || task.prose_file_claims.length;
  const verificationCommandCount = task.fenced_commands.length;
  if (fileClaimCount === 0) blockers.push("missing_file_claim");
  if (verificationCommandCount === 0) blockers.push("missing_verification_for_source_mutation");
  if (task.fenced_commands.some((command) => /\b(git\s+reset\s+--hard|rm\s+-rf|git\s+clean\s+-fd|kubectl\s+delete)\b/i.test(command))) {
    blockers.push("unsafe_verification_command");
  }
  if (input.normalized_task_ids.has(taskId)) {
    return {
      task_id: taskId,
      title: task.title,
      status: "normalized",
      file_claim_count: fileClaimCount,
      verification_command_count: verificationCommandCount,
      blockers: []
    };
  }
  return {
    task_id: taskId,
    title: task.title,
    status: blockers.length > 0 ? "blocked" : "recovered",
    file_claim_count: fileClaimCount,
    verification_command_count: verificationCommandCount,
    blockers: [...new Set(blockers)]
  };
}

function taskIdFor(task: ExtractedPlanTask): string {
  const slug = task.title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `task_${task.number}_${slug || "task"}`;
}

function evidenceRefs(planPath: string | null, taskId: string): string[] {
  return [planPath ? `plan:${planPath}` : "plan:inline", `plan:${taskId}`];
}
```

- [ ] **Step 5: Refactor `intakeRecovery.ts` to use shared extraction and merge status**

In `packages/orchestrator/src/intakeRecovery.ts`, remove local `TASK_HEADING`, `INLINE_PATH`, `FENCED_COMMAND`, `DESTRUCTIVE_COMMAND`, `SAFE_VERIFY_PREFIXES`, `LenientTaskSection`, `extractLenientTaskSections`, `extractFileClaims`, `inferClaimMode`, `extractVerificationCommands`, and `logicalCommandLines`. Add:

```ts
import { extractSuperpowersPlan, type ExtractedPlanTask } from "./planAdapters/planClaimExtraction";
import { buildProjectScriptCatalog } from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
import { mergeIntakeRepair } from "./intakeRepairPlanner";
```

Replace the start of `deterministicRepair` task extraction with:

```ts
  const extracted = extractSuperpowersPlan(input.markdown);
  const catalog = buildProjectScriptCatalog(input.workspace);
  const merge = mergeIntakeRepair({
    extracted,
    strict_error: strictError,
    normalized_task_ids: new Set(),
    plan_path: input.path
  });
  findings.push(...merge.findings);
  const tasks = extracted.tasks.map((section) => recoverSection(section, findings, input.path, input.workspace, catalog));
```

Replace `recoverSection` with this signature and body:

```ts
function recoverSection(
  section: ExtractedPlanTask,
  findings: IntakeFinding[],
  planPath: string | null,
  workspace: string,
  catalog: ReturnType<typeof buildProjectScriptCatalog>
) {
  const taskId = `task_${section.number}_${slugify(section.title)}`;
  const evidenceRefs = [...planEvidence(planPath), `plan:task-${section.number}`];
  const fileClaims = section.explicit_file_claims.length > 0 ? section.explicit_file_claims : section.prose_file_claims;
  const verify = section.fenced_commands.filter((command) =>
    classifyVerificationCommand({ command, workspace, catalog }).status === "safe"
  );
  if (fileClaims.length > 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: section.explicit_file_claims.length > 0 ? "info" : "warning",
      message: `Recovered ${fileClaims.length} file claim(s).`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (verify.length > 0) {
    findings.push({
      code: "verification_command_in_prose",
      severity: "warning",
      message: `Recovered ${verify.length} verification command(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return {
    id: taskId,
    title: section.title,
    dependencies: [] as string[],
    file_claims: fileClaims,
    risk: "high" as const,
    verify,
    instructions: instructionLines(section.body)
  };
}
```

When building the report object, add:

```ts
    strict_task_status: merge.strict_task_status,
    fallback_task_status: merge.fallback_task_status,
    merged_task_status: merge.merged_task_status,
    blocked_tasks: merge.blocked_tasks,
    extract_report_ref: "artifacts/intake/extract-report.json",
```

- [ ] **Step 6: Extend intake recovery tests**

Append this test to `packages/orchestrator/tests/intakeRecovery.test.ts`:

```ts
  test("does not report Kotlin and Gradle plans as missing claims", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: `
# Source Matching Trust Program

### Task 3: Improve Precise And Compact Handoff Trust Wording

**Files:**
- Modify: \`fixthis-mcp/src/test/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatterTest.kt\`
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
\`\`\`
`,
      path: "/tmp/source-matching-trust-program.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("not_needed");
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.findings.some((finding) => finding.message.includes("no recoverable file claim"))).toBe(false);
  });
```

- [ ] **Step 7: Export intake repair planner**

Append to `packages/orchestrator/src/index.ts`:

```ts
export * from "./intakeRepairPlanner";
```

- [ ] **Step 8: Run intake tests**

Run:

```bash
bun test packages/orchestrator/tests/intakeRepairPlanner.test.ts packages/orchestrator/tests/intakeRecovery.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

Run:

```bash
git add packages/contracts/src/types.ts \
  packages/orchestrator/src/intakeRepairPlanner.ts \
  packages/orchestrator/src/intakeRecovery.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/intakeRepairPlanner.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts
git commit -m "fix: preserve intake recovery evidence"
```

---

### Task 5: Emit Intake Extract Artifact And Contract Audit Findings

**Files:**
- Create: `packages/orchestrator/src/adjacentContractAudit.ts`
- Create: `packages/orchestrator/tests/adjacentContractAudit.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/orchestratorRun.test.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Write failing contract audit tests**

Create `packages/orchestrator/tests/adjacentContractAudit.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { auditAdjacentContracts } from "../src/adjacentContractAudit";

describe("adjacent contract audit", () => {
  test("surfaces source matching and handoff contract candidates", () => {
    const findings = auditAdjacentContracts({
      plan_markdown: "Update handoff markdown for source matching confidence and targetReliability.",
      spec_markdown: "Do not rename persisted MCP JSON fields such as sourceCandidates.",
      file_claims: [
        "fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt"
      ]
    });

    expect(findings).toEqual([
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Trust-sensitive source matching or handoff changes should review docs/reference/source-matching.md.",
        task_id: null,
        evidence_refs: ["docs/reference/source-matching.md"]
      },
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Persisted MCP output changes should review docs/reference/output-schema.md.",
        task_id: null,
        evidence_refs: ["docs/reference/output-schema.md"]
      },
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Feedback console handoff wording changes should review docs/reference/feedback-console-contract.md.",
        task_id: null,
        evidence_refs: ["docs/reference/feedback-console-contract.md"]
      }
    ]);
  });
});
```

- [ ] **Step 2: Run audit tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/adjacentContractAudit.test.ts
```

Expected: FAIL because `adjacentContractAudit.ts` does not exist.

- [ ] **Step 3: Create adjacent contract audit helper**

Create `packages/orchestrator/src/adjacentContractAudit.ts`:

```ts
import type { IntakeFinding } from "@waygent/contracts";

export interface AdjacentContractAuditInput {
  plan_markdown: string;
  spec_markdown: string;
  file_claims: string[];
}

export function auditAdjacentContracts(input: AdjacentContractAuditInput): IntakeFinding[] {
  const haystack = [
    input.plan_markdown,
    input.spec_markdown,
    input.file_claims.join("\n")
  ].join("\n").toLowerCase();
  const findings: IntakeFinding[] = [];
  if (/(source matching|sourcecandidate|source candidate|targetreliability|confidence|handoff)/.test(haystack)) {
    findings.push(finding(
      "Trust-sensitive source matching or handoff changes should review docs/reference/source-matching.md.",
      "docs/reference/source-matching.md"
    ));
  }
  if (/(persisted mcp json|output schema|sourcecandidates|targetreliability|items|screens|itemid|screenid)/.test(haystack)) {
    findings.push(finding(
      "Persisted MCP output changes should review docs/reference/output-schema.md.",
      "docs/reference/output-schema.md"
    ));
  }
  if (/(feedback console|copy prompt|compact|handoff markdown|feedbackqueueformatter|compacthandoffrenderer)/.test(haystack)) {
    findings.push(finding(
      "Feedback console handoff wording changes should review docs/reference/feedback-console-contract.md.",
      "docs/reference/feedback-console-contract.md"
    ));
  }
  return findings;
}

function finding(message: string, ref: string): IntakeFinding {
  return {
    code: "adjacent_contract_candidate",
    severity: "warning",
    message,
    task_id: null,
    evidence_refs: [ref]
  };
}
```

- [ ] **Step 4: Write intake extract artifacts in `runWaygent`**

In `packages/orchestrator/src/orchestrator.ts`, add imports:

```ts
import type { IntakeFinding } from "@waygent/contracts";
import { auditAdjacentContracts } from "./adjacentContractAudit";
import { extractSuperpowersPlan } from "./planAdapters/planClaimExtraction";
import { buildProjectScriptCatalog } from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
```

Immediately after `specInput` is resolved, add:

```ts
  const extractedPlan = extractSuperpowersPlan(planInput.markdown);
  const extractionCatalog = buildProjectScriptCatalog(workspace);
  const extractReport = {
    tasks: extractedPlan.tasks.map((task) => ({
      number: task.number,
      title: task.title,
      explicit_file_claims: task.explicit_file_claims,
      prose_file_claims: task.prose_file_claims,
      fenced_commands: task.fenced_commands,
      verification: task.fenced_commands.map((command) =>
        classifyVerificationCommand({ command, workspace, catalog: extractionCatalog })
      )
    }))
  };
  const contractAuditFindings = auditAdjacentContracts({
    plan_markdown: planInput.markdown,
    spec_markdown: specInput.markdown,
    file_claims: extractedPlan.tasks.flatMap((task) => [
      ...task.explicit_file_claims.map((claim) => claim.path),
      ...task.prose_file_claims.map((claim) => claim.path)
    ])
  });
```

Before the first `platform.run_started` event on successful runs, write:

```ts
  const extractReportArtifact = writeArtifact(
    paths.root,
    "intake/extract-report.json",
    `${JSON.stringify(extractReport, null, 2)}\n`,
    "application/json"
  );
```

Then append this event after `platform.run_started`:

```ts
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.intake_extract_completed",
    phase: "intake",
    outcome: "success",
    summary: "Plan intake extraction completed.",
    payload: {
      extract_report_ref: extractReportArtifact.path,
      task_count: extractedPlan.tasks.length,
      adjacent_contract_findings: contractAuditFindings
    },
    trust_impact: contractAuditFindings.length > 0 ? "requires_review" : "neutral"
  }));
```

- [ ] **Step 5: Write extract artifacts for intake-blocked runs**

Extend `FinalizeIntakeBlockedRunInput` with:

```ts
  extractReport?: Record<string, unknown>;
  adjacentContractFindings?: IntakeFinding[];
```

When calling `finalizeIntakeBlockedRun`, pass:

```ts
      extractReport,
      adjacentContractFindings: contractAuditFindings
```

Inside `finalizeIntakeBlockedRun`, before writing recovery report, add:

```ts
  const extractArtifact = input.extractReport
    ? writeArtifact(
      paths.root,
      "intake/extract-report.json",
      `${JSON.stringify(input.extractReport, null, 2)}\n`,
      "application/json"
    )
    : null;
```

After `platform.run_started`, append the same `platform.intake_extract_completed` event with `extractArtifact?.path ?? null`.

- [ ] **Step 6: Export adjacent contract audit**

Append to `packages/orchestrator/src/index.ts`:

```ts
export * from "./adjacentContractAudit";
```

- [ ] **Step 7: Run audit and orchestrator tests**

Run:

```bash
bun test packages/orchestrator/tests/adjacentContractAudit.test.ts packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add packages/orchestrator/src/adjacentContractAudit.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/adjacentContractAudit.test.ts \
  packages/orchestrator/tests/orchestratorRun.test.ts
git commit -m "feat: report intake extraction evidence"
```

---

### Task 6: Add Provider Capability Probe And Option Attestation

**Files:**
- Create: `packages/provider-adapters/src/capabilityProbe.ts`
- Create: `packages/provider-adapters/tests/capabilityProbe.test.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`

- [ ] **Step 1: Write failing capability probe tests**

Create `packages/provider-adapters/tests/capabilityProbe.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { attestProviderProcessOptions } from "../src/capabilityProbe";

describe("provider capability probe", () => {
  test("omits unsupported Codex reasoning flags while preserving requested evidence", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      model: "gpt-5.5",
      effort: "high"
    }, {
      status: "ready",
      stdout: "Usage: codex exec [OPTIONS]\n  --model <MODEL>\n",
      stderr: "",
      exit_code: 0
    });

    expect(attestation.options).toEqual({
      executable: "codex",
      args: ["exec", "--json", "-"],
      model: "gpt-5.5"
    });
    expect(attestation.capability).toMatchObject({
      provider: "codex",
      requested_reasoning: "high",
      applied_reasoning: null,
      reason: "unsupported_by_cli"
    });
  });

  test("keeps supported Codex reasoning flags", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      effort: "high"
    }, {
      status: "ready",
      stdout: "Usage: codex exec [OPTIONS]\n  --reasoning <EFFORT>\n",
      stderr: "",
      exit_code: 0
    });

    expect(attestation.options.effort).toBe("high");
    expect(attestation.capability.applied_reasoning).toBe("high");
  });
});
```

- [ ] **Step 2: Run capability tests and verify failure**

Run:

```bash
bun test packages/provider-adapters/tests/capabilityProbe.test.ts
```

Expected: FAIL because `capabilityProbe.ts` does not exist.

- [ ] **Step 3: Add capability probe helper**

Create `packages/provider-adapters/src/capabilityProbe.ts`:

```ts
import { spawnSync } from "node:child_process";
import type { ProviderProcessOptions } from "./types";

export type ProbedProvider = "codex" | "claude";

export interface ProviderHelpProbeResult {
  status: "ready" | "failed";
  stdout: string;
  stderr: string;
  exit_code: number | null;
}

export interface ProviderCapabilityAttestation {
  provider: ProbedProvider;
  executable: string;
  requested_model: string | null;
  applied_model: string | null;
  requested_reasoning: string | null;
  applied_reasoning: string | null;
  reason: "supported" | "unsupported_by_cli" | "probe_failed";
  help_exit_code: number | null;
}

export interface ProviderProcessAttestation {
  options: ProviderProcessOptions;
  capability: ProviderCapabilityAttestation;
}

export function probeProviderHelp(provider: ProbedProvider, options: ProviderProcessOptions): ProviderHelpProbeResult {
  const executable = options.executable;
  const args = provider === "codex" ? ["exec", "--help"] : ["--help"];
  const result = spawnSync(executable, args, { encoding: "utf8" });
  return {
    status: result.status === 0 ? "ready" : "failed",
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    exit_code: result.status
  };
}

export function attestProviderProcessOptions(
  provider: ProbedProvider,
  options: ProviderProcessOptions,
  probe: ProviderHelpProbeResult
): ProviderProcessAttestation {
  if (provider === "codex") {
    const supportsReasoning = probe.status === "ready" && probe.stdout.includes("--reasoning");
    const nextOptions: ProviderProcessOptions = { ...options };
    if (options.effort && !supportsReasoning) delete nextOptions.effort;
    return {
      options: nextOptions,
      capability: {
        provider,
        executable: options.executable,
        requested_model: options.model ?? null,
        applied_model: options.model ?? null,
        requested_reasoning: options.effort ?? null,
        applied_reasoning: supportsReasoning ? options.effort ?? null : null,
        reason: probe.status === "ready" ? supportsReasoning || !options.effort ? "supported" : "unsupported_by_cli" : "probe_failed",
        help_exit_code: probe.exit_code
      }
    };
  }
  return {
    options,
    capability: {
      provider,
      executable: options.executable,
      requested_model: options.model ?? null,
      applied_model: options.model ?? null,
      requested_reasoning: options.effort ?? null,
      applied_reasoning: options.effort ?? null,
      reason: probe.status === "ready" ? "supported" : "probe_failed",
      help_exit_code: probe.exit_code
    }
  };
}
```

- [ ] **Step 4: Export provider capability helpers**

Append to `packages/provider-adapters/src/index.ts`:

```ts
export * from "./capabilityProbe";
```

- [ ] **Step 5: Use attested process options in orchestrator**

In `packages/orchestrator/src/orchestrator.ts`, update the provider-adapter import:

```ts
import { attestProviderProcessOptions, probeProviderHelp, type ProviderCapabilityAttestation, type ProviderProcessOptions } from "@waygent/provider-adapters";
```

After `const resolvedProviderProcesses = resolveProviderProcesses(...)`, add:

```ts
    const providerCapabilityAttestations: ProviderCapabilityAttestation[] = [];
    const attestedProviderProcesses = { ...resolvedProviderProcesses };
    if (profile.provider === "codex" && resolvedProviderProcesses.codex) {
      const attested = attestProviderProcessOptions("codex", resolvedProviderProcesses.codex, probeProviderHelp("codex", resolvedProviderProcesses.codex));
      attestedProviderProcesses.codex = attested.options;
      providerCapabilityAttestations.push(attested.capability);
    }
    if (profile.provider === "claude" && resolvedProviderProcesses.claude) {
      const attested = attestProviderProcessOptions("claude", resolvedProviderProcesses.claude, probeProviderHelp("claude", resolvedProviderProcesses.claude));
      attestedProviderProcesses.claude = attested.options;
      providerCapabilityAttestations.push(attested.capability);
    }
```

Pass `attestedProviderProcesses` into `executeWaygentTask` instead of `resolvedProviderProcesses`.

Before dispatching the wave, write one artifact per run:

```ts
    if (providerCapabilityAttestations.length > 0) {
      const capabilityArtifact = writeArtifact(
        paths.root,
        "platform/provider-capabilities.json",
        `${JSON.stringify({ provider_capabilities: providerCapabilityAttestations }, null, 2)}\n`,
        "application/json"
      );
      context.appendEvent((sequence) => buildRunEvent({
        run_id: runId,
        sequence,
        event_type: "platform.provider_capability_attested",
        phase: "platform",
        outcome: providerCapabilityAttestations.some((item) => item.reason === "probe_failed") ? "blocked" : "success",
        summary: "Provider CLI capability attested.",
        payload: {
          provider_capabilities_ref: capabilityArtifact.path,
          provider_capabilities: providerCapabilityAttestations
        },
        trust_impact: providerCapabilityAttestations.some((item) => item.reason !== "supported") ? "requires_review" : "neutral"
      }));
    }
```

- [ ] **Step 6: Run provider adapter tests**

Run:

```bash
bun test packages/provider-adapters/tests/capabilityProbe.test.ts packages/provider-adapters/tests/codexAdapter.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

Run:

```bash
git add packages/provider-adapters/src/capabilityProbe.ts \
  packages/provider-adapters/src/index.ts \
  packages/provider-adapters/tests/capabilityProbe.test.ts \
  packages/orchestrator/src/orchestrator.ts
git commit -m "feat: attest provider CLI capabilities"
```

---

### Task 7: Add Execution Dependency Barriers For Gradle Modules

**Files:**
- Create: `packages/orchestrator/src/executionDependencyBarrier.ts`
- Create: `packages/orchestrator/tests/executionDependencyBarrier.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Write failing dependency barrier tests**

Create `packages/orchestrator/tests/executionDependencyBarrier.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { ParsedWaygentPlan } from "../src/planParser";
import { applyExecutionDependencyBarriers } from "../src/executionDependencyBarrier";

const plan: ParsedWaygentPlan = {
  tasks: [
    {
      id: "task_core",
      title: "Core",
      dependencies: [],
      file_claims: [{ path: "fixthis-compose-core/src/main/kotlin/SourceMatcher.kt", mode: "owned" }],
      risk: "medium",
      verification_commands: ['./gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --no-daemon'],
      instructions: []
    },
    {
      id: "task_mcp",
      title: "MCP",
      dependencies: [],
      file_claims: [{ path: "fixthis-mcp/src/main/kotlin/FeedbackQueueFormatter.kt", mode: "owned" }],
      risk: "medium",
      verification_commands: ['./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon'],
      instructions: []
    },
    {
      id: "task_final",
      title: "Final",
      dependencies: [],
      file_claims: [{ path: "docs/reference/source-matching.md", mode: "owned" }],
      risk: "low",
      verification_commands: ["./gradlew test"],
      instructions: []
    }
  ]
};

describe("execution dependency barriers", () => {
  test("adds broad Gradle verification dependencies after module edits", () => {
    const result = applyExecutionDependencyBarriers(plan);

    expect(result.plan.tasks.find((task) => task.id === "task_final")?.dependencies).toEqual([
      "task_core",
      "task_mcp"
    ]);
    expect(result.barriers).toContainEqual({
      task_id: "task_final",
      depends_on: ["task_core", "task_mcp"],
      reason: "broad_gradle_verification",
      detail: "./gradlew test reads modules touched by earlier tasks"
    });
  });

  test("keeps independent module-local Gradle tasks parallel", () => {
    const result = applyExecutionDependencyBarriers({
      tasks: plan.tasks.slice(0, 2)
    });

    expect(result.plan.tasks.map((task) => task.dependencies)).toEqual([[], []]);
    expect(result.barriers).toEqual([]);
  });
});
```

- [ ] **Step 2: Run barrier tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/executionDependencyBarrier.test.ts
```

Expected: FAIL because `executionDependencyBarrier.ts` does not exist.

- [ ] **Step 3: Add execution dependency barrier helper**

Create `packages/orchestrator/src/executionDependencyBarrier.ts`:

```ts
import type { ParsedWaygentPlan, ParsedWaygentTask } from "./planParser";

export interface ExecutionDependencyBarrier {
  task_id: string;
  depends_on: string[];
  reason: "broad_gradle_verification" | "module_overlap";
  detail: string;
}

export interface ExecutionDependencyBarrierResult {
  plan: ParsedWaygentPlan;
  barriers: ExecutionDependencyBarrier[];
}

export function applyExecutionDependencyBarriers(plan: ParsedWaygentPlan): ExecutionDependencyBarrierResult {
  const barriers: ExecutionDependencyBarrier[] = [];
  const tasks = plan.tasks.map((task) => ({ ...task, dependencies: [...task.dependencies] }));
  for (const task of tasks) {
    if (!hasBroadGradleVerification(task)) continue;
    const previousModuleTasks = tasks
      .filter((candidate) => candidate.id !== task.id)
      .filter((candidate) => claimedModules(candidate).length > 0)
      .map((candidate) => candidate.id);
    const missingDeps = previousModuleTasks.filter((id) => !task.dependencies.includes(id));
    if (missingDeps.length === 0) continue;
    task.dependencies.push(...missingDeps);
    barriers.push({
      task_id: task.id,
      depends_on: missingDeps,
      reason: "broad_gradle_verification",
      detail: `${task.verification_commands.find((command) => command.includes("gradle"))} reads modules touched by earlier tasks`
    });
  }
  return { plan: { tasks }, barriers };
}

function hasBroadGradleVerification(task: ParsedWaygentTask): boolean {
  return task.verification_commands.some((command) => {
    const normalized = command.replace(/\s+/g, " ").trim();
    return normalized === "./gradlew test" ||
      normalized === "gradle test" ||
      normalized === "./gradlew check" ||
      normalized === "gradle check" ||
      normalized === "./gradlew build" ||
      normalized === "gradle build";
  });
}

function claimedModules(task: ParsedWaygentTask): string[] {
  const modules = new Set<string>();
  for (const claim of task.file_claims) {
    const first = claim.path.split("/")[0];
    if (first && first.startsWith("fixthis-")) modules.add(first);
  }
  return [...modules];
}
```

- [ ] **Step 4: Integrate barriers into orchestrator task graph building**

In `packages/orchestrator/src/orchestrator.ts`, add:

```ts
import { applyExecutionDependencyBarriers } from "./executionDependencyBarrier";
```

Replace:

```ts
  const parsed = parseWaygentPlan(normalizedPlan.markdown);
```

with:

```ts
  const parsedBeforeBarriers = parseWaygentPlan(normalizedPlan.markdown);
  const barrierResult = applyExecutionDependencyBarriers(parsedBeforeBarriers);
  const parsed = barrierResult.plan;
```

After the initial `runway.safe_wave_selected` event, append barrier events:

```ts
  for (const barrier of barrierResult.barriers) {
    context.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "runway.wave_barrier_inserted",
      phase: "schedule",
      outcome: "success",
      summary: "Execution dependency barrier inserted.",
      payload: barrier,
      trust_impact: "requires_review"
    }));
  }
```

- [ ] **Step 5: Export barrier helper**

Append to `packages/orchestrator/src/index.ts`:

```ts
export * from "./executionDependencyBarrier";
```

- [ ] **Step 6: Run barrier and task graph tests**

Run:

```bash
bun test packages/orchestrator/tests/executionDependencyBarrier.test.ts packages/orchestrator/tests/taskGraph.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

Run:

```bash
git add packages/orchestrator/src/executionDependencyBarrier.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/executionDependencyBarrier.test.ts
git commit -m "feat: add Gradle wave barriers"
```

---

### Task 8: Add FixThis-Style Integration Regression

**Files:**
- Create: `tests/integration/waygent-android-intake-trust.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Write the integration regression test**

Create `tests/integration/waygent-android-intake-trust.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runWaygent } from "@waygent/orchestrator";

let workspace: string;
let root: string;

beforeEach(() => {
  workspace = mkdtempSync(join(tmpdir(), "waygent-android-intake-workspace-"));
  root = mkdtempSync(join(tmpdir(), "waygent-android-intake-root-"));
  writeFileSync(join(workspace, "package.json"), JSON.stringify({
    scripts: {
      "source-matching:fixtures:test": "node --test scripts/source-matching-fixtures-test.mjs"
    }
  }));
});

afterEach(() => {
  rmSync(workspace, { recursive: true, force: true });
  rmSync(root, { recursive: true, force: true });
});

describe("Waygent Android intake trust integration", () => {
  test("does not block FixThis-style Kotlin and Gradle plans at intake", async () => {
    const result = await runWaygent({
      root,
      workspace,
      run_id: "android_intake_trust",
      profile: { provider: "fake", execution_mode: "multi-agent" },
      plan_preflight: "deterministic",
      spec: "# Spec\n\nSource matching trust handoff confidence must remain calibrated.",
      plan: `
# Source Matching Trust Program

### Task 1: Improve Precise And Compact Handoff Trust Wording

**Files:**
- Modify: \`fixthis-mcp/src/test/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatterTest.kt\`
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --tests "*CopyPromptEditSurfaceRendererTest" --no-daemon
\`\`\`

### Task 2: Update References And Run Final Verification

**Files:**
- Modify: \`docs/reference/source-matching.md\`
- Modify: \`docs/reference/output-schema.md\`
- Modify: \`docs/guides/source-matching-fixture-lab.md\`

Run:

\`\`\`bash
npm run source-matching:fixtures:test
git diff --check
\`\`\`
`
    });

    expect(result.events.some((event) => event.event_type === "platform.intake_decision_required")).toBe(false);
    expect(result.events.some((event) => event.event_type === "platform.intake_extract_completed")).toBe(true);
    expect(result.events.some((event) => event.event_type === "runway.plan_loaded")).toBe(true);
  });
});
```

- [ ] **Step 2: Add package script**

In root `package.json`, add this script entry:

```json
"waygent:android-intake-trust": "bun test tests/integration/waygent-android-intake-trust.test.ts"
```

Keep JSON key order near the other `waygent:*` scripts.

- [ ] **Step 3: Run the integration regression**

Run:

```bash
bun run waygent:android-intake-trust
```

Expected: PASS.

- [ ] **Step 4: Commit Task 8**

Run:

```bash
git add tests/integration/waygent-android-intake-trust.test.ts package.json
git commit -m "test: cover Android intake trust regression"
```

---

### Task 9: Final Verification, Docs Sync, And Graphify

**Files:**
- Modify: `docs/superpowers/specs/2026-05-24-waygent-android-intake-trust-design.md`
- Modify: `docs/operations/verification.md`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

- [ ] **Step 1: Update the design doc with final file names**

In `docs/superpowers/specs/2026-05-24-waygent-android-intake-trust-design.md`, add this paragraph under `## 8. Rollout Plan`:

```md
Implementation note: the shared command parser lives in
`packages/orchestrator/src/planAdapters/commandLines.ts`, the shared
verification policy in `packages/orchestrator/src/planAdapters/verificationPolicy.ts`,
and the Superpowers extractor in
`packages/orchestrator/src/planAdapters/planClaimExtraction.ts`.
```

- [ ] **Step 2: Update verification operations docs**

In `docs/operations/verification.md`, add this section after the existing verification environment strategy section:

```md
## Intake Verification Policy

Waygent classifies plan verification commands before provider dispatch. The
same policy is used by Superpowers plan normalization, deterministic intake
recovery, and plan preflight. Safe commands include known test runners,
declared package scripts, `node --test`, `git diff --check`, and Android
Gradle invocations through `./gradlew` or `gradle`.

Command chains split by `&&` are safe only when every segment is safe. A leading
`cd` is allowed only when it stays inside the workspace. Destructive commands,
workspace escapes, shell redirection, and unknown shell features block intake.
```

- [ ] **Step 3: Run focused verification**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/intakeRepairPlanner.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/orchestrator/tests/adjacentContractAudit.test.ts \
  packages/orchestrator/tests/executionDependencyBarrier.test.ts \
  packages/provider-adapters/tests/capabilityProbe.test.ts \
  tests/integration/waygent-android-intake-trust.test.ts
```

Expected: PASS.

- [ ] **Step 4: Run typecheck and fixture-lab verification**

Run:

```bash
bun run typecheck
bun run waygent:fixture-lab
```

Expected: both commands PASS.

- [ ] **Step 5: Run Graphify update**

Run:

```bash
graphify update .
```

Expected: graph update completes and `graphify-out/GRAPH_REPORT.md` plus `graphify-out/graph.json` are refreshed.

- [ ] **Step 6: Run patch hygiene**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 7: Commit final docs and graph**

Run:

```bash
git add docs/superpowers/specs/2026-05-24-waygent-android-intake-trust-design.md \
  docs/operations/verification.md \
  graphify-out/GRAPH_REPORT.md \
  graphify-out/graph.json
git commit -m "docs: document Android intake trust policy"
```

---

## Completion Checklist

- [ ] `bun test packages/orchestrator/tests/verificationPolicy.test.ts packages/orchestrator/tests/planClaimExtraction.test.ts packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/intakeRepairPlanner.test.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/planPreflight.test.ts packages/orchestrator/tests/adjacentContractAudit.test.ts packages/orchestrator/tests/executionDependencyBarrier.test.ts packages/provider-adapters/tests/capabilityProbe.test.ts tests/integration/waygent-android-intake-trust.test.ts` passes.
- [ ] `bun run typecheck` passes.
- [ ] `bun run waygent:fixture-lab` passes.
- [ ] `graphify update .` completes.
- [ ] `git diff --check` passes.
- [ ] A fake-provider Android intake regression reaches `runway.plan_loaded` and does not emit `platform.intake_decision_required`.
