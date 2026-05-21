import { describe, expect, test } from "bun:test";
import { selectResumeAction } from "../src/recoveryExecutor";

describe("Waygent recovery executor", () => {
  test("selects only unambiguous safe resume actions", () => {
    expect(selectResumeAction({ failure_class: "timeout", retry_count: 0, max_retries: 1, checkpoint_ref: null })).toEqual({
      action: "retry_same_provider",
      automatic: true
    });
    expect(selectResumeAction({ failure_class: "verification_failed", retry_count: 2, max_retries: 2, checkpoint_ref: "ckpt" })).toEqual({
      action: "human_decision",
      automatic: false
    });
    expect(selectResumeAction({ failure_class: "dirty_source_checkout", retry_count: 0, max_retries: 1, checkpoint_ref: "ckpt" })).toEqual({
      action: "clean_source_checkout",
      automatic: false
    });
    expect(selectResumeAction({ failure_class: "missing_checkpoint", retry_count: 0, max_retries: 1, checkpoint_ref: null })).toEqual({
      action: "retry_checkpoint_generation",
      automatic: true
    });
    expect(selectResumeAction({ failure_class: "artifact_missing", retry_count: 1, max_retries: 1, checkpoint_ref: null })).toEqual({
      action: "human_decision",
      automatic: false
    });
  });
});
