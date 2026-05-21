import { describe, expect, test } from "bun:test";
import { explicitApply, mergeCandidate } from "../src";

describe("merge and explicit apply gates", () => {
  test("merges only reviewed and verified candidates", () => {
    expect(mergeCandidate({ task_id: "task_demo", candidate_id: "candidate_demo", reviewed: true, verified: true }).merged).toBe(true);
    expect(mergeCandidate({ task_id: "task_demo", candidate_id: "candidate_bad", reviewed: true, verified: false }).failure_class).toBe("verification_failed");
  });

  test("explicit apply refuses dirty source checkout", () => {
    const merged = mergeCandidate({ task_id: "task_demo", candidate_id: "candidate_demo", reviewed: true, verified: true });
    expect(explicitApply(true, merged)?.blocked_actions).toContain("apply_dirty_source");
    expect(explicitApply(false, merged)).toBeNull();
  });
});
