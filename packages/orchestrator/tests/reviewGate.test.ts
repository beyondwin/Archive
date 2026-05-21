import { describe, expect, test } from "bun:test";
import { shouldReviewTask } from "../src/reviewGate";

describe("Waygent review gate", () => {
  test("requires review for high risk, broad claims, and previous failures", () => {
    expect(shouldReviewTask({ risk: "high", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 0 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: ".", mode: "owned" }], previous_failure_count: 0 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 1 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 0 })).toBe(false);
  });
});
