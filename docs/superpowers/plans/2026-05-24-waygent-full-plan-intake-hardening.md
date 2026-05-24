# Waygent Full-Plan Intake Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent recover full Superpowers implementation plans by extracting only real shell verification commands, preserving examples and diagnostics as evidence, and proving the FixThis full-plan shape no longer blocks at intake.

**Architecture:** Replace regex-only fenced command extraction with a line scanner that distinguishes shell command fences from example fences. Extend verification classification with command roles while preserving the existing `safe | unsafe | ignored` public status. Add full-plan regression coverage and expose `extract_report_ref` through the shared operator decision projection.

**Tech Stack:** TypeScript, Bun test, Waygent orchestrator, Lens projectors, fake provider integration tests.

---

## File Structure

- Create `packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md`
  - A reduced but faithful Superpowers plan fixture with shell verification fences, non-shell example fences, git checkpoint commands, diagnostics, optional environment probes, and runtime fixture package scripts.
- Modify `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`
  - Owns fence-aware Markdown scanning, example fence evidence, and shell command candidate extraction.
- Modify `packages/orchestrator/src/planAdapters/verificationPolicy.ts`
  - Owns command role classification and compatibility mapping to existing command status.
- Modify `packages/orchestrator/src/orchestrator.ts`
  - Adds structured extraction fields to `artifacts/intake/extract-report.json`.
- Modify `packages/lens-projectors/src/operatorDecision.ts`
  - Adds `extract_report_ref` to operator-facing intake artifact refs.
- Modify tests:
  - `packages/orchestrator/tests/planClaimExtraction.test.ts`
  - `packages/orchestrator/tests/verificationPolicy.test.ts`
  - `packages/orchestrator/tests/intakeRecovery.test.ts`
  - `tests/integration/waygent-android-intake-trust.test.ts`
  - `packages/lens-projectors/tests/operatorDecision.test.ts`

## Waygent Task Manifest

The blocks below are the executable Waygent intake surface. The detailed
Superpowers task sections that follow remain the implementation source of
truth for exact test bodies, code snippets, and commit boundaries.

```yaml waygent-task
id: task_full_plan_fixture_tests
title: Add full-plan fixture and extraction tests
dependencies: []
file_claims:
  - path: packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md
    mode: owned
  - path: packages/orchestrator/tests/planClaimExtraction.test.ts
    mode: owned
risk: medium
verify:
  - git diff --check
instructions:
  - Implement the detailed Task 1 section below.
  - Add the reduced FixThis-style full-plan fixture and failing extraction coverage first.
  - This is the red-stage test task; do not implement the scanner here.
  - Keep non-shell example fences out of executable command expectations.
```

```yaml waygent-task
id: task_fence_scanner
title: Replace fenced command regex with scanner
dependencies: [task_full_plan_fixture_tests]
file_claims:
  - path: packages/orchestrator/src/planAdapters/planClaimExtraction.ts
    mode: owned
  - path: packages/orchestrator/tests/planClaimExtraction.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/planClaimExtraction.test.ts
instructions:
  - Implement the detailed Task 2 section below.
  - Replace regex-only fenced command extraction with a line scanner.
  - Preserve fenced_commands compatibility while adding fenced_examples and command_candidates evidence.
```

```yaml waygent-task
id: task_command_roles
title: Add command roles for diagnostics and optional environment checks
dependencies: [task_fence_scanner]
file_claims:
  - path: packages/orchestrator/src/planAdapters/verificationPolicy.ts
    mode: owned
  - path: packages/orchestrator/tests/verificationPolicy.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/verificationPolicy.test.ts
instructions:
  - Implement the detailed Task 3 section below.
  - Add role-aware classification for verification, implementation-only, diagnostics, optional environment probes, unsafe, and unknown commands.
  - Keep unknown commands blocking by default.
```

```yaml waygent-task
id: task_full_plan_recovery
title: Prove full-plan recovery and integration dispatch
dependencies: [task_command_roles]
file_claims:
  - path: packages/orchestrator/tests/intakeRecovery.test.ts
    mode: owned
  - path: tests/integration/waygent-android-intake-trust.test.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
risk: high
verify_isolation: isolated
verify:
  - bun test packages/orchestrator/tests/intakeRecovery.test.ts tests/integration/waygent-android-intake-trust.test.ts
instructions:
  - Implement the detailed Task 4 section below.
  - Prove the full-plan fixture recovers without intake_decision_required.
  - Add structured extraction evidence to the intake extract report.
```

```yaml waygent-task
id: task_operator_extract_report
title: Expose extract report in operator evidence
dependencies: [task_full_plan_recovery]
file_claims:
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/lens-projectors/tests/operatorDecision.test.ts
instructions:
  - Implement the detailed Task 5 section below.
  - Include extract_report_ref in intake recovery artifact refs and evidence packet assertions.
```

```yaml waygent-task
id: task_final_verification
title: Run final verification for full-plan intake hardening
dependencies: [task_operator_extract_report]
file_claims:
  - path: docs/superpowers/specs/2026-05-24-waygent-full-plan-intake-hardening-design.md
    mode: read_only
  - path: docs/superpowers/plans/2026-05-24-waygent-full-plan-intake-hardening.md
    mode: read_only
  - path: packages/orchestrator/tests/planClaimExtraction.test.ts
    mode: read_only
  - path: packages/orchestrator/tests/verificationPolicy.test.ts
    mode: read_only
  - path: packages/orchestrator/tests/intakeRecovery.test.ts
    mode: read_only
  - path: packages/orchestrator/tests/intakeRepairPlanner.test.ts
    mode: read_only
  - path: packages/orchestrator/tests/planNormalizer.test.ts
    mode: read_only
  - path: packages/orchestrator/tests/planPreflight.test.ts
    mode: read_only
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: read_only
  - path: tests/integration/waygent-android-intake-trust.test.ts
    mode: read_only
risk: low
verify_isolation: isolated
verify:
  - bun test packages/orchestrator/tests/planClaimExtraction.test.ts packages/orchestrator/tests/verificationPolicy.test.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/intakeRepairPlanner.test.ts packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/planPreflight.test.ts packages/lens-projectors/tests/operatorDecision.test.ts tests/integration/waygent-android-intake-trust.test.ts
  - bun run typecheck
  - git diff --check
instructions:
  - Implement the detailed Task 6 section below, except keep graphify update and git status as post-apply operator actions rather than Waygent verification commands.
  - Confirm focused tests, typecheck, and diff hygiene pass.
```

### Task 1: Add Full-Plan Fixture And Failing Extraction Tests

**Files:**
- Create: `packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md`
- Modify: `packages/orchestrator/tests/planClaimExtraction.test.ts`

- [ ] **Step 1: Create the full-plan fixture**

Create `packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md`:

````markdown
# Source Matching Runtime Trust Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add runtime source matching trust fixtures without weakening source-index fixtures.

## File Structure

- Modify `package.json`.
- Modify `scripts/source-matching-fixtures.mjs`.
- Modify `scripts/source-matching-fixtures-test.mjs`.
- Modify `fixtures/source-matching/manifest.json`.
- Create `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureModels.kt`.
- Create `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureRunner.kt`.
- Modify `docs/guides/source-matching-fixture-lab.md`.

### Task 1: Contract Cleanup

**Files:**
- Modify: `package.json`
- Modify: `fixtures/source-matching/manifest.json`
- Modify: `scripts/source-matching-fixtures.mjs`
- Modify: `scripts/source-matching-fixtures-test.mjs`

- [ ] **Step 1: Write failing package and manifest tests**

```javascript
test("package.json exposes runtime source matching fixture script", () => {
  const pkg = readJson("package.json");
  assert.equal(pkg.scripts["source-matching:fixtures:runtime"], "node scripts/source-matching-fixtures.mjs runtime");
});
```

```json
{
  "id": "reply-compose-fab-runtime",
  "mode": "runtime-trust",
  "runtimeTarget": { "text": "Compose", "role": "Button" },
  "expectedTop3PathContains": "ReplyListContent.kt"
}
```

Run:

```bash
npm run source-matching:fixtures:test
```

Expected: FAIL before the runtime script exists.

- [ ] **Step 2: Commit contract cleanup**

```bash
git add package.json fixtures/source-matching/manifest.json scripts/source-matching-fixtures.mjs scripts/source-matching-fixtures-test.mjs
git commit -m "feat: split source matching fixture contracts"
```

### Task 2: Runtime Runner Mapping

**Files:**
- Create: `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureModels.kt`
- Create: `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureRunner.kt`

- [ ] **Step 1: Add Kotlin DTO examples**

```kotlin
@Serializable
data class RuntimeTrustFixtureInput(
    val applicationId: String,
    val target: RuntimeTarget,
)
```

```kotlin
fun resultLabel(found: Boolean): String {
    return if (found) "runtime_trust_observed" else "target_not_found"
}
```

Run:

```bash
./gradlew :fixthis-mcp:test --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon
```

Expected: PASS after the runner tests are implemented.

- [ ] **Step 2: Commit runtime mapping**

```bash
git add fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture
git commit -m "feat: add runtime trust fixture runner"
```

### Task 3: Documentation And Final Verification

**Files:**
- Modify: `docs/guides/source-matching-fixture-lab.md`

- [ ] **Step 1: Document commands**

```markdown
Runtime fixture commands:
- `npm run source-matching:fixtures:runtime`
- `npm run source-matching:fixtures:runtime -- --strict`
```

- [ ] **Step 2: Run final checks**

```bash
npm run source-matching:fixtures:test
./gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --tests "*TargetReliabilityCalculatorTest" --no-daemon
./gradlew :fixthis-mcp:test --tests "*TargetEvidenceServiceTest" --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon
./gradlew spotlessCheck --no-daemon
git diff --check
graphify update .
git status --short --branch
command -v adb || true
```

Expected: default checks pass; `adb` absence is a non-blocking optional environment finding.

- [ ] **Step 3: Optional runtime strict check**

```bash
npm run source-matching:fixtures:runtime
npm run source-matching:fixtures:runtime -- --strict
```

Expected: strict mode may fail without a connected Android device.
````

- [ ] **Step 2: Add failing extraction tests**

Append these tests to `packages/orchestrator/tests/planClaimExtraction.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
```

```ts
function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "fixtures", name), "utf8");
}

describe("Superpowers full-plan fence extraction", () => {
  test("extracts commands only from explicit shell fences", () => {
    const extracted = extractSuperpowersPlan(fixture("full_plan_intake_hardening.md"));

    expect(extracted.tasks.map((task) => task.number)).toEqual([1, 2, 3]);
    expect(extracted.tasks[0]?.fenced_commands).toEqual([
      "npm run source-matching:fixtures:test",
      "git add package.json fixtures/source-matching/manifest.json scripts/source-matching-fixtures.mjs scripts/source-matching-fixtures-test.mjs",
      'git commit -m "feat: split source matching fixture contracts"'
    ]);
    expect(extracted.tasks[1]?.fenced_commands).toEqual([
      './gradlew :fixthis-mcp:test --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon',
      "git add fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture",
      'git commit -m "feat: add runtime trust fixture runner"'
    ]);
    expect(extracted.tasks[2]?.fenced_commands).toEqual([
      "npm run source-matching:fixtures:test",
      './gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --tests "*TargetReliabilityCalculatorTest" --no-daemon',
      './gradlew :fixthis-mcp:test --tests "*TargetEvidenceServiceTest" --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon',
      "./gradlew spotlessCheck --no-daemon",
      "git diff --check",
      "graphify update .",
      "git status --short --branch",
      "command -v adb || true",
      "npm run source-matching:fixtures:runtime",
      "npm run source-matching:fixtures:runtime -- --strict"
    ]);
  });

  test("keeps non-shell fences as examples and out of command candidates", () => {
    const extracted = extractSuperpowersPlan(fixture("full_plan_intake_hardening.md"));

    expect(extracted.tasks[0]?.fenced_examples?.map((block) => block.language)).toEqual([
      "javascript",
      "json"
    ]);
    expect(extracted.tasks[1]?.fenced_examples?.map((block) => block.language)).toEqual([
      "kotlin",
      "kotlin"
    ]);
    const commands = extracted.tasks.flatMap((task) => task.command_candidates ?? []).map((candidate) => candidate.command);
    expect(commands).not.toContain("- [ ] **Step 1: Write failing package and manifest tests**");
    expect(commands).not.toContain("Run:");
    expect(commands).not.toContain("Expected: PASS after the runner tests are implemented.");
    expect(commands.some((command) => command.includes("RuntimeTrustFixtureInput("))).toBe(false);
  });
});
```

- [ ] **Step 3: Run extraction tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts
```

Expected: FAIL because `fenced_examples` and `command_candidates` do not exist yet, and the current regex extracts prose from non-shell example blocks.

- [ ] **Step 4: Commit only the failing fixture and tests**

Run:

```bash
git add packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md packages/orchestrator/tests/planClaimExtraction.test.ts
git commit -m "test: cover full Superpowers plan fence extraction"
```

Expected: commit contains only the fixture and extraction test changes.

### Task 2: Replace Fenced Command Regex With A Scanner

**Files:**
- Modify: `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`
- Test: `packages/orchestrator/tests/planClaimExtraction.test.ts`

- [ ] **Step 1: Replace extraction types and helpers**

In `packages/orchestrator/src/planAdapters/planClaimExtraction.ts`, replace the interfaces and fenced block helpers with:

```ts
export interface ExtractedFenceBlock {
  language: string | null;
  content: string;
  line_start: number;
  line_end: number;
  source: "command" | "example";
  terminated: boolean;
}

export interface ExtractedCommandCandidate {
  command: string;
  source: "shell_fence" | "prose_hint" | "diagnostic_hint";
  language: string | null;
  line_start: number;
  line_end: number;
}

export interface ExtractedPlanTask {
  number: number;
  title: string;
  body: string;
  explicit_file_claims: FileClaim[];
  prose_file_claims: FileClaim[];
  fenced_commands: string[];
  fenced_examples?: ExtractedFenceBlock[];
  command_candidates?: ExtractedCommandCandidate[];
}
```

Remove the current `const fencedCommand = ...` declaration and add:

```ts
const fenceOpener = /^\s*```\s*([A-Za-z0-9_-]+)?\s*$/;
const fenceCloser = /^\s*```\s*$/;
const shellFenceLanguages = new Set(["bash", "sh", "shell", "zsh"]);
```

- [ ] **Step 2: Add line-scanner functions**

Add these functions below `maskFencedCodeBlocks(...)`:

```ts
export function extractFencedBlocks(section: string): ExtractedFenceBlock[] {
  const lines = section.split(/\r?\n/);
  const blocks: ExtractedFenceBlock[] = [];
  let open: { language: string | null; line_start: number; body: string[] } | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (!open) {
      const opener = line.match(fenceOpener);
      if (opener) {
        open = {
          language: normalizeFenceLanguage(opener[1] ?? null),
          line_start: index + 1,
          body: []
        };
      }
      continue;
    }

    if (fenceCloser.test(line)) {
      blocks.push(blockFromOpenFence(open, index + 1, true));
      open = null;
      continue;
    }

    open.body.push(line);
  }

  if (open) {
    blocks.push(blockFromOpenFence(open, lines.length, false));
  }

  return blocks;
}

export function extractCommandCandidates(section: string): ExtractedCommandCandidate[] {
  return extractFencedBlocks(section)
    .filter((block) => block.source === "command" && block.terminated)
    .flatMap((block) =>
      logicalCommandLines(block.content).map((command) => ({
        command,
        source: "shell_fence" as const,
        language: block.language,
        line_start: block.line_start + 1,
        line_end: Math.max(block.line_start + 1, block.line_end - 1)
      }))
    );
}

export function extractFencedCommands(section: string): string[] {
  const commands = extractCommandCandidates(section).map((candidate) => candidate.command);
  return [...new Set(commands)];
}

function normalizeFenceLanguage(language: string | null): string | null {
  const normalized = language?.trim().toLowerCase() ?? "";
  return normalized.length > 0 ? normalized : null;
}

function blockFromOpenFence(
  open: { language: string | null; line_start: number; body: string[] },
  lineEnd: number,
  terminated: boolean
): ExtractedFenceBlock {
  const source = open.language && shellFenceLanguages.has(open.language) ? "command" : "example";
  return {
    language: open.language,
    content: open.body.join("\n"),
    line_start: open.line_start,
    line_end: lineEnd,
    source,
    terminated
  };
}
```

- [ ] **Step 3: Wire structured fields into `extractSuperpowersPlan`**

Change the task mapping body to compute and return structured blocks:

```ts
const fencedBlocks = extractFencedBlocks(body);
const commandCandidates = extractCommandCandidates(body);
return {
  number,
  title,
  body,
  explicit_file_claims: explicit,
  prose_file_claims: prose,
  fenced_commands: [...new Set(commandCandidates.map((candidate) => candidate.command))],
  fenced_examples: fencedBlocks.filter((block) => block.source === "example"),
  command_candidates: commandCandidates
};
```

Remove the old `extractFencedCommands(...)` implementation so only the scanner-backed version remains.

- [ ] **Step 4: Run extraction tests and verify pass**

Run:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts
```

Expected: PASS. The full-plan fixture should no longer extract checklist or expected-result prose as commands.

- [ ] **Step 5: Commit scanner implementation**

Run:

```bash
git add packages/orchestrator/src/planAdapters/planClaimExtraction.ts packages/orchestrator/tests/planClaimExtraction.test.ts
git commit -m "fix: scan Superpowers plan fences before command extraction"
```

Expected: commit contains the scanner implementation and any necessary extraction test adjustments.

### Task 3: Add Command Roles For Diagnostics And Optional Environment Checks

**Files:**
- Modify: `packages/orchestrator/src/planAdapters/verificationPolicy.ts`
- Modify: `packages/orchestrator/tests/verificationPolicy.test.ts`

- [ ] **Step 1: Add failing command role tests**

Append to `packages/orchestrator/tests/verificationPolicy.test.ts`:

```ts
test("classifies read-only diagnostics as ignored evidence", () => {
  expect(classify("git status --short --branch")).toMatchObject({
    status: "ignored",
    reason: "diagnostic_readonly",
    role: "diagnostic_readonly"
  });
  expect(classify("git log --oneline -3")).toMatchObject({
    status: "ignored",
    reason: "diagnostic_readonly",
    role: "diagnostic_readonly"
  });
  expect(classify("git diff --stat")).toMatchObject({
    status: "ignored",
    reason: "diagnostic_readonly",
    role: "diagnostic_readonly"
  });
});

test("classifies optional Android environment probes as ignored evidence", () => {
  expect(classify("command -v adb || true")).toMatchObject({
    status: "ignored",
    reason: "optional_environment",
    role: "optional_environment"
  });
  expect(classify("adb devices")).toMatchObject({
    status: "ignored",
    reason: "optional_environment",
    role: "optional_environment"
  });
});

test("keeps unknown shell commands blocking", () => {
  expect(classify("custom-tool verify runtime")).toMatchObject({
    status: "unsafe",
    reason: "unknown",
    role: "unknown"
  });
});
```

- [ ] **Step 2: Run policy tests and verify failure**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts
```

Expected: FAIL because `role`, `diagnostic_readonly`, and `optional_environment` are not implemented.

- [ ] **Step 3: Add role types and fields**

In `packages/orchestrator/src/planAdapters/verificationPolicy.ts`, update the type definitions:

```ts
export type VerificationCommandRole =
  | "verification"
  | "implementation_only"
  | "diagnostic_readonly"
  | "optional_environment"
  | "unsafe"
  | "unknown";

export type VerificationClassificationReason =
  | "gradle_wrapper"
  | "gradle"
  | "node_test"
  | "package_script"
  | "known_runner"
  | "implementation_only"
  | "diagnostic_readonly"
  | "optional_environment"
  | "git_diff_check"
  | "destructive"
  | "workspace_escape"
  | "unknown";

export interface VerificationCommandSegment {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
  role: VerificationCommandRole;
}

export interface VerificationClassification {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
  role: VerificationCommandRole;
  segments: VerificationCommandSegment[];
}
```

- [ ] **Step 4: Update aggregate classification logic**

Replace `classifyVerificationCommand(...)` with:

```ts
export function classifyVerificationCommand(input: VerificationPolicyInput): VerificationClassification {
  const segments = commandSegments(input.command).map((segment, index) =>
    classifySegment(segment, index, input.workspace, input.catalog)
  );
  const blocking = segments.find((segment) => segment.role === "unsafe" || segment.role === "unknown");
  if (blocking) {
    return { command: input.command, status: "unsafe", reason: blocking.reason, role: blocking.role, segments };
  }

  const verification = [...segments].reverse().find((segment) => segment.role === "verification");
  const executableVerification = [...segments]
    .reverse()
    .find((segment) => segment.role === "verification" && !isWorkspaceChangeSegment(segment.command));
  const implementationOnly = segments.find((segment) => segment.role === "implementation_only");
  if (executableVerification && implementationOnly) {
    return { command: input.command, status: "unsafe", reason: "implementation_only", role: "unsafe", segments };
  }

  if (implementationOnly) {
    return { command: input.command, status: "ignored", reason: "implementation_only", role: "implementation_only", segments };
  }

  const optionalEnvironment = segments.find((segment) => segment.role === "optional_environment");
  if (optionalEnvironment) {
    return { command: input.command, status: "ignored", reason: "optional_environment", role: "optional_environment", segments };
  }

  const diagnostic = segments.find((segment) => segment.role === "diagnostic_readonly");
  if (diagnostic) {
    return { command: input.command, status: "ignored", reason: "diagnostic_readonly", role: "diagnostic_readonly", segments };
  }

  return {
    command: input.command,
    status: executableVerification ? "safe" : "ignored",
    reason: executableVerification?.reason ?? verification?.reason ?? "unknown",
    role: executableVerification ? "verification" : verification ? "verification" : "unknown",
    segments
  };
}
```

- [ ] **Step 5: Add role-aware segment helpers**

Add these helpers above `classifySegment(...)`:

```ts
function segment(
  command: string,
  status: VerificationClassificationStatus,
  reason: VerificationClassificationReason,
  role: VerificationCommandRole
): VerificationCommandSegment {
  return { command, status, reason, role };
}

function verification(command: string, reason: VerificationClassificationReason): VerificationCommandSegment {
  return segment(command, "safe", reason, "verification");
}

function ignored(command: string, reason: VerificationClassificationReason, role: VerificationCommandRole): VerificationCommandSegment {
  return segment(command, "ignored", reason, role);
}

function blocked(command: string, reason: VerificationClassificationReason, role: VerificationCommandRole = "unsafe"): VerificationCommandSegment {
  return segment(command, "unsafe", reason, role);
}
```

Then replace `classifySegment(...)` with:

```ts
function classifySegment(
  rawSegment: string,
  index: number,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): VerificationCommandSegment {
  const segmentText = rawSegment.trim();
  if (!segmentText) return ignored(segmentText, "unknown", "unknown");
  if (isOptionalEnvironmentCommand(segmentText)) return ignored(segmentText, "optional_environment", "optional_environment");
  if (destructivePattern.test(segmentText)) return blocked(segmentText, "destructive");
  if (/[|;`]/.test(segmentText) || /\s[12]?>/.test(segmentText)) {
    return blocked(segmentText, "unknown", "unknown");
  }
  if (segmentText.startsWith("cd ")) {
    if (index !== 0 || !cdStaysInsideWorkspace(segmentText, workspace)) {
      return blocked(segmentText, "workspace_escape");
    }
    return verification(segmentText, "known_runner");
  }
  if (isImplementationOnlyCommand(segmentText)) {
    return ignored(segmentText, "implementation_only", "implementation_only");
  }
  if (isDiagnosticReadOnlyCommand(segmentText)) {
    return ignored(segmentText, "diagnostic_readonly", "diagnostic_readonly");
  }
  if (segmentText.startsWith("./gradlew ")) return verification(segmentText, "gradle_wrapper");
  if (segmentText === "./gradlew") return verification(segmentText, "gradle_wrapper");
  if (segmentText.startsWith("gradle ")) return verification(segmentText, "gradle");
  if (segmentText.startsWith("node --test")) return verification(segmentText, "node_test");
  if (segmentText.startsWith("git diff --check")) return verification(segmentText, "git_diff_check");
  if (catalog && isCommandInCatalog(segmentText, catalog)) {
    return verification(segmentText, "package_script");
  }
  if (knownPrefixes.some((prefix) => segmentText === prefix.trim() || segmentText.startsWith(prefix))) {
    return verification(segmentText, "known_runner");
  }
  return blocked(segmentText, "unknown", "unknown");
}
```

Add the read-only and optional helpers near `isImplementationOnlyCommand(...)`:

```ts
function isDiagnosticReadOnlyCommand(segment: string): boolean {
  return /^git\s+status\b/.test(segment) ||
    /^git\s+log\b/.test(segment) ||
    /^git\s+diff\s+--stat\b/.test(segment) ||
    /^git\s+branch\b/.test(segment) ||
    /^git\s+rev-parse\b/.test(segment);
}

function isOptionalEnvironmentCommand(segment: string): boolean {
  return segment === "command -v adb || true" ||
    segment === "adb devices" ||
    segment === "adb devices -l";
}
```

- [ ] **Step 6: Run policy tests and verify pass**

Run:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts
```

Expected: PASS. Existing safe/unsafe tests and new role tests pass.

- [ ] **Step 7: Commit command role policy**

Run:

```bash
git add packages/orchestrator/src/planAdapters/verificationPolicy.ts packages/orchestrator/tests/verificationPolicy.test.ts
git commit -m "fix: classify diagnostic intake commands without blocking"
```

Expected: commit contains only verification policy and tests.

### Task 4: Prove Full-Plan Recovery And Integration Dispatch

**Files:**
- Modify: `packages/orchestrator/tests/intakeRecovery.test.ts`
- Modify: `tests/integration/waygent-android-intake-trust.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`

- [ ] **Step 1: Add full-plan recovery test**

Add imports to `packages/orchestrator/tests/intakeRecovery.test.ts` if not already present:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
```

Then append this test:

```ts
test("recovers full Superpowers plans with examples, checkpoints, diagnostics, and optional environment probes", () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-full-plan-recovery-"));
  writeFileSync(join(workspace, "package.json"), JSON.stringify({
    scripts: {
      "source-matching:fixtures:test": "node scripts/source-matching-fixtures-test.mjs",
      "source-matching:fixtures:runtime": "node scripts/source-matching-fixtures.mjs runtime"
    }
  }));

  const recovered = recoverWaygentPlanInput({
    markdown: readFileSync(join(import.meta.dir, "fixtures", "full_plan_intake_hardening.md"), "utf8"),
    path: "/tmp/full_plan_intake_hardening.md",
    workspace,
    spec_markdown: "# Full Plan Intake Hardening\n",
    spec_path: "/tmp/full_plan_intake_hardening_design.md"
  });

  expect(recovered.status).toBe("recovered");
  expect(recovered.report.can_start).toBe(true);
  expect(recovered.report.question).toBeNull();
  expect(recovered.report.findings.filter((finding) => finding.code === "unsafe_verification_command")).toEqual([]);
  expect(recovered.report.merged_task_status?.every((task) => task.verification_command_count > 0)).toBe(true);
  expect(recovered.normalized_plan.markdown).toContain("npm run source-matching:fixtures:test");
  expect(recovered.normalized_plan.markdown).toContain("./gradlew spotlessCheck --no-daemon");
  expect(recovered.normalized_plan.markdown).not.toContain("git status --short --branch");
  expect(recovered.normalized_plan.markdown).not.toContain("command -v adb || true");
});
```

- [ ] **Step 2: Run recovery test and verify failure if Task 2 or 3 is incomplete**

Run:

```bash
bun test packages/orchestrator/tests/intakeRecovery.test.ts
```

Expected: PASS after Tasks 2 and 3. If it fails, the failure should identify a remaining command extraction or command role gap.

- [ ] **Step 3: Add full-plan fake-provider integration test**

In `tests/integration/waygent-android-intake-trust.test.ts`, add these imports:

```ts
import { readFileSync } from "node:fs";
```

Add the two source-matching scripts to the fixture `package.json` setup:

```ts
scripts: {
  "source-matching:fixtures:test":
    "node --test scripts/source-matching-fixtures-test.mjs",
  "source-matching:fixtures:runtime":
    "node scripts/source-matching-fixtures.mjs runtime",
},
```

Create the runtime script used by the new fixture:

```ts
writeFileSync(
  join(workspace, "scripts", "source-matching-fixtures.mjs"),
  "console.log('runtime fixture available');\n",
);
```

Append this test to the existing `describe(...)` block:

```ts
test("loads full FixThis-style Superpowers plans instead of blocking at intake", async () => {
  const result = await runWaygent({
    root,
    workspace,
    run_id: "android_full_plan_intake_trust",
    profile: { provider: "fake", execution_mode: "multi-agent" },
    plan_preflight: "deterministic",
    spec: "# Spec\n\nFull plans with examples and diagnostics should recover.",
    plan: readFileSync(
      join(import.meta.dir, "..", "..", "packages", "orchestrator", "tests", "fixtures", "full_plan_intake_hardening.md"),
      "utf8"
    ),
  });

  expect(
    result.events.some((event) => event.event_type === "platform.intake_decision_required"),
  ).toBe(false);
  expect(
    result.events.some((event) => event.event_type === "platform.intake_extract_completed"),
  ).toBe(true);
  expect(
    result.events.some((event) => event.event_type === "runway.plan_loaded"),
  ).toBe(true);
});
```

- [ ] **Step 4: Add structured extraction fields to extract report**

In `packages/orchestrator/src/orchestrator.ts`, update the `extractReport` task mapping:

```ts
const extractReport = {
  tasks: extractedPlan.tasks.map((task) => ({
    number: task.number,
    title: task.title,
    explicit_file_claims: task.explicit_file_claims,
    prose_file_claims: task.prose_file_claims,
    fenced_commands: task.fenced_commands,
    fenced_examples: task.fenced_examples ?? [],
    command_candidates: task.command_candidates ?? [],
    verification: (task.command_candidates ?? task.fenced_commands.map((command) => ({
      command,
      source: "shell_fence" as const,
      language: null,
      line_start: 0,
      line_end: 0
    }))).map((candidate) => ({
      ...candidate,
      classification: classifyVerificationCommand({ command: candidate.command, workspace, catalog: extractionCatalog })
    }))
  }))
};
```

This preserves existing `fenced_commands` while making `extract-report.json` explain why examples and diagnostics were ignored.

- [ ] **Step 5: Run integration test**

Run:

```bash
bun test tests/integration/waygent-android-intake-trust.test.ts
```

Expected: PASS. Both reduced and full-plan Android intake tests reach `runway.plan_loaded`.

- [ ] **Step 6: Commit full-plan recovery coverage**

Run:

```bash
git add packages/orchestrator/tests/intakeRecovery.test.ts tests/integration/waygent-android-intake-trust.test.ts packages/orchestrator/src/orchestrator.ts
git commit -m "test: prove full Superpowers plans recover at intake"
```

Expected: commit includes full-plan recovery/integration coverage and extract-report evidence fields.

### Task 5: Expose Extract Report In Operator Evidence

**Files:**
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Modify: `packages/lens-projectors/tests/operatorDecision.test.ts`

- [ ] **Step 1: Add failing operator evidence expectations**

In `packages/lens-projectors/tests/operatorDecision.test.ts`, update the `surfaces intake decision blocker and recovery summary` fixture to include:

```ts
extract_report_ref: "artifacts/intake/extract-report.json"
```

Update the expected `projection.intake_recovery` artifact refs:

```ts
artifact_refs: [
  "artifacts/intake/recovery-report.json",
  "artifacts/intake/extract-report.json"
],
```

Update the evidence packet assertion:

```ts
expect(projection.evidence_packet.artifact_refs).toEqual(
  expect.arrayContaining([
    "artifacts/intake/recovery-report.json",
    "artifacts/intake/extract-report.json"
  ])
);
```

In `includes intake recovery summary for recovered runs without a blocker`, add:

```ts
extract_report_ref: "artifacts/intake/extract-report.json"
```

and update the expected refs:

```ts
artifact_refs: [
  "artifacts/intake/normalized-plan.md",
  "artifacts/intake/recovery-report.json",
  "artifacts/intake/extract-report.json"
],
```

- [ ] **Step 2: Run operator decision test and verify failure**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: FAIL because `intakeArtifactRefs(...)` does not include `extract_report_ref`.

- [ ] **Step 3: Implement extract report refs**

In `packages/lens-projectors/src/operatorDecision.ts`, update `intakeArtifactRefs(...)`:

```ts
function intakeArtifactRefs(intakeRecovery: WaygentIntakeRecovery | undefined): string[] {
  if (!intakeRecovery) return [];
  const refs: string[] = [];
  if (intakeRecovery.normalized_plan_ref) refs.push(intakeRecovery.normalized_plan_ref);
  if (intakeRecovery.recovery_report_ref) refs.push(intakeRecovery.recovery_report_ref);
  if (intakeRecovery.extract_report_ref) refs.push(intakeRecovery.extract_report_ref);
  return refs;
}
```

- [ ] **Step 4: Run operator decision tests and verify pass**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit operator evidence change**

Run:

```bash
git add packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/tests/operatorDecision.test.ts
git commit -m "fix: expose intake extract reports to operators"
```

Expected: commit contains only operator projection and tests.

### Task 6: Final Verification And Graph Refresh

**Files:**
- Read: `docs/superpowers/specs/2026-05-24-waygent-full-plan-intake-hardening-design.md`
- Read: `docs/superpowers/plans/2026-05-24-waygent-full-plan-intake-hardening.md`

- [ ] **Step 1: Run focused test suite**

Run:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/orchestrator/tests/intakeRepairPlanner.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/lens-projectors/tests/operatorDecision.test.ts \
  tests/integration/waygent-android-intake-trust.test.ts
```

Expected: PASS.

- [ ] **Step 2: Run strict typecheck and diff hygiene**

Run:

```bash
bun run typecheck
git diff --check
```

Expected: PASS.

- [ ] **Step 3: Run direct FixThis full-plan recovery smoke when checkout exists**

Run:

```bash
bun -e '
import { readFileSync } from "node:fs";
import { recoverWaygentPlanInput } from "./packages/orchestrator/src/intakeRecovery";
const planPath = "/Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-24-source-matching-runtime-trust-fixtures.md";
const specPath = "/Users/kws/source/android/FixThis/docs/superpowers/specs/2026-05-24-source-matching-runtime-trust-fixtures-design.md";
const recovered = recoverWaygentPlanInput({
  markdown: readFileSync(planPath, "utf8"),
  path: planPath,
  workspace: "/Users/kws/source/android/FixThis",
  spec_markdown: readFileSync(specPath, "utf8"),
  spec_path: specPath
});
console.log(JSON.stringify({
  status: recovered.status,
  can_start: recovered.report.can_start,
  task_count: recovered.normalized_plan.task_count,
  question: recovered.report.question,
  blocked_tasks: recovered.report.blocked_tasks ?? []
}, null, 2));
if (recovered.status !== "recovered" || !recovered.report.can_start) process.exit(1);
'
```

Expected: prints `status: "recovered"`, `can_start: true`, and exits 0.

- [ ] **Step 4: Refresh Graphify**

Run:

```bash
graphify update .
git status --short --branch
```

Expected: Graphify completes. Do not stage `graphify-out/` files.

- [ ] **Step 5: Commit final cleanup if any source changes remain**

If prior tasks left uncommitted source or test changes, run:

```bash
git add packages/orchestrator/src/planAdapters/planClaimExtraction.ts \
  packages/orchestrator/src/planAdapters/verificationPolicy.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/lens-projectors/src/operatorDecision.ts \
  packages/orchestrator/tests/fixtures/full_plan_intake_hardening.md \
  packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/lens-projectors/tests/operatorDecision.test.ts \
  tests/integration/waygent-android-intake-trust.test.ts
git commit -m "fix: harden Waygent full-plan intake recovery"
```

Expected: no source/test changes remain except ignored or unstaged `graphify-out/` updates.
