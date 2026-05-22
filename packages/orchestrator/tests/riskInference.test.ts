import { describe, expect, test } from "bun:test";
import { inferRiskLevel } from "../src/planAdapters/riskInference";

describe("inferRiskLevel", () => {
  test("returns high on risk keyword in title", () => {
    const result = inferRiskLevel({
      title: "Apply database migration for users",
      body: "Adds a new column.",
      file_claims: [{ path: "packages/api/src/users.ts" }]
    });

    expect(result.risk).toBe("high");
    expect(result.reason).toBe("high-risk keyword match");
    expect(result.matched_signals).toContain("high_keyword");
  });

  test("returns high on sensitive path even without keyword in title", () => {
    const result = inferRiskLevel({
      title: "Touch up DB",
      body: "small change",
      file_claims: [{ path: "db/migrations/0001_add_users.sql" }]
    });

    expect(result.risk).toBe("high");
    expect(result.reason).toBe("high file_claim count or sensitive path");
    expect(result.matched_signals).toContain("high_sensitive_path");
  });

  test("returns high when file_claim count exceeds threshold", () => {
    const claims = Array.from({ length: 12 }, (_, i) => ({ path: `packages/foo/file_${i}.ts` }));
    const result = inferRiskLevel({
      title: "Bulk refactor",
      body: "rename helpers",
      file_claims: claims
    });

    expect(result.risk).toBe("high");
    expect(result.matched_signals).toContain("high_claim_count");
  });

  test("returns medium when claims span more than one top-level dir", () => {
    const result = inferRiskLevel({
      title: "Wire CLI and orchestrator",
      body: "small plumbing",
      file_claims: [
        { path: "apps/cli/src/index.ts" },
        { path: "packages/orchestrator/src/foo.ts" }
      ]
    });

    expect(result.risk).toBe("medium");
    expect(result.reason).toBe("cross-package claims");
    expect(result.matched_signals).toContain("cross_package");
  });

  test("returns low when single package and no risk signals", () => {
    const result = inferRiskLevel({
      title: "Tidy local helpers",
      body: "rename a function",
      file_claims: [{ path: "packages/orchestrator/src/foo.ts" }]
    });

    expect(result.risk).toBe("low");
    expect(result.reason).toBe("single-package, no risk keyword");
    expect(result.matched_signals).toContain("default_low");
  });

  test("matched_signals is always non-empty", () => {
    const result = inferRiskLevel({ title: "x", body: "", file_claims: [] });
    expect(result.matched_signals.length).toBeGreaterThan(0);
  });

  test("keyword detection is case-insensitive and word-bounded", () => {
    expect(
      inferRiskLevel({
        title: "Rotate Production Secret",
        body: "",
        file_claims: [{ path: "packages/secrets/src/index.ts" }]
      }).risk
    ).toBe("high");

    // "auth" appears as a word boundary trigger
    expect(
      inferRiskLevel({
        title: "Tweak authentication policy",
        body: "",
        file_claims: [{ path: "packages/api/src/index.ts" }]
      }).risk
    ).toBe("high");
  });
});
