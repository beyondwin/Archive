import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, mock, test } from "bun:test";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

mock.module("ajv", () => ({
  default: class Ajv {
    compile() {
      const validator = () => true;
      validator.errors = null;
      return validator;
    }
  },
}));
mock.module("ajv-formats", () => ({ default: () => {} }));

let runWaygent: typeof import("../../packages/orchestrator/src/orchestrator").runWaygent;
let workspace: string;
let root: string;

beforeAll(async () => {
  ({ runWaygent } = await import("../../packages/orchestrator/src/orchestrator"));
});

afterAll(() => {
  mock.restore();
});

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
          "source-matching:fixtures:runtime":
            "node scripts/source-matching-fixtures.mjs runtime",
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
  writeFileSync(
    join(workspace, "scripts", "source-matching-fixtures.mjs"),
    "process.exit(0);\n",
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

function fixture(name: string): string {
  return readFileSync(
    join(import.meta.dir, "..", "..", "packages", "orchestrator", "tests", "fixtures", name),
    "utf8",
  );
}

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

  test("runs the full-plan fixture through intake and records structured extraction evidence", async () => {
    const result = await runWaygent({
      root,
      workspace,
      run_id: "android_full_plan_intake_trust",
      profile: { provider: "fake", execution_mode: "multi-agent" },
      plan_preflight: "deterministic",
      spec: "# Spec\n\nRuntime source matching trust fixtures must keep default checks non-blocking.",
      plan: fixture("full_plan_intake_hardening.md"),
    });

    expect(
      result.events.some(
        (event) => event.event_type === "platform.intake_decision_required",
      ),
    ).toBe(false);
    expect(
      result.events.some((event) => event.event_type === "runway.plan_loaded"),
    ).toBe(true);

    const extractReport = JSON.parse(
      readFileSync(join(root, "android_full_plan_intake_trust", "artifacts", "intake", "extract-report.json"), "utf8"),
    ) as {
      tasks: Array<{
        fenced_examples?: Array<{ language: string | null; line_start: number; line_end: number }>;
        command_candidates?: Array<{
          command: string;
          source: string;
          line_start: number;
          line_end: number;
          classification?: { role: string; status: string; reason: string };
        }>;
      }>;
    };

    expect(extractReport.tasks).toHaveLength(3);
    expect(extractReport.tasks[0]?.fenced_examples?.map((block) => block.language)).toEqual([
      "javascript",
      "json",
      "bash",
    ]);
    expect(extractReport.tasks[1]?.fenced_examples?.map((block) => block.language)).toEqual([
      "kotlin",
      "kotlin",
      "bash",
    ]);

    const candidates = extractReport.tasks.flatMap((task) => task.command_candidates ?? []);
    expect(candidates.every((candidate) => candidate.source === "shell_fence")).toBe(true);
    expect(candidates.every((candidate) => candidate.line_start > 0 && candidate.line_end >= candidate.line_start)).toBe(true);
    expect(candidates.map((candidate) => candidate.command)).not.toContain("Run:");
    expect(candidates.map((candidate) => candidate.command)).not.toContain("Expected: PASS after the runner tests are implemented.");
    expect(candidates).toContainEqual(expect.objectContaining({
      command: "git status --short --branch",
      classification: expect.objectContaining({
        role: "diagnostic_readonly",
        status: "ignored",
      }),
    }));
    expect(candidates).toContainEqual(expect.objectContaining({
      command: "command -v adb || true",
      classification: expect.objectContaining({
        role: "optional_environment",
        status: "ignored",
      }),
    }));
  });
});
