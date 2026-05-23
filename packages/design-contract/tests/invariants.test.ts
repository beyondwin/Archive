import { describe, expect, it } from "bun:test";
import {
  runInvariantsAgainstFileClaims,
  validatePolicyAcks
} from "../src/invariants";
import type { CrossPathInvariant, PolicyAck } from "../src/types";

const inv: CrossPathInvariant = {
  id: "INV-001",
  description: "x",
  paths_bound: ["package.json"],
  enforcement: { mode: "deterministic", check: { kind: "file_exists", path: "package.json" } },
  policy_ack_required: true,
  policy_ack_min_confidence: "verified"
};

describe("runInvariantsAgainstFileClaims", () => {
  it("runs invariants whose paths_bound intersect task file claims", async () => {
    const res = await runInvariantsAgainstFileClaims([inv], ["package.json:write"], process.cwd());
    expect(res).toHaveLength(1);
    expect(res[0]!.invariant_id).toBe("INV-001");
    expect(res[0]!.passed).toBe(true);
  });

  it("skips invariants with no overlap", async () => {
    const res = await runInvariantsAgainstFileClaims([inv], ["other.ts:write"], process.cwd());
    expect(res).toHaveLength(0);
  });
});

describe("validatePolicyAcks", () => {
  it("passes when ack exists with sufficient confidence", () => {
    const acks: PolicyAck[] = [{ invariant_id: "INV-001", confidence: "verified", evidence: "ran rg" }];
    const out = validatePolicyAcks([inv], acks);
    expect(out.missing).toHaveLength(0);
    expect(out.unverified).toHaveLength(0);
  });

  it("flags missing acks", () => {
    const out = validatePolicyAcks([inv], []);
    expect(out.missing).toEqual(["INV-001"]);
  });

  it("flags acks with insufficient confidence", () => {
    const acks: PolicyAck[] = [{ invariant_id: "INV-001", confidence: "best_effort", evidence: "guessed" }];
    const out = validatePolicyAcks([inv], acks);
    expect(out.unverified).toEqual(["INV-001"]);
  });
});
