import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { ContractValidationError, validateContract } from "../src";

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(join(import.meta.dir, "../../../tests/fixtures/contracts", name), "utf8"));
}

describe("contract fixtures", () => {
  test("accepts valid event fixture", () => {
    expect(validateContract("agentlens.event.v3", fixture("valid-event.json"))).toBeTruthy();
  });

  test("rejects legacy namespace fixture", () => {
    expect(() => validateContract("agentlens.event.v3", fixture("invalid-legacy-namespace.json"))).toThrow(
      ContractValidationError
    );
  });

  test("accepts kernel request fixture", () => {
    expect(validateContract("kernel.execution_request.v1", fixture("valid-kernel-request.json"))).toBeTruthy();
  });

  test("accepts worker result fixture", () => {
    expect(validateContract("runway.worker_result.v1", fixture("valid-worker-result.json"))).toBeTruthy();
  });

  test("accepts lens runway projection fixture", () => {
    expect(validateContract("lens.runway_projection.v1", fixture("valid-lens-runway-projection.json"))).toBeTruthy();
  });

  test("accepts valid Waygent v2 runtime fixtures", () => {
    for (const fixtureName of [
      "valid-run-state-v2.json",
      "valid-task-packet.json",
      "valid-review-result.json",
      "valid-provider-attempt.json"
    ]) {
      const payload = fixture(fixtureName) as { schema: string };
      expect(() => validateContract(payload.schema, payload)).not.toThrow();
    }
  });
});
