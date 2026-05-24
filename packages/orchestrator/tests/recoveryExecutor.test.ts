import { describe, expect, test } from "bun:test";
import type { FailureClass } from "@waygent/contracts";
import { nextRecoveryAction, recoveryPolicy, selectResumeAction } from "../src/recoveryExecutor";

describe("Waygent recovery executor — selectResumeAction (legacy)", () => {
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

describe("nextRecoveryAction — D-10 policy matrix", () => {
  test("malformed_result retries with a strict prompt up to max_attempts", () => {
    const first = nextRecoveryAction("malformed_result", 0, { prior_summary: "expected json fence, got prose" });
    expect(first.action).toBe("retry_with_strict_prompt");
    expect(first.attempt_number).toBe(1);
    expect(first.max_attempts).toBe(2);
    expect(first.strict_prompt_suffix).toContain("PRIOR ATTEMPT (#0) FAILED.");
    expect(first.strict_prompt_suffix).toContain("failure_class: malformed_result");
    expect(first.strict_prompt_suffix).toContain("expected json fence, got prose");
    expect(first.strict_prompt_suffix).toContain("```json");

    const second = nextRecoveryAction("malformed_result", 1);
    expect(second.action).toBe("retry_with_strict_prompt");
    expect(second.attempt_number).toBe(2);

    const exhausted = nextRecoveryAction("malformed_result", 2);
    expect(exhausted.action).toBe("request_decision");
    expect(exhausted.attempt_number).toBe(3);
  });

  test("verification_failed retries with evidence up to 3 attempts", () => {
    expect(nextRecoveryAction("verification_failed", 0).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("verification_failed", 2).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("verification_failed", 3).action).toBe("request_decision");
  });

  test("timeout / permission_denied / merge_conflict request operator decision", () => {
    expect(nextRecoveryAction("timeout", 0).action).toBe("request_decision");
    expect(nextRecoveryAction("permission_denied", 0).action).toBe("request_decision");
    expect(nextRecoveryAction("merge_conflict", 0).action).toBe("request_decision");
  });

  test("cancelled / needs_plan_fix / needs_split / terminal_rejected halt and never retry", () => {
    for (const cls of ["cancelled", "needs_plan_fix", "needs_split", "terminal_rejected"] as const) {
      const decision = nextRecoveryAction(cls, 0);
      expect(decision.action).toBe("halt");
      expect(decision.max_attempts).toBe(0);
    }
  });

  test("adapter_crashed retries once with a strict prompt then escalates", () => {
    expect(nextRecoveryAction("adapter_crashed", 0).action).toBe("retry_with_strict_prompt");
    expect(nextRecoveryAction("adapter_crashed", 1).action).toBe("request_decision");
  });

  test("review_changes_requested retries with evidence; review_rejected escalates", () => {
    expect(nextRecoveryAction("review_changes_requested", 0).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("review_changes_requested", 2).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("review_changes_requested", 3).action).toBe("request_decision");
    expect(nextRecoveryAction("review_rejected", 0).action).toBe("request_decision");
  });

  test("missing_checkpoint / artifact_missing retry once with a strict prompt", () => {
    expect(nextRecoveryAction("missing_checkpoint", 0).action).toBe("retry_with_strict_prompt");
    expect(nextRecoveryAction("missing_checkpoint", 1).action).toBe("request_decision");
    expect(nextRecoveryAction("artifact_missing", 0).action).toBe("retry_with_strict_prompt");
    expect(nextRecoveryAction("artifact_missing", 1).action).toBe("request_decision");
  });

  test("context failures retry with bounded evidence", () => {
    expect(nextRecoveryAction("context_missing", 0).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("context_missing", 1).action).toBe("request_decision");
    expect(nextRecoveryAction("insufficient_context", 1).action).toBe("retry_with_evidence");
    expect(nextRecoveryAction("insufficient_context", 2).action).toBe("request_decision");
  });

  test("unknown failure_class defaults to request_decision", () => {
    const decision = nextRecoveryAction("not_a_known_class", 0);
    expect(decision.action).toBe("request_decision");
    expect(decision.attempt_number).toBe(1);
  });

  test("max_overrides apply per failure_class", () => {
    const overridden = nextRecoveryAction("malformed_result", 2, { max_overrides: { malformed_result: 3 } });
    expect(overridden.action).toBe("retry_with_strict_prompt");
    expect(overridden.max_attempts).toBe(3);
    expect(overridden.attempt_number).toBe(3);

    const stopped = nextRecoveryAction("verification_failed", 1, { max_overrides: { verification_failed: 1 } });
    expect(stopped.action).toBe("request_decision");
    expect(stopped.max_attempts).toBe(1);
  });

  test("policy matrix covers every FailureClass exactly once", () => {
    const allClasses: FailureClass[] = [
      "adapter_crashed",
      "timeout",
      "cancelled",
      "malformed_result",
      "diff_scope_failed",
      "review_changes_requested",
      "review_rejected",
      "verification_failed",
      "merge_conflict",
      "needs_rebase",
      "needs_plan_fix",
      "needs_split",
      "needs_infra_fix",
      "missing_checkpoint",
      "missing_resume_handler",
      "permission_denied",
      "service_unreachable",
      "dependency_missing",
      "environment_blocker",
      "flaky_unconfirmed",
      "command_not_found",
      "dependency_blocked",
      "file_claim_conflict",
      "dirty_source_checkout",
      "unsafe_apply",
      "state_drift",
      "artifact_missing",
      "context_missing",
      "insufficient_context",
      "stale_activity",
      "terminal_rejected"
    ];
    const policy = recoveryPolicy();
    for (const cls of allClasses) {
      expect(policy[cls]).toBeDefined();
      expect(policy[cls]?.action).toMatch(/^(retry_with_strict_prompt|retry_with_evidence|request_decision|halt)$/);
    }
    expect(Object.keys(policy).length).toBe(allClasses.length);
  });
});
