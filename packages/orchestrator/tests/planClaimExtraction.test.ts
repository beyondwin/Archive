import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { extractSuperpowersPlan } from "../src/planAdapters/planClaimExtraction";

function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "fixtures", name), "utf8");
}

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

describe("Superpowers full-plan fence extraction", () => {
  test("extracts commands only from verification-intent shell fences", () => {
    const extracted = extractSuperpowersPlan(fixture("full_plan_intake_hardening.md"));

    expect(extracted.tasks.map((task) => task.number)).toEqual([1, 2, 3]);
    expect(extracted.tasks[0]?.fenced_commands).toEqual([
      "npm run source-matching:fixtures:test"
    ]);
    expect(extracted.tasks[1]?.fenced_commands).toEqual([
      './gradlew :fixthis-mcp:test --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon'
    ]);
    expect(extracted.tasks[2]?.fenced_commands).toEqual([
      "npm run source-matching:fixtures:test",
      './gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --tests "*TargetReliabilityCalculatorTest" --no-daemon',
      './gradlew :fixthis-mcp:test --tests "*TargetEvidenceServiceTest" --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon',
      "./gradlew spotlessCheck --no-daemon",
      "git diff --check",
      "graphify update .",
      "git status --short --branch",
      "command -v adb || true"
    ]);
  });

  test("keeps non-verification fences as examples and out of command candidates", () => {
    const extracted = extractSuperpowersPlan(fixture("full_plan_intake_hardening.md"));

    expect(extracted.tasks[0]?.fenced_examples?.map((block) => block.language)).toEqual([
      "javascript",
      "json",
      "bash"
    ]);
    expect(extracted.tasks[1]?.fenced_examples?.map((block) => block.language)).toEqual([
      "kotlin",
      "kotlin",
      "bash"
    ]);
    const commands = extracted.tasks.flatMap((task) => task.command_candidates ?? []).map((candidate) => candidate.command);
    expect(commands).not.toContain("- [ ] **Step 1: Write failing package and manifest tests**");
    expect(commands).not.toContain("Run:");
    expect(commands).not.toContain("Expected: PASS after the runner tests are implemented.");
    expect(commands.some((command) => command.includes("RuntimeTrustFixtureInput("))).toBe(false);
  });

  test("records command candidate source lines from shell fences", () => {
    const extracted = extractSuperpowersPlan(`
### Task 1: Line Evidence

\`\`\`text
Run:
\`\`\`

\`\`\`zsh
npm test \\
  -- --runInBand
\`\`\`
`);

    expect(extracted.tasks[0]?.fenced_examples?.[0]).toMatchObject({
      language: "text",
      line_start: 4,
      line_end: 6
    });
    expect(extracted.tasks[0]?.command_candidates).toEqual([{
      command: "npm test -- --runInBand",
      source: "shell_fence",
      language: "zsh",
      line_start: 9,
      line_end: 10
    }]);
  });

  test("only treats verification-intent shell fences as command candidates", () => {
    const extracted = extractSuperpowersPlan(`
### Task 1: Curated Task Context

**Files:**
- Modify: \`README.md\`

- [ ] **Step 1: Run verification**

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts
\`\`\`

- [ ] **Step 2: Commit checkpoint**

\`\`\`bash
git add README.md
git commit -m "docs"
\`\`\`

- [ ] **Step 3: Optional external smoke when checkout exists**

Run:

\`\`\`bash
bun -e 'console.log("external smoke")'
\`\`\`

Example:

\`\`\`shell
echo "illustrative only"
\`\`\`
`);

    expect(extracted.tasks[0]?.fenced_commands).toEqual([
      "bun test packages/orchestrator/tests/planClaimExtraction.test.ts"
    ]);
    expect(extracted.tasks[0]?.command_candidates?.map((candidate) => candidate.command)).toEqual([
      "bun test packages/orchestrator/tests/planClaimExtraction.test.ts"
    ]);
    expect(extracted.tasks[0]?.fenced_examples?.map((block) => block.language)).toEqual([
      "bash",
      "bash",
      "shell"
    ]);
  });
});
