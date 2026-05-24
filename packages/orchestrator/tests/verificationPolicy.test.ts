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

  test("rejects command chains that mix implementation-only and verification segments", () => {
    expect(classify("git add README.md && git diff --check -- README.md")).toMatchObject({
      status: "unsafe",
      reason: "implementation_only"
    });
  });

  test("treats installs, write-mode maintenance, and graph updates as implementation-only", () => {
    for (const command of [
      "npm install",
      "bun install",
      "pnpm run format",
      "yarn run generate",
      "prettier --write src/index.ts",
      "graphify update ."
    ]) {
      expect(classify(command)).toMatchObject({
        status: "ignored",
        reason: "implementation_only"
      });
    }
  });

  test("does not treat a workspace cd plus implementation-only command as verification", () => {
    expect(classify("cd packages/orchestrator && graphify update .")).toMatchObject({
      status: "ignored",
      reason: "implementation_only"
    });
  });

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
});
