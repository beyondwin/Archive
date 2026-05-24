import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runWaygent } from "@waygent/orchestrator";

let workspace: string;
let root: string;

beforeEach(() => {
  workspace = mkdtempSync(join(tmpdir(), "waygent-android-intake-workspace-"));
  root = mkdtempSync(join(tmpdir(), "waygent-android-intake-root-"));

  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], {
    cwd: workspace,
  });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });

  mkdirSync(join(workspace, "scripts"), { recursive: true });
  writeFileSync(join(workspace, "README.md"), "android intake fixture\n");
  writeFileSync(
    join(workspace, "package.json"),
    `${JSON.stringify(
      {
        scripts: {
          "source-matching:fixtures:test":
            "node --test scripts/source-matching-fixtures-test.mjs",
        },
      },
      null,
      2,
    )}\n`,
  );
  writeFileSync(
    join(workspace, "scripts", "source-matching-fixtures-test.mjs"),
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n\ntest('fixture script is available', () => assert.equal(1, 1));\n",
  );
  writeFileSync(join(workspace, "gradlew"), "#!/usr/bin/env bash\nexit 0\n");
  chmodSync(join(workspace, "gradlew"), 0o755);

  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
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
`,
    });

    expect(
      result.events.some(
        (event) => event.event_type === "platform.intake_decision_required",
      ),
    ).toBe(false);
    expect(
      result.events.some(
        (event) => event.event_type === "platform.intake_extract_completed",
      ),
    ).toBe(true);
    expect(
      result.events.some((event) => event.event_type === "runway.plan_loaded"),
    ).toBe(true);
  });
});
