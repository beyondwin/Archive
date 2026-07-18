import { describe, expect, test } from "bun:test";
import { checkContract, formatContractIssues } from "./check-contract";

describe("checkContract", () => {
  test("accepts the repository contract", async () => {
    expect(await checkContract({ root: process.cwd() })).toEqual([]);
  });

  test("reports a missing active path", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: ["definitely-missing/"],
      requiredAgentFiles: [],
      trackedFiles: [],
    });
    expect(issues[0]?.code).toBe("missing_active_path");
  });

  test("rejects tracked local state", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: [],
      requiredAgentFiles: [],
      trackedFiles: [".waygent/runs/example.json"],
    });
    expect(issues.map((issue) => issue.code)).toContain("tracked_local_state");
  });

  test("formats issues as stable CLI lines", () => {
    expect(
      formatContractIssues([
        {
          code: "missing_active_path",
          path: "apps/missing",
          message: "required active path is missing",
        },
      ]),
    ).toBe("[missing_active_path] [apps/missing] required active path is missing");
  });
});
