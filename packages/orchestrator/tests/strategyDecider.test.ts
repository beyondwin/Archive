import { describe, expect, it } from "bun:test";
import { decideVerificationStrategy } from "../src/strategyDecider";

describe("decideVerificationStrategy", () => {
  it("returns isolated with reason=explicit_tag when verify_isolation=isolated", () => {
    const out = decideVerificationStrategy({ requested: "isolated", worktreeDiff: [] });
    expect(out).toEqual({ resolved: "isolated", reason: "explicit_tag" });
  });

  it("returns fast with reason=explicit_tag when verify_isolation=fast even with cross-package diff", () => {
    const out = decideVerificationStrategy({
      requested: "fast",
      worktreeDiff: [" M packages/a/src/x.ts", " M packages/b/src/y.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "explicit_tag" });
  });

  it("auto: returns fast with reason=diff_no_package_changes when no packages touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M apps/cli/src/index.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "diff_no_package_changes" });
  });

  it("auto: returns fast with reason=diff_single_package when exactly one packages/* is touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M packages/orchestrator/src/x.ts", " M packages/orchestrator/tests/x.test.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "diff_single_package" });
  });

  it("auto: returns isolated with reason=diff_cross_package when two or more packages/* touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M packages/a/src/x.ts", " M packages/b/src/y.ts"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_cross_package" });
  });

  it("auto: returns isolated with reason=diff_lockfile_touched when bun.lock changes", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M bun.lock"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_lockfile_touched" });
  });

  it("auto: isolates package-manager install verification commands", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M front/features/platform-admin/route/admin-health-route.tsx"],
      verificationCommands: ["pnpm install --frozen-lockfile --prefer-offline", "pnpm --dir front test -- --run"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "verification_dependency_install" });
  });

  it("auto: returns isolated when root package.json changes", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M package.json"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_lockfile_touched" });
  });

  it("treats absent verify_isolation as auto", () => {
    const out = decideVerificationStrategy({
      requested: undefined,
      worktreeDiff: [" M apps/cli/src/index.ts"]
    });
    expect(out.resolved).toBe("fast");
  });
});
