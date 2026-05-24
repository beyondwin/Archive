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
});
