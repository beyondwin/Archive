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
