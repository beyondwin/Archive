import { describe, expect, test } from "bun:test";
import { deriveRunId, planSlug, RUN_ID_COLLISION_MAX_RETRIES } from "../src/runIdDerivation";

describe("deriveRunId", () => {
  const now = new Date(Date.UTC(2026, 4, 22, 22, 18, 25)); // 2026-05-22 22:18:25 UTC

  test("uses 'run_<stamp>' when no plan path is provided", () => {
    expect(deriveRunId({ now })).toBe("run_20260522_221825");
  });

  test("derives slug from a dated plan filename", () => {
    expect(deriveRunId({ plan_path: "docs/superpowers/plans/2026-05-22-fixture-lab-full.md", now }))
      .toBe("fixture_lab_full_20260522_221825");
  });

  test("strips file extension and falls back to underscore separator", () => {
    expect(deriveRunId({ plan_path: "/tmp/My Plan!.md", now })).toBe("my_plan_20260522_221825");
  });

  test("appends a numeric suffix for collision retries", () => {
    expect(deriveRunId({ plan_path: "plan.md", now, suffix: 2 })).toBe("plan_20260522_221825_2");
  });

  test("ignores suffix value of zero", () => {
    expect(deriveRunId({ plan_path: "plan.md", now, suffix: 0 })).toBe("plan_20260522_221825");
  });

  test("exposes a positive collision retry cap", () => {
    expect(RUN_ID_COLLISION_MAX_RETRIES).toBeGreaterThan(0);
  });

  test("planSlug returns null for blank/missing input", () => {
    expect(planSlug(undefined)).toBeNull();
    expect(planSlug(null)).toBeNull();
    expect(planSlug("")).toBeNull();
  });
});
